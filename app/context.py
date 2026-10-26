"""Run-local context readiness: registration alone never enables autonomous OCR."""
from .codex import OwnedJobs, RpcProcess, MODEL, EFFORT, now, process_identity, scrub
from .jobs import JobError, atomic_json, sha
from pathlib import Path
from .context_runtime import default_context_runtime, verify_resources, configuration, command, verify_hooks
from .context_evidence import inspect_stores
import copy
import json
import threading
import time
import uuid
import hashlib
import os

ROUTING_PROMPT = ('Verify this run context-mode integration. Follow exactly: first invoke the native shell tool with '
    'command ./gradlew --context-diagnostic and a small output limit, so the trusted PreToolUse build-output '
    'routing hook can redirect it. Follow its routing instruction. Execute the same local generator using '
    'context-mode ctx_execute (language shell, code ./gradlew --context-diagnostic, intent '
    'CONTEXT_DIAGNOSTIC_RECORD); its output exceeds 500 KB and must remain indexed outside the conversation. '
    'Then call context-mode ctx_search for CONTEXT_DIAGNOSTIC_RECORD to retrieve the stored record. '
    'Do not read or print the data file with another tool. Return only the exact record value from ctx_search.')
RECOVERY_PROMPT = ('Recover the previous diagnostic task using the context-mode session_knowledge injected by SessionStart. '
    'First call ctx_search with source "session-events" and a query about the previous diagnostic generator and record. '
    'Then use ctx_search to retrieve the record identified by that recovered session evidence. '
    'Do not read the data file, rerun the generator or rely only on the conversation summary. '
    'Return only the exact stored record value.')


def prepare_input(workspace, storage):
    """Build a reviewable synthetic payload without Codex, hooks or inference."""
    workspace.mkdir(parents=True, exist_ok=True)
    storage.mkdir(parents=True, exist_ok=True)
    oracle = uuid.uuid4().hex
    dataset = ''.join(f'ROW_{index:05d} local diagnostic payload {"x" * 70}\n' for index in range(6000))
    dataset += 'CONTEXT_DIAGNOSTIC_RECORD = ' + oracle + '\n'
    data = workspace / 'diagnostic-data.txt'
    data.write_text(dataset, encoding='utf-8')
    generator = workspace / 'gradlew'
    generator.write_text('#!/bin/sh\nexec python3 -c \'from pathlib import Path; print(Path("diagnostic-data.txt").read_text(), end="")\'\n')
    generator.chmod(0o700)
    instructions = ('Use context-mode for large output and knowledge lookup. Work only in this run workspace. '
                    'Never install or repair dependencies. The gradlew file is a local diagnostic output generator, not a build. '
                    'The literal CONTEXT_DIAGNOSTIC_RECORD is run-local evidence that must be retrieved with ctx_search.\n')
    (workspace / 'AGENTS.md').write_text(instructions, encoding='utf-8')
    (storage / 'config').mkdir(exist_ok=True)
    (storage / 'config/AGENTS.md').write_text(instructions, encoding='utf-8')
    result = {'path': str(data), 'sha256': sha(data), 'bytes': len(dataset.encode()),
              'oracle_commitment': hashlib.sha256(oracle.encode()).hexdigest(), 'generator_sha256': sha(generator),
              'instructions': instructions, 'routing_prompt': ROUTING_PROMPT, 'recovery_prompt': RECOVERY_PROMPT}
    atomic_json(storage / 'prepared-input.json', result)
    return result


def verify_routing(items, hooks, oracle):
    tools = [item for item in items if item.get('type') == 'mcpToolCall' and item.get('server') == 'context_mode'
             and item.get('status') == 'completed' and not item.get('error')]
    large = [item for item in tools if item.get('tool') == 'ctx_execute' and
             item.get('arguments', {}).get('language') == 'shell' and
             item.get('arguments', {}).get('code', '').strip() == './gradlew --context-diagnostic']
    lookup = [item for item in tools if item.get('tool') == 'ctx_search' and
              any(oracle in block.get('text', '') for block in (item.get('result') or {}).get('content', []))]
    redirected = [item for item in items if item.get('type') == 'commandExecution' and item.get('status') == 'completed'
                  and item.get('exitCode') == 0 and 'echo' in item.get('command', '')
                  and item.get('aggregatedOutput', '').startswith('context-mode: Build tool redirected.')]
    events = {entry.get('eventName') for entry in hooks if entry.get('status') == 'completed'}
    if not large or not lookup or not redirected or not {'sessionStart', 'preToolUse', 'postToolUse', 'userPromptSubmit', 'stop'}.issubset(events):
        raise JobError('context_routing_unverified', 'Actual trusted hook redirection, large generator execution and exact stored lookup were not all observed.')


class OwnedContextJobs(OwnedJobs):
    """Owned model lifecycle plus runtime selection, without diagnostic setup."""
    namespace = 'context-attempts'
    step_id = 'context_diagnostic'

    def __init__(self, publish, runtime=None, context_runtime=None):
        super().__init__(publish, runtime)
        self.context_runtime = context_runtime if context_runtime is not None else default_context_runtime()


class ContextJobs(OwnedContextJobs):
    """Context diagnostic preparation and evidence, separate from visual jobs."""

    def prepare(self, root, run):
        work = root / run['artifacts']['workspace']['path']
        return prepare_input(work / 'context/workspace', work / 'context/store')

    def status(self, root, run_id, work, operation=None):
        value = super().status(root, run_id, work, operation)
        if value.get('context_verified') and value.get('state') == 'completed':
            try:
                value['context_evidence'] = inspect_stores(value['context_paths']['storage'], value['context_paths']['workspace'],
                    value['thread_id'], value['oracle'], value['diagnostic_input']['bytes'])
                routing = next(turn for turn in value['turns'] if turn['stage'] == 'routing')
                verify_routing([entry['item'] for entry in value['completed_items'] if entry.get('turnId') == routing['turn_id']],
                    [entry['params']['run'] for entry in value['hook_events'] if entry['method'] == 'hook/completed'], value['oracle'])
            except JobError as error:
                value.update(state='invalidated', context_verified=False, autonomous_ocr_ready=False,
                             error={'code': error.code, 'message': str(error)})
        return value

    def _run(self, job):
        value = job['manifest']
        started = time.monotonic()
        trace_lock = threading.Lock()
        value.update(context_verified=False, hook_events=[], connections=[], turns=[], completed_items=[], terminal_turns={})
        reused_context = None
        previous = (job.get('metadata') or {}).get('previous_context_attempt_id')

        def notify(message):
            if 'method' not in message:
                raise JobError('codex_protocol_invalid', 'Unmatched context protocol response.')
            if 'id' in message:
                job['rpc'].send({'id': message['id'], 'error': {'code': -32601, 'message': 'No client approvals/tools for context diagnostic.'}})
                raise JobError('context_tool_approval', 'Context verification requested unsupported client approval.')
            params = message.get('params', {})
            thread_id = params.get('threadId') or params.get('thread', {}).get('id')
            if thread_id is not None and value.get('thread_id') is not None and thread_id != value['thread_id']:
                raise JobError('codex_identity_mismatch', 'Context event belongs to another thread.')
            if message['method'] in ('hook/started', 'hook/completed'):
                value['hook_events'].append(copy.deepcopy(message))
            elif message['method'] == 'thread/tokenUsage/updated':
                value['usage_events'].append(copy.deepcopy(params))
            elif message['method'] == 'model/rerouted':
                value['reroutes'].append(copy.deepcopy(params))
            elif message['method'] == 'item/completed':
                value['completed_items'].append(copy.deepcopy(params))
            elif message['method'] == 'turn/completed':
                value['terminal_turns'][params['turn']['id']] = copy.deepcopy(params['turn'])
            elif message['method'] == 'thread/compacted':
                value['compacted_notification'] = copy.deepcopy(params)

        def connect(settings, trust=None):
            connection_id = str(len(value['connections']))

            def trace(direction, message):
                with trace_lock, (job['directory'] / 'protocol.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps({'timestamp': now(), 'elapsed_seconds': time.monotonic() - started,
                                             'connection_id': connection_id, 'direction': direction,
                                             'message': scrub(message)}, ensure_ascii=False) + '\n')
                    stream.flush()
                    os.fsync(stream.fileno())

            stderr = (job['directory'] / 'stderr.log').open('a', encoding='utf-8')
            rpc = RpcProcess(command(self.runtime, settings, trust), workspace, stderr, trace,
                             lambda: job['cancel'], env=settings['process_environment'], paused=lambda: job.get('pause', False))
            job['rpc'], job['stderr'] = rpc, stderr
            identity = {'connection_id': connection_id, 'pid': rpc.process.pid, 'process_group': rpc.process.pid,
                        'process_start_ticks': process_identity(rpc.process.pid)}
            value['connections'].append(identity)
            value.update(identity, state='running')
            self._event(job, 'context_process_started', **identity)
            rpc.request('initialize', {'clientInfo': {'name': 'rychvald-context', 'version': '1.0'},
                                      'capabilities': {'experimentalApi': True}}, notify)
            rpc.send({'method': 'initialized'})
            return rpc

        def disconnect():
            if job.get('rpc') is not None:
                job['rpc'].close()
                value['connections'][-1]['returncode'] = job['rpc'].process.returncode
                job['rpc'] = None
                job['stderr'].close()

        def turn(rpc, stage, prompt):
            params = {'threadId': value['thread_id'], 'model': MODEL, 'effort': EFFORT,
                      'input': [{'type': 'text', 'text': prompt}]}
            value.setdefault('application_requests', []).append({'stage': stage, 'params': params})
            atomic_json(job['directory'] / 'request.json', {'requests': value['application_requests'],
                        'profile_sha256': value['profile_sha256'], 'effective_context_config': value['effective_context_config']})
            result = rpc.request('turn/start', params, notify)
            identifier = result['turn']['id']
            value['turn_id'] = identifier
            record = {'stage': stage, 'thread_id': value['thread_id'], 'turn_id': identifier, 'state': 'running', 'prompt': prompt}
            value['turns'].append(record)
            self._event(job, 'context_turn_submitted', stage=stage, thread_id=value['thread_id'], turn_id=identifier)
            deadline = time.monotonic() + 240
            while identifier not in value['terminal_turns']:
                notify(rpc.receive(deadline))
            terminal = value['terminal_turns'][identifier]
            record['state'] = terminal['status']
            if terminal['status'] != 'completed':
                raise JobError('codex_turn_' + terminal['status'], str(terminal.get('error') or terminal['status']))
            if value['reroutes']:
                raise JobError('model_rerouted', 'A redirected turn cannot verify the requested model/context combination.')
            items = [entry['item'] for entry in value['completed_items'] if entry.get('turnId') == identifier]
            messages = [item for item in items if item.get('type') == 'agentMessage']
            final = [item for item in messages if item.get('phase') == 'final_answer']
            record['answer'] = (final or messages or [{}])[-1].get('text', '')
            value['answer'] = record['answer']
            return record, items

        try:
            if previous:
                if not isinstance(previous, str) or len(previous) != 32 or any(c not in '0123456789abcdef' for c in previous):
                    raise JobError('attempt_invalid', 'Invalid original context attempt identity.')
                original_path = job['directory'].parent / previous / 'attempt.json'
                original = json.loads(original_path.read_text())
                routing = next((row for row in original.get('turns', []) if row['stage'] == 'routing' and row.get('state') == 'completed'), None)
                if routing:
                    if (original['run_id'] != value['run_id'] or original['runtime'] != self.runtime or
                            original['context_runtime'] != self.context_runtime or original['profile_sha256'] != value['profile_sha256']):
                        raise JobError('context_input_changed', 'Original context diagnostic has different bindings.')
                    reused_context = original
                    original_protocol = Path(value['root']) / original['artifacts']['protocol']
                    value['reused_context'] = {'path': str(original_path), 'sha256': sha(original_path),
                        'protocol': {'path': str(original_protocol), 'sha256': sha(original_protocol)}}
                    value['turns'] = [copy.deepcopy(row) for row in original['turns'] if row.get('state') == 'completed']
                    value['completed_items'] = copy.deepcopy(original['completed_items'])
                    value['hook_events'] = copy.deepcopy(original['hook_events'])
            self._event(job, 'context_attempt_started')
            value['context_capabilities'] = verify_resources(self.context_runtime, self.runtime)
            work = job['directory'].parents[2]
            workspace, storage = work / 'context/workspace', work / 'context/store'
            workspace.mkdir(parents=True, exist_ok=True)
            storage.mkdir(parents=True, exist_ok=True)
            settings = configuration(self.context_runtime, self.runtime, workspace, storage)
            packet = storage / 'prepared-input.json'
            if not packet.exists():
                prepare_input(workspace, storage)
            prepared = json.loads(packet.read_text())
            if prepared['path'] != str(workspace / 'diagnostic-data.txt') or sha(Path(prepared['path'])) != prepared['sha256'] or sha(workspace / 'gradlew') != prepared['generator_sha256']:
                raise JobError('context_input_changed', 'Prepared synthetic diagnostic input changed before execution.')
            if prepared['routing_prompt'] != ROUTING_PROMPT or prepared['recovery_prompt'] != RECOVERY_PROMPT:
                raise JobError('context_input_changed', 'Prepared diagnostic prompts differ from application instructions.')
            if any(path.read_text(encoding='utf-8') != prepared['instructions'] for path in
                   [workspace / 'AGENTS.md', storage / 'config/AGENTS.md']):
                raise JobError('context_input_changed', 'Prepared diagnostic instruction files changed before execution.')
            oracle = (workspace / 'diagnostic-data.txt').read_text().split('CONTEXT_DIAGNOSTIC_RECORD = ')[-1].strip()
            if hashlib.sha256(oracle.encode()).hexdigest() != prepared['oracle_commitment']:
                raise JobError('context_input_changed', 'Prepared diagnostic record commitment does not match.')
            value['diagnostic_input'] = prepared
            value['context_runtime'] = self.context_runtime
            value['context_paths'] = {'workspace': str(workspace), 'storage': str(storage)}
            value['effective_context_config'] = {key: settings[key] for key in ['hooks', 'mcp_servers', 'context_environment']}
            rpc = connect(settings)
            untrusted = rpc.request('hooks/list', {'cwds': [str(workspace)]}, notify)
            trust = verify_hooks(untrusted, settings)
            value['hook_review'] = untrusted
            disconnect()
            rpc = connect(settings, trust)
            trusted = rpc.request('hooks/list', {'cwds': [str(workspace)]}, notify)
            verify_hooks(trusted, settings, trusted=True, expected=trust)
            value['trusted_hooks'] = trusted
            account = rpc.request('account/read', {'refreshToken': False}, notify)
            value['account'] = scrub(account)
            value['authenticated'] = bool(account.get('account') and account['account'].get('type') == 'chatgpt')
            if not value['authenticated']:
                raise JobError('chatgpt_account_required', 'A supported ChatGPT login is required for context verification.')
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
                    item.get('reasoningEffort') == EFFORT for item in found.get('supportedReasoningEfforts', [])):
                raise JobError('model_capability_unavailable', 'Exact model/high/image capability is not advertised.')
            value['declared_model'] = found
            thread_params = {'model': MODEL, 'cwd': str(workspace), 'config': {'model_reasoning_effort': EFFORT},
                             'approvalPolicy': 'never', 'sandbox': 'workspace-write',
                             'runtimeWorkspaceRoots': [str(workspace), str(storage)],
                             'developerInstructions': 'Use the context-mode MCP tools and routing hooks. Work only in this run workspace. Never install or repair dependencies.'}
            if reused_context:
                thread_params['threadId'] = reused_context['thread_id']
            thread = rpc.request('thread/resume' if reused_context else 'thread/start', thread_params, notify)
            value['thread_id'] = thread['thread']['id']
            value['effective'] = {'model': thread.get('model'), 'reasoning_effort': thread.get('reasoningEffort'), 'source': 'thread/start'}
            if thread.get('model') != MODEL or thread.get('reasoningEffort') != EFFORT:
                raise JobError('model_configuration_mismatch', 'Context thread did not confirm the exact model and high effort.')
            if reused_context:
                if value['thread_id'] != reused_context['thread_id']:
                    raise JobError('codex_identity_mismatch', 'Resumed another original diagnostic thread.')
                routing = next(row for row in value['turns'] if row['stage'] == 'routing')
                items = [entry['item'] for entry in value['completed_items'] if entry.get('turnId') == routing['turn_id']]
                self._event(job, 'context_routing_reused', original_attempt_id=previous, turn_id=routing['turn_id'])
            else:
                routing, items = turn(rpc, 'routing', ROUTING_PROMPT)
            hooks = [entry['params']['run'] for entry in value['hook_events'] if entry['method'] == 'hook/completed']
            verify_routing(items, hooks, oracle)
            if routing['answer'].strip() != oracle:
                raise JobError('context_lookup_incorrect', 'Knowledge lookup did not return the independently held run-local record.')
            value['oracle'] = oracle
            self._event(job, 'context_routing_completed', thread_id=value['thread_id'], turn_id=routing['turn_id'])
            count = sum(entry['item'].get('type') == 'contextCompaction' for entry in value['completed_items'])
            compacted = reused_context and any(event['type'] == 'context_compaction_completed' for event in reused_context['events'])
            if not compacted:
                rpc.request('thread/compact/start', {'threadId': value['thread_id']}, notify)
                deadline = time.monotonic() + 180
                while sum(entry['item'].get('type') == 'contextCompaction' for entry in value['completed_items']) == count and not value.get('compacted_notification'):
                    notify(rpc.receive(deadline))
            hooks = [entry['params']['run'] for entry in value['hook_events'] if entry['method'] == 'hook/completed']
            if not any(entry.get('eventName') == 'preCompact' and entry.get('status') == 'completed' for entry in hooks):
                raise JobError('context_recovery_unverified', 'Codex compaction did not execute the trusted PreCompact hook.')
            self._event(job, 'context_compaction_completed', thread_id=value['thread_id'])
            disconnect()
            rpc = connect(settings, trust)
            verify_hooks(rpc.request('hooks/list', {'cwds': [str(workspace)]}, notify), settings, trusted=True, expected=trust)
            resumed = rpc.request('thread/resume', {'threadId': value['thread_id'], 'model': MODEL, 'cwd': str(workspace),
                'config': {'model_reasoning_effort': EFFORT}, 'approvalPolicy': 'never', 'sandbox': 'workspace-write',
                'runtimeWorkspaceRoots': [str(workspace), str(storage)], 'excludeTurns': True}, notify)
            if resumed['thread']['id'] != value['thread_id'] or resumed.get('model') != MODEL or resumed.get('reasoningEffort') != EFFORT:
                raise JobError('model_configuration_mismatch', 'Resumed thread does not match the exact original configuration.')
            self._event(job, 'context_resumed', thread_id=value['thread_id'])
            recovery = next((row for row in value['turns'] if row['stage'] == 'recovery' and row['state'] == 'completed'), None)
            if recovery:
                recovered_items = [entry['item'] for entry in value['completed_items'] if entry.get('turnId') == recovery['turn_id']]
                self._event(job, 'context_recovery_reused', original_attempt_id=previous, turn_id=recovery['turn_id'])
            else:
                recovery, recovered_items = turn(rpc, 'recovery', RECOVERY_PROMPT)
            recovered_calls = [item for item in recovered_items if item.get('type') == 'mcpToolCall'
                and item.get('server') == 'context_mode' and item.get('tool') == 'ctx_search'
                and item.get('status') == 'completed' and not item.get('error')]
            hooks = [entry['params']['run'] for entry in value['hook_events'] if entry['method'] == 'hook/completed']
            restored = [entry for entry in hooks if entry.get('eventName') == 'sessionStart' and entry.get('status') == 'completed'
                        and any('session_knowledge' in block.get('text', '') for block in entry.get('entries', []))]
            if not restored or not any(item.get('arguments', {}).get('source') == 'session-events' for item in recovered_calls) or recovery['answer'].strip() != oracle:
                raise JobError('context_recovery_unverified', 'Actual resumed session context and stored knowledge retrieval were not established.')
            value['context_evidence'] = inspect_stores(storage, workspace, value['thread_id'], oracle, prepared['bytes'])
            value['context_verified'] = True
            value['state'] = 'completed'
        except Exception as error:
            value.update(state='paused' if getattr(error, 'code', None) == 'autonomous_paused' else 'interrupted' if job['cancel'] else 'failed',
                error={'code': getattr(error, 'code', 'context_runtime_invalid'), 'message': str(error)})
        finally:
            disconnect()
            value['ended_at'] = now()
            value['elapsed_seconds'] = time.monotonic() - started
            try:
                self._event(job, 'context_attempt_' + value['state'], error=value['error'])
            finally:
                with self._lock:
                    atomic_json(job['directory'] / 'attempt.json', value)
                    self._active = None
                self.publish('context_finished', root=value['root'], run_id=value['run_id'], state=value['state'])
