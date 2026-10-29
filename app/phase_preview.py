"""Read-only, identified phase views. Rendering never runs OCR or an AI job.

Coordinates in preparation artifacts already describe the displayed, cropped and
rotated raster. Normalising by that raster's actual dimensions maps them to any
preview resolution, without applying the PDF rotation a second time.
"""
import base64
import hashlib
import json
import math
from pathlib import Path


PHASES = ('preparation', 'reading', 'geometry', 'assembly')


class PreviewError(ValueError):
    code = 'preview_invalid'


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def safe_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise PreviewError('Podklad náhledu leží mimo vybraný průchod.')
    return path


def read_json(work, relative, artifacts):
    path = safe_path(work, relative)
    content = path.read_bytes()
    artifacts[relative] = hashlib.sha256(content).hexdigest()
    return json.loads(content)


def overlay(line, size, *, kind='local_ocr_candidate', order=None):
    box = line.get('ocr_bbox', line.get('selection_region'))
    if (not isinstance(box, list) or len(box) != 4 or
            any(type(v) not in (int, float) or not math.isfinite(v) for v in box) or
            not (0 <= box[0] < box[2] <= size[0] and 0 <= box[1] < box[3] <= size[1])):
        raise PreviewError('Oblast textu neodpovídá rozměrům podkladového rastru.')
    return {'id': str(line.get('id', '')), 'text': str(line.get('text', '')),
        'normalized_bbox': [box[0] / size[0], box[1] / size[1], box[2] / size[0], box[3] / size[1]],
        'kind': kind, 'order': order}


def preparation(work, source_sha256, number, artifacts, source_page=None):
    """Return recorded candidate geometry, or an honest not-yet-available state."""
    if not (work / 'input-manifest.json').is_file():
        return {'state': 'source_only', 'message': 'Zdrojový sken. Místní OCR podklady zatím nejsou dostupné.', 'overlays': []}
    manifest = read_json(work, 'input-manifest.json', artifacts)
    if manifest.get('source_sha256') != source_sha256:
        raise PreviewError('Příprava patří k jinému zdrojovému skenu.')
    page = next((p for p in manifest['pages'] if p['page'] == number), None)
    if page is None:
        return {'state': 'source_only', 'message': 'Rastr této stránky zatím nebyl připraven.', 'overlays': []}
    if source_page and any(page.get(key) != value for key, value in source_page.items()):
        raise PreviewError('Rozměry, ořez nebo rotace podkladu neodpovídají zdrojovému skenu.')
    size = page['raster_size']
    if not isinstance(size, list) or len(size) != 2 or any(type(v) is not int or v <= 0 for v in size):
        raise PreviewError('Podklad neobsahuje platné rozměry rastru.')
    raster_name = f'raster/page-{number}.png'
    raster = safe_path(work, raster_name)
    if digest(raster) != page['raster_sha256']:
        raise PreviewError('Připravený rastr byl změněn nebo neodpovídá uloženému podkladu.')
    from PIL import Image
    with Image.open(raster) as image:
        if list(image.size) != size:
            raise PreviewError('Rozměry připraveného rastru se změnily.')
    artifacts[raster_name] = page['raster_sha256']
    # fresh-lines is the original full-page OCR inventory. Do not call the
    # reading-input operation here: that operation creates mutable AI inputs.
    lines = []
    if (work / 'fresh-lines.json').is_file():
        lines.extend(read_json(work, 'fresh-lines.json', artifacts))
    if (work / 'local-candidates.json').is_file():
        regions = read_json(work, 'local-candidates.json', artifacts)
        lines.extend(line for region in regions for line in region['lines'])
    if not lines and not any(name in artifacts for name in ('fresh-lines.json', 'local-candidates.json')):
        return {'state': 'source_only', 'message': 'Rastr je připraven. Pomocný text místního OCR zatím není dostupný.', 'overlays': []}
    lines = list({line['id']: line for line in lines}.values())
    return {'state': 'available', 'message': 'Pomocné místní OCR; nejde o potvrzený přepis.',
        'overlays': [overlay(line, size) for line in lines if line['page'] == number],
        'raster': {'size': size, 'dpi': manifest.get('dpi'), 'rotation': page.get('rotation'),
            'cropbox': page.get('cropbox'), 'rect': page.get('rect')}}


def phase_content(work, source_sha256, phase, number, artifacts, source_page=None):
    """Single extension point for preserved reading/geometry and actual output.

    Providers return state/message/overlays and may add their immutable backing
    artifact hashes. Missing historical data must never use current work files.
    """
    if phase == 'preparation':
        return preparation(work, source_sha256, number, artifacts, source_page)
    return {'state': 'historical_missing', 'message': 'Zachovaný podklad této fáze zatím není dostupný.', 'overlays': []}


def preview(root, run, payload):
    root = Path(root).resolve()
    phase, number = payload.get('phase', 'preparation'), payload.get('page', 1)
    if phase not in PHASES or type(number) is not int or number < 1:
        raise PreviewError('Vyberte platnou fázi a číslo stránky od 1.')
    edition_id = run['edition_id']
    if payload.get('edition_id', edition_id) != edition_id:
        raise PreviewError('Vybraný průchod nepatří k požadovanému projektu vydání.')
    identity = {'edition_id': edition_id, 'source_sha256': edition_id,
        'run_id': run['project']['run_id'], 'phase': phase, 'page': number}
    result = {'identity': identity, 'page_count': 0, 'image': None, 'overlays': [], 'artifacts': {}}
    source_record, work_record = run['artifacts'].get('source'), run['artifacts'].get('workspace')
    if not source_record or not source_record['available'] or not work_record or not work_record['available']:
        return {**result, 'state': 'source_missing', 'message': 'Zdrojový sken nebo pracovní adresář není dostupný.'}
    source = safe_path(root, source_record['path'])
    work = safe_path(root, work_record['path'])
    if digest(source) != edition_id:
        raise PreviewError('Zdrojový sken se změnil; náhled nesmí zobrazit cizí podklad.')
    import fitz
    with fitz.open(source) as document:
        result['page_count'] = len(document)
        if number > len(document):
            return {**result, 'state': 'page_missing', 'message': 'Tato stránka ve vybraném průchodu neexistuje.'}
        page = document[number - 1]
        source_page = {'rect': list(page.rect), 'cropbox': list(page.cropbox),
            'mediabox': list(page.mediabox), 'rotation': page.rotation}
        scale = min(120 / 72, 2000 / page.rect.width, 2400 / page.rect.height)
        image = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        content = image.tobytes('png')
        result['image'] = {'data_url': 'data:image/png;base64,' + base64.b64encode(content).decode('ascii'),
            'width': image.width, 'height': image.height, 'sha256': hashlib.sha256(content).hexdigest(),
            'kind': 'source_scan', 'page_rect': list(page.rect), 'rotation': page.rotation,
            'cropbox': list(page.cropbox)}
    try:
        result.update(phase_content(work, edition_id, phase, number, result['artifacts'], source_page))
    except (OSError, ValueError, KeyError, TypeError) as error:
        result.update(state='artifact_invalid', message=f'Podklad fáze nelze ověřit: {error}', overlays=[])
    # If a worker replaced a file during this read, do not publish mixed states.
    try:
        if any(digest(safe_path(work, name)) != expected for name, expected in result['artifacts'].items()):
            result.update(state='artifact_changed', message='Podklady se právě změnily. Obnovte náhled.', overlays=[])
    except OSError:
        result.update(state='artifact_changed', message='Podklady se právě změnily. Obnovte náhled.', overlays=[])
    if digest(source) != edition_id:
        raise PreviewError('Zdrojový sken se během načítání změnil. Obnovte náhled.')
    identity['artifact_sha256'] = hashlib.sha256(json.dumps({**identity,
        'artifacts': result['artifacts'], 'image': result['image']['sha256']}, sort_keys=True).encode()).hexdigest()
    return result
