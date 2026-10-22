"""Controlled child-process protocol peer, never native/model evidence."""
import json
import sys
import time
from pathlib import Path

mode = sys.argv[1]
logged_in = mode not in ('login', 'missing_account', 'queue_auth')
state_path = Path(sys.argv[2]) if mode in ('hold', 'lost_ack', 'completed_lost_terminal', 'queue_quota') else None


def emit(value):
    print(json.dumps(value), flush=True)


for raw in sys.stdin:
    request = json.loads(raw)
    method = request.get('method')
    if 'id' not in request:
        continue
    identifier = request['id']
    if method == 'initialize':
        result = {'userAgent': 'controlled-process-fixture'}
    elif method == 'account/read':
        result = {'account': {'type': 'chatgpt', 'email': 'private@example.invalid', 'planType': 'plus'},
                  'requiresOpenaiAuth': True}
        if not logged_in:
            result['account'] = None
    elif method == 'account/login/start':
        assert request['params'] == {'type': 'chatgpt'}
        emit({'id': identifier, 'result': {'type': 'chatgpt', 'loginId': 'fixture-login',
              'authUrl': 'https://auth.openai.com/authorize?state=private-fixture-state'}})
        time.sleep(.15)
        logged_in = True
        emit({'method': 'account/login/completed', 'params': {'loginId': 'fixture-login', 'success': True, 'error': None}})
        continue
    elif method == 'model/list':
        result = {'data': [{'id': 'gpt-6.1-sol', 'model': 'gpt-6.1-sol',
                            'inputModalities': ['text', 'image'],
                            'supportedReasoningEfforts': [{'reasoningEffort': 'high'}]}], 'nextCursor': None}
        if mode in ('no_vision', 'queue_model'):
            result['data'][0]['inputModalities'] = ['text']
    elif method == 'thread/start':
        params = request['params']
        assert params['model'] == 'gpt-6.1-sol'
        assert params['config']['model_reasoning_effort'] == 'high'
        result = {'thread': {'id': 'fixture-thread-13'}, 'model': 'gpt-6.1-sol', 'reasoningEffort': 'high'}
        if mode == 'wrong_effort':
            result['reasoningEffort'] = 'low'
        if mode == 'wrong_model':
            result['model'] = 'gpt-6-sol'
    elif method == 'turn/start':
        params = request['params']
        assert params['model'] == 'gpt-6.1-sol' and params['effort'] == 'high'
        assert params['input'][1]['type'] == 'localImage'
        if mode == 'queue_network':
            break  # Original outgoing request exists; acceptance is unknown.
        if mode == 'rejected':
            emit({'id': identifier, 'error': {'code': -32000, 'message': 'Exact model access denied'}})
            continue
        if mode == 'malformed':
            print('not-json', flush=True)
            continue
        if mode == 'slow':
            time.sleep(60)
        result = {'turn': {'id': 'fixture-turn-13', 'status': 'inProgress'}}
        if mode == 'lost_ack':
            state_path.write_text(json.dumps(result['turn']))
            continue
        emit({'id': identifier, 'result': result})
        emit({'method': 'turn/started', 'params': {'threadId': 'fixture-thread-13', 'turn': result['turn']}})
        usage = {'inputTokens': 31, 'cachedInputTokens': 7, 'outputTokens': 9,
                 'reasoningOutputTokens': 3, 'totalTokens': 40}
        emit({'method': 'thread/tokenUsage/updated', 'params': {'threadId': 'fixture-thread-13',
              'turnId': 'fixture-turn-13', 'tokenUsage': {'last': usage, 'total': usage, 'modelContextWindow': None}}})
        if mode == 'queue_quota' and not Path(str(state_path) + '.restored').exists():
            state_path.write_text(json.dumps({'id': 'fixture-turn-13', 'status': 'failed',
                'error': {'message': 'Controlled provider quota', 'codexErrorInfo': 'usageLimitExceeded'}}))
            emit({'method': 'turn/completed', 'params': {'threadId': 'fixture-thread-13',
                'turn': json.loads(state_path.read_text())}})
            continue
        if mode == 'completed_lost_terminal':
            previous = json.loads(state_path.read_text()) if state_path.exists() else {}
            state_path.write_text(json.dumps({'id': 'fixture-turn-13', 'status': 'completed',
                'start_count': previous.get('start_count', 0) + 1}))
            break  # Provider completion is durable, but the transport loses its final frames.
        if mode == 'hold':
            state_path.write_text(json.dumps({'id': 'fixture-turn-13', 'status': 'inProgress'}))
            continue
        if mode == 'rerouted':
            emit({'method': 'model/rerouted', 'params': {'threadId': 'fixture-thread-13', 'turnId': 'fixture-turn-13',
                  'fromModel': 'gpt-6.1-sol', 'toModel': 'gpt-6-sol', 'reason': 'fixture'}})
        if mode == 'tool_used':
            emit({'method': 'item/completed', 'params': {'threadId': 'fixture-thread-13', 'turnId': 'fixture-turn-13',
                  'item': {'type': 'commandExecution', 'id': 'fixture-tool', 'command': 'cat text.txt'}}})
        emit({'method': 'item/completed', 'params': {'threadId': 'fixture-thread-13', 'turnId': 'fixture-turn-13',
              'item': {'type': 'agentMessage', 'id': 'fixture-message', 'text': 'VISION CHILD 13'}}})
        emit({'method': 'turn/completed', 'params': {'threadId': 'fixture-thread-13',
              'turn': {'id': 'fixture-turn-13', 'status': 'interrupted' if mode == 'interrupted' else 'completed', 'items': []}}})
        continue
    elif method == 'turn/interrupt' and mode in ('hold', 'lost_ack'):
        assert request['params'] == {'threadId': 'fixture-thread-13', 'turnId': 'fixture-turn-13'}
        state_path.write_text(json.dumps({'id': 'fixture-turn-13', 'status': 'interrupted'}))
        emit({'id': identifier, 'result': {}})
        emit({'method': 'turn/completed', 'params': {'threadId': 'fixture-thread-13',
            'turn': {'id': 'fixture-turn-13', 'status': 'interrupted', 'items': []}}})
        continue
    elif method == 'thread/read' and mode in ('hold', 'lost_ack', 'completed_lost_terminal', 'queue_quota'):
        assert request['params']['threadId'] == 'fixture-thread-13'
        result = {'thread': {'id': 'fixture-thread-13', 'turns': [json.loads(state_path.read_text())]}}
    else:
        emit({'id': identifier, 'error': {'code': -32601, 'message': 'Unexpected method ' + str(method)}})
        continue
    emit({'id': identifier, 'result': result})
