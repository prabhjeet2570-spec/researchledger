"""Read-only, bounded project inventory; never imports or executes project code."""

from collections import Counter, deque
from fnmatch import fnmatchcase
import os
from pathlib import Path
import subprocess

from .store import LedgerError


EXCLUDED_NAMES = {".git", ".research", ".venv", "venv", "__pycache__",
                  "node_modules", ".ipynb_checkpoints"}
EXTENSIONS = {
    "notebook": {".ipynb"},
    "source": {".py", ".r", ".jl", ".sh", ".cpp", ".c", ".h", ".rs"},
    "configuration": {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"},
    "documentation": {".md", ".rst", ".txt", ".tex"},
    "artifact_candidate": {".csv", ".tsv", ".npy", ".npz", ".pt", ".pth",
                           ".ckpt", ".h5", ".hdf5", ".png", ".pdf", ".log"},
}


def _git(root, arguments, input=None):
    return subprocess.run(["git", "-C", str(root), *arguments], input=input,
                          capture_output=True, timeout=5)


def inspect_project(root=".", *, max_entries=1000, exclude=()):
    """Inventory names and sizes without reading file contents or writing a ledger.

    The entry limit counts directories and exclusions too. Symlinks are never
    followed. Categories are extension heuristics, not verified provenance.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise LedgerError("Inspection requires an existing project directory")
    if type(max_entries) is not int or not 1 <= max_entries <= 100000:
        raise LedgerError("max_entries must be an integer from 1 to 100000")
    if isinstance(exclude, str):
        raise LedgerError("exclude must be a sequence of nonempty glob patterns")
    exclude = tuple(exclude)
    if any(not isinstance(p, str) or not p for p in exclude):
        raise LedgerError("exclude must be a sequence of nonempty glob patterns")

    warnings = []
    git = {"available": False, "head": None, "ignore_rules_applied": False}
    try:
        probe = _git(root, ["rev-parse", "--show-toplevel"])
        if probe.returncode == 0:
            git["available"] = True
            revision = _git(root, ["rev-parse", "--verify", "HEAD"])
            if revision.returncode == 0:
                git["head"] = revision.stdout.decode().strip()
            git["ignore_rules_applied"] = True
    except (OSError, subprocess.TimeoutExpired):
        warnings.append({"problem": "git_unavailable", "path": "."})

    files, skipped = [], []
    pending = deque([root])
    examined = 0
    truncated = False
    while pending and not truncated:
        directory = pending.popleft()
        entries = []
        try:
            with os.scandir(directory) as scan:
                for entry in scan:
                    if examined >= max_entries:
                        truncated = True
                        break
                    examined += 1
                    entries.append(entry)
        except OSError:
            warnings.append({"problem": "directory_unreadable",
                             "path": directory.relative_to(root).as_posix()})
            continue

        ignored = set()
        if git["ignore_rules_applied"] and entries:
            # NUL framing also handles spaces and newlines in file names.
            paths = [Path(e.path).relative_to(root).as_posix() for e in entries]
            try:
                result = _git(root, ["check-ignore", "--no-index", "--stdin", "-z"],
                              b"".join(os.fsencode(p) + b"\0" for p in paths))
                if result.returncode not in (0, 1):
                    raise OSError("Git ignore check failed")
                ignored = {os.fsdecode(p) for p in result.stdout.split(b"\0") if p}
            except (OSError, subprocess.TimeoutExpired):
                git["ignore_rules_applied"] = False
                warnings.append({"problem": "git_ignore_check_failed", "path": "."})

        for entry in sorted(entries, key=lambda e: e.name):
            relative = Path(entry.path).relative_to(root).as_posix()
            reason = None
            if entry.name in EXCLUDED_NAMES or entry.name.startswith(".env"):
                reason = "default_exclusion"
            elif any(fnmatchcase(relative, p) or fnmatchcase(entry.name, p)
                     for p in exclude):
                reason = "user_exclusion"
            elif relative in ignored:
                reason = "git_ignore"
            try:
                if reason is None and entry.is_symlink():
                    reason = "symlink_not_followed"
                if reason:
                    skipped.append({"path": relative, "reason": reason})
                elif entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    suffix = Path(entry.name).suffix.lower()
                    category = next((k for k, v in EXTENSIONS.items() if suffix in v),
                                    "other")
                    files.append({"path": relative, "category": category,
                                  "size_bytes": entry.stat(follow_symlinks=False).st_size,
                                  "classification_basis": "filename_extension"})
                else:
                    skipped.append({"path": relative, "reason": "not_regular_file"})
            except OSError:
                warnings.append({"problem": "entry_unreadable", "path": relative})

    files.sort(key=lambda item: item["path"])
    counts = dict(sorted(Counter(item["category"] for item in files).items()))
    return {
        "schema_version": 1, "root": str(root), "git": git,
        "complete": not truncated and not warnings,
        "truncated": truncated, "entries_examined": examined,
        "max_entries": max_entries, "counts": counts, "files": files,
        "skipped": sorted(skipped, key=lambda item: item["path"]),
        "warnings": warnings, "relationships": [],
        "capture_plan": {
            "status": "proposal_requires_review",
            "source_candidates": [f["path"] for f in files
                                  if f["category"] in {"source", "notebook"}],
            "configuration_candidates": [f["path"] for f in files
                                         if f["category"] == "configuration"],
            "artifact_candidates": [f["path"] for f in files
                                    if f["category"] == "artifact_candidate"],
            "required_review": [
                "Select relevant files; inspect contents before capturing or sharing.",
                "Identify executed code, configuration, dataset and checkpoint versions.",
                "Link historical results explicitly and record missing provenance.",
            ],
        },
        "limitations": [
            "File contents and notebook execution order have not been inspected.",
            "Categories do not establish scientific roles or result relationships.",
            "The inventory is a point-in-time view, not an atomic source snapshot.",
        ],
    }
