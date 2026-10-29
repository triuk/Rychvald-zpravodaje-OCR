"""Path selection uses the same public request seam as manually entered paths."""

from pathlib import Path
import json
import shutil
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.service import Application
from app.application import WebUIApplication


class RequestEvent:
    def __init__(self, payload):
        import json
        self.value = json.dumps({'operation': 'choose_path', 'payload': payload})

    def get_string(self):
        return self.value

    def return_string(self, value):
        import json
        self.result = json.loads(value)


class PathPickerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='Výběr cest ')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def test_selected_pdf_with_spaces_and_accents_can_be_imported(self):
        source = self.directory / 'Staré vydání.pdf'
        source.write_bytes(b'%PDF-1.4\nsource\n%%EOF\n')
        app = Application(self.directory / 'evidence', path_picker=lambda kind, current: str(source))
        self.addCleanup(app.close)
        selected = app.dispatch('choose_path', {'kind': 'source_pdf', 'current_path': ''})
        self.assertTrue(selected['ok'], selected)
        self.assertFalse(selected['data']['cancelled'])
        imported = app.dispatch('import_sources', {'path': selected['data']['path']})
        self.assertTrue(imported['ok'], imported)
        self.assertEqual(app.dispatch('projects')['data']['editions'][0]['name'], 'Staré vydání.pdf')

    def test_desktop_bridge_selects_a_manifest_without_starting_work(self):
        manifest = self.directory / 'Ověřené prostředí.json'
        manifest.write_text('{}')
        desktop = WebUIApplication(self.directory / 'evidence', path_picker=lambda kind, current: manifest)
        self.addCleanup(desktop.api.close)
        event = RequestEvent({'kind': 'environment_manifest', 'current_path': 'old.json'})
        desktop.request(event)
        self.assertTrue(event.result['ok'], event.result)
        self.assertEqual(event.result['data']['path'], str(manifest))
        self.assertEqual(desktop.api.dispatch('events')['data']['events'], [])

    def test_cancelling_retains_the_exact_existing_path_and_does_not_change_registry(self):
        app = Application(self.directory / 'evidence', path_picker=lambda kind, current: None)
        self.addCleanup(app.close)
        before = app.dispatch('projects')['data']
        previous = '  /dřívější složka/profil.json  '
        result = app.dispatch('choose_path', {'kind': 'profile', 'current_path': previous})
        self.assertEqual(result['data'], {'kind': 'profile', 'path': previous, 'cancelled': True})
        self.assertEqual(app.dispatch('projects')['data'], before)

    def test_directory_and_profile_choices_feed_the_existing_public_operations(self):
        sources = self.directory / 'Vstupní složka'
        sources.mkdir()
        (sources / 'první.pdf').write_bytes(b'%PDF-1.4\none\n%%EOF\n')
        profile = self.directory / 'Vlastní profil.json'
        shutil.copyfile(ROOT / 'profiles/faithful-reading.json', profile)
        paths = {'source_directory': sources, 'registry_directory': self.directory / 'evidence', 'profile': profile}
        app = Application(paths['registry_directory'], path_picker=lambda kind, current: paths[kind])
        self.addCleanup(app.close)
        selected = app.dispatch('choose_path', {'kind': 'source_directory'})
        self.assertTrue(app.dispatch('import_sources', {'path': selected['data']['path']})['ok'])
        selected = app.dispatch('choose_path', {'kind': 'registry_directory'})
        self.assertTrue(app.dispatch('open_registry', {'root': selected['data']['path']})['ok'])
        selected = app.dispatch('choose_path', {'kind': 'profile'})
        inspected = app.dispatch('inspect_profile', {'path': selected['data']['path']})
        self.assertTrue(inspected['ok'], inspected)
        self.assertEqual(inspected['data']['profile'], json.loads(profile.read_text()))

    def test_invalid_type_missing_path_and_malformed_requests_have_public_errors(self):
        wrong = self.directory / 'poznámky.txt'
        wrong.write_text('not a PDF')
        for chosen, kind in [(wrong, 'source_pdf'), (wrong, 'profile'),
                             (wrong, 'source_directory'), (self.directory, 'environment_manifest'),
                             (self.directory / 'missing.pdf', 'source_pdf')]:
            with self.subTest(chosen=chosen, kind=kind):
                app = Application(self.directory / 'evidence', path_picker=lambda *args: chosen)
                self.addCleanup(app.close)
                result = app.dispatch('choose_path', {'kind': kind})
                self.assertFalse(result['ok'], result)
                self.assertEqual(result['error']['code'], 'path_invalid')
        for payload in [None, [], {'kind': 'unknown'}, {'kind': 'source_pdf', 'current_path': []}]:
            self.assertEqual(app.dispatch('choose_path', payload)['error']['code'], 'invalid_request')

    def test_open_dialog_does_not_block_status_queries(self):
        opened, release = threading.Event(), threading.Event()

        def picker(kind, current):
            opened.set()
            release.wait(5)
            return None

        app = Application(self.directory / 'evidence', path_picker=picker)
        self.addCleanup(app.close)
        worker = threading.Thread(target=lambda: app.dispatch('choose_path', {'kind': 'source_pdf'}))
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(release.set)
        self.assertTrue(opened.wait(2))
        query = threading.Event()
        query_worker = threading.Thread(target=lambda: (app.dispatch('events'), query.set()))
        query_worker.start()
        self.addCleanup(query_worker.join)
        self.assertTrue(query.wait(2), 'Status must remain available while a native dialog waits.')
        release.set()


if __name__ == '__main__':
    unittest.main()
