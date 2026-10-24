"""Reuse a completed original visual trace, without submitting another turn."""
import json
from pathlib import Path

from .jobs import JobError, sha
from tools.ocr_visual_evidence import verify_visual_turn
from tools.ocr_quality import check_bindings


def original_directory(work, attempt, observation, namespace):
    directory = work / 'application' / namespace / attempt['attempt_id']
    candidates = {directory / observation['visual_stage']}
    root = Path(attempt['root'])
    for turn in attempt.get('turns', []):
        if (turn.get('stage') == observation['visual_stage'] and
                str(turn.get('connection_id')) == str(observation['connection_id'])):
            candidates.add((root / turn['protocol']).parent)
    candidates.update(root / row['directory'] for row in attempt.get('continuations', [])
        if row['stage'] == observation['visual_stage'])
    matches = []
    for path in candidates:
        path = path.resolve()
        if not path.is_relative_to(directory):
            raise ValueError('Original physical visual phase escaped its attempt')
        protocol = path / 'protocol.jsonl'
        if protocol.exists():
            frames = [json.loads(line) for line in protocol.read_text().splitlines()]
            submissions = [r for r in frames if r['direction'] == 'client' and r['message'].get('method') == 'turn/start']
            if len(submissions) == 1 and {(r.get('stage'), str(r.get('connection_id'))) for r in submissions} == {
                    (observation['visual_stage'], str(observation['connection_id']))}:
                matches.append(path)
    if len(matches) != 1:
        raise ValueError('Exactly one original physical visual phase must match the inspected connection')
    return matches[0]


def original_output_phase(work, attempt, observation):
    """Verify a completed correction output phase before its local publication."""
    try:
        from tools.ocr_correction_graph import output_child
        binding = attempt['parent_binding']
        ancestor = json.loads((work / 'application/correction-attempts' /
            binding['correction_attempt_id'] / 'attempt.json').read_text())
        intent, child = output_child(work, ancestor, binding['cycle_id'])
        if child is None or child['attempt_id'] != attempt['attempt_id'] or intent['binding'] != binding:
            raise ValueError('Completed output belongs to another correction intent')
        path = work / 'output-review-preparation.json'
        if sha(path) != binding['preparation_sha256'] or observation['visual_stage'] != 'output_examination':
            raise ValueError('Completed output belongs to another preparation/phase')
        packet = json.loads(path.read_text())
        check_bindings(packet['inputs'])
        check_bindings(packet['compare_and_swap'])
        packet['preparation_sha256'] = sha(path)
        from .output_review import OUTPUT_PROMPT, OUTPUT_SCHEMA
        directory = original_directory(work, attempt, observation, 'output-review-attempts')
        answer, proof = original_visual(directory, work, packet['images'],
            OUTPUT_PROMPT + json.dumps(packet, ensure_ascii=False), OUTPUT_SCHEMA,
            work / 'application/output-review-attempts' / attempt['attempt_id'] / 'protocol.jsonl')
        if proof['thread_id'] != observation['thread_id'] or proof['turn_id'] != observation['turn_id']:
            raise ValueError('Completed output identity differs from original reconciliation')
        return answer, proof
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise JobError('original_result_unavailable', str(error)) from error


def original_visual(directory, work, images, prompt, schema, aggregate):
    protocol = directory / 'protocol.jsonl'
    raw = protocol.read_text().splitlines(keepends=True)
    if not raw or any(not line.endswith('\n') for line in raw):
        raise ValueError('Original visual protocol is incomplete')
    rows = [json.loads(line) for line in raw]
    scopes = {(row['stage'], str(row['connection_id'])) for row in rows}
    bound = [json.loads(line) for line in aggregate.read_text().splitlines()]
    if rows != [row for row in bound if (row.get('stage'), str(row.get('connection_id'))) in scopes]:
        raise ValueError('Original phase trace differs from its saved attempt protocol')
    starts = [row['message'] for row in rows if row['direction'] == 'client' and row['message'].get('method') == 'turn/start']
    if len(starts) != 1:
        raise ValueError('Exactly one original visual submission is required')
    request = starts[0]
    params = request['params']
    if (params != json.loads((directory / 'request.json').read_text()) or
            params['input'][0] != {'type': 'text', 'text': prompt} or params['outputSchema'] != schema):
        raise ValueError('Original visual request differs from the current bound phase')
    replies = [row['message'] for row in rows if row['direction'] == 'server' and
        row['message'].get('id') == request['id'] and 'method' not in row['message']]
    if len(replies) != 1 or not replies[0].get('result', {}).get('turn', {}).get('id'):
        raise ValueError('Original visual acknowledgement is unavailable')
    proof = {'protocol': {'path': str(protocol), 'sha256': sha(protocol)},
        'thread_id': params['threadId'], 'turn_id': replies[0]['result']['turn']['id']}
    answer = verify_visual_turn(proof, work, images)
    proposal = directory / 'proposal.json'
    if proposal.exists() and json.loads(proposal.read_text()) != answer:
        raise ValueError('Original proposal differs from its completed native trace')
    return answer, proof


def original_correction_phase(work, attempt, observation):
    """Read-only proof for an original repair or geometry publication."""
    try:
        stage = observation['visual_stage']
        ledger = json.loads((work / 'application/corrections/ledger.json').read_text())
        cycle = ledger['cycles'][-1]
        if cycle['attempt_id'] != attempt['attempt_id']:
            raise ValueError('Completed original turn belongs to another correction attempt')
        packet_path = work / cycle['plan']
        if sha(packet_path) != cycle['plan_sha256']:
            raise ValueError('Original correction plan changed')
        if stage == 'repair_' + str(cycle['index']) and cycle['state'] == 'reserved':
            packet = json.loads(packet_path.read_text())
            from .corrections import REPAIR_PROMPT, REPAIR_SCHEMA
            prompt, schema = REPAIR_PROMPT, REPAIR_SCHEMA
        elif stage == 'geometry_' + str(cycle['index']) and cycle['state'] == 'published':
            packet_path = work / 'geometry-preparation.json'
            packet = json.loads(packet_path.read_text())
            scope = packet.get('correction_scope', {})
            if scope.get('cycle_id') != cycle['cycle_id'] or scope.get('previous_snapshot') != cycle['previous_snapshot']:
                raise ValueError('Original geometry belongs to another correction preparation')
            packet['preparation_sha256'] = sha(packet_path)
            from .geometry_contract import GEOMETRY_PROMPT, GEOMETRY_SCHEMA
            prompt, schema = GEOMETRY_PROMPT, GEOMETRY_SCHEMA
        else:
            raise ValueError('Completed original turn is not the current correction phase')
        # Pending native patch CAS is independently verified through its exact
        # ledger-bound transaction and ancestor before a worker can resume.
        if not (cycle['state'] == 'reserved' and cycle.get('patch_intent')):
            check_bindings(packet['inputs'])
        directory = original_directory(work, attempt, observation, 'correction-attempts')
        answer, proof = original_visual(directory, work, packet['images'],
            prompt + json.dumps(packet, ensure_ascii=False), schema,
            work / 'application/correction-attempts' / attempt['attempt_id'] / 'protocol.jsonl')
        if proof['thread_id'] != observation['thread_id'] or proof['turn_id'] != observation['turn_id']:
            raise ValueError('Original repair identity differs from reconciliation')
        return answer, proof
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise JobError('original_result_unavailable', str(error)) from error
