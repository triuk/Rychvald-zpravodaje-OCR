"""Typed queue decisions from original owned attempts, never translated text."""
import copy
import json

from .jobs import JobError, sha
from .recovery import NAMESPACES


def admission_failure(error, item, *, proven_unstarted):
    code = getattr(error, 'code', 'queue_start_failed')
    local = code in ('source_corrupt', 'source_missing', 'source_unreadable', 'invalid_source', 'run_metadata_invalid')
    return {'scope': 'pdf' if local else 'global', 'category': 'pdf' if local else
        'ai_unavailable' if code in ('runtime_changed', 'codex_runtime_invalid', 'context_runtime_invalid') else 'reconciliation',
        'code': code, 'message': str(error), 'item_id': item['item_id'], 'run_id': item['run_id'],
        'parent_attempt_id': item['parent_attempt_id'], 'child_attempt_id': None,
        'thread_id': None, 'turn_id': None, 'evidence_path': None, 'evidence_sha256': None,
        'original_error': {'source': 'local_admission', 'code': code, 'message': str(error)},
        'delivery_state': 'not_submitted' if proven_unstarted else 'unknown'}


def run_failure(root, run, parent):
    error = copy.deepcopy(parent.get('error') or {'code': 'stage_incomplete', 'message': 'Run did not complete.'})
    code = error['code']
    stage = parent.get('stages', [])[-1] if parent.get('stages') else {}
    failure = {'scope': 'pdf', 'category': 'pdf', **error, 'run_id': run['project']['run_id'],
        'parent_attempt_id': parent['attempt_id'], 'child_attempt_id': stage.get('attempt_id'),
        'stage': stage.get('stage'), 'thread_id': None, 'turn_id': None,
        'connection_id': None, 'original_error': None, 'evidence_path': None,
        'evidence_sha256': None, 'delivery_state': 'not_submitted'}
    namespace = NAMESPACES.get(stage.get('stage'), 'correction-attempts' if stage.get('stage') == 'corrections' else None)
    raw_error = None
    if namespace and stage.get('attempt_id'):
        work = root / run['artifacts']['workspace']['path']
        path = work / 'application' / namespace / stage['attempt_id'] / 'attempt.json'
        child = json.loads(path.read_text())
        if child['run_id'] != failure['run_id'] or child['root'] != str(root):
            raise JobError('attempt_conflict', 'Failure evidence belongs to another run.')
        failure.update(thread_id=child.get('thread_id'), turn_id=child.get('turn_id'))
        protocol = (root / child['artifacts']['protocol']).resolve()
        if not protocol.is_relative_to(work.resolve()):
            raise JobError('attempt_invalid', 'Failure evidence escaped the owned workspace.')
        if protocol.exists():
            failure.update(evidence_path=str(protocol.relative_to(root)), evidence_sha256=sha(protocol))
            pending = {}
            for line in protocol.read_text().splitlines(keepends=True):
                if not line.endswith('\n'):
                    failure['delivery_state'] = 'unknown'
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    failure['delivery_state'] = 'unknown'
                    continue
                message, connection = row['message'], str(row.get('connection_id', '0'))
                key = (connection, message.get('id'))
                if row['direction'] == 'client' and message.get('method') == 'turn/start':
                    pending[key] = message['params']['threadId']
                    failure.update(delivery_state='unknown', thread_id=pending[key], connection_id=connection)
                elif row['direction'] == 'server':
                    if message.get('error') and 'method' not in message:
                        raw_error = copy.deepcopy(message['error'])
                        if key in pending:
                            failure.update(delivery_state='rejected', thread_id=pending[key], connection_id=connection)
                    if key in pending and message.get('result', {}).get('turn', {}).get('id'):
                        failure.update(turn_id=message['result']['turn']['id'], delivery_state='accepted')
                    if message.get('method') == 'turn/completed':
                        terminal = message['params']['turn']
                        failure.update(thread_id=message['params'].get('threadId'), turn_id=terminal['id'],
                            connection_id=connection, delivery_state=terminal['status'])
                        if terminal.get('error'):
                            raw_error = copy.deepcopy(terminal['error'])
    failure['original_error'] = raw_error
    categories = {
        'chatgpt_account_required': 'authentication', 'codex_login_failed': 'authentication',
        'model_capability_unavailable': 'model_unavailable', 'model_configuration_mismatch': 'model_unavailable',
        'model_rerouted': 'model_unavailable', 'codex_timeout': 'network', 'codex_process_terminated': 'network',
        'model_configuration_unsupported': 'model_unavailable', 'runtime_changed': 'ai_unavailable',
        'context_runtime_invalid': 'ai_unavailable', 'context_hooks_invalid': 'ai_unavailable',
        'context_hook_untrusted': 'ai_unavailable', 'context_routing_unverified': 'ai_unavailable',
        'context_recovery_unverified': 'ai_unavailable',
        'correction_reconciliation_required': 'reconciliation', 'original_result_unavailable': 'reconciliation',
        'reconciliation_required': 'reconciliation', 'owner_stopped': 'reconciliation'}
    category = categories.get(code)
    info = raw_error.get('codexErrorInfo') if isinstance(raw_error, dict) else None
    if info is None and isinstance(raw_error, dict) and isinstance(raw_error.get('data'), dict):
        info = raw_error['data'].get('codexErrorInfo')
    variant = info if isinstance(info, str) else next(iter(info), None) if isinstance(info, dict) else None
    category = {'usageLimitExceeded': 'quota', 'rateLimitExceeded': 'quota',
        'unauthorized': 'authentication', 'authenticationError': 'authentication',
        'modelNotFound': 'model_unavailable', 'modelUnavailable': 'model_unavailable',
        'httpConnectionFailed': 'network', 'connectionFailed': 'network',
        'streamDisconnected': 'network', 'serverOverloaded': 'service_unavailable',
        'internalServerError': 'service_unavailable'}.get(variant, category)
    if category is None and (raw_error is not None or code.startswith('codex_')):
        category = 'ai_unavailable'
    if category is not None:
        failure.update(scope='global', category=category)
    return failure
