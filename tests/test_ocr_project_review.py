"""Selective reading and review transactions through the public process boundary."""
from pathlib import Path
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'tools/ocr_projects.py'


class ProjectReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='OCR review ')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / 'projekty s mezerami'
        source = self.directory / 'scan.pdf'
        source.write_bytes(b'%PDF-1.4\nsynthetic source scan\n%%EOF\n')
        imported = self.command('import', source)
        self.identifier = imported['project']['project_id']
        self.work = self.root / imported['artifacts']['workspace']
        self.review = {'source_sha256': imported['project']['source_sha256'],
                       'lines': [{'id': 'line-a', 'candidate_id': 'candidate-a', 'page': 1,
                                  'text': 'ABC', 'selection_region': [0, 0, 100, 20],
                                  'source_crop': 'crop.png', 'decision_basis': 'synthetic source reading',
                                  'text_status': 'visually_confirmed'},
                                 {'id': 'line-b', 'candidate_id': 'candidate-b', 'page': 2,
                                  'text': 'DEF', 'selection_region': [0, 0, 100, 20],
                                  'source_crop': 'crop.png', 'decision_basis': 'synthetic source reading',
                                  'text_status': 'visually_confirmed'}],
                       'units': [{'id': 'unit-a', 'article': 'article-a', 'page': 1, 'tag': 'P', 'line_ids': ['line-a']},
                                 {'id': 'unit-b', 'article': 'article-b', 'page': 2, 'tag': 'P', 'line_ids': ['line-b']}],
                       'dropped_candidates': [], 'unresolved': [], 'publisher_errors': [], 'risk_register': []}
        self.put('review.json', self.review)
        self.put('input-manifest.json', {'source_sha256': imported['project']['source_sha256'],
                                        'pages': [{'page': 1, 'raster_size': [100, 100]},
                                                  {'page': 2, 'raster_size': [100, 100]}]})
        self.put('local-candidates.json', [{'id': 'region-a', 'page': 1, 'lines': [{'id': 'candidate-a', 'page': 1, 'text': 'ABC'}]},
                                           {'id': 'region-b', 'page': 2, 'lines': [{'id': 'candidate-b', 'page': 2, 'text': 'DEF'}]}])
        (self.work / 'crop.png').write_bytes(b'synthetic proof crop')

    def command(self, *arguments, expected=0):
        process = subprocess.run([sys.executable, '-S', str(CLI), '--root', str(self.root),
                                  '--json', *map(str, arguments)], capture_output=True)
        self.assertEqual(process.returncode, expected, process.stdout.decode() + process.stderr.decode())
        self.assertLessEqual(len(process.stdout), 4096)
        return json.loads(process.stdout.decode('utf-8'))

    def put(self, relative, value):
        path = self.work / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return path

    def test_selective_transcript_query_returns_source_links_and_does_not_modify_review(self):
        before = (self.work / 'review.json').read_bytes()
        result = self.command('query', self.identifier, 'transcript', '--page', 2, '--id', 'line-b')
        self.assertEqual(result['operation'], 'query')
        self.assertEqual(result['protocol_version'], 1)
        self.assertEqual(result['view'], 'transcript')
        self.assertEqual(result['counts']['returned'], 1)
        self.assertEqual(result['rows'][0]['id'], 'line-b')
        self.assertEqual(result['rows'][0]['text'], 'DEF')
        self.assertEqual(result['rows'][0]['artifact']['pointer'], '/lines/1')
        self.assertTrue((self.root / result['rows'][0]['source']['crop']).is_file())
        self.assertEqual((self.work / 'review.json').read_bytes(), before)
        self.assertFalse((self.work / 'checks/visual-review.json').exists())

    def test_valid_batch_archives_previous_review_and_marks_only_derived_artifacts_stale(self):
        previous = (self.work / 'review.json').read_bytes()
        previous_hash = hashlib.sha256(previous).hexdigest()
        protected = {'samples.json': [{'expected': 'ABC'}], 'clipboard-expectations.json': {'expected': 'ABC'},
                     'ocr/preserved-cache.json': {'status': 'completed'},
                     'checks/independent.json': {'unrelated': 'keep'}}
        for name, value in protected.items():
            self.put(name, value)
        protected_bytes = {name: (self.work / name).read_bytes() for name in protected}
        self.put('segment-manifest.json', {'inputs': {'review': {'path': str(self.work / 'review.json'),
                                                                  'sha256': previous_hash}}})
        self.put('pages.json', [{'page': 1, 'units': []}, {'page': 2, 'units': []}])
        self.put('checks/technical.json', {'previous_export_evidence': 'preserve'})
        changed = {**self.review['lines'][0], 'text': 'ABD', 'decision_basis': 'fresh synthetic crop reading'}
        patch = self.put('patch.json', {'lines': [{'line': changed}]})
        result = self.command('patch', self.identifier, '--patch', patch)
        self.assertEqual(result['operation'], 'patch')
        self.assertEqual(result['counts']['changed_lines'], 1)
        archived = self.root / result['artifacts']['previous_review']
        self.assertEqual(archived.read_bytes(), previous)
        self.assertEqual(archived.name, previous_hash + '.json')
        updated = json.loads((self.work / 'review.json').read_text())
        self.assertEqual(updated['lines'][0]['text'], 'ABD')
        self.assertEqual(updated['lines'][1], self.review['lines'][1])
        self.assertEqual(updated['units'], self.review['units'])
        invalidation = json.loads((self.root / result['artifacts']['review_invalidation']).read_text())
        self.assertEqual(invalidation['affected_lines'], ['line-a'])
        self.assertEqual(invalidation['affected_pages'], [1])
        paths = [item['path'] for item in invalidation['artifacts']]
        self.assertIn('segment-manifest.json', paths)
        self.assertIn('pages.json', paths)
        self.assertIn('checks/technical.json', paths)
        self.assertNotIn('samples.json', paths)
        self.assertNotIn('ocr/preserved-cache.json', paths)
        self.assertNotIn('checks/independent.json', paths)
        for name, expected in protected_bytes.items():
            self.assertEqual((self.work / name).read_bytes(), expected)
        self.assertEqual(result['project']['validation'], 'not_run')
        self.assertFalse((self.work / 'checks/visual-review.json').exists())

    def test_small_query_and_byte_bounded_pagination_cover_huge_publication_and_single_text(self):
        review = copy.deepcopy(self.review)
        review['lines'] = []
        review['units'] = []
        for index in range(1200):
            line = {**self.review['lines'][index % 2], 'id': f'large-{index}',
                    'candidate_id': None, 'text': 'Žluťoučký kůň ' * 100}
            review['lines'].append(line)
            review['units'].append({'id': f'unit-{index}', 'article': f'article-{index % 2}',
                                    'page': line['page'], 'tag': 'P', 'line_ids': [line['id']]})
        review['lines'][-1]['text'] = 'Žluťoučký kůň ' * 10000
        self.put('review.json', review)
        selected = self.command('query', self.identifier, 'transcript', '--id', 'large-1199', '--text-bytes', 128)
        row = selected['rows'][0]
        self.assertTrue(row['text_truncated'])
        self.assertEqual(row['text_bytes'], len(review['lines'][-1]['text'].encode('utf-8')))
        self.assertLessEqual(len(row['text'].encode('utf-8')), 128)
        self.assertEqual(row['artifact']['pointer'], '/lines/1199')
        self.assertEqual(selected['limits']['response_bytes'], 4096)
        page = self.command('query', self.identifier, 'transcript', '--page', 2, '--article', 'article-1', '--limit', 1000)
        self.assertEqual(page['counts']['matched'], 600)
        self.assertLess(page['counts']['returned'], 1000)
        self.assertIsNotNone(page['next_offset'])
        following = self.command('query', self.identifier, 'transcript', '--page', 2,
                                  '--article', 'article-1', '--offset', page['next_offset'], '--limit', 1000)
        self.assertEqual(following['rows'][0]['id'], f'large-{page["next_offset"] * 2 + 1}')
        self.assertEqual(page['limits']['text_preview_bytes'], 256)

    def test_candidates_and_findings_preserve_evidence_and_distinct_content_meanings(self):
        self.put('targeted-candidates.json', [{'id': 'target-a', 'page': 1, 'variant': 'raw',
                                              'candidate': 'hypothesis', 'bbox': [0, 0, 100, 20]}])
        self.put('checks/findings.json', {'items': [{'id': 'finding-a', 'page': 1, 'status': 'open',
                                                   'reason': 'uncertain glyph', 'evidence': ['crop.png']}]})
        self.review['unresolved'] = [{'id': 'unresolved-a', 'line': 'line-a', 'page': 1,
                                      'context': 'uncertain passage', 'status': 'waiting_for_input',
                                      'reason': 'damaged source', 'source_crop': 'crop.png',
                                      'bbox': [0, 0, 100, 20], 'candidates': ['hypothesis']}]
        self.review['publisher_errors'] = [{'line': 'line-b', 'printed': 'DEF',
                                           'explanation': 'preserve printed wording', 'status': 'confirmed_print_error'}]
        self.put('review.json', self.review)
        self.put('reconstructions.json', [{'line': 'line-b', 'page': 2, 'candidate': 'DE?', 'adopted': 'DEF',
                                          'source_crop': 'crop.png', 'basis': 'synthetic reading'}])
        candidates = self.command('query', self.identifier, 'candidates', '--id', 'target-a')
        self.assertEqual(candidates['rows'][0]['text'], 'hypothesis')
        self.assertEqual(candidates['rows'][0]['candidate_kind'], 'targeted')
        finding = self.command('query', self.identifier, 'findings')['rows'][0]
        self.assertEqual(finding['status'], 'open')
        self.assertEqual(finding['source']['evidence'], [str((self.work / 'crop.png').relative_to(self.root))])
        unresolved = self.command('query', self.identifier, 'unresolved')['rows'][0]
        self.assertEqual(unresolved['status'], 'waiting_for_input')
        publisher = self.command('query', self.identifier, 'publisher-errors')['rows'][0]
        self.assertEqual(publisher['printed'], 'DEF')
        self.assertEqual(publisher['status'], 'confirmed_print_error')
        reconstruction = self.command('query', self.identifier, 'reconstructions')['rows'][0]
        self.assertEqual(reconstruction['adopted'], 'DEF')
        self.assertEqual(reconstruction['candidate'], 'DE?')
        units = self.command('query', self.identifier, 'units', '--article', 'article-b')
        self.assertEqual(units['rows'][0]['id'], 'unit-b')
        self.assertFalse((self.work / 'checks/visual-review.json').exists())

    def test_invalid_batch_keeps_review_history_expectations_and_project_state_unchanged(self):
        self.put('samples.json', [{'expected': 'ABC'}])
        self.put('clipboard-expectations.json', {'expected': 'ABC'})
        before = {name: (self.work / name).read_bytes() for name in
                  ['review.json', 'project.json', 'samples.json', 'clipboard-expectations.json']}
        changed = {**self.review['lines'][0], 'text': 'ABD'}
        bad = {**self.review['lines'][1], 'candidate_id': 'missing'}
        patch = self.put('invalid.json', {'lines': [{'line': changed}, {'line': bad}]})
        result = self.command('patch', self.identifier, '--patch', patch, expected=1)
        self.assertEqual(result['error']['code'], 'patch_invalid')
        self.assertEqual(result['project']['project_id'], self.identifier)
        for name, expected in before.items():
            self.assertEqual((self.work / name).read_bytes(), expected)
        self.assertFalse((self.work / 'review-history').exists())
        self.assertFalse((self.work / 'review-invalidation.json').exists())

    def test_patch_lock_is_exclusive_but_query_remains_available(self):
        patch = self.put('patch.json', {'lines': [{'line': {**self.review['lines'][0], 'text': 'ABD'}}]})
        code = '''
import sys
sys.path.insert(0, sys.argv[1])
from ocr_projects import ProjectRegistry
with ProjectRegistry(sys.argv[2]).project_lock(sys.argv[3]):
    print('locked', flush=True)
    sys.stdin.readline()
'''
        holder = subprocess.Popen([sys.executable, '-S', '-c', code, str(ROOT / 'tools'),
                                   str(self.root), self.identifier], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), 'locked')
            rejected = self.command('patch', self.identifier, '--patch', patch, expected=1)
            self.assertEqual(rejected['error']['code'], 'project_busy')
            queried = self.command('query', self.identifier, 'transcript', '--id', 'line-a')
            self.assertEqual(queried['rows'][0]['text'], 'ABC')
            self.assertEqual(queried['project']['operation_state'], 'running')
        finally:
            holder.communicate('done\n', timeout=10)
        self.assertEqual(self.command('patch', self.identifier, '--patch', patch)['counts']['changed_lines'], 1)

    def test_invalid_query_artifacts_and_limits_have_stable_machine_errors(self):
        missing = self.command('query', self.identifier, 'findings', expected=1)
        self.assertEqual(missing['error']['code'], 'artifact_missing')
        self.assertEqual(self.command('query', self.identifier, 'transcript', '--text-bytes', 1000,
                                      expected=1)['error']['code'], 'invalid_selection')
        self.put('review.json', [])
        invalid = self.command('query', self.identifier, 'transcript', expected=1)
        self.assertEqual(invalid['error']['code'], 'artifact_invalid')

    def test_reordered_units_identify_affected_pages_without_changing_line_text(self):
        patch = self.put('order.json', {'units': list(reversed(self.review['units']))})
        result = self.command('patch', self.identifier, '--patch', patch)
        changed = json.loads((self.work / 'review.json').read_text())
        self.assertEqual(changed['lines'], self.review['lines'])
        invalidation = json.loads((self.root / result['artifacts']['review_invalidation']).read_text())
        self.assertEqual(invalidation['affected_pages'], [1, 2])
        self.assertEqual(invalidation['affected_lines'], ['line-a', 'line-b'])
        self.assertTrue(invalidation['unit_order_changed'])
        self.assertEqual(result['counts']['changed_lines'], 0)

    def test_large_finding_metadata_returns_artifact_reference_with_explicit_omissions(self):
        huge = 'Žluťoučký ' * 10000
        self.put('checks/findings.json', {'items': [{'id': 'large-finding', 'page': 1, 'status': 'open',
                                                   **{key: huge for key in ['reason', 'expected', 'actual', 'context',
                                                                            'decision_basis', 'value', 'printed', 'explanation']}}]})
        result = self.command('query', self.identifier, 'findings', '--text-bytes', 512)
        self.assertEqual(result['counts']['returned'], 1)
        self.assertEqual(result['rows'][0]['artifact']['pointer'], '/items/0')
        self.assertTrue(result['rows'][0]['omitted_fields'])

    def test_query_marks_preserved_derived_evidence_stale_after_patch(self):
        self.put('reconstructions.json', [{'line': 'line-a', 'page': 1, 'candidate': 'A?C',
                                          'adopted': 'ABC', 'source_crop': 'crop.png', 'status': 'visually_confirmed'}])
        self.put('checks/findings.json', {'items': [{'id': 'old-finding', 'line': 'line-a', 'status': 'open',
                                                   'reason': 'old export', 'evidence': ['crop.png']}]})
        patch = self.put('patch.json', {'lines': [{'line': {**self.review['lines'][0], 'text': 'ABD'}}]})
        self.command('patch', self.identifier, '--patch', patch)
        reconstruction = self.command('query', self.identifier, 'reconstructions')['rows'][0]
        self.assertTrue(reconstruction['stale_for_current_review'])
        finding = self.command('query', self.identifier, 'findings')['rows'][0]
        self.assertTrue(finding['stale_for_current_review'])
        candidates = self.command('query', self.identifier, 'candidates')
        self.assertFalse(candidates['rows'][0]['stale_for_current_review'])


if __name__ == '__main__':
    unittest.main()
