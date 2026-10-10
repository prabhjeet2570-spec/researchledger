"""Research records backed by explicit source snapshots."""

from .store import Project, LedgerError
from .inspection import inspect_project
from .backends import ExecutionBackend, ExecutionRequest, RunningExecution, ExecutionTimeout, LocalPythonBackend

__all__ = ["Project", "LedgerError", "inspect_project", "ExecutionBackend",
           "ExecutionRequest", "RunningExecution", "ExecutionTimeout", "LocalPythonBackend"]
__version__ = "0.1.0.dev1"
