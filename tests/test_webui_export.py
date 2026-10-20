"""Autonomous public GUI dispatch with real native PDF work and a controlled peer.

The peer is explicitly synthetic protocol evidence, never actual model acceptance.
"""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.service import Application


class AutonomousExportTests(unittest.TestCase):
    def setUp(self):
        import fitz
        from PIL import Image, ImageDraw, ImageFont
        temporary = tempfile.TemporaryDirectory(prefix='Autonomous first export ')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.root = self.directory / 'registry'
        self.source = self.directory / 'source.pdf'
        with fitz.open() as document:
            for text in ('ABC', 'DEF'):
                image = Image.new('RGB', (100, 100), 'white')
                ImageDraw.Draw(image).text((2, 0), text, fill='black',
                    font=ImageFont.truetype('/usr/share/fonts/noto/NotoSerif-Regular.ttf', 16))
                stream = io.BytesIO(); image.save(stream, format='PNG')
                page = document.new_page(width=24, height=24)
                page.insert_image(page.rect, stream=stream.getvalue())
            document.save(self.source)
        fixture = ROOT / 'tests/autonomous_app_server_fixture.py'
        files = [fixture, *[ROOT / 'tests' / name for name in
            ('reading_app_server_fixture.py', 'geometry_app_server_fixture.py',
             'codex_app_server_fixture.py', 'context_app_server_fixture.py')]]
        runtime = {'kind': 'controlled_process_fixture', 'version': 'autonomous-fixture-17',
            'command': [sys.executable, '-B', str(fixture)],
            'files': [{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                      for p in files if p.exists()]}
        context = {'kind': 'controlled_process_fixture', 'package': str(self.directory), 'node': sys.executable,
            'files': [], 'interpreters': [], 'probe_command': [sys.executable, '-B', '-c',
                'print(\'{"node":"fixture","sqlite_fts5":true}\')']}
        self.runtime, self.context = runtime, context
        self.app = Application(self.root, codex_runtime=runtime, context_runtime=context)
        self.addCleanup(lambda: self.app.close())

    def peer(self, mode):
        self.app.close()
        wrapper = self.directory / (mode + '.py')
        wrapper.write_text('import runpy,sys\nsys.argv.insert(1,' + repr(mode) + ')\nrunpy.run_path(' +
            repr(str(ROOT / 'tests/autonomous_app_server_fixture.py')) + ',run_name="__main__")\n')
        runtime = {**self.runtime, 'command': [sys.executable, '-B', str(wrapper)],
            'files': [*self.runtime['files'], {'path': str(wrapper),
                'sha256': hashlib.sha256(wrapper.read_bytes()).hexdigest()}]}
        self.app = Application(self.root, codex_runtime=runtime, context_runtime=self.context)

    def wait_output(self, identifier):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            response = self.app.dispatch('output_review_status', {'run_id': identifier})
            self.assertTrue(response['ok'], response)
            if response['data']['state'] not in ('starting', 'running'):
                return response['data']
            time.sleep(.05)
        self.fail('Output review did not finish')

    def test_one_public_action_drives_source_to_actual_export_reports_and_truthful_validation(self):
        source_bytes = self.source.read_bytes()
        profile = self.app.dispatch('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})['data']
        started = self.app.dispatch('start_autonomous', {'source_path': str(self.source), 'name': 'First autonomous',
            'profile_path': profile['path'], 'profile_sha256': profile['sha256'],
            'environment': os.environ.get('OCR_ENVIRONMENT')})
        self.assertTrue(started['ok'], started)
        identifier = started['data']['run_id']
        blocked = self.app.dispatch('start_preparation', {'run_id': identifier})
        self.assertFalse(blocked['ok'])
        self.assertEqual(blocked['error']['code'], 'operation_active')
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            response = self.app.dispatch('autonomous_status', {'run_id': identifier})
            self.assertTrue(response['ok'], response)
            status = response['data']
            if status['state'] not in ('starting', 'running'):
                break
            time.sleep(.1)
        self.assertEqual(status['state'], 'completed', status)
        detail = self.app.dispatch('select_run', {'run_id': identifier})['data']
        self.assertEqual(detail['project']['operation_state'], 'completed')
        self.assertEqual(detail['project']['validation'], 'ready_with_open_items')
        self.assertEqual(detail['project']['acceptance'], 'not_recorded')
        work = self.root / detail['artifacts']['workspace']['path']
        # The controlled reader declares two distinct articles. The documented
        # article boundary is three LF; paragraphs within one article use two.
        self.assertEqual((self.root / detail['artifacts']['output_txt']['path']).read_bytes(), b'ABC\n\n\nDEF\n')
        self.assertEqual(self.source.read_bytes(), source_bytes)
        self.assertTrue((self.root / detail['artifacts']['output_pdf']['path']).is_file())
        publication = json.loads((work / 'output-review-publication.json').read_text())
        self.assertEqual(json.loads(Path(publication['preparation']).read_text())['protected_findings'], [])
        self.assertEqual(publication['reports']['visual_review']['geometry_status'],
                         'approximation_requires_character_review')
        self.assertIn('Controlled actual exported page inspection', publication['reports']['visual_review']['conclusion'])
        self.assertTrue(any(row['id'] == 'geometry/approximation' and row['status'] == 'open'
                            for row in publication['reports']['findings']['items']))
        steps = [row['stage'] for row in status['stages']]
        self.assertEqual(steps, ['prepare', 'model_diagnostic', 'context_diagnostic', 'reading', 'geometry',
                                 'export', 'output_review', 'validate'])
        denied = self.app.dispatch('open_output_artifact', {'run_id': identifier, 'path': '../../private.pdf'})
        self.assertFalse(denied['ok'], denied)
        results = self.app.dispatch('output_results', {'run_id': identifier})
        self.assertTrue(results['ok'], results)
        self.assertTrue(results['data']['available'])
        metrics = self.app.dispatch('run_metrics', {'run_id': identifier})
        self.assertTrue(metrics['ok'], metrics)
        output_steps = [row for row in metrics['data']['steps'] if row['operation'] == 'output_review']
        self.assertEqual(len(output_steps), 1)
        self.assertEqual(output_steps[0]['tokens']['values']['noncached_input'], 103)

        # Explicit current-export resume keeps the disclosed PDF/TXT and prior
        # source/geometry turns; a stale manifest must never submit another turn.
        prepared = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/ocr_projects.py'),
            '--root', str(self.root), '--json', 'prepare-output-review', identifier], capture_output=True)
        self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
        selected = self.app.dispatch('output_results', {'run_id': identifier})['data']['prepared_resume']
        self.assertIsNotNone(selected)
        unchanged = {str(path): path.read_bytes() for path in [work / 'output-manifest.json',
            *list((work / 'application/reading-attempts').rglob('protocol.jsonl')),
            *list((work / 'application/geometry-attempts').rglob('protocol.jsonl'))]}
        stale = self.app.dispatch('start_first_export', {'run_id': identifier, **selected,
            'existing_export_sha256': '0' * 64})
        self.assertFalse(stale['ok'], stale)
        self.assertEqual(stale['error']['code'], 'output_review_invalid')
        resumed = self.app.dispatch('start_first_export', {'run_id': identifier, **selected,
            'environment': os.environ.get('OCR_ENVIRONMENT')})
        self.assertTrue(resumed['ok'], resumed)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            continued = self.app.dispatch('autonomous_status', {'run_id': identifier})['data']
            if continued['state'] not in ('starting', 'running'):
                break
            time.sleep(.05)
        self.assertEqual(continued['state'], 'completed', continued)
        self.assertEqual([row['stage'] for row in continued['stages']], ['export', 'output_review', 'validate'])
        for name, data in unchanged.items():
            self.assertEqual(Path(name).read_bytes(), data)

        # Absolute aliases identify the very same attached pixels/frozen input,
        # including a frozen template whose label differs from its bound path.
        self.peer('absolute_input_evidence')
        self.assertTrue(self.app.dispatch('start_output_review', {'run_id': identifier})['ok'])
        aliased = self.wait_output(identifier)
        self.assertEqual(aliased['state'], 'completed', aliased)
        published = json.loads((work / 'output-review-publication.json').read_text())
        original = json.loads(Path(published['original_proposal']['path']).read_text())
        self.assertEqual(published['reports']['visual_review'], original['visual_review'])
        self.assertTrue(all(Path(name).is_absolute() for name in original['visual_review']['evidence']))

        # Reuse the public output-review seam after a completed export. These
        # process peers deliberately return original, completed but unacceptable
        # JSON or change an attached image; none may overwrite valid reports.
        for mode in ('waive_output', 'drop_output', 'template_output', 'outside_evidence', 'tamper_output', 'tamper_geometry'):
            with self.subTest(mode=mode):
                before = {name: (work / name).read_bytes() for name in
                    ('checks/visual-review.json', 'checks/findings.json', 'output-review-publication.json')}
                self.peer(mode)
                response = self.app.dispatch('start_output_review', {'run_id': identifier,
                    'environment': os.environ.get('OCR_ENVIRONMENT')})
                self.assertTrue(response['ok'], response)
                rejected = self.wait_output(identifier)
                self.assertEqual(rejected['state'], 'failed', rejected)
                self.assertFalse(rejected.get('output_review_complete'))
                for name, data in before.items():
                    self.assertEqual((work / name).read_bytes(), data)


if __name__ == '__main__':
    unittest.main()
