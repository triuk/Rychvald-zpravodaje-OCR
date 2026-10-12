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

    def test_unavailable_ui_remains_open(self):
        for case in self.manual['cases']:
            case.update(result='not_tested', reason='UI unavailable', actual_clipboard_file=None)
        self.put('checks/manual-copy/status.json', self.manual)
        code, report = self.validate()
        self.assertEqual(code, 2)
        self.assertEqual(len(report['open_items']), 3)

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
            pdf, txt = work / 'output/pdf/scan-ocr.pdf', work / 'output/text/scan-ocr.txt'
            cli('export', '--source', source, '--pages', work / 'pages.json', '--pdf', pdf, '--txt', txt)
            self.assertEqual(txt.read_bytes(), b'OCR 11\n')
            cli('check', '--source', source, '--pages', work / 'exported-pages.json', '--pdf', pdf, '--txt', txt)
            cli('samples', '--pdf', pdf, '--samples', work / 'samples.json')
            old_hash = quality.sha(pdf)
            cli('export', '--source', source, '--pages', work / 'pages.json', '--pdf', pdf, '--txt', txt)
            snapshots = list((work / 'iterations').glob('*/snapshot.json'))
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(quality.load(snapshots[0])['pdf_sha256'], old_hash)
            quality.dump(work / 'samples.json', [{'id': 'all', 'page': 1, 'bbox': [0, 0, 900, 220], 'expected': 'WRONG', 'expected_origin': 'deliberately failing fixture'}])
            cli('samples', '--pdf', pdf, '--samples', work / 'samples.json', code=1)
            txt.write_bytes(b'changed whitespace\n')
            cli('check', '--source', source, '--pages', work / 'exported-pages.json', '--pdf', pdf, '--txt', txt, code=1)


if __name__ == '__main__':
    unittest.main()
