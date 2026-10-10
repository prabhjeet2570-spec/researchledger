import hashlib
import json
import math
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
import zipfile

from researchledger import Project


class CPUWorkflowTests(unittest.TestCase):
    def test_workflow_links_actual_results_failures_decisions_and_exported_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'study'
            result = subprocess.run([sys.executable, 'examples/cpu_workflow.py', str(destination)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            project = Project.open(destination)
            self.assertEqual(len(project.records()), 4)
            self.assertEqual([r['status'] for r in project.runs()], ['succeeded', 'succeeded', 'failed'])
            self.assertEqual(project.verify() + project.verify_runs(), [])
            for name, count in [('coarse_metrics', 8), ('refined_metrics', 64)]:
                metrics = summary[name]
                self.assertTrue(math.isclose(metrics['absolute_error'], 1 / (6 * count * count), abs_tol=1e-15))
            failed = project.get_run(summary['rejected_run'])
            self.assertEqual([a['path'] for a in failed['artifacts']], ['request.json'])
            stderr = destination / '.research/runs' / failed['id'] / 'stderr.log'
            self.assertIn('intervals must be an integer', stderr.read_text())
            notes = project.research_records()
            self.assertEqual(notes[1]['supersedes'], notes[0]['id'])
            self.assertEqual(notes[1]['evidence'][1]['run_id'], failed['id'])
            historical = project.get(summary['historical_record'])
            self.assertTrue(historical['historical']['context']['synthetic'])
            self.assertEqual(historical['execution_status'], 'not_observed')
            self.assertTrue(historical['gaps'])
            inventory = json.loads((destination / 'inventory.json').read_text())
            self.assertTrue(inventory['complete'])
            self.assertEqual(inventory['relationships'], [])
            self.assertEqual(inventory['capture_plan']['status'], 'proposal_requires_review')
            with zipfile.ZipFile(destination / 'evidence.zip') as bundle:
                manifest = json.loads(bundle.read('manifest.json'))
                self.assertTrue(manifest['integrity_ok'])
                for item in manifest['files']:
                    data = bundle.read(item['path'])
                    self.assertEqual(hashlib.sha256(data).hexdigest(), item['sha256'])
                    self.assertEqual(len(data), item['size_bytes'])
                self.assertEqual(json.loads(bundle.read('research_records.json')), notes)
                self.assertEqual(len(json.loads(bundle.read('runs.json'))), 3)

    def test_existing_destination_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'keep.txt').write_text('untouched')
            result = subprocess.run([sys.executable, 'examples/cpu_workflow.py', str(root)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(list(root.iterdir()), [root / 'keep.txt'])
            self.assertEqual((root / 'keep.txt').read_text(), 'untouched')

    def test_numerical_example_checks_inputs_and_known_integral(self):
        integrate = runpy.run_path('examples/integrate.py')['integrate']
        for count in (1, 2, 8, 64):
            self.assertTrue(math.isclose(integrate(count)['estimate'], 1 / 3 + 1 / (6 * count * count), abs_tol=1e-15))
        for invalid in (0, -1, True, 1.5, '8', 100001):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                integrate(invalid)
