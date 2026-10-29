"""Phase previews through the same requests as the GUI, with independent page geometry."""
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.service import Application


class PhasePreviewTests(unittest.TestCase):
    def setUp(self):
        import fitz
        self.temporary = tempfile.TemporaryDirectory(prefix='Náhled průchodu ')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.source = self.directory / 'Dvě strany.pdf'
        with fitz.open() as document:
            page = document.new_page(width=240, height=160)
            page.draw_rect(fitz.Rect(40, 20, 100, 60), color=(1, 0, 0), fill=(1, 0, 0))
            page = document.new_page(width=300, height=200)
            page.draw_rect(fitz.Rect(50, 60, 110, 90), color=(1, 0, 0), fill=(1, 0, 0))
            page.set_cropbox(fitz.Rect(20, 30, 280, 180))
            page.set_rotation(90)
            document.save(self.source)
        self.app = Application(self.directory / 'evidence')
        self.addCleanup(self.app.close)
        result = self.app.dispatch('import_sources', {'path': str(self.source)})
        self.assertTrue(result['ok'], result)
        self.edition = result['data']['editions'][0]
        self.run_id = self.edition['runs'][0]['run_id']
        self.run = self.app.dispatch('select_run', {'run_id': self.run_id})['data']
        self.work = self.app.root / self.run['artifacts']['workspace']['path']

    def preview(self, **changes):
        result = self.app.dispatch('phase_preview', {'run_id': self.run_id,
            'edition_id': self.edition['edition_id'], 'phase': 'preparation', 'page': 1, **changes})
        self.assertTrue(result['ok'], result)
        return result['data']

    def prepare_fixture(self):
        """A recorded local OCR fixture; literal boxes derive from the drawn rectangles."""
        import fitz
        self.work.mkdir(parents=True, exist_ok=True)
        (self.work / 'raster').mkdir(exist_ok=True)
        pages = []
        with fitz.open(self.source) as document:
            for number, page in enumerate(document, 1):
                raster = self.work / f'raster/page-{number}.png'
                page.get_pixmap(dpi=144).save(raster)
                pages.append({'page': number, 'rect': list(page.rect), 'cropbox': list(page.cropbox),
                    'mediabox': list(page.mediabox), 'rotation': page.rotation,
                    'raster_size': [480, 320] if number == 1 else [300, 520],
                    'raster_sha256': hashlib.sha256(raster.read_bytes()).hexdigest()})
        manifest = {'source_sha256': self.edition['edition_id'], 'dpi': 144, 'pages': pages}
        (self.work / 'input-manifest.json').write_text(json.dumps(manifest))
        (self.work / 'fresh-lines.json').write_text(json.dumps([
            {'id': 'front', 'page': 1, 'text': 'Pomocné OCR první strany', 'ocr_bbox': [80, 40, 200, 120]},
            {'id': 'rotated', 'page': 2, 'text': 'Pomocné OCR otočené strany', 'ocr_bbox': [180, 60, 240, 180]}]))

    def test_source_and_local_candidates_are_bound_to_run_page_and_displayed_crop_rotation(self):
        first = self.preview()
        self.assertEqual(first['state'], 'source_only')
        self.assertEqual(first['page_count'], 2)
        self.assertEqual(first['overlays'], [])
        self.prepare_fixture()
        original = {p: p.read_bytes() for p in self.work.rglob('*') if p.is_file()}
        data = self.preview(page=2)
        self.assertEqual(data['state'], 'available')
        self.assertEqual(data['identity']['run_id'], self.run_id)
        self.assertEqual(data['identity']['source_sha256'], self.edition['edition_id'])
        self.assertEqual(data['identity']['page'], 2)
        self.assertEqual(data['identity']['phase'], 'preparation')
        self.assertEqual(data['overlays'][0]['text'], 'Pomocné OCR otočené strany')
        self.assertEqual(data['overlays'][0]['kind'], 'local_ocr_candidate')
        for actual, expected in zip(data['overlays'][0]['normalized_bbox'], [.6, 30/260, .8, 90/260]):
            self.assertAlmostEqual(actual, expected, places=5)
        from PIL import Image
        image = Image.open(io.BytesIO(base64.b64decode(data['image']['data_url'].split(',', 1)[1])))
        red = image.convert('RGB').getpixel((int(image.width * .7), int(image.height * .23)))
        self.assertGreater(red[0], 220)
        self.assertLess(red[1], 30)
        self.assertEqual({p: p.read_bytes() for p in original}, original)
        reading = self.preview(phase='reading', page=2)
        self.assertEqual(reading['state'], 'historical_missing')
        self.assertEqual(reading['overlays'], [])
        self.assertEqual(self.preview(page=99)['state'], 'page_missing')

    def test_foreign_changed_or_invalid_backing_files_are_not_displayed_as_valid_candidates(self):
        self.prepare_fixture()
        path = self.work / 'input-manifest.json'
        original = json.loads(path.read_text())
        value = {**original, 'source_sha256': '0' * 64}
        path.write_text(json.dumps(value))
        self.assertEqual(self.preview()['state'], 'artifact_invalid')
        path.write_text(json.dumps(original))
        original['pages'][0]['rotation'] = 90
        path.write_text(json.dumps(original))
        self.assertEqual(self.preview()['state'], 'artifact_invalid')

    def named_run(self):
        profile = self.app.dispatch('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})['data']
        result = self.app.dispatch('create_run', {'edition_id': self.edition['edition_id'],
            'name': 'Nezávislý průchod', 'profile_path': profile['path'], 'profile_sha256': profile['sha256']})
        self.assertTrue(result['ok'], result)
        return result['data']

    def test_recorded_region_candidates_are_visible_without_creating_reading_inputs(self):
        self.prepare_fixture()
        (self.work / 'fresh-lines.json').unlink()
        (self.work / 'local-candidates.json').write_text(json.dumps([{'id': 'region', 'page': 1,
            'lines': [{'id': 'local-region', 'page': 1, 'text': 'Oblast místního OCR',
                'ocr_bbox': [80, 40, 200, 120]}]}]))
        data = self.preview()
        self.assertEqual(data['state'], 'available')
        self.assertEqual(data['overlays'][0]['text'], 'Oblast místního OCR')
        self.assertFalse((self.work / 'reading-input.json').exists())

    def test_another_run_cannot_borrow_candidates_and_preview_does_not_change_saved_state(self):
        self.prepare_fixture()
        another = self.named_run()
        run_id = another['project']['run_id']
        before = self.app.dispatch('select_run', {'run_id': run_id})['data']
        second = self.preview(run_id=run_id)
        self.assertEqual(second['state'], 'source_only')
        self.assertEqual(second['overlays'], [])
        self.assertNotEqual(second['identity']['run_id'], self.preview()['identity']['run_id'])
        after = self.app.dispatch('select_run', {'run_id': run_id})['data']
        self.assertEqual(before, after)
        wrong = self.app.dispatch('phase_preview', {'run_id': run_id, 'edition_id': '0' * 64})
        self.assertFalse(wrong['ok'])
        self.assertEqual(wrong['error']['code'], 'preview_invalid')

    def test_real_local_preparation_produces_a_read_only_preview_without_new_work(self):
        run = self.named_run()
        run_id = run['project']['run_id']
        started = self.app.dispatch('start_preparation', {'run_id': run_id})
        self.assertTrue(started['ok'], started)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status = self.app.dispatch('preparation_status', {'run_id': run_id})['data']
            if status['state'] not in ('starting', 'running'):
                break
            time.sleep(.05)
        self.assertEqual(status['state'], 'completed', status)
        before = self.app.dispatch('select_run', {'run_id': run_id})['data']
        data = self.preview(run_id=run_id, page=2)
        self.assertEqual(data['state'], 'available')
        self.assertEqual(data['raster']['rotation'], 90)
        self.assertEqual(data['page_count'], 2)
        self.assertIn('fresh-lines.json', data['artifacts'])
        self.assertEqual(self.app.dispatch('select_run', {'run_id': run_id})['data'], before)
