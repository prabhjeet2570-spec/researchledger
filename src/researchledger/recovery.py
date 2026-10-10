"""Conservative local recovery without PID attachment or fabricated exit status."""

from contextlib import contextmanager
import os
import platform
from pathlib import Path
import uuid

from .backends import LOCAL_BACKEND_IDENTITY
from .executor import copy_bytes, hash_file, relative_file
from .store import LedgerError, canonical, now, require_text

try:
    import fcntl
except ImportError:
    fcntl = None


@contextmanager
def coordinator_guard(directory, *, nonblocking=False):
    if fcntl is None:
        if nonblocking:
            raise LedgerError("Local reconciliation requires POSIX coordinator locking")
        yield False
        return
    with (directory / "coordinator.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
        except BlockingIOError as exc:
            raise LedgerError("Run coordinator is still active") from exc
        try:
            yield True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def reconcile_run(project, run_id, reason):
    require_text(reason, "Reconciliation reason")
    run = project.get_run(run_id)
    if run["finished_at"] is not None:
        raise LedgerError("Run is already finalized")
    if not run.get("coordinator_lock"):
        raise LedgerError("Run predates coordinator locking; automatic reconciliation is unavailable")
    if canonical(run.get("backend")) != canonical(LOCAL_BACKEND_IDENTITY):
        raise LedgerError("Only the built-in local backend supports reconciliation")
    if run.get("execution_host") != platform.node():
        raise LedgerError("Execution host differs or is unknown; local process absence is insufficient")
    directory = project.directory / "runs" / run_id
    with coordinator_guard(directory, nonblocking=True):
        run = project.get_run(run_id)
        if run["finished_at"] is not None:
            raise LedgerError("Run finalized before reconciliation")
        # Probe only. A recycled live PID/group blocks recovery rather than
        # risking attachment, termination or duplicate execution.
        if run.get("pid") is None:
            raise LedgerError("Launch outcome is unknown; absence of a process cannot be established")
        try:
            os.killpg(run["pid"], 0)
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            raise LedgerError("Process group state cannot be established") from exc
        else:
            raise LedgerError("Recorded process group still exists; reconciliation refused")
        artifact_directory = "recovered-" + uuid.uuid4().hex
        artifacts, errors = [], []
        work = directory / "work"
        # Recovered files use a distinct directory, preserving any partial
        # finalization evidence instead of replacing it.
        for path in run["declared_outputs"]:
            name = relative_file(path)
            source = work / name
            try:
                if any((work / Path(*Path(name).parts[:i])).is_symlink() for i in range(1, len(Path(name).parts) + 1)):
                    raise LedgerError("Output symlinks cannot be recovered")
                if not source.resolve().is_relative_to(work.resolve()) or not source.is_file():
                    raise LedgerError("Recovered output is missing or outside the workspace")
                captured = copy_bytes(source, directory / artifact_directory / name)
                artifacts.append({"path": name, **captured})
            except (OSError, LedgerError) as exc:
                errors.append({"path": name, "problem": str(exc)})
        run.update(status="recovered_unknown", finished_at=now(), returncode=None,
                   artifacts=artifacts, output_errors=errors, artifact_directory=artifact_directory,
                   reconciliation={"reason": reason, "observed_at": now(),
                                   "observation": "coordinator lock available and recorded process group absent"})
        run["log_manifest"] = []
        for name in run["logs"].values():
            path = directory / name
            if path.is_file() and not path.is_symlink():
                run["log_manifest"].append({"path": name, **hash_file(path)})
        run["gaps"].append("Coordinator disappeared; exit outcome is unknown. Detached children and externally modified work files cannot be ruled out; recovered bytes are post-interruption observations")
        project._save_run(run)
    return run
