"""Explicit recovery through project CLI and durable artifact boundaries."""
from pathlib import Path
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from native_fixtures import environment_manifest, environment_path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'tools/ocr_projects.py'


class ProjectResumeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='OCR resume ')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / 'projects with spaces'
        self.source = self.scan()

    def scan(self, pages=1, height=220):
        import fitz
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new('RGB', (900, height), 'white')
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(environment_manifest(ROOT)['fonts']['segmentation']['path'], 65)
        for y in range(70, height - 65, 90):
            draw.text((30, y), 'OCR 11', font=font, fill='black')
        stream = io.BytesIO()
        image.save(stream, format='PNG')
        source = self.directory / f'scan-{pages}-{height}.pdf'
        with fitz.open() as doc:
            for _ in range(pages):
                page = doc.new_page(width=216, height=height * .24)
                page.insert_image(page.rect, stream=stream.getvalue())
            doc.save(source)
        return source

    def cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, '-B', str(CLI), '--root', str(self.root),
                                 '--json', *map(str, args)], capture_output=True)
        self.assertEqual(result.returncode, expected, result.stdout.decode() + result.stderr.decode())
        self.assertLessEqual(len(result.stdout), 4096)
        result = json.loads(result.stdout)
        self.assertEqual(result['protocol_version'], 1)
        return result

    def imported(self, source=None):
        record = self.cli('import', source or self.source)
        return record['project']['project_id'], self.root / record['artifacts']['workspace']

    def manual_files(self, work):
        paths = ['review.json', 'repair-history.json', 'samples.json', 'clipboard-expectations.json',
                 'checks/findings/status.json', 'checks/evidence/original.png',
                 'iterations/previous/snapshot.json', 'output/pdf/previous.pdf', 'output/text/previous.txt']
        result = {}
        for name in paths:
            path = work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('independent original manual input: ' + name + '\n').encode())
            result[path] = path.read_bytes()
        return result

    def test_explicit_resume_retries_failure_and_preserves_completed_and_manual_work(self):
        identifier, work = self.imported()
        broken_log = work / 'ocr/page-1-psm3.log'
        broken_log.mkdir(parents=True)
        failed = self.cli('prepare', identifier, expected=1)
        self.assertEqual(failed['error']['code'], 'prepare_failed')
        self.assertEqual(self.cli('prepare', identifier, expected=1)['error']['code'], 'resume_required')
        preserved = self.manual_files(work)
        raster = work / 'raster/page-1.png'
        before = (raster.stat().st_mtime_ns, raster.read_bytes())
        broken_log.rmdir()
        resumed = self.cli('resume', identifier)
        self.assertEqual(resumed['operation'], 'resume')
        self.assertEqual(resumed['project']['phase'], 'prepared')
        self.assertEqual(resumed['project']['operation_state'], 'completed')
        self.assertEqual(resumed['counts']['rasters_reused'], 1)
        self.assertEqual((raster.stat().st_mtime_ns, raster.read_bytes()), before)
        for path, content in preserved.items():
            self.assertEqual(path.read_bytes(), content)
        again = self.cli('resume', identifier)
        self.assertEqual(again['counts']['ocr_reused'], 2)
        self.assertEqual(again['counts']['ocr_computed'], 0)

    def test_damaged_master_checkpoint_recovers_original_configuration_and_hashes(self):
        identifier, work = self.imported()
        self.cli('prepare', identifier, '--dpi', 150, '--language', 'eng')
        raster = work / 'raster/page-1.png'
        before = (raster.stat().st_mtime_ns, raster.read_bytes())
        for damaged in ['{invalid json', '[]']:
            with self.subTest(damaged=damaged):
                (work / 'preparation-checkpoint.json').write_text(damaged)
                self.assertEqual(self.cli('status', identifier)['project']['operation_state'], 'interrupted')
                resumed = self.cli('resume', identifier)
                self.assertEqual(resumed['counts']['rasters_reused'], 1)
                self.assertEqual(resumed['counts']['ocr_reused'], 2)
                manifest = json.loads((work / 'input-manifest.json').read_text())
                self.assertEqual(manifest['dpi'], 150)
                self.assertEqual(manifest['ocr']['language'], 'eng')
                self.assertEqual((raster.stat().st_mtime_ns, raster.read_bytes()), before)

    def completed(self, work, pattern):
        result = []
        for path in work.glob(pattern):
            try:
                if json.loads(path.read_text()).get('status') == 'completed':
                    result.append(path)
            except (OSError, ValueError, AttributeError):
                pass
        return result

    def start(self, operation, identifier):
        process = subprocess.Popen([sys.executable, '-B', str(CLI), '--root', str(self.root),
                                    '--json', operation, identifier], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        self.addCleanup(self.kill, process)
        return process

    @staticmethod
    def kill(process):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        return process.communicate(timeout=10)

    def suspend_at(self, process, predicate):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and process.poll() is None:
            if predicate():
                os.killpg(process.pid, signal.SIGSTOP)
                return
            time.sleep(.001)
        stdout, stderr = self.kill(process)
        self.fail('Preparation did not reach pending checkpoint boundary: ' + (stdout + stderr).decode())

    def test_sigkill_between_pages_resumes_valid_rasters_without_rewriting_manual_data(self):
        identifier, work = self.imported(self.scan(pages=8, height=1200))
        manual = self.manual_files(work)
        process = self.start('prepare', identifier)
        self.suspend_at(process, lambda: 0 < len(self.completed(work, 'raster/page-*-checkpoint.json')) < 8)
        completed = self.completed(work, 'raster/page-*-checkpoint.json')
        self.assertGreater(len(completed), 0)
        self.assertLess(len(completed), 8)
        before = {path.with_name(path.name.replace('-checkpoint.json', '.png')):
                  (path.with_name(path.name.replace('-checkpoint.json', '.png')).stat().st_mtime_ns,
                   path.with_name(path.name.replace('-checkpoint.json', '.png')).read_bytes()) for path in completed}
        self.kill(process)
        self.assertEqual(self.cli('status', identifier)['project']['operation_state'], 'interrupted')
        self.assertEqual(self.cli('prepare', identifier, expected=1)['error']['code'], 'resume_required')
        resumed = self.cli('resume', identifier)
        self.assertEqual(resumed['counts']['rasters_reused'], len(completed))
        self.assertEqual(resumed['counts']['pages'], 8)
        for path, state in before.items():
            self.assertEqual((path.stat().st_mtime_ns, path.read_bytes()), state)
        for path, content in manual.items():
            self.assertEqual(path.read_bytes(), content)

    def test_sigkill_between_candidate_passes_and_repeated_resume_keeps_completed_units(self):
        identifier, work = self.imported(self.scan(pages=8, height=1200))
        process = self.start('prepare', identifier)
        self.suspend_at(process, lambda: 0 < len(self.completed(work, 'ocr/page-*-cache.json')) < 16)
        first = self.completed(work, 'ocr/page-*-cache.json')
        self.assertGreater(len(first), 0)
        before = {}
        for checkpoint in first:
            for suffix in ['.hocr', '.tsv', '.txt', '.box']:
                path = checkpoint.with_name(checkpoint.name.replace('-cache.json', suffix))
                before[path] = (path.stat().st_mtime_ns, path.read_bytes())
        self.kill(process)
        self.assertEqual(self.cli('status', identifier)['project']['phase'], 'preparation_interrupted')
        again = self.start('resume', identifier)
        self.suspend_at(again, lambda: len(first) < len(self.completed(work, 'ocr/page-*-cache.json')) < 16)
        second = self.completed(work, 'ocr/page-*-cache.json')
        self.kill(again)
        resumed = self.cli('resume', identifier)
        self.assertEqual(resumed['counts']['rasters_reused'], 8)
        self.assertEqual(resumed['counts']['ocr_reused'], len(second))
        self.assertEqual(resumed['counts']['ocr_computed'], 16 - len(second))
        for path, state in before.items():
            self.assertEqual((path.stat().st_mtime_ns, path.read_bytes()), state)

    def test_resume_refuses_live_writer_and_accepts_abandoned_lock(self):
        identifier, work = self.imported(self.scan(pages=8, height=1200))
        process = self.start('prepare', identifier)
        self.suspend_at(process, lambda: (work / 'preparation-checkpoint.json').exists())
        self.assertEqual(self.cli('status', identifier)['project']['operation_state'], 'running')
        self.assertEqual(self.cli('resume', identifier, expected=1)['error']['code'], 'project_busy')
        self.assertEqual(self.cli('status', identifier)['project']['operation_state'], 'running')
        self.kill(process)
        self.assertEqual(self.cli('status', identifier)['project']['operation_state'], 'interrupted')
        self.assertEqual(self.cli('resume', identifier)['project']['operation_state'], 'completed')

    def test_corrupt_unit_metadata_and_outputs_are_repaired_independently(self):
        identifier, work = self.imported()
        self.cli('prepare', identifier)
        manual = self.manual_files(work)
        raster_checkpoint = work / 'raster/page-1-checkpoint.json'
        checkpoint = json.loads(raster_checkpoint.read_text())
        checkpoint['page']['rect'] = [0, 0, 1, 1]
        raster_checkpoint.write_text(json.dumps(checkpoint))
        repaired = self.cli('resume', identifier)
        self.assertEqual(repaired['counts']['rasters_computed'], 1)
        self.assertEqual(repaired['counts']['ocr_reused'], 2)
        rect = json.loads((work / 'input-manifest.json').read_text())['pages'][0]['rect']
        self.assertEqual(rect[:3], [0, 0, 216])
        self.assertAlmostEqual(rect[3], 52.8, places=5)
        (work / 'ocr/page-1-psm3-cache.json').write_text('{invalid cache')
        (work / 'ocr/page-1-psm11.txt').write_text('corrupted candidate')
        repaired = self.cli('resume', identifier)
        self.assertEqual(repaired['counts']['rasters_reused'], 1)
        self.assertEqual(repaired['counts']['ocr_computed'], 2)
        (work / 'raster/overview-1.png').unlink()
        repaired = self.cli('resume', identifier)
        self.assertEqual(repaired['counts']['rasters_computed'], 1)
        self.assertEqual(repaired['counts']['ocr_reused'], 2)
        for path, content in manual.items():
            self.assertEqual(path.read_bytes(), content)

    def test_resume_preserves_later_review_state_even_across_another_failure(self):
        identifier, work = self.imported()
        prepared = self.cli('prepare', identifier)
        project_path = self.root / prepared['artifacts']['project']
        record = json.loads(project_path.read_text())
        record['project'].update(phase='reviewed', validation='passed', acceptance='recorded')
        project_path.write_text(json.dumps(record))
        manual = self.manual_files(work)
        resumed = self.cli('resume', identifier)
        for key in ['phase', 'validation', 'acceptance']:
            self.assertEqual(resumed['project'][key], record['project'][key])
        (work / 'ocr/page-1-psm3-cache.json').unlink()
        log = work / 'ocr/page-1-psm3.log'
        log.unlink()
        log.mkdir()
        self.assertEqual(self.cli('resume', identifier, expected=1)['error']['code'], 'prepare_failed')
        log.rmdir()
        result = self.cli('resume', identifier)
        for key in ['phase', 'validation', 'acceptance']:
            self.assertEqual(result['project'][key], record['project'][key])
        for path, content in manual.items():
            self.assertEqual(path.read_bytes(), content)

    def test_resume_uses_original_manifest_and_refuses_input_mismatches_without_writes(self):
        identifier, work = self.imported()
        manifest = environment_manifest(ROOT)
        manifest['build_id'] = 'explicit-custom-test-profile'
        profile = self.directory / 'custom-environment.json'
        profile.write_text(json.dumps(manifest))
        prepared = self.cli('prepare', identifier, '--environment', profile)
        self.assertEqual(self.cli('resume', identifier)['counts']['ocr_reused'], 2)
        manual = self.manual_files(work)
        marker = work / 'preparation-checkpoint.json'
        before = marker.read_bytes()
        for arguments, code in [(['--dpi', '150'], 'configuration_changed'),
                                (['--language', 'eng'], 'configuration_changed'),
                                (['--environment', environment_path(ROOT)], 'environment_changed'),
                                (['--environment', self.directory / 'missing.json'], 'environment_invalid')]:
            with self.subTest(arguments=arguments):
                result = self.cli('resume', identifier, *arguments, expected=1)
                self.assertEqual(result['error']['code'], code)
                self.assertTrue(result['error']['message'])
                self.assertEqual(marker.read_bytes(), before)
        source = self.root / prepared['artifacts']['source']
        source.write_bytes(source.read_bytes() + b'changed source bytes')
        self.assertEqual(self.cli('resume', identifier, expected=1)['error']['code'], 'source_corrupt')
        self.assertEqual(marker.read_bytes(), before)
        for path, content in manual.items():
            self.assertEqual(path.read_bytes(), content)

    def test_unrecoverable_identity_refuses_resume_without_destroying_workspace(self):
        identifier, work = self.imported()
        self.cli('prepare', identifier)
        manual = self.manual_files(work)
        for name in ['preparation-checkpoint.json', 'preparation-identity.json', 'input-manifest.json']:
            (work / name).write_text('{unrecoverable identity')
        refused = self.cli('resume', identifier, expected=1)
        self.assertEqual(refused['error']['code'], 'checkpoint_invalid')
        self.assertIn('new run', refused['error']['message'])
        for path, content in manual.items():
            self.assertEqual(path.read_bytes(), content)
        fresh = self.cli('import', self.source, '--new-run')
        self.assertNotEqual(fresh['project']['project_id'], identifier)

    def test_resume_on_registered_only_project_requires_first_prepare(self):
        identifier, work = self.imported()
        before = {path.name: path.read_bytes() for path in work.iterdir()}
        refused = self.cli('resume', identifier, expected=1)
        self.assertEqual(refused['error']['code'], 'resume_unavailable')
        self.assertEqual({path.name: path.read_bytes() for path in work.iterdir()}, before)


if __name__ == '__main__':
    unittest.main()
