"""Native project export and truthful validation at public process/artifact seams."""
from pathlib import Path
import hashlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'tools/ocr_projects.py'


class ProjectExportTests(unittest.TestCase):
    def setUp(self):
        import fitz
        from PIL import Image, ImageDraw, ImageFont
        self.temporary = tempfile.TemporaryDirectory(prefix='OCR export ')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / 'projects with spaces'
        self.source = self.directory / 'scan.pdf'
        image = Image.new('RGB', (900, 220), 'white')
        ImageDraw.Draw(image).text((30, 70), 'OCR 11',
                                  font=ImageFont.truetype('/usr/share/fonts/noto/NotoSerif-Regular.ttf', 65), fill='black')
        stream = io.BytesIO()
        image.save(stream, format='PNG')
        with fitz.open() as document:
            page = document.new_page(width=216, height=52.8)
            page.insert_image(page.rect, stream=stream.getvalue())
            document.save(self.source)
        imported = self.command('import', self.source)
        self.identifier = imported['project']['project_id']
        self.work = self.root / imported['artifacts']['workspace']
        self.command('prepare', self.identifier)
        self.put('regions.json', [{'id': 'block', 'page': 1, 'bbox': [20, 60, 500, 155], 'psm': 7}])
        self.workflow('regions', '--regions', self.work / 'regions.json')
        self.workflow('draft', '--review', self.work / 'review.json')
        review = self.get('review.json')
        line = {**review['lines'][0], 'text': 'OCR 11', 'text_status': 'visually_confirmed',
                'decision_basis': 'Controlled synthetic source raster; literal OCR 11 at source box',
                'selection_region': [20, 60, 500, 155]}
        patch = self.put('confirm.json', {'lines': [{'line': line}]})
        self.command('patch', self.identifier, '--patch', patch)
        self.put('samples.json', [{'id': 'all', 'page': 1, 'bbox': [0, 0, 900, 220],
                                   'expected': 'OCR 11', 'expected_origin': 'Controlled synthetic source raster OCR 11'}])

    def command(self, *arguments, expected=0):
        result = subprocess.run([sys.executable, str(CLI), '--root', str(self.root),
                                 '--json', *map(str, arguments)], capture_output=True)
        self.assertEqual(result.returncode, expected, result.stdout.decode() + result.stderr.decode())
        self.assertLessEqual(len(result.stdout), 4096)
        return json.loads(result.stdout.decode('utf-8'))

    def workflow(self, operation, *arguments):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/ocr_workflow.py'), operation,
                                 '--work', str(self.work), *map(str, arguments)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def put(self, name, value):
        path = self.work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return path

    def get(self, name):
        return json.loads((self.work / name).read_text())

    def record_controlled_visual_evidence(self):
        """Fixture-only explicit source reading, never a production confirmation."""
        proof = self.put('controlled-source-evidence.json', {
            'reader': 'Controlled synthetic fixture reader', 'pages': [1],
            'source_text': 'OCR 11', 'source_region': [20, 60, 500, 155],
            'basis': 'Known rendered source text plus native exact image/text/selection assertions',
            'source_sha256': hashlib.sha256(self.source.read_bytes()).hexdigest()})
        visual = self.get('checks/visual-review.json')
        visual.update(reviewer='Controlled synthetic fixture reader', pages_reviewed=[1],
                      evidence=[proof.name, 'raster/page-1.png'], geometry_status='visually_verified')
        self.put('checks/visual-review.json', visual)
        findings = self.get('checks/findings.json')
        for finding in findings['items']:
            finding.update(status='resolved', reason='Controlled known synthetic source and selection assertions',
                           evidence=[proof.name])
        self.put('checks/findings.json', findings)

    def test_export_uses_common_transcript_preserves_source_and_creates_unconfirmed_reports(self):
        import fitz
        source_bytes = self.source.read_bytes()
        result = self.command('export', self.identifier)
        self.assertEqual(result['operation'], 'export')
        self.assertEqual(result['project']['phase'], 'exported')
        self.assertEqual(result['project']['validation'], 'not_run')
        self.assertEqual(result['project']['acceptance'], 'not_recorded')
        pdf, txt = self.root / result['artifacts']['output_pdf'], self.root / result['artifacts']['output_txt']
        self.assertEqual(pdf.parent, self.root / 'outputs')
        self.assertEqual(txt.read_bytes(), b'OCR 11\n')
        with fitz.open(self.source) as source, fitz.open(pdf) as output:
            self.assertEqual(source[0].rect, output[0].rect)
            self.assertEqual(source[0].get_pixmap(dpi=150).samples, output[0].get_pixmap(dpi=150).samples)
            self.assertEqual(output[0].get_text().strip(), 'OCR 11')
        manifest = self.get('output-manifest.json')
        self.assertEqual(manifest['project_id'], self.identifier)
        self.assertEqual(manifest['source_sha256'], hashlib.sha256(source_bytes).hexdigest())
        self.assertEqual(manifest['review_sha256'], hashlib.sha256((self.work / 'review.json').read_bytes()).hexdigest())
        self.assertEqual(self.source.read_bytes(), source_bytes)
        visual = self.get('checks/visual-review.json')
        self.assertIsNone(visual['reviewer'])
        self.assertEqual(visual['pages_reviewed'], [])
        self.assertFalse(any('reviewer_render_identical' in page for page in self.get('checks/technical.json')['pages']))

    def test_template_fails_then_explicit_first_reading_verifies_without_optional_ui(self):
        self.command('export', self.identifier)
        unconfirmed = self.command('validate', self.identifier, expected=1)
        self.assertEqual(unconfirmed['status'], 'completed')
        self.assertEqual(unconfirmed['project']['operation_state'], 'completed')
        self.assertEqual(unconfirmed['project']['validation'], 'failed')
        self.assertGreater(unconfirmed['counts']['errors'], 0)
        self.record_controlled_visual_evidence()
        verified = self.command('validate', self.identifier)
        self.assertEqual(verified['project']['validation'], 'verified')
        self.assertEqual(verified['project']['acceptance'], 'not_recorded')
        self.assertEqual(verified['coverage']['ui_clipboard']['status'], 'not_tested')
        self.assertEqual(verified['coverage']['reviewer']['status'], 'not_tested')
        report = self.get('checks/run-validation.json')
        self.assertEqual(report['status'], 'verified')
        self.assertEqual(report['reviewer_integration']['tested_pages'], [])
        self.assertEqual(report['open_items'], [])
        self.assertEqual(report['extractor_framing'][0]['kind'], 'single_terminal_lf_omitted')
        self.assertEqual(verified['coverage']['extractor_framing']['differences'], 1)
        self.assertFalse(self.get('checks/technical.json')['pages'][0]['poppler_literal_equal'])
        self.assertFalse(any('reviewer_render_identical' in page for page in self.get('checks/technical.json')['pages']))

    def test_only_exact_one_terminal_lf_omission_is_allowed_as_extractor_framing(self):
        self.command('export', self.identifier)
        self.record_controlled_visual_evidence()
        self.command('validate', self.identifier)
        literal = self.work / 'checks/poppler-page-1.txt'
        self.assertEqual(literal.read_bytes(), b'OCR 11')
        for bad in [b'OCR  11', b'OCR\n11', b'OCR\n\n11', b'OCR 11\n\n', b'OCR 11X', b'OCR 1']:
            with self.subTest(raw=bad):
                literal.write_bytes(bad)
                result = self.command('validate', self.identifier, expected=1)
                self.assertEqual(result['project']['validation'], 'failed')
                self.assertIn('changed_literal_framing/1/poppler', self.get('checks/run-validation.json')['errors'])
        literal.write_bytes(b'OCR 11')
        self.command('validate', self.identifier)

    def test_new_iteration_keeps_previous_flat_outputs_frozen_reports_and_review_history(self):
        first = self.command('export', self.identifier)
        self.record_controlled_visual_evidence()
        self.command('validate', self.identifier)
        old_pdf, old_txt = self.root / first['artifacts']['output_pdf'], self.root / first['artifacts']['output_txt']
        project = self.get('project.json')
        project['project']['acceptance'] = 'accepted'
        self.put('project.json', project)
        pdf_bytes, txt_bytes = old_pdf.read_bytes(), old_txt.read_bytes()
        visual_bytes = (self.work / 'checks/visual-review.json').read_bytes()
        history_before = {path.name: path.read_bytes() for path in (self.work / 'review-history').glob('*')}
        line = self.get('review.json')['lines'][0]
        line['decision_basis'] += '; independently rechecked controlled source'
        patch = self.put('recheck.json', {'lines': [{'line': line}]})
        self.command('patch', self.identifier, '--patch', patch)
        stale = self.command('validate', self.identifier, expected=1)
        self.assertEqual(stale['project']['validation'], 'failed')
        second = self.command('export', self.identifier)
        self.assertNotEqual(second['artifacts']['output_pdf'], first['artifacts']['output_pdf'])
        self.assertNotEqual(second['project']['iteration_id'], first['project']['iteration_id'])
        self.assertEqual(old_pdf.read_bytes(), pdf_bytes)
        self.assertEqual(old_txt.read_bytes(), txt_bytes)
        snapshots = list((self.work / 'iterations').glob('*/snapshot.json'))
        self.assertEqual(len(snapshots), 1)
        archived = snapshots[0].parent
        self.assertEqual((archived / 'checks/visual-review.json').read_bytes(), visual_bytes)
        self.assertEqual(json.loads((archived / 'project.json').read_text())['project']['acceptance'], 'accepted')
        self.assertEqual((archived / 'external' / old_pdf.name).read_bytes(), pdf_bytes)
        snapshot = json.loads(snapshots[0].read_text())
        self.assertEqual(snapshot['source_sha256'], hashlib.sha256(self.source.read_bytes()).hexdigest())
        for name, before in history_before.items():
            self.assertEqual((self.work / 'review-history' / name).read_bytes(), before)
        self.assertIsNone(self.get('checks/visual-review.json')['reviewer'])
        self.assertEqual(second['project']['validation'], 'not_run')
        self.assertEqual(second['project']['acceptance'], 'not_recorded')
        self.assertNotIn('coverage', second)
        self.command('validate', self.identifier, expected=1)

    def test_failed_export_keeps_previous_outputs_and_reports_truthful_failed_operation(self):
        first = self.command('export', self.identifier)
        self.record_controlled_visual_evidence()
        self.command('validate', self.identifier)
        old_pdf, old_txt = self.root / first['artifacts']['output_pdf'], self.root / first['artifacts']['output_txt']
        before = old_pdf.read_bytes(), old_txt.read_bytes()
        log = self.work / 'export-process.log'
        log.unlink()
        log.mkdir()
        result = self.command('export', self.identifier, expected=1)
        self.assertEqual(result['error']['code'], 'export_failed')
        self.assertEqual(result['project']['phase'], 'export_failed')
        self.assertEqual(result['project']['operation_state'], 'failed')
        self.assertEqual(result['project']['validation'], 'not_run')
        self.assertEqual((old_pdf.read_bytes(), old_txt.read_bytes()), before)
        self.assertTrue((self.root / result['artifacts']['export_error']).is_file())

    def test_candidate_review_and_missing_independent_expectations_are_not_exported(self):
        review = self.get('review.json')
        confirmed = json.loads(json.dumps(review))
        review['lines'][0]['text_status'] = 'candidate'
        self.put('review.json', review)
        candidate = self.command('export', self.identifier, expected=1)
        self.assertEqual(candidate['error']['code'], 'review_invalid')
        self.assertFalse((self.work / 'checks/visual-review.json').exists())
        self.assertEqual(list((self.root / 'outputs').glob('*.pdf')), [])
        self.put('review.json', confirmed)
        (self.work / 'samples.json').unlink()
        self.command('export', self.identifier, expected=1)
        self.assertEqual(list((self.root / 'outputs').glob('*.pdf')), [])
        self.assertFalse((self.work / 'samples.json').exists())

    def test_explicit_open_findings_return_two_and_actual_technical_or_reviewer_failure_returns_one(self):
        self.command('export', self.identifier)
        self.record_controlled_visual_evidence()
        self.command('validate', self.identifier)
        findings = self.get('checks/findings.json')
        findings['items'].append({'id': 'manual/uncertain-number', 'status': 'open',
                                  'reason': 'Controlled fixture open-item case',
                                  'evidence': ['controlled-source-evidence.json']})
        self.put('checks/findings.json', findings)
        opened = self.command('validate', self.identifier, expected=2)
        self.assertEqual(opened['status'], 'completed')
        self.assertEqual(opened['project']['validation'], 'ready_with_open_items')
        self.assertEqual(opened['counts']['errors'], 0)
        self.assertEqual(opened['counts']['open_items'], 1)
        technical = self.get('checks/technical.json')
        technical['qpdf_returncode'] = 1
        self.put('checks/technical.json', technical)
        failure = self.command('validate', self.identifier, expected=1)
        self.assertEqual(failure['project']['validation'], 'failed')
        self.assertIn('qpdf', self.get('checks/run-validation.json')['errors'])
        technical['qpdf_returncode'] = 0
        technical['pages'][0].update(reviewer_render_identical=False, reviewer_characters_equal=True)
        self.put('checks/technical.json', technical)
        self.command('validate', self.identifier, expected=1)
        self.assertIn('page/1/reviewer_render_identical', self.get('checks/run-validation.json')['errors'])
        self.assertEqual(self.get('checks/run-validation.json')['reviewer_integration']['tested_pages'], [1])

    def test_project_writer_lock_protects_export_and_validate(self):
        before = (self.work / 'review.json').read_bytes()
        code = '''
import sys
sys.path.insert(0, sys.argv[1])
from ocr_projects import ProjectRegistry
with ProjectRegistry(sys.argv[2]).project_lock(sys.argv[3]):
    print('locked', flush=True)
    sys.stdin.readline()
'''
        holder = subprocess.Popen([sys.executable, '-S', '-c', code, str(ROOT / 'tools'),
                                   str(self.root), self.identifier], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), 'locked')
            for operation in ['export', 'validate']:
                rejected = self.command(operation, self.identifier, expected=1)
                self.assertEqual(rejected['error']['code'], 'project_busy')
                self.assertEqual(rejected['project']['project_id'], self.identifier)
            self.assertEqual((self.work / 'review.json').read_bytes(), before)
            self.assertFalse((self.work / 'checks/run-validation.json').exists())
            self.assertEqual(list((self.root / 'outputs').glob('*.pdf')), [])
        finally:
            holder.communicate('done\n', timeout=10)

    def test_same_source_filename_different_pdf_content_has_disjoint_flat_outputs(self):
        import fitz
        first = self.command('export', self.identifier)
        first_pdf = self.root / first['artifacts']['output_pdf']
        first_bytes = first_pdf.read_bytes()
        directory = self.directory / 'another source directory'
        directory.mkdir()
        second_source = directory / self.source.name
        with fitz.open(self.source) as document:
            document.set_metadata({'subject': 'Distinct source bytes with the same controlled raster'})
            document.save(second_source)
        imported = self.command('import', second_source)
        self.assertNotEqual(imported['project']['source_sha256'], first['project']['source_sha256'])
        self.identifier = imported['project']['project_id']
        self.work = self.root / imported['artifacts']['workspace']
        self.command('prepare', self.identifier)
        regions = self.put('regions.json', [{'id': 'block', 'page': 1, 'bbox': [20, 60, 500, 155], 'psm': 7}])
        self.workflow('regions', '--regions', regions)
        self.workflow('draft', '--review', self.work / 'review.json')
        line = self.get('review.json')['lines'][0]
        line.update(text='OCR 11', text_status='visually_confirmed', decision_basis='Controlled second source raster',
                    selection_region=[20, 60, 500, 155])
        patch = self.put('confirm.json', {'lines': [{'line': line}]})
        self.command('patch', self.identifier, '--patch', patch)
        self.put('samples.json', [{'id': 'all', 'page': 1, 'bbox': [0, 0, 900, 220],
                                   'expected': 'OCR 11', 'expected_origin': 'Controlled second source raster'}])
        second = self.command('export', self.identifier)
        self.assertNotEqual(second['artifacts']['output_pdf'], first['artifacts']['output_pdf'])
        self.assertEqual(first_pdf.read_bytes(), first_bytes)
        self.assertEqual((self.root / second['artifacts']['output_txt']).read_bytes(), b'OCR 11\n')

    def test_abrupt_export_kill_cannot_leave_a_verified_running_or_partial_iteration(self):
        first = self.command('export', self.identifier)
        self.record_controlled_visual_evidence()
        self.command('validate', self.identifier)
        old_pdf = self.root / first['artifacts']['output_pdf']
        old_bytes = old_pdf.read_bytes()
        process = subprocess.Popen([sys.executable, str(CLI), '--root', str(self.root),
                                    '--json', 'export', self.identifier], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        try:
            deadline = time.monotonic() + 15
            while process.poll() is None and time.monotonic() < deadline:
                if self.get('project.json')['project']['phase'] == 'exporting':
                    break
                time.sleep(.001)
            self.assertEqual(self.get('project.json')['project']['phase'], 'exporting')
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=10)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
        result = self.command('status', self.identifier)
        self.assertEqual(result['project']['phase'], 'export_interrupted')
        self.assertEqual(result['project']['operation_state'], 'interrupted')
        self.assertEqual(result['project']['validation'], 'not_run')
        self.assertEqual(old_pdf.read_bytes(), old_bytes)

    def test_validation_requires_correct_project_run_iteration_and_output_path_binding(self):
        self.command('export', self.identifier)
        self.record_controlled_visual_evidence()
        self.command('validate', self.identifier)
        manifest = self.get('output-manifest.json')
        for key in ['project_id', 'run_id', 'iteration_id']:
            with self.subTest(identity=key):
                bad = {**manifest, key: 'foreign identity'}
                self.put('output-manifest.json', bad)
                result = self.command('validate', self.identifier, expected=1)
                self.assertEqual(result['project']['validation'], 'failed')
                self.assertIn('project_output_binding', self.get('checks/run-validation.json')['errors'])
        self.put('output-manifest.json', manifest)
        self.command('validate', self.identifier)


if __name__ == '__main__':
    unittest.main()
