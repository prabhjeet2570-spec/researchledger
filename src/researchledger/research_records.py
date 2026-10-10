"""Explicit research judgments with immutable revision history."""

import json
import uuid

from .store import LedgerError, canonical, now, require_text


def list_records(project):
    with project.connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='research_records' AND type='table'").fetchone():
            return []
        rows = db.execute("SELECT payload FROM research_records ORDER BY rowid").fetchall()
    return [json.loads(row[0]) for row in rows]


def add_record(project, manifest):
    allowed = {'kind', 'statement', 'rationale', 'scope', 'evidence', 'uncertainties',
               'origin', 'supersedes'}
    if not isinstance(manifest, dict) or set(manifest) - allowed:
        raise LedgerError('Research record must be an object with supported fields')
    kind = manifest.get('kind')
    if kind not in ('decision', 'interpretation'):
        raise LedgerError('Kind must be decision or interpretation')
    for field in ('statement', 'rationale', 'scope'):
        require_text(manifest.get(field), field)
    origin = manifest.get('origin', 'manual')
    if origin not in ('manual', 'agent'):
        raise LedgerError('Research record origin must be manual or agent')
    uncertainties = manifest.get('uncertainties', [])
    if not isinstance(uncertainties, list):
        raise LedgerError('Uncertainties must be a list')
    for item in uncertainties:
        require_text(item, 'Uncertainty')
    evidence = manifest.get('evidence', [])
    if not isinstance(evidence, list):
        raise LedgerError('Evidence must be a list of experiment/run references')
    for reference in evidence:
        if not isinstance(reference, dict) or set(reference) not in ({'record_id'}, {'record_id', 'run_id'}):
            raise LedgerError('Evidence requires record_id and optionally run_id')
        require_text(reference['record_id'], 'Evidence record ID')
        project.get(reference['record_id'])
        if 'run_id' in reference:
            require_text(reference['run_id'], 'Evidence run ID')
            run = project.get_run(reference['run_id'])
            if run['record_id'] != reference['record_id']:
                raise LedgerError('Evidence run does not belong to the referenced experiment')
    if len({canonical(item) for item in evidence}) != len(evidence):
        raise LedgerError('Duplicate evidence references')
    previous = manifest.get('supersedes')
    if previous is not None:
        require_text(previous, 'Superseded revision ID')
    identifier = 'note-' + uuid.uuid4().hex
    payload = {'id': identifier, 'created_at': now(), 'kind': kind,
               'statement': manifest['statement'], 'rationale': manifest['rationale'],
               'scope': manifest['scope'], 'evidence': evidence,
               'uncertainties': uncertainties, 'origin': origin,
               'assessment_status': 'unverified_declaration', 'supersedes': previous}
    # Serialize before writing, and serialize revision creation across writers.
    canonical(payload)
    with project.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS research_records '
                   '(id TEXT PRIMARY KEY, supersedes TEXT UNIQUE, payload TEXT NOT NULL)')
        if previous:
            row = db.execute('SELECT payload FROM research_records WHERE id=?', (previous,)).fetchone()
            if row is None:
                raise LedgerError('Unknown superseded research record')
            prior = json.loads(row[0])
            if prior['kind'] != kind:
                raise LedgerError('A revision must retain the research record kind')
            if db.execute('SELECT 1 FROM research_records WHERE supersedes=?', (previous,)).fetchone():
                raise LedgerError('Revision already superseded; revise the latest version')
            payload['thread_id'] = prior['thread_id']
            payload['version'] = prior['version'] + 1
        else:
            payload['thread_id'] = identifier
            payload['version'] = 1
        db.execute('INSERT INTO research_records VALUES (?, ?, ?)',
                   (identifier, previous, canonical(payload)))
    return payload
