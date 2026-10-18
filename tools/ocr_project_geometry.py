"""Hash-bound native geometry preparation; generating sheets asserts no visual work."""
from pathlib import Path
import hashlib
import json
import re
import shutil

from ocr_projects import ProjectError, atomic_json, source_hash
from ocr_quality import load, validate_review, bbox, unique, bindings, check_bindings
from ocr_project_export import project_environment, workflow_command, WORKFLOW


def identity(registry, record):
    work = registry.root / record['artifacts']['workspace']
    result = {key: record['project'][key] for key in ('project_id', 'run_id', 'source_sha256')}
    result['review_sha256'] = source_hash(work / 'review.json')
    for name in ('profile_snapshot', 'run_manifest'):
        if name in record['artifacts']:
            result[name + '_sha256'] = source_hash(registry.root / record['artifacts'][name])
    return result


def prepare_geometry(registry, project_id, samples, *, environment=None, provenance=None):
    with registry.project_lock(project_id) as record:
        work = registry.root / record['artifacts']['workspace']
        try:
            native = project_environment(work, environment)
            source = registry.root / record['artifacts']['source']
            if source_hash(source) != record['project']['source_sha256']:
                raise ValueError('Registered source changed')
            review = load(work / 'review.json')
            validate_review(work, review)
            if review['source_sha256'] != record['project']['source_sha256']:
                raise ValueError('Wrong source review')
            manifest = load(work / 'input-manifest.json')
            specs = load(samples)
            if not isinstance(specs, list) or not specs:
                raise ValueError('Nonempty independent source samples required')
            unique(specs, 'source sample')
            for sample in specs:
                bbox(sample['bbox'], sample['page'], manifest)
                if (not re.fullmatch(r'[A-Za-z0-9_-]+', sample['id']) or
                    not isinstance(sample.get('expected'), str) or not sample.get('expected_origin')):
                    raise ValueError('Invalid source sample')
            if {s['page'] for s in specs} != {p['page'] for p in manifest['pages']}:
                raise ValueError('Source samples must cover every page')
            # A new iteration cannot quietly change previously committed expectations.
            saved = work / 'geometry-source-samples.json'
            if saved.exists() and saved.read_bytes() != Path(samples).read_bytes():
                raise ValueError('Preserve the original committed source sample bytes')
            if not saved.exists():
                shutil.copyfile(samples, saved)
            if (work / 'output-manifest.json').exists():
                raise ValueError('Geometry expectations must be frozen before first export')
            if (work / 'samples.json').resolve() != Path(samples).resolve():
                shutil.copyfile(samples, work / 'samples.json')
            elif source_hash(saved) != source_hash(work / 'samples.json'):
                raise ValueError('Source sample copy differs')
            origin = work / 'geometry-sample-origin.json'
            if provenance is not None:
                shutil.copyfile(provenance, origin)
            else:
                atomic_json(origin, {'kind': 'native_source_samples_require_application_provenance',
                    'samples_sha256': source_hash(saved), 'source_sha256': record['project']['source_sha256']})
            workflow_command(work, native, 'segment', '--review', work / 'review.json')
            workflow_command(work, native, 'sheets', '--lines', work / 'reviewed-lines.json')
            workflow_command(work, native, 'sample-sheets', '--samples', work / 'samples.json')
            segmented = load(work / 'segment-manifest.json')
            check_bindings(segmented['inputs'])
            lines = load(work / 'reviewed-lines.json')
            sample_manifest = load(work / 'checks/sample-source.json')
            sample_dir = Path(sample_manifest['samples'][0]['source_preview']).parent
            names = [f'checks/geometry-review-{i:03}.png' for i in range(1, (len(lines)+19)//20+1)]
            names += [str(sample_dir / f'sheet-{i:03}.png') for i in range(1, (len(specs)+9)//10+1)]
            names += [s['source_preview'] for s in sample_manifest['samples']]
            names += [f"raster/page-{p['page']}.png" for p in manifest['pages']]
            images = [{'path': name, 'sha256': source_hash(work / name)} for name in names]
            products = ['segment-manifest.json', 'segmented-review.json', 'pages.json', 'reviewed-lines.json',
                'geometry.json', 'segmentation-events.json', 'checks/unsupported-cells.json',
                'checks/geometry-anomalies.json', 'unresolved.json', 'publisher-errors.json',
                'reconstructions.json', 'risk-register.json', 'samples.json', 'geometry-source-samples.json',
                'geometry-sample-origin.json', 'checks/sample-source.json', *names]
            inputs = bindings(source=source, review=work/'review.json', samples=saved,
                origin=origin, environment=native.path, workflow=WORKFLOW,
                geometry_tool=Path(__file__), quality_tool=Path(__file__).with_name('ocr_quality.py'))
            inputs.update({'segment_' + k: v for k, v in segmented['inputs'].items()})
            for key in ('profile_snapshot', 'run_manifest', 'reading_publication'):
                if key in record['artifacts']:
                    inputs[key] = bindings(value=registry.root / record['artifacts'][key])['value']
            value = {'schema_version': 1, 'status': 'prepared_unexamined', 'identity': identity(registry, record),
                'native_environment': native.identity, 'inputs': inputs,
                'outputs': {name: source_hash(work / name) for name in products}, 'images': images,
                'logical_units': review['units'], 'source_samples': specs,
                'unresolved': review.get('unresolved', []), 'source_risks': review.get('risk_register', []),
                'required_lines': [line['id'] for line in lines],
                'unsupported_cells': load(work / 'checks/unsupported-cells.json'),
                'geometry_anomalies': load(work / 'checks/geometry-anomalies.json'),
                'geometry_status': 'approximation_requires_character_review', 'export_validation': 'not_run',
                'acceptance': 'separate_user_decision'}
            atomic_json(work / 'geometry-preparation.json', value)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ProjectError('geometry_invalid', str(error)) from error
        record['project'].update(phase='geometry_prepared', operation_state='completed', validation='not_run')
        record['artifacts']['geometry_preparation'] = str((work / 'geometry-preparation.json').relative_to(registry.root))
        record['counts'].update(geometry_lines=len(lines), geometry_samples=len(specs))
    return registry.get(project_id)


def verify_geometry(registry, record, *, examined=True):
    work = registry.root / record['artifacts']['workspace']
    try:
        packet = load(work / 'geometry-preparation.json')
        if packet['identity'] != identity(registry, record):
            raise ValueError('Geometry belongs to another run or review')
        check_bindings(packet['inputs'])
        for name, digest in packet['outputs'].items():
            path = (work / name).resolve()
            if not path.is_relative_to(work.resolve()) or source_hash(path) != digest:
                raise ValueError('Changed geometry artifact: ' + name)
        if examined:
            proof = load(work / 'geometry-checkpoint.json')
            if proof['preparation_sha256'] != source_hash(work / 'geometry-preparation.json'):
                raise ValueError('Examined geometry differs from current preparation')
            check_bindings(proof['evidence'])
            from ocr_visual_evidence import verify_visual_turn
            observations = verify_visual_turn(proof['visual_turn'], work, packet['images'])
            if observations != load(Path(proof['evidence']['proposal']['path'])):
                raise ValueError('Saved observations differ from original completed assistant JSON')
            packet['preparation_sha256'] = source_hash(work / 'geometry-preparation.json')
            validate_observations(packet, observations)
        return packet
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ProjectError('geometry_invalid', str(error)) from error


def validate_observations(packet, proposal):
    if proposal['preparation_sha256'] != packet['preparation_sha256']:
        raise ValueError('Observation preparation identity differs')
    if proposal['images_examined'] != packet['images']:
        raise ValueError('Every original, overlay and source sample image must actually be examined')
    if proposal['logical_units'] != packet['logical_units']:
        raise ValueError('Logical reading order differs; apply a validated correction first')
    lines = unique(proposal['lines'], 'geometry observation')
    if set(lines) != set(packet['required_lines']):
        raise ValueError('Every source line needs its own geometric observation')
    samples = unique(proposal['samples'], 'source sample observation')
    if set(samples) != {s['id'] for s in packet['source_samples']}:
        raise ValueError('Every independent sample needs a source-boundary observation')
    allowed_images = {i['path'] for i in packet['images']}
    for observation in [*lines.values(), *samples.values()]:
        if (observation['status'] not in ('examined_approximate', 'open') or not observation['reason'].strip() or
            not observation['evidence'] or not set(observation['evidence']) <= allowed_images):
            raise ValueError('Observations need specific honest decisions and original image evidence')
    for finding in [*packet['unsupported_cells'], *packet['geometry_anomalies']]:
        if lines[finding['line']]['status'] != 'open':
            raise ValueError('Automatic geometry finding must remain open pending validated correction')
    if proposal['geometry_status'] != 'approximation_requires_character_review':
        raise ValueError('Diagnostic examination does not prove glyph identity')


def publish_geometry(registry, project_id, checkpoint):
    with registry.project_lock(project_id) as record:
        work = registry.root / record['artifacts']['workspace']
        packet = verify_geometry(registry, record, examined=False)
        value = load(checkpoint)
        packet['preparation_sha256'] = source_hash(work / 'geometry-preparation.json')
        check_bindings(value['evidence'])
        from ocr_visual_evidence import verify_visual_turn
        proposal = verify_visual_turn(value['visual_turn'], work, packet['images'])
        if proposal != load(value['evidence']['proposal']['path']):
            raise ProjectError('geometry_invalid', 'Original model-authored observations differ')
        try:
            validate_observations(packet, proposal)
        except (ValueError, KeyError, TypeError) as error:
            raise ProjectError('geometry_invalid', str(error)) from error
        if value['preparation_sha256'] != packet['preparation_sha256']:
            raise ProjectError('geometry_invalid', 'Geometry changed before publication')
        atomic_json(work / 'geometry-checkpoint.json', value)
        record['project'].update(phase='geometry_examined', operation_state='completed', validation='not_run')
        record['counts']['geometry_open_items'] = sum(o['status'] == 'open' for o in proposal['lines']+proposal['samples'])
        record['artifacts']['geometry_checkpoint'] = str((work / 'geometry-checkpoint.json').relative_to(registry.root))
    return registry.get(project_id)
