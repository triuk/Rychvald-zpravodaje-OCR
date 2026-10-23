"""Native correction export intent; the iteration is reserved before any output."""
from pathlib import Path
import shutil
import uuid

from ocr_projects import atomic_json, source_hash
from ocr_quality import load, bindings, check_bindings
from ocr_project_corrections import checked, cycle_record, ledger_path


def expected_inputs(registry, record, work, cycle):
    previous = (work / cycle['previous_snapshot']).resolve()
    if not previous.is_relative_to(work / 'iterations'):
        raise ValueError('Export ancestor escaped its correction run')
    return bindings(source=registry.root / record['artifacts']['source'], review=work / 'review.json',
        geometry_checkpoint=work / 'geometry-checkpoint.json', geometry_preparation=work / 'geometry-preparation.json',
        previous_snapshot=previous / 'snapshot.json', previous_output=previous / 'output-manifest.json',
        plan=work / cycle['plan'])


def verify_intent(registry, record, work, cycle, value):
    identifier = value['iteration_id']
    if not isinstance(identifier, str) or len(identifier) != 32 or any(c not in '0123456789abcdef' for c in identifier):
        raise ValueError('Invalid reserved export iteration')
    pdf = registry.root / 'outputs' / (record['project']['project_id'] + '-' + identifier + '-ocr.pdf')
    if (value['schema_version'] != 1 or value['cycle_id'] != cycle['cycle_id'] or
            value['attempt_id'] != cycle['attempt_id'] or value['source_iteration_id'] != cycle['source_iteration_id'] or
            value['pdf'] != str(pdf) or value['txt'] != str(pdf.with_suffix('.txt')) or
            value['inputs'] != expected_inputs(registry, record, work, cycle)):
        raise ValueError('Export intent differs from its exact correction/geometry/ancestor')
    check_bindings(value['inputs'])
    return value


def reserve_locked(registry, record, work, cycle_id):
    from ocr_project_geometry import verify_geometry
    packet = verify_geometry(registry, record)
    ledger, cycle, _ = cycle_record(work, cycle_id)
    if (cycle['state'] != 'published' or packet.get('correction_scope', {}).get('cycle_id') != cycle_id or
            source_hash(work / 'review.json') != cycle['review_sha256']):
        raise ValueError('Export requires the same published correction and examined geometry')
    path = work / 'application/corrections' / cycle_id / 'export-intent.json'
    if path.exists():
        if cycle.get('export_intent_sha256') and source_hash(path) != cycle['export_intent_sha256']:
            raise ValueError('Original export intent changed')
        value = verify_intent(registry, record, work, cycle, load(path))
    else:
        if cycle.get('export_intent') or cycle.get('exported_iteration_id'):
            raise ValueError('Original reserved export intent is missing')
        identifier = uuid.uuid4().hex
        pdf = registry.root / 'outputs' / (record['project']['project_id'] + '-' + identifier + '-ocr.pdf')
        value = {'schema_version': 1, 'cycle_id': cycle_id, 'attempt_id': cycle['attempt_id'],
            'source_iteration_id': cycle['source_iteration_id'], 'iteration_id': identifier,
            'pdf': str(pdf), 'txt': str(pdf.with_suffix('.txt')), 'inputs': expected_inputs(registry, record, work, cycle)}
        atomic_json(path, value)
    cycle.update(export_intent=str(path.relative_to(work)), export_intent_sha256=source_hash(path))
    if not cycle.get('exported_iteration_id'):
        cycle['phase'] = 'export_reserved'
    atomic_json(ledger_path(work), ledger)
    return value


@checked
def prepare(registry, run_id, cycle_id):
    with registry.project_lock(run_id) as record:
        work = (registry.root / record['artifacts']['workspace']).resolve()
        reserve_locked(registry, record, work, cycle_id)
    return registry.get(run_id)


def stage_paths(work, intent):
    directory = work / 'application/corrections' / intent['cycle_id'] / 'export-stage'
    return {'pdf': directory / 'result.pdf', 'txt': directory / 'result.txt'}


def verify_rendered(registry, record, work, cycle, intent, value):
    verify_intent(registry, record, work, cycle, intent)
    staged = stage_paths(work, intent)
    if any(value[key] != expected for key, expected in {
            'project_id': record['project']['project_id'], 'run_id': record['project']['run_id'],
            'iteration_id': intent['iteration_id'], 'review_sha256': cycle['review_sha256'],
            'source_sha256': record['project']['source_sha256']}.items()):
        raise ValueError('Rendered export differs from its reserved iteration/source')
    for key, stage in staged.items():
        if value[key] != str(stage):
            raise ValueError('Rendered export escaped its owned staging paths')
        candidates = (stage, Path(intent[key]))
        if not any(p.is_file() and not p.is_symlink() and source_hash(p) == value[key + '_sha256'] for p in candidates):
            raise ValueError('Rendered export bytes changed: ' + key)
    check_bindings(value['inputs'])
    if value['examined_geometry'] != {
            'checkpoint_sha256': intent['inputs']['geometry_checkpoint']['sha256'],
            'preparation_sha256': intent['inputs']['geometry_preparation']['sha256'],
            'source_samples_sha256': source_hash(work / 'geometry-source-samples.json')}:
        raise ValueError('Rendered export differs from the exact examined geometry')
    return value


def normalize_native_render(registry, record, work, cycle, intent, raw):
    """Validate a complete native render that stopped before its local envelope."""
    from ocr_project_export import WORKFLOW
    expected = {'project_id': record['project']['project_id'], 'run_id': record['project']['run_id'],
        'iteration_id': intent['iteration_id'], 'review_sha256': cycle['review_sha256'],
        'examined_geometry': {'checkpoint_sha256': intent['inputs']['geometry_checkpoint']['sha256'],
            'preparation_sha256': intent['inputs']['geometry_preparation']['sha256'],
            'source_samples_sha256': source_hash(work / 'geometry-source-samples.json')}}
    if (raw['tool_sha256'] != source_hash(WORKFLOW) or
            raw['generator_sha256'] != source_hash(WORKFLOW.with_name('ocr_f_layer.py')) or
            raw['source'] != str(registry.root / record['artifacts']['source']) or
            any(key in raw and raw[key] != value for key, value in expected.items())):
        raise ValueError('Incomplete native render does not match the reserved generator/inputs')
    return verify_rendered(registry, record, work, cycle, intent, {**raw, **expected})


def render_locked(registry, record, work, intent, native, examined, previous):
    """Render once into owned staging, retaining the last published output."""
    from ocr_project_export import workflow_command
    ledger, cycle, _ = cycle_record(work, intent['cycle_id'])
    path = work / 'application/corrections' / intent['cycle_id'] / 'export-rendered.json'
    value = None
    if path.exists():
        if cycle.get('export_rendered_sha256') and source_hash(path) != cycle['export_rendered_sha256']:
            raise ValueError('Original rendered export manifest changed')
        value = verify_rendered(registry, record, work, cycle, intent, load(path))
    staged = stage_paths(work, intent)
    staged['pdf'].parent.mkdir(parents=True, exist_ok=True)
    current_path = work / 'output-manifest.json'
    current = load(current_path)
    if value is None and all(current.get(key) == str(stage) for key, stage in staged.items()):
        value = normalize_native_render(registry, record, work, cycle, intent, current)
    if value is None and any(p.exists() for p in staged.values()):
        # A process stopped before a complete native manifest. Preserve every
        # partial byte; retry only this intent's derived staging outputs.
        interrupted = path.parent / 'export-interrupted' / uuid.uuid4().hex
        interrupted.mkdir(parents=True)
        for name in ('output-manifest.json', 'exported-pages.json', 'exported-review.json', 'export-inputs.json'):
            if (work / name).is_file():
                shutil.copy2(work / name, interrupted / name)
        for key, stage in staged.items():
            if stage.exists():
                stage.rename(interrupted / ('partial-' + key))
        atomic_json(work / 'output-manifest.json', load(previous / 'output-manifest.json'))
    if value is None:
        workflow_command(work, native, 'export', '--source', registry.root / record['artifacts']['source'],
            '--pages', work / 'pages.json', '--pdf', staged['pdf'], '--txt', staged['txt'], '--previous-snapshot', previous)
        value = normalize_native_render(registry, record, work, cycle, intent, load(current_path))
    if all(load(current_path).get(key) == str(stage) for key, stage in staged.items()):
        raw = path.with_name('raw-native-manifest-' + source_hash(current_path) + '.json')
        if not raw.exists():
            shutil.copy2(current_path, raw)
    if not path.exists():
        atomic_json(path, value)
    # This phase publishes only immutable staging proof. The old output remains
    # the current public iteration until the separate native commit.
    if load(current_path).get('iteration_id') != intent['iteration_id']:
        atomic_json(current_path, load(previous / 'output-manifest.json'))
    cycle.update(export_rendered=str(path.relative_to(work)),
        export_rendered_sha256=source_hash(path))
    if not cycle.get('exported_iteration_id'):
        cycle['phase'] = 'export_rendered'
    atomic_json(ledger_path(work), ledger)
    return value


def commit_artifacts(work, intent, rendered):
    value = dict(rendered)
    for key, stage in stage_paths(work, intent).items():
        final = Path(intent[key])
        if final.exists():
            if final.is_symlink() or source_hash(final) != rendered[key + '_sha256']:
                raise ValueError('Refuse to replace unrelated output at the reserved export path')
        else:
            final.parent.mkdir(parents=True, exist_ok=True)
            stage.rename(final)
        value[key] = str(final)
    return value


@checked
def render(registry, run_id, cycle_id, *, environment=None):
    record = registry.get(run_id)
    work = registry.root / record['artifacts']['workspace']
    _, cycle, _ = cycle_record(work, cycle_id)
    from ocr_project_export import export_project
    return export_project(registry, run_id, environment=environment,
        geometry_checkpoint=work / 'geometry-checkpoint.json',
        previous_snapshot=work / cycle['previous_snapshot'], _render_only=True)
