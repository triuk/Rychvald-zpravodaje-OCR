"""Owned source-expectation → native geometry → actual image examination stage."""
import copy
import hashlib
import json
from pathlib import Path
import time

from .context import ContextJobs
from .codex import now
from .jobs import JobError, atomic_json, sha
from .context_runtime import verify_resources
from .visual_session import examine
from .geometry_contract import SOURCE_SCHEMA, GEOMETRY_SCHEMA, SOURCE_PROMPT, GEOMETRY_PROMPT


class GeometryJobs(ContextJobs):
    namespace = 'geometry-attempts'
    step_id = 'geometry'

    def __init__(self, publish, runtime=None, context_runtime=None, process=None):
        super().__init__(publish, runtime, context_runtime)
        self.process = process

    def _run(self, job):
        value = job['manifest']
        started = time.monotonic()
        root = Path(value['root'])
        job['root'] = root
        work = job['directory'].parents[2]
        value.update(geometry_complete=False, turns=[], context_runtime=copy.deepcopy(self.context_runtime))
        metadata = job['metadata']
        try:
            value['state'] = 'running'
            self._event(job, 'geometry_attempt_started')
            verify_resources(self.context_runtime, self.runtime)
            packet = copy.deepcopy(metadata['source'])
            value['source'] = packet
            value['historical_reading'] = metadata['reading']
            images = [{'path': str(Path(page['path']).relative_to(work)), 'sha256': page['sha256']} for page in packet['pages']]
            samples = metadata.get('samples')
            origin_path = job['directory'] / 'samples-origin.json'
            if samples is not None:
                # External pre-existing source commitment is verified, not a result-adapted sample list.
                commitment = metadata['commitment']
                digest = hashlib.sha256(json.dumps(samples, ensure_ascii=False, sort_keys=True,
                    separators=(',', ':')).encode()).hexdigest()
                if digest != commitment['sample_commitment'] or commitment['source_sha256'] != packet['source_sha256']:
                    raise JobError('geometry_samples_invalid', 'Original source sample commitment differs.')
                atomic_json(origin_path, commitment)
            else:
                # No transcript/candidate/cell/output text is provided to the independent sample turn.
                source_packet = {key: packet[key] for key in ('source_sha256', 'pages')}
                answer, proof, path = examine(self, job, 'source_expectations',
                    SOURCE_PROMPT + json.dumps(source_packet), SOURCE_SCHEMA, work, images)
                if answer['source_sha256'] != packet['source_sha256']:
                    raise JobError('geometry_samples_invalid', 'Independent source samples belong to another source.')
                samples = answer['samples']
                atomic_json(origin_path, {'kind': 'source_visual_turn', 'source_sha256': packet['source_sha256'],
                    'visual_turn': proof, 'proposal': {'path': str(path), 'sha256': sha(path)}, 'images': images})
            samples_path = job['directory'] / 'source-samples.json'
            if metadata.get('samples_bytes') is not None:
                samples_path.write_bytes(bytes(metadata['samples_bytes']))
            else:
                atomic_json(samples_path, samples)
            value['samples_commitment'] = sha(samples_path)
            value['artifacts'].update(source_samples=str(samples_path.relative_to(root)),
                sample_origin=str(origin_path.relative_to(root)))
            self._event(job, 'geometry_samples_committed', samples_sha256=sha(samples_path), count=len(samples))
            arguments = ['prepare-geometry', value['run_id'], '--samples', samples_path, '--provenance', origin_path]
            if metadata.get('environment'):
                arguments += ['--environment', metadata['environment']]
            self.process.request(root, *arguments)
            preparation_path = work / 'geometry-preparation.json'
            preparation = json.loads(preparation_path.read_text())
            preparation['preparation_sha256'] = sha(preparation_path)
            self.process.request(root, 'verify-geometry', value['run_id'], '--prepared')
            self._event(job, 'geometry_diagnostics_prepared', images=len(preparation['images']))
            value['thread_id'] = None
            observations, proof, proposal_path = examine(self, job, 'geometry_examination',
                GEOMETRY_PROMPT + json.dumps(preparation, ensure_ascii=False), GEOMETRY_SCHEMA, work, preparation['images'])
            checkpoint = {'schema_version': 1, 'status': 'examined_with_remaining_approximations',
                'preparation_sha256': sha(preparation_path), 'identity': preparation['identity'],
                'visual_turn': proof, 'evidence': {
                    'protocol': proof['protocol'], 'proposal': {'path': str(proposal_path), 'sha256': sha(proposal_path)},
                    'sample_origin': {'path': str(origin_path), 'sha256': sha(origin_path)}},
                'historical_reading': metadata['reading'], 'source_samples_sha256': sha(samples_path),
                'runtime': self.runtime, 'context_runtime': self.context_runtime,
                'export_validation': 'not_run', 'acceptance': 'separate_user_decision'}
            for name, item in enumerate([*self.runtime['files'], *self.context_runtime.get('files', []),
                    *self.context_runtime.get('interpreters', [])]):
                if 'sha256' in item:
                    checkpoint['evidence']['runtime_'+str(name)] = {'path': item['path'], 'sha256': item['sha256']}
            checkpoint_path = job['directory'] / 'checkpoint-proposal.json'
            atomic_json(checkpoint_path, checkpoint)
            verify_resources(self.context_runtime, self.runtime)
            self.process.request(root, 'publish-geometry', value['run_id'], '--checkpoint', checkpoint_path)
            value.update(state='completed', geometry_complete=True, observations=observations,
                counts={'lines': len(observations['lines']), 'samples': len(observations['samples']),
                    'open_items': sum(o['status'] == 'open' for o in observations['lines']+observations['samples'])})
            value['artifacts']['checkpoint'] = str((work / 'geometry-checkpoint.json').relative_to(root))
        except Exception as error:
            value.update(state='interrupted' if job['cancel'] else 'failed',
                error={'code': getattr(error, 'code', 'geometry_failed'), 'message': str(error)})
        finally:
            if job['rpc'] is not None:
                job['rpc'].close()
                job['rpc'] = None
            value.update(ended_at=now(), elapsed_seconds=max(0, time.monotonic()-started))
            try:
                self._event(job, 'geometry_attempt_'+value['state'], state=value['state'], error=value['error'])
            finally:
                with self._lock:
                    atomic_json(job['directory']/'attempt.json', value)
                    self._active = None
                self.publish('geometry_finished', root=str(root), run_id=value['run_id'], state=value['state'])

    def status(self, root, run_id, work, operation=None):
        value = super(ContextJobs, self).status(root, run_id, work, operation)
        value['prepared_artifacts_valid'] = False
        if (work/'geometry-preparation.json').exists():
            try:
                self.process.request(root, 'verify-geometry', run_id, '--prepared')
                packet = json.loads((work/'geometry-preparation.json').read_text())
                value['prepared_artifacts_valid'] = True
                value['prepared'] = {key: packet[key] for key in ('identity', 'images', 'logical_units',
                    'source_samples', 'unresolved', 'source_risks', 'geometry_status', 'export_validation', 'acceptance')}
            except Exception as error:
                value['preparation_error'] = {'code': getattr(error, 'code', 'geometry_invalid'), 'message': str(error)}
        if value.get('geometry_complete') and value['state'] == 'completed':
            try:
                self.process.request(root, 'verify-geometry', run_id)
            except Exception as error:
                value.update(state='invalidated', geometry_complete=False,
                    error={'code': getattr(error, 'code', 'geometry_invalid'), 'message': str(error)})
        return value
