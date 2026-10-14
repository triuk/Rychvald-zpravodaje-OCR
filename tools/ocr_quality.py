"""Content-neutral validation, provenance and atomic review edits (stdlib only)."""
from pathlib import Path
from datetime import datetime, timezone
import collections
import copy
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def bindings(**paths):
    return {name: {'path': str(Path(path).resolve()), 'sha256': sha(path)}
            for name, path in paths.items()}


def check_bindings(records):
    for name, record in records.items():
        path = Path(record['path'])
        if not path.is_file() or sha(path) != record['sha256']:
            raise ValueError(f'Stale or missing input: {name} ({path})')


def work_file(work, name):
    path = (Path(work) / name).resolve()
    if not path.is_relative_to(Path(work).resolve()):
        raise ValueError(f'Artifact must be inside work directory: {name}')
    if not path.is_file():
        raise ValueError(f'Missing artifact: {name}')
    return path


def bbox(box, page, manifest):
    if not isinstance(page, int) or not 1 <= page <= len(manifest['pages']):
        raise ValueError(f'Invalid page: {page}')
    if (not isinstance(box, list) or len(box) != 4 or
            not all(isinstance(v, (int, float)) and math.isfinite(v) for v in box)):
        raise ValueError(f'Invalid rectangle: {box}')
    width, height = manifest['pages'][page - 1]['raster_size']
    if not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height):
        raise ValueError(f'Rectangle outside page {page}: {box}')


def unique(records, label):
    ids = [r['id'] for r in records]
    if len(ids) != len(set(ids)) or any(not isinstance(i, str) or not i for i in ids):
        raise ValueError(f'Duplicate or empty {label} ID')
    return {r['id']: r for r in records}


def validate_review(work, review):
    work = Path(work)
    manifest = load(work / 'input-manifest.json')
    if review['source_sha256'] != manifest['source_sha256']:
        raise ValueError('Review belongs to another source')
    candidates = unique([line for r in load(work / 'local-candidates.json')
                         for line in r['lines']], 'candidate')
    lines = unique(review['lines'], 'line')
    unique(review['units'], 'unit')
    references = set()
    for key, line in lines.items():
        bbox(line['selection_region'], line['page'], manifest)
        work_file(work, line['source_crop'])
        if not line.get('text') or not line.get('decision_basis'):
            raise ValueError(f'{key}: text and decision_basis required')
        if line['text_status'] not in ('visually_confirmed', 'partially_unresolved'):
            raise ValueError(f'{key}: still a candidate')
        uncertain = '[NEČITELNÉ]' in line['text']
        if uncertain != (line['text_status'] == 'partially_unresolved'):
            raise ValueError(f'{key}: marker/text_status mismatch')
        candidate = line.get('candidate_id', key)
        if candidate is not None:
            if candidate not in candidates or candidates[candidate]['page'] != line['page']:
                raise ValueError(f'{key}: missing or wrong-page candidate {candidate}')
            references.add(candidate)
        if 'fields' in line:
            if '\t'.join(f['text'] for f in line['fields']) != line['text']:
                raise ValueError(f'{key}: fields/text mismatch')
            for field in line['fields']:
                bbox(field['bbox'], line['page'], manifest)
                overrides = list(field.get('token_boxes', {}).values()) + list(field.get('character_boxes', {}).values())
                overrides += [box for pieces in field.get('piece_boxes', {}).values() for box in pieces.values()]
                for box in overrides:
                    bbox(box, line['page'], manifest)
    dropped = unique(review.get('dropped_candidates', []), 'dropped candidate')
    if set(candidates) - references != set(dropped) or any(not r.get('reason') for r in dropped.values()):
        raise ValueError('Account for each candidate as reviewed or dropped with a reason')
    used = []
    for unit in review['units']:
        if unit['tag'] not in ('H1', 'H2', 'P') or not unit.get('article') or not unit['line_ids']:
            raise ValueError(f"{unit['id']}: invalid logical unit")
        for key in unit['line_ids']:
            if key not in lines or lines[key]['page'] != unit['page']:
                raise ValueError(f"{unit['id']}: missing or wrong-page line {key}")
        used.extend(unit['line_ids'])
        for key in unit['line_ids'][:-1]:
            join = lines[key].get('join_after')
            if join not in ('space', 'typesetting_hyphen', 'literal_hyphen', 'none'):
                raise ValueError(f'{key}: explicit join_after required')
            if join in ('typesetting_hyphen', 'literal_hyphen') and not lines[key]['text'].endswith('-'):
                raise ValueError(f'{key}: hyphen join without a final hyphen')
    if collections.Counter(used) != collections.Counter({key: 1 for key in lines}):
        raise ValueError('Each reviewed line must occur in exactly one unit')
    unresolved = review.get('unresolved', [])
    unique(unresolved, 'unresolved')
    counts = collections.Counter()
    for register in ('unresolved', 'publisher_errors', 'risk_register'):
        if register == 'risk_register':
            unique(review.get(register, []), register)
        for record in review.get(register, []):
            key = record['line']
            if key not in lines:
                raise ValueError(f'{register}: missing line {key}')
            if 'page' in record and record['page'] != lines[key]['page']:
                raise ValueError(f'{register}: wrong page for {key}')
            if record.get('source_crop'):
                work_file(work, record['source_crop'])
            if 'bbox' in record:
                bbox(record['bbox'], lines[key]['page'], manifest)
            if register == 'unresolved':
                if not all(record.get(k) for k in ('reason', 'status', 'context', 'source_crop', 'bbox')) or not isinstance(record.get('candidates'), list):
                    raise ValueError(f'{key}: incomplete unresolved record')
                counts[key] += 1
            elif register == 'publisher_errors':
                if not all(record.get(k) for k in ('printed', 'explanation', 'status')) or record['printed'] not in lines[key]['text']:
                    raise ValueError(f'{key}: stale or incomplete publisher error')
            elif register == 'risk_register':
                if (not all(record.get(k) for k in ('value', 'status', 'source_crop')) or
                        ' '.join(record['value'].split()) not in ' '.join(lines[key]['text'].split())):
                    raise ValueError(f'{key}: stale or incomplete risk value')
    for key, line in lines.items():
        if line['text'].count('[NEČITELNÉ]') != counts[key]:
            raise ValueError(f'{key}: unresolved marker/register mismatch')
    return {'lines': len(lines), 'units': len(review['units']), 'unresolved': len(unresolved)}


def apply_line_patch(review, key, patch, allow_new=False):
    if set(patch) - {'line', 'unresolved', 'publisher_errors', 'risk_register'}:
        raise ValueError('Patch accepts line and related registers only')
    lines = unique(review['lines'], 'line')
    if (key not in lines and not allow_new) or patch['line']['id'] != key:
        raise ValueError(f'Missing or mismatched line: {key}')
    review['lines'] = [patch['line'] if r['id'] == key else r for r in review['lines']]
    if key not in lines:
        review['lines'].append(patch['line'])
    for register in ('unresolved', 'publisher_errors', 'risk_register'):
        related = [r for r in review.get(register, []) if r['line'] == key]
        if related and register not in patch:
            raise ValueError(f'Patch must explicitly replace related {register} (use [] to clear)')
        if register in patch:
            if any(r['line'] != key for r in patch[register]):
                raise ValueError(f'Patch {register} references another line')
            review[register] = [r for r in review.get(register, []) if r['line'] != key] + patch[register]


def save_review(a, review, changed):
    summary = validate_review(a.work, changed)
    backup = Path(a.work) / 'review-history' / (sha(a.review) + '.json')
    if not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=backup.parent, prefix='.' + backup.name)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(Path(a.review).read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, backup)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    dump(a.review, changed)
    print(json.dumps({'review': str(a.review), 'previous': str(backup), 'validation': summary}, ensure_ascii=False))


def update_line(a):
    review = load(a.review)
    changed = copy.deepcopy(review)
    apply_line_patch(changed, a.id, load(a.patch))
    save_review(a, review, changed)


def patched_review(review, patch):
    """Apply the existing structured batch schema without mutating its inputs."""
    if not patch or set(patch) - {'lines', 'drop_lines', 'units', 'dropped_candidates'}:
        raise ValueError('Batch accepts lines, drop_lines, units and dropped_candidates')
    changed = copy.deepcopy(review)
    edits = patch.get('lines', [])
    unique([edit['line'] for edit in edits], 'line patch')
    for edit in edits:
        apply_line_patch(changed, edit['line']['id'], edit, allow_new=True)
    drops = patch.get('drop_lines', [])
    if len(set(drops)) != len(drops) or not set(drops) <= set(unique(changed['lines'], 'line')):
        raise ValueError('Missing or duplicate dropped line')
    for register in ('unresolved', 'publisher_errors', 'risk_register'):
        if any(row['line'] in drops for row in changed.get(register, [])):
            raise ValueError(f'Explicitly clear related {register} in line patches before dropping a line')
    changed['lines'] = [line for line in changed['lines'] if line['id'] not in drops]
    for name in ('units', 'dropped_candidates'):
        if name in patch:
            changed[name] = patch[name]
    return changed


def update_review(a):
    """Apply a batch once; archive and write only after whole-review validation."""
    review = load(a.review)
    save_review(a, review, patched_review(review, load(a.patch)))


def validate_clipboard_expectations(work, expectations):
    manifest = load(Path(work) / 'input-manifest.json')
    if expectations['source_sha256'] != manifest['source_sha256']:
        raise ValueError('Clipboard expectations belong to another source')
    if not expectations.get('expected_origin'):
        raise ValueError('Record clipboard expectation origin')
    cases = unique(expectations['cases'], 'clipboard expectation')
    required = set(expectations.get('required_cases', []))
    if not required <= set(cases):
        raise ValueError('Missing required clipboard expectation')
    for key, case in cases.items():
        if case.get('result') == 'not_applicable':
            if key in required or not case.get('reason'):
                raise ValueError(f'Invalid not_applicable clipboard expectation: {key}')
            continue
        if not case.get('selection'):
            raise ValueError(f'Missing clipboard selection: {key}')
        path = work_file(work, case['expected_file'])
        if sha(path) != case['expected_sha256']:
            raise ValueError(f'Modified clipboard expectation: {key}')
        path.read_bytes().decode('utf-8')
    return expectations


def clipboard_expectations(a):
    """Write exact UTF-8 bytes into an immutable version before PDF export."""
    work = Path(a.work)
    source_hash = load(work / 'input-manifest.json')['source_sha256']
    spec = load(a.cases)
    if set(spec) - {'expected_origin', 'required_cases', 'cases'} or not spec.get('expected_origin'):
        raise ValueError('Use expected_origin, optional required_cases and cases')
    cases = unique(spec['cases'], 'clipboard case')
    if not cases:
        raise ValueError('Provide at least one clipboard case')
    required = set(spec.get('required_cases', []))
    if not required <= set(cases):
        raise ValueError('Missing required clipboard case')
    version = hashlib.sha256(json.dumps(spec, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
    records, files = [], []
    for key, case in cases.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]+', key):
            raise ValueError(f'Use a simple clipboard case ID: {key}')
        if set(case) - {'id', 'selection', 'expected', 'result', 'reason'} or case.get('result', 'not_tested') not in ('not_tested', 'not_applicable'):
            raise ValueError(f'Clipboard specification must contain expectations, not executed results: {key}')
        if case.get('result') == 'not_applicable':
            if key in required or not case.get('reason'):
                raise ValueError(f'Invalid not_applicable clipboard case: {key}')
            records.append({'id': key, 'result': 'not_applicable', 'reason': case['reason']})
            continue
        if not case.get('selection') or not isinstance(case.get('expected'), str):
            raise ValueError(f'Provide selection and exact expected text: {key}')
        relative = f'checks/manual-copy/expectations/{version}/{key}.txt'
        path = (work / relative).resolve()
        if not path.is_relative_to(work.resolve()):
            raise ValueError('Clipboard expectation must stay inside work')
        content = case['expected'].encode('utf-8')
        if path.exists() and path.read_bytes() != content:
            raise ValueError(f'Modified immutable clipboard expectation: {key}')
        files.append((path, content))
        records.append({'id': key, 'selection': case['selection'], 'expected_file': relative,
                        'expected_sha256': hashlib.sha256(content).hexdigest(), 'result': 'not_tested',
                        'actual_clipboard_file': None})
    # Check the whole specification before writing any artifacts.
    for path, content in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(content)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    result = {'source_sha256': source_hash, 'version': version,
              'expected_origin': spec['expected_origin'], 'required_cases': sorted(required), 'cases': records}
    validate_clipboard_expectations(work, result)
    dump(work / 'clipboard-expectations.json', result)
    print(f'Clipboard expectations: {work / "clipboard-expectations.json"}; {len(records)} cases; version {version[:12]}')


def clipboard_validation(work, manifest, errors, open_finding):
    """Optional UI coverage; an executed test still needs frozen expectations."""
    result = {'optional': True, 'status': 'not_tested', 'tested_cases': []}
    frozen = load(manifest['inputs']['export_inputs']['path']).get('clipboard_expectations')
    if frozen is not None:
        validate_clipboard_expectations(work, frozen)
    path = Path(work) / 'checks/manual-copy/status.json'
    if not path.exists():
        return result
    manual = load(path)
    if manual.get('pdf_sha256') != manifest['pdf_sha256'] or manual.get('source_sha256') != manifest['source_sha256']:
        raise ValueError('Clipboard report belongs to another export')
    cases = unique(manual.get('cases', []), 'clipboard case')
    required = set(manual.get('required_cases', []))
    if frozen:
        required.update(frozen.get('required_cases', []))
    if not required <= set(cases):
        errors.append('clipboard_case_coverage')
    expected = unique(frozen['cases'], 'frozen clipboard case') if frozen else {}
    for key, case in cases.items():
        state = case['result']
        if state == 'not_applicable':
            if key in required or not case.get('reason'):
                errors.append('clipboard_not_applicable/' + key)
            continue
        if state == 'not_tested':
            continue
        if state not in ('pass', 'fail') or not all(manual.get(k) for k in ('reader', 'version', 'os')):
            errors.append('clipboard_record/' + key)
            continue
        golden = expected.get(key)
        if not golden or golden.get('result') == 'not_applicable':
            errors.append('clipboard_unfrozen/' + key)
            continue
        if manual.get('expected_origin') != frozen['expected_origin'] or any(
                case.get(k) != golden.get(k) for k in ('selection', 'expected_file', 'expected_sha256')):
            errors.append('clipboard_changed_expectation/' + key)
            continue
        expected_path = work_file(work, golden['expected_file'])
        actual_path = work_file(work, case['actual_clipboard_file'])
        actual_path.read_bytes().decode('utf-8')
        result['tested_cases'].append(key)
        if actual_path.read_bytes() != expected_path.read_bytes():
            if state == 'fail':
                open_finding('clipboard/' + key)
            else:
                errors.append('clipboard_mismatch/' + key)
        elif state != 'pass':
            errors.append('clipboard_result/' + key)
    if result['tested_cases']:
        result['status'] = 'tested'
    return result


def report_templates(a):
    """Prepare metadata and finding IDs; never assert a visual review or a reason."""
    work = Path(a.work)
    manifest = load(work / 'output-manifest.json')
    identity = {key: manifest[key] for key in ('source_sha256', 'pdf_sha256')}
    technical = load(work / 'checks/technical.json')
    samples = load(work / 'checks/geometry-samples.json')
    check_bindings(manifest['inputs'])
    check_bindings(technical['inputs'])
    check_bindings(samples['inputs'])
    if technical['source_sha256'] != identity['source_sha256'] or technical['output_sha256'] != identity['pdf_sha256'] or samples['inputs']['pdf']['sha256'] != identity['pdf_sha256']:
        raise ValueError('Run checks and samples on the current PDF before preparing reports')
    targets = {}
    for name in ('checks/visual-review.json', 'checks/findings.json', 'checks/manual-copy/status.json'):
        path = work / name
        if not path.exists():
            continue
        existing = load(path)
        current = all(existing.get(key) == value for key, value in identity.items())
        if not current and not a.reset:
            raise ValueError(f'Report belongs to another export: {name}; use --reset after export archived the previous run')
        targets[name] = existing if current and not a.reset else None
    visual = targets.get('checks/visual-review.json') or {
        **identity, 'review_sha256': sha(manifest['inputs']['review']['path']),
        'reviewer': None, 'pages_reviewed': [], 'evidence': [],
        'geometry_status': 'approximation_requires_character_review'}
    findings = targets.get('checks/findings.json') or {**identity, 'items': []}
    registered = unique(findings['items'], 'finding')

    def pending(key, evidence, **details):
        if key not in registered:
            row = {'id': key, 'status': 'open', 'reason': None, 'evidence': evidence, **details}
            findings['items'].append(row)
            registered[key] = row

    for page in technical['pages']:
        for extractor in ('mupdf', 'poppler'):
            if page.get(extractor + '_literal_equal') is not True and not (extractor == 'poppler' and page.get('poppler_terminal_lf_omitted') is True):
                number = page['page']
                pending(f'literal/{number}/{extractor}',
                        ['checks/technical.json', f'checks/expected-page-{number}.txt', f'checks/{extractor}-page-{number}.txt'],
                        page=number, extractor=extractor)
    for sample in samples['samples']:
        for extractor in ('mupdf', 'poppler'):
            if sample.get(extractor + '_characters_pass') is not True:
                evidence = ['checks/geometry-samples.json']
                crop = f"checks/{sample['id']}-source.png"
                if (work / crop).is_file():
                    evidence.append(crop)
                pending(f"sample/{sample['id']}/{extractor}", evidence, page=sample['page'],
                        bbox=sample['bbox'], expected=sample['expected'], actual=sample[extractor + '_literal'])
    if visual['geometry_status'] != 'visually_verified':
        pending('geometry/approximation', ['checks/visual-review.json'])
    unsupported = work / 'checks/unsupported-cells.json'
    if unsupported.exists():
        for index, cell in enumerate(load(unsupported)):
            pending(f"geometry/unsupported/{cell['line']}/{index}", ['checks/unsupported-cells.json'],
                    diagnostic_status=cell.get('status'), **{key: value for key, value in cell.items() if key != 'status'})
    anomalies = work / 'checks/geometry-anomalies.json'
    if anomalies.exists():
        for row in load(anomalies):
            pending('geometry/anomaly/' + row['line'], ['checks/geometry-anomalies.json'], **row)
    outputs = {'checks/visual-review.json': visual, 'checks/findings.json': findings}
    frozen = load(work / 'export-inputs.json').get('clipboard_expectations')
    if frozen is not None:
        manual = targets.get('checks/manual-copy/status.json') or {
            **frozen, **identity, 'reader': None, 'version': None, 'os': None}
        outputs['checks/manual-copy/status.json'] = manual
    elif (work / 'checks/manual-copy/status.json').exists() and a.reset:
        outputs['checks/manual-copy/status.json'] = {**identity, 'cases': [], 'status': 'not_tested'}
    for name, value in outputs.items():
        path = work / name
        if path.exists() and a.reset:
            dump(work / 'checks/report-history' / (sha(path) + '.json'), load(path))
        dump(path, value)
    expected_pages = {page['page'] for page in load(work / 'input-manifest.json')['pages']}
    todo = {'source_sha256': identity['source_sha256'], 'pdf_sha256': identity['pdf_sha256'],
            'visual_review_required': not visual.get('reviewer') or set(visual.get('pages_reviewed', [])) != expected_pages or not visual.get('evidence'),
            'finding_reasons_required': [key for key, row in registered.items() if row.get('status') == 'open' and not row.get('reason')]}
    dump(work / 'checks/report-todo.json', todo)
    print(f'Report templates: {work / "checks"}; finding reasons to fill: {len(todo["finding_reasons_required"])}; visual review must be recorded by the reader')


def article_text(pages):
    articles = collections.OrderedDict()
    for page in pages:
        for unit in page['units']:
            articles.setdefault(unit['article'], []).append(unit)
    parts = []
    for units in articles.values():
        text, previous = '', False
        for unit in units:
            table = 'table_fields' in unit
            if text:
                text += '\n' if table and previous else '\n\n'
            text += '\t'.join(unit['table_fields']) if table else unit['pdf_text']
            previous = table
        parts.append(text)
    return '\n\n\n'.join(parts).rstrip() + '\n'


def unit_text(unit, lines):
    text = ''
    for index, key in enumerate(unit['line_ids']):
        line = lines[key]
        text += ' '.join(line['text'].split())
        if index < len(unit['line_ids']) - 1:
            join = line['join_after']
            if join == 'space':
                text += ' '
            elif join == 'typesetting_hyphen':
                text = text[:-1]
    return text


REQUIRED_PAGE_CHECKS = (
    'geometry_preserved', 'source_content_streams_preserved', 'decoded_images_identical',
    'mupdf_render_identical', 'poppler_render_identical', 'mupdf_characters_equal',
    'poppler_characters_equal', 'invisible', 'no_ActualText', 'no_Tz',
)


def technical_failures(report):
    failures = []
    if report.get('qpdf_returncode') != 0:
        failures.append('qpdf')
    if report.get('source_identity_preserved') is not True:
        failures.append('source_identity')
    if report.get('txt_literal_equal_common_transcript') is not True:
        failures.append('txt_literal')
    if report.get('txt_characters_equal_common_transcript') is not True:
        failures.append('txt_characters')
    if not report.get('pages'):
        failures.append('missing_pages')
    for row in report.get('pages', []):
        for key in REQUIRED_PAGE_CHECKS + tuple(k for k in ('reviewer_render_identical', 'reviewer_characters_equal') if k in row):
            if row.get(key) is not True:
                failures.append(f"page/{row['page']}/{key}")
        if row.get('BT') != row.get('units') or row.get('tags') != row.get('units'):
            failures.append(f"page/{row['page']}/structure")
    fonts = [f for f in report.get('fonts', []) if 'OCRCells' in f['name']]
    if not fonts or any(f['embedded'] is not True for f in fonts):
        failures.append('cell_fonts')
    return failures


def snapshot(work):
    """Archive the previous export and its frozen decisions before replacement."""
    work = Path(work).resolve()
    manifest = load(work / 'output-manifest.json')
    for name in ('pdf', 'txt'):
        if sha(manifest[name]) != manifest[name + '_sha256']:
            raise ValueError(f'Cannot snapshot modified {name}')
    target = work / 'iterations' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + manifest['pdf_sha256'][:12])
    target.mkdir(parents=True)
    records = {}
    paths = [work / 'output-manifest.json', work / 'exported-pages.json', work / 'exported-review.json',
             work / 'export-inputs.json', work / 'input-manifest.json', Path(manifest['pdf']), Path(manifest['txt'])]
    for directory in ('checks', 'construction'):
        paths.extend(p for p in (work / directory).rglob('*') if p.is_file())
    # Large OCR/raster inputs stay in the work directory, with their identity recorded.
    for directory in ('raster', 'ocr', 'crops'):
        for path in (work / directory).rglob('*'):
            if path.is_file():
                records[str(path.relative_to(work))] = {'sha256': sha(path), 'stored': False}
    for path in paths:
        if not path.is_file():
            raise ValueError(f'Cannot snapshot missing artifact: {path}')
        relative = path.relative_to(work) if path.is_relative_to(work) else Path('external') / path.name
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        records[str(relative)] = {'sha256': sha(destination), 'stored': True}
    dump(target / 'snapshot.json', {'source_sha256': manifest['source_sha256'],
                                  'pdf_sha256': manifest['pdf_sha256'], 'artifacts': records})
    return target


def doctor(a):
    results = {}
    for module, package in [('fitz', 'PyMuPDF'), ('PIL', 'Pillow'), ('numpy', 'numpy'),
                            ('lxml.etree', 'lxml'), ('reportlab', 'reportlab'), ('fontTools', 'fonttools')]:
        try:
            importlib.import_module(module)
            results[package] = {'ok': True, 'version': importlib.metadata.version(package)}
        except (ImportError, importlib.metadata.PackageNotFoundError) as error:
            results[package] = {'ok': False, 'reason': str(error)}
    for program in ('tesseract', 'qpdf', 'pdftotext', 'pdftoppm', 'pdffonts'):
        executable = shutil.which(program)
        result = {'ok': bool(executable), 'path': executable}
        if executable:
            p = subprocess.run([executable, '--version' if program in ('tesseract', 'qpdf') else '-v'], capture_output=True, text=True)
            result.update(ok=p.returncode == 0, version=(p.stdout + p.stderr).splitlines()[0])
        results[program] = result
    if results['tesseract']['ok']:
        p = subprocess.run(['tesseract', '--list-langs'], capture_output=True, text=True)
        available = (p.stdout + p.stderr).splitlines()
        results['language'] = {'ok': p.returncode == 0 and all(lang in available for lang in a.language.split('+')), 'requested': a.language}
    else:
        results['language'] = {'ok': False, 'requested': a.language}
    for name, font in [('segmentation_font', a.font), ('sheet_font', a.sheet_font)]:
        try:
            from PIL import ImageFont
            ImageFont.truetype(font, 18)
            results[name] = {'ok': True, 'path': font, 'sha256': sha(font)}
        except (ImportError, OSError) as error:
            results[name] = {'ok': False, 'path': font, 'reason': str(error)}
    report = {'python': sys.version, 'executable': sys.executable, 'checks': results,
              'ok': all(r['ok'] for r in results.values()), 'reader_ui': 'check availability separately'}
    if a.work:
        dump(Path(a.work) / 'checks/environment.json', report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['ok'] else 1


def validate_run(a):
    work = Path(a.work).resolve()
    errors, opened, manifest = [], [], {}
    clipboard = {'optional': True, 'status': 'not_tested', 'tested_cases': []}
    reviewer_coverage = {'optional': True, 'status': 'not_tested', 'tested_pages': []}
    framing = []
    try:
        manifest = load(work / 'output-manifest.json')
        for name in ('source', 'pdf', 'txt'):
            if sha(manifest[name]) != manifest[name + '_sha256']:
                raise ValueError(f'Modified {name}')
        check_bindings(manifest['inputs'])
        review_path = Path(manifest['inputs']['review']['path'])
        review = load(review_path)
        validate_review(work, review)
        technical = load(work / 'checks/technical.json')
        check_bindings(technical['inputs'])
        if technical['output_sha256'] != manifest['pdf_sha256'] or technical['source_sha256'] != manifest['source_sha256']:
            raise ValueError('Technical report belongs to another export')
        for name in ('source', 'pdf', 'txt'):
            if technical['inputs'][name]['sha256'] != manifest[name + '_sha256']:
                raise ValueError(f'Technical report uses another {name}')
        if technical['inputs']['pages']['sha256'] != manifest['inputs']['exported_pages']['sha256']:
            raise ValueError('Technical report uses other exported pages')
        exported = load(manifest['inputs']['exported_pages']['path'])
        lines = unique(review['lines'], 'line')
        for page in exported:
            units = [u for u in review['units'] if u['page'] == page['page']]
            if [u['id'] for u in units] != [u['id'] for u in page['units']]:
                raise ValueError('Exported logical order differs from review')
            for original, actual in zip(units, page['units']):
                if unit_text(original, lines) != actual['pdf_text'] or any(original.get(k) != actual.get(k) for k in ('tag', 'article', 'table_fields')):
                    raise ValueError(f"Export differs from reviewed unit: {original['id']}")
        errors.extend(technical_failures(technical))
        expected_pages = set(range(1, len(load(work / 'input-manifest.json')['pages']) + 1))
        if len(technical['pages']) != len(expected_pages) or {r['page'] for r in technical['pages']} != expected_pages or {p['page'] for p in exported} != expected_pages:
            errors.append('technical_page_coverage')
        unit_counts = {p['page']: len(p['units']) for p in exported}
        for row in technical['pages']:
            if row['units'] != unit_counts.get(row['page']):
                errors.append(f"page/{row['page']}/unit_coverage")
        sample_report = load(work / 'checks/geometry-samples.json')
        check_bindings(sample_report['inputs'])
        if sample_report['inputs']['pdf']['sha256'] != manifest['pdf_sha256']:
            raise ValueError('Sample report belongs to another export')
        if sample_report['inputs']['samples']['sha256'] != manifest['inputs']['samples']['sha256']:
            raise ValueError('Sample expectations differ from the frozen export inputs')
        expected = unique(load(sample_report['inputs']['samples']['path']), 'sample')
        actual = unique(sample_report['samples'], 'sample result')
        if not expected or set(expected) != set(actual):
            errors.append('sample_coverage')
        findings_path = work / 'checks/findings.json'
        findings = load(findings_path) if findings_path.exists() else {'items': []}
        if findings['items'] and (findings.get('pdf_sha256') != manifest['pdf_sha256'] or findings.get('source_sha256') != manifest['source_sha256']):
            raise ValueError('Findings belong to another export')
        registered = unique(findings['items'], 'finding')
        def open_finding(key):
            finding = registered.get(key)
            if not finding or finding.get('status') != 'open' or not finding.get('reason') or not finding.get('evidence'):
                errors.append('unrecorded/' + key)
                return
            for path in finding['evidence']:
                work_file(work, path)
            opened.append({'id': key, 'reason': finding['reason']})
        for row in technical['pages']:
            for extractor in ('mupdf', 'poppler'):
                if row.get(extractor + '_literal_equal') is not True:
                    if extractor == 'poppler' and row.get('poppler_terminal_lf_omitted') is True:
                        page = next(page for page in exported if page['page'] == row['page'])
                        expected_text = '\n\n'.join(unit['pdf_text'] for unit in page['units']) + '\n'
                        expected_path = f"checks/expected-page-{row['page']}.txt"
                        actual_path = f"checks/poppler-page-{row['page']}.txt"
                        if (not expected_text.endswith('\n\n') and
                                work_file(work, expected_path).read_bytes() == expected_text.encode('utf-8') and
                                work_file(work, actual_path).read_bytes() == expected_text[:-1].encode('utf-8')):
                            framing.append({'page': row['page'], 'extractor': 'poppler',
                                            'kind': 'single_terminal_lf_omitted', 'evidence': [expected_path, actual_path]})
                        else:
                            errors.append(f"changed_literal_framing/{row['page']}/poppler")
                    else:
                        open_finding(f"literal/{row['page']}/{extractor}")
        for key, row in actual.items():
            if row['output_sha256'] != manifest['pdf_sha256']:
                errors.append('stale_sample/' + key)
            if any(row.get(k) != expected[key].get(k) for k in ('page', 'bbox', 'expected', 'expected_origin')):
                errors.append('changed_sample/' + key)
            for extractor in ('mupdf', 'poppler'):
                if row.get(extractor + '_characters_pass') is not True:
                    open_finding(f'sample/{key}/{extractor}')
        visual = load(work / 'checks/visual-review.json')
        if (visual['source_sha256'] != manifest['source_sha256'] or visual['pdf_sha256'] != manifest['pdf_sha256'] or visual['review_sha256'] != sha(review_path)):
            raise ValueError('Visual report belongs to another review/export')
        if set(visual['pages_reviewed']) != expected_pages or not visual.get('evidence') or not visual.get('reviewer'):
            errors.append('visual_page_coverage')
        for path in visual.get('evidence', []):
            work_file(work, path)
        if visual.get('geometry_status') != 'visually_verified':
            open_finding('geometry/approximation')
        for entry in review.get('unresolved', []):
            opened.append({'id': 'unresolved/' + entry['id'], 'reason': entry['reason']})
        tested = [row['page'] for row in technical['pages']
                  if 'reviewer_render_identical' in row and 'reviewer_characters_equal' in row]
        if any(('reviewer_render_identical' in row) != ('reviewer_characters_equal' in row)
               for row in technical['pages']):
            errors.append('reviewer_incomplete_check')
        reviewer_coverage.update(status='tested' if len(tested) == len(expected_pages) else 'partial' if tested else 'not_tested',
                                 tested_pages=tested)
        clipboard = clipboard_validation(work, manifest, errors, open_finding)
        # Keep additional open findings visible even when no automatic check produces them.
        for key, finding in registered.items():
            for path in finding.get('evidence', []):
                work_file(work, path)
            if finding.get('status') == 'open' and key not in {r['id'] for r in opened}:
                open_finding(key)
    except (OSError, ValueError, KeyError, TypeError) as error:
        errors.append(str(error))
    status = 'failed' if errors else 'ready_with_open_items' if opened else 'verified'
    report_inputs = {name: work / name for name in ('output-manifest.json', 'checks/technical.json',
                     'checks/geometry-samples.json', 'checks/visual-review.json', 'checks/manual-copy/status.json',
                     'checks/findings.json') if (work / name).is_file()}
    report = {'source_sha256': manifest.get('source_sha256'), 'pdf_sha256': manifest.get('pdf_sha256'),
              'txt_sha256': manifest.get('txt_sha256'), 'inputs': bindings(**report_inputs),
              'status': status, 'errors': errors, 'open_items': opened,
               'ui_clipboard': clipboard,
              'reviewer_integration': reviewer_coverage,
              'extractor_framing': framing,
              'acceptance': 'separate_user_decision'}
    dump(work / 'checks/run-validation.json', report)
    summary = [f'OCR validation: {status}', '',
               f'Source SHA-256: {manifest.get("source_sha256")}',
               f'PDF SHA-256: {manifest.get("pdf_sha256")}',
               f'Optional UI clipboard: {clipboard["status"]}; tested cases: {len(clipboard["tested_cases"])}',
               '', f'Errors: {len(errors)}; open items: {len(opened)}']
    summary.extend('- ' + error for error in errors)
    summary.extend('- ' + item['id'] + ': ' + item['reason'] for item in opened)
    summary.append('\nVerified scope is the recorded technical, source-reading and selection checks; UI compatibility is covered only by executed UI cases.\n')
    (work / 'checks/run-summary.md').write_text('\n'.join(summary), encoding='utf-8')
    print(f'{status}; errors {len(errors)}; open items {len(opened)}; UI clipboard {clipboard["status"]}; {work / "checks/run-validation.json"}')
    return 1 if errors else 2 if opened else 0
