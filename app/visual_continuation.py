"""Explicit continuation of a definitively stopped original correction turn."""
import hashlib
import json
from pathlib import Path
import uuid

from .jobs import JobError, atomic_json, sha


def content_hash(params):
    selected = {key: params[key] for key in ('model', 'effort', 'input', 'outputSchema')}
    return hashlib.sha256(json.dumps(selected, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def original_reconciliation(root, work, attempt, reference, *, verify_originals=True):
    try:
        parent = attempt['parent_binding']['parent_attempt_id']
        identifier = reference['reconciliation_id']
        path = Path(reference['path']).resolve()
        expected = work / 'application/autonomous-attempts' / parent / ('reconciliation-' + identifier + '.json')
        if path != expected or sha(path) != reference['sha256']:
            raise ValueError('Original correction reconciliation changed')
        integrity = path.with_name('reconciliation-' + identifier + '-integrity.json')
        if json.loads(integrity.read_text())['sha256'] != reference['sha256']:
            raise ValueError('Original reconciliation integrity changed')
        proof = json.loads(path.read_text())
        if (proof['reconciliation_id'] != identifier or proof['attempt_id'] != parent or
                proof['run_id'] != attempt['run_id'] or not proof['checkpoint']['valid'] or
                not proof['provider']['safe_to_continue']):
            raise ValueError('Original correction has no valid explicit reconciliation')
        if verify_originals:
            for relative, digest in proof['provider']['originals'].items():
                source = (root / relative).resolve()
                if not source.is_relative_to(work) or sha(source) != digest:
                    raise ValueError('Inspected original correction evidence changed')
        return proof
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise JobError('reconciliation_required', str(error)) from error


def reserve_continuation(manager, job, stage, directory, frames, prompt, schema, images):
    """Bind one new physical turn only after explicit stopped-turn inspection."""
    value, root = job['manifest'], job['root']
    work = job['directory'].parents[2]
    proof = original_reconciliation(root, work, value, job['reconciliation'], verify_originals=False)
    starts = [row for row in frames if row['direction'] == 'client' and row['message'].get('method') == 'turn/start']
    if len(starts) != 1:
        raise JobError('original_result_unavailable', 'An original physical phase must have exactly one submitted request.')
    start = starts[0]
    connection = str(start['connection_id'])
    params = start['message']['params']
    observed = [row for row in proof['provider']['turns'] if row['attempt_id'] == value['attempt_id'] and
        row.get('visual_stage') == stage and row['connection_id'] == connection and row['thread_id'] == params['threadId']]
    if len(observed) != 1 or observed[0]['state'] not in ('rejected', 'failed', 'interrupted'):
        return None  # Completed originals may only be reused; unknown originals never continue.
    original = observed[0]
    saved = job['reconciliation_protocol']
    aggregate_name = str((root / value['artifacts']['protocol']).relative_to(root))
    if sha(saved) != proof['provider']['originals'].get(aggregate_name):
        raise JobError('reconciliation_required', 'Original inspected protocol snapshot changed.')
    scopes = {(row['stage'], str(row['connection_id'])) for row in frames}
    archived = [json.loads(line) for line in saved.read_text().splitlines()]
    if frames != [row for row in archived if (row.get('stage'), str(row.get('connection_id'))) in scopes]:
        raise JobError('reconciliation_required', 'Original physical phase differs from inspected protocol.')
    if params != json.loads((directory / 'request.json').read_text()):
        raise JobError('reconciliation_required', 'Original physical request changed.')
    expected = {'model': 'gpt-6.1-sol', 'effort': 'high', 'outputSchema': schema,
        'input': [{'type': 'text', 'text': prompt}] + [
            {'type': 'localImage', 'path': str((work / image['path']).resolve())} for image in images]}
    if content_hash(params) != content_hash(expected):
        raise JobError('checkpoint_invalid', 'Original stopped request differs from the exact current phase.')
    if original['state'] == 'rejected' and not any(row['direction'] == 'server' and
            str(row['connection_id']) == connection and row['message'].get('id') == start['message']['id'] and
            row['message'].get('error') for row in frames):
        raise JobError('reconciliation_required', 'Original rejection is not present in its native protocol.')
    ledger = json.loads((work / 'application/corrections/ledger.json').read_text())
    cycle = ledger['cycles'][-1]
    if cycle['attempt_id'] != value['attempt_id'] or cycle['cycle_id'] != job['cycle_id']:
        raise JobError('attempt_conflict', 'Stopped original turn belongs to another reserved correction.')
    identifier = uuid.uuid4().hex
    physical = job['recovery_directory'] / ('continuation-' + identifier)
    body = {'schema_version': 1, 'continuation_id': identifier, 'stage': stage,
        'cycle_id': cycle['cycle_id'], 'cycle_index': cycle['index'], 'attempt_id': value['attempt_id'],
        'parent_binding': value['parent_binding'], 'profile_sha256': value['profile_sha256'],
        'plan_sha256': cycle['plan_sha256'], 'request_content_sha256': content_hash(expected),
        'images': images, 'directory': str(physical.relative_to(root)),
        'original': {'state': original['state'], 'connection_id': connection, 'thread_id': original['thread_id'],
            'turn_id': original['turn_id'], 'request_id': start['message']['id'],
            'protocol': {'path': str(directory / 'protocol.jsonl'), 'sha256': sha(directory / 'protocol.jsonl')}},
        'reconciliation': job['reconciliation']}
    intent = job['recovery_directory'] / ('continuation-' + identifier + '.json')
    atomic_json(intent, body)
    continuation = {**body, 'intent': {'path': str(intent), 'sha256': sha(intent)}, 'successor': None}
    value.setdefault('continuations', []).append(continuation)
    manager._event(job, 'correction_continuation_reserved', stage=stage, cycle_id=cycle['cycle_id'],
        continuation_id=identifier, original_delivery=original['state'], intent=continuation['intent'])
    return continuation


def bind_submission(manager, job, continuation, params, connection, directory, protocol):
    intent = continuation['intent']
    if sha(Path(intent['path'])) != intent['sha256']:
        raise JobError('checkpoint_invalid', 'Original continuation intent changed before submission.')
    body = json.loads(Path(intent['path']).read_text())
    if (body['request_content_sha256'] != content_hash(params) or
            body['directory'] != str(directory.relative_to(job['root']))):
        raise JobError('checkpoint_invalid', 'Continuation submission differs from its exact reserved phase.')
    successor = {'connection_id': connection, 'thread_id': params['threadId'], 'turn_id': None,
        'request': {'path': str(directory / 'request.json'), 'sha256': sha(directory / 'request.json')},
        'protocol': {'path': str(protocol)}, 'state': 'not_submitted'}
    submission = directory / 'submission-intent.json'
    atomic_json(submission, {'schema_version': 1, 'continuation_id': continuation['continuation_id'],
        'continuation_intent': intent, 'attempt_id': job['manifest']['attempt_id'], 'stage': continuation['stage'],
        'cycle_id': continuation['cycle_id'], **successor})
    successor['submission_intent'] = {'path': str(submission), 'sha256': sha(submission)}
    continuation['successor'] = successor
    manager._event(job, 'correction_continuation_submitting', stage=continuation['stage'],
        cycle_id=continuation['cycle_id'], continuation_id=continuation['continuation_id'], successor=successor)
