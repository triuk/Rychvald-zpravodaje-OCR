"""Ledger-bound local review transaction; recovery never applies a second patch."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile

from ocr_projects import atomic_json, source_hash
from ocr_quality import load, bindings, check_bindings, patched_review, validate_review
from ocr_project_corrections import checked, cycle_record, ledger_path, tool_snapshot


def intent_path(work, cycle):
    return work / 'application/corrections' / cycle['cycle_id'] / 'patch-intent.json'


def has_intent(work, cycle):
    path = intent_path(work, cycle)
    return path.exists() or path.is_symlink()


def reserve_intent(registry, record, work, ledger, cycle, packet, publication, previous, patch, transaction):
    path = intent_path(work, cycle)
    if path.exists():
        raise ValueError('Original patch transaction requires explicit recovery')
    writes = {}
    for name, content in transaction['writes'].items():
        target = work / name
        digest = hashlib.sha256(content.encode()).hexdigest()
        if target.is_symlink() or (name.startswith('review-history/') and target.exists() and source_hash(target) != digest):
            raise ValueError('Original review history must remain immutable')
        writes[name] = {'content': content, 'sha256': digest,
            'previous_sha256': source_hash(target) if target.exists() else None}
    value = {'schema_version': 1, 'cycle_id': cycle['cycle_id'], 'attempt_id': cycle['attempt_id'],
        'plan_sha256': cycle['plan_sha256'], 'previous_snapshot': str(previous.relative_to(work)),
        'snapshot_sha256': source_hash(previous / 'snapshot.json'),
        'inputs': bindings(publication=publication, patch=patch, validator=tool_snapshot(work)),
        'project_before_sha256': source_hash(registry.root / record['artifacts']['project']),
        'record': transaction['record'], 'writes': writes}
    atomic_json(path, value)
    cycle.update(patch_intent=str(path.relative_to(work)), patch_intent_sha256=source_hash(path), phase='patch_reserved')
    atomic_json(ledger_path(work), ledger)


def verify_intent(registry, record, work, cycle, packet):
    path = intent_path(work, cycle)
    orphan = 'patch_intent' not in cycle and 'patch_intent_sha256' not in cycle
    if path.is_symlink() or (orphan and (cycle['state'] != 'reserved' or cycle['phase'] != 'reserved')):
        raise ValueError('Original orphan patch is not an untouched reserved transaction')
    if not orphan and (cycle.get('patch_intent') != str(path.relative_to(work)) or source_hash(path) != cycle.get('patch_intent_sha256')):
        raise ValueError('Original patch transaction binding changed')
    value = load(path)
    if (value['schema_version'] != 1 or value['cycle_id'] != cycle['cycle_id'] or
            value['attempt_id'] != cycle['attempt_id'] or value['plan_sha256'] != cycle['plan_sha256']):
        raise ValueError('Original patch transaction belongs to another correction')
    previous = (work / value['previous_snapshot']).resolve()
    if not previous.is_relative_to(work / 'iterations') or source_hash(previous / 'snapshot.json') != value['snapshot_sha256']:
        raise ValueError('Original patch ancestor changed')
    from ocr_correction_resume import verify_archive
    verify_archive(work, previous, record)
    check_bindings(value['inputs'])
    publication_path = Path(value['inputs']['publication']['path']).resolve()
    directory = work / 'application/correction-attempts' / cycle['attempt_id']
    if publication_path.parent != directory or Path(value['inputs']['patch']['path']) != path.with_name('native-patch.json'):
        raise ValueError('Original patch publication escaped its reserved attempt/cycle')
    child_path = directory / 'attempt.json'
    child = load(child_path)
    if (cycle['attempt'] != str(child_path.relative_to(work)) or child['attempt_id'] != cycle['attempt_id'] or
            child['run_id'] != record['project']['run_id'] or child['root'] != str(registry.root) or
            child['profile_sha256'] != packet['inputs']['profile']['sha256'] or
            packet['cycle_id'] != cycle['cycle_id'] or packet['index'] != cycle['index'] or
            load(previous / 'output-manifest.json')['iteration_id'] != cycle['source_iteration_id']):
        raise ValueError('Original patch parent/child/cycle/source binding changed')
    parent_binding = child.get('parent_binding')
    if parent_binding:
        parent_id = parent_binding['parent_attempt_id']
        if len(parent_id) != 32 or any(c not in '0123456789abcdef' for c in parent_id):
            raise ValueError('Original patch parent identity changed')
        parent = load(work / 'application/autonomous-attempts' / parent_id / 'attempt.json')
        rows = [row for row in parent['stages'] if row['stage'] == 'corrections' and
            row.get('intent_id') == parent_binding['intent_id']]
        if (parent['run_id'] != child['run_id'] or parent['root'] != child['root'] or len(rows) != 1 or
                rows[0].get('attempt_id') != child['attempt_id'] or parent_binding['stage'] != 'corrections'):
            raise ValueError('Original patch parent stage/intent changed')
    publication = load(publication_path)
    if any(not Path(pointer['path']).resolve().is_relative_to(directory) for pointer in
            (publication['evidence']['proposal'], publication['visual_turn']['protocol'])):
        raise ValueError('Original patch evidence escaped its reserved attempt')
    from ocr_project_corrections import validate_patch
    answer, changed = validate_patch(work, packet, publication, archive=previous)
    if not changed or answer['patch'] != load(value['inputs']['patch']['path']):
        raise ValueError('Original native patch differs from its completed assistant JSON')
    original = load(previous / 'review.json')
    corrected = patched_review(original, answer['patch'])
    encode = lambda item, indent=None: json.dumps(item, ensure_ascii=False, indent=indent) + '\n'
    review_text = encode(corrected, 2)
    digest = hashlib.sha256(review_text.encode()).hexdigest()
    old_digest = source_hash(previous / 'review.json')
    patch_name = 'review-history/' + digest + '-patch.json'
    patch_text = encode(answer['patch'])
    chain = load(previous / 'review-patch-chain.json') if (previous / 'review-patch-chain.json').exists() else []
    chain.append({'previous': old_digest, 'current': digest, 'patch': patch_name,
        'patch_sha256': hashlib.sha256(patch_text.encode()).hexdigest(), 'line_id': None})
    expected = {'review-history/' + old_digest + '.json': (previous / 'review.json').read_text(),
        'review.json': review_text, patch_name: patch_text, 'review-patch-chain.json': encode(chain)}
    if set(value['writes']) != {*expected, 'review-invalidation.json'}:
        raise ValueError('Original patch transaction contains unexpected writes')
    if any(value['writes'][name]['content'] != content for name, content in expected.items()):
        raise ValueError('Original patch transaction differs from its exact native review/history')
    invalidation = json.loads(value['writes']['review-invalidation.json']['content'])
    from ocr_project_review import DERIVED_ARTIFACTS
    inventory = load(previous / 'snapshot.json')['artifacts']
    artifacts = [{'path': name, 'sha256': inventory[name]['sha256']} for name in DERIVED_ARTIFACTS if name in inventory]
    if (invalidation['previous_review_sha256'] != old_digest or invalidation['review_sha256'] != digest or
            invalidation['status'] != 'stale_for_current_review' or invalidation['artifacts'] != artifacts):
        raise ValueError('Original patch invalidation differs from its frozen ancestor')
    desired = value['record']
    prior_record = load(previous / 'project.json')
    if value['project_before_sha256'] != source_hash(previous / 'project.json'):
        raise ValueError('Original patch project precondition differs from its frozen ancestor')
    immutable_project = {key: item for key, item in prior_record['project'].items()
        if key not in ('phase', 'operation_state', 'validation', 'review_sha256')}
    if ({key: desired['project'].get(key) for key in immutable_project} != immutable_project or
            desired['project']['review_sha256'] != digest or desired['project']['phase'] != 'review_updated' or
            desired['project']['operation_state'] != 'completed' or desired['project']['validation'] != 'not_run'):
        raise ValueError('Original patch project identity changed')
    expected_artifacts = {**prior_record['artifacts'], 'review': str((work / 'review.json').relative_to(registry.root)),
        'previous_review': str((work / 'review-history' / (old_digest + '.json')).relative_to(registry.root)),
        'review_invalidation': str((work / 'review-invalidation.json').relative_to(registry.root))}
    if desired['artifacts'] != expected_artifacts:
        raise ValueError('Original patch project artifact paths changed')
    summary = validate_review(work, corrected)
    if any(desired['counts'].get(key) != item for key, item in summary.items()):
        raise ValueError('Original patch validation counts changed')
    # An unbound file has no independent ledger digest yet. Its proposed record
    # and invalidation must be derived completely from the pinned original
    # assistant answer and ancestor, not trusted as self-declared fields.
    old_lines = {line['id']: line for line in original['lines']}
    new_lines = {line['id']: line for line in corrected['lines']}
    changed_lines = {key for key in old_lines.keys() | new_lines.keys() if old_lines.get(key) != new_lines.get(key)}
    affected = set(changed_lines)
    for register in ('unresolved', 'publisher_errors', 'risk_register'):
        if original.get(register, []) != corrected.get(register, []):
            affected.update(row['line'] for row in original.get(register, []) + corrected.get(register, []))
    reordered = original['units'] != corrected['units']
    if reordered:
        old_units = {unit['id']: (index, unit) for index, unit in enumerate(original['units'])}
        new_units = {unit['id']: (index, unit) for index, unit in enumerate(corrected['units'])}
        for key in old_units.keys() | new_units.keys():
            if old_units.get(key) != new_units.get(key):
                for units in (old_units, new_units):
                    if key in units:
                        affected.update(units[key][1]['line_ids'])
    pages = sorted({line['page'] for key in affected for line in (old_lines.get(key), new_lines.get(key)) if line})
    expected_invalidation = {'schema_version': 1, 'status': 'stale_for_current_review',
        'previous_review_sha256': old_digest, 'review_sha256': digest,
        'affected_lines': sorted(affected), 'affected_pages': pages, 'unit_order_changed': reordered, 'artifacts': artifacts}
    if value['writes']['review-invalidation.json']['content'] != encode(expected_invalidation):
        raise ValueError('Original patch invalidation scope changed')
    expected_record = copy.deepcopy(prior_record)
    expected_record['project'].update(phase='review_updated', operation_state='completed', validation='not_run', review_sha256=digest)
    expected_record['counts'].update(summary, changed_lines=len(changed_lines), affected_lines=len(affected),
        affected_pages=len(pages), invalidated_artifacts=len(artifacts))
    expected_record['artifacts'] = expected_artifacts
    if desired != expected_record:
        raise ValueError('Original patch project transaction differs from its exact native result')
    before = source_hash(registry.root / record['artifacts']['project'])
    after = hashlib.sha256(encode(desired).encode()).hexdigest()
    if before not in (value['project_before_sha256'], after):
        raise ValueError('Project changed outside its original patch transaction')
    for name, write in value['writes'].items():
        target = work / name
        if target.is_symlink() or not target.resolve().is_relative_to(work):
            raise ValueError('Original patch write escaped its run')
        if hashlib.sha256(write['content'].encode()).hexdigest() != write['sha256']:
            raise ValueError('Original patch transaction content changed')
        old = write['previous_sha256']
        if name in ('review.json', 'review-patch-chain.json', 'review-invalidation.json'):
            expected_old = inventory.get(name, {}).get('sha256')
            if old != expected_old:
                raise ValueError('Original patch precondition differs from its snapshot')
        elif old is not None and old != write['sha256']:
            raise ValueError('Original review history would be overwritten')
        actual = source_hash(target) if target.is_file() else None
        if orphan and actual != old:
            raise ValueError('Unbound original patch has unexpected physical writes: ' + name)
        if actual not in (old, write['sha256']):
            raise ValueError('Original patch artifact drifted: ' + name)
    return value, previous


@checked
def adopt(registry, run_id, cycle_id):
    with registry.project_lock(run_id) as record:
        work = (registry.root / record['artifacts']['workspace']).resolve()
        ledger, cycle, packet = cycle_record(work, cycle_id)
        if cycle['state'] != 'reserved':
            raise ValueError('Only an original pending patch transaction may be adopted')
        value, previous = verify_intent(registry, record, work, cycle, packet)
        # The immutable intent is durable before its ledger pointer. Validate
        # its entire original transaction before repairing that missing link.
        if 'patch_intent' not in cycle:
            path = intent_path(work, cycle)
            cycle.update(patch_intent=str(path.relative_to(work)), patch_intent_sha256=source_hash(path), phase='patch_reserved')
            atomic_json(ledger_path(work), ledger)
        for name, write in value['writes'].items():
            target = work / name
            if target.is_file() and source_hash(target) == write['sha256']:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(write['content']); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, target)
        record.clear(); record.update(copy.deepcopy(value['record']))
        publication = load(value['inputs']['publication']['path'])
        cycle.update(state='published', phase='patch_published', previous_snapshot=str(previous.relative_to(work)),
            proposal=str(Path(publication['evidence']['proposal']['path']).relative_to(work)),
            publication=str(Path(value['inputs']['publication']['path']).relative_to(work)),
            review_sha256=record['project']['review_sha256'], patch=str(Path(value['inputs']['patch']['path']).relative_to(work)),
            patch_sha256=value['inputs']['patch']['sha256'], validator=value['inputs']['validator'])
        atomic_json(ledger_path(work), ledger)
    return registry.get(run_id)
