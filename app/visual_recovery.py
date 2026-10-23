"""Reuse a completed original visual trace, without submitting another turn."""
import json

from .jobs import JobError, sha
from tools.ocr_visual_evidence import verify_visual_turn
from tools.ocr_quality import check_bindings


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
    """Read-only proof for a repair whose publication was interrupted."""
    try:
        stage = observation['visual_stage']
        ledger = json.loads((work / 'application/corrections/ledger.json').read_text())
        cycle = ledger['cycles'][-1]
        if stage != 'repair_' + str(cycle['index']) or cycle['attempt_id'] != attempt['attempt_id'] or cycle['state'] != 'reserved':
            raise ValueError('Completed original turn is not the reserved repair phase')
        packet_path = work / cycle['plan']
        if sha(packet_path) != cycle['plan_sha256']:
            raise ValueError('Original correction plan changed')
        packet = json.loads(packet_path.read_text())
        check_bindings(packet['inputs'])
        from .corrections import REPAIR_PROMPT, REPAIR_SCHEMA
        directory = work / 'application/correction-attempts' / attempt['attempt_id']
        answer, proof = original_visual(directory / stage, work, packet['images'],
            REPAIR_PROMPT + json.dumps(packet, ensure_ascii=False), REPAIR_SCHEMA, directory / 'protocol.jsonl')
        if proof['thread_id'] != observation['thread_id'] or proof['turn_id'] != observation['turn_id']:
            raise ValueError('Original repair identity differs from reconciliation')
        return answer, proof
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise JobError('original_result_unavailable', str(error)) from error
