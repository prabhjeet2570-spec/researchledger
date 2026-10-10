"""Synchronous execution adapters using prepared local workspaces and log streams."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import subprocess
from typing import BinaryIO, Mapping, Protocol

from .store import LedgerError, canonical, require_text


LOCAL_BACKEND_IDENTITY = {"name": "local-python", "version": "1"}


class ExecutionTimeout(TimeoutError):
    """The backend's wait deadline expired; the coordinator must stop execution."""


@dataclass(frozen=True)
class ExecutionRequest:
    run_id: str
    command: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str]
    stdout: BinaryIO
    stderr: BinaryIO


class RunningExecution(Protocol):
    execution_id: str
    pid: int | None

    @property
    def returncode(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def stop(self) -> None:
        """Stop execution and wait until it is safe to capture outputs."""
        ...


class ExecutionBackend(Protocol):
    def identity(self) -> dict:
        """Stable name/version and any configuration affecting compatibility."""
        ...

    def launch(self, request: ExecutionRequest) -> RunningExecution: ...


class LocalExecution:
    def __init__(self, process):
        self.process = process
        self.pid = process.pid
        self.execution_id = f"pid:{process.pid}"

    @property
    def returncode(self):
        return self.process.returncode

    def wait(self, timeout=None):
        try:
            return self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise ExecutionTimeout(str(exc)) from exc

    def stop(self):
        # Detached processes can escape; this is not resource isolation.
        if os.name == "posix":
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif self.process.poll() is None:
            self.process.kill()
        self.process.wait()


class LocalPythonBackend:
    def identity(self):
        return dict(LOCAL_BACKEND_IDENTITY)

    def launch(self, request):
        process = subprocess.Popen(request.command, cwd=request.cwd,
                                   env=dict(request.environment), stdout=request.stdout,
                                   stderr=request.stderr, stdin=subprocess.DEVNULL,
                                   start_new_session=os.name == "posix")
        return LocalExecution(process)


def resolve_backend(value):
    if isinstance(value, str):
        if value != "local-python":
            raise LedgerError(f"Unknown execution backend: {value}")
        value = LocalPythonBackend()
    if not callable(getattr(value, "identity", None)) or not callable(getattr(value, "launch", None)):
        raise LedgerError("Backend must implement identity() and launch(request)")
    identity = value.identity()
    if not isinstance(identity, dict):
        raise LedgerError("Backend identity must be a finite JSON object")
    require_text(identity.get("name"), "Backend name")
    require_text(identity.get("version"), "Backend version")
    return value, json.loads(canonical(identity))
