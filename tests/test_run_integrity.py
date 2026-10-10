import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from researchledger import Project


class RunIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = Project.init(self.root, 'Synthetic integrity study')

    def capture(self, code):
        (self.root / 'experiment.py').write_text(code)
        return self.project.record('Observe actual effects', ['experiment.py'])

    def test_verifies_log_and_output_tampering_and_missing_files(self):
        record = self.capture("from pathlib import Path\nprint('captured log')\nPath('result.txt').write_text('output')\n")
        run = self.project.execute(record['id'], 'experiment.py', outputs=['result.txt'])
        self.assertEqual(self.project.verify_runs(), [])
        directory = self.root / '.research/runs' / run['id']
        (directory / 'stdout.log').write_text('changed log')
        (directory / 'artifacts/result.txt').unlink()
        errors = self.project.verify_runs()
        self.assertIn({'id': run['id'], 'path': 'stdout.log', 'problem': 'changed'}, errors)
        self.assertIn({'id': run['id'], 'path': 'result.txt', 'problem': 'missing'}, errors)
        cli = subprocess.run([sys.executable, '-m', 'researchledger', '--project', str(self.root), 'verify'], capture_output=True, text=True)
        self.assertEqual(cli.returncode, 1, cli.stderr)

    def test_unresolved_and_legacy_runs_report_gaps_without_rewriting(self):
        record = self.capture("print('done')\n")
        run = self.project.execute(record['id'], 'experiment.py')
        del run['log_manifest']
        self.project._save_run(run)
        self.assertEqual(self.project.verify_runs()[0]['problem'], 'log_manifest_unavailable')
        run['finished_at'] = None
        run['status'] = 'running'
        self.project._save_run(run)
        self.assertEqual(self.project.verify_runs()[0]['problem'], 'run_not_finalized')
        self.assertEqual(self.project.get_run(run['id'])['status'], 'running')

    @unittest.skipUnless(os.name == 'posix', 'POSIX signal test')
    def test_sigterm_stops_child_and_records_partial_evidence(self):
        record = self.capture("import time\nfrom pathlib import Path\nPath('partial.txt').write_text('started')\nprint('before interruption', flush=True)\ntime.sleep(30)\n")
        process = subprocess.Popen([sys.executable, '-m', 'researchledger', '--project', str(self.root), 'run', record['id'], '--entrypoint', 'experiment.py', '--output', 'partial.txt'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                runs = self.project.runs(record['id'])
                if runs and runs[0]['status'] == 'running':
                    run = runs[0]
                    partial = self.root / '.research/runs' / run['id'] / 'work/partial.txt'
                    if partial.exists():
                        break
                time.sleep(0.02)
            else:
                self.fail('Executor did not start')
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 1, stderr)
            saved = self.project.get_run(run['id'])
            self.assertEqual(saved['status'], 'interrupted')
            self.assertEqual(saved['interruption_signal'], signal.SIGTERM)
            self.assertEqual(saved['artifacts'][0]['path'], 'partial.txt')
            self.assertIsNotNone(saved['finished_at'])
            self.assertEqual(self.project.verify_runs(), [])
            with self.assertRaises(ProcessLookupError):
                os.kill(saved['pid'], 0)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()

    def test_caller_signal_handler_restored(self):
        before = signal.getsignal(signal.SIGTERM)
        record = self.capture("print('short run')\n")
        self.project.execute(record['id'], 'experiment.py')
        self.assertEqual(signal.getsignal(signal.SIGTERM), before)
