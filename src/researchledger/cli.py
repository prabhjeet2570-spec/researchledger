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
    record.add_argument("--config", type=Path, help="JSON configuration file")
    record.add_argument("--gap", action="append", default=[])
    record.add_argument("--parent")
    record.add_argument("--origin", choices=["manual", "agent", "historical"], default="manual")
    history = commands.add_parser("import", help="Capture explicitly mapped historical evidence")
    history.add_argument("--manifest", type=Path, required=True, help="Historical evidence JSON")
    run = commands.add_parser("run", help="Execute a captured Python script locally")
    run.add_argument("id", help="Saved experiment record ID")
    run.add_argument("--entrypoint", required=True)
    run.add_argument("--output", action="append", default=[], help="Expected file relative to run workspace")
    run.add_argument("--arg", action="append", default=[], help="Script argument; use --arg=-flag")
    run.add_argument("--timeout", type=float, default=3600)
    runs = commands.add_parser("runs", help="List local execution attempts")
    runs.add_argument("--record")
    show_run = commands.add_parser("show-run", help="Read a persisted execution attempt")
    show_run.add_argument("id")
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
                                        args.parent, args.origin)
            elif args.command == "import":
                output = project.import_history(json.loads(args.manifest.read_text()))
            elif args.command == "run":
                output = project.execute(args.id, args.entrypoint, outputs=args.output,
                                         arguments=args.arg, timeout=args.timeout)
                print(canonical(output))
                return 0 if output["status"] == "succeeded" else 1
            elif args.command == "runs":
                output = project.runs(args.record)
            elif args.command == "show-run":
                output = project.get_run(args.id)
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
