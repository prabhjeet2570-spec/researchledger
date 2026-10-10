"""Portable evidence bundles from persisted records and verified saved bytes."""

import csv
import os
from pathlib import Path
import re
import tempfile
import zipfile

from .executor import copy_bytes, hash_file, relative_file
from .store import LedgerError, canonical, now


def export_bundle(project, output, record_ids=None):
    output = Path(output).absolute()
    if output.resolve().is_relative_to(project.directory.resolve()):
        raise LedgerError("Export destination must be outside ledger storage")
    if os.path.lexists(output):
        raise LedgerError("Export destination already exists; overwriting refused")
    if isinstance(record_ids, str):
        raise LedgerError("Record selection must be a sequence of IDs")
    selected = project.records() if record_ids is None else [project.get(i) for i in record_ids]
    if not selected:
        raise LedgerError("Export requires at least one experiment record")
    records = {record["id"]: record for record in selected}
    def include_ancestors():
        pending = list(records.values())
        while pending:
            parent = pending.pop().get("parent")
            if parent and parent not in records:
                records[parent] = project.get(parent)
                pending.append(records[parent])

    include_ancestors()
    all_notes = project.research_records()
    threads = {note["thread_id"] for note in all_notes
               if any(ref["record_id"] in records for ref in note["evidence"])}
    notes = [note for note in all_notes if record_ids is None or note["thread_id"] in threads]
    # Include whole selected revision threads and their evidence to avoid dangling links.
    for note in notes:
        for reference in note["evidence"]:
            identifier = reference["record_id"]
            if identifier not in records:
                records[identifier] = project.get(identifier)
    include_ancestors()
    records = sorted(records.values(), key=lambda record: record["id"])
    runs = [run for run in project.runs() if run["record_id"] in {r["id"] for r in records}]
    for item in [*records, *runs]:
        if not re.fullmatch(r"(?:exp|run)-[0-9a-f]{32}", item["id"]):
            raise LedgerError("Invalid stored record/run identifier")

    output.parent.mkdir(parents=True, exist_ok=True)
    issues, files = [], []
    with tempfile.TemporaryDirectory(prefix=".researchledger-export-", dir=output.parent) as temporary:
        stage = Path(temporary) / "bundle"
        stage.mkdir()

        def capture(identifier, item, base, prefix):
            target = None
            try:
                name = relative_file(item["path"])
                source = base / name
                if any((base / Path(*Path(name).parts[:i])).is_symlink()
                       for i in range(1, len(Path(name).parts) + 1)):
                    raise LedgerError("Saved evidence symlinks cannot be exported")
                if not source.resolve().is_relative_to(base.resolve()) or not source.is_file():
                    raise LedgerError("Saved evidence is missing or not a regular file")
                destination = prefix / name
                target = stage / destination
                saved = copy_bytes(source, target)
                if any(saved[key] != item[key] for key in saved):
                    raise LedgerError("Saved evidence differs from its capture hash")
                files.append({"path": destination.as_posix(), **saved})
            except (OSError, LedgerError) as exc:
                if target is not None:
                    target.unlink(missing_ok=True)
                issues.append({"id": identifier, "path": item["path"], "problem": str(exc)})

        for record in records:
            base = project.directory / "snapshots" / record["id"]
            for item in record["sources"] + record.get("artifacts", []):
                capture(record["id"], item, base, Path("snapshots") / record["id"])
        for run in runs:
            if run["finished_at"] is None:
                issues.append({"id": run["id"], "path": None, "problem": "run_not_finalized; live files omitted"})
                continue
            base = project.directory / "runs" / run["id"]
            if "log_manifest" not in run:
                issues.append({"id": run["id"], "path": None, "problem": "log_manifest_unavailable; unverified logs omitted"})
            for item in run.get("log_manifest", []):
                capture(run["id"], item, base, Path("runs") / run["id"])
            for item in run["artifacts"]:
                capture(run["id"], item, base / "artifacts", Path("runs") / run["id"] / "artifacts")

        for name, value in [("records.json", records), ("runs.json", runs), ("research_records.json", notes)]:
            (stage / name).write_text(canonical(value) + "\n", encoding="utf-8")
        with (stage / "evidence.csv").open("w", newline="", encoding="utf-8") as table:
            writer = csv.writer(table)
            writer.writerow(["record_id", "question", "origin", "run_id", "run_status", "gaps_json"])
            for record in records:
                attempts = [r for r in runs if r["record_id"] == record["id"]]
                for run in attempts or [None]:
                    writer.writerow([record["id"], record["question"], record["origin"],
                                     run["id"] if run else "", run["status"] if run else "not_observed",
                                     canonical(record["gaps"] + (run["gaps"] if run else []))])
        for name in ["records.json", "runs.json", "research_records.json", "evidence.csv"]:
            files.append({"path": name, **hash_file(stage / name)})
        manifest = {
            "schema_version": 2, "exported_at": now(),
            "record_ids": [r["id"] for r in records], "run_ids": [r["id"] for r in runs],
            "research_record_ids": [note["id"] for note in notes],
            "files": sorted(files, key=lambda item: item["path"]),
            "integrity_ok": not issues, "issues": issues,
            "limitations": [
                "Hashes check bytes, not scientific correctness or authenticity.",
                "Historical claims and research judgments remain unverified declarations.",
                "Dependencies, external datasets/checkpoints and working run directories are not bundled.",
                "Records preserve declared gaps; integrity_ok does not mean provenance is complete.",
                "This is an evidence archive, not a restorable ledger or runnable environment.",
                "Review all contents before sharing; no secret redaction is performed.",
            ],
        }
        (stage / "manifest.json").write_text(canonical(manifest) + "\n", encoding="utf-8")
        archive = Path(temporary) / "evidence.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    bundle.write(path, path.relative_to(stage).as_posix())
        # Publish without replacing a file created by someone else during export.
        try:
            os.link(archive, output)
        except FileExistsError as exc:
            raise LedgerError("Export destination appeared during export; overwriting refused") from exc
    return {"output": str(output), "integrity_ok": not issues, "issues": issues,
            "records_exported": len(records), "runs_exported": len(runs),
            "research_records_exported": len(notes)}
