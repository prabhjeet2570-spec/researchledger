import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from researchledger import LedgerError, Project


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = Project.init(self.root, "Approximation study")
        (self.root / "experiment.py").write_text("degree = 3\n")

    def test_snapshot_survives_edits_and_restart(self):
        record = self.project.record("Does degree matter?", ["experiment.py"], {"degree": 3})
        (self.root / "experiment.py").write_text("degree = 7\n")
        reopened = Project.open(self.root)
        self.assertEqual(reopened.get(record["id"])["config"], {"degree": 3})
        captured = self.root / ".research/snapshots" / record["id"] / "experiment.py"
        self.assertEqual(captured.read_text(), "degree = 3\n")
        self.assertEqual(reopened.verify(), [])
        self.assertEqual(record["execution_status"], "not_observed")

    def test_tampered_and_missing_snapshots_fail_verification(self):
        record = self.project.record("Capture", ["experiment.py"])
        path = self.root / ".research/snapshots" / record["id"] / "experiment.py"
        path.write_text("degree = 9\n")
        self.assertEqual(self.project.verify()[0]["problem"], "changed")
        path.unlink()
        self.assertEqual(self.project.verify()[0]["problem"], "missing")

    def test_historical_gaps_remain_explicit(self):
        record = self.project.record("Prior result", ["experiment.py"], origin="historical",
                                     gaps=["Executed notebook version unavailable"])
        self.assertEqual(self.project.get(record["id"])["gaps"], record["gaps"])
        self.assertEqual(record["execution_status"], "not_observed")

    def test_parent_must_exist_and_old_record_is_preserved(self):
        with self.assertRaises(LedgerError):
            self.project.record("Follow up", ["experiment.py"], parent="missing")
        first = self.project.record("First", ["experiment.py"])
        second = self.project.record("Next", ["experiment.py"], parent=first["id"])
        self.assertEqual(second["parent"], first["id"])
        self.assertEqual(self.project.get(first["id"]), first)

    def test_bad_capture_leaves_no_record_or_snapshot(self):
        with self.assertRaises(LedgerError):
            self.project.record("Bad", ["experiment.py", "absent.py"])
        self.assertEqual(self.project.records(), [])
        self.assertEqual(list((self.root / ".research/snapshots").iterdir()), [])

    def test_path_escape_and_excluded_storage_are_rejected(self):
        (self.root / ".env").write_text("not for capture")
        (self.root / "alias").symlink_to(self.root / ".env")
        for path in ["../outside", str(self.root / "experiment.py"), ".env", "alias",
                     ".research/ledger.sqlite3"]:
            with self.subTest(path=path), self.assertRaises(LedgerError):
                self.project.record("Bad", [path])

    def test_nonfinite_config_and_reinitialization_are_rejected(self):
        with self.assertRaises(LedgerError):
            self.project.record("Bad", ["experiment.py"], {"accuracy": float("nan")})
        with self.assertRaises(LedgerError):
            Project.init(self.root, "Overwrite")
        self.assertEqual(self.project.records(), [])

    def test_cli_json_and_failure_exit(self):
        base = [sys.executable, "-m", "researchledger", "--project", str(self.root)]
        done = subprocess.run(base + ["record", "--question", "CLI capture", "--source",
                                      "experiment.py"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["execution_status"], "not_observed")
        failed = subprocess.run(base + ["show", "unknown"], capture_output=True, text=True)
        self.assertEqual(failed.returncode, 1)
        self.assertIn("error", json.loads(failed.stderr))


if __name__ == "__main__":
    unittest.main()
