"""Actual exported-page examination; publication remains a native transaction."""
import copy
import json
from pathlib import Path
import time

from .context import ContextJobs
from .codex import now
from .jobs import JobError, atomic_json, sha
from .visual_session import examine


OUTPUT_PROMPT = '''Inspect every attached original source and actual final PDF render. Compare visible image,
transcript order and selection geometry with the bound technical/sample checks. Return specific visual
conclusions and evidence, never a completed-turn claim or template. Keep source uncertainties, observed
geometry limitations, remaining approximation and untested UI clipboard cases honest. You cannot repair
or waive automatic integrity failures. Do not silently close an existing limitation from a general page
impression. Preserve every finding ID and frozen source expectation. User acceptance remains separate.
This first-export review retains approximation_requires_character_review and the open
geometry/approximation finding from the bound checkpoint, even when every line/sample was examined
and no individual item is open. Whole-page render identity is not exact glyph/cell-boundary evidence;
do not return visually_verified from this output review.
Evidence paths must identify attached images.path or actual inputs entries' bound path, either relative
to the run workspace or the exact absolute alias. Input labels are not paths to frozen report snapshots.
Keep evidence within this run workspace; do not cite the nested external source PDF path.
Return JSON with preparation_sha256, images_examined (the original path/sha256 objects), visual_review
(the identity fields from the supplied template plus reviewer, pages_reviewed, evidence, geometry_status,
conclusion), and findings (source_sha256, pdf_sha256, items with id/status/open-or-resolved/reason/evidence).
OUTPUT_PACKET\n'''

OUTPUT_INSTRUCTIONS = ('Examine only the attached original source and actual exported-page diagnostic images '
    'with the bound check/report JSON supplied in the prompt. Do not run shell commands, read files, '
    'install software, change the project or invent visual conclusions. Call context_mode ctx_stats once. '
    'Return exactly the requested JSON and preserve every unchanged open limitation.\n')

OUTPUT_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required':
    ['preparation_sha256', 'images_examined', 'visual_review', 'findings'], 'properties': {
        'preparation_sha256': {'type': 'string'},
        'images_examined': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
            'required': ['path', 'sha256'], 'properties': {'path': {'type': 'string'}, 'sha256': {'type': 'string'}}}},
        'visual_review': {'type': 'object', 'additionalProperties': False, 'required':
            ['source_sha256', 'pdf_sha256', 'review_sha256', 'reviewer', 'pages_reviewed', 'evidence', 'geometry_status', 'conclusion'],
            'properties': {**{key: {'type': 'string'} for key in ('source_sha256', 'pdf_sha256', 'review_sha256',
                'reviewer', 'geometry_status', 'conclusion')}, 'pages_reviewed': {'type': 'array', 'items': {'type': 'integer'}},
                'evidence': {'type': 'array', 'items': {'type': 'string'}}}},
        'findings': {'type': 'object', 'additionalProperties': False, 'required': ['source_sha256', 'pdf_sha256', 'items'],
            'properties': {'source_sha256': {'type': 'string'}, 'pdf_sha256': {'type': 'string'},
                'items': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                    'required': ['id', 'status', 'reason', 'evidence'], 'properties': {
                        'id': {'type': 'string'}, 'status': {'type': 'string', 'enum': ['open', 'resolved']},
                        'reason': {'type': 'string'}, 'evidence': {'type': 'array', 'items': {'type': 'string'}}}}}}}}}


class OutputReviewJobs(ContextJobs):
    namespace = 'output-review-attempts'
    step_id = 'output_review'

    def __init__(self, publish, runtime=None, context_runtime=None, process=None):
        super().__init__(publish, runtime, context_runtime)
        self.process = process

    def _run(self, job):
        value = job['manifest']
        started = time.monotonic()
        job['root'] = root = Path(value['root'])
        work = job['directory'].parents[2]
        value.update(output_review_complete=False, turns=[], context_runtime=copy.deepcopy(self.context_runtime))
        try:
            value['state'] = 'running'
            self._event(job, 'output_review_started')
            selected = job['metadata'].get('prepared_review_sha256')
            arguments = ['verify-output-preparation', value['run_id'], '--sha256', selected] if selected else [
                'prepare-output-review', value['run_id']]
            if not selected and job['metadata'].get('environment'):
                arguments += ['--environment', job['metadata']['environment']]
            self.process.request(root, *arguments, timeout=120)
            path = work / 'output-review-preparation.json'
            packet = json.loads(path.read_text())
            packet['preparation_sha256'] = sha(path)
            if selected and packet['preparation_sha256'] != selected:
                raise JobError('output_review_invalid', 'Explicitly disclosed output review preparation changed.')
            answer, proof, proposal = examine(self, job, 'output_examination',
                OUTPUT_PROMPT + json.dumps(packet, ensure_ascii=False), OUTPUT_SCHEMA, work, packet['images'],
                instructions=OUTPUT_INSTRUCTIONS)
            publication = {'schema_version': 1, 'preparation_sha256': packet['preparation_sha256'],
                'preparation': str(work / packet['preparation_artifact']),
                'runtime': self.runtime, 'context_runtime': self.context_runtime,
                'visual_turn': proof, 'evidence': {'protocol': proof['protocol'],
                    'proposal': {'path': str(proposal), 'sha256': sha(proposal)}}}
            for index, item in enumerate([*self.runtime['files'], *self.context_runtime.get('files', []),
                    *self.context_runtime.get('interpreters', [])]):
                if 'sha256' in item:
                    publication['evidence']['runtime_' + str(index)] = {'path': item['path'], 'sha256': item['sha256']}
            path = job['directory'] / 'publication-proposal.json'
            atomic_json(path, publication)
            self.process.request(root, 'publish-output-review', value['run_id'], '--proposal', path)
            value.update(output_review_complete=True, state='completed', observations=answer,
                publication_sha256=sha(work / 'output-review-publication.json'))
            value['artifacts'].update(proposal=str(proposal.relative_to(root)),
                publication=str((work / 'output-review-publication.json').relative_to(root)))
            self._event(job, 'output_review_completed')
        except Exception as error:
            value.update(state='paused' if getattr(error, 'code', None) == 'autonomous_paused' else 'interrupted' if job['cancel'] else 'failed',
                error={'code': getattr(error, 'code', 'output_review_failed'), 'message': str(error)})
            self._event(job, 'output_review_failed')
        finally:
            if job.get('rpc'):
                job['rpc'].close()
            value.update(ended_at=now(), elapsed_seconds=time.monotonic() - started)
            atomic_json(job['directory'] / 'attempt.json', value)
            with self._lock:
                self._active = None

    def status(self, root, run_id, work, operation=None):
        # This namespace is image examination, not context diagnostics.
        value = super(ContextJobs, self).status(root, run_id, work, operation)
        if value.get('output_review_complete') and value['state'] == 'completed':
            try:
                if sha(work / 'output-review-publication.json') != value['publication_sha256']:
                    raise JobError('output_review_invalid', 'Published output review changed.')
                self.process.request(root, 'verify-output-review', run_id)
            except Exception as error:
                value.update(state='invalidated', output_review_complete=False,
                    error={'code': getattr(error, 'code', 'output_review_invalid'), 'message': str(error)})
        return value
