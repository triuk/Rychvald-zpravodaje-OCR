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


def update_line(a):
    review = load(a.review)
    patch = load(a.patch)
    if set(patch) - {'line', 'unresolved', 'publisher_errors', 'risk_register'}:
        raise ValueError('Patch accepts line and related registers only')
    lines = unique(review['lines'], 'line')
    if a.id not in lines or patch['line']['id'] != a.id:
        raise ValueError(f'Missing or mismatched line: {a.id}')
    changed = copy.deepcopy(review)
    changed['lines'] = [patch['line'] if r['id'] == a.id else r for r in review['lines']]
    for register in ('unresolved', 'publisher_errors', 'risk_register'):
        related = [r for r in review.get(register, []) if r['line'] == a.id]
        if related and register not in patch:
            raise ValueError(f'Patch must explicitly replace related {register} (use [] to clear)')
        if register in patch:
            if any(r['line'] != a.id for r in patch[register]):
                raise ValueError(f'Patch {register} references another line')
            changed[register] = [r for r in review.get(register, []) if r['line'] != a.id] + patch[register]
    summary = validate_review(a.work, changed)
    backup = Path(a.work) / 'review-history' / (sha(a.review) + '.json')
    if not backup.exists():
        dump(backup, review)
    dump(a.review, changed)
    print(json.dumps({'line': patch['line'], 'validation': summary}, ensure_ascii=False))


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
        if not any('reviewer_render_identical' in row for row in technical['pages']):
            opened.append({'id': 'reviewer/not_tested', 'reason': 'Optional reviewer was not tested'})
        manual = load(work / 'checks/manual-copy/status.json')
        if manual.get('pdf_sha256') != manifest['pdf_sha256'] or manual.get('source_sha256') != manifest['source_sha256']:
            raise ValueError('Clipboard report belongs to another export')
        cases = unique(manual['cases'], 'clipboard case')
        required = {'first-page', 'multiline-paragraph', 'two-adjacent-paragraphs'}
        required.update(manual.get('required_cases', []))
        if not required <= set(cases):
            errors.append('clipboard_case_coverage')
        for key, case in cases.items():
            expected_path = work_file(work, case['expected_file'])
            result = case['result']
            if not case.get('selection') or not manual.get('expected_origin'):
                errors.append('clipboard_expectation/' + key)
            if result == 'not_applicable' and key not in required and case.get('reason'):
                continue
            if result == 'not_tested' and case.get('reason', manual.get('reason')):
                opened.append({'id': 'clipboard/' + key, 'reason': case.get('reason', manual.get('reason'))})
                continue
            if result not in ('pass', 'fail') or not all(manual.get(k) for k in ('reader', 'version', 'os')) or not case.get('selection'):
                errors.append('clipboard_record/' + key)
                continue
            actual_path = work_file(work, case['actual_clipboard_file'])
            if actual_path.read_bytes() != expected_path.read_bytes():
                if result == 'fail':
                    open_finding('clipboard/' + key)
                else:
                    errors.append('clipboard_mismatch/' + key)
            elif result != 'pass':
                errors.append('clipboard_result/' + key)
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
              'acceptance': 'separate_user_decision'}
    dump(work / 'checks/run-validation.json', report)
    print(json.dumps(report, ensure_ascii=False))
    return 1 if errors else 2 if opened else 0
