"""Real native preparation through the public GUI operations and artifacts."""

import io
import json
import os
from pathlib import Path
import sys
import signal
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.service import Application


class WebUIPreparationTests(unittest.TestCase):
    def setUp(self):
        import fitz
        from PIL import Image, ImageDraw, ImageFont
        temporary = tempfile.TemporaryDirectory(prefix='WebUI skutečná příprava ')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.root = self.directory / 'evidence'
        self.source = self.directory / 'malý sken.pdf'
        image = Image.new('RGB', (900, 220), 'white')
        ImageDraw.Draw(image).text((30, 70), 'OCR 12',
                                  font=ImageFont.truetype('/usr/share/fonts/noto/NotoSerif-Regular.ttf', 65), fill='black')
        stream = io.BytesIO()
        image.save(stream, format='PNG')
        with fitz.open() as document:
            for _ in range(2):
                page = document.new_page(width=216, height=52.8)
                page.insert_image(page.rect, stream=stream.getvalue())
            document.save(self.source)
        self.app = Application(self.root)

    def named_run(self, dpi=300, name='Skutečná místní příprava'):
        imported = self.app.dispatch('import_sources', {'path': str(self.source)})
        self.assertTrue(imported['ok'], imported)
        edition = imported['data']['editions'][0]
        profile = json.loads((ROOT / 'profiles/faithful-reading.json').read_text())
        profile['parameters']['dpi'] = dpi
        path = self.directory / 'profile.json'
        path.write_text(json.dumps(profile), encoding='utf-8')
        inspected = self.app.dispatch('inspect_profile', {'path': str(path)})['data']
        result = self.app.dispatch('create_run', {'edition_id': edition['edition_id'], 'name': name,
                                   'profile_path': str(path), 'profile_sha256': inspected['sha256']})
        self.assertTrue(result['ok'], result)
        return result['data']

    def wait(self, run_id):
        deadline = time.monotonic() + 45
        observed = []
        while time.monotonic() < deadline:
            result = self.app.dispatch('preparation_status', {'run_id': run_id})
            self.assertTrue(result['ok'], result)
            observed.append(result['data'])
            if result['data']['state'] not in ('starting', 'running'):
                return result['data'], observed
            time.sleep(.05)
        self.fail('Real native preparation did not finish within 45 seconds.')

    def test_real_preparation_is_nonblocking_and_publishes_only_verified_units(self):
        run = self.named_run()
        identifier = run['project']['run_id']
        original = self.source.read_bytes()
        work = self.root / run['artifacts']['workspace']['path']
        note = work / 'preserved-note.txt'
        note.write_text('Do not replace earlier operator work.')
        started_at = time.monotonic()
        started = self.app.dispatch('start_preparation', {'run_id': identifier})
        self.assertTrue(started['ok'], started)
        self.addCleanup(self.app.close)
        self.assertLess(time.monotonic() - started_at, 1)
        self.assertIn(started['data']['state'], ('starting', 'running'))
        self.assertTrue(self.app.dispatch('projects')['ok'])
        self.assertEqual(self.app.dispatch('open_registry', {'root': str(self.directory)})['error']['code'],
                         'operation_active')
        finished, observed = self.wait(identifier)
        self.assertEqual(finished['state'], 'completed', finished)
        self.assertTrue(finished['checkpoint_valid'])
        self.assertEqual(finished['counts']['pages_completed'], 2)
        self.assertEqual(finished['counts']['ocr_completed'], 4)
        self.assertTrue(any(status['state'] == 'running' for status in observed))
        events = finished['events']
        self.assertEqual(len({event['event_id'] for event in events}), len(events))
        self.assertTrue(all(event['attempt_id'] == started['data']['attempt_id'] for event in events))
        completed = [event for event in events if event['type'] == 'unit_completed']
        self.assertEqual(len(completed), 6)
        self.assertTrue(all(event['duration_seconds'] >= 0 for event in completed))
        self.assertTrue(any(event['step_id'] == 'environment' and event['type'] == 'step_completed' for event in events))
        checkpoint = json.loads((work / 'preparation-checkpoint.json').read_text())
        self.assertEqual(checkpoint['status'], 'completed')
        self.assertIn('fresh-lines.json', checkpoint['outputs'])
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(note.read_text(), 'Do not replace earlier operator work.')
        self.assertIn('OCR', (work / 'fresh-lines.json').read_text())
        selected = self.app.dispatch('select_run', {'run_id': identifier})['data']
        self.assertEqual(selected['project']['phase'], 'prepared')
        self.assertEqual(selected['project']['validation'], 'not_run')
        self.assertEqual(selected['project']['acceptance'], 'not_recorded')
        self.assertTrue(any(event.get('event_id') == events[-1]['event_id'] for event in selected['history']))

    def test_native_cache_parameters_bad_environment_and_tampering_remain_truthful(self):
        run = self.named_run()
        identifier = run['project']['run_id']
        self.addCleanup(self.app.close)
        self.assertTrue(self.app.dispatch('start_preparation', {'run_id': identifier})['ok'])
        first, _ = self.wait(identifier)
        self.assertEqual(first['state'], 'completed', first)
        work = self.root / run['artifacts']['workspace']['path']
        raster = work / 'raster/page-1.png'
        ocr = work / 'ocr/page-1-psm3.hocr'
        old = {path: (path.stat().st_mtime_ns, path.read_bytes()) for path in [raster, ocr]}
        self.assertTrue(self.app.dispatch('start_preparation', {'run_id': identifier})['ok'])
        cached, _ = self.wait(identifier)
        self.assertEqual(cached['state'], 'completed', cached)
        self.assertEqual(cached['counts']['rasters_cached'], 2)
        self.assertEqual(cached['counts']['ocr_cached'], 4)
        self.assertNotEqual(first['attempt_id'], cached['attempt_id'])
        self.assertEqual(len([e for e in cached['events'] if e['type'] == 'unit_cached']), 6)
        for path, expected in old.items():
            self.assertEqual((path.stat().st_mtime_ns, path.read_bytes()), expected)
        before = (work / 'preparation-checkpoint.json').read_bytes()
        changed = self.app.dispatch('start_preparation', {'run_id': identifier, 'dpi': 150})
        self.assertEqual(changed['error']['code'], 'configuration_changed')
        self.assertEqual((work / 'preparation-checkpoint.json').read_bytes(), before)
        self.assertTrue(self.app.dispatch('start_preparation', {'run_id': identifier,
                                             'environment': str(self.directory / 'missing environment.json')})['ok'])
        failed, _ = self.wait(identifier)
        self.assertEqual(failed['state'], 'failed')
        self.assertEqual(failed['error']['code'], 'environment_invalid')
        self.assertEqual(failed['counts']['ocr_completed'], 0)
        self.assertTrue(any(e['type'] == 'attempt_failed' for e in failed['events']))
        self.assertEqual((work / 'preparation-checkpoint.json').read_bytes(), before)
        other = self.named_run(dpi=150, name='Nové DPI v novém průchodu')
        other_id = other['project']['run_id']
        self.assertTrue(self.app.dispatch('start_preparation', {'run_id': other_id})['ok'])
        changed, _ = self.wait(other_id)
        self.assertEqual(changed['state'], 'completed', changed)
        self.assertEqual(changed['counts']['rasters_cached'], 0)
        self.assertEqual(changed['counts']['ocr_cached'], 0)
        self.assertEqual((work / 'preparation-checkpoint.json').read_bytes(), before)
        # Querying a saved success after its artifact changed must not treat the
        # mere presence of a completed checkpoint as verification.
        other_work = self.root / other['artifacts']['workspace']['path']
        (other_work / 'ocr/page-1-psm3.hocr').write_text('corrupt cached output')
        restarted = Application(self.root)
        invalidated = restarted.dispatch('preparation_status', {'run_id': other_id})['data']
        self.assertEqual(invalidated['state'], 'invalidated')
        self.assertFalse(invalidated['checkpoint_valid'])

    def test_native_process_termination_has_a_durable_failure_event_after_restart(self):
        run = self.named_run()
        identifier = run['project']['run_id']
        self.addCleanup(self.app.close)
        started = self.app.dispatch('start_preparation', {'run_id': identifier})
        self.assertTrue(started['ok'], started)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = self.app.dispatch('preparation_status', {'run_id': identifier})['data']
            if status.get('process_group') and status['active_steps']:
                os.killpg(status['process_group'], signal.SIGKILL)
                break
            time.sleep(.02)
        else:
            self.fail('Could not observe the real owned process while active.')
        failed, _ = self.wait(identifier)
        self.assertEqual(failed['state'], 'failed')
        self.assertEqual(failed['error']['code'], 'process_terminated')
        self.assertEqual(failed['events'][-1]['type'], 'attempt_failed')
        self.assertEqual(failed['active_steps'], [])
        reloaded = Application(self.root).dispatch('preparation_status', {'run_id': identifier})['data']
        self.assertEqual(reloaded['events'][-1]['event_id'], failed['events'][-1]['event_id'])


if __name__ == '__main__':
    unittest.main()
