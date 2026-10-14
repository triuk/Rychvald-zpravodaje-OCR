"""Controlled source fixture executed by the installed Python in an empty root."""
from pathlib import Path
import hashlib
import io
import json
import os
import signal
import shutil
import subprocess
import sys
import time

APP = Path('/app')
BASE = Path('/work')
PROJECTS = BASE / 'projects ž'
LAUNCHER = APP / 'bin/rychvald-ocr'
assert not Path('/usr').exists() and not Path('/home').exists()
assert Path(sys.executable).resolve() == APP / 'bin/python3.14'
assert all(Path(path).is_relative_to(APP) for path in sys.path)
sys.path.insert(0, str(APP / 'tools'))
from ocr_environment import verify_environment
native = verify_environment(APP / 'environment.json')
import fitz
from PIL import Image, ImageDraw, ImageFont
import numpy
import lxml.etree
import reportlab
import fontTools
import charset_normalizer
for module in (fitz, Image, numpy, lxml.etree, reportlab, fontTools, charset_normalizer):
    assert Path(module.__file__).resolve().is_relative_to(APP), module.__file__


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def put(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return path


def get(path):
    return json.loads(Path(path).read_text())


reply_sizes = []


def cli(*arguments, expected=0):
    result = subprocess.run([str(LAUNCHER), '--root', str(PROJECTS), '--json', *map(str, arguments)], capture_output=True)
    assert result.returncode == expected, (arguments, result.returncode, result.stdout, result.stderr)
    assert len(result.stdout) <= 4096 and not result.stderr, (len(result.stdout), result.stderr)
    reply = json.loads(result.stdout)
    assert reply['protocol_version'] == 1
    reply_sizes.append(len(result.stdout))
    return reply


def workflow(work, operation, *arguments):
    result = subprocess.run([str(LAUNCHER), 'workflow', operation, '--work', str(work), *map(str, arguments)], capture_output=True, text=True)
    assert result.returncode == 0, (operation, result.stdout, result.stderr)


def source(path, pages=1, subject='fixture'):
    image = Image.new('RGB', (900, 220), 'white')
    font = ImageFont.truetype(str(APP / 'fonts/NotoSerif-Regular.ttf'), 65)
    ImageDraw.Draw(image).text((30, 70), 'OCR 11', font=font, fill='black')
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    with fitz.open() as doc:
        for _ in range(pages):
            page = doc.new_page(width=216, height=52.8)
            page.insert_image(page.rect, stream=stream.getvalue())
        doc.set_metadata({'subject': subject})
        doc.save(path)


def registered(path):
    result = cli('import', path)
    return result['project']['project_id'], PROJECTS / result['artifacts']['workspace']


def confirm(work, identifier):
    regions = put(work / 'regions.json', [{'id': 'block', 'page': 1, 'bbox': [20, 60, 500, 155], 'psm': 7}])
    workflow(work, 'regions', '--regions', regions)
    workflow(work, 'draft', '--review', work / 'review.json')
    review = get(work / 'review.json')
    assert len(review['lines']) == 1
    candidate = cli('export', identifier, expected=1)
    assert candidate['error']['code'] == 'review_invalid'
    assert not (work / 'checks/visual-review.json').exists()
    expectation = put(work / 'samples.json', [{'id': 'all', 'page': 1, 'bbox': [0, 0, 900, 220],
                                             'expected': 'OCR 11', 'expected_origin': 'Known synthetic source raster'}])
    prior, sample_hash = (work / 'review.json').read_bytes(), digest(expectation)
    line = {**review['lines'][0], 'text': 'OCR 11', 'text_status': 'visually_confirmed',
            'decision_basis': 'Controlled known source raster OCR 11 at (30,70)', 'selection_region': [20, 60, 500, 155]}
    patch = put(work / 'confirm.json', {'lines': [{'line': line}]})
    cli('patch', identifier, '--patch', patch)
    assert (work / 'review-history' / (hashlib.sha256(prior).hexdigest() + '.json')).read_bytes() == prior
    assert digest(expectation) == sample_hash
    before = (work / 'review.json').read_bytes()
    history = {p.name: p.read_bytes() for p in (work / 'review-history').glob('*')}
    invalid = put(work / 'invalid.json', {'lines': [{'line': {**line, 'selection_region': [-1, 0, 1, 1]}}]})
    cli('patch', identifier, '--patch', invalid, expected=1)
    assert (work / 'review.json').read_bytes() == before and digest(expectation) == sample_hash
    assert {p.name: p.read_bytes() for p in (work / 'review-history').glob('*')} == history
    selected = cli('query', identifier, 'transcript', '--page', '1', '--id', line['id'], '--text-bytes', '3')
    assert len(selected['rows']) == 1
    return line


def visual(work):
    proof = put(work / 'controlled-source-evidence.json', {'source_text': 'OCR 11', 'source_region': [20, 60, 500, 155],
                                                        'basis': 'Known generated source plus exact image/text/selection checks'})
    report = get(work / 'checks/visual-review.json')
    report.update(reviewer='Controlled fixture reader', pages_reviewed=[1], evidence=[proof.name, 'raster/page-1.png'], geometry_status='visually_verified')
    put(work / 'checks/visual-review.json', report)
    findings = get(work / 'checks/findings.json')
    for row in findings['items']:
        row.update(status='resolved', reason='Controlled source/geometry fixture assertions', evidence=[proof.name])
    put(work / 'checks/findings.json', findings)


def main():
    # Actual process-group interruption after completed OCR units with more pending.
    resumed_source = BASE / 'resume.pdf'
    source(resumed_source, 2, 'interruption fixture')
    resume_id, resume_work = registered(resumed_source)
    process = subprocess.Popen([str(LAUNCHER), '--root', str(PROJECTS), '--json', 'prepare', resume_id],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    completed = []
    deadline = time.monotonic() + 45
    while process.poll() is None and time.monotonic() < deadline:
        completed = []
        for path in (resume_work / 'ocr').glob('*-cache.json'):
            try:
                if get(path).get('status') == 'completed':
                    completed.append(path)
            except (ValueError, OSError):
                pass
        if completed and len(completed) < 4:
            os.killpg(process.pid, signal.SIGKILL)
            break
        time.sleep(.002)
    process.communicate(timeout=10)
    assert process.returncode == -signal.SIGKILL and completed, 'Did not interrupt pending real OCR work'
    preserved = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (resume_work / 'ocr').glob('*')
                 if p.is_file() and not p.name.endswith('-cache.json') and any(p.stem.startswith(c.name.split('-cache')[0]) for c in completed)}
    status = cli('status', resume_id)
    assert status['project']['operation_state'] == 'interrupted'
    cli('resume', resume_id)
    for path, original in preserved.items():
        assert (path.read_bytes(), path.stat().st_mtime_ns) == original
    repeated = cli('resume', resume_id)
    assert repeated['counts']['ocr_reused'] == 4 and repeated['counts']['ocr_computed'] == 0

    input_source = BASE / 'scan.pdf'
    source(input_source)
    source_hash = digest(input_source)
    identifier, work = registered(input_source)
    assert cli('import', input_source)['project']['project_id'] == identifier
    cli('prepare', identifier)
    repeated = cli('prepare', identifier)
    assert repeated['counts']['ocr_reused'] == 2 and repeated['counts']['rasters_reused'] == 1
    corrupted = work / 'ocr/page-1-psm3.txt'
    corrupted.write_text('corrupt cache')
    repaired = cli('prepare', identifier)
    assert repaired['counts']['ocr_computed'] == 1 and repaired['counts']['ocr_reused'] == 1
    assert 'corrupt cache' not in corrupted.read_text()
    # Configuration changes cannot reuse a run's old inputs.
    cli('prepare', identifier, '--dpi', '150', expected=1)
    line = confirm(work, identifier)
    first = cli('export', identifier)
    assert first['project']['validation'] == 'not_run' and first['project']['acceptance'] == 'not_recorded'
    pdf, txt = PROJECTS / first['artifacts']['output_pdf'], PROJECTS / first['artifacts']['output_txt']
    assert txt.read_bytes() == b'OCR 11\n'
    with fitz.open(input_source) as original, fitz.open(pdf) as result:
        assert original[0].rect == result[0].rect
        assert original[0].get_pixmap(dpi=150).samples == result[0].get_pixmap(dpi=150).samples
        assert result[0].get_text().strip() == 'OCR 11'
    assert digest(input_source) == source_hash
    assert get(work / 'checks/visual-review.json')['reviewer'] is None
    cli('validate', identifier, expected=1)
    visual(work)
    verified = cli('validate', identifier)
    assert verified['project']['validation'] == 'verified'
    assert verified['coverage']['ui_clipboard']['status'] == 'not_tested'
    assert verified['project']['acceptance'] == 'not_recorded'
    findings = get(work / 'checks/findings.json')
    findings['items'].append({'id': 'manual/fixture', 'status': 'open', 'reason': 'Controlled open-item case', 'evidence': ['controlled-source-evidence.json']})
    put(work / 'checks/findings.json', findings)
    assert cli('validate', identifier, expected=2)['project']['validation'] == 'ready_with_open_items'
    findings['items'].pop()
    put(work / 'checks/findings.json', findings)
    old = pdf.read_bytes(), txt.read_bytes()
    prior_visual = (work / 'checks/visual-review.json').read_bytes()
    line['decision_basis'] += '; independently rechecked'
    cli('patch', identifier, '--patch', put(work / 'recheck.json', {'lines': [{'line': line}]}))
    cli('validate', identifier, expected=1)
    second = cli('export', identifier)
    assert second['artifacts']['output_pdf'] != first['artifacts']['output_pdf']
    assert (pdf.read_bytes(), txt.read_bytes()) == old
    snapshots = list((work / 'iterations').glob('*/snapshot.json'))
    assert len(snapshots) == 1
    assert (snapshots[0].parent / 'checks/visual-review.json').read_bytes() == prior_visual
    visual(work)
    cli('validate', identifier)

    # A different PDF carrying the same basename cannot overwrite the first.
    otherdir = BASE / 'same-name'
    otherdir.mkdir()
    other = otherdir / input_source.name
    source(other, subject='distinct bytes same name')
    other_id, other_work = registered(other)
    assert other_id != identifier
    cli('prepare', other_id)
    confirm(other_work, other_id)
    other_export = cli('export', other_id)
    assert other_export['artifacts']['output_pdf'] != second['artifacts']['output_pdf']
    assert (pdf.read_bytes(), txt.read_bytes()) == old

    # A real separate writer holds OS flock; another mutation is refused.
    holder_code = "import sys; sys.path.insert(0,'/app/tools'); from ocr_projects import ProjectRegistry;\nwith ProjectRegistry(sys.argv[1]).project_lock(sys.argv[2]):\n print('locked',flush=True); sys.stdin.readline()"
    holder = subprocess.Popen([str(APP / 'lib/ld-linux-x86-64.so.2'), '--library-path', str(APP / 'lib'),
                               str(APP / 'bin/python3.14'), '-I', '-B', '-c', holder_code, str(PROJECTS), identifier],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == 'locked'
        assert cli('export', identifier, expected=1)['error']['code'] == 'project_busy'
        assert cli('patch', identifier, '--patch', work / 'recheck.json', expected=1)['error']['code'] == 'project_busy'
    finally:
        holder.communicate('done\n', timeout=10)

    # Real installed files are tampered, rejected, then restored. No project data changes.
    project_before = (work / 'project.json').read_bytes()
    for relative in ['tessdata/ces.traineddata', 'fonts/NotoSerif-Regular.ttf']:
        asset = APP / relative
        original = asset.read_bytes()
        try:
            asset.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
            result = subprocess.run([str(LAUNCHER), 'verify'], capture_output=True)
            assert result.returncode == 1 and json.loads(result.stdout)['error']['code'] == 'installation_invalid'
            assert cli('prepare', identifier, expected=1)['error']['code'] == 'environment_invalid'
            assert (work / 'project.json').read_bytes() == project_before
        finally:
            asset.write_bytes(original)

    # Missing native and wrong version profiles fail before project state writes.
    for kind in ['missing', 'version', 'inconsistent-tessdata']:
        altered = get(APP / 'environment.json')
        altered['root'] = '/app'
        if kind == 'missing':
            altered['programs']['tesseract']['path'] = '/work/no-such-tesseract'
        elif kind == 'version':
            altered['programs']['tesseract']['version'] = 'tesseract 0.0.0'
        else:
            # All declared original file hashes are valid, but do not describe
            # the files Tesseract would load from the new prefix. Must reject.
            altered['tessdata'] = '/work/unverified-tessdata'
        profile = put(BASE / (kind + '-environment.json'), altered)
        assert cli('prepare', identifier, '--environment', profile, expected=1)['error']['code'] == 'environment_invalid'
        assert (work / 'project.json').read_bytes() == project_before

    # Explicitly approved valid alternative model has the same filename but a
    # different content identity; it cannot reuse the previous run's cache.
    model_dir = BASE / 'approved-model'
    shutil.copytree(APP / 'tessdata', model_dir)
    model = model_dir / 'ces.traineddata'
    model.write_bytes((APP / 'tessdata/eng.traineddata').read_bytes())
    alternate = get(APP / 'environment.json')
    alternate.update(root='/app', build_id='controlled-alternate-model-fixture', tessdata=str(model_dir))
    alternate['models']['ces'].update(path=str(model), sha256=digest(model), source='controlled valid alternate eng model copied under ces name')
    for name, config in alternate['configs'].items():
        config['path'] = str(model_dir / 'configs' / name)
    approved = put(BASE / 'approved-environment.json', alternate)
    cli('prepare', identifier, '--environment', approved, expected=1)
    assert (work / 'project.json').read_bytes() == project_before
    new_run = cli('import', input_source, '--new-run')
    new_id = new_run['project']['project_id']
    new_work = PROJECTS / new_run['artifacts']['workspace']
    fresh = cli('prepare', new_id, '--environment', approved)
    assert fresh['counts']['ocr_reused'] == 0 and fresh['counts']['ocr_computed'] == 2
    cache = get(new_work / 'ocr/page-1-psm3-cache.json')
    assert cache['identity']['models']['ces'] == digest(model)

    # Large synthetic query-only records exercise byte limits and complete
    # pagination. They are deliberately not marked as source-confirmed OCR.
    query_source = BASE / 'large-query.pdf'
    source(query_source, subject='large response fixture')
    query_id, query_work = registered(query_source)
    crop = query_work / 'fixture-crop.png'
    crop.write_bytes((work / 'raster/page-1.png').read_bytes())
    records = [{'id': f'large-{index}', 'page': 1, 'text': 'Žluťoučký kůň ' * (40000 if index == 0 else 5),
                'source_crop': crop.name, 'text_status': 'candidate'} for index in range(40)]
    put(query_work / 'review.json', {'source_sha256': digest(query_source), 'lines': records, 'units': []})
    offset, seen = 0, []
    while True:
        response = cli('query', query_id, 'transcript', '--offset', str(offset), '--limit', '30', '--text-bytes', '512')
        seen.extend(row['id'] for row in response['rows'])
        if response.get('next_offset') is None:
            break
        assert response['next_offset'] > offset
        offset = response['next_offset']
    assert seen == [row['id'] for row in records]
    verify = subprocess.run([str(LAUNCHER), 'verify'], capture_output=True, text=True)
    assert verify.returncode == 0, verify.stdout + verify.stderr
    evidence = {'criteria': {f'A{number}': True for number in range(1, 12)},
                'host_usr_visible': False, 'host_home_visible': False, 'python': sys.executable,
                'max_response_bytes': max(reply_sizes), 'source_sha256': source_hash,
                'project_id': identifier, 'resumed_project_id': resume_id,
                'output_pdf': second['artifacts']['output_pdf'], 'output_txt': second['artifacts']['output_txt'],
                'ui_clipboard': 'not_tested', 'acceptance': 'not_recorded', 'verification': json.loads(verify.stdout)}
    put(BASE / 'package-evidence.json', evidence)
    print(json.dumps(evidence))


if __name__ == '__main__':
    main()
