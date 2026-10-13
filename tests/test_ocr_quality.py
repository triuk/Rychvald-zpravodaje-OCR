"""Regression cases use synthetic data, never a previous issue's transcript."""
from pathlib import Path
from types import SimpleNamespace
import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import ocr_quality as quality


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.source = self.work / 'source.pdf'
        self.pdf = self.work / 'output.pdf'
        self.txt = self.work / 'output.txt'
        self.source.write_bytes(b'synthetic source')
        self.pdf.write_bytes(b'synthetic output')
        self.txt.write_bytes(b'ABC\n')
        (self.work / 'crop.png').write_bytes(b'proof')
        self.review = {
            'source_sha256': quality.sha(self.source),
            'lines': [{'id': 'line', 'candidate_id': 'candidate', 'page': 1, 'text': 'ABC',
                       'selection_region': [0, 0, 100, 20], 'source_crop': 'crop.png',
                       'decision_basis': 'synthetic fixture', 'text_status': 'visually_confirmed'}],
            'units': [{'id': 'unit', 'article': 'article', 'page': 1, 'tag': 'P', 'line_ids': ['line']}],
            'dropped_candidates': [], 'unresolved': [], 'publisher_errors': [], 'risk_register': [],
        }
        self.put('input-manifest.json', {'source_sha256': quality.sha(self.source), 'pages': [{'page': 1, 'raster_size': [100, 100]}]})
        self.put('local-candidates.json', [{'lines': [{'id': 'candidate', 'page': 1}]}])
        self.put('review.json', self.review)
        self.put('exported-pages.json', [{'page': 1, 'units': [{'id': 'unit', 'article': 'article', 'page': 1, 'tag': 'P', 'pdf_text': 'ABC'}]}])
        self.manifest = {'source': str(self.source), 'source_sha256': quality.sha(self.source),
                         'pdf': str(self.pdf), 'pdf_sha256': quality.sha(self.pdf),
                         'txt': str(self.txt), 'txt_sha256': quality.sha(self.txt),
                         'inputs': quality.bindings(review=self.work / 'review.json', exported_pages=self.work / 'exported-pages.json')}
        self.put('output-manifest.json', self.manifest)
        self.technical = {
            'source_sha256': quality.sha(self.source), 'output_sha256': quality.sha(self.pdf),
            'inputs': quality.bindings(source=self.source, pdf=self.pdf, txt=self.txt, pages=self.work / 'exported-pages.json'),
            'qpdf_returncode': 0, 'source_identity_preserved': True,
            'txt_literal_equal_common_transcript': True, 'txt_characters_equal_common_transcript': True,
            'fonts': [{'name': 'OCRCells0', 'embedded': True}],
            'pages': [{'page': 1, **dict.fromkeys(quality.REQUIRED_PAGE_CHECKS, True),
                       'mupdf_literal_equal': True, 'poppler_literal_equal': True,
                       'BT': 1, 'tags': 1, 'units': 1,
                       'reviewer_render_identical': True, 'reviewer_characters_equal': True}],
        }
        self.put('checks/technical.json', self.technical)
        self.samples = [{'id': 'sample', 'page': 1, 'bbox': [0, 0, 100, 20], 'expected': 'ABC', 'expected_origin': 'synthetic source'}]
        self.put('samples.json', self.samples)
        self.sample_report = {'inputs': quality.bindings(pdf=self.pdf, samples=self.work / 'samples.json', manifest=self.work / 'input-manifest.json'),
                              'samples': [{**self.samples[0], 'output_sha256': quality.sha(self.pdf), 'mupdf_characters_pass': True, 'poppler_characters_pass': True}]}
        self.put('checks/geometry-samples.json', self.sample_report)
        self.put('visual.md', {'synthetic': True})
        self.put('checks/visual-review.json', {'source_sha256': quality.sha(self.source), 'pdf_sha256': quality.sha(self.pdf),
                 'review_sha256': quality.sha(self.work / 'review.json'), 'reviewer': 'synthetic fixture', 'pages_reviewed': [1], 'evidence': ['visual.md'], 'geometry_status': 'visually_verified'})
        (self.work / 'expected.txt').write_bytes(b'ABC\n')
        (self.work / 'actual.txt').write_bytes(b'ABC\n')
        self.manual = {'source_sha256': quality.sha(self.source), 'pdf_sha256': quality.sha(self.pdf),
                       'reader': 'synthetic', 'version': '1', 'os': 'test', 'expected_origin': 'fixture',
                       'cases': [{'id': name, 'selection': name, 'expected_file': 'expected.txt', 'actual_clipboard_file': 'actual.txt', 'result': 'pass'}
                                 for name in ('first-page', 'multiline-paragraph', 'two-adjacent-paragraphs')]}
        for case in self.manual['cases']:
            case['expected_sha256'] = quality.sha(self.work / 'expected.txt')
        self.frozen_clipboard = {'source_sha256': quality.sha(self.source), 'expected_origin': 'fixture',
                                 'required_cases': [], 'cases': copy.deepcopy(self.manual['cases'])}
        for case in self.frozen_clipboard['cases']:
            case.update(result='not_tested', actual_clipboard_file=None)
        self.put('export-inputs.json', {'clipboard_expectations': self.frozen_clipboard})
        self.manifest['inputs'].update(quality.bindings(samples=self.work / 'samples.json',
                                                       export_inputs=self.work / 'export-inputs.json',
                                                       clipboard_expected=self.work / 'expected.txt'))
        self.put('output-manifest.json', self.manifest)
        self.put('checks/manual-copy/status.json', self.manual)

    def put(self, name, value):
        quality.dump(self.work / name, value)

    def validate(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = quality.validate_run(SimpleNamespace(work=self.work))
        return code, quality.load(self.work / 'checks/run-validation.json')

    def finding(self, key):
        self.put('checks/findings.json', {'source_sha256': quality.sha(self.source), 'pdf_sha256': quality.sha(self.pdf),
                 'items': [{'id': key, 'status': 'open', 'reason': 'synthetic open finding', 'evidence': ['crop.png']}]})

    def test_verified_run(self):
        self.assertEqual(self.validate()[0], 0)

    def test_modified_source_fails(self):
        self.source.write_bytes(b'changed')
        self.assertEqual(self.validate()[0], 1)

    def test_qpdf_failure_cannot_be_waived(self):
        self.technical['qpdf_returncode'] = 2
        self.put('checks/technical.json', self.technical)
        self.finding('qpdf')
        self.assertEqual(self.validate()[0], 1)

    def test_changed_image_cannot_be_waived(self):
        self.technical['pages'][0]['decoded_images_identical'] = False
        self.put('checks/technical.json', self.technical)
        self.finding('page/1/decoded_images_identical')
        self.assertEqual(self.validate()[0], 1)

    def test_stale_expected_samples_fail(self):
        self.put('samples.json', [{**self.samples[0], 'expected': 'changed'}])
        self.assertEqual(self.validate()[0], 1)

    def test_unrecorded_selection_failure_fails(self):
        self.sample_report['samples'][0]['mupdf_characters_pass'] = False
        self.put('checks/geometry-samples.json', self.sample_report)
        self.assertEqual(self.validate()[0], 1)
        self.finding('sample/sample/mupdf')
        code, report = self.validate()
        self.assertEqual(code, 2)
        self.assertEqual(report['open_items'][0]['id'], 'sample/sample/mupdf')

    def test_whitespace_diff_needs_individual_finding(self):
        self.technical['pages'][0]['poppler_literal_equal'] = False
        self.put('checks/technical.json', self.technical)
        self.assertEqual(self.validate()[0], 1)
        self.finding('literal/1/poppler')
        self.assertEqual(self.validate()[0], 2)

    def test_clipboard_preserves_whitespace(self):
        (self.work / 'actual.txt').write_bytes(b'ABC\r\n')
        self.assertEqual(self.validate()[0], 1)

    def test_unavailable_ui_is_optional(self):
        for case in self.manual['cases']:
            case.update(result='not_tested', reason='UI unavailable', actual_clipboard_file=None)
        self.put('checks/manual-copy/status.json', self.manual)
        code, report = self.validate()
        self.assertEqual(code, 0)
        self.assertEqual(report['open_items'], [])
        self.assertEqual(report['ui_clipboard']['status'], 'not_tested')

    def test_missing_ui_report_is_optional(self):
        (self.work / 'checks/manual-copy/status.json').unlink()
        self.assertEqual(self.validate()[0], 0)

    def test_ocr_without_any_ui_inputs_is_verified(self):
        self.put('export-inputs.json', {'clipboard_expectations': None})
        self.manifest['inputs']['export_inputs'] = quality.bindings(export_inputs=self.work / 'export-inputs.json')['export_inputs']
        del self.manifest['inputs']['clipboard_expected']
        self.put('output-manifest.json', self.manifest)
        for name in ('checks/manual-copy/status.json', 'expected.txt', 'actual.txt'):
            (self.work / name).unlink()
        code, report = self.validate()
        self.assertEqual(code, 0)
        self.assertEqual(report['ui_clipboard'], {'optional': True, 'status': 'not_tested', 'tested_cases': []})

    def test_not_applicable_needs_no_expected_file(self):
        self.manual['cases'].append({'id': 'cross-page', 'result': 'not_applicable', 'reason': 'No continuation'})
        self.put('checks/manual-copy/status.json', self.manual)
        self.assertEqual(self.validate()[0], 0)
        self.manual['required_cases'] = ['cross-page']
        self.put('checks/manual-copy/status.json', self.manual)
        self.assertEqual(self.validate()[0], 1)

    def test_modified_clipboard_golden_and_actual_cannot_pass(self):
        (self.work / 'expected.txt').write_bytes(b'CHANGED\n')
        (self.work / 'actual.txt').write_bytes(b'CHANGED\n')
        self.assertEqual(self.validate()[0], 1)

    def test_ui_result_cannot_change_selection_or_expected_hash(self):
        self.manual['cases'][0]['expected_sha256'] = 'wrong'
        self.put('checks/manual-copy/status.json', self.manual)
        self.assertIn('clipboard_changed_expectation/first-page', self.validate()[1]['errors'])
        self.manual['cases'][0]['expected_sha256'] = quality.sha(self.work / 'expected.txt')
        self.manual['cases'][0]['selection'] = 'different selection'
        self.put('checks/manual-copy/status.json', self.manual)
        self.assertEqual(self.validate()[0], 1)

    def test_executed_ui_requires_frozen_expectations_and_reader(self):
        self.put('export-inputs.json', {'clipboard_expectations': None})
        self.manifest['inputs']['export_inputs'] = quality.bindings(export_inputs=self.work / 'export-inputs.json')['export_inputs']
        self.put('output-manifest.json', self.manifest)
        self.assertIn('clipboard_unfrozen/first-page', self.validate()[1]['errors'])
        self.put('export-inputs.json', {'clipboard_expectations': self.frozen_clipboard})
        self.manifest['inputs']['export_inputs'] = quality.bindings(export_inputs=self.work / 'export-inputs.json')['export_inputs']
        self.put('output-manifest.json', self.manifest)
        self.manual['reader'] = None
        self.put('checks/manual-copy/status.json', self.manual)
        self.assertEqual(self.validate()[0], 1)

    def test_executed_ui_failure_still_requires_individual_finding(self):
        self.manual['cases'] = self.manual['cases'][:1]
        self.manual['cases'][0]['result'] = 'fail'
        self.put('checks/manual-copy/status.json', self.manual)
        (self.work / 'actual.txt').write_bytes(b'wrong')
        self.assertEqual(self.validate()[0], 1)
        self.finding('clipboard/first-page')
        code, report = self.validate()
        self.assertEqual(code, 2)
        self.assertEqual(report['ui_clipboard']['tested_cases'], ['first-page'])

    def test_samples_cannot_be_replaced_after_export_and_rechecked(self):
        self.samples[0]['expected'] = 'WRONG'
        self.put('samples.json', self.samples)
        self.sample_report['inputs']['samples'] = quality.bindings(samples=self.work / 'samples.json')['samples']
        self.sample_report['samples'][0]['expected'] = 'WRONG'
        self.put('checks/geometry-samples.json', self.sample_report)
        self.assertEqual(self.validate()[0], 1)

    def test_clipboard_builder_writes_exact_utf8_and_preserves_versions(self):
        spec = {'expected_origin': 'fresh synthetic raster', 'cases': [
            {'id': 'letter', 'selection': 'one letter', 'expected': 'F'},
            {'id': 'row', 'selection': 'a row', 'expected': 'Ž\t0\n'},
            {'id': 'cross-page', 'result': 'not_applicable', 'reason': 'No continuation'}]}
        self.put('clipboard-cases.json', spec)
        args = SimpleNamespace(work=self.work, cases=self.work / 'clipboard-cases.json')
        with contextlib.redirect_stdout(io.StringIO()):
            quality.clipboard_expectations(args)
        frozen = quality.load(self.work / 'clipboard-expectations.json')
        letter = self.work / frozen['cases'][0]['expected_file']
        self.assertEqual(letter.read_bytes(), b'F')
        self.assertEqual((self.work / frozen['cases'][1]['expected_file']).read_bytes(), 'Ž\t0\n'.encode('utf-8'))
        self.assertNotIn('expected_file', frozen['cases'][2])
        spec['cases'][0]['expected'] = 'G'
        self.put('clipboard-cases.json', spec)
        with contextlib.redirect_stdout(io.StringIO()):
            quality.clipboard_expectations(args)
        latest = quality.load(self.work / 'clipboard-expectations.json')
        self.assertNotEqual(latest['version'], frozen['version'])
        self.assertEqual(letter.read_bytes(), b'F')
        self.assertEqual((self.work / latest['cases'][0]['expected_file']).read_bytes(), b'G')

    def test_clipboard_builder_rejects_invalid_case_before_writing(self):
        self.put('clipboard-cases.json', {'expected_origin': 'fixture', 'cases': [
            {'id': 'letter', 'selection': 'letter', 'expected': 'F'},
            {'id': '../escape', 'selection': 'letter', 'expected': 'F'}]})
        with self.assertRaisesRegex(ValueError, 'simple clipboard'):
            quality.clipboard_expectations(SimpleNamespace(work=self.work, cases=self.work / 'clipboard-cases.json'))
        self.assertFalse((self.work / 'clipboard-expectations.json').exists())
        self.assertFalse((self.work / 'checks/manual-copy/expectations').exists())

    def test_batch_review_updates_lines_and_order_atomically(self):
        before = quality.sha(self.work / 'review.json')
        original = {**self.review['lines'][0], 'text': 'ABD'}
        added = {**original, 'id': 'added', 'candidate_id': None, 'text': 'XYZ'}
        units = [self.review['units'][0], {'id': 'added-unit', 'article': 'article', 'page': 1, 'tag': 'P', 'line_ids': ['added']}]
        self.put('batch.json', {'lines': [{'line': original}, {'line': added}], 'units': units})
        args = SimpleNamespace(work=self.work, review=self.work / 'review.json', patch=self.work / 'batch.json')
        with contextlib.redirect_stdout(io.StringIO()):
            quality.update_review(args)
        changed = quality.load(self.work / 'review.json')
        self.assertEqual([line['text'] for line in changed['lines']], ['ABD', 'XYZ'])
        self.assertEqual(changed['units'], units)
        self.assertTrue((self.work / 'review-history' / (before + '.json')).is_file())
        self.assertEqual(quality.load(self.work / 'samples.json'), self.samples)

    def test_invalid_batch_leaves_review_and_history_unchanged(self):
        before = (self.work / 'review.json').read_bytes()
        self.put('batch.json', {'lines': [{'line': {**self.review['lines'][0], 'text': 'ABD'}},
                                        {'line': {**self.review['lines'][0], 'id': 'added', 'candidate_id': 'missing'}}]})
        with self.assertRaisesRegex(ValueError, 'candidate'):
            quality.update_review(SimpleNamespace(work=self.work, review=self.work / 'review.json', patch=self.work / 'batch.json'))
        self.assertEqual((self.work / 'review.json').read_bytes(), before)
        self.assertFalse((self.work / 'review-history').exists())

    def test_batch_drop_requires_candidate_reason_and_updated_units(self):
        added = {**self.review['lines'][0], 'id': 'added', 'candidate_id': None}
        self.put('batch.json', {'lines': [{'line': added}], 'drop_lines': ['line'],
                               'units': [{**self.review['units'][0], 'line_ids': ['added']}],
                               'dropped_candidates': [{'id': 'candidate', 'reason': 'Synthetic noise replacement'}]})
        with contextlib.redirect_stdout(io.StringIO()):
            quality.update_review(SimpleNamespace(work=self.work, review=self.work / 'review.json', patch=self.work / 'batch.json'))
        self.assertEqual([line['id'] for line in quality.load(self.work / 'review.json')['lines']], ['added'])

    def test_report_templates_do_not_claim_visual_review_or_waive_failures(self):
        (self.work / 'checks/visual-review.json').unlink()
        self.sample_report['samples'][0].update(mupdf_characters_pass=False, mupdf_literal='WRONG')
        self.put('checks/geometry-samples.json', self.sample_report)
        with contextlib.redirect_stdout(io.StringIO()):
            quality.report_templates(SimpleNamespace(work=self.work, reset=False))
        visual = quality.load(self.work / 'checks/visual-review.json')
        self.assertIsNone(visual['reviewer'])
        self.assertEqual(visual['pages_reviewed'], [])
        findings = quality.load(self.work / 'checks/findings.json')['items']
        self.assertTrue(any(row['id'] == 'sample/sample/mupdf' and row['reason'] is None for row in findings))
        self.assertEqual(self.validate()[0], 1)

    def test_report_templates_preserve_completed_reasons(self):
        self.sample_report['samples'][0].update(mupdf_characters_pass=False, mupdf_literal='WRONG')
        self.put('checks/geometry-samples.json', self.sample_report)
        self.finding('sample/sample/mupdf')
        with contextlib.redirect_stdout(io.StringIO()):
            quality.report_templates(SimpleNamespace(work=self.work, reset=False))
        self.assertEqual(quality.load(self.work / 'checks/findings.json')['items'][0]['reason'], 'synthetic open finding')

    def test_report_reset_archives_old_ui_and_does_not_require_it(self):
        self.put('export-inputs.json', {'clipboard_expectations': None})
        self.manifest['inputs']['export_inputs'] = quality.bindings(export_inputs=self.work / 'export-inputs.json')['export_inputs']
        self.put('output-manifest.json', self.manifest)
        self.manual['pdf_sha256'] = 'old'
        self.put('checks/manual-copy/status.json', self.manual)
        old_hash = quality.sha(self.work / 'checks/manual-copy/status.json')
        with self.assertRaisesRegex(ValueError, 'another export'):
            quality.report_templates(SimpleNamespace(work=self.work, reset=False))
        with contextlib.redirect_stdout(io.StringIO()):
            quality.report_templates(SimpleNamespace(work=self.work, reset=True))
        self.assertTrue((self.work / 'checks/report-history' / (old_hash + '.json')).is_file())
        self.assertEqual(quality.load(self.work / 'checks/manual-copy/status.json')['cases'], [])

    def test_report_diagnostics_stay_open_until_reader_fills_reason(self):
        self.put('checks/unsupported-cells.json', [{'line': 'line', 'text': 'A', 'status': 'open_geometry_uncertainty'}])
        self.put('checks/geometry-anomalies.json', [{'line': 'line', 'tiny': [0], 'overlaps': [], 'outside': []}])
        with contextlib.redirect_stdout(io.StringIO()):
            quality.report_templates(SimpleNamespace(work=self.work, reset=False))
        findings = quality.load(self.work / 'checks/findings.json')['items']
        self.assertEqual(len(findings), 2)
        self.assertTrue(all(row['status'] == 'open' and row['reason'] is None for row in findings))
        self.assertEqual(self.validate()[0], 1)

    def test_missing_evidence_fails(self):
        (self.work / 'crop.png').unlink()
        self.assertEqual(self.validate()[0], 1)

    def test_stale_visual_report_fails(self):
        visual = quality.load(self.work / 'checks/visual-review.json')
        visual['pdf_sha256'] = 'old'
        self.put('checks/visual-review.json', visual)
        self.assertEqual(self.validate()[0], 1)

    def test_patch_missing_reference_does_not_write(self):
        before = (self.work / 'review.json').read_bytes()
        line = {**self.review['lines'][0], 'candidate_id': 'missing'}
        self.put('patch.json', {'line': line})
        with self.assertRaisesRegex(ValueError, 'candidate'):
            quality.update_line(SimpleNamespace(work=self.work, review=self.work / 'review.json', id='line', patch=self.work / 'patch.json'))
        self.assertEqual((self.work / 'review.json').read_bytes(), before)

    def test_patch_leaves_expectations_and_preserves_previous_review(self):
        before = quality.sha(self.work / 'review.json')
        line = {**self.review['lines'][0], 'text': 'ABD'}
        self.put('patch.json', {'line': line})
        with contextlib.redirect_stdout(io.StringIO()):
            quality.update_line(SimpleNamespace(work=self.work, review=self.work / 'review.json', id='line', patch=self.work / 'patch.json'))
        self.assertTrue((self.work / 'review-history' / (before + '.json')).exists())
        self.assertEqual(quality.load(self.work / 'samples.json'), self.samples)
        self.assertEqual(self.validate()[0], 1)

    def test_patch_requires_consistent_risk_replacement(self):
        review = copy.deepcopy(self.review)
        risk = {'id': 'risk', 'line': 'line', 'value': 'ABC', 'status': 'visually_confirmed', 'source_crop': 'crop.png'}
        review['risk_register'] = [risk]
        self.put('review.json', review)
        before = (self.work / 'review.json').read_bytes()
        self.put('patch.json', {'line': {**review['lines'][0], 'text': 'ABD'}, 'risk_register': [risk]})
        with self.assertRaisesRegex(ValueError, 'risk value'):
            quality.update_line(SimpleNamespace(work=self.work, review=self.work / 'review.json', id='line', patch=self.work / 'patch.json'))
        self.assertEqual((self.work / 'review.json').read_bytes(), before)

    def test_outside_page_character_override_is_rejected(self):
        review = copy.deepcopy(self.review)
        review['lines'][0]['fields'] = [{'text': 'ABC', 'bbox': [0, 0, 100, 20], 'character_boxes': {'0:0:0': [0, 0, 101, 20]}}]
        with self.assertRaisesRegex(ValueError, 'outside page'):
            quality.validate_review(self.work, review)

    def test_unresolved_is_validated_per_line(self):
        review = copy.deepcopy(self.review)
        review['lines'][0].update(text='[NEČITELNÉ]', text_status='partially_unresolved')
        review['unresolved'] = [{'id': 'unknown', 'line': 'missing', 'page': 1, 'reason': 'unclear'}]
        with self.assertRaisesRegex(ValueError, 'missing line'):
            quality.validate_review(self.work, review)


class ExportIntegrationTests(unittest.TestCase):
    def test_synthetic_scan_export_cache_and_iteration(self):
        try:
            import fitz
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            self.skipTest('Install requirements.txt for the integration test')
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / 'run'
            image = Image.new('RGB', (900, 220), 'white')
            ImageDraw.Draw(image).text((30, 70), 'OCR 11', font=ImageFont.truetype('/usr/share/fonts/noto/NotoSerif-Regular.ttf', 65), fill='black')
            stream = io.BytesIO()
            image.save(stream, format='PNG')
            source = Path(directory) / 'source.pdf'
            doc = fitz.open()
            page = doc.new_page(width=216, height=52.8)
            page.insert_image(page.rect, stream=stream.getvalue())
            doc.save(source)
            doc.close()
            def cli(command, *arguments, code=0):
                result = subprocess.run([sys.executable, str(ROOT / 'tools/ocr_workflow.py'), command, '--work', str(work), *map(str, arguments)], capture_output=True, text=True)
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                return result.stdout
            cli('prepare', '--source', source)
            regions = work / 'regions.json'
            quality.dump(regions, [{'id': 'block', 'page': 1, 'bbox': [20, 60, 500, 155], 'psm': 7}])
            cli('regions', '--regions', regions)
            before = quality.sha(work / 'local-candidates.json')
            self.assertIn('1 cached', cli('regions', '--regions', regions))
            self.assertEqual(quality.sha(work / 'local-candidates.json'), before)
            (work / 'ocr/block.txt').write_text('corrupted cache', encoding='utf-8')
            self.assertIn('0 cached', cli('regions', '--regions', regions))
            self.assertNotIn('corrupted', (work / 'ocr/block.txt').read_text())
            review_path = work / 'review.json'
            cli('draft', '--review', review_path)
            review = quality.load(review_path)
            self.assertEqual(len(review['lines']), 1)
            review['lines'][0].update(text='OCR 11', text_status='visually_confirmed', decision_basis='synthetic raster', selection_region=[20, 60, 500, 155])
            quality.dump(review_path, review)
            cli('validate-review', '--review', review_path)
            cli('segment', '--review', review_path)
            cli('sheets', '--lines', work / 'reviewed-lines.json')
            quality.dump(work / 'samples.json', [{'id': 'all', 'page': 1, 'bbox': [0, 0, 900, 220], 'expected': 'OCR 11', 'expected_origin': 'synthetic source'}])
            cli('sample-sheets', '--samples', work / 'samples.json')
            preview = quality.load(work / 'checks/sample-source.json')
            self.assertTrue((work / preview['samples'][0]['source_preview']).is_file())
            quality.dump(work / 'clipboard-cases.json', {'expected_origin': 'synthetic raster', 'cases': [
                {'id': 'all', 'selection': 'all text', 'expected': 'OCR 11'},
                {'id': 'cross-page', 'result': 'not_applicable', 'reason': 'Only one page'}]})
            cli('clipboard-expectations', '--cases', work / 'clipboard-cases.json')
            pdf, txt = work / 'output/pdf/scan-ocr.pdf', work / 'output/text/scan-ocr.txt'
            cli('export', '--source', source, '--pages', work / 'pages.json', '--pdf', pdf, '--txt', txt)
            self.assertEqual(txt.read_bytes(), b'OCR 11\n')
            cli('check', '--source', source, '--pages', work / 'exported-pages.json', '--pdf', pdf, '--txt', txt)
            cli('samples', '--pdf', pdf, '--samples', work / 'samples.json')
            cli('reports')
            clipboard = quality.load(work / 'checks/manual-copy/status.json')
            self.assertEqual((work / clipboard['cases'][0]['expected_file']).read_bytes(), b'OCR 11')
            export_inputs = quality.load(work / 'export-inputs.json')
            self.assertEqual(export_inputs['clipboard_expectations']['expected_origin'], 'synthetic raster')
            old_hash = quality.sha(pdf)
            cli('export', '--source', source, '--pages', work / 'pages.json', '--pdf', pdf, '--txt', txt)
            snapshots = list((work / 'iterations').glob('*/snapshot.json'))
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(quality.load(snapshots[0])['pdf_sha256'], old_hash)
            stored = quality.load(snapshots[0])['artifacts']
            self.assertTrue(stored[clipboard['cases'][0]['expected_file']]['stored'])
            quality.dump(work / 'samples.json', [{'id': 'all', 'page': 1, 'bbox': [0, 0, 900, 220], 'expected': 'WRONG', 'expected_origin': 'deliberately failing fixture'}])
            cli('samples', '--pdf', pdf, '--samples', work / 'samples.json', code=1)
            txt.write_bytes(b'changed whitespace\n')
            cli('check', '--source', source, '--pages', work / 'exported-pages.json', '--pdf', pdf, '--txt', txt, code=1)


if __name__ == '__main__':
    unittest.main()
