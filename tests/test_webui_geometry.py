"""Geometry preparation at the application's public request/artifact seam."""
from pathlib import Path
import sys
import unittest
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import test_webui_reading as reading_fixture


class GeometryTests(unittest.TestCase):
    setUp = reading_fixture.WebUIReadingTests.setUp
    peer = reading_fixture.WebUIReadingTests.peer
    put = reading_fixture.WebUIReadingTests.put
    wait = reading_fixture.WebUIReadingTests.wait

    def test_geometry_requires_a_verified_first_reading_before_any_preparation(self):
        result = self.app.dispatch('start_geometry', {'run_id': self.identifier})
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['error']['code'], 'geometry_reading_required')
        self.assertFalse((self.work / 'geometry-preparation.json').exists())

    def test_native_geometry_patch_preserves_historical_reading_and_rejects_stale_cas(self):
        self.peer()
        self.assertTrue(self.app.dispatch('start_reading', {'run_id': self.identifier})['ok'])
        reading = self.wait()
        self.assertTrue(reading['reading_complete'], reading)
        original = json.loads((self.work / 'review.json').read_text())
        line = dict(original['lines'][0], selection_region=[1, 1, 89, 19])
        payload = {'run_id': self.identifier, 'expected_review_sha256': reading['review_sha256'],
            'patch': {'lines': [{'line': line}]}}
        changed = self.app.dispatch('patch_geometry', payload)
        self.assertTrue(changed['ok'], changed)
        historical = self.app.dispatch('reading_status', {'run_id': self.identifier})['data']
        self.assertTrue(historical['reading_complete'], historical)
        self.assertFalse(historical['current_review_bound'])
        self.assertEqual(historical['review_sha256'], reading['review_sha256'])
        stale = self.app.dispatch('patch_geometry', payload)
        self.assertFalse(stale['ok'], stale)
        self.assertEqual(stale['error']['code'], 'review_changed')


if __name__ == '__main__':
    unittest.main()
