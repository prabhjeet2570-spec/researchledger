"""Run a synthetic evidence workflow in a new directory, using the public SDK."""

import argparse
import json
from pathlib import Path
import shutil

from researchledger import LedgerError, Project, inspect_project


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def workflow(destination):
    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=False)  # Never adopt an existing research directory.
    shutil.copyfile(Path(__file__).with_name('integrate.py'), root / 'integrate.py')
    # A fabricated public fixture, explicitly labeled synthetic rather than a real study.
    (root / 'prior.csv').write_text('intervals,reported_estimate\n1,0.5\n', encoding='utf-8')
    write_json(root / 'config.json', {'intervals': 8})
    inventory = inspect_project(root, max_entries=100)
    write_json(root / 'inventory.json', inventory)
    write_json(root / 'capture-plan.json', {
        'status': 'explicit_selection_for_synthetic_demo',
        'sources': ['integrate.py', 'config.json'],
        'historical_artifacts': [{'path': 'prior.csv', 'role': 'synthetic prior-result fixture'}],
        'gaps': ['Prior execution was not observed; fixture is not a real historical study'],
        'basis': 'Known example filenames and explicitly generated contents; no inferred relationships',
    })
    project = Project.init(root, 'Synthetic quadrature workflow')
    history = project.import_history({
        'question': 'What does the synthetic prior-result fixture report?',
        'artifacts': [{'path': 'prior.csv', 'role': 'synthetic prior-result fixture'}],
        'claims': {'reported_estimate': 0.5},
        'context': {'synthetic': True},
        'gaps': ['Original executed code and environment unavailable; synthetic demonstration only'],
    })

    def execute(intervals, parent):
        config = {'intervals': intervals}
        write_json(root / 'config.json', config)
        record = project.record('Estimate the integral of x squared on [0, 1]',
            ['integrate.py', 'config.json'], config=config, parent=parent,
            gaps=['Stdlib-only example; cross-platform floating-point identity not guaranteed'])
        run = project.execute(record['id'], 'integrate.py',
            outputs=['request.json', 'metrics.json'], timeout=10)
        return record, run

    coarse, coarse_run = execute(8, history['id'])
    if coarse_run['status'] != 'succeeded':
        raise LedgerError('Coarse numerical example did not succeed; inspect saved run logs')
    first = project.add_research_record({
        'kind': 'decision', 'statement': 'Refine the grid from 8 to 64 intervals',
        'rationale': 'The coarse trapezoidal estimate can be compared with the analytic integral',
        'scope': 'Synthetic x-squared quadrature on [0, 1]',
        'evidence': [{'record_id': coarse['id'], 'run_id': coarse_run['id']}],
        'uncertainties': ['One deterministic example does not validate other scientific workloads'],
    })
    refined, refined_run = execute(64, coarse['id'])
    if refined_run['status'] != 'succeeded':
        raise LedgerError('Refined numerical example did not succeed; inspect saved run logs')
    # Demonstrate a genuine input-validation failure, not a faulty numerical implementation.
    rejected, rejected_run = execute(0, refined['id'])
    if rejected_run['status'] != 'failed':
        raise LedgerError('Invalid quadrature configuration was not rejected as expected')
    errors = project.verify() + project.verify_runs()
    if errors:
        raise LedgerError('Saved evidence failed integrity verification: ' + json.dumps(errors))

    def metrics(run):
        path = project.directory / 'runs' / run['id'] / 'artifacts' / 'metrics.json'
        return json.loads(path.read_text())

    coarse_metrics, refined_metrics = metrics(coarse_run), metrics(refined_run)
    second = project.add_research_record({
        'kind': 'decision', 'supersedes': first['id'],
        'statement': 'Retain the 64-interval estimate for this demonstration',
        'rationale': f"Measured absolute error changed from {coarse_metrics['absolute_error']} "
                     f"to {refined_metrics['absolute_error']}; zero intervals was rejected",
        'scope': 'Synthetic x-squared quadrature on [0, 1]',
        'evidence': [{'record_id': refined['id'], 'run_id': refined_run['id']},
                     {'record_id': rejected['id'], 'run_id': rejected_run['id']}],
        'uncertainties': ['This judgment is a declaration, not independent scientific confirmation'],
    })
    exported = project.export(root / 'evidence.zip')
    if not exported['integrity_ok']:
        raise LedgerError('Evidence export reported integrity gaps')
    summary = {'project': str(root), 'historical_record': history['id'],
               'successful_runs': [coarse_run['id'], refined_run['id']],
               'rejected_run': rejected_run['id'], 'decision_versions': [first['id'], second['id']],
               'coarse_metrics': coarse_metrics, 'refined_metrics': refined_metrics,
               'export': exported,
               'limitations': ['Synthetic CPU example; no GPU or scheduler jobs',
                               'No checkpoint resume, automatic output reuse or dependency restoration']}
    write_json(root / 'summary.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', help='New directory for synthetic project and evidence')
    args = parser.parse_args()
    try:
        print(json.dumps(workflow(args.destination), indent=2))
    except (OSError, LedgerError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
