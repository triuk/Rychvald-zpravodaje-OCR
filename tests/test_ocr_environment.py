"""Environment contract at the public OCR CLI and emitted artifact seams."""
from pathlib import Path
import json
import os
import io
import shutil
import subprocess
import sys
import tempfile
import unittest

from native_fixtures import environment_manifest

ROOT = Path(__file__).resolve().parents[1]


class EnvironmentTests(unittest.TestCase):
    def cli(self, *args, env=None):
        return subprocess.run([sys.executable, '-B', str(ROOT / 'tools/ocr_workflow.py'), *map(str, args)],
                              capture_output=True, text=True, env=env)

    def test_missing_environment_stops_prepare_without_changing_work(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / 'work'
            work.mkdir()
            marker = work / 'review.json'
            marker.write_bytes(b'preserve my edits\n')
            result = self.cli('--environment', Path(directory) / 'missing.json',
                              'prepare', '--source', 'not-needed.pdf', '--work', work)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('missing environment manifest', result.stderr.lower())
            self.assertEqual(list(work.iterdir()), [marker])
            self.assertEqual(marker.read_bytes(), b'preserve my edits\n')

    def test_wrong_resource_version_stops_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            manifest = environment_manifest(ROOT)
            manifest['programs']['tesseract']['version'] = 'tesseract 0.0.0'
            changed = directory / 'environment.json'
            changed.write_text(json.dumps(manifest))
            work = directory / 'work'
            result = self.cli('--environment', changed, 'prepare', '--source', 'not-needed.pdf', '--work', work)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('wrong version: tesseract', result.stderr.lower())
            self.assertFalse(work.exists())

    def test_changed_model_or_font_preserves_existing_work(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            work = directory / 'work'
            work.mkdir()
            marker = work / 'review.json'
            marker.write_bytes(b'confirmed text\n')
            for category, name in [('models', 'ces'), ('fonts', 'segmentation')]:
                with self.subTest(category=category):
                    manifest = environment_manifest(ROOT)
                    corrupted = directory / 'changed-resource'
                    corrupted.write_bytes(b'changed bytes')
                    manifest[category][name]['path'] = str(corrupted)
                    changed = directory / 'environment.json'
                    changed.write_text(json.dumps(manifest))
                    result = self.cli('--environment', changed, 'targeted', '--targets', 'not-needed.json', '--work', work)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn(f'Changed content: {category}/{name}', result.stderr)
                    self.assertEqual(marker.read_bytes(), b'confirmed text\n')
                    self.assertEqual(list(work.iterdir()), [marker])

    def test_doctor_uses_pinned_programs_when_path_and_tessdata_are_wrong(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            fake = directory / 'fake'
            fake.mkdir()
            for name in ['tesseract', 'qpdf', 'pdftotext', 'pdftoppm', 'pdffonts']:
                executable = fake / name
                executable.write_text('#!/bin/sh\necho WRONG-PATH >&2\nexit 99\n')
                executable.chmod(0o755)
            env = {**os.environ, 'PATH': str(fake), 'TESSDATA_PREFIX': str(fake)}
            result = self.cli('doctor', env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            manifest = environment_manifest(ROOT)
            self.assertEqual(report['build_id'], manifest['build_id'])
            self.assertEqual(report['checks']['tesseract']['path'], manifest['programs']['tesseract']['path'])

    def test_pythonpath_cannot_shadow_verified_python_library(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / 'numpy.py').write_text('this_is_the_wrong_library = True\n')
            env = {**os.environ, 'PYTHONPATH': str(directory)}
            result = self.cli('doctor', env=env)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('Wrong import location: numpy', result.stderr)

    def test_synthetic_workflow_uses_relocated_resources_with_poisoned_path(self):
        import fitz
        from PIL import Image, ImageDraw, ImageFont
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            manifest = environment_manifest(ROOT)
            source_root = Path(manifest['root'])
            root = directory / 'resources'
            root.mkdir()
            for category in ['programs', 'models', 'fonts', 'configs', 'libraries']:
                for name, record in manifest[category].items():
                    source = Path(record['path'])
                    if category == 'libraries':
                        relative = source.relative_to(source_root)
                    else:
                        relative = (Path('models/configs') if category == 'configs' else Path(category)) / source.name
                    target = root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    record['path'] = str(relative)
            manifest['library_dirs'] = [str(Path(value).relative_to(source_root))
                                        for value in manifest['library_dirs']]
            manifest['root'] = 'resources'
            manifest['tessdata'] = 'models'
            relocated = directory / 'environment.json'
            relocated.write_text(json.dumps(manifest))
            fake = directory / 'fake'
            fake.mkdir()
            for name in manifest['programs']:
                executable = fake / name
                executable.write_text('#!/bin/sh\necho WRONG-PATH >&2\nexit 99\n')
                executable.chmod(0o755)
            env = {**os.environ, 'PATH': str(fake), 'TESSDATA_PREFIX': str(fake)}
            image = Image.new('RGB', (900, 220), 'white')
            ImageDraw.Draw(image).text((30, 70), 'OCR 11', font=ImageFont.truetype(str(root / manifest['fonts']['segmentation']['path']), 65), fill='black')
            stream = io.BytesIO()
            image.save(stream, format='PNG')
            source = directory / 'scan.pdf'
            with fitz.open() as doc:
                page = doc.new_page(width=216, height=52.8)
                page.insert_image(page.rect, stream=stream.getvalue())
                doc.save(source)
            work = directory / 'work'

            def cli(command, *args):
                result = self.cli('--environment', relocated, command, '--work', work, *args, env=env)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            cli('prepare', '--source', source)
            prepared = json.loads((work / 'input-manifest.json').read_text())
            self.assertEqual(prepared['environment']['build_id'], manifest['build_id'])
            commands = json.loads((work / 'ocr-commands.json').read_text())
            self.assertTrue(all(row['command'][0] == str(root / 'programs/tesseract') for row in commands))
            regions = directory / 'regions.json'
            regions.write_text(json.dumps([{'id': 'block', 'page': 1, 'bbox': [20, 60, 500, 155], 'psm': 7}]))
            cli('regions', '--regions', regions)
            targets = directory / 'targets.json'
            targets.write_text(json.dumps([{'id': 'word', 'page': 1, 'bbox': [20, 60, 500, 155], 'psm': 7}]))
            cli('targeted', '--targets', targets)
            candidates = json.loads((work / 'targeted-candidates.json').read_text())
            self.assertEqual(candidates[0]['candidate'].strip(), 'OCR 11')
            self.assertEqual(candidates[0]['command'][0], str(root / 'programs/tesseract'))
            review_path = work / 'review.json'
            cli('draft', '--review', review_path)
            review = json.loads(review_path.read_text())
            review['lines'][0].update(text='OCR 11', text_status='visually_confirmed',
                                      decision_basis='synthetic source raster', selection_region=[20, 60, 500, 155])
            review_path.write_text(json.dumps(review))
            cli('segment', '--review', review_path)
            (work / 'samples.json').write_text(json.dumps([{'id': 'all', 'page': 1,
                'bbox': [0, 0, 900, 220], 'expected': 'OCR 11', 'expected_origin': 'synthetic source raster'}]))
            pdf, txt = work / 'output/pdf/scan-ocr.pdf', work / 'output/text/scan-ocr.txt'
            cli('export', '--source', source, '--pages', work / 'pages.json', '--pdf', pdf, '--txt', txt)
            self.assertEqual(txt.read_bytes(), b'OCR 11\n')
            cli('check', '--source', source, '--pages', work / 'exported-pages.json', '--pdf', pdf, '--txt', txt)


if __name__ == '__main__':
    unittest.main()
