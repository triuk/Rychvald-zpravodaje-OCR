"""Resolve only preserved, source-bound first reading; never use current review."""
import hashlib
import json
from pathlib import Path

from .phase_preview import PreviewError, digest, overlay, read_json, safe_path


def _check_frozen_run(work, binding):
    for key, name in [('profile_sha256', 'application/profile.json'),
                      ('run_manifest_sha256', 'application/run.json')]:
        if binding.get(key) is not None and digest(safe_path(work, name)) != binding[key]:
            raise PreviewError('Původní přepis patří k jinému zmrazenému profilu nebo průchodu.')


def _archive(work, artifacts):
    prefix = 'phase-previews/reading/'
    binding = read_json(work, prefix + 'manifest.json', artifacts)
    if binding.get('schema_version') != 1 or binding.get('phase') != 'reading':
        raise PreviewError('Archiv původního přepisu nemá platnou identitu.')
    values = {}
    for name in ['review.json', 'publication.json', 'input.json', 'source-manifest.json', 'proposal.json']:
        relative = prefix + name
        values[name] = read_json(work, relative, artifacts)
        if artifacts[relative] != binding['files'][name]:
            raise PreviewError('Zachovaný podklad prvního přepisu se změnil.')
    publication, proposal = values['publication.json'], values['proposal.json']
    if (publication['review_sha256'] != binding['files']['review.json'] or
            publication['proposal_sha256'] != binding['files']['proposal.json'] or
            publication['coverage'] != proposal['coverage'] or proposal['review'] != values['review.json']):
        raise PreviewError('Zachovaný přepis neodpovídá dokladu svého prvního zveřejnění.')
    return binding, values['input.json'], values['review.json'], values['source-manifest.json']


def _legacy(work, artifacts):
    """Use the earliest completed original proposal and its actual protocol.

    Old projects already retained these immutable originals. Reading them does
    not backfill files, re-run the model, or borrow the corrected review.json.
    """
    attempts = []
    for path in sorted((work / 'application/reading-attempts').glob('*/attempt.json')):
        content = safe_path(work, path.relative_to(work)).read_bytes()
        value = json.loads(content)
        if value.get('state') == 'completed' and value.get('reading_complete') is True:
            attempts.append((value.get('ended_at', ''), path.parent, value, hashlib.sha256(content).hexdigest()))
    if not attempts:
        return None
    _, directory, value, attempt_sha = min(attempts, key=lambda row: (row[0], row[1].name))
    artifacts[str((directory / 'attempt.json').relative_to(work))] = attempt_sha
    packet = value['source']
    relative = str((directory / 'proposal.json').relative_to(work))
    proposal = read_json(work, relative, artifacts)
    if digest(directory / 'proposal.json') != value['proposal_sha256']:
        raise PreviewError('Původní návrh přepisu se změnil.')
    review = proposal['review']
    review_sha = hashlib.sha256((json.dumps(review, ensure_ascii=False) + '\n').encode()).hexdigest()
    if review_sha != value['review_sha256']:
        raise PreviewError('Původní návrh neodpovídá zveřejněnému prvnímu přepisu.')
    protocol_name = str((directory / 'protocol.jsonl').relative_to(work))
    protocol = safe_path(work, protocol_name)
    artifacts[protocol_name] = digest(protocol)
    frames = [json.loads(line)['message'] for line in protocol.read_text().splitlines()]
    turns = value['turns']
    if len(turns) != 2 or value.get('reroutes'):
        raise PreviewError('Původní dokončení přepisu nelze jednoznačně doložit.')
    if value.get('reused_source'):
        reused = value['reused_source']
        original_id = Path(reused['attempt']['path']).parent.name
        if len(original_id) != 32 or any(character not in '0123456789abcdef' for character in original_id):
            raise PreviewError('Původní zdrojový tah nemá platnou identitu pokusu.')
        original_prefix = f'application/reading-attempts/{original_id}/'
        original = read_json(work, original_prefix + 'attempt.json', artifacts)
        old_protocol = safe_path(work, original_prefix + 'protocol.jsonl')
        artifacts[original_prefix + 'protocol.jsonl'] = digest(old_protocol)
        if (artifacts[original_prefix + 'attempt.json'] != reused['attempt']['sha256'] or
                artifacts[original_prefix + 'protocol.jsonl'] != reused['protocol']['sha256'] or
                original['source'] != packet or original['turns'][0] != turns[0]):
            raise PreviewError('Zachovaný zdrojový tah se změnil.')
        prefix = []
        for line in old_protocol.read_text().splitlines():
            frame = json.loads(line)['message']; prefix.append(frame)
            if frame.get('method') == 'turn/completed' and frame['params']['turn']['id'] == turns[0]['turn_id']:
                break
        frames = prefix + frames
    for turn in turns:
        terminal = any(frame.get('method') == 'turn/completed' and
            frame['params']['turn']['id'] == turn['turn_id'] and
            frame['params']['turn']['status'] == 'completed' for frame in frames)
        answer = any(frame.get('method') == 'item/completed' and
            frame['params'].get('turnId') == turn['turn_id'] and
            frame['params']['item'].get('phase') == 'final_answer' and
            frame['params']['item'].get('text') == turn['answer'] for frame in frames)
        if not terminal or not answer:
            raise PreviewError('Úplná původní odpověď nemá doložené dokončení.')
    if json.loads(turns[-1]['answer']) != proposal:
        raise PreviewError('Návrh se liší od původní dokončené odpovědi.')
    binding = {'run_id': value['run_id'], 'source_sha256': packet['source_sha256'],
        'profile_sha256': packet.get('profile_sha256'),
        'run_manifest_sha256': packet.get('run_manifest_sha256'),
        'attempt_id': value['attempt_id'], 'origin': 'preserved_original_completed_proposal'}
    return binding, packet, review, None


def reading(work, source_sha256, number, artifacts, source_page=None):
    if (work / 'phase-previews/reading').exists():
        preserved = _archive(work, artifacts)
    else:
        preserved = _legacy(work, artifacts)
    if preserved is None:
        return {'state': 'historical_missing', 'message': 'Původní dokončený přepis není zachován. Současný pracovní přepis jej nenahrazuje.', 'overlays': []}
    binding, packet, review, manifest = preserved
    if binding['source_sha256'] != source_sha256 or packet['source_sha256'] != source_sha256 or review['source_sha256'] != source_sha256:
        raise PreviewError('Původní přepis patří k jinému zdrojovému skenu.')
    _check_frozen_run(work, binding)
    if manifest is not None:
        if manifest['source_sha256'] != source_sha256:
            raise PreviewError('Původní geometrie stránek patří k jinému zdroji.')
        page = next((p for p in manifest['pages'] if p['page'] == number), None)
        if page is None or source_page and any(page.get(key) != value for key, value in source_page.items()):
            raise PreviewError('Ořez nebo rotace původní stránky neodpovídají skenu.')
    page = next((p for p in packet['pages'] if p['page'] == number), None)
    if page is None:
        return {'state': 'historical_missing', 'message': 'Původní přepis této stránky není zachován.', 'overlays': []}
    size = page['raster_size']
    if not isinstance(size, list) or len(size) != 2 or any(type(v) is not int or v <= 0 for v in size):
        raise PreviewError('Původní přepis nemá doložené rozměry rastru.')
    return {'state': 'available', 'message': 'První dokončený přepis před pozdějšími automatickými opravami.',
        'snapshot_binding': binding,
        'overlays': [overlay(line, size, kind='first_reading') for line in review['lines'] if line['page'] == number]}
