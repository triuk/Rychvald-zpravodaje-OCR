"""Verify an exact reserved visual phase before reusing its unsubmitted preparation."""
import copy
import json

from .jobs import JobError, sha
from .visual_continuation import content_hash


def restore_preparation(job, stage, prompt, schema, work, images, directory):
    continuation = job['current_continuation']
    try:
        from tools.ocr_correction_graph import continuation_edges
        continuation_edges(work, job['manifest'])
        expected = {'model': 'gpt-6.1-sol', 'effort': 'high', 'outputSchema': schema,
            'input': [{'type': 'text', 'text': prompt}] + [
                {'type': 'localImage', 'path': str((work / image['path']).resolve())} for image in images]}
        if (continuation['stage'] != stage or continuation['directory'] != str(directory.relative_to(job['root'])) or
                continuation['images'] != images or continuation['request_content_sha256'] != content_hash(expected) or
                any(sha(work / image['path']) != image['sha256'] for image in images)):
            raise ValueError('Reserved continuation differs from the exact current phase or pixels.')
        protocol = directory / 'protocol.jsonl'
        raw = protocol.read_text() if protocol.exists() else ''
        if raw and not raw.endswith('\n'):
            raise ValueError('Unsubmitted preparation protocol is incomplete.')
        frames = [json.loads(line) for line in raw.splitlines()]
        if any(row['direction'] == 'client' and row['message'].get('method') == 'turn/start' for row in frames):
            raise ValueError('A submitted visual phase cannot reuse unsubmitted preparation.')
        submission_path = directory / 'submission-intent.json'
        successor = None
        if submission_path.exists():
            saved = json.loads(submission_path.read_text())
            successor = {key: saved[key] for key in ('connection_id', 'thread_id', 'turn_id', 'request', 'protocol', 'state')}
            successor['submission_intent'] = {'path': str(submission_path), 'sha256': sha(submission_path)}
            if successor['state'] != 'not_submitted' or successor['turn_id'] is not None:
                raise ValueError('Only provably unsubmitted successor preparation can be resumed.')
            current = continuation.get('successor')
            if current is not None and current != successor:
                raise ValueError('Saved successor differs from its immutable submission preparation.')
            candidate = copy.deepcopy(job['manifest'])
            rows = [row for row in candidate['continuations'] if row['continuation_id'] == continuation['continuation_id']]
            if len(rows) != 1:
                raise ValueError('Continuation preparation has no unique original reservation.')
            rows[0]['successor'] = successor
            continuation_edges(work, candidate)
        elif continuation.get('successor'):
            raise ValueError('Original successor submission preparation is missing.')
        request = directory / 'request.json'
        if not request.exists():
            if successor is not None:
                raise ValueError('Original prepared successor request is missing.')
            return {}
        params = json.loads(request.read_text())
        if content_hash(params) != content_hash(expected):
            raise ValueError('Prepared successor request differs from the exact current phase.')
        confirmations = [row for row in frames if row['direction'] == 'server' and
            row['message'].get('result', {}).get('thread', {}).get('id') == params['threadId'] and
            row['message']['result'].get('model') == expected['model'] and
            row['message']['result'].get('reasoningEffort') == expected['effort']]
        if not confirmations:
            raise ValueError('Prepared successor has no original native thread confirmation.')
        connection = str(confirmations[-1]['connection_id'])
        if successor is not None and (successor['thread_id'] != params['threadId'] or
                str(successor['connection_id']) != connection):
            raise ValueError('Prepared successor belongs to another native connection or thread.')
        return {'params': params, 'connection_id': connection, 'successor': successor}
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise JobError('checkpoint_invalid', str(error)) from error
