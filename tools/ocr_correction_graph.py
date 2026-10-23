"""Exact durable output-child identities shared by native and application readers."""
import json
from pathlib import Path


def output_binding(correction, intent):
    parent = correction.get('parent_binding') or {}
    manual = correction.get('manual_binding') or {}
    return {'parent_attempt_id': parent.get('parent_attempt_id', correction['attempt_id']),
        'intent_id': parent.get('intent_id', manual.get('manual_id', correction['attempt_id'])),
        'stage': 'correction_output_review', 'correction_attempt_id': correction['attempt_id'],
        'cycle_id': intent['cycle_id'], 'cycle_index': intent['cycle_index'],
        'stage_intent_id': intent['stage_intent_id'], 'preparation_sha256': intent['preparation_sha256']}


def output_child(work, correction, cycle_id):
    """Discover exactly one child, including a crash before its parent's link."""
    work = Path(work).resolve()
    intents = [i for i in correction.get('output_intents', []) if i['cycle_id'] == cycle_id]
    links = [i for i in correction.get('children', []) if i['cycle_id'] == cycle_id and i['stage'] == 'output_review']
    if len(intents) > 1 or len(links) > 1:
        raise ValueError('Multiple output intents/children claim the same correction cycle')
    if not intents:
        if links:
            raise ValueError('Correction output child has no durable phase intent')
        return None, None
    intent = intents[0]
    identifier = intent['stage_intent_id']
    if len(identifier) != 32 or any(c not in '0123456789abcdef' for c in identifier):
        raise ValueError('Invalid correction output stage intent')
    binding = output_binding(correction, intent)
    if intent['binding'] != binding:
        raise ValueError('Original correction output binding changed')
    matches = []
    for path in (work / 'application/output-review-attempts').glob('*/attempt.json'):
        child = json.loads(path.read_text())
        if child.get('parent_binding') == binding:
            if (path.is_symlink() or not path.resolve().is_relative_to(work) or
                    path.parent.name != child['attempt_id'] or child['run_id'] != correction['run_id'] or
                    child['root'] != correction['root']):
                raise ValueError('Correction output child belongs to another run/registry')
            matches.append(child)
    if len(matches) > 1:
        raise ValueError('Multiple output children claim the same durable correction intent')
    claims = {i['attempt_id'] for i in links}
    if intent.get('attempt_id'):
        claims.add(intent['attempt_id'])
    if len(claims) > 1 or (claims and (not matches or matches[0]['attempt_id'] not in claims)):
        raise ValueError('Original correction output child cannot be replaced')
    return intent, matches[0] if matches else None
