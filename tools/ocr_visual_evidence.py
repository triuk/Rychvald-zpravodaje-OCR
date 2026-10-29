"""Re-derive image examination from original completed native app-server frames."""
import json
from pathlib import Path
import hashlib
if __package__:
    from .ocr_evidence_archive import resolve_bound, verify_relocated_path
else:
    from ocr_evidence_archive import resolve_bound, verify_relocated_path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_visual_turn(proof, work, images, *, activity, archive=None):
    if __package__:
        from .ocr_profiles import load_profile, effective_ai_settings
    else:
        from ocr_profiles import load_profile, effective_ai_settings
    settings = effective_ai_settings(load_profile(Path(work) / 'application/profile.json')['profile'], activity)
    protocol = resolve_bound(proof['protocol']['path'], proof['protocol']['sha256'])
    messages = [json.loads(line)['message'] for line in protocol.read_text().splitlines()]
    identifier, thread = proof['turn_id'], proof['thread_id']
    requests = [m['params'] for m in messages if m.get('method') == 'turn/start' and
        m['params']['threadId'] == thread]
    if len(requests) != 1 or any(m.get('method') == 'model/rerouted' for m in messages):
        raise ValueError('One non-rerouted original visual turn is required')
    request = requests[0]
    if request['model'] != settings['model'] or request['effort'] != settings['reasoning_effort']:
        raise ValueError('The exact frozen profile model/reasoning is required for a visual turn')
    result = [m['result'] for m in messages if isinstance(m.get('result'), dict) and
        isinstance(m['result'].get('thread'), dict) and m['result']['thread']['id'] == thread]
    if not result or result[-1].get('model') != request['model'] or result[-1].get('reasoningEffort') != request['effort']:
        raise ValueError('Native thread did not confirm the requested visual model')
    requested_images = [i['path'] for i in request['input'] if i['type'] == 'localImage']
    expected = [str((Path(work) / i['path']).resolve()) for i in images]
    actual_images = expected
    if archive is not None:
        # Requested paths stay ORIGINAL aliases from the original native frame.
        # Only pixel lookup changes, via an exact immutable snapshot SHA map.
        archive = Path(archive).resolve()
        if not archive.is_relative_to((Path(work) / 'iterations').resolve()):
            raise ValueError('Historical pixels must belong to this run iteration archive')
        records = json.loads((archive / 'snapshot.json').read_text())['artifacts']
        actual_images = []
        for path, image in zip(expected, images):
            name = str(Path(path).relative_to(Path(work).resolve()))
            record = records[name]
            if record['sha256'] != image['sha256']:
                raise ValueError('Historical image identity differs from original bound pixels')
            actual_images.append(archive / name if record['stored'] else Path(path))
    if len(requested_images) != len(expected):
        raise ValueError('Actual attached original/diagnostic images differ')
    for requested, current, image in zip(requested_images, expected, images):
        verify_relocated_path(requested, current, image['sha256'])
    if any(sha(resolve_bound(str(path), image['sha256'])) != image['sha256']
           for path, image in zip(actual_images, images)):
        raise ValueError('Actual attached original/diagnostic images differ')
    terminals = [m['params']['turn'] for m in messages if m.get('method') == 'turn/completed' and
        m['params']['turn']['id'] == identifier and m['params'].get('threadId') == thread]
    if len(terminals) != 1 or terminals[0]['status'] != 'completed':
        raise ValueError('Original visual assistant turn did not complete')
    items = [m['params']['item'] for m in messages if m.get('method') == 'item/completed' and
        m['params'].get('threadId') == thread and m['params'].get('turnId') == identifier]
    answers = [i['text'] for i in items if i['type'] == 'agentMessage' and i.get('phase') == 'final_answer']
    if not answers:
        raise ValueError('Missing original final visual assistant JSON')
    if any(i['type'] in ('commandExecution', 'fileChange') or i['type'] == 'mcpToolCall' and
           (i.get('server') != 'context_mode' or i.get('tool') != 'ctx_stats') for i in items):
        raise ValueError('Visual observations must use attached images, not output extraction or files')
    if not any(i['type'] == 'mcpToolCall' and i.get('tool') == 'ctx_stats' and
               i.get('status') == 'completed' and not i.get('error') for i in items):
        raise ValueError('Actual successful run-local context statistics required')
    hooks = {m['params']['run']['eventName'] for m in messages if m.get('method') == 'hook/completed' and
        m['params']['run'].get('status') == 'completed' and m['params']['run'].get('source') == 'sessionFlags'}
    if not {'sessionStart', 'userPromptSubmit', 'postToolUse', 'stop'} <= hooks:
        raise ValueError('Actual applicable trusted context hooks are missing')
    return json.loads(answers[-1])
