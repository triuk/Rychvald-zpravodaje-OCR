"""A single image-only native Codex turn with original protocol provenance."""
import copy
import json
import os
import threading
import time

from .codex import RpcProcess, MODEL, EFFORT, now, process_identity, scrub
from .context_runtime import verify_resources, configuration, command, verify_hooks
from .jobs import JobError, atomic_json, sha


def examine(manager, job, stage, prompt, schema, work, images, *, instructions=None, directory=None):
    """No automatic retries; every accepted turn remains durable even on local failure."""
    value = job['manifest']
    directory = directory or job['directory'] / stage
    continuation = job.get('current_continuation')
    preparation = {}
    if continuation is not None:
        from .visual_preparation import restore_preparation
        preparation = restore_preparation(job, stage, prompt, schema, work, images, directory)
    directory.mkdir(exist_ok=continuation is not None)
    workspace = directory / 'workspace'
    storage = directory / 'context'
    workspace.mkdir(exist_ok=continuation is not None)
    storage.mkdir(exist_ok=continuation is not None)
    protocol = directory / 'protocol.jsonl'
    started = time.monotonic()
    lock = threading.Lock()
    value.setdefault('turns', [])
    value.setdefault('connections', [])
    items, terminals, reroutes = [], {}, []
    rpc = None
    connection_id = None

    def trace(direction, message):
        row = {'timestamp': now(), 'elapsed_seconds': time.monotonic()-started,
            'direction': direction, 'stage': stage, 'connection_id': connection_id, 'message': scrub(message)}
        with lock:
            for target in (protocol, job['directory']/'protocol.jsonl'):
                with target.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(row, ensure_ascii=False)+'\n')
                    stream.flush()
                    os.fsync(stream.fileno())

    def notify(message):
        if 'id' in message:
            rpc.send({'id': message['id'], 'error': {'code': -32601, 'message': 'Image-only examination has no dynamic tools or approvals.'}})
            raise JobError('visual_tool_forbidden', 'Only attached images and context statistics may be used.')
        params = message.get('params', {})
        foreign = params.get('threadId') or params.get('thread', {}).get('id')
        if foreign is not None and value.get('thread_id') is not None and foreign != value['thread_id']:
            raise JobError('codex_identity_mismatch', 'Visual event belongs to another native thread.')
        method = message.get('method')
        if method == 'item/completed':
            items.append(copy.deepcopy(params))
            item = params['item']
            if item['type'] in ('commandExecution', 'fileChange') or item['type'] == 'mcpToolCall' and (
                item.get('server') != 'context_mode' or item.get('tool') != 'ctx_stats'):
                raise JobError('visual_tool_forbidden', 'Visual source examination cannot inspect candidate/output files.')
        elif method == 'turn/completed':
            terminals[params['turn']['id']] = params['turn']
        elif method == 'thread/tokenUsage/updated':
            value['usage_events'].append(copy.deepcopy(params))
        elif method == 'model/rerouted':
            reroutes.append(params)

    def connect(settings, trust=None):
        nonlocal rpc, connection_id
        connection_id = preparation['connection_id'] if trust and preparation else str(len(value['connections']))
        stderr = (directory / 'stderr.log').open('a')
        rpc = RpcProcess(command(manager.runtime, settings, trust), workspace, stderr, trace,
                         lambda: job['cancel'], env=settings['process_environment'], paused=lambda: job.get('pause', False))
        job['rpc'] = rpc
        value['connections'].append({'stage': stage, 'connection_id': connection_id,
            'pid': rpc.process.pid, 'process_start_ticks': process_identity(rpc.process.pid),
            **({'resumed_preparation': True} if trust and preparation else {})})
        rpc.request('initialize', {'clientInfo': {'name': 'rychvald-geometry', 'version': '1.0'},
            'capabilities': {'experimentalApi': True}}, notify)
        rpc.send({'method': 'initialized'})
        return stderr

    def disconnect(stderr):
        nonlocal rpc
        if rpc is not None:
            rpc.close()
            job['rpc'] = None
            rpc = None
        stderr.close()

    verify_resources(manager.context_runtime, manager.runtime)
    instructions = instructions or ('Examine only the attached original/diagnostic images. Do not run shell commands, read files, '
        'use candidate/output text, install software or change the project. Call context_mode ctx_stats once. '
        'Return exactly the requested JSON with honest uncertainty, no invented visual verification.\n')
    (workspace / 'AGENTS.md').write_text(instructions)
    settings = configuration(manager.context_runtime, manager.runtime, workspace, storage)
    (storage / 'config/AGENTS.md').write_text(instructions)
    stderr = connect(settings)
    try:
        trust = verify_hooks(rpc.request('hooks/list', {'cwds': [str(workspace)]}, notify), settings)
    finally:
        disconnect(stderr)
    stderr = connect(settings, trust)
    try:
        verify_hooks(rpc.request('hooks/list', {'cwds': [str(workspace)]}, notify), settings, trusted=True, expected=trust)
        account = rpc.request('account/read', {'refreshToken': False}, notify)
        if account.get('account', {}).get('type') != 'chatgpt':
            raise JobError('chatgpt_account_required', 'A managed ChatGPT account is required.')
        thread_params = {'model': MODEL, 'cwd': str(workspace),
            'config': {'model_reasoning_effort': EFFORT}, 'approvalPolicy': 'never', 'sandbox': 'workspace-write',
            'runtimeWorkspaceRoots': [str(workspace), str(storage)], 'developerInstructions': instructions}
        if preparation:
            thread_params['threadId'] = preparation['params']['threadId']
        thread = rpc.request('thread/resume' if preparation else 'thread/start', thread_params, notify)
        if preparation and thread['thread']['id'] != preparation['params']['threadId']:
            raise JobError('codex_identity_mismatch', 'Native provider did not resume the exact unsubmitted thread.')
        value['thread_id'] = thread['thread']['id']
        value['effective'] = {'model': thread.get('model'), 'reasoning_effort': thread.get('reasoningEffort')}
        if thread.get('model') != MODEL or thread.get('reasoningEffort') != EFFORT:
            raise JobError('model_configuration_mismatch', 'Exact model/high required for geometry examination.')
        inputs = [{'type': 'text', 'text': prompt}] + [
            {'type': 'localImage', 'path': str((work / image['path']).resolve())} for image in images]
        params = {'threadId': value['thread_id'], 'model': MODEL, 'effort': EFFORT, 'input': inputs, 'outputSchema': schema}
        value.setdefault('application_requests', []).append({'stage': stage, 'params': params})
        atomic_json(job['directory']/'request.json', {'requests': value['application_requests']})
        if preparation:
            if params != preparation['params']:
                raise JobError('checkpoint_invalid', 'Resumed request differs from its immutable preparation.')
        else:
            atomic_json(directory / 'request.json', params)
        continuation = job.get('current_continuation')
        if continuation is not None:
            if preparation.get('successor') is not None:
                continuation['successor'] = preparation['successor']
                manager._event(job, 'correction_continuation_submitting', stage=stage,
                    cycle_id=continuation['cycle_id'], continuation_id=continuation['continuation_id'],
                    successor=continuation['successor'], resumed_preparation=True)
            else:
                from .visual_continuation import bind_submission
                bind_submission(manager, job, continuation, params, connection_id, directory, protocol)
        result = rpc.request('turn/start', params, notify)
        identifier = result['turn']['id']
        value['turn_id'] = identifier
        record = {'stage': stage, 'thread_id': value['thread_id'], 'turn_id': identifier, 'state': 'running',
            'prompt': prompt, 'protocol': str(protocol.relative_to(job['root'])), 'connection_id': connection_id}
        value['turns'].append(record)
        if continuation is not None:
            continuation['successor'].update(turn_id=identifier, state='accepted')
        manager._event(job, 'geometry_turn_submitted', stage=stage, thread_id=value['thread_id'], turn_id=identifier)
        deadline = time.monotonic()+600
        while identifier not in terminals:
            notify(rpc.receive(deadline))
        record['state'] = terminals[identifier]['status']
        if continuation is not None:
            continuation['successor']['state'] = record['state']
        if record['state'] != 'completed':
            raise JobError('codex_turn_'+record['state'], str(terminals[identifier].get('error')))
        if reroutes:
            raise JobError('model_rerouted', 'Visual examination was rerouted.')
    finally:
        disconnect(stderr)
    # Verify the original trace after closing the provider connection, before publication.
    proof = {'protocol': {'path': str(protocol), 'sha256': sha(protocol)},
        'thread_id': value['thread_id'], 'turn_id': identifier}
    if continuation is not None:
        continuation['successor']['protocol']['sha256'] = proof['protocol']['sha256']
    from tools.ocr_visual_evidence import verify_visual_turn
    answer = verify_visual_turn(proof, work, images)
    path = directory / 'proposal.json'
    atomic_json(path, answer)
    record.update(answer=json.dumps(answer, ensure_ascii=False), proposal=str(path.relative_to(job['root'])))
    return answer, proof, path
