"""Owned source-expectation → native geometry → actual image examination stage."""
import copy
import hashlib
import json
from pathlib import Path
import time
import uuid
import fcntl

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

    def recover(self, root, run, attempt_id):
        """Revalidate an unchanged completed proposal; never starts a provider process."""
        work = root/run['artifacts']['workspace']['path']
        directory = (work/'application'/self.namespace/str(attempt_id)).resolve()
        if directory.parent != (work/'application'/self.namespace).resolve():
            raise JobError('geometry_recovery_invalid', 'Choose an original geometry attempt of this run.')
        try:
            attempt_path = directory/'attempt.json'
            value = json.loads(attempt_path.read_text())
            if (value['root'] != str(root) or value['run_id'] != run['project']['run_id'] or
                value['state'] not in ('failed', 'interrupted') or value['runtime'] != self.runtime or
                value['context_runtime'] != self.context_runtime or value['profile_sha256'] != run['run']['profile_sha256']):
                raise ValueError('Saved attempt runtime/source/profile/state differs')
            last = value['turns'][-1]
            if last['stage'] != 'geometry_examination' or last['state'] != 'completed':
                raise ValueError('No original completed geometry observation turn to recover')
            proposal_path = directory/'geometry_examination/proposal.json'
            original_checkpoint = directory/'checkpoint-proposal.json'
            checkpoint = json.loads(original_checkpoint.read_text())
            if (Path(checkpoint['evidence']['proposal']['path']).resolve() != proposal_path.resolve() or
                checkpoint['visual_turn']['turn_id'] != last['turn_id']):
                raise ValueError('Saved publication proposal differs from original completed geometry turn')
            verify_resources(self.context_runtime, self.runtime)
            recovery_id = uuid.uuid4().hex
            descriptor = directory/('recovery-'+recovery_id+'.json')
            record = {'schema_version': 1, 'recovery_id': recovery_id, 'run_id': value['run_id'],
                'original_attempt_id': attempt_id, 'original_state': value['state'], 'original_error': value['error'],
                'reason': 'Revalidate unchanged original completed assistant JSON after local publication failure; no new inference.',
                'policy': 'workspace-confined-image-path-alias-v1', 'new_ai_turns': 0,
                'original_evidence': {'attempt': {'path': str(attempt_path), 'sha256': sha(attempt_path)},
                    'checkpoint_proposal': {'path': str(original_checkpoint), 'sha256': sha(original_checkpoint)},
                    'protocol': checkpoint['visual_turn']['protocol'], 'proposal': checkpoint['evidence']['proposal']},
                'validator': {'path': str(Path(__file__).resolve().parents[1]/'tools/ocr_project_geometry.py')}}
            record['validator']['sha256'] = sha(Path(record['validator']['path']))
            atomic_json(descriptor, record)
            checkpoint = copy.deepcopy(checkpoint)
            checkpoint['evidence'].update(recovery_descriptor={'path': str(descriptor), 'sha256': sha(descriptor)},
                recovery_validator=record['validator'])
            packet = json.loads((work/'geometry-preparation.json').read_text())
            original_adapter = packet['inputs']['geometry_tool']
            archive = work/'geometry-code-snapshots'/(original_adapter['sha256']+'.py')
            checkpoint['evidence']['original_adapter_snapshot'] = {'path': str(archive), 'sha256': original_adapter['sha256']}
            policy = Path(__file__).resolve().parents[1]/'native/geometry-adapter-compatibility.json'
            if Path(original_adapter['path']).resolve() == Path(record['validator']['path']).resolve():
                checkpoint['evidence']['validator_compatibility_policy'] = {'path': str(policy), 'sha256': sha(policy)}
            path = directory/('recovery-checkpoint-'+recovery_id+'.json')
            atomic_json(path, checkpoint)
            self.process.request(root, 'publish-geometry', value['run_id'], '--checkpoint', path)
            result = {'recovery_id': recovery_id, 'attempt_id': attempt_id, 'original_attempt_sha256': sha(attempt_path),
                'checkpoint_sha256': sha(work/'geometry-checkpoint.json'),
                'descriptor': {'path': str(descriptor), 'sha256': sha(descriptor)}, 'new_ai_turns': 0}
            atomic_json(work/'geometry-recovery.json', result)
            event = {'schema_version': 1, 'event_id': recovery_id, 'run_id': value['run_id'],
                'type': 'geometry_recovered', 'timestamp': now(), **result}
            with (root/run['artifacts']['history']['path']).open('a') as stream:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                stream.write(json.dumps(event, ensure_ascii=False)+'\n'); stream.flush()
            self.publish('geometry_recovered', root=str(root), run_id=value['run_id'], recovery_id=recovery_id)
            return result
        except JobError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise JobError('geometry_recovery_invalid', str(error)) from error

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
                commitment = metadata.get('saved_origin') or metadata['commitment']
                if not metadata.get('saved_origin'):
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
            value['reconciled_from'] = metadata.get('previous_attempt_id')
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
            value.update(state='paused' if getattr(error, 'code', None) == 'autonomous_paused' else 'interrupted' if job['cancel'] else 'failed',
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
        recovery_path = work/'geometry-recovery.json'
        if recovery_path.exists() and value.get('state') in ('failed', 'interrupted'):
            try:
                recovery = json.loads(recovery_path.read_text())
                if (recovery['attempt_id'] != value['attempt_id'] or
                    recovery['original_attempt_sha256'] != sha(root/value['artifacts']['attempt']) or
                    recovery['checkpoint_sha256'] != sha(work/'geometry-checkpoint.json')):
                    raise ValueError('Saved geometry recovery changed')
                checkpoint = json.loads((work/'geometry-checkpoint.json').read_text())
                if checkpoint['evidence']['recovery_descriptor'] != recovery['descriptor']:
                    raise ValueError('Recovery descriptor differs from validated checkpoint')
                self.process.request(root, 'verify-geometry', run_id)
                proposal = json.loads(Path(checkpoint['evidence']['proposal']['path']).read_text())
                value.update(original_attempt_state=value['state'], state='completed', geometry_complete=True,
                    evidence_recovered=True, recovery=recovery, error=None, observations=proposal,
                    counts={'lines': len(proposal['lines']), 'samples': len(proposal['samples']),
                        'open_items': sum(o['status']=='open' for o in proposal['lines']+proposal['samples'])})
            except Exception as error:
                value['recovery_error'] = {'code': getattr(error, 'code', 'geometry_recovery_invalid'), 'message': str(error)}
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
                checkpoint = json.loads((work/'geometry-checkpoint.json').read_text())
                if checkpoint.get('correction_scope'):
                    # The current checkpoint has a NEW local examination and
                    # separately bound, unchanged observations from prior turns.
                    packet = json.loads((work/'geometry-preparation.json').read_text())
                    value['first_geometry_attempt_id'] = value.get('attempt_id')
                    value['observations'] = json.loads(Path(checkpoint['evidence']['proposal']['path']).read_text())
                    value['correction_scope'] = checkpoint['correction_scope']
                    value['historical_observations'] = packet['historical_observations']
                    ledger = json.loads((work/'application/corrections/ledger.json').read_text())
                    cycle = next(c for c in ledger['cycles'] if c['cycle_id'] == checkpoint['correction_scope']['cycle_id'])
                    value['attempt_id'] = cycle['attempt_id']
                    value['counts'] = {'lines': len(value['observations']['lines']),
                        'samples': len(value['observations']['samples']),
                        'historical_lines': len(checkpoint['correction_scope']['unchanged_line_ids']),
                        'historical_samples': len(checkpoint['correction_scope']['unchanged_sample_ids']),
                        'open_items': sum(row['status'] == 'open' for row in
                            value['observations']['lines']+value['observations']['samples']) +
                            sum(row['observation']['status'] == 'open' for row in packet['historical_observations'])}
                value['decision_artifacts'] = []
                for name in ('proposal', 'sample_origin', 'recovery_descriptor'):
                    record = checkpoint['evidence'].get(name)
                    if record and Path(record['path']).resolve().is_relative_to(work.resolve()):
                        value['decision_artifacts'].append({'name': name,
                            'path': str(Path(record['path']).resolve().relative_to(work.resolve())), 'sha256': record['sha256']})
            except Exception as error:
                value.update(state='invalidated', geometry_complete=False,
                    error={'code': getattr(error, 'code', 'geometry_invalid'), 'message': str(error)})
        return value
