"""Verify and adopt the exact original cycle outcome without revalidation."""
from pathlib import Path

from ocr_projects import atomic_json, source_hash
from ocr_quality import load
from ocr_project_corrections import checked, cycle_record, failure_map, ledger_path


def outcome_path(work, cycle):
    return work / 'application/corrections' / cycle['cycle_id'] / 'outcome.json'


def verify_saved(work, cycle, artifacts, project):
    path = outcome_path(work, cycle)
    value = load(path)
    if set(value) != {'cycle_id', 'index', 'stop_reason', 'iteration_id', 'validation', 'acceptance',
            'failure_signatures', 'validation_sha256'}:
        raise ValueError('Original correction outcome has an invalid shape')
    report = load(artifacts / 'checks/run-validation.json')
    if (value['cycle_id'] != cycle['cycle_id'] or value['index'] != cycle['index'] or
            value['iteration_id'] != load(artifacts / 'output-manifest.json')['iteration_id'] or
            value['validation_sha256'] != source_hash(artifacts / 'checks/run-validation.json') or
            value['validation'] != report['status'] or value['failure_signatures'] != failure_map(artifacts) or
            value['stop_reason'] not in (None, 'technical_failure', 'repeated_failure', 'limit_reached',
                'awaiting_input', 'completed', 'no_valid_change', 'invalid_patch')):
        raise ValueError('Original correction outcome differs from its exact iteration/validation/findings')
    if cycle['state'] == 'settled':
        if (cycle.get('outcome') != str(path.relative_to(work)) or source_hash(path) != cycle.get('outcome_sha256') or
                any(cycle.get(key) != value[key] for key in ('stop_reason', 'iteration_id', 'validation', 'acceptance'))):
            raise ValueError('Committed original correction outcome changed')
    elif value['validation'] != project['validation'] or value['acceptance'] != project['acceptance']:
        raise ValueError('Project changed before its original correction outcome committed')
    return value


def verify_all(work, record, cycles):
    pending = False
    archives = [work / row['previous_snapshot'] for row in cycles if row.get('previous_snapshot')]
    for row in cycles:
        path = outcome_path(work, row)
        if not path.exists() and row['state'] != 'settled':
            continue
        value = load(path)
        candidates = [archive for archive in archives
            if load(archive / 'output-manifest.json')['iteration_id'] == value['iteration_id']]
        artifacts = candidates[0] if candidates else work
        project = load(artifacts / 'project.json')['project'] if artifacts != work else record['project']
        verify_saved(work, row, artifacts, project)
        if row is not cycles[-1] and value['stop_reason'] is not None:
            raise ValueError('A new cycle followed an immutable early stop')
        if row is cycles[-1] and row['state'] == 'settled' and record is not None:
            if load(ledger_path(work))['stop_reason'] != value['stop_reason']:
                raise ValueError('Original correction stop reason changed')
        pending = pending or row['state'] != 'settled'
    return pending


@checked
def adopt(registry, run_id, cycle_id):
    with registry.project_lock(run_id) as record:
        work = (registry.root / record['artifacts']['workspace']).resolve()
        ledger, cycle, _ = cycle_record(work, cycle_id)
        from ocr_correction_resume import verify
        verify(registry, run_id, cycle['attempt_id'], source_hash(ledger_path(work)))
        value = verify_saved(work, cycle, work, record['project'])
        if cycle['state'] == 'settled':
            return record
        path = outcome_path(work, cycle)
        cycle.update(state='settled', phase='settled', outcome=str(path.relative_to(work)),
            outcome_sha256=source_hash(path), **{key: value[key] for key in ('stop_reason', 'iteration_id', 'validation', 'acceptance')})
        ledger['stop_reason'] = value['stop_reason']
        atomic_json(ledger_path(work), ledger)
    return registry.get(run_id)
