"""Comparison and cross-run preparation through the GUI's public operations."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest

from native_fixtures import environment_manifest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.service import Application


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        import fitz
        from PIL import Image, ImageDraw, ImageFont
        self.temporary = tempfile.TemporaryDirectory(prefix='OCR comparison ')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / 'registry'
        self.app = Application(self.root)
        self.addCleanup(self.app.close)
        image = Image.new('RGB', (900, 220), 'white')
        ImageDraw.Draw(image).text((30, 70), 'OCR 11', font=ImageFont.truetype(
            environment_manifest(ROOT)['fonts']['segmentation']['path'], 65), fill='black')
        stream = io.BytesIO()
        image.save(stream, format='PNG')
        self.source = self.directory / 'source.pdf'
        with fitz.open() as document:
            page = document.new_page(width=216, height=52.8)
            page.insert_image(page.rect, stream=stream.getvalue())
            document.save(self.source)
        self.edition = self.call('import_sources', path=str(self.source))['editions'][0]['edition_id']

    def call(self, operation, **payload):
        result = self.app.dispatch(operation, payload)
        self.assertTrue(result['ok'], result)
        return result['data']

    def run_named(self, name, dpi=300):
        profile = json.loads((ROOT / 'profiles/faithful-reading.json').read_text())
        profile['parameters']['dpi'] = dpi
        profile['prompts']['read'] += '\nComparison profile: ' + name
        path = self.directory / (name + '.json')
        path.write_text(json.dumps(profile))
        inspected = self.call('inspect_profile', path=str(path))
        return self.call('create_run', edition_id=self.edition, name=name,
            profile_path=str(path), profile_sha256=inspected['sha256'])

    def prepare(self, run, donor=None):
        self.call('start_preparation', run_id=run['project']['run_id'], **(
            {'reuse_from_run_id': donor['project']['run_id']} if donor else {}))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            status = self.call('preparation_status', run_id=run['project']['run_id'])
            if status['state'] not in ('starting', 'running'):
                self.assertEqual(status['state'], 'completed', status)
                self.assertTrue(status['checkpoint_valid'], status)
                return status
            time.sleep(.05)
        self.fail('Preparation did not finish')

    def work(self, run):
        return self.root / run['artifacts']['workspace']['path']

    def test_new_profile_imports_only_verified_full_page_local_units(self):
        donor = self.run_named('A')
        self.prepare(donor)
        old = self.work(donor)
        for name in ('review.json', 'samples.json', 'regions.json', 'targets.json',
                     'reading-proposal.json', 'application/ai-sentinel.json',
                     'context-mode/knowledge.json', 'output/text/answer.txt'):
            path = old / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('DONOR AI RESULT DO NOT INHERIT')
        before = {str(p.relative_to(old)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in old.rglob('*') if p.is_file()}
        target = self.run_named('B')
        status = self.prepare(target, donor)
        units = [e for e in status['events'] if e['type'] == 'unit_cached']
        self.assertEqual([e.get('origin') for e in units], ['imported_local'] * 3)
        self.assertTrue(all(e['donor_run_id'] == donor['project']['run_id'] for e in units))
        new = self.work(target)
        for name in ('review.json', 'samples.json', 'regions.json', 'targets.json',
                     'reading-proposal.json', 'application/ai-sentinel.json', 'context-mode/knowledge.json'):
            self.assertFalse((new / name).exists(), name)
        cache = json.loads((new / 'ocr/page-1-psm3-cache.json').read_text())
        self.assertEqual(cache['identity']['command'][1:3],
            [str(new / 'raster/page-1.png'), str(new / 'ocr/page-1-psm3')])
        provenance = json.loads((new / 'local-imports.json').read_text())
        self.assertEqual(len(provenance['units']), 3)
        self.assertNotEqual((new / 'raster/page-1.png').stat().st_ino,
                            (old / 'raster/page-1.png').stat().st_ino)
        (new / 'raster/page-1.png').write_bytes(b'destination changed')
        self.assertEqual({name: hashlib.sha256((old / name).read_bytes()).hexdigest()
                          for name in before}, before)

    def test_comparison_retains_exact_profiles_origins_prices_and_history_after_restart(self):
        a = self.run_named('A')
        self.prepare(a)
        b = self.run_named('B')
        self.prepare(b, a)
        cursor = self.call('events')['events'][-1]['sequence']
        comparison = self.call('compare_runs', left_run_id=a['project']['run_id'],
            right_run_id=b['project']['run_id'], limit=2)
        self.assertEqual(comparison['edition_id'], self.edition)
        self.assertEqual([r['run']['name'] for r in comparison['runs']], ['A', 'B'])
        self.assertNotEqual(comparison['runs'][0]['profile']['sha256'], comparison['runs'][1]['profile']['sha256'])
        self.assertIn('Comparison profile: A', comparison['runs'][0]['profile']['text'])
        self.assertEqual(comparison['runs'][1]['local_origins'],
            {'computed': 0, 'same_run_cache': 0, 'imported_local': 3})
        self.assertEqual(comparison['runs'][1]['metrics']['tokens']['status'], 'unavailable')
        self.assertEqual(comparison['runs'][0]['metrics']['cost_scale'], comparison['cost_scale'])
        self.assertIsNotNone(comparison['runs'][0]['metrics']['step_next_offset'])
        self.assertIsNotNone(comparison['runs'][0]['history_next_offset'])
        events = self.call('events', after=cursor)['events']
        self.assertFalse(any(e['type'] == 'run_selected' for e in events))
        self.app.close()
        self.app = Application(self.root)
        restored = self.call('compare_runs', left_run_id=a['project']['run_id'],
            right_run_id=b['project']['run_id'], limit=2)
        self.assertEqual(restored, comparison)
        failure = self.app.dispatch('compare_runs', {'left_run_id': a['project']['run_id'],
            'right_run_id': a['project']['run_id']})
        self.assertEqual(failure['error']['code'], 'invalid_comparison')

    def test_malformed_donor_unit_is_recomputed_without_importing_its_completion(self):
        donor = self.run_named('A')
        self.prepare(donor)
        old = self.work(donor)
        cache = old / 'ocr/page-1-psm3-cache.json'
        cache.write_text('[]')
        target = self.run_named('B')
        result = self.prepare(target, donor)
        units = {e['step_id']: e for e in result['events'] if e['type'] in ('unit_cached', 'unit_completed')}
        self.assertEqual(units['ocr:page:1:psm:3']['origin'], 'computed')
        self.assertEqual(units['ocr:page:1:psm:11']['origin'], 'imported_local')
        self.assertEqual(cache.read_text(), '[]')
        self.assertEqual((self.work(target) / 'ocr/page-1-psm3.txt').read_text().strip(), 'OCR 11')

    def test_damaged_or_mismatched_unit_and_dpi_miss_never_credit_donor_compute(self):
        donor = self.run_named('A')
        self.prepare(donor)
        old = self.work(donor)
        cache = old / 'ocr/page-1-psm3-cache.json'
        original = cache.read_bytes()
        for index, damage in enumerate(('output', 'resource', 'command', 'symlink', 'running')):
            with self.subTest(damage=damage):
                cache.write_bytes(original)
                data = json.loads(original)
                candidate = old / 'ocr/page-1-psm3.txt'
                candidate.unlink()
                candidate.write_text('OCR 11\n')
                if damage == 'output':
                    candidate.write_text('untrusted AI result')
                elif damage == 'resource':
                    data['identity']['tesseract'] = 'different nominal version'
                elif damage == 'command':
                    data['identity']['command'][-1] = 'unexpected-option'
                elif damage == 'symlink':
                    other = self.directory / 'linked.txt'
                    other.write_text('OCR 11\n')
                    candidate.unlink(); candidate.symlink_to(other)
                else:
                    data['status'] = 'running'
                cache.write_text(json.dumps(data))
                target = self.run_named('bad-' + str(index))
                result = self.prepare(target, donor)
                units = {e['step_id']: e for e in result['events'] if e['type'] in ('unit_cached', 'unit_completed')}
                self.assertEqual(units['ocr:page:1:psm:3']['origin'], 'computed')
                self.assertEqual(units['ocr:page:1:psm:11']['origin'], 'imported_local')
        target = self.run_named('DPI', dpi=150)
        result = self.prepare(target, donor)
        self.assertEqual([e.get('origin') for e in result['events'] if e['type'] == 'unit_completed'], ['computed'] * 3)
        self.assertTrue(any(e['type'] == 'local_import_rejected' for e in result['events']))
        again = self.prepare(target)
        self.assertEqual([e.get('origin') for e in again['events'] if e['type'] == 'unit_cached'], ['same_run_cache'] * 3)

    def test_destination_symlink_cannot_make_preparation_modify_donor(self):
        donor = self.run_named('A')
        self.prepare(donor)
        target = self.run_named('B')
        (self.work(target) / 'raster').symlink_to(self.work(donor) / 'raster', target_is_directory=True)
        result = self.app.dispatch('start_preparation', {'run_id': target['project']['run_id'],
            'reuse_from_run_id': donor['project']['run_id']})
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'], 'invalid_import_destination')

    def test_comparison_and_donor_reject_different_full_sources(self):
        first = self.run_named('A')
        # Same display filename, genuinely different registered source bytes.
        self.source.write_bytes(b'%PDF-1.4\nsecond controlled metadata source\n%%EOF\n')
        imported = self.call('import_sources', path=str(self.source))
        self.edition = next(e['edition_id'] for e in imported['editions']
            if e['edition_id'] != first['edition_id'])
        second = self.run_named('B')
        for operation, payload, code in (
            ('compare_runs', {'left_run_id': first['project']['run_id'], 'right_run_id': second['project']['run_id']}, 'invalid_comparison'),
            ('start_preparation', {'run_id': second['project']['run_id'], 'reuse_from_run_id': first['project']['run_id']}, 'invalid_donor')):
            result = self.app.dispatch(operation, payload)
            self.assertFalse(result['ok'])
            self.assertEqual(result['error']['code'], code)

    def test_native_import_cannot_override_the_destination_profile_parameters(self):
        donor = self.run_named('A')
        self.prepare(donor)
        target = self.run_named('B')
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/ocr_projects.py'),
            '--root', str(self.root), '--json', 'prepare', target['project']['run_id'],
            '--dpi', '150', '--reuse-from-run-id', donor['project']['run_id']], capture_output=True)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'configuration_changed')
        self.assertFalse((self.work(target) / 'raster/page-1.png').exists())

    def test_native_import_rejects_manifest_and_profile_paths_escaping_registry(self):
        donor = self.run_named('A')
        self.prepare(donor)
        project_path = self.root / donor['artifacts']['project']['path']
        original = project_path.read_bytes()
        external = {}
        for key in ('run_manifest', 'profile_snapshot'):
            path = self.directory / (key + '.json')
            path.write_bytes((self.root / donor['artifacts'][key]['path']).read_bytes())
            external[key] = path
        before = {key: path.read_bytes() for key, path in external.items()}
        for index, key in enumerate(('run_manifest', 'profile_snapshot')):
            with self.subTest(escaping_artifact=key):
                changed = json.loads(original)
                changed['artifacts'][key] = '../' + external[key].name
                project_path.write_text(json.dumps(changed))
                target = self.run_named('escape-' + str(index))
                result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/ocr_projects.py'),
                    '--root', str(self.root), '--json', 'prepare', target['project']['run_id'],
                    '--reuse-from-run-id', donor['project']['run_id']], capture_output=True)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertEqual(json.loads(result.stdout)['error']['code'], 'invalid_donor')
                self.assertFalse((self.work(target) / 'preparation-checkpoint.json').exists())
                self.assertEqual({name: path.read_bytes() for name, path in external.items()}, before)
                project_path.write_bytes(original)


class ComparisonWorkflowTests(unittest.TestCase):
    def test_two_complete_controlled_actions_compare_results_without_inheriting_ai(self):
        """Controlled external peer; no actual model evidence is claimed here."""
        import fitz
        from PIL import Image, ImageDraw, ImageFont
        temporary = tempfile.TemporaryDirectory(prefix='OCR full comparison ')
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        root = directory / 'registry'
        source = directory / 'source.pdf'
        with fitz.open() as document:
            for value in ('ABC', 'DEF'):
                image = Image.new('RGB', (100, 100), 'white')
                ImageDraw.Draw(image).text((2, 0), value, fill='black', font=ImageFont.truetype(
                    environment_manifest(ROOT)['fonts']['segmentation']['path'], 16))
                stream = io.BytesIO(); image.save(stream, format='PNG')
                page = document.new_page(width=24, height=24)
                page.insert_image(page.rect, stream=stream.getvalue())
            document.save(source)
        files = [ROOT / 'tests' / name for name in ('autonomous_app_server_fixture.py',
            'reading_app_server_fixture.py', 'geometry_app_server_fixture.py',
            'codex_app_server_fixture.py', 'context_app_server_fixture.py')]
        runtime = {'kind': 'controlled_process_fixture', 'version': 'comparison-fixture',
            'command': [sys.executable, '-B', str(files[0])],
            'files': [{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}
        context = {'kind': 'controlled_process_fixture', 'package': str(directory), 'node': sys.executable,
            'files': [], 'interpreters': [], 'probe_command': [sys.executable, '-B', '-c',
                'print(\'{"node":"fixture","sqlite_fts5":true}\')']}
        app = Application(root, codex_runtime=runtime, context_runtime=context)
        self.addCleanup(app.close)
        def call(operation, **payload):
            result = app.dispatch(operation, payload)
            self.assertTrue(result['ok'], result)
            return result['data']
        run_ids = []
        for name in ('A', 'B'):
            profile = json.loads((ROOT / 'profiles/faithful-reading.json').read_text())
            profile['prompts']['read'] += '\nVariant ' + name
            path = directory / (name + '.json'); path.write_text(json.dumps(profile))
            selected = call('inspect_profile', path=str(path))
            payload = {'source_path': str(source), 'name': name, 'profile_path': str(path),
                'profile_sha256': selected['sha256'], 'environment': os.environ.get('OCR_ENVIRONMENT')}
            if run_ids:
                payload['reuse_from_run_id'] = run_ids[0]
            started = call('start_autonomous', **payload)
            run_ids.append(started['run_id'])
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                state = call('autonomous_status', run_id=started['run_id'])
                if state['state'] not in ('starting', 'running'):
                    break
                time.sleep(.1)
            self.assertEqual(state['state'], 'completed', state)
        compared = call('compare_runs', left_run_id=run_ids[0], right_run_id=run_ids[1])
        self.assertEqual(compared['runs'][1]['local_origins']['imported_local'], 6)
        for run in compared['runs']:
            self.assertEqual(run['milestones']['validation'], 'ready_with_open_items')
            self.assertEqual(run['milestones']['acceptance'], 'not_recorded')
            self.assertEqual(run['output']['report_provenance']['status'], 'original_turn_verified')
            self.assertTrue(run['output']['reports']['findings']['items'])
            self.assertTrue(any(s['operation'] == 'output_review' for s in run['metrics']['steps']))
        # This peer deliberately reuses literal thread IDs. The comparison must
        # flag it honestly, rather than manufacture an independence claim.
        self.assertEqual(compared['independence'], 'shared_thread_detected')
        left_paths = compared['runs'][0]['ai_context']['context_paths']
        right_paths = compared['runs'][1]['ai_context']['context_paths']
        self.assertTrue(left_paths and right_paths)
        self.assertFalse({p['workspace'] for p in left_paths} & {p['workspace'] for p in right_paths})
        app.close()
        app = Application(root)
        self.assertEqual(call('compare_runs', left_run_id=run_ids[0], right_run_id=run_ids[1]), compared)


if __name__ == '__main__':
    unittest.main()
