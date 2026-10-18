"""Public package builder/installer seams; installed workflow is never skipped."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from native_fixtures import bundle_source

ROOT = Path(__file__).resolve().parents[1]


class BundleInputTests(unittest.TestCase):
    def test_changed_locked_input_is_rejected_before_bundle_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            fixture_root, _ = bundle_source(ROOT, directory)
            lock = json.loads((fixture_root / 'native/bundle-inputs.json').read_text())
            source = directory / 'inputs'
            source.mkdir()
            archive = source / lock['python_archive']['sha256']
            archive.write_bytes(b'changed input')
            output = directory / 'bundle.tar.gz'
            result = subprocess.run([sys.executable, '-B', str(fixture_root / 'tools/ocr_bundle.py'),
                                     'build', '--inputs', str(source), '--output', str(output)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)['error']['code'], 'input_mismatch')
            self.assertFalse(output.exists())

    def test_wrong_archive_hash_preserves_existing_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            archive = directory / 'package.tar.gz'
            archive.write_bytes(b'wrong archive')
            install = directory / 'installed'
            install.mkdir()
            sentinel = install / 'existing'
            sentinel.write_bytes(b'preserved')
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/ocr_bundle.py'),
                                     'install', '--archive', str(archive), '--sha256', '0' * 64,
                                     '--destination', str(install)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)['error']['code'], 'archive_mismatch')
            self.assertEqual(sentinel.read_bytes(), b'preserved')


class InstalledBundleTests(unittest.TestCase):
    def test_mandatory_clean_installed_project_workflow(self):
        artifacts = Path(os.environ.get('OCR_BUNDLE_ARTIFACTS', '/tmp/rychvald-native-artifacts'))
        inputs = Path(os.environ.get('OCR_BUNDLE_INPUTS', str(artifacts / 'inputs')))
        with tempfile.TemporaryDirectory() as temporary:
            fixture_root, selection = bundle_source(ROOT, Path(temporary))
            result = subprocess.run([sys.executable, '-B', str(fixture_root / 'tools/verify_linux_bundle.py'),
                                     '--inputs', str(inputs), '--artifacts', str(artifacts)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            evidence = json.loads(result.stdout)
            self.assertEqual(evidence['status'], 'completed')
            self.assertEqual(set(evidence['criteria']), {f'A{number}' for number in range(1, 12)})
            self.assertTrue(all(evidence['criteria'].values()))
            self.assertFalse(evidence['host_usr_visible'])
            self.assertFalse(evidence['host_home_visible'])
            proof = Path(evidence['artifact_directory'])
            installed = Path(evidence['installation'])
            self.assertEqual(json.loads((installed / 'provenance/input-lock.json').read_text()),
                             json.loads((fixture_root / 'native/bundle-inputs.json').read_text()))
            self.assertEqual(json.loads((installed / 'provenance/application-files.json').read_text()),
                             {name: digest for name, digest in selection['source_files'].items()
                              if name.startswith('tools/')})
            for copied, original in [(installed / 'bootstrap.py', 'native/bundle_bootstrap.py'),
                                     (proof / 'fixture.py', 'tests/bundle_workflow_fixture.py')]:
                self.assertEqual(hashlib.sha256(copied.read_bytes()).hexdigest(), selection['source_files'][original])
            (proof / 'fixture-input-selection.json').write_text(json.dumps(selection, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
