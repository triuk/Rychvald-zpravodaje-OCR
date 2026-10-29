"""Replayable accounting over original process artifacts, without model calls.

`total` is treated as a cumulative observation only inside a demonstrably fresh
thread/connection epoch. This is an explicit accounting policy, not a claim that
the app-server guarantees billing semantics across resumes or compaction.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path

from app.jobs import atomic_json


POLICY = 'fresh-thread-cumulative-observations-v1'
FIELDS = ('inputTokens', 'cachedInputTokens', 'outputTokens', 'reasoningOutputTokens',
          'cacheWriteInputTokens', 'totalTokens')
CATEGORIES = [
    {'key': 'noncached_input', 'label': 'Necacheovaný vstup', 'color': '#2563eb'},
    {'key': 'cached_input', 'label': 'Vstup z AI cache', 'color': '#9333ea'},
    {'key': 'output', 'label': 'Výstup včetně reasoning', 'color': '#ea580c'},
]
COST_SCALE = {'unit': 'USD', 'thresholds': [0, .001, .01, .1, 1, 10],
              'colors': ['#f8fafc', '#dbeafe', '#93c5fd', '#3b82f6', '#1d4ed8', '#172554'],
              'unknown_color': '#e5e7eb'}
PRICE_CARD = {
    'id': 'gpt-6.1-sol-standard-short-2026-10-16', 'model': 'gpt-6.1-sol',
    'retrieved_at': '2026-10-16', 'currency': 'USD', 'unit_tokens': 1000000,
    'scenario': 'Standard API, every request <=272000 input tokens, no regional uplift',
    'rates': {'input': 2., 'cached_input': .1, 'cache_write_input': 2.5, 'output': 10.},
    'long_request_threshold': 272000,
    'long_request_rates': {'input': 4., 'cached_input': .2, 'cache_write_input': 5., 'output': 15.},
    'source_urls': ['https://developers.openai.com/api/docs/models/gpt-6.1-sol',
                    'https://developers.openai.com/api/docs/guides/prompt-caching'],
    'assumptions': ['Comparative API scenario; not a ChatGPT subscription charge.',
                    'High reasoning does not identify a service tier.',
                    'Cache writes replace ordinary input pricing; reasoning is included in output.',
                    'Request-level tier, regional routing and long-context mix are not established by thread totals.'],
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def safe_file(root, path):
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError('Metric source is outside the registry.')
    return candidate


def stamp(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (TypeError, ValueError, AttributeError):
        return None


def union_length(intervals):
    merged = []
    for start, end in sorted((a, b) for a, b in intervals if a is not None and b is not None and b >= a):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return sum(b - a for a, b in merged)


def waiting_length(waiting, active):
    # Explicitly waiting spans cannot simultaneously count as active work.
    return max(0., union_length(waiting + active) - union_length(active))


def subtract(intervals, excluded):
    result = []
    for start, end in intervals:
        spans = [[start, end]]
        for a, b in excluded:
            spans = [[c, d] for x, y in spans for c, d in ((x, min(y, a)), (max(x, b), y)) if d > c]
        result.extend(spans)
    return result


def unknown(reason, status='unavailable'):
    return {'status': status, 'values': None, 'reasoning_output': None, 'cache_write_input': None,
            'reasons': [reason]}


def tokens(value, reasons=()):
    required = ('inputTokens', 'cachedInputTokens', 'outputTokens')
    if any(type(value.get(k)) is not int or value[k] < 0 for k in required):
        return unknown('Missing or invalid input/cached/output counters.')
    i, c, o = (value[k] for k in required)
    r, w, total = (value.get(k) for k in ('reasoningOutputTokens', 'cacheWriteInputTokens', 'totalTokens'))
    if c > i or any(x is not None and (type(x) is not int or x < 0) for x in (r, w, total)):
        return unknown('Inconsistent token counters.')
    if (r is not None and r > o) or (w is not None and c + w > i) or (total is not None and total != i + o):
        return unknown('Inconsistent token counter categories.')
    missing = [k + ' was not reported numerically.' for k in FIELDS if type(value.get(k)) is not int]
    return {'status': 'partial' if missing or reasons else 'observed',
            'values': {'noncached_input': i - c, 'cached_input': c, 'output': o},
            'reasoning_output': r, 'cache_write_input': w, 'reasons': list(reasons) + missing}


def add_tokens(parts):
    if not parts:
        return unknown('No AI usage observation was reported.')
    if any(p['values'] is None for p in parts):
        return unknown('Some attempts have unknown usage; run totals are incomplete.', 'partial')
    result = {'status': 'observed' if all(p['status'] == 'observed' for p in parts) else 'partial',
              'values': {k: sum(p['values'][k] for p in parts) for k in parts[0]['values']},
              'reasons': sorted(set(r for p in parts for r in p['reasons']))}
    for key in ('reasoning_output', 'cache_write_input'):
        result[key] = None if any(p[key] is None for p in parts) else sum(p[key] for p in parts)
    return result


def price(usage, model, card):
    result = {'usd': None, 'kind': 'comparative_api_scenario', 'price_card_id': card['id'],
              'price_card_sha256': digest(card), 'scenario': card['scenario'],
              'not_subscription_billing': True, 'reason': None}
    if model != card['model']:
        result['reason'] = 'No exact-model price card; no replacement model was substituted.'
    elif usage['values'] is None or usage['cache_write_input'] is None:
        result['reason'] = 'Complete input/cache-write/output observations are required for pricing.'
    else:
        v, w, rates = usage['values'], usage['cache_write_input'], card['rates']
        result['usd'] = ((v['noncached_input'] - w) * rates['input'] + w * rates['cache_write_input']
                         + v['cached_input'] * rates['cached_input'] + v['output'] * rates['output']) / card['unit_tokens']
    return result


def protocol_rows(root, relative, sources, warnings):
    path = safe_file(root, relative)
    if not path.is_file():
        warnings.append('Missing protocol: ' + relative)
        return []
    raw = path.read_bytes()
    sources[relative] = hashlib.sha256(raw).hexdigest()
    rows, offset = [], 0
    for number, line in enumerate(raw.splitlines(keepends=True), 1):
        if not line.endswith(b'\n'):
            warnings.append('Incomplete JSONL tail retained: ' + relative)
            break
        try:
            value = json.loads(line)
            if not isinstance(value, dict) or not isinstance(value.get('message'), dict):
                raise ValueError()
            value['_source'] = {'path': relative, 'line': number, 'byte_offset': offset,
                                'sha256': hashlib.sha256(line).hexdigest()}
            rows.append(value)
        except (ValueError, TypeError):
            warnings.append(f'Invalid protocol line retained: {relative}:{number}')
        offset += len(line)
    return rows


def ai_step(root, attempt, rows):
    aid = attempt['attempt_id']
    step = {'step_id': 'ai:' + aid, 'kind': 'ai', 'operation': attempt.get('operation'),
            'attempt_id': aid, 'run_id': attempt.get('run_id'), 'thread_id': attempt.get('thread_id'),
            'turn_ids': [], 'state': attempt.get('state'), 'started_at': attempt.get('started_at'),
            'ended_at': attempt.get('ended_at'), 'artifacts': attempt.get('artifacts', {}),
            'profile_sha256': attempt.get('profile_sha256'), 'usage_sources': [], 'attempt': attempt}
    pending, fresh, epochs, snapshots, problems = {}, {}, {}, {}, []
    turn_threads = {}
    for row in rows:
        m = row['message']
        connection = row.get('connection_id', 'legacy-single-connection')
        fresh.setdefault(connection, set())
        epochs.setdefault(connection, -1)
        method, params = m.get('method'), m.get('params') or {}
        if row.get('direction') == 'client':
            if method == 'initialize':
                epochs[connection] += 1
                fresh[connection] = set()
            if method == 'thread/resume':
                fresh[connection].discard(params.get('threadId'))
            if method and 'compact' in method.lower():
                problems.append('Compaction semantics are unknown; usage cannot be completed across this boundary.')
            if 'id' in m:
                pending[connection, m['id']] = (method, params)
            continue
        if 'id' in m and (connection, m['id']) in pending:
            request, args = pending.pop((connection, m['id']))
            result = m.get('result') or {}
            if request == 'thread/start' and result.get('thread', {}).get('id'):
                fresh[connection].add(result['thread']['id'])
            if request == 'turn/start' and result.get('turn', {}).get('id'):
                turn_threads[connection, result['turn']['id']] = args.get('threadId')
        if 'compact' in str(method).lower() or 'compaction' in str(params.get('item', {}).get('type', '')).lower():
            problems.append('Compaction semantics are unknown; usage cannot be completed across this boundary.')
        if method != 'thread/tokenUsage/updated':
            continue
        thread, turn = params.get('threadId'), params.get('turnId')
        usage = params.get('tokenUsage') or {}
        total = usage.get('total')
        epoch = (connection, epochs[connection])
        source = {**row['_source'], 'epoch': aid + ':' + connection + ':' + str(epochs[connection]),
                  'connection_id': connection, 'thread_id': thread, 'turn_id': turn,
                  'received_at': row.get('timestamp'), 'elapsed_seconds': row.get('elapsed_seconds'),
                  'emitted_at_ms': m.get('emittedAtMs'), 'field_presence': sorted(total) if isinstance(total, dict) else [],
                  'usage_field_presence': sorted(usage),
                  'last_field_presence': sorted(usage['last']) if isinstance(usage.get('last'), dict) else [],
                  'mapping_basis': 'Original thread/start and turn/start RPC requests/responses in this connection epoch',
                  'original': deepcopy(m), 'disposition': 'observed'}
        step['usage_sources'].append(source)
        if thread not in fresh[connection] or not turn or (turn_threads.get((connection, turn)) != thread):
            source['disposition'] = 'unmapped_or_unknown_epoch'
            problems.append('Usage lacks a proven fresh-thread baseline and submitted turn mapping.')
            continue
        if turn not in step['turn_ids']:
            step['turn_ids'].append(turn)
        if not isinstance(total, dict):
            problems.append('Usage total is missing.')
            continue
        key = (epoch, thread)
        previous = snapshots.get(key)
        if previous and total == previous['total']:
            source['disposition'] = 'duplicate'
            continue
        if previous and any(type(total.get(k)) is int and type(previous['total'].get(k)) is int
                            and total[k] < previous['total'][k] for k in FIELDS):
            emitted, older = m.get('emittedAtMs'), previous.get('emitted')
            if type(emitted) is int and type(older) is int and emitted < older:
                source['disposition'] = 'delayed_observation'
                continue
            problems.append('Cumulative counters decreased; reset/epoch semantics are unknown.')
            source['disposition'] = 'unknown_reset'
        snapshots[key] = {'total': total, 'emitted': m.get('emittedAtMs')}
    usage = add_tokens([tokens(s['total']) for s in snapshots.values()])
    if problems:
        usage = unknown('; '.join(sorted(set(problems))), 'partial')
    elif attempt.get('state') != 'completed' and usage['values'] is not None:
        usage['status'] = 'partial'
        usage['reasons'].append('Attempt did not complete; observed consumption is retained.')
    step['tokens'] = usage
    actual_settings = sorted({(row['message']['params']['model'], row['message']['params'].get('effort'))
        for row in rows if row.get('direction') == 'client' and row['message'].get('method') == 'turn/start'
        and isinstance(row['message'].get('params', {}).get('model'), str)}, key=lambda item: (item[0], str(item[1])))
    step['model_settings'] = [{'model': model, 'reasoning_effort': effort} for model, effort in actual_settings]
    step['model_attribution'] = 'mixed_models' if len({model for model, _ in actual_settings}) > 1 else 'single_model' if actual_settings else 'not_observed'
    step['model'] = (attempt.get('effective') or {}).get('model')
    if attempt.get('reroutes') or step['model_attribution'] == 'mixed_models':
        step['model'] = None
    step['timing'] = timing(step, rows)
    return step


def timing(step, rows=()):
    start, end = stamp(step.get('started_at')), stamp(step.get('ended_at'))
    submitted = stamp(step.get('attempt', {}).get('submitted_at'))
    wall = end - start if start is not None and end is not None and end >= start else None
    work = [[start, end]] if wall is not None else []
    waiting = []
    for interval in step.get('attempt', {}).get('waiting_intervals', []):
        if not isinstance(interval, list) or len(interval) != 2:
            continue
        a, b = map(stamp, interval)
        if a is not None and b is not None and b >= a:
            waiting.append([a, b])
    active = subtract(work, waiting)
    tools, spans = {}, []
    for row in rows:
        m = row['message']
        p, at = m.get('params') or {}, stamp(row.get('timestamp'))
        item = p.get('item') or {}
        if item.get('type') not in ('commandExecution', 'mcpToolCall', 'dynamicToolCall',
                                    'webSearch', 'imageView', 'fileChange', 'collabAgentToolCall') or not item.get('id'):
            continue
        if m.get('method') == 'item/started':
            tools[row.get('connection_id'), item['id']] = at
        elif m.get('method') == 'item/completed' and (row.get('connection_id'), item['id']) in tools:
            spans.append([tools.pop((row.get('connection_id'), item['id'])), at])
    return {'wall_seconds': wall, 'active_seconds': union_length(active) if active else None,
            'waiting_seconds': union_length(waiting) if waiting else None,
            'waiting_reason': None if waiting else 'No explicit waiting/queue/approval span was recorded.',
            'startup_seconds': submitted - start if submitted is not None and start is not None and submitted >= start else None,
            'turn_wall_seconds': end - submitted if submitted is not None and end is not None and end >= submitted else None,
            'tool_seconds': union_length(spans) if spans else None,
            'active_intervals': active, 'waiting_intervals': waiting,
            'tool_time_is_nested': True,
            'basis': 'Observed application worker wall span excluding explicit waits; not provider compute time. Startup and submitted-turn wall spans are separate. Nested tool spans are not added.'}


def local_steps(root, application, run, sources, warnings):
    history_path = run['artifacts']['history']['path']
    history = safe_file(root, history_path).read_bytes()
    sources[history_path] = hashlib.sha256(history).hexdigest()
    events = run.get('history', [])
    steps = []
    for path in sorted((application / 'attempts').glob('*.json')):
        if path.name.endswith(('.stdout.json', '.control.json')):
            continue
        path = safe_file(root, path)
        raw = path.read_bytes()
        sources[str(path.relative_to(root))] = hashlib.sha256(raw).hexdigest()
        try:
            attempt = json.loads(raw)
            if attempt.get('run_id') != run['project']['run_id'] or attempt.get('root') != str(root):
                raise ValueError('Local attempt has a different registry/run identity.')
            aid = attempt['attempt_id']
            # New native admissions retain their units in a single journal.
            # Keep the legacy reader for earlier preparation-only histories.
            if (application / 'local-attempts' / (aid + '.json')).is_file():
                continue
            grouped = {}
            for event in events:
                if event.get('attempt_id') == aid and event.get('step_id'):
                    grouped.setdefault(event['step_id'], []).append(event)
            for sid, group in grouped.items():
                starts = [e for e in group if e['type'] in ('step_started', 'unit_started')]
                ends = [e for e in group if e['type'] in ('step_completed', 'step_failed', 'unit_completed', 'unit_cached')]
                if not starts and not ends:
                    continue
                first, last = (starts[0] if starts else {}), (ends[-1] if ends else {})
                intervals = [[stamp(first.get('timestamp')), stamp(last.get('timestamp'))]] if first and last else []
                state = {'unit_cached': 'cached', 'step_failed': 'failed'}.get(last.get('type'),
                    'completed' if last else attempt.get('state', 'running'))
                usage = unknown('Local work is not AI usage.', 'not_applicable')
                steps.append({'step_id': 'local:' + aid + ':' + sid, 'native_step_id': sid,
                    'kind': 'local', 'operation': 'prepare', 'attempt_id': aid, 'run_id': run['project']['run_id'],
                    'phase': 'preparation', 'edition_id': run['project']['source_sha256'],
                    'scope': 'legacy_unit', 'parent_step_id': None,
                    'tool': first.get('tool', {'name': 'Původní místní krok', 'version': None}),
                    'command': first.get('command', []), 'parameters': first,
                    'inputs': first.get('inputs', []), 'outputs': last.get('outputs', []), 'error': last.get('error'),
                    'thread_id': None, 'turn_ids': [], 'started_at': first.get('timestamp'),
                    'origin': last.get('origin', 'same_run_cache' if last.get('type') == 'unit_cached' else 'computed'),
                    'import_provenance': last.get('import_provenance'),
                    'ended_at': last.get('timestamp'), 'state': state, 'events': group, 'attempt': attempt,
                    'artifacts': {'attempt': str(path.relative_to(root)), 'history': history_path},
                    'usage_sources': [], 'tokens': usage, 'model': None,
                    'timing': {'wall_seconds': last.get('duration_seconds'),
                               'active_seconds': union_length(intervals) if intervals else None,
                               'waiting_seconds': None, 'tool_seconds': None,
                               'active_intervals': intervals, 'waiting_intervals': [], 'tool_time_is_nested': True,
                               'basis': 'Native step/unit start and terminal events. Nested intervals are unioned; unobserved waiting is unknown.'}})
        except (ValueError, KeyError, TypeError) as error:
            warnings.append(str(path.relative_to(root)) + ': ' + str(error))
    return steps


def native_local_steps(root, application, run, sources, warnings):
    """Read durable local admissions without changing their terminal state."""
    from app.jobs import read_history
    steps = []
    for path in sorted((application / 'local-attempts').glob('*.json')):
        try:
            path = safe_file(root, path)
            raw = path.read_bytes()
            sources[str(path.relative_to(root))] = hashlib.sha256(raw).hexdigest()
            attempt = json.loads(raw)
            aid = attempt['attempt_id']
            if (attempt.get('schema_version') != 1 or path.stem != aid or
                    attempt.get('root') != str(root) or attempt.get('run_id') != run['project']['run_id'] or
                    attempt.get('edition_id') != run['project']['source_sha256']):
                raise ValueError('Native local attempt belongs to another registry, source or run.')
            journal = safe_file(root, path.with_suffix('.jsonl'))
            content = journal.read_bytes()
            sources[str(journal.relative_to(root))] = hashlib.sha256(content).hexdigest()
            events = read_history(journal)
            grouped, seen = {}, set()
            for event in events:
                if event.get('event_id') in seen:
                    continue
                if (event.get('attempt_id') != aid or event.get('run_id') != attempt['run_id'] or
                        event.get('edition_id') != attempt['edition_id']):
                    raise ValueError('Native journal event has a foreign admission/source identity.')
                seen.add(event['event_id'])
                grouped.setdefault(event['step_id'], []).append(event)
            alive = False
            try:
                fields = Path(f'/proc/{attempt["pid"]}/stat').read_text().rsplit(')', 1)[1].split()
                alive = fields[0] not in ('Z', 'X') and fields[19] == attempt.get('process_start_ticks')
            except (OSError, KeyError, IndexError):
                pass
            for sid, group in grouped.items():
                first = next((e for e in group if e['type'] == 'started'), None)
                last = next((e for e in reversed(group) if e['type'] in ('completed', 'failed', 'cached', 'interrupted')), None)
                if first is None:
                    continue
                end = last.get('timestamp') if last else None
                start = first['timestamp']
                a, b = stamp(start), stamp(end)
                intervals = [[a, b]] if a is not None and b is not None and b >= a else []
                state = last['type'] if last else 'running' if alive else 'interrupted'
                parent = first.get('parent_step_id')
                identifier = 'native:' + aid + ':' + sid
                error = last.get('error') if last else None
                if not last and not alive:
                    error = {'code': 'native_owner_ended', 'message': 'Native owner ended before publishing this step result; its completion is unknown.'}
                steps.append({'step_id': identifier, 'native_step_id': sid, 'kind': 'local',
                    'operation': first.get('operation', attempt['operation']), 'phase': attempt['phase'],
                    'edition_id': attempt['edition_id'], 'run_id': attempt['run_id'], 'attempt_id': aid,
                    'parent_attempt': attempt.get('owner'), 'scope': first.get('scope', 'tool'),
                    'parent_step_id': 'native:' + aid + ':' + parent if parent is not None else None,
                    'thread_id': None, 'turn_ids': [], 'started_at': start, 'ended_at': end,
                    'state': state, 'error': error, 'events': group, 'attempt': attempt,
                    'tool': first.get('tool', attempt['tool']), 'command': first.get('command', []),
                    'parameters': first.get('parameters', {}), 'inputs': first.get('inputs', []),
                    'outputs': last.get('outputs', []) if last else [],
                    'observations': last.get('details') if last else None,
                    'result': last.get('result') if last else None,
                    'origin': last.get('origin', 'computed') if last else 'computed',
                    'import_provenance': last.get('import_provenance') if last else None,
                    'artifacts': {'attempt': str(path.relative_to(root)), 'history': str(journal.relative_to(root))},
                    'usage_sources': [], 'tokens': unknown('Local work is not AI usage.', 'not_applicable'), 'model': None,
                    'timing': {'wall_seconds': last.get('duration_seconds', b - a if intervals else None) if last else None,
                        'active_seconds': union_length(intervals) if intervals else None, 'waiting_seconds': None,
                        'tool_seconds': None, 'active_intervals': intervals, 'waiting_intervals': [],
                        'tool_time_is_nested': True,
                        'basis': 'Observed native operation, workflow and tool spans. Parent/child intervals are unioned, never added. Missing terminal records remain incomplete.'}})
        except (OSError, ValueError, KeyError, TypeError) as error:
            warnings.append(str(path.relative_to(root)) + ': ' + str(error))
    return steps


def collect(root, run):
    root = Path(root).resolve()
    rid = run['project']['run_id']
    application = safe_file(root, run['artifacts']['run_manifest']['path']).parent
    application = safe_file(root, application)
    sources, steps, warnings, local_warnings = {}, [], [], []
    for path in sorted(path for namespace in ('codex-attempts', 'context-attempts', 'reading-attempts', 'geometry-attempts', 'output-review-attempts', 'correction-attempts')
                       for path in (application / namespace).glob('*/attempt.json')):
        path = safe_file(root, path)
        raw = path.read_bytes()
        relative = str(path.relative_to(root))
        sources[relative] = hashlib.sha256(raw).hexdigest()
        try:
            attempt = json.loads(raw)
            if attempt.get('run_id') != rid or attempt.get('root') != str(root):
                raise ValueError('Attempt identity differs from the selected registry/run.')
            rows = protocol_rows(root, attempt['artifacts']['protocol'], sources, warnings)
            if attempt['artifacts'].get('request'):
                request_path = safe_file(root, attempt['artifacts']['request'])
                if request_path.is_file():
                    sources[attempt['artifacts']['request']] = hashlib.sha256(request_path.read_bytes()).hexdigest()
            if attempt.get('operation') not in ('check_account', 'login'):
                step = ai_step(root, attempt, rows)
                if any('tail retained: ' + attempt['artifacts']['protocol'] in w or
                       'Invalid protocol line retained: ' + attempt['artifacts']['protocol'] in w for w in warnings):
                    step['tokens'] = unknown('Protocol contains an incomplete or invalid row; accounting coverage is incomplete.', 'partial')
                steps.append(step)
        except (ValueError, KeyError, TypeError) as error:
            warnings.append(relative + ': ' + str(error))
    steps.extend(local_steps(root, application, run, sources, warnings))
    steps.extend(native_local_steps(root, application, run, sources, local_warnings))
    steps.sort(key=lambda s: (s.get('started_at') or '', s['step_id']))
    directory = application / 'metrics'
    directory.mkdir(parents=True, exist_ok=True)
    card_path = directory / 'price-card.json'
    if card_path.exists():
        card = json.loads(safe_file(root, card_path).read_text())
    else:
        card = deepcopy(PRICE_CARD)
        atomic_json(card_path, card)
    for step in steps:
        step['cost'] = price(step['tokens'], step['model'], card)
        if step['kind'] == 'local':
            step['cost']['reason'] = 'Local work has no applicable API token price.'
    ai, owners = [], {}
    for step in (s for s in steps if s['kind'] == 'ai'):
        scope = (step['thread_id'], tuple(step['turn_ids']))
        previous = owners.get(scope) if scope[0] and scope[1] else None
        if previous:
            originals = lambda s: [v['original'] for v in s['usage_sources']]
            if originals(previous) == originals(step):
                step['duplicate_of'] = previous['step_id']
                continue
            step['tokens'] = unknown('Overlapping thread/turn observations across attempts have unresolved ownership.', 'partial')
            step['cost'] = price(step['tokens'], step['model'], card)
        owners[scope] = step
        ai.append(step)
    usage = add_tokens([s['tokens'] for s in ai])
    if warnings:
        usage = unknown('Metric source artifacts are incomplete or invalid; known step observations remain available.', 'partial')
    cost = price(usage, card['model'], card)
    if not warnings and ai and all(s['cost']['usd'] is not None for s in ai):
        cost['usd'] = sum(s['cost']['usd'] for s in ai)
    elif any(s['cost']['usd'] is None for s in ai):
        cost['usd'] = None
        cost['reason'] = 'Some steps cannot be priced under the exact-model scenario.'
    active = [v for s in steps for v in s['timing']['active_intervals']]
    waiting = [v for s in steps for v in s['timing']['waiting_intervals']]
    queue_intervals = []
    queue_closed = []
    queue_path = root / 'application/queue.json'
    if queue_path.exists():
        queue_bytes = queue_path.read_bytes()
        queued = json.loads(queue_bytes)
        if queued['schema_version'] != 1 or queued['root'] != str(root):
            raise ValueError('Queue history belongs to another registry/schema.')
        sources[str(queue_path.relative_to(root))] = hashlib.sha256(queue_bytes).hexdigest()
        queue_intervals = [dict(interval, item_id=item['item_id']) for item in queued['items']
            if item['run_id'] == rid for interval in item.get('waiting_intervals', [])]
        for interval in queue_intervals:
            a, b = stamp(interval['start']), stamp(interval['end'])
            if a is not None and b is not None and b >= a:
                waiting.append([a, b])
                queue_closed.append([a, b])
    queue_complete = bool(queue_intervals) and len(queue_closed) == len(queue_intervals)
    starts = [stamp(s['started_at']) for s in steps if stamp(s.get('started_at')) is not None]
    ends = [stamp(s['ended_at']) for s in steps if stamp(s.get('ended_at')) is not None]
    span = max(ends) - min(starts) if starts and len(ends) == len(steps) else None
    page_count = run.get('counts', {}).get('pages')
    result = {'schema_version': 1, 'policy': POLICY, 'run_id': rid,
              'source_hash': digest(sources), 'sources': sources, 'warnings': warnings, 'local_warnings': local_warnings,
              'tokens': usage, 'cost': cost, 'steps': steps, 'categories': CATEGORIES, 'cost_scale': COST_SCALE,
              'queue': {'waiting_intervals': queue_intervals,
                  'waiting_seconds': waiting_length(queue_closed, active) if queue_complete else None,
                  'observed_waiting_seconds': waiting_length(queue_closed, active) if queue_closed else None,
                  'status': 'complete' if queue_complete else 'partial' if queue_intervals else 'unknown',
                  'basis': 'Explicit queue admission/pause/outage intervals; open intervals remain unbounded.'},
              'timing': {'active_seconds': union_length(active) if active else None,
                         'waiting_seconds': waiting_length(waiting, active) if waiting else None,
                         'observed_span_seconds': span,
                         'unattributed_seconds': max(0., span - union_length(active + waiting)) if span is not None else None,
                         'basis': 'First recorded step start to last recorded terminal; gaps are unattributed, not assumed waiting. Not a claim that the whole OCR workflow is complete.',
                         'tool_time_is_nested': True},
              'per_page': {'page_count': page_count, 'usd': cost['usd'] / page_count
                           if type(page_count) is int and page_count > 0 and cost['usd'] is not None else None,
                           'reason': None if type(page_count) is int and page_count > 0 else 'No verified page count is available.'},
              'price_card': card, 'price_card_sha256': digest(card),
              'assumptions': ['Only original app-server tokenUsage.total observations are accounted.',
                              'Never sum last snapshots; duplicate cumulative snapshots contribute once.',
                              'Resumed, unmapped, decreasing or compacted epochs remain incomplete.',
                              'Local OCR/cache artifacts and response length are not AI token usage.'],
              'artifacts': {'ledger': str((directory / 'ledger.json').relative_to(root)),
                            'price_card': str(card_path.relative_to(root))}}
    atomic_json(directory / 'ledger.json', result)
    return result


def summary(ledger, offset=0, limit=100, *, kind=None, phase=None, newest_first=False):
    """Keep the GUI overview small; original messages belong in step detail."""
    result = {k: v for k, v in ledger.items() if k != 'steps'}
    result['steps'] = []
    steps = [step for step in ledger['steps'] if (kind is None or step['kind'] == kind) and
             (phase is None or step.get('phase') == phase)]
    if newest_first:
        steps.reverse()
    result.update(step_total=len(steps),
                  step_next_offset=offset + limit if offset + limit < len(steps) else None,
                  running_steps=[{key: step.get(key) for key in ('step_id', 'operation', 'tool', 'scope', 'parent_step_id')}
                                 for step in steps if step['state'] in ('running', 'starting')])
    for step in steps[offset:offset + limit]:
        result['steps'].append({k: v for k, v in step.items() if k not in ('attempt', 'events', 'usage_sources')})
        result['steps'][-1]['usage_sources'] = [{k: v for k, v in source.items() if k != 'original'}
                                               for source in step['usage_sources'][-5:]]
        result['steps'][-1]['usage_source_total'] = len(step['usage_sources'])
    return result


def step_detail(ledger, step, offset=0, limit=100):
    value = deepcopy(step)
    value['usage_source_total'] = len(step['usage_sources'])
    value['usage_sources'] = step['usage_sources'][offset:offset + limit]
    value['usage_next_offset'] = offset + limit if offset + limit < len(step['usage_sources']) else None
    events = step.get('events', [])
    value['event_total'] = len(events)
    value['events'] = events[offset:offset + limit]
    value['event_next_offset'] = offset + limit if offset + limit < len(events) else None
    # Complete originals remain in the hashed attempt/request/protocol artifacts.
    for key in ('usage_events', 'events', 'tool_events'):
        value.get('attempt', {}).pop(key, None)
    for key in ('prompt', 'answer'):
        content = value.get('attempt', {}).get(key)
        if isinstance(content, str) and len(content) > 32768:
            value['attempt'][key] = content[:32768]
            value['attempt'][key + '_truncated'] = True
            value['attempt'][key + '_characters'] = len(content)
    value.update(price_card=ledger['price_card'], policy=ledger['policy'])
    return value
