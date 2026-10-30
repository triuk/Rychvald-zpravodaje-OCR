"""Source-bound original geometry, independent of mutable correction products."""
from .phase_preview import PreviewError, overlay, read_json
from .reading_preview import _check_frozen_run


def geometry(work, source_sha256, number, artifacts, source_page=None):
    prefix = 'phase-previews/geometry/'
    if not (work / prefix).exists():
        return {'state': 'historical_missing', 'message': 'Původní dokončená geometrie není zachována. Současná pracovní geometrie ji nenahrazuje.', 'overlays': []}
    binding = read_json(work, prefix + 'manifest.json', artifacts)
    if binding.get('schema_version') != 1 or binding.get('phase') != 'geometry' or binding['source_sha256'] != source_sha256:
        raise PreviewError('Archiv původní geometrie patří k jiné fázi nebo zdroji.')
    names = ['geometry-checkpoint.json', 'geometry-preparation.json', 'input-manifest.json',
        'reviewed-lines.json', 'pages.json', 'geometry.json', 'review.json',
        'segmented-review.json', 'segment-manifest.json']
    values = {}
    for name in names:
        values[name] = read_json(work, prefix + name, artifacts)
        if artifacts[prefix + name] != binding['files'][name]:
            raise PreviewError('Zachovaná původní geometrie byla změněna.')
    _check_frozen_run(work, binding)
    packet, checkpoint = values['geometry-preparation.json'], values['geometry-checkpoint.json']
    if (packet['identity'] != checkpoint['identity'] or
            packet['identity']['run_id'] != binding['run_id'] or
            packet['identity']['source_sha256'] != source_sha256 or
            checkpoint['preparation_sha256'] != binding['files']['geometry-preparation.json']):
        raise PreviewError('Původní geometrie neodpovídá svému dokončenému checkpointu.')
    for name in ['reviewed-lines.json', 'pages.json', 'geometry.json']:
        if packet['outputs'][name] != binding['files'][name]:
            raise PreviewError('Geometrický podklad se liší od původně prohlédnuté podoby.')
    if packet['inputs']['review']['sha256'] != binding['files']['review.json']:
        raise PreviewError('Původní geometrie patří k jiné podobě přepisu.')
    manifest = values['input-manifest.json']
    if manifest['source_sha256'] != source_sha256:
        raise PreviewError('Původní stránky geometrie patří k jinému zdroji.')
    page = next((item for item in manifest['pages'] if item['page'] == number), None)
    if page is None:
        return {'state': 'historical_missing', 'message': 'Původní geometrie této stránky není zachována.', 'overlays': []}
    if source_page and any(page.get(key) != value for key, value in source_page.items()):
        raise PreviewError('Ořez nebo rotace původní geometrie neodpovídají zdrojovému skenu.')
    size = page['raster_size']
    if not isinstance(size, list) or len(size) != 2 or any(type(value) is not int or value <= 0 for value in size):
        raise PreviewError('Původní geometrie nemá platné rozměry rastru.')
    lines = {line['id']: line for line in values['reviewed-lines.json']}
    ordered, seen = [], set()
    order = 0
    for physical_page in values['pages.json']:
        for unit in physical_page['units']:
            for entry in unit['lines']:
                line = lines[entry['id']]
                if line['id'] in seen or line['page'] != physical_page['page']:
                    raise PreviewError('Logické pořadí obsahuje duplicitní nebo cizí řádek.')
                seen.add(line['id']); order += 1
                if line['page'] != number:
                    continue
                cells = line.get('cells', [])
                characters = [overlay({'id': f"{line['id']}:{index}", 'text': cell['text'],
                    'selection_region': cell['selection_bbox']}, size, kind='geometry_character')
                    for index, cell in enumerate(cells)]
                if cells:
                    boxes = [cell['selection_bbox'] for cell in cells]
                    box = [min(b[0] for b in boxes), min(b[1] for b in boxes),
                        max(b[2] for b in boxes), max(b[3] for b in boxes)]
                    basis = 'segmented_character_selection'
                else:
                    box, basis = line['selection_region'], 'source_region_only'
                row = overlay({**line, 'ocr_bbox': box, 'selection_region': box}, size, kind='first_geometry', order=order)
                row.update(characters=characters, unit_id=unit['id'], geometry_basis=basis,
                    geometry_status=line.get('geometry_status', 'approximation_requires_character_review'))
                ordered.append(row)
    if seen != set(lines):
        raise PreviewError('Logické pořadí neobsahuje všechny zachované řádky geometrie.')
    return {'state': 'available', 'message': 'Původní pořadí a geometrie před opravami. Znakové oblasti jsou aproximace; jejich poloha nepotvrzuje identitu znaku.',
        'geometry_status': 'approximation_requires_character_review', 'snapshot_binding': binding,
        'overlays': ordered}
