"""Controlled process peer for context failure cases; never real hook evidence."""
import json
import sys
import tomllib
from pathlib import Path

mode = sys.argv[1]
settings = {}
for index, argument in enumerate(sys.argv):
    if argument == '-c':
        parsed = tomllib.loads(sys.argv[index + 1])
        for key, value in parsed.items():
            settings.setdefault(key, {}).update(value) if isinstance(value, dict) else settings.update({key: value})

for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method = request['method']
    if method == 'initialize':
        result = {'userAgent': 'controlled-context-child'}
    elif method == 'hooks/list':
        hooks = []
        for event, groups in settings.get('hooks', {}).items():
            if event == 'state':
                continue
            command = groups[0]['hooks'][0]['command']
            key = 'fixture:' + event
            trusted = key in settings['hooks'].get('state', {}) and mode != 'untrusted'
            hooks.append({'key': key, 'command': command, 'eventName': event[0].lower() + event[1:],
                          'currentHash': 'sha256:' + '1' * 64, 'trustStatus': 'trusted' if trusted else 'untrusted',
                          'enabled': True, 'source': 'sessionFlags', 'handlerType': 'command'})
        result = {'data': [{'cwd': request['params']['cwds'][0], 'errors': [], 'warnings': [], 'hooks': hooks}]}
    elif method == 'account/read':
        result = {'account': None if mode == 'missing_account' else {'type': 'chatgpt'}}
    elif method == 'model/list':
        result = {'data': [{'model': 'gpt-6.1-sol', 'inputModalities': ['text', 'image'],
                           'supportedReasoningEfforts': [{'reasoningEffort': 'high'}]}], 'nextCursor': None}
    elif method in ('thread/start', 'thread/resume'):
        if mode == 'approval_policy' and not all(settings['mcp_servers']['context_mode'].get('tools', {}).get(tool, {}).get('approval_mode') == 'approve' for tool in ['ctx_execute', 'ctx_execute_file', 'ctx_batch_execute', 'ctx_index', 'ctx_search', 'ctx_stats']):
            print(json.dumps({'id': request['id'], 'error': {'code': -32602, 'message': 'Named tools need explicit approval policy'}}), flush=True)
            continue
        result = {'model': 'gpt-6-sol' if mode == 'wrong_model' else 'gpt-6.1-sol',
                  'reasoningEffort': 'high', 'thread': {'id': 'context-fixture-thread'}}
    elif method == 'turn/start':
        recovery = request['params']['input'][0]['text'].startswith('Recover')
        turn_id = 'context-fixture-recovery' if recovery else 'context-fixture-turn'
        result = {'turn': {'id': turn_id, 'status': 'inProgress'}}
        print(json.dumps({'id': request['id'], 'result': result}), flush=True)
        text = next(line.split(' = ', 1)[1] for line in Path('diagnostic-data.txt').read_text().splitlines()
                    if line.startswith('CONTEXT_DIAGNOSTIC_RECORD = '))
        if mode in ('no_recovery', 'full_protocol', 'wrong_generator'):
            print(json.dumps({'method': 'item/completed', 'params': {'threadId': 'context-fixture-thread', 'turnId': turn_id,
                  'item': {'type': 'commandExecution', 'id': 'redirect', 'status': 'completed', 'exitCode': 0,
                  'command': 'echo "context-mode: Build tool redirected."', 'aggregatedOutput': 'context-mode: Build tool redirected.\n'}}}), flush=True)
            print(json.dumps({'method': 'item/completed', 'params': {'threadId': 'context-fixture-thread',
                  'turnId': turn_id, 'item': {'type': 'agentMessage', 'text': 'Diagnostic progress',
                  'phase': 'commentary', 'id': 'progress'}}}), flush=True)
            for event in ['sessionStart', 'preToolUse', 'postToolUse', 'userPromptSubmit', 'stop']:
                print(json.dumps({'method': 'hook/completed', 'params': {'threadId': 'context-fixture-thread',
                      'turnId': turn_id, 'run': {'id': event, 'eventName': event,
                      'status': 'completed', 'source': 'sessionFlags', 'sourcePath': '/<session-flags>/config.toml',
                      'entries': [{'kind': 'context', 'text': '<session_knowledge>'}] if recovery and event == 'sessionStart' else []}}}), flush=True)
            for tool in ['ctx_execute', 'ctx_search']:
                print(json.dumps({'method': 'item/completed', 'params': {'threadId': 'context-fixture-thread',
                      'turnId': turn_id, 'item': {'type': 'mcpToolCall', 'id': tool,
                      'server': 'context_mode', 'tool': tool, 'status': 'completed',
                      'arguments': {'source': 'session-events'} if recovery else
                          {'language': 'shell', 'code': 'echo tiny' if mode == 'wrong_generator' else './gradlew --context-diagnostic'},
                      'result': {'content': [{'type': 'text', 'text': 'CONTEXT_DIAGNOSTIC_RECORD = ' + text}]}, 'error': None}}}), flush=True)
        print(json.dumps({'method': 'item/completed', 'params': {'threadId': 'context-fixture-thread',
              'turnId': turn_id, 'item': {'type': 'agentMessage', 'text': text, 'phase': 'final_answer', 'id': 'answer'}}}), flush=True)
        print(json.dumps({'method': 'turn/completed', 'params': {'threadId': 'context-fixture-thread',
              'turn': {'id': turn_id, 'status': 'completed'}}}), flush=True)
        continue
    elif method == 'thread/compact/start':
        print(json.dumps({'id': request['id'], 'result': {}}), flush=True)
        if mode in ('full_protocol', 'wrong_generator'):
            print(json.dumps({'method': 'hook/completed', 'params': {'threadId': 'context-fixture-thread',
                  'turnId': None, 'run': {'id': 'preCompact', 'eventName': 'preCompact', 'status': 'completed', 'entries': []}}}), flush=True)
        print(json.dumps({'method': 'item/completed', 'params': {'threadId': 'context-fixture-thread',
              'turnId': 'compact-fixture-turn', 'item': {'type': 'contextCompaction', 'id': 'fixture-compaction'}}}), flush=True)
        continue
    else:
        print(json.dumps({'id': request['id'], 'error': {'code': -32601, 'message': 'Unexpected model request'}}), flush=True)
        continue
    print(json.dumps({'id': request['id'], 'result': result}), flush=True)
