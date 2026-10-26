"""Typed queue decisions from original owned attempts, never translated text."""
import copy
import json

from .jobs import JobError, sha
from .original_protocol import read_original_protocol
from .recovery import NAMESPACES
from tools import ocr_correction_graph


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


def _continued_submissions(work, child, submitted):
    """Only verified durable edges can supersede a definitely stopped request."""
    reader = getattr(ocr_correction_graph, 'continuation_edges', None)
    if not child.get('continuations') or not callable(reader):
        return []  # Older sources retain the original global rejection.
    try:
        edges = reader(work, child)
        linked = []
        for edge in edges:
            def matches(record, identity):
                return (record['visual_stage'] == edge['stage'] and all(record[key] == identity[key]
                    for key in ('connection_id', 'thread_id', 'turn_id', 'request_id')))
            originals = [record for record in submitted if matches(record, edge['original'])]
            successors = [record for record in submitted if matches(record, edge['successor'])]
            if (len(originals) != 1 or len(successors) != 1 or originals[0] is successors[0] or
                    originals[0]['delivery_state'] not in ('rejected', 'failed', 'interrupted') or
                    originals[0]['delivery_state'] != edge['original']['state']):
                raise ValueError('Continuation does not identify the original stopped request and exact successor.')
            linked.append((edge, originals[0], successors[0]))
        # Follow explicit edges, including successive definitely stopped attempts.
        # A still unknown/accepted successor never resolves its original.
        for _ in linked:
            changed = False
            for edge, original, successor in linked:
                if not original.get('resolved_by') and (successor['delivery_state'] == 'completed' or successor.get('resolved_by')):
                    original.update(resolved_by=edge['continuation_id'], continuation_successor=copy.deepcopy(edge['successor']))
                    changed = True
            if not changed:
                break
        return edges
    except (ValueError, KeyError, TypeError) as error:
        raise JobError('attempt_conflict', 'Original continuation evidence is invalid: ' + str(error)) from error


def _stage_failure(root, run, parent):
    error = copy.deepcopy(parent.get('error') or {'code': 'stage_incomplete', 'message': 'Run did not complete.'})
    code = error['code']
    stage = parent.get('stages', [])[-1] if parent.get('stages') else {}
    failure = {'scope': 'pdf', 'category': 'pdf', **error, 'run_id': run['project']['run_id'],
        'parent_attempt_id': parent['attempt_id'], 'child_attempt_id': stage.get('attempt_id'),
        'stage': stage.get('stage'), 'thread_id': None, 'turn_id': None,
        'connection_id': None, 'original_error': None, 'evidence_path': None,
        'evidence_sha256': None, 'delivery_state': 'not_submitted'}
    namespace = NAMESPACES.get(stage.get('stage'), 'correction-attempts' if stage.get('stage') == 'corrections' else None)
    raw_error, child = None, None
    if namespace and stage.get('attempt_id'):
        work = root / run['artifacts']['workspace']['path']
        path = work / 'application' / namespace / stage['attempt_id'] / 'attempt.json'
        child = json.loads(path.read_text())
        if (path.is_symlink() or not path.resolve().is_relative_to(work.resolve()) or
                path.parent.name != child['attempt_id'] or child['run_id'] != failure['run_id'] or child['root'] != str(root)):
            raise JobError('attempt_conflict', 'Failure evidence belongs to another run.')
        if stage.get('expected_parent_binding') is not None and child.get('parent_binding') != stage['expected_parent_binding']:
            raise JobError('attempt_conflict', 'Failure evidence belongs to another parent/cycle/intent.')
        failure['child_state'] = child['state']
        failure.update(thread_id=child.get('thread_id'), turn_id=child.get('turn_id'))
        protocol = (root / child['artifacts']['protocol']).resolve()
        if not protocol.is_relative_to(work.resolve()):
            raise JobError('attempt_invalid', 'Failure evidence escaped the owned workspace.')
        if protocol.exists():
            failure.update(evidence_path=str(protocol.relative_to(root)), evidence_sha256=sha(protocol))
            original = read_original_protocol(protocol)
            submitted, malformed = original.submissions, original.malformed
            if submitted:
                edges = _continued_submissions(work, child, submitted) if namespace in ('correction-attempts', 'output-review-attempts') else []
                active = [item for item in submitted if not item.get('resolved_by')] or submitted
                record = next((item for item in active if item['delivery_state'] in ('unknown', 'accepted')),
                    next((item for item in active if item['delivery_state'] in ('rejected', 'failed', 'interrupted')), active[-1]))
                failure.update(record)
                failure['submissions'] = copy.deepcopy(submitted)
                if edges:
                    failure['continuation_edges'] = copy.deepcopy(edges)
                raw_error = record['original_error']
            if malformed:
                failure['delivery_state'] = 'unknown'
        if failure['delivery_state'] == 'not_submitted' and (child.get('turns') or child.get('turn_id')):
            failure.update(delivery_state='unknown', evidence_path=str(path.relative_to(root)), evidence_sha256=sha(path))
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
    if failure['delivery_state'] in ('unknown', 'accepted'):
        failure.update(scope='global', category=category or 'reconciliation')
    if (stage.get('stage') == 'output_review' and failure['delivery_state'] == 'completed' and
            (child['state'] != 'completed' or not child.get('output_review_complete'))):
        failure.update(scope='global', category='reconciliation')
    if child and child.get('continuations') and not callable(getattr(ocr_correction_graph, 'continuation_edges', None)):
        failure.update(scope='global', category=category or 'reconciliation', continuation_verification='unavailable')
    return failure


def run_failure(root, run, parent):
    """Classify the original P/C/K/O graph, including an unlinked output child."""
    stages = parent.get('stages', [])
    stage = stages[-1] if stages else {}
    if stage.get('stage') != 'corrections':
        return _stage_failure(root, run, parent)
    work = root / run['artifacts']['workspace']['path']
    stage = dict(stage)
    if not stage.get('attempt_id') and stage.get('intent_id'):
        binding = {'parent_attempt_id': parent['attempt_id'], 'intent_id': stage['intent_id'], 'stage': 'corrections'}
        matches = [json.loads(path.read_text()) for path in (work / 'application/correction-attempts').glob('*/attempt.json')
            if json.loads(path.read_text()).get('parent_binding') == binding]
        if len(matches) > 1:
            raise JobError('attempt_conflict', 'Multiple correction children claim the original parent intent.')
        if matches:
            stage.update(attempt_id=matches[0]['attempt_id'], expected_parent_binding=binding)
    failure = _stage_failure(root, run, {**parent, 'stages': [stage]})
    if not stage.get('attempt_id'):
        return failure
    path = work / 'application/correction-attempts' / stage['attempt_id'] / 'attempt.json'
    correction = json.loads(path.read_text())
    binding = correction.get('parent_binding')
    if binding and (binding.get('parent_attempt_id') != parent['attempt_id'] or binding.get('stage') != 'corrections' or
            stage.get('intent_id') is not None and binding.get('intent_id') != stage['intent_id']):
        raise JobError('attempt_conflict', 'Correction belongs to another original parent intent.')
    failure.update(correction_attempt_id=correction['attempt_id'], cycle_id=correction.get('cycle_id'),
        cycle_index=correction.get('cycle_index'), intent_id=(binding or {}).get('intent_id'))
    if any(item['stage'] != 'output_review' for item in correction.get('children', [])):
        raise JobError('correction_reconciliation_required', 'Original correction descendant identity is unsupported; no new admission.')
    descendants = []
    cycle_ids = {item['cycle_id'] for item in correction.get('output_intents', [])}
    cycle_ids.update(item['cycle_id'] for item in correction.get('children', []) if item['stage'] == 'output_review')
    if cycle_ids:
        ledger = json.loads((work / 'application/corrections/ledger.json').read_text())
        for cycle_id in sorted(cycle_ids):
            cycles = [item for item in ledger['cycles'] if item['cycle_id'] == cycle_id]
            if len(cycles) != 1 or cycles[0].get('attempt_id') != correction['attempt_id']:
                raise JobError('attempt_conflict', 'Output descendant belongs to another correction cycle.')
            try:
                intent, child = ocr_correction_graph.output_child(work, correction, cycle_id)
            except ValueError as error:
                raise JobError('attempt_conflict', str(error)) from error
            if intent['cycle_index'] != cycles[0]['index']:
                raise JobError('attempt_conflict', 'Output descendant correction index changed.')
            if child is None:
                evidence = {**failure, 'stage': 'output_review', 'child_attempt_id': None,
                    'delivery_state': 'unknown', 'scope': 'global', 'category': 'reconciliation',
                    'thread_id': None, 'turn_id': None, 'connection_id': None,
                    'evidence_path': str(path.relative_to(root)), 'evidence_sha256': sha(path)}
            else:
                evidence = _stage_failure(root, run, {**parent, 'stages': [{'stage': 'output_review',
                    'attempt_id': child['attempt_id'], 'expected_parent_binding': intent['binding']}]})
                if child['state'] != 'completed' and evidence['delivery_state'] == 'not_submitted':
                    child_path = work / 'application/output-review-attempts' / child['attempt_id'] / 'attempt.json'
                    # RpcProcess.send records before writing to stdin; visual_session
                    # flushes/fsyncs both traces before record returns. No outgoing
                    # trace means not_submitted, while this local child is pending.
                    evidence.update(scope='global', category='reconciliation', pending_descendant=True,
                        evidence_path=str(child_path.relative_to(root)), evidence_sha256=sha(child_path))
            evidence.update(correction_attempt_id=correction['attempt_id'], cycle_id=cycle_id,
                cycle_index=intent['cycle_index'], stage_intent_id=intent['stage_intent_id'],
                intent_id=intent['binding']['intent_id'], parent_binding=copy.deepcopy(intent['binding']))
            descendants.append(evidence)
    if correction.get('stage') == 'output_review' and correction.get('state') != 'completed' and not descendants:
        failure.update(delivery_state='unknown', scope='global', category='reconciliation',
            code='correction_reconciliation_required', message='Original correction output intent is incomplete; no new admission.')
    selected = next((item for item in [*descendants, failure] if item['delivery_state'] in ('unknown', 'accepted')),
        next((item for item in descendants if item['scope'] == 'global'), failure))
    return {**selected, 'descendants': descendants}
