"""Source-first visual reading; candidates remain unpublished until validation."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import threading
import time

from .context import ContextJobs
from .codex import MODEL, EFFORT, RpcProcess, now, process_identity, scrub
from .context_runtime import verify_resources, configuration, command, verify_hooks
from .jobs import JobError, atomic_json, sha
from .reading_contract import SOURCE_INSTRUCTIONS, ACCOUNTING_INSTRUCTIONS, SOURCE_SCHEMA, PROPOSAL_SCHEMA, TOOLS


def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def verify_source(packet, answer):
    if answer['read_pages'] != [p['page'] for p in packet['pages']]:
        raise JobError('reading_source_incomplete', 'The original source answer did not read every original page.')
    review = answer['review']
    if review['source_sha256'] != packet['source_sha256'] or review['dropped_candidates']:
        raise JobError('reading_source_invalid', 'Source-only answer contains foreign source or candidate accounting.')
    lines = review['lines']
    if len({line['id'] for line in lines}) != len(lines) or any(line.get('candidate_id') is not None for line in lines):
        raise JobError('reading_source_invalid', 'Source-only line inventory is not independent of OCR candidates.')


def verify_proposal(packet, source, source_turn, proposal, tools):
    coverage = proposal['coverage']
    if coverage['source_turn_id'] != source_turn['turn_id'] or coverage['source_answer_sha256'] != text_hash(source_turn['answer']):
        raise JobError('reading_evidence_mismatch', 'Proposal does not cite the exact completed original source answer.')
    source_lines = {line['id']: line for line in source['review']['lines']}
    final_lines = {line['id']: line for line in proposal['review']['lines']}
    if not set(source_lines) <= set(final_lines):
        raise JobError('reading_source_omitted', 'Final proposal omits source-read lines.')
    reread = {call['arguments']['page'] for call in tools if call['tool'] == 'ocr_image' and call['success']}
    for key, line in final_lines.items():
        original = source_lines.get(key)
        if original is None or any(line.get(k) != original.get(k) for k in
            ['page', 'text', 'text_status', 'selection_region', 'source_crop']):
            if line['page'] not in reread:
                raise JobError('reading_revision_unverified', 'A source change needs an actual original-image reread.')
    if not any(c['tool'] == 'ocr_query' and c['arguments'].get('view') == 'candidates' and c['success'] for c in tools):
        raise JobError('reading_tools_unverified', 'Candidate accounting requires actual successful native candidate queries.')
    if not any(c['tool'] == 'ocr_validate' and c['success'] and c['arguments']['proposal'] == proposal for c in tools):
        raise JobError('reading_validation_missing', 'The exact final model-authored proposal was not successfully validated.')


def verify_trace(value, packet, protocol):
    """Re-derive publication evidence from original JSON-RPC, not saved flags."""
    frames = [json.loads(line)['message'] for line in protocol.read_text().splitlines()]
    requests = [m['params'] for m in frames if m.get('method') == 'turn/start']
    terminals = {m['params']['turn']['id']: m['params']['turn'] for m in frames if m.get('method') == 'turn/completed'}
    if len(requests) != 2 or len(value['turns']) != 2 or value['reroutes']:
        raise JobError('reading_evidence_mismatch', 'Exactly two original non-rerouted reading turns are required.')
    for record in value['turns']:
        terminal = terminals.get(record['turn_id'])
        messages = [m['params']['item'] for m in frames if m.get('method') == 'item/completed' and
            m['params'].get('turnId') == record['turn_id'] and m['params']['item'].get('type') == 'agentMessage' and
            m['params']['item'].get('phase') == 'final_answer']
        if not terminal or terminal['status'] != 'completed' or not messages or messages[-1]['text'] != record['answer']:
            raise JobError('reading_evidence_mismatch', 'Original completed final assistant JSON differs from preserved reading evidence.')
    thread_results = [m['result'] for m in frames if isinstance(m.get('result'), dict) and
        isinstance(m['result'].get('thread'), dict) and m['result']['thread'].get('id') == value['thread_id']]
    if not thread_results or thread_results[-1].get('model') != MODEL or thread_results[-1].get('reasoningEffort') != EFFORT:
        raise JobError('model_configuration_mismatch', 'Original thread response did not confirm the requested model/high.')
    images = [item['path'] for item in requests[0]['input'] if item['type'] == 'localImage']
    if images != [page['path'] for page in packet['pages']] or any(sha(Path(p['path'])) != p['sha256'] for p in packet['pages']):
        raise JobError('reading_source_changed', 'Every original source raster must be attached unchanged to the first turn.')
    if any(request.get('model') != MODEL or request.get('effort') != EFFORT for request in requests):
        raise JobError('model_configuration_mismatch', 'Original reading requests did not use the exact model/high combination.')
    source = json.loads(value['turns'][0]['answer'])
    proposal = json.loads(value['turns'][1]['answer'])
    verify_source(packet, source)
    replies = {m['id']: m['result'] for m in frames if 'id' in m and 'method' not in m and 'result' in m}
    calls = []
    source_id, accounting_id = [turn['turn_id'] for turn in value['turns']]
    for frame in frames:
        if frame.get('method') != 'item/tool/call':
            continue
        params = frame['params']
        if params['threadId'] != value['thread_id'] or params['turnId'] not in (source_id, accounting_id):
            raise JobError('reading_evidence_mismatch', 'A dynamic tool belongs to another reading thread/turn.')
        reply = replies.get(frame['id'], {})
        if params['turnId'] == source_id and params['tool'] != 'ocr_image':
            raise JobError('reading_source_tool_forbidden', 'The independent source turn requested a candidate or mutation tool.')
        if params['turnId'] == accounting_id:
            calls.append({'tool': params['tool'], 'arguments': params['arguments'], 'success': reply.get('success') is True})
        if params['tool'] == 'ocr_image' and reply.get('success') is True:
            page = packet['pages'][params['arguments']['page'] - 1]
            expected = 'data:image/png;base64,' + base64.b64encode(Path(page['path']).read_bytes()).decode()
            images = [item.get('imageUrl') for item in reply['contentItems'] if item['type'] == 'inputImage']
            if images != [expected]:
                raise JobError('reading_source_changed', 'Original-image tool response differs from the attached source raster.')
    source_items = [m['params']['item'] for m in frames if m.get('method') == 'item/completed' and m['params'].get('turnId') == source_id]
    if any(item.get('type') in ('commandExecution', 'fileChange') or
            item.get('type') == 'mcpToolCall' and item.get('tool') != 'ctx_stats' for item in source_items):
        raise JobError('reading_source_tool_forbidden', 'The original source turn inspected non-image content.')
    verify_proposal(packet, source, value['turns'][0], proposal, calls)
    hooks = [m['params']['run'] for m in frames if m.get('method') == 'hook/completed']
    completed = {hook['eventName'] for hook in hooks if hook.get('status') == 'completed' and hook.get('source') == 'sessionFlags'}
    if not {'sessionStart', 'userPromptSubmit', 'postToolUse', 'stop'} <= completed:
        raise JobError('reading_tools_unverified', 'The applicable trusted context hooks were not observed during reading.')
    statistics = [m for m in frames if m.get('method') == 'item/completed' and
        m['params']['item'].get('type') == 'mcpToolCall' and m['params']['item'].get('server') == 'context_mode' and
        m['params']['item'].get('tool') == 'ctx_stats' and m['params']['item'].get('status') == 'completed' and
        not m['params']['item'].get('error')]
    if not statistics:
        raise JobError('reading_tools_unverified', 'No actual successful run-local context-mode tool was observed.')
    return proposal


class ReadingJobs(ContextJobs):
    namespace = 'reading-attempts'
    step_id = 'visual_reading'

    def __init__(self, publish, runtime=None, context_runtime=None, process=None):
        super().__init__(publish, runtime, context_runtime)
        self.process = process

    def _run(self, job):
        value = job['manifest']
        started = time.monotonic()
        trace_lock = threading.Lock()
        value.update(reading_complete=False, turns=[], completed_items=[], terminal_turns={}, hook_events=[],
                     dynamic_tools=[], connections=[], context_runtime=copy.deepcopy(self.context_runtime),
                     counts={'pages_read': 0, 'lines_read': 0, 'units_read': 0})
        work = job['directory'].parents[2]
        root = Path(value['root'])
        workspace, storage = work / 'context/workspace', work / 'context/store'
        phase = 'source'

        def trace(direction, message):
            with trace_lock, (job['directory'] / 'protocol.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'timestamp': now(), 'elapsed_seconds': time.monotonic() - started,
                    'connection_id': str(len(value['connections']) - 1), 'direction': direction,
                    'message': scrub(message)}, ensure_ascii=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())

        def notify(message):
            params = message.get('params', {})
            thread = params.get('threadId') or params.get('thread', {}).get('id')
            if thread is not None and value['thread_id'] is not None and thread != value['thread_id']:
                raise JobError('codex_identity_mismatch', 'Reading notification belongs to a foreign thread.')
            if 'id' in message:
                if message.get('method') != 'item/tool/call':
                    job['rpc'].send({'id': message['id'], 'error': {'code': -32601, 'message': 'Only declared run-local reading tools are supported.'}})
                    raise JobError('reading_approval_unsupported', 'Unsupported client approval/tool request.')
                response = dynamic(params)
                job['rpc'].send({'id': message['id'], 'result': response})
                return
            method = message.get('method')
            if method is None:
                raise JobError('codex_protocol_invalid', 'Unmatched reading protocol response.')
            if method in ('hook/started', 'hook/completed'):
                value['hook_events'].append(copy.deepcopy(message))
            elif method == 'thread/tokenUsage/updated':
                value['usage_events'].append(copy.deepcopy(params))
            elif method == 'model/rerouted':
                value['reroutes'].append(copy.deepcopy(params))
            elif method == 'turn/completed':
                value['terminal_turns'][params['turn']['id']] = copy.deepcopy(params['turn'])
            elif method == 'item/completed':
                item = params['item']
                if phase == 'source' and (item.get('type') in ('commandExecution', 'fileChange') or
                    item.get('type') == 'mcpToolCall' and item.get('tool') != 'ctx_stats'):
                    raise JobError('reading_source_tool_forbidden', 'Source-first reading may use only original images and context statistics.')
                value['completed_items'].append(copy.deepcopy(params))

        def dynamic(params):
            tool, args = params['tool'], params['arguments']
            call = {'tool': tool, 'arguments': copy.deepcopy(args), 'phase': phase, 'turn_id': params['turnId'], 'success': False}
            try:
                if tool == 'ocr_image':
                    number = args['page']
                    if type(number) is not int or not 1 <= number <= len(packet['pages']):
                        raise JobError('invalid_selection', 'Choose an original source page.')
                    page = packet['pages'][number - 1]
                    path = Path(page['path'])
                    if sha(path) != page['sha256']:
                        raise JobError('reading_source_changed', 'Original source raster changed.')
                    content = [{'type': 'inputText', 'text': json.dumps(page)},
                        {'type': 'inputImage', 'imageUrl': 'data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode()}]
                    call['source'] = copy.deepcopy(page)
                elif phase != 'accounting':
                    raise JobError('reading_candidates_unavailable', 'OCR candidates are unavailable during the independent source-first phase.')
                elif tool == 'ocr_query':
                    arguments = ['query', value['run_id'], args.get('view', 'candidates'), '--offset', args.get('offset', 0), '--limit', 8]
                    if args.get('page') is not None:
                        arguments += ['--page', args['page']]
                    result = self.process.request(root, *arguments)
                    content = [{'type': 'inputText', 'text': json.dumps(result, ensure_ascii=False)}]
                elif tool == 'ocr_validate':
                    proposal = args['proposal']
                    path = job['directory'] / ('provisional-' + str(len(value['dynamic_tools'])) + '.json')
                    atomic_json(path, proposal)
                    result = self.process.request(root, 'check-reading', value['run_id'], '--proposal', path)
                    call['artifact'] = {'path': str(path.relative_to(root)), 'sha256': sha(path)}
                    content = [{'type': 'inputText', 'text': json.dumps(result, ensure_ascii=False)}]
                else:
                    raise JobError('reading_tool_unknown', 'Undeclared reading tool.')
                call['success'] = True
            except (KeyError, TypeError, OSError, ValueError, JobError) as error:
                call['error'] = {'code': getattr(error, 'code', 'invalid_selection'), 'message': str(error)}
                content = [{'type': 'inputText', 'text': json.dumps({'error': call['error']})}]
            except Exception as error:
                # The native process client exposes machine errors without allowing
                # a failed validation to terminate the corrective model turn.
                call['error'] = {'code': getattr(error, 'code', 'native_operation_failed'), 'message': str(error)}
                content = [{'type': 'inputText', 'text': json.dumps({'error': call['error']})}]
            value['dynamic_tools'].append(call)
            self._event(job, 'reading_tool_completed', tool=tool, phase=phase, success=call['success'])
            return {'contentItems': content, 'success': call['success']}

        def connect(settings, trust=None):
            stderr = (job['directory'] / 'stderr.log').open('a', encoding='utf-8')
            rpc = RpcProcess(command(self.runtime, settings, trust), workspace, stderr, trace,
                lambda: job['cancel'], env=settings['process_environment'])
            job['rpc'], job['stderr'] = rpc, stderr
            identity = {'connection_id': str(len(value['connections'])), 'pid': rpc.process.pid,
                'process_group': rpc.process.pid, 'process_start_ticks': process_identity(rpc.process.pid)}
            value['connections'].append(identity)
            value.update(identity, state='running')
            self._event(job, 'reading_process_started', **identity)
            rpc.request('initialize', {'clientInfo': {'name': 'rychvald-reading', 'version': '1.0'},
                'capabilities': {'experimentalApi': True}}, notify)
            rpc.send({'method': 'initialized'})
            return rpc

        def disconnect():
            if job['rpc'] is not None:
                job['rpc'].close()
                value['connections'][-1]['returncode'] = job['rpc'].process.returncode
                job['rpc'] = None
                job['stderr'].close()

        def turn(stage, prompt, schema, images=None):
            inputs = [{'type': 'text', 'text': prompt}]
            inputs += [{'type': 'localImage', 'path': page['path']} for page in images or []]
            params = {'threadId': value['thread_id'], 'model': MODEL, 'effort': EFFORT,
                'input': inputs, 'outputSchema': schema}
            value.setdefault('application_requests', []).append({'stage': stage, 'params': params})
            atomic_json(job['directory'] / 'request.json', {'requests': value['application_requests'],
                'profile_sha256': value['profile_sha256'], 'source': packet})
            result = rpc.request('turn/start', params, notify)
            identifier = result['turn']['id']
            value['turn_id'] = identifier
            record = {'stage': stage, 'thread_id': value['thread_id'], 'turn_id': identifier, 'state': 'running', 'prompt': prompt}
            value['turns'].append(record)
            self._event(job, 'reading_turn_submitted', stage=stage, thread_id=value['thread_id'], turn_id=identifier)
            deadline = time.monotonic() + 480
            while identifier not in value['terminal_turns']:
                notify(rpc.receive(deadline))
            terminal = value['terminal_turns'][identifier]
            record['state'] = terminal['status']
            if terminal['status'] != 'completed':
                raise JobError('codex_turn_' + terminal['status'], str(terminal.get('error') or terminal['status']))
            if value['reroutes']:
                raise JobError('model_rerouted', 'Reading was redirected away from the exact requested model.')
            messages = [entry['item'] for entry in value['completed_items'] if entry.get('turnId') == identifier and
                entry['item'].get('type') == 'agentMessage' and entry['item'].get('phase') == 'final_answer']
            if not messages:
                raise JobError('reading_answer_missing', 'No original final assistant JSON was returned.')
            record['answer'] = messages[-1]['text']
            value['answer'] = record['answer']
            (job['directory'] / (stage + '-answer.txt')).write_text(record['answer'], encoding='utf-8')
            self._event(job, 'reading_turn_completed', stage=stage, thread_id=value['thread_id'], turn_id=identifier)
            return record, json.loads(record['answer'])

        try:
            self._event(job, 'reading_attempt_started')
            value['context_capabilities'] = verify_resources(self.context_runtime, self.runtime)
            metadata = job['metadata']
            run = metadata['run']
            profile = run['run']['profile']
            packet = json.loads((work / 'reading-input.json').read_text())
            if packet['profile_sha256'] != value['profile_sha256']:
                raise JobError('reading_profile_changed', 'Prepared reading packet differs from the immutable run profile.')
            value['source'] = copy.deepcopy(packet)
            value['preflight'] = {'model_attempt_id': metadata['model']['attempt_id'],
                'context_attempt_id': metadata['preflight']['attempt_id'], 'profile_sha256': value['profile_sha256']}
            workspace.mkdir(parents=True, exist_ok=True)
            storage.mkdir(parents=True, exist_ok=True)
            # Only source metadata is copied into the model workspace before phase one.
            atomic_json(workspace / 'reading-packet.json', packet)
            instructions = SOURCE_INSTRUCTIONS + '\n' + profile['prompts']['read'] + '\n'
            (workspace / 'AGENTS.md').write_text(instructions, encoding='utf-8')
            settings = configuration(self.context_runtime, self.runtime, workspace, storage)
            (storage / 'config/AGENTS.md').write_text(instructions, encoding='utf-8')
            value['context_paths'] = {'workspace': str(workspace), 'storage': str(storage)}
            value['effective_context_config'] = {key: settings[key] for key in ['hooks', 'mcp_servers', 'context_environment']}
            rpc = connect(settings)
            untrusted = rpc.request('hooks/list', {'cwds': [str(workspace)]}, notify)
            trust = verify_hooks(untrusted, settings)
            value['hook_review'] = untrusted
            disconnect()
            rpc = connect(settings, trust)
            value['trusted_hooks'] = rpc.request('hooks/list', {'cwds': [str(workspace)]}, notify)
            verify_hooks(value['trusted_hooks'], settings, trusted=True, expected=trust)
            account = rpc.request('account/read', {'refreshToken': False}, notify)
            value['authenticated'] = bool(account.get('account') and account['account'].get('type') == 'chatgpt')
            if not value['authenticated']:
                raise JobError('chatgpt_account_required', 'A supported ChatGPT account is required.')
            cursor, found, cursors = None, None, set()
            while True:
                catalog = rpc.request('model/list', {'cursor': cursor, 'limit': 100}, notify)
                found = next((item for item in catalog['data'] if item.get('model') == MODEL), found)
                cursor = catalog.get('nextCursor')
                if cursor is None:
                    break
                if cursor in cursors:
                    raise JobError('codex_protocol_invalid', 'Model catalog cursor did not advance.')
                cursors.add(cursor)
            if found is None or 'image' not in found.get('inputModalities', []) or not any(
                    effort.get('reasoningEffort') == EFFORT for effort in found.get('supportedReasoningEfforts', [])):
                raise JobError('model_capability_unavailable', 'The exact model/high/image combination is unavailable.')
            thread = rpc.request('thread/start', {'model': MODEL, 'cwd': str(workspace),
                'config': {'model_reasoning_effort': EFFORT}, 'approvalPolicy': 'never', 'sandbox': 'workspace-write',
                'runtimeWorkspaceRoots': [str(workspace), str(storage)], 'dynamicTools': TOOLS,
                'developerInstructions': instructions}, notify)
            value['thread_id'] = thread['thread']['id']
            value['effective'] = {'model': thread.get('model'), 'reasoning_effort': thread.get('reasoningEffort'), 'source': 'thread/start'}
            if thread.get('model') != MODEL or thread.get('reasoningEffort') != EFFORT:
                raise JobError('model_configuration_mismatch', 'Reading thread did not confirm the exact requested model/high.')
            source_turn, source = turn('source', instructions + '\nORIGINAL_SOURCE_PACKET\n' + json.dumps(packet), SOURCE_SCHEMA, packet['pages'])
            verify_source(packet, source)
            value['counts'].update(pages_read=len(source['read_pages']), lines_read=len(source['review']['lines']), units_read=len(source['review']['units']))
            phase = 'accounting'
            accounting = {'source_turn_id': source_turn['turn_id'], 'source_answer_sha256': text_hash(source_turn['answer']),
                'source_sha256': packet['source_sha256'], 'expected_review_sha256': packet['expected_review_sha256'], 'pages': packet['pages']}
            # The source phase's restrictive instructions no longer constrain candidate reconciliation.
            (workspace / 'AGENTS.md').write_text(ACCOUNTING_INSTRUCTIONS.split('READING_ACCOUNTING_PACKET')[0], encoding='utf-8')
            final, proposed = turn('accounting', ACCOUNTING_INSTRUCTIONS + json.dumps(accounting), PROPOSAL_SCHEMA)
            proposal = verify_trace(value, packet, job['directory'] / 'protocol.jsonl')
            if proposal != proposed:
                raise JobError('reading_evidence_mismatch', 'Final proposal differs from the original assistant JSON.')
            path = job['directory'] / 'proposal.json'
            atomic_json(path, proposal)
            value['artifacts']['proposal'] = str(path.relative_to(root))
            value['proposal_sha256'] = sha(path)
            # Recheck the exact runtime immediately before the native locked CAS.
            verify_resources(self.context_runtime, self.runtime)
            publication = self.process.request(root, 'publish-reading', value['run_id'], '--proposal', path)
            value.update(state='completed', reading_complete=True, coverage=proposal['coverage'],
                review_sha256=publication['project']['review_sha256'])
        except Exception as error:
            value.update(state='interrupted' if job['cancel'] or getattr(error, 'code', None) == 'codex_turn_interrupted' else 'failed',
                error={'code': getattr(error, 'code', 'reading_protocol_invalid'), 'message': str(error)})
        finally:
            disconnect()
            value.update(ended_at=now(), elapsed_seconds=max(0, time.monotonic() - started))
            try:
                self._event(job, 'reading_attempt_' + value['state'], state=value['state'], error=value['error'])
            finally:
                with self._lock:
                    atomic_json(job['directory'] / 'attempt.json', value)
                    self._active = None
                self.publish('reading_finished', root=value['root'], run_id=value['run_id'], state=value['state'])

    def status(self, root, run_id, work, operation=None):
        value = super(ContextJobs, self).status(root, run_id, work, operation)
        if value.get('reading_complete') and value['state'] == 'completed':
            try:
                packet = json.loads((work / 'reading-input.json').read_text())
                if packet != value['source']:
                    raise JobError('reading_source_changed', 'Source reading input changed after publication.')
                if sha(work / 'local-candidates.json') != packet['candidate_sha256']:
                    raise JobError('reading_source_changed', 'Candidate inventory changed after publication.')
                if sha(Path(packet['source_path'])) != packet['source_sha256']:
                    raise JobError('reading_source_changed', 'Registered source PDF changed after publication.')
                application = work / 'application'
                if (sha(application / 'profile.json') != packet['profile_sha256'] or
                    sha(application / 'run.json') != packet['run_manifest_sha256']):
                    raise JobError('reading_profile_changed', 'Immutable run profile or manifest changed after publication.')
                proposal = verify_trace(value, packet, root / value['artifacts']['protocol'])
                if proposal != json.loads((root / value['artifacts']['proposal']).read_text()):
                    raise JobError('reading_publication_changed', 'Published review or original proposal changed.')
                current = sha(work / 'review.json')
                value['current_review_bound'] = current == value['review_sha256']
                value['current_review_sha256'] = current
                if not value['current_review_bound']:
                    original = work / 'review-history' / (value['review_sha256'] + '.json')
                    if sha(original) != value['review_sha256'] or json.loads(original.read_text()) != proposal['review']:
                        raise JobError('reading_publication_changed', 'Original first-reading review snapshot is missing or changed.')
                    chain = json.loads((work / 'review-patch-chain.json').read_text())
                    reached = value['review_sha256']
                    for step in chain:
                        if step['previous'] == reached:
                            old = work / 'review-history' / (reached + '.json')
                            patch = (work / step['patch']).resolve()
                            if not patch.is_relative_to(work.resolve()) or sha(patch) != step['patch_sha256'] or sha(old) != reached:
                                raise JobError('reading_publication_changed', 'Native review correction history changed.')
                            # Reapply each public native validated correction to its archived input.
                            from tools.ocr_quality import patched_review, apply_line_patch
                            expected = json.loads(old.read_text())
                            if step.get('line_id') is None:
                                expected = patched_review(expected, json.loads(patch.read_text()))
                            else:
                                apply_line_patch(expected, step['line_id'], json.loads(patch.read_text()))
                            target = work / 'review.json' if step['current'] == current else work / 'review-history' / (step['current'] + '.json')
                            if sha(target) != step['current'] or json.loads(target.read_text()) != expected:
                                raise JobError('reading_publication_changed', 'Current review is not the recorded native correction result.')
                            reached = step['current']
                    if reached != current:
                        raise JobError('reading_publication_changed', 'Current review has no validated native correction chain.')
            except (OSError, ValueError, KeyError, TypeError, JobError) as error:
                value.update(state='invalidated', reading_complete=False,
                    error={'code': getattr(error, 'code', 'reading_evidence_invalid'), 'message': str(error)})
        return value
