#!/usr/bin/env python3
"""Project registry and small process protocol; importing never starts OCR."""
from pathlib import Path
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
import shutil
import sys
import tempfile
import uuid

# The executable and its command modules must share protocol/error classes.
if __name__ == '__main__':
    sys.modules.setdefault('ocr_projects', sys.modules[__name__])

PROTOCOL_VERSION = 1
MAX_RESPONSE_BYTES = 4096


class ProjectError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def response(operation, *, project=None, artifacts=None, counts=None,
             status='completed', error=None, **extra):
    return {'protocol_version': PROTOCOL_VERSION, 'operation': operation,
            'status': status, 'project': project, 'counts': counts or {},
            'artifacts': artifacts or {}, 'error': error, **extra}


def encode_response(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')


def response_size(value):
    return len(encode_response(value))


def paginate_response(result, collection, entries, *, offset, limit, too_large,
                      prepare_row=None):
    """Fill a response page within the emitted UTF-8 budget, including metadata."""
    selected = result[collection]
    for entry in entries[offset:offset + min(limit, 1000)]:
        row = prepare_row(entry, result) if prepare_row else entry
        selected.append(row)
        result['counts']['returned'] = len(selected)
        end = offset + len(selected)
        result['next_offset'] = end if end < len(entries) else None
        if response_size(result) > MAX_RESPONSE_BYTES:
            selected.pop()
            result['counts']['returned'] = len(selected)
            result['next_offset'] = offset + len(selected)
            break
    if not selected and offset < len(entries):
        raise ProjectError('response_too_large', too_large)
    return result


def emit_response(value):
    encoded = encode_response(value)
    if len(encoded) > MAX_RESPONSE_BYTES:
        raise ProjectError('response_too_large', 'Response exceeds 4096 UTF-8 bytes; use a smaller selection.')
    sys.stdout.buffer.write(encoded)


def atomic_json(path, value):
    """Publish complete UTF-8 JSON with one rename; preserve the last valid file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=f'.{path.name}-', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def source_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class ProjectRegistry:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.path = self.root / 'registry.json'

    def _read(self):
        if not self.path.exists():
            return {'schema_version': 1, 'projects': []}
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
            if value.get('schema_version') != 1 or not isinstance(value.get('projects'), list):
                raise ValueError()
            for record in value['projects']:
                self._validate_record(record)
            return value
        except (ValueError, UnicodeError, KeyError, TypeError, AttributeError):
            raise ProjectError('registry_invalid', 'Registry is not a valid version 1 project registry.') from None

    @staticmethod
    def _validate_record(record):
        project = record['project']
        identifier = project['project_id']
        digest = project['source_sha256']
        if (not isinstance(identifier, str) or len(identifier) != 25 or
                identifier[12] != '-' or any(character not in '0123456789abcdef' for character in identifier.replace('-', '')) or
                not isinstance(digest, str) or len(digest) != 64 or
                any(character not in '0123456789abcdef' for character in digest)):
            raise ValueError()
        if project['run_id'] != identifier or not isinstance(project['original_name'], str):
            raise ValueError()
        for key in ('phase', 'operation_state', 'validation', 'acceptance'):
            if not isinstance(project[key], str):
                raise ValueError()
        if record['artifacts']['project'] != f'work/{identifier}/project.json':
            raise ValueError()
        if record['artifacts']['workspace'] != f'work/{identifier}' or record['artifacts']['source'] != f'inputs/{digest}.pdf':
            raise ValueError()
        if not isinstance(record['counts'], dict):
            raise ValueError()

    @contextmanager
    def _registry_lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / '.registry.lock').open('a') as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            yield

    def import_source(self, source, *, new_run=False, run_name=None, profile_path=None,
                      profile_sha256=None, source_sha256=None):
        profile = None
        if run_name is not None or profile_path is not None or profile_sha256 is not None:
            if not new_run or run_name is None or profile_path is None:
                raise ProjectError('invalid_arguments', 'A named run requires --new-run, --run-name and --profile.')
            from ocr_profiles import ProfileError, load_profile, run_name as validate_name
            try:
                validate_name(run_name)
                profile = load_profile(profile_path, expected_sha256=profile_sha256)
            except ProfileError as error:
                raise ProjectError(error.code, str(error)) from None
        with self._registry_lock():
            return self._import_source(source, new_run=new_run, run_name=run_name, profile=profile,
                                       source_sha256=source_sha256)

    def _import_source(self, source, *, new_run=False, run_name=None, profile=None, source_sha256=None):
        source = Path(source)
        if not source.exists():
            raise ProjectError('source_missing', 'Source PDF does not exist.')
        if not source.is_file():
            raise ProjectError('invalid_source', 'Source must be a PDF file.')
        with source.open('rb') as stream:
            if b'%PDF-' not in stream.read(1024):
                raise ProjectError('invalid_source', 'Source has no PDF header.')
        digest = source_hash(source)
        if source_sha256 is not None and source_sha256 != digest:
            raise ProjectError('source_changed', 'Selected source differs from the edition content identity.')
        registry = self._read()
        original_name = source.name
        if run_name is not None:
            original_name = next((record['project']['original_name'] for record in registry['projects']
                                  if record['project']['source_sha256'] == digest), original_name)
        if run_name is not None:
            for record in registry['projects']:
                project = record['project']
                if (project['source_sha256'] == digest and
                        project.get('run_name', '').casefold() == run_name.casefold()):
                    raise ProjectError('run_name_conflict', 'A run with this name already exists for this edition. Choose a different name.')
        if not new_run:
            for record in registry['projects']:
                if record['project']['source_sha256'] == digest:
                    destination = self.root / record['artifacts']['source']
                    if not destination.is_file() or source_hash(destination) != digest:
                        raise ProjectError('source_corrupt', 'Registered source differs from its content hash.')
                    return self.get(record['project']['project_id']), False
        identifier = digest[:12] + '-' + uuid.uuid4().hex[:12]
        artifacts = {'source': f'inputs/{digest}.pdf', 'workspace': f'work/{identifier}',
                     'project': f'work/{identifier}/project.json',
                     'output_pdf': f'outputs/{identifier}-ocr.pdf',
                     'output_txt': f'outputs/{identifier}-ocr.txt'}
        project = {'project_id': identifier, 'run_id': identifier,
                   'source_sha256': digest, 'original_name': original_name,
                   'phase': 'registered', 'operation_state': 'idle',
                   'validation': 'not_run', 'acceptance': 'not_recorded'}
        if run_name is not None:
            project['run_name'] = run_name
            artifacts.update(profile_snapshot=f'work/{identifier}/application/profile.json',
                             run_manifest=f'work/{identifier}/application/run.json',
                             history=f'work/{identifier}/application/history.jsonl')
        for folder in ('inputs', 'work', 'outputs'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        (self.root / artifacts['workspace']).mkdir()
        record = {'project': project, 'artifacts': artifacts, 'counts': {}}
        try:
            destination = self.root / artifacts['source']
            if destination.exists():
                if source_hash(destination) != digest:
                    raise ProjectError('source_corrupt', 'Registered source differs from its content hash.')
            else:
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.source-', delete=False) as stream:
                        temporary = Path(stream.name)
                        with source.open('rb') as input_stream:
                            shutil.copyfileobj(input_stream, stream)
                        stream.flush()
                        os.fsync(stream.fileno())
                    if source_hash(temporary) != digest:
                        raise ProjectError('source_changed', 'Source changed while it was being imported; retry with a stable input.')
                    os.replace(temporary, destination)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
            if profile is not None:
                from datetime import datetime, timezone
                timestamp = datetime.now(timezone.utc).isoformat()
                snapshot = self.root / artifacts['profile_snapshot']
                snapshot.parent.mkdir()
                with snapshot.open('xb') as stream:
                    stream.write(profile['text'].encode('utf-8'))
                    stream.flush()
                    os.fsync(stream.fileno())
                manifest = {'schema_version': 1, 'run_id': identifier, 'edition_id': digest,
                            'name': run_name, 'created_at': timestamp,
                            'profile_sha256': profile['sha256'], 'profile_source_path': profile['path']}
                atomic_json(self.root / artifacts['run_manifest'], manifest)
                atomic_json(self.root / artifacts['history'], {
                    'type': 'run_created', 'timestamp': timestamp, 'run_id': identifier,
                    'name': run_name, 'profile_sha256': profile['sha256']})
            atomic_json(self.root / artifacts['project'], record)
            registry['projects'].append(record)
            atomic_json(self.path, registry)
        except BaseException:
            shutil.rmtree(self.root / artifacts['workspace'])
            raise
        return record, True

    def _get_record(self, project_id):
        for record in self._read()['projects']:
            if record['project']['project_id'] == project_id:
                try:
                    current = json.loads((self.root / record['artifacts']['project']).read_text(encoding='utf-8'))
                    self._validate_record(current)
                    if current['project']['project_id'] != project_id or current['project']['source_sha256'] != record['project']['source_sha256']:
                        raise ValueError()
                    return current
                except (ValueError, UnicodeError, KeyError, TypeError, AttributeError, FileNotFoundError):
                    raise ProjectError('project_invalid', 'Project metadata is missing or invalid.') from None
        raise ProjectError('project_not_found', 'Project does not exist in this registry.')

    def get(self, project_id):
        record = self._get_record(project_id)
        lock_path = self.root / record['artifacts']['workspace'] / '.operation.lock'
        if lock_path.exists():
            with lock_path.open('a') as stream:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    record['project']['operation_state'] = 'running'
                    return record
        if record['project']['operation_state'] == 'running':
            record['project']['operation_state'] = 'interrupted'
            if record['project']['phase'] == 'exporting':
                record['project']['phase'] = 'export_interrupted'
        marker = self.root / record['artifacts']['workspace'] / 'preparation-checkpoint.json'
        if marker.is_file() or (marker.parent / 'preparation-identity.json').is_file():
            try:
                preparation = json.loads(marker.read_text(encoding='utf-8'))
                if not isinstance(preparation, dict):
                    preparation = {'status': 'invalid'}
            except (ValueError, OSError):
                preparation = {'status': 'invalid'}
            if preparation.get('status') != 'completed':
                failed = preparation.get('status') == 'failed'
                record['project'].update(operation_state='failed' if failed else 'interrupted',
                                         phase='preparation_failed' if failed else 'preparation_interrupted',
                                         validation='not_run')
                record['artifacts']['preparation_checkpoint'] = str(marker.relative_to(self.root))
        return record

    @contextmanager
    def project_lock(self, project_id):
        """Exclusive project transaction: edit the yielded record; commit on success.

        Keep this context open across OCR subprocesses and checkpoint writes.
        The OS releases the lock after a crash, so a leftover lock file is harmless.
        """
        original = self._get_record(project_id)
        lock_path = self.root / original['artifacts']['workspace'] / '.operation.lock'
        with lock_path.open('a') as stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ProjectError('project_busy', 'Another operation is active for this project.') from None
            record = self._get_record(project_id)
            yield record
            self._validate_record(record)
            for key in ('project_id', 'run_id', 'source_sha256', 'original_name'):
                if record['project'][key] != original['project'][key]:
                    raise ProjectError('identity_changed', 'Project identity is immutable.')
            atomic_json(self.root / original['artifacts']['project'], record)

    def list_projects(self, *, offset=0, limit=10):
        if offset < 0 or limit < 1:
            raise ProjectError('invalid_selection', 'Offset must be nonnegative and limit must be positive.')
        records = self._read()['projects']
        result = response('list', counts={'total': len(records), 'returned': 0},
                          artifacts={'registry': 'registry.json'}, projects=[], next_offset=None)
        return paginate_response(
            result, 'projects', records, offset=offset, limit=limit,
            too_large='Project summary exceeds the response limit.',
            prepare_row=lambda record, result: self.get(record['project']['project_id'])['project'])


class ProtocolArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ProjectError('invalid_arguments', 'Invalid command arguments; use --help for syntax.')


def build_parser():
    parser = ProtocolArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--json', action='store_true', help='Version 1 JSON protocol (also the default).')
    commands = parser.add_subparsers(dest='operation', required=True)
    command = commands.add_parser('import')
    command.add_argument('source', type=Path)
    command.add_argument('--new-run', action='store_true')
    command.add_argument('--run-name')
    command.add_argument('--profile', type=Path)
    command.add_argument('--profile-sha256')
    command.add_argument('--source-sha256')
    command = commands.add_parser('status')
    command.add_argument('project_id')
    command = commands.add_parser('list')
    command.add_argument('--offset', type=int, default=0)
    command.add_argument('--limit', type=int, default=10)
    command = commands.add_parser('prepare')
    command.add_argument('project_id')
    command.add_argument('--dpi', type=int, default=300)
    command.add_argument('--language', default='ces')
    command.add_argument('--environment', type=Path)
    command.add_argument('--progress-events', type=Path)
    command.add_argument('--attempt-id')
    command = commands.add_parser('query')
    command.add_argument('project_id')
    command.add_argument('view', choices=['transcript', 'candidates', 'findings', 'unresolved', 'publisher-errors', 'reconstructions', 'units'])
    command.add_argument('--page', type=int)
    command.add_argument('--id', dest='ids', action='append')
    command.add_argument('--article')
    command.add_argument('--offset', type=int, default=0)
    command.add_argument('--limit', type=int, default=10)
    command.add_argument('--text-bytes', type=int, default=256)
    command = commands.add_parser('patch')
    command.add_argument('project_id')
    command.add_argument('--patch', required=True, type=Path)
    command.add_argument('--expected-review-sha256')
    command.add_argument('--id', dest='line_id')
    command = commands.add_parser('reading-input')
    command.add_argument('project_id')
    command = commands.add_parser('publish-reading')
    command.add_argument('project_id')
    command.add_argument('--proposal', required=True, type=Path)
    command = commands.add_parser('check-reading')
    command.add_argument('project_id')
    command.add_argument('--proposal', required=True, type=Path)
    command = commands.add_parser('export')
    command.add_argument('project_id')
    command.add_argument('--environment', type=Path)
    command.add_argument('--reviewer-root', type=Path)
    command.add_argument('--geometry-checkpoint', type=Path)
    command.add_argument('--previous-snapshot', type=Path)
    command = commands.add_parser('reserve-correction')
    command.add_argument('project_id')
    command.add_argument('--expected-iteration-id', required=True)
    command.add_argument('--expected-validation-sha256', required=True)
    for operation in ('publish-correction', 'check-correction', 'prepare-correction-geometry', 'settle-correction', 'bind-correction'):
        command = commands.add_parser(operation)
        command.add_argument('project_id')
        command.add_argument('--cycle-id', required=True)
        if operation in ('publish-correction', 'check-correction'):
            command.add_argument('--proposal', required=True, type=Path)
        elif operation == 'prepare-correction-geometry':
            command.add_argument('--environment', type=Path)
        elif operation == 'bind-correction':
            command.add_argument('--attempt', required=True, type=Path)
        else:
            command.add_argument('--reason', choices=['invalid_patch', 'no_valid_change', 'technical_failure', 'interrupted'])
    command = commands.add_parser('prepare-output-review')
    command.add_argument('project_id')
    command.add_argument('--environment', type=Path)
    command = commands.add_parser('publish-output-review')
    command.add_argument('project_id')
    command.add_argument('--proposal', required=True, type=Path)
    command = commands.add_parser('verify-output-review')
    command.add_argument('project_id')
    command = commands.add_parser('verify-output-preparation')
    command.add_argument('project_id')
    command.add_argument('--sha256', required=True)
    command.add_argument('--output-manifest-sha256')
    command = commands.add_parser('prepare-geometry')
    command.add_argument('project_id')
    command.add_argument('--samples', required=True, type=Path)
    command.add_argument('--provenance', type=Path)
    command.add_argument('--environment', type=Path)
    command = commands.add_parser('verify-geometry')
    command.add_argument('project_id')
    command.add_argument('--prepared', action='store_true')
    command = commands.add_parser('verify-geometry-samples')
    command.add_argument('project_id')
    command = commands.add_parser('publish-geometry')
    command.add_argument('project_id')
    command.add_argument('--checkpoint', required=True, type=Path)
    command = commands.add_parser('validate')
    command.add_argument('project_id')
    command.add_argument('--environment', type=Path)
    command = commands.add_parser('resume')
    command.add_argument('project_id')
    command.add_argument('--dpi', type=int)
    command.add_argument('--language')
    command.add_argument('--environment', type=Path)
    command.add_argument('--progress-events', type=Path)
    command.add_argument('--attempt-id')
    return parser


def main(argv=None):
    operation = 'request'
    exit_code = 0
    try:
        args = build_parser().parse_args(argv)
        operation = args.operation
        registry = ProjectRegistry(args.root)
        if args.operation == 'import':
            if args.source.is_dir() and (args.run_name is not None or args.profile is not None or args.profile_sha256 is not None or args.source_sha256 is not None):
                raise ProjectError('invalid_arguments', 'Create a named run from one selected edition, not a source directory.')
            if args.source.is_dir():
                counts = {'sources': 0, 'created': 0, 'reused': 0}
                for source in sorted(args.source.iterdir()):
                    if source.is_file() and source.suffix.lower() == '.pdf':
                        _, created = registry.import_source(source, new_run=args.new_run)
                        counts['sources'] += 1
                        counts['created' if created else 'reused'] += 1
                result = response(args.operation, artifacts={'registry': 'registry.json'}, counts=counts)
            else:
                record, created = registry.import_source(args.source, new_run=args.new_run,
                                                        run_name=args.run_name, profile_path=args.profile,
                                                        profile_sha256=args.profile_sha256,
                                                        source_sha256=args.source_sha256)
                result = response(args.operation, project=record['project'], artifacts=record['artifacts'],
                                  counts={'created': int(created), 'reused': int(not created)})
        elif args.operation == 'validate':
            from ocr_project_export import validate_project
            record, exit_code = validate_project(registry, args.project_id, environment=args.environment)
            result = response(args.operation, **record)
        elif args.operation == 'prepare-geometry':
            from ocr_project_geometry import prepare_geometry
            record = prepare_geometry(registry, args.project_id, args.samples,
                environment=args.environment, provenance=args.provenance)
            result = response(args.operation, **record)
        elif args.operation == 'verify-geometry-samples':
            from ocr_project_geometry import verify_committed_samples
            record = registry.get(args.project_id)
            verify_committed_samples(registry, record)
            result = response(args.operation, **record)
        elif args.operation == 'verify-geometry':
            from ocr_project_geometry import verify_geometry
            record = registry.get(args.project_id)
            packet = verify_geometry(registry, record, examined=not args.prepared)
            if not args.prepared and packet.get('correction_scope'):
                from ocr_project_corrections import historical_geometry_observations
                work = registry.root / record['artifacts']['workspace']
                if json.loads((work / 'geometry-checkpoint.json').read_text()).get('correction_scope') != packet['correction_scope']:
                    raise ProjectError('geometry_invalid', 'Original correction examination scope changed.')
                historical_geometry_observations(work, packet)
            result = response(args.operation, **record)
        elif args.operation == 'publish-geometry':
            from ocr_project_geometry import publish_geometry
            result = response(args.operation, **publish_geometry(registry, args.project_id, args.checkpoint))
        elif args.operation == 'prepare-output-review':
            from ocr_project_output_review import prepare_output_review
            result = response(args.operation, **prepare_output_review(registry, args.project_id, environment=args.environment))
        elif args.operation == 'publish-output-review':
            from ocr_project_output_review import publish_output_review
            result = response(args.operation, **publish_output_review(registry, args.project_id, args.proposal))
        elif args.operation == 'verify-output-review':
            from ocr_project_output_review import verify_output_review
            result = response(args.operation, **verify_output_review(registry, args.project_id))
        elif args.operation == 'verify-output-preparation':
            from ocr_project_output_review import verify_output_preparation
            result = response(args.operation, **verify_output_preparation(registry, args.project_id, args.sha256,
                output_manifest_sha256=args.output_manifest_sha256))
        elif args.operation == 'reserve-correction':
            from ocr_project_corrections import reserve
            result = response(args.operation, **reserve(registry, args.project_id,
                args.expected_iteration_id, args.expected_validation_sha256))
        elif args.operation in ('publish-correction', 'check-correction'):
            from ocr_project_corrections import publish
            result = response(args.operation, **publish(registry, args.project_id, args.cycle_id, args.proposal,
                check_only=args.operation == 'check-correction'))
        elif args.operation == 'bind-correction':
            from ocr_project_corrections import bind_attempt
            result = response(args.operation, **bind_attempt(registry, args.project_id, args.cycle_id, args.attempt))
        elif args.operation == 'prepare-correction-geometry':
            from ocr_project_corrections import prepare_geometry
            result = response(args.operation, **prepare_geometry(registry, args.project_id, args.cycle_id, environment=args.environment))
        elif args.operation == 'settle-correction':
            from ocr_project_corrections import settle
            result = response(args.operation, **settle(registry, args.project_id, args.cycle_id, reason=args.reason))
        elif args.operation == 'export':
            from ocr_project_export import export_project
            record = export_project(registry, args.project_id, environment=args.environment,
                                    reviewer_root=args.reviewer_root, geometry_checkpoint=args.geometry_checkpoint,
                                    previous_snapshot=args.previous_snapshot)
            result = response(args.operation, **record)
        elif args.operation in ('publish-reading', 'check-reading'):
            from ocr_project_reading import publish_reading
            result = response(args.operation, **publish_reading(registry, args.project_id, args.proposal,
                              check_only=args.operation == 'check-reading'))
        elif args.operation == 'reading-input':
            from ocr_project_reading import reading_input
            result = response(args.operation, **reading_input(registry, args.project_id))
        elif args.operation == 'patch':
            from ocr_project_review import patch_project
            record = patch_project(registry, args.project_id, args.patch, line_id=args.line_id,
                                   expected_review_sha256=args.expected_review_sha256)
            result = response(args.operation, **record)
        elif args.operation == 'query':
            from ocr_project_review import query_project
            result = query_project(registry, args.project_id, args.view, page=args.page,
                                   ids=args.ids, article=args.article, offset=args.offset,
                                   limit=args.limit, text_bytes=args.text_bytes)
        elif args.operation in ('prepare', 'resume'):
            from ocr_project_prepare import prepare_project, resume_project
            prepare = resume_project if args.operation == 'resume' else prepare_project
            record = prepare(registry, args.project_id, dpi=args.dpi,
                                     language=args.language, environment=args.environment,
                                     progress_events=args.progress_events, attempt_id=args.attempt_id)
            result = response(args.operation, **record)
        elif args.operation == 'list':
            result = registry.list_projects(offset=args.offset, limit=args.limit)
        else:
            record = registry.get(args.project_id)
            result = response(args.operation, **record)
        emit_response(result)
        return exit_code
    except ProjectError as error:
        record = {}
        if operation in ('prepare', 'resume', 'query', 'patch', 'export', 'validate'):
            try:
                record = registry.get(args.project_id)
            except (ProjectError, OSError):
                pass
        emit_response(response(operation, **record, status='failed', error={'code': error.code, 'message': str(error)}))
        return 1
    except OSError:
        emit_response(response(operation, status='failed', error={'code': 'io_error', 'message': 'Project filesystem operation failed.'}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
