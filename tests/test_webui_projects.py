"""Public application scenarios shared with the WebUI request bridge."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.service import Application


class WebUIProjectsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='WebUI starší vydání ')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.registry = self.directory / 'evidence s mezerami'

    def cli(self, *arguments):
        result = subprocess.run(
            [sys.executable, '-S', str(ROOT / 'tools/ocr_projects.py'),
             '--root', str(self.registry), '--json', *map(str, arguments)],
            capture_output=True, check=True)
        return json.loads(result.stdout)

    def legacy_run(self, folder, content, *, new_run=False):
        source = self.directory / folder / 'zpravodaj.pdf'
        source.parent.mkdir(exist_ok=True)
        source.write_bytes(b'%PDF-1.4\n' + content + b'\n%%EOF\n')
        return self.cli('import', source, *(['--new-run'] if new_run else []))

    def test_existing_runs_group_by_content_and_keep_truthful_details_after_restart(self):
        first = self.legacy_run('první', b'first source')
        second = self.legacy_run('první', b'first source', new_run=True)
        collision = self.legacy_run('druhý', b'different source')
        project_file = self.registry / second['artifacts']['project']
        record = json.loads(project_file.read_text())
        record['project'].update(phase='ready_with_open_items', operation_state='completed',
                                 validation='passed', acceptance='not_recorded')
        record['artifacts']['history'] = second['artifacts']['workspace'] + '/history.jsonl'
        project_file.write_text(json.dumps(record), encoding='utf-8')
        (self.registry / record['artifacts']['history']).write_text('{"step":"legacy"}\n')
        (self.registry / second['artifacts']['output_pdf']).write_bytes(b'legacy result')
        before = {p.relative_to(self.registry): p.read_bytes()
                  for p in self.registry.rglob('*') if p.is_file()}

        app = Application(self.registry)
        listing = app.dispatch('projects')
        self.assertTrue(listing['ok'], listing)
        editions = listing['data']['editions']
        self.assertEqual(len(editions), 2)
        same_source = next(e for e in editions if len(e['runs']) == 2)
        self.assertEqual(same_source['edition_id'], first['project']['source_sha256'])
        self.assertEqual({r['run_id'] for r in same_source['runs']},
                         {first['project']['run_id'], second['project']['run_id']})
        self.assertEqual({e['name'] for e in editions}, {'zpravodaj.pdf'})
        self.assertEqual(len({e['edition_id'] for e in editions}), 2)

        selected = app.dispatch('select_run', {'run_id': second['project']['run_id']})
        self.assertTrue(selected['ok'], selected)
        self.assertEqual(selected['data']['project'], record['project'])
        artifacts = selected['data']['artifacts']
        self.assertTrue(artifacts['source']['available'])
        self.assertTrue(artifacts['output_pdf']['available'])
        self.assertTrue(artifacts['history']['available'])
        self.assertFalse(artifacts['output_txt']['available'])
        events = app.dispatch('events', {'after': 0})['data']['events']
        self.assertEqual([e['type'] for e in events], ['projects_changed', 'run_selected'])
        self.assertEqual(events[-1]['run_id'], second['project']['run_id'])

        restarted = Application(self.registry)
        self.assertEqual(restarted.dispatch('projects')['data'], listing['data'])
        self.assertEqual(restarted.dispatch('select_run', {'run_id': first['project']['run_id']})
                         ['data']['project']['validation'], 'not_run')
        self.assertEqual(restarted.dispatch('select_run', {'run_id': collision['project']['run_id']})
                         ['data']['project']['acceptance'], 'not_recorded')
        self.assertEqual({p.relative_to(self.registry): p.read_bytes()
                          for p in self.registry.rglob('*') if p.is_file()}, before)

    def test_open_registry_pages_all_legacy_runs_and_reports_errors_without_changing_data(self):
        runs = [self.legacy_run('první', b'same old source', new_run=True) for _ in range(14)]
        app = Application(self.directory / 'empty registry')
        self.assertEqual(app.dispatch('projects')['data']['editions'], [])
        opened = app.dispatch('open_registry', {'root': str(self.registry)})
        self.assertTrue(opened['ok'], opened)
        self.assertEqual(len(opened['data']['editions'][0]['runs']), 14)
        self.assertEqual(app.dispatch('select_run', {'run_id': 'missing'})['error']['code'],
                         'project_not_found')
        self.assertEqual(app.dispatch('open_registry', {'root': str(self.directory / 'missing')})
                         ['error']['code'], 'registry_missing')
        self.assertEqual(app.dispatch('projects')['data'], opened['data'])
        project_path = self.registry / runs[0]['artifacts']['project']
        project_path.write_text('{broken', encoding='utf-8')
        failed = app.dispatch('select_run', {'run_id': runs[0]['project']['run_id']})
        self.assertFalse(failed['ok'])
        self.assertEqual(failed['error']['code'], 'project_invalid')
        self.assertEqual(project_path.read_text(), '{broken')


if __name__ == '__main__':
    unittest.main()
