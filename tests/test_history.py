import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from researchledger import LedgerError, Project


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = Project.init(self.root, 'Synthetic study')
        (self.root / 'results.csv').write_text('degree,error\n3,0.12\n')
        (self.root / 'study.py').write_text('degree = 3\n')
        self.manifest = {'question': 'What was reported?', 'sources': ['study.py'],
                         'artifacts': [{'path': 'results.csv', 'role': 'reported metrics'}],
                         'claims': {'error': 0.12}, 'config': {'degree': 3},
                         'context': {'label': 'prior exploratory run'},
                         'gaps': ['Executed version unavailable']}

    def test_persists_evidence_and_declarations_without_execution_claim(self):
        record = self.project.import_history(self.manifest)
        (self.root / 'results.csv').write_text('changed')
        saved = Project.open(self.root).get(record['id'])
        self.assertEqual(saved['origin'], 'historical')
        self.assertEqual(saved['execution_status'], 'not_observed')
        self.assertEqual(saved['historical']['claims_status'], 'unverified_declaration')
        self.assertEqual(saved['historical']['claims'], {'error': 0.12})
        self.assertIn('Executed version unavailable', saved['gaps'])
        self.assertEqual(saved['artifacts'][0]['role'], 'reported metrics')
        path = self.root / '.research/snapshots' / record['id'] / 'results.csv'
        self.assertEqual(path.read_text(), 'degree,error\n3,0.12\n')
        self.assertEqual(self.project.verify(), [])
        path.write_text('tampered')
        self.assertEqual(self.project.verify()[0]['problem'], 'changed')
        path.unlink()
        self.assertEqual(self.project.verify()[0]['problem'], 'missing')

    def test_artifact_only_import_still_records_verification_gap(self):
        record = self.project.import_history({'question': 'Unavailable original code',
            'artifacts': self.manifest['artifacts']})
        self.assertEqual(record['sources'], [])
        self.assertEqual(record['historical']['claims'], {})
        self.assertIn('not observed', record['gaps'][0])
        self.assertEqual(self.project.verify(), [])

    def test_invalid_imports_leave_no_records_or_snapshots(self):
        variants = [dict(self.manifest, artifacts=[]),
            dict(self.manifest, artifacts=[{'path': 'missing.csv', 'role': 'metrics'}]),
            dict(self.manifest, sources=['results.csv']),
            dict(self.manifest, artifacts=[{'path': '../escape', 'role': 'metrics'}]),
            dict(self.manifest, artifacts=[{'path': 'results.csv'}]),
            dict(self.manifest, claims={'value': float('nan')}),
            dict(self.manifest, context=[]), dict(self.manifest, gaps='missing'),
            dict(self.manifest, execution_status='succeeded'),
            dict(self.manifest, parent='unknown'), dict(self.manifest, sources='study.py')]
        for manifest in variants:
            with self.subTest(manifest=manifest), self.assertRaises(LedgerError):
                self.project.import_history(manifest)
        self.assertEqual(self.project.records(), [])
        self.assertEqual(list((self.root / '.research/snapshots').iterdir()), [])

    def test_parent_import_and_legacy_source_record_both_verify(self):
        old = self.project.record('Original capture', ['study.py'])
        imported = self.project.import_history(dict(self.manifest, parent=old['id']))
        self.assertEqual(imported['parent'], old['id'])
        self.assertEqual(self.project.get(old['id']), old)
        self.assertNotIn('artifacts', old)
        self.assertEqual(self.project.verify(), [])

    def test_cli_import_and_failure_exit(self):
        manifest = self.root / 'history.json'
        manifest.write_text(json.dumps(self.manifest))
        base = [sys.executable, '-m', 'researchledger', '--project', str(self.root)]
        done = subprocess.run(base + ['import', '--manifest', str(manifest)],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)['historical']['claims_status'],
                         'unverified_declaration')
        manifest.write_text('{"execution_status":"succeeded"}')
        bad = subprocess.run(base + ['import', '--manifest', str(manifest)],
                             capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        self.assertIn('error', json.loads(bad.stderr))
