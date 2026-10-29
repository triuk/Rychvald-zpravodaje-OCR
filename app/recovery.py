"""Read-only reconciliation of original provider submissions.

An outgoing request is intent, never proof of delivery or rejection. Original
protocol and attempts are immutable; every inspection has its own trace.
"""
import json
import os
from pathlib import Path

from .codex import RpcProcess, now, scrub
from .jobs import JobError, atomic_json, sha
from .original_protocol import read_original_protocol
from tools.ocr_correction_graph import output_child


NAMESPACES = {'model_diagnostic': 'codex-attempts', 'context_diagnostic': 'context-attempts',
    'reading': 'reading-attempts', 'geometry': 'geometry-attempts', 'output_review': 'output-review-attempts',
    'corrections': 'correction-attempts'}


def original_stages(work, parent):
    """Traverse the exact P/I/C/K/O graph, never a latest-child namespace walk."""
    stages = list(parent['stages'])
    for row in parent['stages']:
        if row['stage'] != 'corrections' or row['state'] == 'completed':
            continue
        if not row.get('attempt_id'):
            binding = {'parent_attempt_id': parent['attempt_id'], 'intent_id': row['intent_id'], 'stage': 'corrections'}
            matches = [json.loads(path.read_text()) for path in (work / 'application/correction-attempts').glob('*/attempt.json')
                if json.loads(path.read_text()).get('parent_binding') == binding]
            if len(matches) > 1:
                raise JobError('attempt_conflict', 'Multiple correction children claim the original parent intent.')
            if not matches:
                continue
            row['attempt_id'] = matches[0]['attempt_id']
        correction = json.loads((work / 'application/correction-attempts' / row['attempt_id'] / 'attempt.json').read_text())
        ledger = json.loads((work / 'application/corrections/ledger.json').read_text())
        cycle = ledger['cycles'][-1]
        try:
            intent, child = output_child(work, correction, cycle['cycle_id'])
        except ValueError as error:
            raise JobError('attempt_conflict', str(error)) from error
        if child is not None and not any(item.get('attempt_id') == child['attempt_id'] and item['stage'] == 'output_review' for item in stages):
            stages.append({'stage': 'output_review', 'attempt_id': child['attempt_id'],
                'state': 'completed' if child['state'] == 'completed' and child.get('output_review_complete') else 'interrupted',
                'child_status_operation': 'output_review_status', 'expected_parent_binding': intent['binding']})
    return stages


def inspect_original(app, work, parent, destination):
    destination.mkdir(parents=True, exist_ok=True)
    observations, originals = [], {}
    scoped = {**parent, 'stages': original_stages(work, parent)}
    for stage in scoped['stages']:
        namespace = NAMESPACES.get(stage['stage'])
        if namespace is None or stage['state'] == 'completed':
            continue
        if not stage.get('attempt_id'):
            matches = []
            for candidate in (work / 'application' / namespace).glob('*/attempt.json'):
                saved = json.loads(candidate.read_text())
                expected = {'parent_attempt_id': parent['attempt_id'], 'intent_id': stage.get('intent_id'), 'stage': stage['stage']}
                if saved.get('parent_binding') == expected:
                    matches.append(saved['attempt_id'])
            if len(matches) > 1:
                raise JobError('attempt_conflict', 'Multiple children claim the same durable stage intent.')
            if not matches:
                continue  # Child manifest is published before its process can start.
            stage['attempt_id'] = matches[0]
        if not isinstance(stage['attempt_id'], str) or len(stage['attempt_id']) != 32 or any(c not in '0123456789abcdef' for c in stage['attempt_id']):
            raise JobError('attempt_invalid', 'Saved child identity is invalid.')
        path = work / 'application' / namespace / stage['attempt_id'] / 'attempt.json'
        attempt = json.loads(path.read_text())
        if attempt['run_id'] != parent['run_id'] or attempt['root'] != str(app.root):
            raise JobError('attempt_invalid', 'Original AI attempt belongs to another run.')
        expected_binding = stage.get('expected_parent_binding')
        if expected_binding is not None and attempt.get('parent_binding') != expected_binding:
            raise JobError('attempt_conflict', 'Original descendant belongs to another parent/cycle/intent.')
        original = app.root / attempt['artifacts']['protocol']
        if not original.resolve().is_relative_to(work.resolve()):
            raise JobError('attempt_invalid', 'Original AI protocol escaped the run workspace.')
        originals[str(path.relative_to(app.root))] = sha(path)
        parsed = None
        if original.exists():
            originals[str(original.relative_to(app.root))] = sha(original)
            parsed = read_original_protocol(original)
        if parsed is not None and parsed.malformed:
            observations.append({'attempt_id': attempt['attempt_id'], 'state': 'unknown', 'reason': 'incomplete_original_protocol'})
        submitted = parsed.submissions if parsed is not None else []
        for index, submission in enumerate(submitted):
            record = {'attempt_id': attempt['attempt_id'], 'stage': stage['stage'],
                'connection_id': submission['connection_id'], 'thread_id': submission['thread_id'],
                'turn_id': submission['turn_id'], 'state': 'unknown', 'visual_stage': submission['visual_stage']}
            if submission['delivery_state'] == 'rejected':
                record.update(state='rejected', error=submission['original_error'])
            if record['state'] == 'rejected' or record['turn_id'] is None:
                observations.append(record)
                continue
            # Only a correlated request ACK and same stage/connection/thread/
            # turn terminal establish original native completion. A foreign
            # started notification cannot substitute for a lost ACK.
            if stage['stage'] in ('corrections', 'output_review') and submission['delivery_state'] == 'completed':
                record.update(state='completed', inspection='original_native_terminal')
                observations.append(record)
                continue
            directory = destination / (attempt['attempt_id'] + '-' + str(index))
            directory.mkdir()

            def trace(direction, message):
                with (directory / 'protocol.jsonl').open('a') as stream:
                    stream.write(json.dumps({'timestamp': now(), 'direction': direction, 'message': scrub(message)}) + '\n')
                    stream.flush()
                    os.fsync(stream.fileno())

            def notify(message):
                if 'id' in message:
                    raise JobError('recovery_tool_forbidden', 'Read-only reconciliation cannot execute tools or approvals.')

            rpc = None
            try:
                with (directory / 'stderr.log').open('w') as stderr:
                    workspace = Path(attempt.get('context_paths', {}).get('workspace', path.parent / 'workspace'))
                    rpc = RpcProcess(app.codex.runtime['command'], workspace if workspace.is_dir() else directory,
                        stderr, trace, lambda: False)
                    rpc.request('initialize', {'clientInfo': {'name': 'rychvald-recovery', 'version': '1'},
                        'capabilities': {'experimentalApi': True}}, notify, timeout=10)
                    rpc.send({'method': 'initialized'})
                    result = rpc.request('thread/read', {'threadId': record['thread_id'], 'includeTurns': True}, notify, timeout=10)
                    atomic_json(directory / 'thread-read.json', result)
                    if result['thread']['id'] != record['thread_id']:
                        raise JobError('codex_identity_mismatch', 'Provider returned another original thread.')
                    turn = next((row for row in result['thread']['turns'] if row['id'] == record['turn_id']), None)
                    if turn is None:
                        raise JobError('original_turn_unavailable', 'Original submitted turn is unavailable.')
                    record.update(state=turn['status'], error=turn.get('error'), inspection=str(directory.relative_to(app.root)))
            except Exception as error:
                record.update(state='unknown', reason=getattr(error, 'code', 'original_turn_unavailable'), message=str(error))
            finally:
                if rpc is not None:
                    rpc.close()
            observations.append(record)
    states = [row['state'] for row in observations]
    unresolved = any(state not in ('completed', 'interrupted', 'failed', 'rejected') for state in states)
    proof = {'state': 'unknown' if unresolved else 'reconciled' if observations else 'not_submitted',
        'turns': observations, 'originals': originals, 'safe_to_continue': not unresolved}
    if not unresolved:
        try:
            verify_completed_reuse(app, work, scoped, proof, local_recovery_routes(work, scoped))
        except JobError as error:
            proof.update(safe_to_continue=False, continuation_error={'code': error.code, 'message': str(error)})
    return proof


def unchanged_originals(root, proof):
    return all((root / path).is_file() and sha(root / path) == digest for path, digest in proof['originals'].items())


def verify_completed_reuse(app, work, parent, provider, routes):
    """A known provider completion permits reuse, never a replacement submission."""
    parent = {**parent, 'stages': original_stages(work, parent)}
    recoverable = {route['attempt_id'] for route in routes}
    flags = {'model_diagnostic': 'combination_verified', 'context_diagnostic': 'context_verified',
        'reading': 'reading_complete', 'geometry': 'geometry_complete', 'output_review': 'output_review_complete'}
    for record in provider['turns']:
        if record['state'] != 'completed':
            continue
        identifier, stage = record['attempt_id'], record['stage']
        if identifier in recoverable:
            continue  # recover_local validates the original result before any worker starts.
        entry = next(row for row in parent['stages'] if row.get('attempt_id') == identifier)
        operation = entry.get('child_status_operation')
        if operation and stage in flags:
            status = app.dispatch(operation, {'run_id': parent['run_id']})
            if (status['ok'] and status['data'].get('attempt_id') == identifier and
                    status['data']['state'] == 'completed' and status['data'].get(flags[stage])):
                continue
        path = work / 'application' / NAMESPACES[stage] / identifier / 'attempt.json'
        attempt = json.loads(path.read_text())
        turns = attempt.get('turns', [])
        saved = next((turn for turn in turns if turn.get('thread_id') == record['thread_id'] and
            turn.get('turn_id') == record['turn_id'] and turn.get('state') == 'completed' and turn.get('answer') and
            (not record.get('visual_stage') or turn.get('stage') == record['visual_stage']) and
            (turn.get('connection_id') is None or turn['connection_id'] == record['connection_id'])), None)
        protocol = app.root / attempt['artifacts']['protocol']
        completed_frame = any(row['direction'] == 'server' and row['message'].get('method') == 'turn/completed' and
            row['message']['params'].get('threadId') == record['thread_id'] and
            row['message']['params']['turn'].get('id') == record['turn_id'] and
            row['message']['params']['turn'].get('status') == 'completed' and
            str(row.get('connection_id', '0')) == record['connection_id']
            for row in (json.loads(raw) for raw in protocol.read_text().splitlines()))
        if stage == 'corrections' and completed_frame and not saved:
            from .visual_recovery import original_correction_phase
            original_correction_phase(work, attempt, record)
            continue
        if (stage == 'output_review' and completed_frame and
                (attempt.get('parent_binding') or {}).get('correction_attempt_id')):
            binding = attempt['parent_binding']
            app.process.request(app.root, 'verify-output-preparation', parent['run_id'], '--sha256', binding['preparation_sha256'])
            from .visual_recovery import original_output_phase
            original_output_phase(work, attempt, record)
            continue
        if saved and completed_frame:
            if stage == 'corrections':
                continue  # Phase-aware native verification runs before continuation.
            if stage == 'reading' and saved is turns[0] and saved['stage'] == 'source':
                continue  # Reading resumes the original thread with only the accounting turn.
            if stage == 'context_diagnostic' and any(turn['stage'] == 'routing' and
                    turn.get('state') == 'completed' and turn.get('answer') for turn in turns):
                continue  # Context continuation explicitly reuses completed routing/recovery.
            if stage == 'geometry' and saved['stage'] == 'source_expectations' and all(
                    (work / name).is_file() for name in ('geometry-source-samples.json', 'geometry-sample-origin.json')):
                continue  # Native verification checks the frozen samples before another examination.
        raise JobError('original_result_unavailable',
            'The original provider turn completed, but its local result cannot be safely reused; no replacement turn was submitted.')


def local_recovery_routes(work, parent):
    routes = []
    for stage in original_stages(work, parent):
        namespace = NAMESPACES.get(stage['stage'])
        if not namespace or not stage.get('attempt_id') or stage['state'] == 'completed':
            continue
        path = work / 'application' / namespace / stage['attempt_id'] / 'attempt.json'
        value = json.loads(path.read_text())
        if value['state'] == 'completed':
            continue
        turns = value.get('turns', [])
        if stage['stage'] == 'model_diagnostic' and value.get('terminal_turn', {}).get('status') == 'completed':
            routes.append({'stage': stage['stage'], 'attempt_id': stage['attempt_id']})
        elif stage['stage'] == 'reading' and len(turns) == 2 and all(row.get('state') == 'completed' for row in turns):
            routes.append({'stage': stage['stage'], 'attempt_id': stage['attempt_id']})
        elif stage['stage'] == 'geometry' and turns and turns[-1]['stage'] == 'geometry_examination' and turns[-1]['state'] == 'completed':
            routes.append({'stage': stage['stage'], 'attempt_id': stage['attempt_id']})
        elif stage['stage'] == 'output_review' and turns and turns[-1]['stage'] == 'output_examination' and turns[-1]['state'] == 'completed':
            routes.append({'stage': stage['stage'], 'attempt_id': stage['attempt_id']})
    return routes


def recover_local(app, work, run_id, route):
    """Publish/revalidate a completed original result without another model turn."""
    stage, identifier = route['stage'], route['attempt_id']
    directory = work / 'application' / NAMESPACES[stage] / identifier
    path = directory / 'attempt.json'
    value = json.loads(path.read_text())
    if stage == 'geometry':
        app.geometry.recover(app.root, app.select_run(run_id), identifier)
        return
    result = {'state': 'completed', 'error': None, 'original_attempt_state': value['state']}
    if stage == 'model_diagnostic':
        from tools.ocr_profiles import effective_ai_settings
        requested = effective_ai_settings(app.select_run(run_id)['run']['profile'], 'vision_diagnostic')
        if (value.get('effective', {}).get('model') != requested['model'] or
                value.get('effective', {}).get('reasoning_effort') != requested['reasoning_effort'] or value.get('reroutes') or
                value.get('tool_events') or not value.get('answer')):
            raise JobError('local_recovery_invalid', 'Original completed diagnostic did not verify the requested combination.')
        frames = [json.loads(raw)['message'] for raw in (app.root / value['artifacts']['protocol']).read_text().splitlines()]
        if not any(message.get('method') == 'turn/completed' and
                message['params']['turn'].get('id') == value['turn_id'] and message['params']['turn']['status'] == 'completed'
                for message in frames):
            raise JobError('local_recovery_invalid', 'Original diagnostic completion is missing.')
        result['combination_verified'] = True
    elif stage == 'reading':
        from .reading import verify_trace
        proposal = verify_trace(value, value['source'], app.root / value['artifacts']['protocol'])
        proposal_path = directory / 'local-recovered-proposal.json'
        atomic_json(proposal_path, proposal)
        app.process.request(app.root, 'publish-reading', run_id, '--proposal', proposal_path)
        result.update(reading_complete=True, proposal_sha256=sha(proposal_path),
            coverage=proposal['coverage'], review_sha256=sha(work / 'review.json'),
            artifacts={**value['artifacts'], 'proposal': str(proposal_path.relative_to(app.root))})
    else:
        publication_path = directory / 'publication-proposal.json'
        # This transaction revalidates original protocol, pixels, runtime and
        # native output binding before any saved result can become completed.
        app.process.request(app.root, 'publish-output-review', run_id, '--proposal', publication_path)
        result.update(output_review_complete=True, publication_sha256=sha(work / 'output-review-publication.json'),
            artifacts={**value['artifacts'], 'publication': str((work / 'output-review-publication.json').relative_to(app.root))})
    evidence = {value['artifacts']['protocol']: sha(app.root / value['artifacts']['protocol'])}
    atomic_json(directory / 'local-recovery.json', {'original_sha256': sha(path), 'evidence': evidence,
        'result': result, 'new_ai_turns': 0, 'created_at': now()})
