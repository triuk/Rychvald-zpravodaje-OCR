"""Durable manual admission identity and original-delivery evidence."""
import json

from .failures import run_failure
from .jobs import JobError, sha
from .recovery import NAMESPACES


STAGES = {'start_model_diagnostic': 'model_diagnostic', 'check_codex_account': 'model_diagnostic',
    'start_codex_login': 'model_diagnostic', 'start_context_diagnostic': 'context_diagnostic',
    'start_reading': 'reading', 'start_geometry': 'geometry', 'start_output_review': 'output_review',
    'start_corrections': 'corrections', 'start_preparation': 'prepare'}


def settle(app, root, value):
    """Local idleness never establishes that an outgoing AI request was unsent."""
    stage = STAGES.get(value['operation'])
    namespace = NAMESPACES.get(stage, 'correction-attempts' if stage == 'corrections' else 'attempts')
    matches = []
    pattern = '*/application/' + namespace + ('/*.json' if namespace == 'attempts' else '/*/attempt.json')
    if stage:
        for path in (root / 'work').glob(pattern):
            if namespace == 'attempts' and (len(path.stem) != 32 or any(c not in '0123456789abcdef' for c in path.stem)):
                continue
            child = json.loads(path.read_text())
            if isinstance(child, dict) and child.get('manual_binding') == {'manual_id': value['manual_id']}:
                matches.append((path, child))
    if len(matches) > 1:
        raise JobError('attempt_conflict', 'Multiple children claim the manual admission intent.')
    if not matches:
        # dispatch returned locally without publishing an asynchronous child;
        # unlike a process crash or lost RPC ACK, this is a closed admission.
        value.update(state='settled', delivery_state='not_submitted', child_attempt_id=None)
        return value
    path, child = matches[0]
    if child['root'] != str(root) or child['run_id'] != value['run_id']:
        raise JobError('attempt_conflict', 'Manual child belongs to another registry/run.')
    value.update(child_attempt_id=child['attempt_id'], child_manifest=str(path.relative_to(root)),
        child_manifest_sha256=sha(path))
    if stage == 'prepare':
        value.update(state='settled', delivery_state='not_submitted')
        return value
    # This object describes only the inspection scope; it does not publish an
    # autonomous parent or change the original standalone attempt/protocol.
    inspected = {'attempt_id': value['manual_id'], 'error': child.get('error'), 'stages': [
        {'stage': stage, 'attempt_id': child['attempt_id']}]}
    failure = run_failure(root, app.select_run(value['run_id'], notify=False), inspected)
    failure.update(parent_attempt_id=None, manual_id=value['manual_id'])
    value.update(failure=failure, delivery_state=failure['delivery_state'],
        state='reconciliation_required' if failure['delivery_state'] in ('unknown', 'accepted') else 'settled')
    return value
