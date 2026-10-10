"""Synchronous local Python execution. Working copies are not a code sandbox."""

import hashlib
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


def execute(project, record_id, entrypoint, *, outputs=(), arguments=(), timeout=3600):
    record = project.get(record_id)
    entrypoint = relative_file(entrypoint)
    if isinstance(outputs, str) or isinstance(arguments, str):
        raise LedgerError("Outputs and arguments must be sequences, not strings")
    outputs = [relative_file(p) for p in outputs]
    arguments = list(arguments)
    if any(not isinstance(a, str) or "\0" in a for a in arguments):
        raise LedgerError("Arguments must be strings without NUL characters")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise LedgerError("Timeout must be finite and positive")
    sources = {relative_file(item["path"]): item for item in record["sources"]}
    if entrypoint not in sources or Path(entrypoint).suffix != ".py":
        raise LedgerError("Entrypoint must be a captured Python source file")
    reserved = ".researchledger-config.json"
    if any(Path(p).parts[0] == reserved for p in [*sources, *outputs]):
        raise LedgerError("Generated configuration path is reserved")
    if len(set(outputs)) != len(outputs) or set(outputs) & sources.keys():
        raise LedgerError("Output paths must be unique and distinct from captured sources")

    identifier = "run-" + uuid.uuid4().hex
    directory = project.directory / "runs" / identifier
    work = directory / "work"
    work.mkdir(parents=True)
    payload = {
        "id": identifier, "record_id": record_id, "created_at": now(),
        "status": "preparing", "started_at": None, "finished_at": None,
        "entrypoint": entrypoint, "arguments": arguments, "timeout_seconds": timeout,
        "config": record["config"], "source_manifest": record["sources"],
        "declared_outputs": outputs, "artifacts": [], "output_errors": [],
        "returncode": None, "pid": None, "error": None, "interruption_signal": None,
        "environment": {"python_executable": sys.executable,
                        "python_version": sys.version, "platform": platform.platform()},
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
        (work / reserved).write_text(canonical(record["config"]) + "\n", encoding="utf-8")
        environment = os.environ.copy()
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
    for name in outputs:
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
