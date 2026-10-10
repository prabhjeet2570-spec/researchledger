import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from researchledger import LedgerError, Project


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = Project.init(self.root, 'CPU numerical study')

    def capture(self, code, config=None):
        (self.root / 'experiment.py').write_text(code)
        return self.project.record('Numerical evidence', ['experiment.py'], config)

    def test_runs_snapshot_and_configuration_after_working_source_changes(self):
        record = self.capture("import json, os\nfrom pathlib import Path\nc=json.loads(Path(os.environ['RESEARCHLEDGER_CONFIG']).read_text())\nPath('metrics.json').write_text(json.dumps({'squared': c['x']**2}))\nprint('completed')\n", {'x': 3})
        (self.root / 'experiment.py').write_text("raise RuntimeError('wrong version')")
        run = self.project.execute(record['id'], 'experiment.py', outputs=['metrics.json'])
        self.assertEqual(run['status'], 'succeeded')
        self.assertEqual(run['returncode'], 0)
        directory = self.root / '.research/runs' / run['id']
        self.assertEqual(json.loads((directory / 'artifacts/metrics.json').read_text()), {'squared': 9})
        self.assertIn('completed', (directory / 'stdout.log').read_text())
        self.assertEqual(Project.open(self.root).get_run(run['id']), run)
        self.assertEqual(self.project.get(record['id']), record)
        self.assertEqual(self.project.verify(), [])

    def test_failure_retains_logs_and_partial_outputs_and_missing_outputs_fail(self):
        record = self.capture("from pathlib import Path\nimport sys\nPath('partial.txt').write_text('partial')\nprint('failure evidence', file=sys.stderr)\nsys.exit(7)\n")
        run = self.project.execute(record['id'], 'experiment.py', outputs=['partial.txt', 'absent.txt'])
        self.assertEqual(run['status'], 'failed')
        self.assertEqual(run['returncode'], 7)
        self.assertEqual(len(run['artifacts']), 1)
        self.assertEqual(len(run['output_errors']), 1)
        self.assertIn('failure evidence', (self.root / '.research/runs' / run['id'] / 'stderr.log').read_text())
        successful = self.capture("print('no output produced')\n")
        run = self.project.execute(successful['id'], 'experiment.py', outputs=['absent.txt'])
        self.assertEqual(run['status'], 'outputs_incomplete')
        self.assertEqual(run['returncode'], 0)

    def test_timeout_and_unique_attempts(self):
        record = self.capture("import time\nprint('started', flush=True)\ntime.sleep(10)\n")
        run = self.project.execute(record['id'], 'experiment.py', timeout=0.1)
        self.assertEqual(run['status'], 'timed_out')
        again = self.project.execute(record['id'], 'experiment.py', timeout=0.1)
        self.assertNotEqual(run['id'], again['id'])
        self.assertEqual(len(self.project.runs(record['id'])), 2)

    def test_tampered_snapshot_is_not_executed_and_paths_validated(self):
        record = self.capture("print('original')\n")
        captured = self.root / '.research/snapshots' / record['id'] / 'experiment.py'
        captured.write_text("print('tampered')\n")
        run = self.project.execute(record['id'], 'experiment.py')
        self.assertEqual(run['status'], 'preparation_failed')
        self.assertIsNone(run['pid'])
        for kwargs in [{'outputs': ['../outside']}, {'outputs': ['experiment.py']},
                       {'timeout': float('nan')}, {'arguments': 'bad'}]:
            with self.assertRaises(LedgerError):
                self.project.execute(record['id'], 'experiment.py', **kwargs)

    def test_symlink_output_rejected_and_cli_nonzero_exit(self):
        record = self.capture("from pathlib import Path\nPath('link.txt').symlink_to('experiment.py')\n")
        run = self.project.execute(record['id'], 'experiment.py', outputs=['link.txt'])
        self.assertEqual(run['status'], 'outputs_incomplete')
        self.assertEqual(run['artifacts'], [])
        base = [sys.executable, '-m', 'researchledger', '--project', str(self.root)]
        done = subprocess.run(base + ['run', record['id'], '--entrypoint', 'experiment.py', '--output', 'link.txt'], capture_output=True, text=True)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(json.loads(done.stdout)['status'], 'outputs_incomplete')
        listing = subprocess.run(base + ['runs'], capture_output=True, text=True)
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertEqual(len(json.loads(listing.stdout)), 2)
