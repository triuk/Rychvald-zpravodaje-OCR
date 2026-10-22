"""Controlled native-protocol peer; never actual image-examination evidence."""
import json
import os
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
        output = 'OUTPUT_PACKET\n' in prompt
        gate = os.environ.get('QUEUE_DESCENDANT_LOST_ACK')
        if output and gate and Path(gate).exists():
            Path(gate + '.ready').write_text('Controlled descendant turn accepted; acknowledgement lost')
            continue
        correction = 'CORRECTION_PACKET\n' in prompt
        packet = json.loads(prompt.split('CORRECTION_PACKET\n' if correction else 'OUTPUT_PACKET\n' if output else 'SOURCE_GEOMETRY_PACKET\n' if source else 'GEOMETRY_PACKET\n', 1)[1])
        if correction:
            line = dict(packet['lines'][0], text='ABC', decision_basis='Controlled targeted source ABC crop reading')
            if mode == 'repeated':
                line['text'] = packet['lines'][0]['text']
                line['selection_region'] = [0, 0, 90 + packet['index'], 20]
            if mode == 'limit':
                line['text'] = {1: 'AYC', 2: 'AZC', 3: 'AQC'}[packet['index']]
            if mode == 'invalid':
                line['selection_region'] = [0, 0, 99999, 20]
            answer = {'expected_review_sha256': packet['expected_review_sha256'],
                'expected_iteration_id': packet['expected_iteration_id'], 'target_finding_ids': packet['target_finding_ids'],
                'images_examined': packet['images'], 'patch': {'lines': [{'line': line}]},
                'decisions': [{'finding_id': key, 'reason': 'Controlled ABC scan supports changing mistaken AXC to ABC',
                    'evidence': [packet['images'][0]['path']]} for key in packet['target_finding_ids']],
                'remaining_uncertainties': ['Geometry remains approximate']}
            if mode == 'noop':
                answer['patch'] = {'lines': []}
            if mode == 'publisher':
                answer['patch']['lines'][0]['publisher_errors'] = []
        elif output:
            visual = {**packet['visual_review'], 'reviewer': 'Explicit controlled model peer',
                'pages_reviewed': packet['pages'], 'evidence': [i['path'] for i in packet['images']],
                'geometry_status': 'approximation_requires_character_review',
                'conclusion': 'Controlled actual exported page inspection; known ABC/DEF synthetic fixture, approximation retained'}
            findings = {**packet['findings'], 'items': [{**row, 'status': 'open',
                'reason': 'Controlled fixture retains this explicitly open limitation',
                'evidence': [packet['images'][0]['path']]} for row in packet['findings']['items']]}
            answer = {'preparation_sha256': packet['preparation_sha256'], 'images_examined': packet['images'],
                'visual_review': visual, 'findings': findings}
            if mode in ('repair', 'repeated', 'limit', 'invalid', 'noop', 'publisher'):
                # Actual #17 OUTPUT_SCHEMA has no page/bbox/expected/actual in
                # model finding rows. Native diagnostics own those details.
                findings['items'] = [{key: row[key] for key in ('id', 'status', 'reason', 'evidence')}
                    for row in findings['items']]
            if mode == 'waive_output':
                visual['geometry_status'] = 'visually_verified'
                for row in findings['items']:
                    row['status'] = 'resolved'
            if mode == 'drop_output':
                findings['items'] = []
            if mode == 'template_output':
                visual.update(conclusion='', pages_reviewed=[])
            if mode == 'absolute_input_evidence':
                attached = [i['path'] for i in params['input'] if i['type'] == 'localImage']
                paths = [attached[0], packet['inputs']['checks/visual-review.json']['path']]
                visual['evidence'] = paths
                for row in findings['items']:
                    row['evidence'] = paths
            if mode == 'outside_evidence':
                visual['evidence'] = [packet['technical']['inputs']['source']['path']]
        elif source:
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
                    'evidence': [packet['images'][-1]['path']] if packet.get('correction_scope') else
                        ['raster/page-'+str(s['page'])+'.png']} for s in packet['source_samples']]}
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
        identifier = 'output-examination' if output else 'source-expectations' if source else 'geometry-examination'
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
        if output and mode == 'tamper_output':
            attached = [i['path'] for i in params['input'] if i['type'] == 'localImage']
            Path(attached[0]).write_bytes(b'Controlled changed pixels after completed model turn')
        if output and mode == 'tamper_geometry':
            attached = [i['path'] for i in params['input'] if i['type'] == 'localImage']
            (Path(attached[0]).parents[1] / 'geometry.json').write_text('[]')
        if not source and mode=='publication_blocked':
            attached = [i['path'] for i in params['input'] if i['type']=='localImage']
            # Deliberate controlled host filesystem fault AFTER provider completion.
            (Path(attached[0]).parents[1]/'geometry-checkpoint.json').mkdir()
        continue
    else:
        raise RuntimeError('Unexpected fixture method '+method)
    emit({'id': request['id'], 'result': result})
