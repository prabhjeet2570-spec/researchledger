"""Research records backed by explicit source snapshots."""

from .store import Project, LedgerError
from .inspection import inspect_project

__all__ = ["Project", "LedgerError", "inspect_project"]
__version__ = "0.1.0.dev1"
