"""Bounded source corrections. Native locks own budget, CAS and complete patch validation."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid
from functools import wraps

from ocr_projects import ProjectError, atomic_json, source_hash
from ocr_quality import load, load_bound, bindings, check_bindings, patched_review, validate_review, snapshot
from ocr_project_output_review import output_identity, verify_output_review
from ocr_project_geometry import verify_committed_samples, identity, adapter_snapshot
from ocr_project_export import project_environment, workflow_command, WORKFLOW


def checked(action):
    @wraps(action)
    def invoke(*args, **kwargs):
        try:
            return action(*args, **kwargs)
        except ProjectError:
            raise
        except (OSError, ValueError, KeyError, TypeError, StopIteration, IndexError, AttributeError) as error:
            raise ProjectError('correction_invalid', str(error) or 'Choose an original correction cycle of this run.') from error
    return invoke


def ledger_path(work):
    return work / 'application/corrections/ledger.json'


def tool_snapshot(work):
    path = work / 'correction-code-snapshots' / (source_hash(Path(__file__)) + '.py')
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        shutil.copyfile(__file__, path)
    if source_hash(path) != source_hash(Path(__file__)):
        raise ValueError('Original correction adapter snapshot changed')
    return path


def failure_map(work):
    """Version 1 substantive identity excludes output UUID, timestamps and model prose."""
    findings = load(work / 'checks/findings.json')['items']
    samples = {r['id']: r for r in load(work / 'checks/geometry-samples.json')['samples']}
    result = {}
    for row in findings:
        key = row['id']
        if row.get('status') != 'open' or key == 'geometry/approximation':
            continue
        value = {'id': key, 'page': row.get('page'), 'bbox': row.get('bbox')}
        if key.startswith('sample/'):
            _, identifier, extractor = key.split('/')
            sample = samples[identifier]
            value.update(page=sample['page'], bbox=sample['bbox'], expected=sample['expected'],
                actual=sample[extractor + '_literal'], check=extractor)
        elif key.startswith('literal/'):
            _, page, extractor = key.split('/')
            value.update(actual=(work / f'checks/{extractor}-page-{page}.txt').read_text(),
                expected=(work / f'checks/expected-page-{page}.txt').read_text(), check=extractor)
        # Native source/geometry finding IDs retain their line/registry identity.
        result[key] = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return result


def current(registry, record, expected_iteration=None, expected_validation=None):
    work = registry.root / record['artifacts']['workspace']
    selected = output_identity(record, work)
    if expected_iteration is not None and selected['iteration_id'] != expected_iteration:
        raise ValueError('Selected export iteration changed')
    if expected_validation is not None and source_hash(work / 'checks/run-validation.json') != expected_validation:
        raise ValueError('Selected native validation changed')
    report = load(work / 'checks/run-validation.json')
    check_bindings(report['inputs'])
    if report['pdf_sha256'] != selected['pdf_sha256'] or record['project']['validation'] != report['status']:
        raise ValueError('Complete native validation is required for the current export')
    verify_output_review(registry, record['project']['project_id'])
    verify_committed_samples(registry, record)
    if source_hash(work / 'samples.json') != source_hash(work / 'geometry-source-samples.json'):
        raise ValueError('Frozen sample bytes differ')
    return work, selected, report


def targets(work):
    review = load(work / 'review.json')
    samples = {row['id']: row for row in load(work / 'checks/geometry-samples.json')['samples']}
    rows = load(work / 'checks/findings.json')['items']
    failures = failure_map(work)
    selected, line_ids = [], set()
    for row in rows:
        key = row['id']
        if key not in failures:
            continue
        relevant = []
        target = copy.deepcopy(row)
        if key.startswith('sample/') or key.startswith('literal/'):
            if key.startswith('sample/'):
                _, sample_id, extractor = key.split('/')
                sample = samples[sample_id]
                page, box = sample['page'], sample['bbox']
                target.update(page=page, bbox=box, expected=sample['expected'], actual=sample[extractor + '_literal'])
            else:
                page, box = int(key.split('/')[1]), None
                target.update(page=page)
                target.pop('bbox', None)
            for line in review['lines']:
                region = line['selection_region']
                if line['page'] == page and (box is None or
                        region[0] < box[2] and box[0] < region[2] and region[1] < box[3] and box[1] < region[3]):
                    relevant.append(line['id'])
        elif key.startswith('geometry/observed/lines/'):
            relevant = [key.rsplit('/', 1)[1]]
        elif key.startswith('source/unresolved/'):
            identifier = key[len('source/unresolved/'):]
            relevant = [r['line'] for r in review.get('unresolved', []) if r['id'] == identifier]
        if relevant:
            selected.append(target)
            line_ids.update(relevant)
    return review, selected, sorted(line_ids)


def reserve(registry, project_id, expected_iteration, expected_validation):
    try:
        with registry.project_lock(project_id) as record:
            work, selected, validation = current(registry, record, expected_iteration, expected_validation)
            path = ledger_path(work)
            ledger = load(path) if path.exists() else {'schema_version': 1, 'policy': 'targeted-corrections-v1',
                'run_id': project_id, 'source_sha256': selected['source_sha256'],
                'first_iteration_id': selected['iteration_id'], 'profile_sha256': source_hash(registry.root / record['artifacts']['profile_snapshot']),
                'frozen_samples_sha256': source_hash(work / 'samples.json'), 'cycles': [], 'stop_reason': None}
            if ledger['run_id'] != project_id or ledger['source_sha256'] != selected['source_sha256'] or any(
                    ledger[key] != digest for key, digest in (
                        ('profile_sha256', source_hash(registry.root / record['artifacts']['profile_snapshot'])),
                        ('frozen_samples_sha256', source_hash(work / 'samples.json')))):
                raise ValueError('Correction anchor source/profile/expectations changed')
            if any(cycle['state'] != 'settled' for cycle in ledger['cycles']):
                raise ProjectError('correction_reconciliation_required', 'Inspect the reserved original cycle; it must not be replayed or renumbered.')
            if len(ledger['cycles']) >= 3 or ledger.get('stop_reason'):
                raise ProjectError('correction_stopped', 'Saved correction budget or early stop is final; inspect the original evidence.')
            review, findings, line_ids = targets(work)
            if validation['errors']:
                raise ProjectError('correction_technical_failure', 'Native technical failure requires intervention; no model turn was sent.')
            if not findings:
                ledger['stop_reason'] = 'awaiting_input' if validation['open_items'] else 'completed'
                atomic_json(path, ledger)
                return record
            index = len(ledger['cycles']) + 1
            identifier = str(index) + '-' + uuid.uuid4().hex
            directory = path.parent / identifier
            directory.mkdir(parents=True)
            units = [u for u in review['units'] if set(u['line_ids']) & set(line_ids)]
            scope = sorted({key for unit in units for key in unit['line_ids']})
            images, source_crops, diagnostic_images = [], [], []
            from PIL import Image
            manifest = load(work / 'input-manifest.json')
            for line in review['lines']:
                if line['id'] not in scope:
                    continue
                page = next(p for p in manifest['pages'] if p['page'] == line['page'])
                raster = work / f"raster/page-{line['page']}.png"
                if source_hash(raster) != page['raster_sha256']:
                    raise ValueError('Original source raster changed')
                x0, y0, x1, y1 = line['selection_region']
                for finding in findings:
                    if finding.get('page') == line['page'] and finding.get('bbox'):
                        a, b, c, d = finding['bbox']
                        x0, y0, x1, y1 = min(x0, a), min(y0, b), max(x1, c), max(y1, d)
                name = directory / ('source-' + hashlib.sha256(line['id'].encode()).hexdigest()[:16] + '.png')
                with Image.open(raster) as image:
                    crop_box = [max(0, x0-20), max(0, y0-20), min(image.width, x1+20), min(image.height, y1+20)]
                    image.crop(crop_box).save(name)
                images.append({'path': str(name.relative_to(work)), 'sha256': source_hash(name)})
                source_crops.append({'line_id': line['id'], 'page': line['page'], 'bbox': crop_box,
                    'source_raster': {'path': str(raster.relative_to(work)), 'sha256': source_hash(raster)}, **images[-1]})
            old_lines = load(work / 'reviewed-lines.json')
            sheets = sorted({index//20+1 for index, row in enumerate(old_lines) if row['id'] in scope})
            for sheet in sheets:
                source_image = work / f'checks/geometry-review-{sheet:03}.png'
                target = directory / f'diagnostic-geometry-{sheet:03}.png'
                shutil.copyfile(source_image, target)
                images.append({'path': str(target.relative_to(work)), 'sha256': source_hash(target)})
                diagnostic_images.append({'kind': 'geometry_overlay', 'original_path': str(source_image.relative_to(work)), **images[-1]})
            names = ['review.json', 'output-manifest.json', 'checks/run-validation.json', 'checks/findings.json',
                'checks/technical.json', 'checks/geometry-samples.json', 'samples.json', 'geometry-source-samples.json',
                'geometry-sample-origin.json', 'output-review-publication.json']
            bound_inputs = {name: bindings(value=work / name)['value'] for name in names}
            bound_inputs['profile'] = bindings(value=registry.root / record['artifacts']['profile_snapshot'])['value']
            packet = {'schema_version': 1, 'cycle_id': identifier, 'index': index, 'identity': selected,
                'expected_review_sha256': selected['review_sha256'], 'expected_iteration_id': selected['iteration_id'],
                'target_finding_ids': [row['id'] for row in findings], 'findings': findings,
                'lines': [line for line in review['lines'] if line['id'] in scope], 'units': units, 'all_units': review['units'],
                'line_registries': {key: [row for row in review.get(key, []) if row['line'] in scope]
                    for key in ('unresolved', 'publisher_errors', 'risk_register')},
                'allowed_line_ids': scope, 'images': images, 'inputs': bound_inputs,
                'source_crops': source_crops, 'diagnostic_images': diagnostic_images,
                'profile_repair_prompt': load(registry.root / record['artifacts']['profile_snapshot'])['prompts']['repair'],
                'failure_signatures': failure_map(work)}
            atomic_json(directory / 'plan.json', packet)
            cycle = {'cycle_id': identifier, 'index': index,
                'parent_cycle_id': ledger['cycles'][-1]['cycle_id'] if ledger['cycles'] else None,
                'state': 'reserved', 'phase': 'reserved', 'source_iteration_id': selected['iteration_id'],
                'plan': str((directory / 'plan.json').relative_to(work)), 'plan_sha256': source_hash(directory / 'plan.json'),
                'owner_pid': os.getpid(), 'attempt_id': None}
            ledger['cycles'].append(cycle)
            atomic_json(path, ledger)
        return registry.get(project_id)
    except ProjectError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ProjectError('correction_invalid', str(error)) from error


@checked
def cycle_record(work, cycle_id):
    ledger = load(ledger_path(work))
    cycle = next(c for c in ledger['cycles'] if c['cycle_id'] == cycle_id)
    packet = load(work / cycle['plan'])
    if source_hash(work / cycle['plan']) != cycle['plan_sha256']:
        raise ValueError('Original repair plan changed')
    return ledger, cycle, packet


@checked
def bind_attempt(registry, project_id, cycle_id, attempt):
    with registry.project_lock(project_id) as record:
        work = registry.root / record['artifacts']['workspace']
        path = Path(attempt).resolve()
        if not path.is_relative_to((work / 'application/correction-attempts').resolve()):
            raise ProjectError('correction_invalid', 'Attempt must belong to this run.')
        value = load(path)
        ledger, cycle, _ = cycle_record(work, cycle_id)
        if cycle['state'] != 'reserved' or cycle.get('attempt_id') not in (None, value['attempt_id']) or value['run_id'] != project_id:
            raise ProjectError('correction_invalid', 'Cycle attempt identity cannot be replaced.')
        cycle.update(attempt_id=value['attempt_id'], attempt=str(path.relative_to(work)),
            owner_pid=value['owner_pid'], owner_start_ticks=value['owner_start_ticks'])
        atomic_json(ledger_path(work), ledger)
    return registry.get(project_id)


def validate_patch(work, packet, publication):
    from ocr_visual_evidence import verify_visual_turn
    check_bindings(packet['inputs'])
    check_bindings(publication['evidence'])
    previous_geometry = load(work / 'geometry-checkpoint.json')
    if any(publication[key] != previous_geometry[key] for key in ('runtime', 'context_runtime')):
        raise ValueError('Correction runtime differs from the original verified source/geometry runtime')
    for index, item in enumerate([*publication['runtime']['files'], *publication['context_runtime'].get('files', []),
            *publication['context_runtime'].get('interpreters', [])]):
        if 'sha256' in item and publication['evidence'].get('runtime_' + str(index)) != {'path': item['path'], 'sha256': item['sha256']}:
            raise ValueError('Exact original runtime resource evidence is required')
    answer = verify_visual_turn(publication['visual_turn'], work, packet['images'])
    if answer != load(publication['evidence']['proposal']['path']):
        raise ValueError('Proposal differs from original completed native assistant JSON')
    if any(answer[key] != packet[key] for key in ('expected_review_sha256', 'expected_iteration_id', 'target_finding_ids')):
        raise ValueError('Model patch source/iteration/target identity differs')
    from ocr_project_geometry import image_identity
    if [image_identity(work, i) for i in answer['images_examined']] != [image_identity(work, i) for i in packet['images']]:
        raise ValueError('Original targeted source images must all be examined')
    if {d['finding_id'] for d in answer['decisions']} != set(packet['target_finding_ids']):
        raise ValueError('Every target requires a specific source decision')
    allowed_images = {image_identity(work, i)[0] for i in packet['images']}
    for decision in answer['decisions']:
        if not decision['reason'].strip() or not decision['evidence'] or any(
                str((work / name).resolve()) not in allowed_images for name in decision['evidence']):
            raise ValueError('Correction rationale requires its original source image evidence')
    patch = answer['patch']
    if not isinstance(patch, dict) or set(patch) - {'lines', 'units', 'drop_lines', 'dropped_candidates'}:
        raise ValueError('Correction can change only native review data')
    original = load(work / 'review.json')
    changed = patched_review(original, patch)
    validate_review(work, changed)
    scope = set(packet['allowed_line_ids'])
    old_lines = {r['id']: r for r in original['lines']}
    new_lines = {r['id']: r for r in changed['lines']}
    if any(key not in scope and old_lines.get(key) != new_lines.get(key) for key in old_lines.keys() | new_lines.keys()):
        raise ValueError('Patch changes a line outside the targeted source scope')
    outside = lambda review: [(index, u) for index, u in enumerate(review['units']) if not set(u['line_ids']) & scope]
    if outside(original) != outside(changed):
        raise ValueError('Patch changes unrelated logical units')
    if original.get('publisher_errors', []) != changed.get('publisher_errors', []) or any(
            old_lines[r['line']]['text'] != new_lines.get(r['line'], {}).get('text') for r in original.get('publisher_errors', [])):
        raise ValueError('Readable printed publisher errors remain unchanged')
    for key in ('unresolved', 'risk_register'):
        if [r for r in original.get(key, []) if r['line'] not in scope] != [r for r in changed.get(key, []) if r['line'] not in scope]:
            raise ValueError('Patch changes unrelated source registries')
    if original.get('dropped_candidates', []) != changed.get('dropped_candidates', []):
        raise ValueError('Correction cannot silently change candidate accounting')
    return answer, changed != original


def publish(registry, project_id, cycle_id, proposal, *, check_only=False):
    try:
        with registry.project_lock(project_id) as record:
            work = registry.root / record['artifacts']['workspace']
            ledger, cycle, packet = cycle_record(work, cycle_id)
            if cycle['state'] != 'reserved':
                raise ValueError('Cycle already published or settled')
            current(registry, record, packet['expected_iteration_id'], packet['inputs']['checks/run-validation.json']['sha256'])
            publication = load(proposal)
            proposal_path = Path(proposal).resolve()
            if (proposal_path.parent.name != cycle.get('attempt_id') or
                    not proposal_path.is_relative_to((work / 'application/correction-attempts').resolve()) or
                    any(not Path(pointer['path']).resolve().is_relative_to(proposal_path.parent)
                        for pointer in (publication['evidence']['proposal'], publication['visual_turn']['protocol']))):
                raise ValueError('Original correction proposal and protocol must belong to the reserved run attempt')
            answer, changed = validate_patch(work, packet, publication)
            if check_only:
                return record
            if not changed:
                raise ProjectError('correction_no_valid_change', 'Original model proposal contains no valid change.')
            # Freeze ORIGINAL derived diagnostics and provider evidence before any data change.
            previous = snapshot(work)
            for name in ('review.json', 'samples.json', 'geometry-source-samples.json', 'geometry-sample-origin.json',
                    'geometry-preparation.json', 'geometry-checkpoint.json', 'review-patch-chain.json',
                    'output-review-preparation.json', 'output-review-publication.json',
                    'reviewed-lines.json', 'geometry.json', 'pages.json', 'segmented-review.json', 'segment-manifest.json',
                    'reading-publication.json', 'reading-first-publication-review.json'):
                if (work / name).is_file():
                    shutil.copy2(work / name, previous / name)
            for key in ('profile_snapshot', 'run_manifest'):
                shutil.copy2(registry.root / record['artifacts'][key], previous / (key + '.json'))
            for path in (work / 'correction-code-snapshots').glob('*.py'):
                target = previous / path.relative_to(work)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
            for namespace in ('reading-attempts', 'geometry-attempts', 'output-review-attempts', 'correction-attempts'):
                source = work / 'application' / namespace
                for path in source.rglob('*'):
                    if path.is_file() and path.suffix in ('.json', '.jsonl') and 'context' not in path.relative_to(source).parts:
                        target = previous / path.relative_to(work)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(path, target)
            for path in (work / 'output-review-inputs').rglob('*.json'):
                target = previous / path.relative_to(work)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
            # Corrected geometry uses fresh immutable crop IDs outside checks/.
            # Preserve those original model pixels before the NEXT cycle too.
            for path in (work / 'application/corrections').rglob('*'):
                if path.is_file() and path.name != 'ledger.json' and path.suffix in ('.json', '.png'):
                    target = previous / path.relative_to(work)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
            atomic_json(previous / 'project.json', record)
            archived = load(previous / 'snapshot.json')
            for path in previous.rglob('*'):
                if path.is_file() and path.name != 'snapshot.json':
                    archived['artifacts'][str(path.relative_to(previous))] = {'sha256': source_hash(path), 'stored': True}
            atomic_json(previous / 'snapshot.json', archived)
            patch = work / 'application/corrections' / cycle_id / 'native-patch.json'
            atomic_json(patch, answer['patch'])
            from ocr_project_review import patch_project
            patch_project(registry, project_id, patch, expected_review_sha256=packet['expected_review_sha256'], _record=record)
            cycle.update(state='published', phase='patch_published', previous_snapshot=str(previous.relative_to(work)),
                proposal=str(Path(publication['evidence']['proposal']['path']).relative_to(work)),
                publication=str(Path(proposal).relative_to(work)), review_sha256=source_hash(work / 'review.json'),
                patch=str(patch.relative_to(work)), patch_sha256=source_hash(patch),
                validator=bindings(value=tool_snapshot(work))['value'])
            atomic_json(ledger_path(work), ledger)
        return registry.get(project_id)
    except ProjectError:
        raise
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as error:
        raise ProjectError('correction_invalid', str(error)) from error


@checked
def settle(registry, project_id, cycle_id, *, reason=None):
    with registry.project_lock(project_id) as record:
        work = registry.root / record['artifacts']['workspace']
        ledger, cycle, packet = cycle_record(work, cycle_id)
        outcome = work / 'application/corrections' / cycle_id / 'outcome.json'
        if outcome.exists():
            raise ProjectError('correction_settled', 'Original cycle outcome is immutable.')
        report = load(work / 'checks/run-validation.json')
        failed = failure_map(work)
        if reason is None:
            if report['errors']:
                reason = 'technical_failure'
            elif any(key in failed and failed[key] == packet['failure_signatures'].get(key)
                    for key in packet['target_finding_ids']):
                reason = 'repeated_failure'
            elif len(ledger['cycles']) >= 3:
                reason = 'limit_reached'
            else:
                _, remaining, _ = targets(work)
                reason = None if remaining else 'awaiting_input' if report['open_items'] else 'completed'
        value = {'cycle_id': cycle_id, 'index': cycle['index'], 'stop_reason': reason,
            'iteration_id': load(work / 'output-manifest.json')['iteration_id'],
            'validation': record['project']['validation'], 'acceptance': record['project']['acceptance'],
            'failure_signatures': failed, 'validation_sha256': source_hash(work / 'checks/run-validation.json')}
        atomic_json(outcome, value)
        cycle.update(state='settled', phase='settled', outcome=str(outcome.relative_to(work)),
            outcome_sha256=source_hash(outcome), **{key: value[key] for key in ('stop_reason', 'iteration_id', 'validation', 'acceptance')})
        ledger['stop_reason'] = reason
        atomic_json(ledger_path(work), ledger)
    return registry.get(project_id)


@checked
def prepare_geometry(registry, project_id, cycle_id, *, environment=None):
    """Regenerate diagnostics only after the previous complete iteration was frozen."""
    with registry.project_lock(project_id) as record:
        work = registry.root / record['artifacts']['workspace']
        ledger, cycle, packet = cycle_record(work, cycle_id)
        if cycle['state'] != 'published' or source_hash(work / 'review.json') != cycle['review_sha256']:
            raise ProjectError('correction_invalid', 'A current validated correction publication is required.')
        check_bindings({k: v for k, v in packet['inputs'].items() if k in
            ('samples.json', 'geometry-source-samples.json', 'geometry-sample-origin.json', 'profile')})
        previous = work / cycle['previous_snapshot']
        archived = load(previous / 'snapshot.json')
        for name, row in archived['artifacts'].items():
            if row['stored'] and source_hash(previous / name) != row['sha256']:
                raise ProjectError('correction_invalid', 'Previous iteration snapshot changed.')
        native = project_environment(work, environment)
        workflow_command(work, native, 'segment', '--review', work / 'review.json')
        workflow_command(work, native, 'sheets', '--lines', work / 'reviewed-lines.json')
        workflow_command(work, native, 'sample-sheets', '--samples', work / 'samples.json')
        segmented = load(work / 'segment-manifest.json')
        lines = load(work / 'reviewed-lines.json')
        specs = load(work / 'samples.json')
        source_manifest = load(work / 'input-manifest.json')
        sample_manifest = load(work / 'checks/sample-source.json')
        sample_dir = Path(sample_manifest['samples'][0]['source_preview']).parent
        names = [f'checks/geometry-review-{i:03}.png' for i in range(1, (len(lines)+19)//20+1)]
        names += [str(sample_dir / f'sheet-{i:03}.png') for i in range(1, (len(specs)+9)//10+1)]
        names += [s['source_preview'] for s in sample_manifest['samples']]
        products = ['segment-manifest.json', 'segmented-review.json', 'pages.json', 'reviewed-lines.json',
            'geometry.json', 'segmentation-events.json', 'checks/unsupported-cells.json', 'checks/geometry-anomalies.json',
            'unresolved.json', 'publisher-errors.json', 'reconstructions.json', 'risk-register.json', 'samples.json',
            'geometry-source-samples.json', 'geometry-sample-origin.json', 'checks/sample-source.json', *names]
        old_lines = {row['id']: row for row in load(previous / 'reviewed-lines.json')}
        current_lines = {row['id']: row for row in lines}
        changed = {key for key in current_lines if current_lines[key] != old_lines.get(key)}
        # Full native segmentation stays whole-document. Only changed rows,
        # affected logical-unit context and page-local neighbors need a NEW turn.
        changed.update(packet['allowed_line_ids'])
        required = set(changed)
        for index, row in enumerate(lines):
            if row['id'] in changed:
                required.update(neighbor['id'] for neighbor in lines[max(0, index-1):index+2]
                    if neighbor['page'] == row['page'])
        affected_pages = {row['page'] for row in lines if row['id'] in required}
        examined_samples = [sample for sample in specs if sample['page'] in affected_pages]
        image_names = sorted({f'checks/geometry-review-{index//20+1:03}.png'
            for index, row in enumerate(lines) if row['id'] in required})
        image_names += [s['source_preview'] for s in sample_manifest['samples'] if s['page'] in affected_pages]
        from PIL import Image
        for row in lines:
            if row['id'] not in required:
                continue
            original = next(line for line in load(work / 'review.json')['lines'] if line['id'] == row['id'])
            x0, y0, x1, y1 = original['selection_region']
            raster = work / f"raster/page-{row['page']}.png"
            source_page = next(p for p in source_manifest['pages'] if p['page'] == row['page'])
            if source_hash(raster) != source_page['raster_sha256']:
                raise ProjectError('correction_invalid', 'Original source raster changed.')
            path = work / 'application/corrections' / cycle_id / ('geometry-source-' + hashlib.sha256(row['id'].encode()).hexdigest()[:16] + '.png')
            with Image.open(raster) as image:
                image.crop((max(0, x0-20), max(0, y0-20), min(image.width, x1+20), min(image.height, y1+20))).save(path)
            image_names.append(str(path.relative_to(work)))
        image_names = sorted(set(image_names))
        products += image_names
        scope = {'policy': 'changed-rows-neighbors-with-exact-prior-evidence-v1',
            'cycle_id': cycle_id, 'previous_snapshot': cycle['previous_snapshot'],
            'previous_checkpoint_sha256': source_hash(previous / 'geometry-checkpoint.json'),
            'previous_preparation_sha256': source_hash(previous / 'geometry-preparation.json'),
            'newly_examined_line_ids': sorted(required),
            'unchanged_line_ids': sorted(set(current_lines) - required),
            'newly_examined_sample_ids': sorted(s['id'] for s in examined_samples),
            'unchanged_sample_ids': sorted(s['id'] for s in specs if s not in examined_samples)}
        inputs = bindings(source=registry.root / record['artifacts']['source'], review=work / 'review.json',
            samples=work / 'geometry-source-samples.json', origin=work / 'geometry-sample-origin.json',
            environment=native.path, workflow=WORKFLOW, geometry_tool=adapter_snapshot(work),
            quality_tool=Path(__file__).with_name('ocr_quality.py'))
        inputs.update({'segment_' + k: v for k, v in segmented['inputs'].items()})
        inputs['correction_tool'] = bindings(value=tool_snapshot(work))['value']
        for key in ('profile_snapshot', 'run_manifest', 'reading_publication'):
            if key in record['artifacts']:
                inputs[key] = bindings(value=registry.root / record['artifacts'][key])['value']
        review = load(work / 'review.json')
        value = {'schema_version': 1, 'status': 'prepared_unexamined', 'identity': identity(registry, record),
            'native_environment': native.identity, 'inputs': inputs,
            'outputs': {name: source_hash(work / name) for name in products},
            'images': [{'path': name, 'sha256': source_hash(work / name)} for name in image_names],
            'logical_units': review['units'], 'source_samples': examined_samples, 'unresolved': review.get('unresolved', []),
            'source_risks': review.get('risk_register', []), 'required_lines': [line['id'] for line in lines if line['id'] in required],
            'unsupported_cells': [row for row in load(work / 'checks/unsupported-cells.json') if row['line'] in required],
            'geometry_anomalies': [row for row in load(work / 'checks/geometry-anomalies.json') if row['line'] in required],
            'correction_scope': scope,
            'geometry_status': 'approximation_requires_character_review', 'export_validation': 'not_run',
            'acceptance': 'separate_user_decision'}
        historical = historical_geometry_observations(work, value, preparing=True)
        value['historical_observations'] = [{'kind': kind, 'id': identifier, **record}
            for (kind, identifier), record in sorted(historical.items())]
        atomic_json(work / 'geometry-preparation.json', value)
        record['project'].update(phase='geometry_prepared', validation='not_run')
    return registry.get(project_id)


@checked
def historical_geometry_observations(work, packet, *, preparing=False):
    """Return prior observations with their ORIGINAL JSON and separate pixel aliases.

    Every unaffected row is byte-equivalent to the previous segmentation. A new
    model does not claim to have examined those rows or the old packet's images.
    """
    work = Path(work).resolve()
    seen = set()

    def collect(current_packet, current_directory):
        scope = current_packet.get('correction_scope')
        if not scope:
            return {}
        previous = (work / scope['previous_snapshot']).resolve()
        if not previous.is_relative_to(work / 'iterations') or previous in seen:
            raise ValueError('Invalid historical geometry iteration chain')
        seen.add(previous)
        archive = load(previous / 'snapshot.json')
        for name, row in archive['artifacts'].items():
            path = (previous / name).resolve()
            if not path.is_relative_to(previous):
                raise ValueError('Historical geometry artifact escapes its snapshot')
            if row['stored'] and source_hash(path) != row['sha256']:
                raise ValueError('Historical geometry snapshot changed')
        if (source_hash(previous / 'geometry-checkpoint.json') != scope['previous_checkpoint_sha256'] or
                source_hash(previous / 'geometry-preparation.json') != scope['previous_preparation_sha256']):
            raise ValueError('Original historical geometry checkpoint/preparation changed')
        old_packet = load(previous / 'geometry-preparation.json')
        checkpoint = load(previous / 'geometry-checkpoint.json')
        if any(old_packet['identity'][key] != current_packet['identity'][key] for key in ('project_id', 'run_id', 'source_sha256')):
            raise ValueError('Historical geometry belongs to a different source/run')
        if checkpoint['preparation_sha256'] != scope['previous_preparation_sha256']:
            raise ValueError('Historical geometry was bound to another preparation')
        from ocr_visual_evidence import verify_visual_turn
        answer = verify_visual_turn(checkpoint['visual_turn'], work, old_packet['images'], archive=previous)
        if answer != load_bound(checkpoint['evidence']['proposal']):
            raise ValueError('Historical observations differ from original native assistant JSON')
        if answer['preparation_sha256'] != scope['previous_preparation_sha256']:
            raise ValueError('Original historical model examined another packet')
        result = collect(old_packet, previous)
        for kind in ('lines', 'samples'):
            for row in answer[kind]:
                aliases = []
                for name in row['evidence']:
                    relative = str((work / name).resolve().relative_to(work))
                    stored = archive['artifacts'][relative]
                    aliases.append(str((previous / relative).relative_to(work)) if stored['stored'] else relative)
                result[(kind, row['id'])] = {'observation': row, 'evidence_aliases': aliases,
                    'checkpoint': {'path': str(previous / 'geometry-checkpoint.json'),
                        'sha256': scope['previous_checkpoint_sha256']},
                    'original_proposal': checkpoint['evidence']['proposal'], 'original_visual_turn': checkpoint['visual_turn']}
        actual_lines = {r['id']: r for r in load(current_directory / 'reviewed-lines.json')}
        previous_lines = {r['id']: r for r in load(previous / 'reviewed-lines.json')}
        required = set(current_packet['required_lines'])
        unchanged = set(scope['unchanged_line_ids'])
        if required != set(scope['newly_examined_line_ids']) or required & unchanged or required | unchanged != set(actual_lines):
            raise ValueError('New and historical line examination scopes are incomplete')
        for key in unchanged:
            if actual_lines[key] != previous_lines.get(key) or ('lines', key) not in result:
                raise ValueError('Changed line cannot inherit a prior geometry observation')
        current_specs = {r['id']: r for r in load(work / 'geometry-source-samples.json')}
        required_samples = {r['id'] for r in current_packet['source_samples']}
        unchanged_samples = set(scope['unchanged_sample_ids'])
        if required_samples != set(scope['newly_examined_sample_ids']) or required_samples & unchanged_samples or required_samples | unchanged_samples != set(current_specs):
            raise ValueError('New and historical source-sample scopes are incomplete')
        for key in unchanged_samples:
            if ('samples', key) not in result:
                raise ValueError('Source sample lacks original geometry evidence')
        return {key: value for key, value in result.items() if key[1] in (unchanged if key[0] == 'lines' else unchanged_samples)}

    result = collect(packet, work)
    expected = [{'kind': kind, 'id': identifier, **record} for (kind, identifier), record in sorted(result.items())]
    if not preparing and packet.get('historical_observations') != expected:
        raise ValueError('Historical observations differ from original native JSON/protocol/pixel evidence')
    return result
