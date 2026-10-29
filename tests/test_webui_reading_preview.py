"""Original reading preview survives actual public correction and application restart."""
import json
from pathlib import Path
import shutil
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import test_webui_corrections as scenarios


class ReadingPreviewTests(unittest.TestCase):
    setUp = scenarios.CorrectionTests.setUp
    start = scenarios.CorrectionTests.start
    wait = scenarios.CorrectionTests.wait
    correction = scenarios.CorrectionTests.correction

    def preview(self):
        result = self.app.dispatch('phase_preview', {'run_id': self.identifier,
            'edition_id': self.detail['edition_id'], 'phase': 'reading', 'page': 1})
        self.assertTrue(result['ok'], result)
        return result['data']

    def test_first_reading_remains_original_after_controlled_correction_restart_and_legacy_lookup(self):
        self.start()
        before = self.preview()
        self.assertEqual(before['state'], 'available', before)
        self.assertTrue(any(region['text'] == 'AXC' for region in before['overlays']), before['overlays'])
        self.assertTrue(all(region['kind'] == 'first_reading' for region in before['overlays']))
        status = self.correction()
        self.assertEqual(status['state'], 'completed', status)
        current = json.loads((self.work / 'review.json').read_text())
        self.assertTrue(any(line['text'] == 'ABC' for line in current['lines']))
        self.assertEqual(self.preview()['overlays'], before['overlays'])
        self.assertEqual(self.preview()['identity'], before['identity'])
        runtime, context = self.app.corrections.runtime, self.context
        self.app.close()
        from app.service import Application
        self.app = Application(self.root, codex_runtime=runtime, context_runtime=context)
        after = self.preview()
        self.assertEqual(after['identity'], before['identity'])
        self.assertEqual(after['overlays'], before['overlays'])
        attempts = len(list((self.work / 'application/reading-attempts').glob('*/attempt.json')))
        # Existing projects can retain the original completed proposal without
        # the new dedicated preview archive. No current-review fallback is used.
        shutil.rmtree(self.work / 'phase-previews/reading')
        historical = self.preview()
        self.assertEqual(historical['state'], 'available', historical)
        self.assertEqual(historical['overlays'], before['overlays'])
        (self.work / 'application/reading-attempts').rename(self.work / 'application/retained-reading-attempts')
        missing = self.preview()
        self.assertEqual(missing['state'], 'historical_missing', missing)
        self.assertEqual(missing['overlays'], [])
        self.assertEqual(len(list((self.work / 'application/retained-reading-attempts').glob('*/attempt.json'))), attempts)
        self.assertFalse((self.work / 'application/reading-attempts').exists())
