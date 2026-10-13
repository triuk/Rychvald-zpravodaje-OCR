"""Project registry behavior at the public process and artifact boundaries."""
from pathlib import Path
import json
import resource
import signal
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'tools' / 'ocr_projects.py'


class ProjectCommandsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='OCR projects ')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / 'vydání s mezerami'
        self.source = self.directory / 'zdroj s mezerami.pdf'
        self.source.write_bytes(b'%PDF-1.4\nsynthetic source scan\n%%EOF\n')

    def command(self, *arguments, expected=0):
        result = subprocess.run([sys.executable, '-S', str(CLI), '--root', str(self.root),
                                 '--json', *map(str, arguments)], capture_output=True)
        self.assertEqual(result.returncode, expected, result.stderr.decode())
        self.assertLessEqual(len(result.stdout), 4096)
        return json.loads(result.stdout.decode('utf-8'))

    def test_import_and_status_register_source_without_ocr_or_claiming_verification(self):
        source_bytes = self.source.read_bytes()
        imported = self.command('import', self.source)
        self.assertEqual(imported['protocol_version'], 1)
        self.assertEqual(imported['operation'], 'import')
        self.assertEqual(imported['status'], 'completed')
        self.assertEqual(imported['project']['original_name'], self.source.name)
        self.assertEqual(imported['project']['phase'], 'registered')
        self.assertEqual(imported['project']['validation'], 'not_run')
        self.assertEqual(imported['counts']['created'], 1)
        self.assertIsNone(imported['error'])
        status = self.command('status', imported['project']['project_id'])
        self.assertEqual(status['project'], imported['project'])
        self.assertEqual((self.root / status['artifacts']['source']).read_bytes(), source_bytes)
        self.assertEqual(self.source.read_bytes(), source_bytes)
        self.assertTrue((self.root / status['artifacts']['workspace']).is_dir())

    def test_duplicate_content_reuses_project_until_new_run_is_explicit(self):
        imported = self.command('import', self.source)
        renamed = self.directory / 'kopie.pdf'
        renamed.write_bytes(self.source.read_bytes())
        reused = self.command('import', renamed)
        self.assertEqual(reused['project'], imported['project'])
        self.assertEqual(reused['counts'], {'created': 0, 'reused': 1})
        independent = self.command('import', self.source, '--new-run')
        self.assertNotEqual(independent['project']['run_id'], imported['project']['run_id'])
        self.assertEqual(independent['project']['source_sha256'], imported['project']['source_sha256'])
        self.assertNotEqual(independent['artifacts']['workspace'], imported['artifacts']['workspace'])
        self.assertNotEqual(independent['artifacts']['output_pdf'], imported['artifacts']['output_pdf'])
        self.assertEqual(self.command('import', self.source)['project'], imported['project'])

    def test_same_filename_different_content_preserves_old_work_outputs_and_prototype(self):
        prototype = self.root / 'experiments' / 'legacy' / 'checks' / 'run-validation.json'
        prototype.parent.mkdir(parents=True)
        prototype.write_text('{"status":"verified"}', encoding='utf-8')
        first = self.command('import', self.source)
        output = self.root / first['artifacts']['output_pdf']
        output.write_bytes(b'old export')
        review = self.root / first['artifacts']['workspace'] / 'review.json'
        review.write_text('{"confirmed":"original"}', encoding='utf-8')
        other_directory = self.directory / 'different directory'
        other_directory.mkdir()
        other = other_directory / self.source.name
        other.write_bytes(b'%PDF-1.4\ndifferent source scan\n%%EOF\n')
        second = self.command('import', other)
        self.assertNotEqual(second['project']['project_id'], first['project']['project_id'])
        self.assertNotEqual(second['artifacts']['source'], first['artifacts']['source'])
        self.assertNotEqual(second['artifacts']['output_pdf'], first['artifacts']['output_pdf'])
        self.assertEqual(output.read_bytes(), b'old export')
        self.assertEqual(review.read_text(), '{"confirmed":"original"}')
        self.assertEqual(prototype.read_text(), '{"status":"verified"}')
        self.assertEqual(second['project']['validation'], 'not_run')
        self.assertEqual(self.command('status', first['project']['project_id'])['project']['validation'], 'not_run')

    def test_large_registry_list_is_paginated_valid_utf8_and_complete(self):
        for index in range(25):
            source = self.directory / f'vydání číslo {index}.pdf'
            source.write_bytes(f'%PDF-1.4\nscan {index}\n%%EOF\n'.encode('utf-8'))
            self.command('import', source)
        projects = []
        offset = 0
        while offset is not None:
            page = self.command('list', '--offset', offset, '--limit', 1000)
            self.assertEqual(page['counts']['total'], 25)
            self.assertEqual(page['counts']['returned'], len(page['projects']))
            projects.extend(item['project_id'] for item in page['projects'])
            offset = page['next_offset']
        self.assertEqual(len(projects), 25)
        self.assertEqual(len(set(projects)), 25)

    def test_interrupted_registry_write_keeps_last_valid_registry_usable(self):
        imported = self.command('import', self.source)
        registry_path = self.root / 'registry.json'
        previous = registry_path.read_bytes()
        different = self.directory / 'next.pdf'
        different.write_bytes(b'%PDF-1.4\nnext scan\n%%EOF\n')

        def constrain_write():
            signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
            resource.setrlimit(resource.RLIMIT_FSIZE, (len(previous) + 50, len(previous) + 50))

        result = subprocess.run([sys.executable, '-S', str(CLI), '--root', str(self.root),
                                 '--json', 'import', str(different)], capture_output=True,
                                preexec_fn=constrain_write)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'io_error')
        self.assertEqual(registry_path.read_bytes(), previous)
        self.assertEqual(self.command('status', imported['project']['project_id'])['project'], imported['project'])
        self.assertEqual(self.command('list')['counts']['total'], 1)
        self.assertEqual(self.command('import', different)['counts']['created'], 1)

    def test_concurrent_imports_do_not_lose_projects_or_duplicate_same_source(self):
        sources = []
        for index in range(8):
            source = self.directory / f'source {index}.pdf'
            source.write_bytes(f'%PDF-1.4\nscan {index}\n%%EOF\n'.encode())
            sources.extend([source, source])
        processes = [subprocess.Popen([sys.executable, '-S', str(CLI), '--root', str(self.root),
                                      '--json', 'import', str(source)], stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE) for source in sources]
        responses = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, stderr.decode())
            responses.append(json.loads(stdout))
        self.assertEqual(sum(value['counts']['created'] for value in responses), 8)
        self.assertEqual(sum(value['counts']['reused'] for value in responses), 8)
        self.assertEqual(self.command('list')['counts']['total'], 8)

    def test_source_in_registry_can_be_imported_as_independent_run_without_overwriting(self):
        imported = self.command('import', self.source)
        registered_source = self.root / imported['artifacts']['source']
        again = self.command('import', registered_source, '--new-run')
        self.assertNotEqual(again['project']['run_id'], imported['project']['run_id'])
        self.assertEqual(registered_source.read_bytes(), self.source.read_bytes())

    def test_folder_import_returns_small_summary_and_lists_all_pdf_projects(self):
        directory = self.directory / 'incoming publications'
        directory.mkdir()
        (directory / 'a.pdf').write_bytes(self.source.read_bytes())
        (directory / 'b.PDF').write_bytes(b'%PDF-1.4\nother scan\n%%EOF\n')
        (directory / 'notes.txt').write_text('preserve this note')
        result = self.command('import', directory)
        self.assertEqual(result['counts'], {'sources': 2, 'created': 2, 'reused': 0})
        self.assertIsNone(result['project'])
        self.assertEqual(result['artifacts']['registry'], 'registry.json')
        self.assertEqual(self.command('import', directory)['counts']['reused'], 2)
        listing = self.command('list')
        self.assertEqual({item['original_name'] for item in listing['projects']}, {'a.pdf', 'b.PDF'})
        self.assertEqual((directory / 'notes.txt').read_text(), 'preserve this note')

    def test_invalid_inputs_and_broken_registry_use_stable_json_errors(self):
        self.assertEqual(self.command('import', self.directory / 'missing.pdf', expected=1)['error']['code'], 'source_missing')
        invalid = self.directory / 'not a PDF.pdf'
        invalid.write_bytes(b'not a PDF')
        self.assertEqual(self.command('import', invalid, expected=1)['error']['code'], 'invalid_source')
        self.assertEqual(self.command('status', '../../other', expected=1)['error']['code'], 'project_not_found')
        self.assertEqual(self.command('list', '--limit', 0, expected=1)['error']['code'], 'invalid_selection')
        self.assertEqual(self.command('list', '--limit', 'invalid', expected=1)['error']['code'], 'invalid_arguments')
        imported = self.command('import', self.source)
        project_path = self.root / imported['artifacts']['project']
        project_path.write_text('{broken', encoding='utf-8')
        self.assertEqual(self.command('status', imported['project']['project_id'], expected=1)['error']['code'], 'project_invalid')
        registry = self.root / 'registry.json'
        registry.write_text('{broken', encoding='utf-8')
        previous = registry.read_bytes()
        self.assertEqual(self.command('list', expected=1)['error']['code'], 'registry_invalid')
        self.assertEqual(self.command('import', self.source, expected=1)['error']['code'], 'registry_invalid')
        self.assertEqual(registry.read_bytes(), previous)

    def test_per_project_transaction_lock_is_live_exclusive_and_publishes_state_atomically(self):
        imported = self.command('import', self.source)
        identifier = imported['project']['project_id']
        hold_code = '''
import sys
sys.path.insert(0, sys.argv[1])
from ocr_projects import ProjectRegistry
registry = ProjectRegistry(sys.argv[2])
with registry.project_lock(sys.argv[3]) as record:
    print('locked', flush=True)
    sys.stdin.readline()
    record['project']['phase'] = 'prepared'
    record['project']['operation_state'] = 'completed'
    record['counts']['pages'] = 2
'''
        holder = subprocess.Popen([sys.executable, '-S', '-c', hold_code, str(ROOT / 'tools'),
                                   str(self.root), identifier], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), 'locked')
            self.assertEqual(self.command('status', identifier)['project']['operation_state'], 'running')
            other_code = '''
import sys
sys.path.insert(0, sys.argv[1])
from ocr_projects import ProjectRegistry, ProjectError
try:
    with ProjectRegistry(sys.argv[2]).project_lock(sys.argv[3]):
        sys.exit(3)
except ProjectError as error:
    print(error.code)
'''
            contender = subprocess.run([sys.executable, '-S', '-c', other_code, str(ROOT / 'tools'),
                                        str(self.root), identifier], capture_output=True, text=True)
            self.assertEqual(contender.stdout.strip(), 'project_busy')
            self.assertEqual(contender.returncode, 0, contender.stderr)
            stdout, stderr = holder.communicate('continue\n', timeout=10)
            self.assertEqual(holder.returncode, 0, stderr)
        finally:
            if holder.poll() is None:
                holder.kill()
            if holder.stdin and not holder.stdin.closed:
                holder.communicate()
        result = self.command('status', identifier)
        self.assertEqual(result['project']['phase'], 'prepared')
        self.assertEqual(result['project']['validation'], 'not_run')
        self.assertEqual(result['project']['operation_state'], 'completed')
        self.assertEqual(result['counts']['pages'], 2)

    def test_killed_operation_releases_lock_and_aborted_edit_keeps_previous_state(self):
        imported = self.command('import', self.source)
        identifier = imported['project']['project_id']
        code = '''
import sys
sys.path.insert(0, sys.argv[1])
from ocr_projects import ProjectRegistry
with ProjectRegistry(sys.argv[2]).project_lock(sys.argv[3]) as record:
    record['project']['phase'] = 'uncommitted'
    print('locked', flush=True)
    sys.stdin.readline()
'''
        holder = subprocess.Popen([sys.executable, '-S', '-c', code, str(ROOT / 'tools'),
                                   str(self.root), identifier], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), 'locked')
            holder.kill()
            holder.communicate(timeout=10)
        finally:
            if holder.poll() is None:
                holder.kill()
            if holder.stdin and not holder.stdin.closed:
                holder.communicate()
        self.assertEqual(self.command('status', identifier)['project'], imported['project'])

        abort_code = '''
import sys
sys.path.insert(0, sys.argv[1])
from ocr_projects import ProjectRegistry
try:
    with ProjectRegistry(sys.argv[2]).project_lock(sys.argv[3]) as record:
        record['project']['phase'] = 'also uncommitted'
        raise RuntimeError('abort')
except RuntimeError:
    pass
'''
        result = subprocess.run([sys.executable, '-S', '-c', abort_code, str(ROOT / 'tools'),
                                 str(self.root), identifier], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.command('status', identifier)['project'], imported['project'])

    def test_reimport_detects_corrupted_managed_source_without_replacing_it(self):
        imported = self.command('import', self.source)
        managed = self.root / imported['artifacts']['source']
        managed.write_bytes(b'externally damaged source')
        result = self.command('import', self.source, expected=1)
        self.assertEqual(result['error']['code'], 'source_corrupt')
        self.assertEqual(managed.read_bytes(), b'externally damaged source')



if __name__ == '__main__':
    unittest.main()
