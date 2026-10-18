"""Controlled protocol peer. These answers are not native visual-reading proof."""
import hashlib
import json
from pathlib import Path
import sys
import tomllib
import time

mode = sys.argv[1]
settings = {}
for index, argument in enumerate(sys.argv):
    if argument == '-c':
        parsed = tomllib.loads(sys.argv[index + 1])
        for key, value in parsed.items():
            settings.setdefault(key, {}).update(value) if isinstance(value, dict) else settings.update({key: value})


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def event(method, **params):
    emit({'method': method, 'params': {'threadId': 'reading-thread', **params}})


def finish(turn_id, value):
    scale = 1 if turn_id == 'source-turn' else 2
    event('thread/tokenUsage/updated', turnId=turn_id, tokenUsage={'total': {
        'inputTokens': 101 * scale, 'cachedInputTokens': 20 * scale, 'cacheWriteInputTokens': 0,
        'outputTokens': 10 * scale, 'reasoningOutputTokens': 5 * scale, 'totalTokens': 111 * scale}})
    for name in ['sessionStart', 'userPromptSubmit', 'postToolUse', 'stop']:
        event('hook/completed', turnId=turn_id, run={'eventName': name, 'status': 'completed', 'source': 'sessionFlags'})
    event('item/completed', turnId=turn_id, item={'type': 'mcpToolCall', 'server': 'context_mode',
        'tool': 'ctx_stats', 'status': 'completed', 'error': None})
    event('item/completed', turnId=turn_id, item={'type': 'agentMessage', 'phase': 'final_answer',
        'text': json.dumps(value, ensure_ascii=False)})
    event('turn/completed', turn={'id': turn_id, 'status': 'completed'})


pending = None
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    if 'method' not in request:
        if pending == 'query':
            pending = 'image'
            emit({'id': 'dynamic-image', 'method': 'item/tool/call', 'params': {'threadId': 'reading-thread',
                'turnId': 'accounting-turn', 'callId': 'image', 'tool': 'ocr_image', 'arguments': {'page': 1}}})
        elif pending == 'image':
            pending = 'validate'
            emit({'id': 'dynamic-validate', 'method': 'item/tool/call', 'params': {'threadId': 'reading-thread',
                'turnId': 'accounting-turn', 'callId': 'validate', 'tool': 'ocr_validate', 'arguments': {'proposal': proposal}}})
        else:
            finish('accounting-turn', proposal)
        continue
    method, params = request['method'], request.get('params', {})
    if method == 'initialize':
        result = {}
    elif method == 'hooks/list':
        hooks = []
        for name, groups in settings['hooks'].items():
            if name == 'state':
                continue
            key = 'reading:' + name
            hooks.append({'key': key, 'command': groups[0]['hooks'][0]['command'],
                'eventName': name[0].lower() + name[1:], 'currentHash': 'sha256:' + '2' * 64,
                'trustStatus': 'trusted' if key in settings['hooks'].get('state', {}) else 'untrusted',
                'source': 'sessionFlags', 'handlerType': 'command', 'enabled': True})
        result = {'data': [{'hooks': hooks, 'errors': []}]}
    elif method == 'account/read':
        result = {'account': {'type': 'chatgpt'}}
    elif method == 'model/list':
        result = {'data': [{'model': 'gpt-6.1-sol', 'inputModalities': ['text', 'image'],
            'supportedReasoningEfforts': [{'reasoningEffort': 'high'}]}], 'nextCursor': None}
    elif method == 'thread/start':
        result = {'thread': {'id': 'reading-thread'}, 'model': 'gpt-6-sol' if mode == 'wrong_model' else 'gpt-6.1-sol', 'reasoningEffort': 'high'}
    elif method == 'turn/start':
        source = len([item for item in params['input'] if item['type'] == 'localImage']) > 0
        turn_id = 'source-turn' if source else 'accounting-turn'
        emit({'id': request['id'], 'result': {'turn': {'id': turn_id}}})
        packet = json.loads(Path('reading-packet.json').read_text())
        if source:
            if mode == 'slow':
                time.sleep(.5)
            review = {'source_sha256': packet['source_sha256'], 'lines': [], 'units': [],
                'dropped_candidates': [], 'unresolved': [], 'publisher_errors': [], 'risk_register': []}
            for page in packet['pages']:
                number = page['page']
                review['lines'].append({'id': f'line-{number}', 'candidate_id': None, 'page': number,
                    'text': 'ABC' if number == 1 else 'DEF', 'selection_region': [0, 0, 90, 20],
                    'source_crop': f'raster/page-{number}.png', 'text_status': 'visually_confirmed',
                    'decision_basis': 'Controlled source image reading', 'join_after': 'none'})
                review['units'].append({'id': f'unit-{number}', 'article': f'article-{number}',
                    'page': number, 'tag': 'P', 'line_ids': [f'line-{number}']})
            source_answer = {'read_pages': [p['page'] for p in packet['pages']], 'review': review}
            if mode == 'uncertain':
                review['lines'][0].update(text='Dne [NEČITELNÉ]', text_status='partially_unresolved')
                review['unresolved'] = [{'id': 'uncertain-date', 'line': 'line-1', 'context': 'Dne',
                    'source_crop': 'raster/page-1.png', 'bbox': [20, 0, 90, 20], 'reason': 'Blurred date',
                    'status': 'waiting_for_input', 'candidates': ['12.', '17.']}]
                review['publisher_errors'] = [{'id': 'publisher-typo', 'line': 'line-2', 'printed': 'DEF',
                    'explanation': 'Controlled readable printed mistake', 'status': 'confirmed',
                    'source_crop': 'raster/page-2.png', 'bbox': [0, 0, 90, 20]}]
            if mode == 'partial_source':
                source_answer['read_pages'] = [1]
            finish(turn_id, source_answer)
        else:
            metadata = json.loads(params['input'][0]['text'].split('READING_ACCOUNTING_PACKET\n', 1)[1])
            for number, row in enumerate(review['lines'], 1):
                row['candidate_id'] = f'candidate-{number}'
            proposal = {'review': review, 'expected_review_sha256': packet['expected_review_sha256'],
                'coverage': {'source_turn_id': metadata['source_turn_id'],
                    'source_answer_sha256': metadata['source_answer_sha256'],
                    'pages': [{'page': p['page'], 'sha256': p['sha256'], 'line_ids': [f"line-{p['page']}"],
                        'blank_reason': None} for p in packet['pages']]}}
            if mode == 'partial_final':
                proposal['coverage']['pages'] = proposal['coverage']['pages'][:1]
            pending = 'query'
            emit({'id': 'dynamic-query', 'method': 'item/tool/call', 'params': {'threadId': 'reading-thread',
                'turnId': turn_id, 'callId': 'query', 'tool': 'ocr_query', 'arguments': {'view': 'candidates', 'page': 1}}})
        continue
    else:
        emit({'id': request['id'], 'error': {'code': -32601, 'message': 'Unexpected request'}})
        continue
    emit({'id': request['id'], 'result': result})
