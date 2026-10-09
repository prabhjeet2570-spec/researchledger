"""Local authoritative records. Capture is evidence of bytes, not execution."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import uuid


class LedgerError(ValueError):
    """A research record or operation is invalid."""


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, allow_nan=False, ensure_ascii=False)
    except (ValueError, TypeError) as exc:
        raise LedgerError("Records must contain finite JSON values") from exc


def now():
    return datetime.now(timezone.utc).isoformat()


def require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise LedgerError(f"{label} must be nonempty text")


class Project:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.directory = self.root / ".research"
        self.database = self.directory / "ledger.sqlite3"
        if not self.database.is_file():
            raise LedgerError("No research project here; run researchledger init")

    @classmethod
    def init(cls, root, name):
        require_text(name, "Project name")
        root = Path(root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        directory = root / ".research"
        # Never adopt or overwrite an existing store, even an incomplete one.
        try:
            directory.mkdir()
        except FileExistsError as exc:
            raise LedgerError(".research already exists; initialization refused") from exc
        try:
            with sqlite3.connect(directory / "ledger.sqlite3") as db:
                db.executescript("""
                    CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE records (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                """)
                db.executemany("INSERT INTO metadata VALUES (?, ?)", [
                    ("schema_version", "1"), ("name", name), ("created_at", now())
                ])
            (directory / "snapshots").mkdir()
        except Exception:
            shutil.rmtree(directory)
            raise
        return cls(root)

    @classmethod
    def open(cls, root="."):
        return cls(root)

    @contextmanager
    def connect(self):
        with sqlite3.connect(self.database) as db:
            version = db.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()
            if version != ("1",):
                raise LedgerError("Unsupported ledger schema")
            yield db

    def _source(self, name):
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise LedgerError("Sources must be project-relative paths without ..")
        if any(p in {".git", ".research"} or p.startswith(".env") for p in path.parts):
            raise LedgerError("Git, ledger, and dotenv files cannot be captured")
        resolved = (self.root / path).resolve()
        if not resolved.is_relative_to(self.root) or not resolved.is_file():
            raise LedgerError(f"Source is missing or outside the project: {name}")
        # A symlink into excluded storage must not bypass the path check.
        actual = resolved.relative_to(self.root)
        if any(p in {".git", ".research"} or p.startswith(".env") for p in actual.parts):
            raise LedgerError("Source resolves into excluded storage")
        return path.as_posix(), resolved

    def record(self, question, sources, config=None, gaps=None, parent=None,
               origin="manual"):
        """Record a question and captured files without claiming they executed."""
        require_text(question, "Question")
        if origin not in {"manual", "agent", "historical"}:
            raise LedgerError("Origin must be manual, agent, or historical")
        config = {} if config is None else config
        gaps = [] if gaps is None else gaps
        if not isinstance(config, dict) or not isinstance(gaps, list):
            raise LedgerError("Configuration must be an object; gaps must be a list")
        for gap in gaps:
            require_text(gap, "Provenance gap")
        canonical(config)
        if parent is not None:
            self.get(parent)
        files = [self._source(s) for s in sources]
        if not files:
            raise LedgerError("Capture requires at least one explicit source")
        if len({name for name, _ in files}) != len(files):
            raise LedgerError("Duplicate source paths")
        identifier = "exp-" + uuid.uuid4().hex
        staging = Path(tempfile.mkdtemp(prefix=".capture-", dir=self.directory))
        final = self.directory / "snapshots" / identifier
        try:
            manifest = []
            for name, source in files:
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                # Hash the bytes actually captured, not a later reread of the source.
                size = 0
                digest = hashlib.sha256()
                with source.open("rb") as reader, target.open("xb") as writer:
                    while chunk := reader.read(1024 * 1024):
                        writer.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                manifest.append({"path": name, "size_bytes": size,
                                 "sha256": digest.hexdigest()})
            payload = {"id": identifier, "created_at": now(), "question": question,
                       "origin": origin, "parent": parent, "config": config,
                       "execution_status": "not_observed", "gaps": gaps,
                       "sources": manifest}
            staging.rename(final)
            with self.connect() as db:
                db.execute("INSERT INTO records VALUES (?, ?)",
                           (identifier, canonical(payload)))
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            shutil.rmtree(final, ignore_errors=True)
            raise
        return payload

    def get(self, identifier):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM records WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise LedgerError(f"Unknown experiment: {identifier}")
        return json.loads(row[0])

    def records(self):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM records ORDER BY rowid").fetchall()
        return [json.loads(row[0]) for row in rows]

    def verify(self):
        """Verify saved source bytes. Does not check scientific correctness."""
        errors = []
        for record in self.records():
            for item in record["sources"]:
                path = self.directory / "snapshots" / record["id"] / item["path"]
                if not path.is_file():
                    errors.append({"id": record["id"], "path": item["path"],
                                   "problem": "missing"})
                    continue
                digest = hashlib.sha256()
                with path.open("rb") as reader:
                    while chunk := reader.read(1024 * 1024):
                        digest.update(chunk)
                if path.stat().st_size != item["size_bytes"] or digest.hexdigest() != item["sha256"]:
                    errors.append({"id": record["id"], "path": item["path"],
                                   "problem": "changed"})
        return errors
