"""Project preparation at its public CLI and durable artifact seams."""
from pathlib import Path
import hashlib
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from native_fixtures import environment_manifest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'tools/ocr_projects.py'


class ProjectPrepareTests(unittest.TestCase):
    def setUp(self):
        import fitz
        from PIL import Image, ImageDraw, ImageFont
        self.temporary = tempfile.TemporaryDirectory(prefix='OCR preparation ')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / 'projekty s mezerami'
        image = Image.new('RGB', (900, 220), 'white')
        ImageDraw.Draw(image).text((30, 70), 'OCR 11',
                                  font=ImageFont.truetype(environment_manifest(ROOT)['fonts']['segmentation']['path'], 65), fill='black')
        stream = io.BytesIO()
        image.save(stream, format='PNG')
        self.source = self.directory / 'synthetic scan.pdf'
        with fitz.open() as document:
            page = document.new_page(width=216, height=52.8)
            page.insert_image(page.rect, stream=stream.getvalue())
            document.save(self.source)

    def command(self, *arguments, expected=0):
        result = subprocess.run([sys.executable, '-B', str(CLI), '--root', str(self.root),
                                 '--json', *map(str, arguments)], capture_output=True)
        self.assertEqual(result.returncode, expected, result.stdout.decode() + result.stderr.decode())
        self.assertLessEqual(len(result.stdout), 4096)
        return json.loads(result.stdout.decode('utf-8'))

    def test_prepare_records_each_raster_and_pass_without_claiming_content_verification(self):
        imported = self.command('import', self.source)
        identifier = imported['project']['project_id']
        result = self.command('prepare', identifier)
        self.assertEqual(result['operation'], 'prepare')
        self.assertEqual(result['protocol_version'], 1)
        self.assertEqual(result['project']['phase'], 'prepared')
        self.assertEqual(result['project']['validation'], 'not_run')
        self.assertEqual(result['project']['acceptance'], 'not_recorded')
        self.assertEqual(result['counts']['pages'], 1)
        self.assertEqual(result['counts']['rasters_computed'], 1)
        self.assertEqual(result['counts']['ocr_computed'], 2)
        work = self.root / result['artifacts']['workspace']
        checkpoint = json.loads((work / 'preparation-checkpoint.json').read_text())
        self.assertEqual(checkpoint['status'], 'completed')
        for unit in ['raster/page-1-checkpoint.json', 'ocr/page-1-psm3-cache.json', 'ocr/page-1-psm11-cache.json']:
            completed = json.loads((work / unit).read_text())
            self.assertEqual(completed['status'], 'completed')
            self.assertTrue(completed['identity'])
            self.assertTrue(completed['outputs'])
        manifest = json.loads((work / 'input-manifest.json').read_text())
        self.assertEqual(manifest['source_sha256'], imported['project']['source_sha256'])
        self.assertIsNotNone(manifest['environment'])
        self.assertFalse((work / 'review.json').exists())

    def test_unchanged_prepare_reuses_verified_units_and_repairs_only_damaged_pass(self):
        imported = self.command('import', self.source)
        identifier = imported['project']['project_id']
        first = self.command('prepare', identifier)
        work = self.root / first['artifacts']['workspace']
        raster = work / 'raster/page-1.png'
        candidate = work / 'ocr/page-1-psm3.hocr'
        untouched = work / 'ocr/page-1-psm11.hocr'
        before = {path: (path.stat().st_mtime_ns, path.read_bytes()) for path in [raster, candidate, untouched]}
        review = work / 'review.json'
        review.write_bytes(b'confirmed user text\n')
        samples = work / 'samples.json'
        samples.write_bytes(b'original expectations\n')
        cached = self.command('prepare', identifier)
        self.assertEqual(cached['counts']['rasters_reused'], 1)
        self.assertEqual(cached['counts']['rasters_computed'], 0)
        self.assertEqual(cached['counts']['ocr_reused'], 2)
        self.assertEqual(cached['counts']['ocr_computed'], 0)
        for path, state in before.items():
            self.assertEqual((path.stat().st_mtime_ns, path.read_bytes()), state)
        candidate.write_bytes(b'damaged hOCR')
        repaired = self.command('prepare', identifier)
        self.assertEqual(repaired['counts']['rasters_reused'], 1)
        self.assertEqual(repaired['counts']['ocr_reused'], 1)
        self.assertEqual(repaired['counts']['ocr_computed'], 1)
        self.assertEqual(candidate.read_bytes(), before[candidate][1])
        self.assertEqual((untouched.stat().st_mtime_ns, untouched.read_bytes()), before[untouched])
        self.assertEqual(review.read_bytes(), b'confirmed user text\n')
        self.assertEqual(samples.read_bytes(), b'original expectations\n')

    def test_same_named_model_change_is_rejected_until_approved_in_new_run(self):
        manifest = environment_manifest(ROOT)
        models = self.directory / 'models'
        models.mkdir()
        original = Path(manifest['root']) / manifest['models']['ces']['path']
        copied = models / 'ces.traineddata'
        shutil.copy2(original, copied)
        manifest['models']['ces']['path'] = str(copied)
        manifest['tessdata'] = str(models)
        configs = Path(manifest['root']) / Path(manifest['configs']['txt']['path']).parent
        (models / 'configs').symlink_to(configs, target_is_directory=True)
        profile = self.directory / 'approved environment.json'
        profile.write_text(json.dumps(manifest))
        imported = self.command('import', self.source)
        identifier = imported['project']['project_id']
        first = self.command('prepare', identifier, '--environment', profile)
        work = self.root / first['artifacts']['workspace']
        cache_before = json.loads((work / 'ocr/page-1-psm3-cache.json').read_text())
        self.assertEqual(cache_before['identity']['models']['ces'], manifest['models']['ces']['sha256'])
        checkpoint_before = (work / 'preparation-checkpoint.json').read_bytes()
        with copied.open('ab') as stream:
            stream.write(b'\nexplicitly approved additional model bytes\n')
        refused = self.command('prepare', identifier, '--environment', profile, expected=1)
        self.assertEqual(refused['error']['code'], 'environment_invalid')
        self.assertEqual((work / 'preparation-checkpoint.json').read_bytes(), checkpoint_before)
        manifest['models']['ces']['sha256'] = hashlib.sha256(copied.read_bytes()).hexdigest()
        manifest['build_id'] = 'synthetic-approved-model-change'
        profile.write_text(json.dumps(manifest))
        refused = self.command('prepare', identifier, '--environment', profile, expected=1)
        self.assertEqual(refused['error']['code'], 'configuration_changed')
        independent = self.command('import', self.source, '--new-run')
        fresh = self.command('prepare', independent['project']['project_id'], '--environment', profile)
        self.assertEqual(fresh['counts']['ocr_computed'], 2)
        cache_after = json.loads((self.root / fresh['artifacts']['workspace'] / 'ocr/page-1-psm3-cache.json').read_text())
        self.assertNotEqual(cache_after['identity']['models'], cache_before['identity']['models'])
        self.assertEqual(cache_after['identity']['models']['ces'], manifest['models']['ces']['sha256'])
        self.assertEqual((work / 'preparation-checkpoint.json').read_bytes(), checkpoint_before)

    def test_changed_parameters_require_fresh_explicit_run_and_new_computation(self):
        identifier = self.command('import', self.source)['project']['project_id']
        first = self.command('prepare', identifier)
        refused = self.command('prepare', identifier, '--dpi', 150, expected=1)
        self.assertEqual(refused['error']['code'], 'configuration_changed')
        fresh_id = self.command('import', self.source, '--new-run')['project']['project_id']
        fresh = self.command('prepare', fresh_id, '--dpi', 150)
        self.assertEqual(fresh['counts']['rasters_computed'], 1)
        self.assertEqual(fresh['counts']['ocr_computed'], 2)
        old_manifest = json.loads((self.root / first['artifacts']['workspace'] / 'input-manifest.json').read_text())
        new_manifest = json.loads((self.root / fresh['artifacts']['workspace'] / 'input-manifest.json').read_text())
        self.assertEqual(old_manifest['dpi'], 300)
        self.assertEqual(new_manifest['dpi'], 150)
        self.assertNotEqual(old_manifest['pages'][0]['raster_size'], new_manifest['pages'][0]['raster_size'])

    def test_targeted_cache_checks_models_parameters_completion_and_output_hashes(self):
        identifier = self.command('import', self.source)['project']['project_id']
        result = self.command('prepare', identifier)
        work = self.root / result['artifacts']['workspace']
        targets = self.directory / 'targets.json'
        spec = [{'id': 'word', 'page': 1, 'bbox': [20, 60, 500, 155], 'psm': 7}]
        targets.write_text(json.dumps(spec))

        def targeted():
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/ocr_workflow.py'),
                                     'targeted', '--work', str(work), '--targets', str(targets)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout

        self.assertIn('0 cached', targeted())
        self.assertIn('2 cached', targeted())
        raw_cache = work / 'ocr/word-raw-cache.json'
        cached = json.loads(raw_cache.read_text())
        self.assertEqual(cached['status'], 'completed')
        self.assertEqual(cached['identity']['language'], 'ces')
        self.assertEqual(cached['identity']['models']['ces'],
                         environment_manifest(ROOT)['models']['ces']['sha256'])
        (work / 'ocr/word-raw.txt').write_bytes(b'damaged output')
        self.assertIn('1 cached', targeted())
        self.assertEqual((work / 'ocr/word-raw.txt').read_text().strip(), 'OCR 11')
        cached = json.loads(raw_cache.read_text())
        cached['status'] = 'running'
        raw_cache.write_text(json.dumps(cached))
        self.assertIn('1 cached', targeted())
        spec[0]['psm'] = 6
        targets.write_text(json.dumps(spec))
        self.assertIn('0 cached', targeted())

    def test_concurrent_writer_gets_small_busy_error_while_other_project_can_prepare(self):
        identifier = self.command('import', self.source)['project']['project_id']
        other = self.command('import', self.source, '--new-run')['project']['project_id']
        holder_code = '''
import sys
sys.path.insert(0, sys.argv[1])
from ocr_projects import ProjectRegistry
with ProjectRegistry(sys.argv[2]).project_lock(sys.argv[3]):
    print('locked', flush=True)
    sys.stdin.readline()
'''
        holder = subprocess.Popen([sys.executable, '-c', holder_code, str(ROOT / 'tools'),
                                   str(self.root), identifier], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), 'locked')
            refused = self.command('prepare', identifier, expected=1)
            self.assertEqual(refused['error']['code'], 'project_busy')
            self.assertEqual(refused['project']['project_id'], identifier)
            self.assertEqual(self.command('status', identifier)['project']['operation_state'], 'running')
            self.assertEqual(self.command('prepare', other)['project']['phase'], 'prepared')
        finally:
            holder.communicate('done\n', timeout=10)

    def test_write_failure_has_durable_failed_status_and_requires_explicit_resume(self):
        imported = self.command('import', self.source)
        identifier = imported['project']['project_id']
        work = self.root / imported['artifacts']['workspace']
        bad_log = work / 'ocr/page-1-psm3.log'
        bad_log.mkdir(parents=True)
        refused = self.command('prepare', identifier, expected=1)
        self.assertEqual(refused['error']['code'], 'prepare_failed')
        self.assertEqual(refused['project']['phase'], 'preparation_failed')
        status = self.command('status', identifier)
        self.assertEqual(status['project']['operation_state'], 'failed')
        marker = json.loads((work / 'preparation-checkpoint.json').read_text())
        self.assertEqual(marker['status'], 'failed')
        bad_log.rmdir()
        self.assertEqual(self.command('prepare', identifier, expected=1)['error']['code'], 'resume_required')

    def test_abrupt_kill_keeps_checkpoint_and_status_reports_abandoned_operation(self):
        imported = self.command('import', self.source)
        identifier = imported['project']['project_id']
        marker_path = self.root / imported['artifacts']['workspace'] / 'preparation-checkpoint.json'
        process = subprocess.Popen([sys.executable, '-B', str(CLI), '--root', str(self.root),
                                    '--json', 'prepare', identifier], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        try:
            deadline = time.monotonic() + 15
            while not marker_path.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.001)
            self.assertTrue(marker_path.exists())
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=10)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
        marker = json.loads(marker_path.read_text())
        self.assertEqual(marker['status'], 'running')
        status = self.command('status', identifier)
        self.assertEqual(status['project']['operation_state'], 'interrupted')
        self.assertEqual(status['project']['phase'], 'preparation_interrupted')
        self.assertEqual(status['project']['validation'], 'not_run')
        self.assertEqual(self.command('prepare', identifier, expected=1)['error']['code'], 'resume_required')

    def test_malformed_unit_checkpoint_is_recomputed_instead_of_credited_or_crashing(self):
        identifier = self.command('import', self.source)['project']['project_id']
        prepared = self.command('prepare', identifier)
        work = self.root / prepared['artifacts']['workspace']
        raster_checkpoint = work / 'raster/page-1-checkpoint.json'
        value = json.loads(raster_checkpoint.read_text())
        del value['page']
        raster_checkpoint.write_text(json.dumps(value))
        candidate_checkpoint = work / 'ocr/page-1-psm3-cache.json'
        value = json.loads(candidate_checkpoint.read_text())
        value['outputs'] = None
        candidate_checkpoint.write_text(json.dumps(value))
        repaired = self.command('prepare', identifier)
        self.assertEqual(repaired['counts']['rasters_computed'], 1)
        self.assertEqual(repaired['counts']['ocr_computed'], 1)
        self.assertEqual(repaired['counts']['ocr_reused'], 1)


if __name__ == '__main__':
    unittest.main()
