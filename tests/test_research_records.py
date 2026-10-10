import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor

from researchledger import LedgerError, Project


class ResearchRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = Project.init(self.root, 'Synthetic decisions')
        (self.root / 'main.py').write_text("print('sample')\n")
        self.experiment = self.project.record('Synthetic experiment', ['main.py'])
        self.manifest = dict(kind='decision', statement='Try higher degree',
                             rationale='Sampled error was too high', scope='Synthetic interval',
                             evidence=[{'record_id': self.experiment['id']}],
                             uncertainties=['Sample grid is finite'])

    def test_revision_is_immutable_and_survives_reopen(self):
        first = self.project.add_research_record(self.manifest)
        second = self.project.add_research_record(dict(self.manifest, statement='Keep this degree',
            rationale='New sampled evidence met the target', supersedes=first['id']))
        project = Project.open(self.root)
        self.assertEqual(project.get_research_record(first['id']), first)
        self.assertEqual(project.research_records(), [first, second])
        self.assertEqual(second['thread_id'], first['id'])
        self.assertEqual(second['version'], 2)
        self.assertEqual(second['assessment_status'], 'unverified_declaration')
        with self.assertRaises(LedgerError):
            project.add_research_record(dict(self.manifest, supersedes=first['id']))
        self.assertEqual(project.get(self.experiment['id']), self.experiment)

    def test_invalid_inputs_never_append(self):
        other = self.project.record('Other experiment', ['main.py'])
        run = self.project.execute(other['id'], 'main.py')
        bad = [dict(self.manifest, scope=''), dict(self.manifest, kind='fact'), dict(self.manifest, kind=[]),
               dict(self.manifest, unknown=True), dict(self.manifest, origin=[]), dict(self.manifest, origin='historical'),
               dict(self.manifest, evidence=[{'record_id': 'missing'}]),
               dict(self.manifest, evidence=[{'record_id': self.experiment['id'], 'run_id': run['id']}]),
               dict(self.manifest, supersedes='missing'),
               dict(self.manifest, uncertainties=[123]),
               dict(self.manifest, evidence=self.manifest['evidence'] * 2)]
        for manifest in bad:
            with self.subTest(manifest=manifest), self.assertRaises(LedgerError):
                self.project.add_research_record(manifest)
        self.assertEqual(self.project.research_records(), [])
        first = self.project.add_research_record(self.manifest)
        with self.assertRaises(LedgerError):
            self.project.add_research_record(dict(self.manifest, kind='interpretation', supersedes=first['id']))

    def test_concurrent_revisions_allow_only_one_successor(self):
        first = self.project.add_research_record(self.manifest)
        def revise(_):
            try:
                return Project.open(self.root).add_research_record(dict(self.manifest, supersedes=first['id']))
            except LedgerError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(revise, range(2)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(len(self.project.research_records()), 2)

    def test_selected_export_preserves_thread_and_all_its_evidence(self):
        other = self.project.record('Other evidence', ['main.py'])
        unrelated = self.project.record('Unrelated', ['main.py'])
        run = self.project.execute(other['id'], 'main.py')
        first = self.project.add_research_record(self.manifest)
        second = self.project.add_research_record(dict(self.manifest, supersedes=first['id'],
            evidence=[{'record_id': other['id'], 'run_id': run['id']}]))
        unsupported = self.project.add_research_record(dict(self.manifest, evidence=[]))
        output = self.root / 'selected.zip'
        self.project.export(output, [self.experiment['id']])
        with zipfile.ZipFile(output) as bundle:
            notes = json.loads(bundle.read('research_records.json'))
            manifest = json.loads(bundle.read('manifest.json'))
            self.assertEqual(notes, [first, second])
            self.assertEqual(set(manifest['record_ids']), {self.experiment['id'], other['id']})
            self.assertNotIn(unrelated['id'], manifest['record_ids'])
            self.assertEqual(manifest['run_ids'], [run['id']])
            self.assertEqual(manifest['research_record_ids'], [first['id'], second['id']])
        self.project.export(self.root / 'all.zip')
        with zipfile.ZipFile(self.root / 'all.zip') as bundle:
            self.assertIn(unsupported, json.loads(bundle.read('research_records.json')))

    def test_interpretation_and_parent_context_are_exported(self):
        before = self.project.database.read_bytes()
        self.assertEqual(self.project.research_records(), [])
        self.assertEqual(self.project.database.read_bytes(), before)
        child = self.project.record('Follow-up', ['main.py'], parent=self.experiment['id'])
        note = self.project.add_research_record(dict(self.manifest, kind='interpretation', origin='agent'))
        self.project.export(self.root / 'child.zip', [child['id']])
        with zipfile.ZipFile(self.root / 'child.zip') as bundle:
            self.assertEqual(json.loads(bundle.read('research_records.json')), [note])
        self.assertEqual(note['origin'], 'agent')
        self.assertEqual(note['assessment_status'], 'unverified_declaration')

    def test_cli_create_list_show_and_reject_stale_revision(self):
        path = self.root / 'decision.json'
        path.write_text(json.dumps(self.manifest))
        command = [sys.executable, '-m', 'researchledger', '--project', str(self.root)]
        result = subprocess.run(command + ['note', '--manifest', str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        first = json.loads(result.stdout)
        for args in [['notes'], ['show-note', first['id']]]:
            result = subprocess.run(command + args, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [first] if args == ['notes'] else first)
        path.write_text(json.dumps(dict(self.manifest, supersedes=first['id'])))
        result = subprocess.run(command + ['note', '--manifest', str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(command + ['note', '--manifest', str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('already superseded', json.loads(result.stderr)['error'])
