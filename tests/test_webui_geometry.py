"""Geometry preparation at the application's public request/artifact seam."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import test_webui_reading as reading_fixture


class GeometryTests(unittest.TestCase):
    setUp = reading_fixture.WebUIReadingTests.setUp

    def test_geometry_requires_a_verified_first_reading_before_any_preparation(self):
        result = self.app.dispatch('start_geometry', {'run_id': self.identifier})
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['error']['code'], 'geometry_reading_required')
        self.assertFalse((self.work / 'geometry-preparation.json').exists())


if __name__ == '__main__':
    unittest.main()
