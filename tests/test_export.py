import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from researchledger import LedgerError, Project


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = Project.init(self.root, 'Synthetic portable evidence')
        (self.root / 'experiment.py').write_text("from pathlib import Path\nprint('done')\nPath('metrics.json').write_text('{\"error\":0.1}')\n")

    def test_selected_record_includes_parent_and_run_bytes_with_valid_hashes(self):
        parent = self.project.record('Baseline', ['experiment.py'])
        selected = self.project.record('Follow up', ['experiment.py'], parent=parent['id'])
        unrelated = self.project.record('Unrelated', ['experiment.py'])
        run = self.project.execute(selected['id'], 'experiment.py', outputs=['metrics.json'])
        (self.root / 'experiment.py').write_text('changed working code')
        output = self.root / 'evidence.zip'
        result = self.project.export(output, [selected['id']])
        self.assertTrue(result['integrity_ok'])
        with zipfile.ZipFile(output) as bundle:
            manifest = json.loads(bundle.read('manifest.json'))
            self.assertEqual(set(manifest['record_ids']), {selected['id'], parent['id']})
            self.assertNotIn(unrelated['id'], manifest['record_ids'])
            for item in manifest['files']:
                data = bundle.read(item['path'])
                self.assertEqual(len(data), item['size_bytes'])
                self.assertEqual(hashlib.sha256(data).hexdigest(), item['sha256'])
            self.assertIn('evidence.csv', bundle.namelist())
            self.assertEqual(json.loads(bundle.read('runs.json'))[0]['id'], run['id'])
            self.assertEqual(bundle.read('runs/' + run['id'] + '/artifacts/metrics.json'), b'{"error":0.1}')
            self.assertFalse(any('/work/' in name for name in bundle.namelist()))

    def test_changed_and_missing_bytes_are_omitted_and_reported(self):
        record = self.project.record('Capture', ['experiment.py'])
        snapshot = self.root / '.research/snapshots' / record['id'] / 'experiment.py'
        snapshot.write_text('changed saved evidence')
        result = self.project.export(self.root / 'changed.zip')
        self.assertFalse(result['integrity_ok'])
        with zipfile.ZipFile(self.root / 'changed.zip') as bundle:
            self.assertNotIn('snapshots/' + record['id'] + '/experiment.py', bundle.namelist())
            self.assertEqual(len(json.loads(bundle.read('manifest.json'))['issues']), 1)
        snapshot.unlink()
        self.assertFalse(self.project.export(self.root / 'missing.zip')['integrity_ok'])

    def test_unresolved_run_omits_live_evidence_and_preserves_status(self):
        record = self.project.record('Run', ['experiment.py'])
        run = self.project.execute(record['id'], 'experiment.py', outputs=['metrics.json'])
        run.update(status='running', finished_at=None)
        self.project._save_run(run)
        result = self.project.export(self.root / 'unresolved.zip')
        self.assertFalse(result['integrity_ok'])
        with zipfile.ZipFile(self.root / 'unresolved.zip') as bundle:
            self.assertEqual(json.loads(bundle.read('runs.json'))[0]['status'], 'running')
            self.assertFalse(any(name.startswith('runs/') for name in bundle.namelist()))

    def test_historical_declarations_and_gaps_remain_explicit(self):
        (self.root / 'old.csv').write_text('error\n0.12\n')
        record = self.project.import_history({'question': 'Prior result',
            'artifacts': [{'path': 'old.csv', 'role': 'reported metrics'}],
            'claims': {'error': 0.12}, 'gaps': ['Executed source missing']})
        self.project.export(self.root / 'history.zip')
        with zipfile.ZipFile(self.root / 'history.zip') as bundle:
            saved = json.loads(bundle.read('records.json'))[0]
            self.assertEqual(saved, record)
            self.assertEqual(saved['historical']['claims_status'], 'unverified_declaration')
            self.assertIn('Executed source missing', saved['gaps'])

    def test_overwrite_storage_and_invalid_selection_rejected(self):
        self.project.record('Capture', ['experiment.py'])
        existing = self.root / 'existing.zip'
        existing.write_text('keep')
        for output, selected in [(existing, None), (self.root / '.research/export.zip', None),
                                 (self.root / 'empty.zip', []), (self.root / 'bad.zip', 'invalid')]:
            with self.assertRaises(LedgerError):
                self.project.export(output, selected)
        self.assertEqual(existing.read_text(), 'keep')

    def test_cli_writes_partial_bundle_and_exits_nonzero(self):
        record = self.project.record('Capture', ['experiment.py'])
        (self.root / '.research/snapshots' / record['id'] / 'experiment.py').unlink()
        output = self.root / 'partial.zip'
        result = subprocess.run([sys.executable, '-m', 'researchledger', '--project', str(self.root),
                                 'export', '--output', str(output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)['integrity_ok'])
        self.assertTrue(zipfile.is_zipfile(output))
