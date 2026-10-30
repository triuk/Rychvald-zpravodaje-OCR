"""Public evidence archive contract; original packets retain their identities."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))


class EvidenceArchiveTests(unittest.TestCase):
    def test_publication_rejects_current_report_drift_even_when_old_bytes_are_archived(self):
        import ocr_evidence_archive as evidence
        from ocr_projects import ProjectRegistry, ProjectError
        from ocr_project_output_review import publish_output_review, output_identity
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.pdf'
            source.write_bytes(b'%PDF-synthetic publication guard fixture\n')
            registry = ProjectRegistry(root / 'registry')
            record, _ = registry.import_source(source)
            identifier = record['project']['project_id']
            work = registry.root / record['artifacts']['workspace']
            review = work / 'review.json'
            review.write_bytes(b'{}\n')
            pdf, txt = work / 'output.pdf', work / 'output.txt'
            pdf.write_bytes(b'%PDF-synthetic output\n')
            txt.write_bytes(b'fixture\n')
            with registry.project_lock(identifier) as current:
                current['project'].update(iteration_id='iteration',
                    review_sha256=hashlib.sha256(review.read_bytes()).hexdigest())
            record = registry.get(identifier)
            identity = {key: record['project'][key] for key in
                ('project_id', 'run_id', 'iteration_id', 'source_sha256', 'review_sha256')}
            manifest = dict(identity, source=str(registry.root / record['artifacts']['source']),
                pdf=str(pdf), txt=str(txt), pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(), inputs={})
            (work / 'output-manifest.json').write_text(json.dumps(manifest))
            report = work / 'checks/visual-review.json'
            report.parent.mkdir()
            report.write_bytes(b'{"state":"old"}\n')
            old_sha = hashlib.sha256(report.read_bytes()).hexdigest()
            inventory = root / 'inventory.json'
            inventory.write_text(json.dumps({'records': [{'original_path': str(report),
                'sha256': old_sha, 'kind': 'whole_file', 'source': {'path': str(report)},
                'proof': {'statement': 'historical report before current modification'}}]}))
            evidence.capture(inventory, root / 'archive')
            packet = {'identity': output_identity(record, work), 'inputs': {}, 'images': [],
                'compare_and_swap': {'visual': {'path': str(report), 'sha256': old_sha}}}
            preparation = work / 'output-review-preparation.json'
            preparation.write_text(json.dumps(packet))
            proposal = root / 'proposal.json'
            proposal.write_text(json.dumps({'preparation_sha256': hashlib.sha256(preparation.read_bytes()).hexdigest()}))
            report.write_bytes(b'{"state":"changed after preparation"}\n')
            with patch.dict(os.environ, OCR_EVIDENCE_CATALOG=str(root / 'archive/catalog.json')):
                # Historical reads can still recover the exact old bytes.
                self.assertEqual(evidence.load_bound({'path': str(report), 'sha256': old_sha}), {'state': 'old'})
                with self.assertRaises(ProjectError) as caught:
                    publish_output_review(registry, identifier, proposal)
                self.assertIn('Stale or missing input: visual', str(caught.exception))
            self.assertEqual(json.loads(report.read_bytes()), {'state': 'changed after preparation'})
            self.assertFalse((work / 'output-review-publication.json').exists())

    def test_duplicate_identity_inventory_is_rejected_before_publication(self):
        import ocr_evidence_archive as evidence
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.write_bytes(b'one')
            record = {'original_path': str(root / 'removed'),
                'sha256': hashlib.sha256(b'one').hexdigest(), 'kind': 'whole_file',
                'source': {'path': str(source)}, 'proof': {'statement': 'trusted'}}
            inventory = root / 'inventory.json'
            inventory.write_text(json.dumps({'records': [record, record]}))
            with self.assertRaises(ValueError):
                evidence.capture(inventory, root / 'archive')
            self.assertFalse((root / 'archive').exists())

    def test_multiple_hashes_and_fail_closed_catalog_cas_and_path_negatives(self):
        import ocr_evidence_archive as evidence
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = str(root / 'removed/same-name.json')
            records = []
            for name, content in [('one', b'{"version":1}\n'), ('two', b'{"version":2}\n')]:
                source = root / name
                source.write_bytes(content)
                records.append({'original_path': old, 'sha256': hashlib.sha256(content).hexdigest(),
                    'kind': 'whole_file', 'source': {'path': str(source)}, 'proof': {'statement': name}})
            absent = dict(records[0], sha256='f' * 64, status='unavailable',
                proof={'classification': 'proven unsubmitted prepared-only'})
            inventory = root / 'inventory.json'
            inventory.write_text(json.dumps({'records': records + [absent]}))
            evidence.capture(inventory, root / 'archive')
            catalog = root / 'archive/catalog.json'
            self.assertEqual(evidence.load_bound({'path': old, 'sha256': records[0]['sha256']}, catalog=catalog), {'version': 1})
            self.assertEqual(evidence.load_bound({'path': old, 'sha256': records[1]['sha256']}, catalog=catalog), {'version': 2})
            for path, digest in [(old, 'e' * 64), (old, 'f' * 64), (str(root / 'other'), records[0]['sha256']),
                                 (str(root) + '/removed/../removed/same-name.json', records[0]['sha256'])]:
                with self.assertRaises(ValueError):
                    evidence.resolve_bound(path, digest, catalog=catalog)
            pin = {'path': str(catalog), 'sha256': hashlib.sha256(catalog.read_bytes()).hexdigest()}
            catalog.chmod(0o644)
            original_catalog = catalog.read_bytes()
            catalog.write_bytes(original_catalog + b' ')
            with self.assertRaises(ValueError):
                evidence.resolve_bound(old, records[0]['sha256'], catalog=pin)
            catalog.write_bytes(original_catalog)
            obj = root / 'archive/objects' / records[0]['sha256']
            original_bytes = obj.read_bytes()
            obj.chmod(0o644)
            obj.write_bytes(b'altered')
            with self.assertRaises(ValueError):
                evidence.resolve_bound(old, records[0]['sha256'], catalog=catalog)
            obj.unlink()
            with self.assertRaises(ValueError):
                evidence.resolve_bound(old, records[0]['sha256'], catalog=catalog)
            obj.symlink_to(root / 'one')
            with self.assertRaises(ValueError):
                evidence.resolve_bound(old, records[0]['sha256'], catalog=catalog)
            obj.unlink()
            obj.write_bytes(original_bytes)
            malformed = json.loads(original_catalog)
            malformed['records'][0]['object'] = '../one'
            catalog.write_text(json.dumps(malformed))
            pin = {'path': str(catalog), 'sha256': hashlib.sha256(catalog.read_bytes()).hexdigest()}
            with self.assertRaises(ValueError):
                evidence.resolve_bound(old, records[0]['sha256'], catalog=pin)

    def test_visual_protocol_and_images_keep_original_paths_with_explicit_workspace_binding(self):
        import ocr_evidence_archive as evidence
        from ocr_visual_evidence import verify_visual_turn
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original_work, work = root / 'original', root / 'relocated'
            work.mkdir()
            (work / 'application').mkdir()
            (work / 'application/profile.json').write_bytes((ROOT / 'profiles/faithful-reading.json').read_bytes())
            image = work / 'image.png'
            image.write_bytes(b'original encoded image bytes')
            image_sha = hashlib.sha256(image.read_bytes()).hexdigest()
            messages = [
                {'method': 'turn/start', 'params': {'threadId': 'thread', 'model': 'gpt-6.1-sol',
                    'effort': 'high', 'input': [{'type': 'localImage', 'path': str(original_work / 'image.png')}] }},
                {'result': {'thread': {'id': 'thread'}, 'model': 'gpt-6.1-sol', 'reasoningEffort': 'high'}},
                {'method': 'turn/completed', 'params': {'threadId': 'thread', 'turn': {'id': 'turn', 'status': 'completed'}}},
                {'method': 'item/completed', 'params': {'threadId': 'thread', 'turnId': 'turn',
                    'item': {'type': 'agentMessage', 'phase': 'final_answer', 'text': '{"observed":true}'}}},
                {'method': 'item/completed', 'params': {'threadId': 'thread', 'turnId': 'turn',
                    'item': {'type': 'mcpToolCall', 'server': 'context_mode', 'tool': 'ctx_stats', 'status': 'completed'}}},
            ] + [{'method': 'hook/completed', 'params': {'run': {'eventName': event,
                    'status': 'completed', 'source': 'sessionFlags'}}}
                 for event in ('sessionStart', 'userPromptSubmit', 'postToolUse', 'stop')]
            protocol = root / 'original-protocol.jsonl'
            protocol.write_bytes(b''.join((json.dumps({'message': m}) + '\n').encode() for m in messages))
            protocol_raw = protocol.read_bytes()
            old_protocol = original_work / 'protocol.jsonl'
            proof = {'protocol': {'path': str(old_protocol), 'sha256': hashlib.sha256(protocol_raw).hexdigest()},
                'turn_id': 'turn', 'thread_id': 'thread'}
            records = [{'original_path': str(old_protocol), 'sha256': proof['protocol']['sha256'],
                'kind': 'whole_file', 'source': {'path': str(protocol)}, 'proof': {'statement': 'original protocol'}},
                {'original_path': str(original_work / 'image.png'), 'sha256': image_sha,
                 'kind': 'whole_file', 'source': {'path': str(image)}, 'proof': {'statement': 'original image'}}]
            inventory = root / 'inventory.json'
            inventory.write_text(json.dumps({'records': records, 'workspace_bindings': [{
                'original_prefix': str(original_work), 'canonical_prefix': str(work),
                'proof': {'statement': 'explicit original workspace copy'}}]}))
            evidence.capture(inventory, root / 'archive')
            with patch.dict(os.environ, OCR_EVIDENCE_CATALOG=str(root / 'archive/catalog.json')):
                self.assertEqual(verify_visual_turn(proof, work, [{'path': 'image.png', 'sha256': image_sha}], activity='geometry'),
                    {'observed': True})
            self.assertEqual(protocol.read_bytes(), protocol_raw)
            self.assertEqual(image.read_bytes(), b'original encoded image bytes')
            inventory.write_text(json.dumps({'records': records}))
            evidence.capture(inventory, root / 'no-binding')
            with patch.dict(os.environ, OCR_EVIDENCE_CATALOG=str(root / 'no-binding/catalog.json')):
                with self.assertRaises(ValueError):
                    verify_visual_turn(proof, work, [{'path': 'image.png', 'sha256': image_sha}], activity='geometry')

    def test_binding_verifier_uses_archived_exact_identity_after_relocation(self):
        import ocr_evidence_archive as evidence
        import ocr_quality
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = root / 'old/input.json'
            source = root / 'canonical.json'
            source.write_bytes(b'{"preserved":true}\n')
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            inventory = root / 'inventory.json'
            inventory.write_text(json.dumps({'records': [{'original_path': str(old),
                'sha256': digest, 'kind': 'whole_file', 'source': {'path': str(source)},
                'proof': {'statement': 'exact historical identity'}}]}))
            evidence.capture(inventory, root / 'archive')
            with patch.dict(os.environ, OCR_EVIDENCE_CATALOG=str(root / 'archive/catalog.json')):
                ocr_quality.check_bindings({'original': {'path': str(old), 'sha256': digest}}, historical=True)
                with self.assertRaises(ValueError):
                    ocr_quality.check_bindings({'original': {'path': str(old), 'sha256': digest}})
                self.assertEqual(ocr_quality.load_bound({'path': str(old), 'sha256': digest}), {'preserved': True})

    def test_exact_git_bytes_capture_without_executing_historical_code(self):
        import ocr_evidence_archive as evidence
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / 'repository'
            repository.mkdir()
            for args in [('init',), ('config', 'user.email', 'fixture@example.invalid'),
                         ('config', 'user.name', 'Fixture')]:
                subprocess.run(['git', '-C', str(repository), *args], check=True, capture_output=True)
            (repository / 'fixture.py').write_bytes(b'raise RuntimeError("never execute")\n')
            subprocess.run(['git', '-C', str(repository), 'add', 'fixture.py'], check=True)
            subprocess.run(['git', '-C', str(repository), 'commit', '-m', 'fixture'],
                check=True, capture_output=True)
            commit = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
            digest = hashlib.sha256((repository / 'fixture.py').read_bytes()).hexdigest()
            old = str(root / 'removed-worktree/fixture.py')
            inventory = root / 'inventory.json'
            inventory.write_text(json.dumps({'records': [{'original_path': old, 'sha256': digest,
                'kind': 'whole_file', 'source': {'repository': str(repository),
                'commit': commit, 'path': 'fixture.py'}, 'proof': {'statement': 'exact commit'}}]}))
            evidence.capture(inventory, root / 'archive')
            self.assertEqual(evidence.resolve_bound(old, digest, catalog=root / 'archive/catalog.json').read_bytes(),
                b'raise RuntimeError("never execute")\n')

    def test_protocol_fragment_requires_exact_line_offset_and_digest(self):
        import ocr_evidence_archive as evidence
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            protocol = root / 'protocol.jsonl'
            protocol.write_bytes(b'{"first":1}\n{"usage":2}\n')
            fragment = b'{"usage":2}\n'
            digest = hashlib.sha256(fragment).hexdigest()
            inventory = root / 'inventory.json'
            inventory.write_text(json.dumps({'records': [{'original_path': str(protocol),
                'sha256': digest, 'kind': 'protocol_line', 'line': 2, 'byte_offset': 12,
                'source': {'path': str(protocol)}, 'proof': {'statement': 'original metric'}}]}))
            evidence.capture(inventory, root / 'archive')
            catalog = root / 'archive/catalog.json'
            protocol.unlink()
            self.assertEqual(evidence.resolve_fragment(str(protocol), digest,
                line=2, byte_offset=12, catalog=catalog), fragment)
            for line, offset in [(1, 0), (2, 11), (3, 12)]:
                with self.assertRaises(ValueError):
                    evidence.resolve_fragment(str(protocol), digest,
                        line=line, byte_offset=offset, catalog=catalog)
            with self.assertRaises(ValueError):
                evidence.resolve_bound(str(protocol), digest, catalog=catalog)
            self.assertTrue(evidence.verify_catalog(catalog)['verified'])

    def test_original_then_captured_reference_survives_source_removal(self):
        import ocr_evidence_archive as evidence
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / 'original.json'
            original.write_bytes(b'{"identity":"first"}\n')
            digest = hashlib.sha256(original.read_bytes()).hexdigest()
            pointer = {'path': str(original), 'sha256': digest}
            frozen_pointer = json.dumps(pointer)
            self.assertEqual(evidence.load_bound(pointer), {'identity': 'first'})
            inventory = {'records': [{'original_path': str(original), 'sha256': digest,
                'kind': 'whole_file', 'source': {'path': str(original)},
                'proof': {'statement': 'original trusted pointer', 'pointer': pointer}}]}
            inventory_path = root / 'inventory.json'
            inventory_path.write_text(json.dumps(inventory))
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/ocr_evidence_archive.py'),
                'capture', '--inventory', str(inventory_path), '--output', str(root / 'archive')],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            catalog = root / 'archive/catalog.json'
            original.unlink()
            self.assertEqual(evidence.load_bound(pointer, catalog=catalog), {'identity': 'first'})
            self.assertEqual(json.dumps(pointer), frozen_pointer)
            self.assertTrue(evidence.verify_catalog(catalog)['verified'])


if __name__ == '__main__':
    unittest.main()
