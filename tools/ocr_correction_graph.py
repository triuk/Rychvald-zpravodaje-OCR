"""Exact durable output-child identities shared by native and application readers."""
import json
import hashlib
from pathlib import Path


def continuation_edges(work, correction):
    """Return only immutable, exact stopped-original → submitted-successor edges.

    This authorizes failure classifiers to follow an explicit continuation. It
    does not classify delivery, authorize another request, or weaken active CAS.
    A reserved continuation without an outgoing request is not a resolved edge.
    """
    work = Path(work).resolve()
    root = Path(correction['root']).resolve()
    binding = correction.get('parent_binding') or {}
    ancestor_id = binding.get('correction_attempt_id', correction['attempt_id'])
    namespace = 'output-review-attempts' if binding.get('correction_attempt_id') else 'correction-attempts'
    directory = work / 'application' / namespace / correction['attempt_id']

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def bound(pointer):
        path = Path(pointer['path']).resolve()
        if not path.is_relative_to(work) or digest(path) != pointer['sha256']:
            raise ValueError('Continuation evidence changed or escaped the original run')
        return path

    def frames(path):
        lines = path.read_text().splitlines(keepends=True)
        if any(not line.endswith('\n') for line in lines):
            raise ValueError('Continuation native protocol is incomplete')
        return [json.loads(line) for line in lines]

    def content(params):
        selected = {key: params[key] for key in ('model', 'effort', 'input', 'outputSchema')}
        return hashlib.sha256(json.dumps(selected, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    edges, originals, successors = [], set(), set()
    try:
        ledger = None
        for record in correction.get('continuations', []):
            intent_path = bound(record['intent'])
            if not intent_path.is_relative_to(directory / 'recovery-sessions'):
                raise ValueError('Continuation intent belongs to another correction')
            intent = json.loads(intent_path.read_text())
            if intent != {k: v for k, v in record.items() if k not in ('intent', 'successor')}:
                raise ValueError('Continuation manifest differs from its immutable intent')
            if ledger is None:
                ledger = json.loads((work / 'application/corrections/ledger.json').read_text())
            cycles = [c for c in ledger['cycles'] if c['cycle_id'] == intent['cycle_id']]
            if (len(cycles) != 1 or cycles[0]['attempt_id'] != ancestor_id or
                    cycles[0]['index'] != intent['cycle_index'] or cycles[0]['plan_sha256'] != intent['plan_sha256'] or
                    intent['attempt_id'] != correction['attempt_id'] or
                    intent['parent_binding'] != correction['parent_binding'] or
                    intent['profile_sha256'] != correction['profile_sha256']):
                raise ValueError('Continuation belongs to another parent/cycle/profile/plan')
            if binding.get('correction_attempt_id'):
                ancestor = json.loads((work / 'application/correction-attempts' / ancestor_id / 'attempt.json').read_text())
                output_intent, child = output_child(work, ancestor, intent['cycle_id'])
                if child is None or child['attempt_id'] != correction['attempt_id'] or output_intent['binding'] != binding:
                    raise ValueError('Continuation belongs to another correction output intent')
            proof_path = bound(intent['reconciliation'])
            proof = json.loads(proof_path.read_text())
            parent = correction['parent_binding']['parent_attempt_id']
            expected = work / 'application/autonomous-attempts' / parent / ('reconciliation-' + proof['reconciliation_id'] + '.json')
            integrity = proof_path.with_name(proof_path.stem + '-integrity.json')
            if (proof_path != expected or proof['attempt_id'] != parent or proof['run_id'] != correction['run_id'] or
                    intent['reconciliation']['reconciliation_id'] != proof['reconciliation_id'] or
                    json.loads(integrity.read_text())['sha256'] != intent['reconciliation']['sha256'] or
                    not proof['checkpoint']['valid'] or not proof['provider']['safe_to_continue']):
                raise ValueError('Continuation has no exact explicit original reconciliation')
            original = intent['original']
            observations = [o for o in proof['provider']['turns'] if o['attempt_id'] == correction['attempt_id'] and
                o.get('visual_stage') == intent['stage'] and str(o['connection_id']) == str(original['connection_id']) and
                o['thread_id'] == original['thread_id'] and o['turn_id'] == original['turn_id']]
            if (len(observations) != 1 or observations[0]['state'] != original['state'] or
                    original['state'] not in ('rejected', 'failed', 'interrupted')):
                raise ValueError('Unknown or completed original cannot be superseded')
            original_protocol = bound(original['protocol'])
            original_frames = frames(original_protocol)
            aggregate = intent_path.parent / 'original-protocol.jsonl'
            aggregate_name = str((root / correction['artifacts']['protocol']).relative_to(root))
            if digest(aggregate) != proof['provider']['originals'].get(aggregate_name):
                raise ValueError('Inspected original protocol snapshot changed')
            scopes = {(r.get('stage'), str(r.get('connection_id'))) for r in original_frames}
            if original_frames != [r for r in frames(aggregate) if (r.get('stage'), str(r.get('connection_id'))) in scopes]:
                raise ValueError('Stopped original phase differs from the inspected snapshot')
            requests = [r for r in original_frames if r['direction'] == 'client' and r['message'].get('method') == 'turn/start']
            if len(requests) != 1:
                raise ValueError('Stopped original must identify exactly one request')
            request = requests[0]
            if (str(request['connection_id']) != str(original['connection_id']) or request.get('stage') != intent['stage'] or
                    request['message']['id'] != original['request_id'] or
                    request['message']['params']['threadId'] != original['thread_id'] or
                    content(request['message']['params']) != intent['request_content_sha256']):
                raise ValueError('Stopped original request identity changed')
            successor = record.get('successor')
            if successor is None:
                continue  # Durable reservation alone never supersedes a rejection.
            submission_path = bound(successor['submission_intent'])
            submission = json.loads(submission_path.read_text())
            physical = (root / intent['directory']).resolve()
            if (not physical.is_relative_to(directory / 'recovery-sessions') or
                    submission_path != physical / 'submission-intent.json' or
                    submission['continuation_id'] != intent['continuation_id'] or
                    submission['continuation_intent'] != record['intent'] or
                    submission['attempt_id'] != correction['attempt_id'] or submission['stage'] != intent['stage'] or
                    submission['cycle_id'] != intent['cycle_id'] or
                    any(submission[k] != successor[k] for k in ('connection_id', 'thread_id', 'request'))):
                raise ValueError('Successor submission differs from its durable original intent')
            successor_request = json.loads(bound(successor['request']).read_text())
            if (Path(successor['request']['path']).resolve() != physical / 'request.json' or
                    content(successor_request) != intent['request_content_sha256'] or
                    successor_request['threadId'] != successor['thread_id']):
                raise ValueError('Successor request differs from the exact stopped phase')
            protocol = Path(successor['protocol']['path']).resolve()
            if protocol != physical / 'protocol.jsonl' or submission['protocol']['path'] != str(protocol):
                raise ValueError('Successor native protocol belongs to another phase')
            if successor['protocol'].get('sha256'):
                bound(successor['protocol'])
            native = frames(protocol)
            starts = [r for r in native if r['direction'] == 'client' and r['message'].get('method') == 'turn/start']
            if not starts:
                continue  # No trace-before-send means no successor submission.
            if (len(starts) != 1 or starts[0]['message']['params'] != successor_request or
                    starts[0].get('stage') != intent['stage'] or
                    str(starts[0]['connection_id']) != str(successor['connection_id'])):
                raise ValueError('Successor native submission changed')
            request_id = starts[0]['message']['id']
            acks = [r['message']['result']['turn']['id'] for r in native if r['direction'] == 'server' and
                str(r['connection_id']) == str(successor['connection_id']) and r['message'].get('id') == request_id and
                r['message'].get('result', {}).get('turn', {}).get('id')]
            if len(set(acks)) > 1 or (successor.get('turn_id') and acks != [successor['turn_id']]):
                raise ValueError('Successor acknowledgement identity changed')
            old_key = (intent['stage'], str(original['connection_id']), original['thread_id'], original['turn_id'], original['request_id'])
            new_key = (intent['stage'], str(successor['connection_id']), successor['thread_id'], acks[0] if acks else None, request_id)
            if old_key in originals or new_key in successors or str(original['connection_id']) == str(successor['connection_id']):
                raise ValueError('Multiple or cyclic continuation claims')
            originals.add(old_key); successors.add(new_key)
            edges.append({'continuation_id': intent['continuation_id'], 'stage': intent['stage'], 'cycle_id': intent['cycle_id'],
                'original': {k: original[k] for k in ('connection_id', 'thread_id', 'turn_id', 'request_id', 'state')},
                'successor': {'connection_id': successor['connection_id'], 'thread_id': successor['thread_id'],
                    'turn_id': acks[0] if acks else None, 'request_id': request_id},
                'evidence': {'intent': record['intent'], 'submission_intent': successor['submission_intent'],
                    'original_protocol': original['protocol']}})
        return edges
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ValueError('Invalid original correction continuation: ' + str(error)) from error


def output_binding(correction, intent):
    parent = correction.get('parent_binding') or {}
    manual = correction.get('manual_binding') or {}
    return {'parent_attempt_id': parent.get('parent_attempt_id', correction['attempt_id']),
        'intent_id': parent.get('intent_id', manual.get('manual_id', correction['attempt_id'])),
        'stage': 'correction_output_review', 'correction_attempt_id': correction['attempt_id'],
        'cycle_id': intent['cycle_id'], 'cycle_index': intent['cycle_index'],
        'stage_intent_id': intent['stage_intent_id'], 'preparation_sha256': intent['preparation_sha256']}


def output_child(work, correction, cycle_id):
    """Discover exactly one child, including a crash before its parent's link."""
    work = Path(work).resolve()
    intents = [i for i in correction.get('output_intents', []) if i['cycle_id'] == cycle_id]
    links = [i for i in correction.get('children', []) if i['cycle_id'] == cycle_id and i['stage'] == 'output_review']
    if len(intents) > 1 or len(links) > 1:
        raise ValueError('Multiple output intents/children claim the same correction cycle')
    if not intents:
        if links:
            raise ValueError('Correction output child has no durable phase intent')
        return None, None
    intent = intents[0]
    identifier = intent['stage_intent_id']
    if len(identifier) != 32 or any(c not in '0123456789abcdef' for c in identifier):
        raise ValueError('Invalid correction output stage intent')
    binding = output_binding(correction, intent)
    if intent['binding'] != binding:
        raise ValueError('Original correction output binding changed')
    matches = []
    for path in (work / 'application/output-review-attempts').glob('*/attempt.json'):
        child = json.loads(path.read_text())
        if child.get('parent_binding') == binding:
            if (path.is_symlink() or not path.resolve().is_relative_to(work) or
                    path.parent.name != child['attempt_id'] or child['run_id'] != correction['run_id'] or
                    child['root'] != correction['root']):
                raise ValueError('Correction output child belongs to another run/registry')
            matches.append(child)
    if len(matches) > 1:
        raise ValueError('Multiple output children claim the same durable correction intent')
    claims = {i['attempt_id'] for i in links}
    if intent.get('attempt_id'):
        claims.add(intent['attempt_id'])
    if len(claims) > 1 or (claims and (not matches or matches[0]['attempt_id'] not in claims)):
        raise ValueError('Original correction output child cannot be replaced')
    return intent, matches[0] if matches else None
