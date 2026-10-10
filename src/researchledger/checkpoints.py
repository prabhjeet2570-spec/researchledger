"""Explicit immutable checkpoint revisions independent of mutable run status."""

import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from .executor import copy_bytes, relative_file
from .store import LedgerError, canonical, now


def list_checkpoints(project, run_id):
    project.get_run(run_id)
    with project.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoints'").fetchone():
            return []
        rows = db.execute("SELECT payload FROM checkpoints WHERE run_id=? ORDER BY rowid", (run_id,)).fetchall()
    return [json.loads(row[0]) for row in rows]


def save_checkpoint(project, run_id, path):
    run = project.get_run(run_id)
    name = relative_file(path)
    if name not in run.get("declared_checkpoints", []):
        raise LedgerError("Checkpoint must be explicitly declared by the run")
    if run["finished_at"] is not None or run["status"] not in {"launching", "running"}:
        raise LedgerError("Live checkpoint capture requires an active unresolved run")
    work = project.directory / "runs" / run_id / "work"
    source = work / name
    if any((work / Path(*Path(name).parts[:i])).is_symlink() for i in range(1, len(Path(name).parts) + 1)):
        raise LedgerError("Checkpoint symlinks cannot be captured")
    if not source.resolve().is_relative_to(work.resolve()) or not source.is_file():
        raise LedgerError("Checkpoint is missing or outside the run workspace")
    base = project.directory / "runs" / run_id / "checkpoints"
    base.mkdir(exist_ok=True)
    identifier = "cp-" + uuid.uuid4().hex
    stage = Path(tempfile.mkdtemp(prefix=".capture-", dir=base))
    final = base / identifier
    try:
        before = source.stat()
        captured = copy_bytes(source, stage / name)
        after = source.stat()
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in fields) or captured["size_bytes"] != before.st_size:
            raise LedgerError("Checkpoint changed during capture; write atomically and retry")
        with (stage / name).open("rb") as saved:
            os.fsync(saved.fileno())
        payload = {"id": identifier, "run_id": run_id, "record_id": run["record_id"],
                   "created_at": now(), "artifact": {"path": name, **captured},
                   "gaps": ["Checkpoint bytes were saved, but state completeness and scientific semantics are not verified"]}
        # A separate append-only row cannot be overwritten by the coordinator's
        # later run-status save. Recheck activity under the writer transaction.
        with project.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            latest = json.loads(db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()[0])
            if latest["finished_at"] is not None or latest["status"] not in {"launching", "running"}:
                raise LedgerError("Run finalized while checkpoint was being captured")
            db.execute("CREATE TABLE IF NOT EXISTS checkpoints (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, payload TEXT NOT NULL)")
            stage.rename(final)
            db.execute("INSERT INTO checkpoints VALUES (?, ?, ?)", (identifier, run_id, canonical(payload)))
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(final, ignore_errors=True)
        raise
    return payload
