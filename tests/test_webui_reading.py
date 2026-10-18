"""First visual reading through the same public operations used by the GUI."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.service import Application


class WebUIReadingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='První vizuální čtení ')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.root = self.directory / 'registry'
        self.app = Application(self.root)
        self.addCleanup(lambda: self.app.close())
        source = self.directory / 'source.pdf'
        source.write_bytes(b'%PDF-1.4\ncontrolled reading source\n%%EOF\n')
        edition = self.app.dispatch('import_sources', {'path': str(source)})['data']['editions'][0]
        profile = self.app.dispatch('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})['data']
        self.run = self.app.dispatch('create_run', {'edition_id': edition['edition_id'], 'name': 'Vizuální čtení',
            'profile_path': profile['path'], 'profile_sha256': profile['sha256']})['data']
        self.identifier = self.run['project']['run_id']
        self.work = self.root / self.run['artifacts']['workspace']['path']

    def test_unprepared_source_and_missing_real_preflight_never_submit_a_reading_turn(self):
        missing = self.app.dispatch('start_reading', {'run_id': self.identifier})
        self.assertFalse(missing['ok'])
        self.assertEqual(missing['error']['code'], 'reading_preflight_required')
        status = self.app.dispatch('reading_status', {'run_id': self.identifier})
        self.assertTrue(status['ok'], status)
        self.assertEqual(status['data']['state'], 'not_started')
        self.assertFalse((self.work / 'review.json').exists())


if __name__ == '__main__':
    unittest.main()
