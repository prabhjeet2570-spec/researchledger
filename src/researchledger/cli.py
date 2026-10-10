"""Machine-readable CLI sharing the Python SDK's operations."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from . import __version__
from .store import LedgerError, Project, canonical
from .inspection import inspect_project


def main(argv=None):
    parser = argparse.ArgumentParser(description="Capture research code and provenance")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--project", default=".", help="Research directory (default: current)")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Read-only directory inventory and capture proposal")
    inspect.add_argument("--max-entries", type=int, default=1000)
    inspect.add_argument("--exclude", action="append", default=[], help="Relative-path or name glob")
    init = commands.add_parser("init", help="Initialize a local research ledger")
    init.add_argument("--name", required=True)
    record = commands.add_parser("record", help="Snapshot explicit files; does not execute them")
    record.add_argument("--question", required=True)
    record.add_argument("--source", action="append", required=True)
    record.add_argument("--input", action="append", default=[], help="Explicit project-relative data file to snapshot")
    record.add_argument("--config", type=Path, help="JSON configuration file")
    record.add_argument("--gap", action="append", default=[])
    record.add_argument("--parent")
    record.add_argument("--origin", choices=["manual", "agent", "historical"], default="manual")
    history = commands.add_parser("import", help="Capture explicitly mapped historical evidence")
    history.add_argument("--manifest", type=Path, required=True, help="Historical evidence JSON")
    run = commands.add_parser("run", help="Execute a captured Python script locally")
    run.add_argument("id", help="Saved experiment record ID")
    run.add_argument("--backend", default="local-python", choices=["local-python"], help="Execution adapter")
    run.add_argument("--entrypoint", required=True)
    run.add_argument("--output", action="append", default=[], help="Expected file relative to run workspace")
    run.add_argument("--arg", action="append", default=[], help="Script argument; use --arg=-flag")
    run.add_argument("--dependency", action="append", default=[], help="Observe an installed distribution version")
    run.add_argument("--timeout", type=float, default=3600)
    run.add_argument("--checkpoint-output", action="append", default=[], help="Explicit resumable output file")
    run.add_argument("--resume-from", help="Finalized prior run ID")
    run.add_argument("--checkpoint", help="Saved checkpoint output path from prior run")
    run.add_argument("--reuse-from", help="Explicit successful prior run; launches no process")
    run.add_argument("--reuse-reason", help="Why saved evidence is suitable for this request")
    run.add_argument("--reuse-context", type=Path, help="JSON identities, seed and determinism declaration")
    run.add_argument("--checkpoint-revision", help="Explicit saved cp-ID to resume")
    checkpoint = commands.add_parser("checkpoint", help="Save a declared live checkpoint revision")
    checkpoint.add_argument("id", help="Active run ID")
    checkpoint.add_argument("--path", required=True)
    checkpoints = commands.add_parser("checkpoints", help="List immutable checkpoint revisions")
    checkpoints.add_argument("id", help="Run ID")
    runs = commands.add_parser("runs", help="List local execution attempts")
    runs.add_argument("--record")
    show_run = commands.add_parser("show-run", help="Read a persisted execution attempt")
    show_run.add_argument("id")
    export = commands.add_parser("export", help="Bundle saved records and evidence into a ZIP")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--record", action="append", help="Select records (ancestors included)")
    note = commands.add_parser("note", help="Append a decision, interpretation or revision")
    note.add_argument("--manifest", type=Path, required=True)
    commands.add_parser("notes", help="List all research record versions")
    show_note = commands.add_parser("show-note", help="Read an immutable research record version")
    show_note.add_argument("id")
    commands.add_parser("list", help="List saved experiment records as JSON")
    show = commands.add_parser("show", help="Inspect a saved experiment")
    show.add_argument("id")
    commands.add_parser("verify", help="Check snapshots, run logs and output hashes")
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            output = inspect_project(args.project, max_entries=args.max_entries,
                                     exclude=args.exclude)
        elif args.command == "init":
            project = Project.init(args.project, args.name)
            output = {"project": str(project.root), "name": args.name}
        else:
            project = Project.open(args.project)
            if args.command == "record":
                config = json.loads(args.config.read_text()) if args.config else {}
                output = project.record(args.question, args.source, config, args.gap,
                                        args.parent, args.origin, inputs=args.input)
            elif args.command == "import":
                output = project.import_history(json.loads(args.manifest.read_text()))
            elif args.command == "run":
                output = project.execute(args.id, args.entrypoint, outputs=args.output,
                                         arguments=args.arg, timeout=args.timeout,
                                         checkpoints=args.checkpoint_output, resume_from=args.resume_from,
                                         checkpoint=args.checkpoint, reuse_from=args.reuse_from,
                                         reuse_reason=args.reuse_reason,
                                         reuse_context=json.loads(args.reuse_context.read_text()) if args.reuse_context else None,
                                         dependencies=args.dependency, backend=args.backend,
                                         checkpoint_revision=args.checkpoint_revision)
                print(canonical(output))
                return 0 if output["status"] in {"succeeded", "reused"} else 1
            elif args.command == "checkpoint":
                output = project.save_checkpoint(args.id, args.path)
            elif args.command == "checkpoints":
                output = project.checkpoints(args.id)
            elif args.command == "runs":
                output = project.runs(args.record)
            elif args.command == "show-run":
                output = project.get_run(args.id)
            elif args.command == "export":
                output = project.export(args.output, args.record)
                print(canonical(output))
                return 0 if output["integrity_ok"] else 1
            elif args.command == "note":
                output = project.add_research_record(json.loads(args.manifest.read_text()))
            elif args.command == "notes":
                output = project.research_records()
            elif args.command == "show-note":
                output = project.get_research_record(args.id)
            elif args.command == "list":
                output = project.records()
            elif args.command == "show":
                output = project.get(args.id)
            else:
                errors = project.verify() + project.verify_runs()
                print(canonical({"ok": not errors, "errors": errors}))
                return 1 if errors else 0
        print(canonical(output))
        return 0
    except (LedgerError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(canonical({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
