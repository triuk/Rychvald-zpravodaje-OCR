"""Controlled process peer for accounting tests; never native AI evidence."""
import json
import sys

scenario = json.loads(open(sys.argv[1], encoding='utf-8').read())


def emit(value):
    print(json.dumps(value), flush=True)


for raw in sys.stdin:
    request = json.loads(raw)
    if 'id' not in request:
        continue
    method, identifier = request['method'], request['id']
    if method == 'initialize':
        result = {'userAgent': 'metrics-controlled-process'}
    elif method == 'account/read':
        result = {'account': {'type': 'chatgpt'}, 'requiresOpenaiAuth': True}
    elif method == 'model/list':
        result = {'data': [{'id': 'gpt-6.1-sol', 'model': 'gpt-6.1-sol',
                  'inputModalities': ['text', 'image'],
                  'supportedReasoningEfforts': [{'reasoningEffort': 'high'}]}], 'nextCursor': None}
    elif method == 'thread/start':
        result = {'thread': {'id': 'metrics-thread'}, 'model': 'gpt-6.1-sol', 'reasoningEffort': 'high'}
    elif method == 'turn/start':
        emit({'id': identifier, 'result': {'turn': {'id': 'metrics-turn', 'status': 'inProgress'}}})
        for total in scenario['snapshots']:
            emit({'method': 'thread/tokenUsage/updated', 'params': {'threadId': 'metrics-thread',
                  'turnId': 'metrics-turn', 'tokenUsage': {'total': total, 'last': scenario.get('last', total)}}})
        for event in scenario.get('events', []):
            emit(event)
        emit({'method': 'item/completed', 'params': {'threadId': 'metrics-thread', 'turnId': 'metrics-turn',
              'item': {'type': 'agentMessage', 'id': 'answer', 'text': 'Controlled accounting answer'}}})
        emit({'method': 'turn/completed', 'params': {'threadId': 'metrics-thread',
              'turn': {'id': 'metrics-turn', 'status': scenario.get('state', 'completed'), 'items': []}}})
        continue
    else:
        emit({'id': identifier, 'error': {'code': -32601, 'message': method}})
        continue
    emit({'id': identifier, 'result': result})
