"""Read views over two independent named runs of one complete source hash."""
from .metrics import collect, summary


def compare(application, payload):
    from .service import ApplicationError
    left, right = payload.get('left_run_id'), payload.get('right_run_id')
    if left == right:
        raise ApplicationError('invalid_comparison', 'Choose two different named OCR runs.')
    offset, limit = payload.get('offset', 0), payload.get('limit', 100)
    history_offset = payload.get('history_offset', 0)
    if (type(offset) is not int or offset < 0 or type(history_offset) is not int or history_offset < 0 or
            type(limit) is not int or not 1 <= limit <= 200):
        raise ApplicationError('invalid_request', 'Comparison pages require nonnegative offsets and limit 1..200.')
    runs = [application.select_run(identifier, notify=False) for identifier in (left, right)]
    if any(not run.get('run') for run in runs) or runs[0]['edition_id'] != runs[1]['edition_id']:
        raise ApplicationError('invalid_comparison', 'Comparison requires two named runs of the same full source hash.')
    result = []
    for run in runs:
        try:
            ledger = collect(application.root, run)
            profile_path = application.root / run['artifacts']['profile_snapshot']['path']
            origins = {key: 0 for key in ('computed', 'same_run_cache', 'imported_local')}
            for event in run['history']:
                if event.get('type') in ('unit_cached', 'unit_completed'):
                    origin = event.get('origin', 'same_run_cache' if event['type'] == 'unit_cached' else 'computed')
                    origins[origin] = origins.get(origin, 0) + 1
            ai = [s for s in ledger['steps'] if s['kind'] == 'ai']
            history = run['history']
            output = application.output_results({'run_id': run['project']['run_id']}, run=run)
            result.append({'project': run['project'], 'run': run['run'],
                'profile': {'sha256': run['run']['profile_sha256'], 'text': profile_path.read_text(encoding='utf-8')},
                'metrics': summary(ledger, offset, limit), 'local_origins': origins,
                'milestones': {'phase': run['project']['phase'], 'validation': run['project']['validation'],
                    'acceptance': run['project']['acceptance']}, 'output': output,
                'ai_context': {'workspace': str(application.root / run['artifacts']['workspace']['path']),
                    'thread_ids': sorted({s['thread_id'] for s in ai if s.get('thread_id')}),
                    'attempt_ids': [s['attempt_id'] for s in ai],
                    'context_paths': [s['attempt']['context_paths'] for s in ai if s['attempt'].get('context_paths')],
                    'meaning': 'Observed run-local attempts/threads; local preparation import transfers no AI context.'},
                'history': history[history_offset:history_offset + limit], 'history_total': len(history),
                'history_next_offset': history_offset + limit if history_offset + limit < len(history) else None})
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ApplicationError('comparison_artifact_invalid', f'Cannot read comparison artifacts: {error}') from None
    shared = sorted(set(result[0]['ai_context']['thread_ids']) & set(result[1]['ai_context']['thread_ids']))
    return {'edition_id': runs[0]['edition_id'], 'runs': result,
        'categories': ledger['categories'], 'cost_scale': ledger['cost_scale'],
        'price_cards_equal': result[0]['metrics']['price_card_sha256'] == result[1]['metrics']['price_card_sha256'],
        'shared_ai_threads': shared,
        'independence': ('shared_thread_detected' if shared else
            'no_shared_observed_threads' if all(r['ai_context']['thread_ids'] for r in result) else 'not_observed'),
        'disclosures': ['Local imported units, same-run cache and computed work are separate from provider cached input tokens.',
            'Prices use each run\'s frozen reference card, not ChatGPT subscription billing.',
            'No shared observed threads is not evidence of completed independent AI runs when AI observations are absent.']}
