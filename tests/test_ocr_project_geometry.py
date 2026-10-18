"""Native geometry data contract, using independently rendered source fixtures."""
import unittest
import test_ocr_project_export as export_fixture


class NativeGeometryTests(unittest.TestCase):
    setUp = export_fixture.ProjectExportTests.setUp
    command = export_fixture.ProjectExportTests.command
    workflow = export_fixture.ProjectExportTests.workflow
    put = export_fixture.ProjectExportTests.put
    get = export_fixture.ProjectExportTests.get

    def test_prepared_geometry_binds_original_samples_and_requires_actual_examination(self):
        samples = (self.work / 'samples.json').read_bytes()
        result = self.command('prepare-geometry', self.identifier, '--samples', self.work / 'samples.json')
        self.assertEqual(result['project']['phase'], 'geometry_prepared')
        packet = self.get('geometry-preparation.json')
        self.assertEqual(packet['status'], 'prepared_unexamined')
        self.assertTrue(packet['images'])
        self.assertEqual(packet['logical_units'][0]['line_ids'], self.get('review.json')['units'][0]['line_ids'])
        self.assertEqual((self.work / 'samples.json').read_bytes(), samples)
        self.command('verify-geometry', self.identifier, '--prepared')
        packet['identity']['run_id'] = 'foreign-run'
        self.put('geometry-preparation.json', packet)
        swapped = self.command('verify-geometry', self.identifier, '--prepared', expected=1)
        self.assertEqual(swapped['error']['code'], 'geometry_invalid')
        packet['identity']['run_id'] = self.identifier
        self.put('geometry-preparation.json', packet)
        self.command('verify-geometry', self.identifier, '--prepared')
        missing = self.command('verify-geometry', self.identifier, expected=1)
        self.assertEqual(missing['error']['code'], 'geometry_invalid')
        self.put('samples.json', [{'id': 'adapted', 'page': 1, 'bbox': [0, 0, 900, 220],
            'expected': 'WRONG', 'expected_origin': 'Export output'}])
        stale = self.command('verify-geometry', self.identifier, '--prepared', expected=1)
        self.assertEqual(stale['error']['code'], 'geometry_invalid')


if __name__ == '__main__':
    unittest.main()
