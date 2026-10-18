"""Controlled native-protocol peer; never actual image-examination evidence."""
import json
import sys
import tomllib
from pathlib import Path

mode = sys.argv[1]
settings = {}
for index, argument in enumerate(sys.argv):
    if argument == '-c':
        for key, value in tomllib.loads(sys.argv[index+1]).items():
            settings.setdefault(key, {}).update(value) if isinstance(value, dict) else settings.update({key: value})


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


for raw in sys.stdin:
    request = json.loads(raw)
    if 'id' not in request:
        continue
    method, params = request['method'], request.get('params', {})
    if method == 'initialize':
        result = {}
    elif method == 'hooks/list':
        hooks = []
        for name, groups in settings['hooks'].items():
            if name == 'state':
                continue
            key = 'geometry:'+name
            hooks.append({'key': key, 'command': groups[0]['hooks'][0]['command'],
                'eventName': name[0].lower()+name[1:], 'currentHash': 'sha256:'+'2'*64,
                'trustStatus': 'trusted' if key in settings['hooks'].get('state', {}) else 'untrusted',
                'source': 'sessionFlags', 'handlerType': 'command', 'enabled': True})
        result = {'data': [{'hooks': hooks, 'errors': []}]}
    elif method == 'account/read':
        result = {'account': {'type': 'chatgpt'}}
    elif method == 'thread/start':
        result = {'thread': {'id': 'geometry-thread'}, 'model': 'gpt-6.1-sol', 'reasoningEffort': 'high'}
    elif method == 'turn/start':
        prompt = params['input'][0]['text']
        source = 'SOURCE_GEOMETRY_PACKET\n' in prompt
        packet = json.loads(prompt.split('SOURCE_GEOMETRY_PACKET\n' if source else 'GEOMETRY_PACKET\n', 1)[1])
        if source:
            answer = {'source_sha256': packet['source_sha256'], 'basis': 'Controlled known source raster letters',
                'samples': [{'id': 'sample-'+str(p['page']), 'page': p['page'], 'bbox': [0, 0, 90, 20],
                    'expected': 'ABC' if p['page']==1 else 'DEF', 'expected_origin': 'Controlled original source image'} for p in packet['pages']]}
        else:
            required_open = {i['line'] for i in packet['unsupported_cells']+packet['geometry_anomalies']}
            answer = {'preparation_sha256': packet['preparation_sha256'], 'images_examined': packet['images'],
                'logical_units': packet['logical_units'], 'geometry_status': 'approximation_requires_character_review',
                'remaining_risks': ['Controlled fixture geometry remains approximate'],
                'lines': [{'id': key, 'status': 'open' if key in required_open else 'examined_approximate',
                    'reason': 'Controlled original and overlay inspected; approximation retained',
                    'evidence': ['checks/geometry-review-001.png']} for key in packet['required_lines']],
                'samples': [{'id': s['id'], 'status': 'examined_approximate', 'reason': 'Controlled source rectangle covers ABC or DEF',
                    'evidence': ['raster/page-'+str(s['page'])+'.png']} for s in packet['source_samples']]}
            if mode == 'missing_line':
                answer['lines'] = answer['lines'][:-1]
            if mode == 'missing_image':
                answer['images_examined'] = answer['images_examined'][:-1]
            if mode == 'template':
                answer['lines'][0]['reason'] = ''
            if mode in ('absolute_paths', 'escaped_path'):
                attached = [i['path'] for i in params['input'] if i['type']=='localImage']
                for image, path in zip(answer['images_examined'], attached):
                    image['path'] = path
                if mode=='escaped_path':
                    answer['images_examined'][0]['path'] = '/tmp/foreign-image.png'
        identifier = 'source-expectations' if source else 'geometry-examination'
        emit({'id': request['id'], 'result': {'turn': {'id': identifier}}})
        def event(method, **values):
            emit({'method': method, 'params': {'threadId': 'geometry-thread', 'turnId': identifier, **values}})
        event('thread/tokenUsage/updated', tokenUsage={'total': {'inputTokens': 123, 'cachedInputTokens': 20,
            'outputTokens': 17, 'reasoningOutputTokens': 5, 'totalTokens': 140}})
        for name in ['sessionStart', 'userPromptSubmit', 'postToolUse', 'stop']:
            event('hook/completed', run={'eventName': name, 'status': 'completed', 'source': 'sessionFlags'})
        event('item/completed', item={'type': 'mcpToolCall', 'server': 'context_mode', 'tool': 'ctx_stats',
            'status': 'completed', 'error': None})
        event('item/completed', item={'type': 'agentMessage', 'phase': 'final_answer', 'text': json.dumps(answer)})
        event('turn/completed', turn={'id': identifier, 'status': 'completed'})
        if not source and mode=='publication_blocked':
            attached = [i['path'] for i in params['input'] if i['type']=='localImage']
            # Deliberate controlled host filesystem fault AFTER provider completion.
            (Path(attached[0]).parents[1]/'geometry-checkpoint.json').mkdir()
        continue
    else:
        raise RuntimeError('Unexpected fixture method '+method)
    emit({'id': request['id'], 'result': result})
