"""Synchronous local Python execution. Working copies are not a code sandbox."""

import hashlib
import json
from contextlib import contextmanager
import math
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import threading
import uuid

from .store import LedgerError, canonical, now, require_text


class RunInterrupted(KeyboardInterrupt):
    def __init__(self, signum):
        self.signum = signum
        super().__init__(f"Execution interrupted by signal {signum}")


@contextmanager
def interruption_signals():
    """Restore caller signal handlers after main-thread execution."""
    previous = {}
    if threading.current_thread() is threading.main_thread():
        def interrupt(signum, frame):
            raise RunInterrupted(signum)
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, interrupt)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def hash_file(path):
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as reader:
        while chunk := reader.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return {"size_bytes": size, "sha256": digest.hexdigest()}


def relative_file(name):
    require_text(name, "File path")
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or path == Path("."):
        raise LedgerError("Execution paths must be relative files without ..")
    if any(p in {".git", ".research"} or p.startswith(".env") for p in path.parts):
        raise LedgerError("Execution paths cannot use Git, ledger or dotenv storage")
    return path.as_posix()


def copy_bytes(source, target):
    """Copy and hash the same bytes rather than rereading a mutable source."""
    target.parent.mkdir(parents=True, exist_ok=True)
    digest, size = hashlib.sha256(), 0
    with source.open("rb") as reader, target.open("xb") as writer:
        while chunk := reader.read(1024 * 1024):
            writer.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return {"size_bytes": size, "sha256": digest.hexdigest()}


def stop_process(process):
    # Kill the launched process group on POSIX so ordinary children do not survive
    # timeout. Detached processes can escape: this is not resource isolation.
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        process.kill()
    process.wait()


def declared_context(value):
    """Validate caller declarations; they are not observed external state."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"inputs", "dependencies", "environment", "seed", "deterministic"}:
        raise LedgerError("Reuse context requires inputs, dependencies, environment, seed and deterministic")
    for field in ("inputs", "dependencies", "environment"):
        if not isinstance(value[field], dict):
            raise LedgerError(f"Reuse context {field} must map names to explicit identities")
        for key, identity in value[field].items():
            require_text(key, "Identity name")
            require_text(identity, "Identity value")
    if type(value["deterministic"]) is not bool:
        raise LedgerError("Reuse context deterministic must be a boolean")
    if value["seed"] is not None and type(value["seed"]) is not int:
        raise LedgerError("Reuse context seed must be an integer or null")
    return json.loads(canonical(value))


def execute(project, record_id, entrypoint, *, outputs=(), arguments=(), timeout=3600,
            checkpoints=(), resume_from=None, checkpoint=None, reuse_from=None,
            reuse_reason=None, reuse_context=None):
    record = project.get(record_id)
    reuse_context = declared_context(reuse_context)
    if reuse_from is None and reuse_reason is not None:
        raise LedgerError("Reuse reason requires a prior run")
    if reuse_from is not None:
        require_text(reuse_reason, "Reuse reason")
        if resume_from is not None or checkpoint is not None:
            raise LedgerError("Resume and result reuse are separate operations")
        if reuse_context is None or not reuse_context["deterministic"]:
            raise LedgerError("Reuse requires an explicit deterministic context")
    if isinstance(checkpoints, str):
        raise LedgerError("Checkpoints must be a sequence of output paths")
    checkpoints = [relative_file(p) for p in checkpoints]
    if len(set(checkpoints)) != len(checkpoints):
        raise LedgerError("Duplicate checkpoint paths")
    if (resume_from is None) != (checkpoint is None):
        raise LedgerError("Resume requires both a prior run and checkpoint path")
    entrypoint = relative_file(entrypoint)
    if isinstance(outputs, str) or isinstance(arguments, str):
        raise LedgerError("Outputs and arguments must be sequences, not strings")
    outputs = [relative_file(p) for p in outputs]
    if len(set(outputs)) != len(outputs):
        raise LedgerError("Duplicate output paths")
    outputs = list(dict.fromkeys([*outputs, *checkpoints]))
    arguments = list(arguments)
    if any(not isinstance(a, str) or "\0" in a for a in arguments):
        raise LedgerError("Arguments must be strings without NUL characters")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise LedgerError("Timeout must be finite and positive")
    sources = {relative_file(item["path"]): item for item in record["sources"]}
    if entrypoint not in sources or Path(entrypoint).suffix != ".py":
        raise LedgerError("Entrypoint must be a captured Python source file")
    reserved = ".researchledger-config.json"
    resume_directory = ".researchledger-resume"
    if any(Path(p).parts[0] == resume_directory for p in [*sources, *outputs]):
        raise LedgerError("Resume input directory is reserved")
    if any(Path(p).parts[0] == reserved for p in [*sources, *outputs]):
        raise LedgerError("Generated configuration path is reserved")
    if len(set(outputs)) != len(outputs) or set(outputs) & sources.keys():
        raise LedgerError("Output paths must be unique and distinct from captured sources")

    environment_identity = {"python_executable": sys.executable,
                            "python_version": sys.version, "platform": platform.platform()}
    resume = None
    if resume_from is not None:
        prior = project.get_run(resume_from)
        checkpoint = relative_file(checkpoint)
        if prior["finished_at"] is None:
            raise LedgerError("Cannot resume from an unresolved run")
        if (prior["record_id"] != record_id or prior["entrypoint"] != entrypoint
                or prior["arguments"] != arguments or prior["config"] != record["config"]
                or prior["source_manifest"] != record["sources"]
                or prior["environment"] != environment_identity):
            raise LedgerError("Resume requires identical record, entrypoint, arguments and interpreter/platform")
        if checkpoint not in prior.get("declared_checkpoints", []):
            raise LedgerError("Checkpoint was not explicitly declared by the prior run")
        saved = next((a for a in prior["artifacts"] if a["path"] == checkpoint), None)
        if saved is None:
            raise LedgerError("Prior checkpoint was not captured")
        resume = {"run_id": resume_from, "checkpoint": dict(saved)}

    reused = None
    if reuse_from is not None:
        reused = project.get_run(reuse_from)
        if reused["status"] != "succeeded" or reused["finished_at"] is None:
            raise LedgerError("Reuse requires a finalized successful execution")
        if reused.get("resume_from") is not None:
            raise LedgerError("Resumed execution reuse requires checkpoint identity support; use fresh execution")
        if (reused["record_id"] != record_id or reused["entrypoint"] != entrypoint
                or reused["arguments"] != arguments or canonical(reused["config"]) != canonical(record["config"])
                or reused["source_manifest"] != record["sources"]
                or reused["environment"] != environment_identity
                or reused["declared_outputs"] != outputs
                or reused.get("declared_checkpoints", []) != checkpoints
                or canonical(reused.get("reuse_context")) != canonical(reuse_context)):
            raise LedgerError("Reuse requires identical snapshot, arguments, outputs, runtime and declared context")
        if not outputs or reused["output_errors"] or {a["path"] for a in reused["artifacts"]} != set(outputs):
            raise LedgerError("Reuse requires complete declared output evidence")

    identifier = "run-" + uuid.uuid4().hex
    directory = project.directory / "runs" / identifier
    work = directory / "work"
    work.mkdir(parents=True)
    payload = {
        "id": identifier, "record_id": record_id, "created_at": now(),
        "status": "preparing", "started_at": None, "finished_at": None,
        "entrypoint": entrypoint, "arguments": arguments, "timeout_seconds": timeout,
        "config": record["config"], "source_manifest": record["sources"],
        "declared_outputs": outputs, "declared_checkpoints": checkpoints,
        "resume_from": resume, "input_manifest": [], "artifacts": [], "output_errors": [],
        "execution_kind": "reused" if reused is not None else "executed",
        "reused_from": reuse_from, "reuse_reason": reuse_reason, "reuse_context": reuse_context,
        "returncode": None, "pid": None, "error": None, "interruption_signal": None,
        "environment": environment_identity,
        "logs": {"stdout": "stdout.log", "stderr": "stderr.log"},
        "gaps": ["Dependencies and external inputs are not snapshotted",
                 "Process exit and captured outputs do not establish scientific correctness",
                 "Inherited environment can affect execution; environment variables are not recorded"],
    }
    project._save_run(payload)
    process = None
    try:
        snapshot = project.directory / "snapshots" / record_id
        for name, item in sources.items():
            original = snapshot / name
            if original.is_symlink() or not original.resolve().is_relative_to(snapshot.resolve()):
                raise LedgerError("Captured source resolves outside its snapshot")
            copied = copy_bytes(original, work / name)
            if copied["size_bytes"] != item["size_bytes"] or copied["sha256"] != item["sha256"]:
                raise LedgerError(f"Captured source failed hash verification: {name}")
        if reused is not None:
            base = project.directory / "runs" / reused["id"] / "artifacts"
            for item in reused["artifacts"]:
                name = relative_file(item["path"])
                original = base / name
                if any((base / Path(*Path(name).parts[:i])).is_symlink()
                       for i in range(1, len(Path(name).parts) + 1)):
                    raise LedgerError("Reused output symlinks cannot be copied")
                if not original.resolve().is_relative_to(base.resolve()) or not original.is_file():
                    raise LedgerError("Reused output is missing or outside saved storage")
                saved = copy_bytes(original, directory / "artifacts" / name)
                if any(saved[k] != item[k] for k in saved):
                    (directory / "artifacts" / name).unlink()
                    raise LedgerError("Reused output failed hash verification")
                payload["artifacts"].append({"path": name, **saved})
            payload.update(status="reused", logs={}, log_manifest=[], finished_at=now())
            payload["gaps"].extend([
                "No process was launched; reused evidence is not independent replication",
                "External input/dependency/environment identities and determinism are caller declarations, not verified observations",
            ])
            project._save_run(payload)
            return payload
        (work / reserved).write_text(canonical(record["config"]) + "\n", encoding="utf-8")
        environment = os.environ.copy()
        environment.pop("RESEARCHLEDGER_RESUME", None)
        if resume is not None:
            name = resume["checkpoint"]["path"]
            base = project.directory / "runs" / resume["run_id"] / "artifacts"
            original = base / name
            if any((base / Path(*Path(name).parts[:i])).is_symlink()
                   for i in range(1, len(Path(name).parts) + 1)):
                raise LedgerError("Checkpoint symlinks cannot be resumed")
            if not original.resolve().is_relative_to(base.resolve()):
                raise LedgerError("Checkpoint resolves outside saved storage")
            captured = copy_bytes(original, directory / "inputs" / name)
            if any(captured[k] != resume["checkpoint"][k] for k in captured):
                raise LedgerError("Checkpoint failed hash verification")
            payload["input_manifest"].append({"path": name, **captured})
            target = work / resume_directory / name
            copy_bytes(directory / "inputs" / name, target)
            environment["RESEARCHLEDGER_RESUME"] = str(target)
            payload["gaps"].append("Resume checks saved bytes and basic runtime identity; external state and checkpoint semantics are not verified")
        environment["RESEARCHLEDGER_CONFIG"] = str(work / reserved)
        environment["RESEARCHLEDGER_RUN_ID"] = identifier
        command = [sys.executable, "-u", entrypoint, *arguments]
        payload["command"] = command
        with interruption_signals(), (directory / "stdout.log").open("xb") as stdout, (directory / "stderr.log").open("xb") as stderr:
            payload["status"] = "launching"
            project._save_run(payload)
            process = subprocess.Popen(command, cwd=work, env=environment,
                                       stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL,
                                       start_new_session=os.name == "posix")
            payload.update(status="running", pid=process.pid, started_at=now())
            project._save_run(payload)
            try:
                code = process.wait(timeout=timeout)
                payload["status"] = "succeeded" if code == 0 else "failed"
            except subprocess.TimeoutExpired:
                stop_process(process)
                payload["status"] = "timed_out"
            except KeyboardInterrupt as exc:
                stop_process(process)
                payload["status"] = "interrupted"
                payload["interruption_signal"] = getattr(exc, "signum", signal.SIGINT)
            payload["returncode"] = process.returncode
    except (Exception, KeyboardInterrupt) as exc:
        if process is not None:
            stop_process(process)
        payload["status"] = ("interrupted" if isinstance(exc, KeyboardInterrupt) else
                             "preparation_failed" if process is None else "executor_failed")
        payload["error"] = str(exc)
        if isinstance(exc, KeyboardInterrupt):
            payload["interruption_signal"] = getattr(exc, "signum", signal.SIGINT)
        if process is not None:
            payload["returncode"] = process.returncode

    # Preserve available declared outputs even after failure or timeout.
    for name in ([] if reused is not None else outputs):
        source = work / name
        try:
            if any((work / Path(*Path(name).parts[:i])).is_symlink()
                   for i in range(1, len(Path(name).parts) + 1)):
                raise LedgerError("Output symlinks cannot be captured")
            if not source.resolve().is_relative_to(work.resolve()) or not source.is_file():
                raise LedgerError("Declared output is missing or not a regular file")
            captured = copy_bytes(source, directory / "artifacts" / name)
            payload["artifacts"].append({"path": name, **captured})
        except (OSError, LedgerError) as exc:
            payload["output_errors"].append({"path": name, "problem": str(exc)})
    if payload["status"] == "succeeded" and payload["output_errors"]:
        payload["status"] = "outputs_incomplete"
    payload["log_manifest"] = []
    for name in payload["logs"].values():
        path = directory / name
        if path.is_file():
            payload["log_manifest"].append({"path": name, **hash_file(path)})
    payload["finished_at"] = now()
    project._save_run(payload)
    return payload
