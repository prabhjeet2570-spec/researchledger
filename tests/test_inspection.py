import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from researchledger import LedgerError, inspect_project


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_inventory_proposes_capture_without_executing_or_initializing(self):
        (self.root / "study.ipynb").write_text(json.dumps({"cells": [{
            "cell_type": "code", "source": "raise RuntimeError('never execute')"}]}))
        (self.root / "run.py").write_text("raise RuntimeError('never import')\n")
        (self.root / "config.json").write_text('{"degree":3}')
        (self.root / "results.csv").write_text("error\n0.12\n")
        (self.root / "notes.md").write_text("Unconfirmed result")
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        report = inspect_project(self.root)
        self.assertTrue(report["complete"])
        self.assertEqual(report["counts"]["notebook"], 1)
        self.assertEqual(report["capture_plan"]["source_candidates"],
                         ["run.py", "study.ipynb"])
        self.assertEqual(report["capture_plan"]["artifact_candidates"], ["results.csv"])
        self.assertEqual(report["relationships"], [])
        self.assertEqual(report["capture_plan"]["status"], "proposal_requires_review")
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_default_custom_exclusions_and_symlinks(self):
        for name in [".research", ".venv", "__pycache__", "private"]:
            (self.root / name).mkdir()
            (self.root / name / "hidden.py").write_text("do not inventory")
        (self.root / ".env.local").write_text("excluded")
        (self.root / "safe.py").write_text("print('safe')")
        (self.root / "link.py").symlink_to(self.root / "safe.py")
        (self.root / "directory-link").symlink_to(self.root / "private", target_is_directory=True)
        report = inspect_project(self.root, exclude=["private"])
        self.assertEqual([f["path"] for f in report["files"]], ["safe.py"])
        reasons = {f["path"]: f["reason"] for f in report["skipped"]}
        self.assertEqual(reasons["link.py"], "symlink_not_followed")
        self.assertEqual(reasons["directory-link"], "symlink_not_followed")
        self.assertEqual(reasons["private"], "user_exclusion")

    @unittest.skipUnless(shutil.which("git"), "Git not installed")
    def test_git_revision_and_ignore_rules_with_spaces_and_newlines(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / ".gitignore").write_text("cache/\n*.csv\n")
        (self.root / "cache").mkdir()
        (self.root / "cache/hidden.py").write_text("ignored")
        (self.root / "data space.csv").write_text("ignored")
        (self.root / "data\nnewline.csv").write_text("ignored")
        (self.root / "run.py").write_text("x=1")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Test",
                        "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",
                        "commit", "-qm", "fixture"], check=True)
        report = inspect_project(self.root)
        self.assertTrue(report["git"]["ignore_rules_applied"])
        self.assertEqual(len(report["git"]["head"]), 40)
        self.assertNotIn("artifact_candidate", report["counts"])
        self.assertNotIn("cache/hidden.py", [f["path"] for f in report["files"]])
        self.assertEqual(next(f["reason"] for f in report["skipped"]
                              if f["path"] == "data\nnewline.csv"), "git_ignore")

    def test_bounded_inventory_reports_truncation_and_validates_input(self):
        for i in range(5):
            (self.root / f"{i}.py").write_text("x=1")
        report = inspect_project(self.root, max_entries=2)
        self.assertEqual(report["entries_examined"], 2)
        self.assertTrue(report["truncated"])
        self.assertFalse(report["complete"])
        self.assertEqual(len(report["files"]), 2)
        for limit in [0, -1, True, 100001]:
            with self.assertRaises(LedgerError):
                inspect_project(self.root, max_entries=limit)
        with self.assertRaises(LedgerError):
            inspect_project(self.root / "absent")

    def test_cli_before_initialization_and_invalid_limit(self):
        base = [sys.executable, "-m", "researchledger", "--project", str(self.root)]
        done = subprocess.run(base + ["inspect"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["files"], [])
        self.assertFalse((self.root / ".research").exists())
        bad = subprocess.run(base + ["inspect", "--max-entries", "0"],
                             capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("error", json.loads(bad.stderr))
