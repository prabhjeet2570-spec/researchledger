"""Machine-readable CLI sharing the Python SDK's operations."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from . import __version__
from .store import LedgerError, Project, canonical


def main(argv=None):
    parser = argparse.ArgumentParser(description="Capture research code and provenance")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--project", default=".", help="Research directory (default: current)")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Initialize a local research ledger")
    init.add_argument("--name", required=True)
    record = commands.add_parser("record", help="Snapshot explicit files; does not execute them")
    record.add_argument("--question", required=True)
    record.add_argument("--source", action="append", required=True)
    record.add_argument("--config", type=Path, help="JSON configuration file")
    record.add_argument("--gap", action="append", default=[])
    record.add_argument("--parent")
    record.add_argument("--origin", choices=["manual", "agent", "historical"], default="manual")
    commands.add_parser("list", help="List saved experiment records as JSON")
    show = commands.add_parser("show", help="Inspect a saved experiment")
    show.add_argument("id")
    commands.add_parser("verify", help="Check captured source hashes")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            project = Project.init(args.project, args.name)
            output = {"project": str(project.root), "name": args.name}
        else:
            project = Project.open(args.project)
            if args.command == "record":
                config = json.loads(args.config.read_text()) if args.config else {}
                output = project.record(args.question, args.source, config, args.gap,
                                        args.parent, args.origin)
            elif args.command == "list":
                output = project.records()
            elif args.command == "show":
                output = project.get(args.id)
            else:
                errors = project.verify()
                print(canonical({"ok": not errors, "errors": errors}))
                return 1 if errors else 0
        print(canonical(output))
        return 0
    except (LedgerError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(canonical({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
