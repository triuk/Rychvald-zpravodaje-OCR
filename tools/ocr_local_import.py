"""Conservative cross-run import of deterministic full-page preparation only.

The caller holds the donor reader lock and destination writer lock. Native
preparation still applies its ordinary exact cache gates after every import.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile
import threading

from ocr_projects import ProjectError, atomic_json, source_hash


@contextmanager
def donor_snapshot(registry, donor_id, destination_id):
    if donor_id is None:
        yield None
        return
    if donor_id == destination_id:
        raise ProjectError('invalid_donor', 'A local preparation donor must be another named run.')
    donor = registry.get(donor_id)
    target = registry.get(destination_id)
    if ('run_manifest' not in donor['artifacts'] or 'run_manifest' not in target['artifacts'] or
            donor['project']['source_sha256'] != target['project']['source_sha256']):
        raise ProjectError('invalid_donor', 'Choose two named runs of the same complete source hash.')
    work = registry.root / donor['artifacts']['workspace']
    if work.is_symlink() or not work.resolve().is_relative_to(registry.root.resolve()):
        raise ProjectError('invalid_donor', 'Donor workspace is outside the registry.')
    source = registry.root / donor['artifacts']['source']
    if source_hash(source) != donor['project']['source_sha256']:
        raise ProjectError('source_corrupt', 'Donor registered source differs from its complete hash.')
    from ocr_profiles import load_profile, ProfileError
    parameters = []
    try:
        for record in (donor, target):
            manifest = json.loads(regular(registry.root, record['artifacts']['run_manifest']).read_text())
            if (manifest['run_id'] != record['project']['run_id'] or
                    manifest['edition_id'] != record['project']['source_sha256']):
                raise ValueError('Named run identity differs')
            profile = load_profile(regular(registry.root, record['artifacts']['profile_snapshot']),
                                   expected_sha256=manifest['profile_sha256'])
            parameters.append(profile['profile']['parameters'])
    except (OSError, ValueError, KeyError, TypeError, ProfileError) as error:
        raise ProjectError('invalid_donor', 'Donor/destination immutable run profiles are unavailable or changed.') from error
    snapshot = {'run_id': donor_id, 'work': work, 'parameters': parameters[0], 'target_parameters': parameters[1]}
    lock = work / '.operation.lock'
    if not lock.is_file() or lock.is_symlink():
        yield {**snapshot, 'available': False}
        return
    with lock.open('r') as stream:
        try:
            # Both locks are nonblocking, so opposite-direction imports cannot
            # wait for one another or create an AB/BA deadlock.
            fcntl.flock(stream.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ProjectError('project_busy', 'The donor is being changed by another operation.') from None
        yield {**snapshot, 'available': True}


def regular(root, relative):
    path = root / relative
    if ('..' in Path(relative).parts or not path.is_relative_to(root)
            or not path.resolve().is_relative_to(root.resolve())):
        raise ValueError('Import path escapes workspace')
    for component in (path, *path.parents):
        if component == root.parent:
            break
        if component.is_symlink():
            raise ValueError('Import paths may not contain symlinks')
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('Import requires regular files')
    return path


class LocalImporter:
    def __init__(self, donor, work, identity, progress):
        self.donor, self.work, self.progress = donor, work, progress
        self.units = {}
        self.lock = threading.Lock()
        self.compatible = False
        if donor:
            try:
                anchor = json.loads(regular(donor['work'], 'preparation-identity.json').read_text())
                self.compatible = (donor['available'] and isinstance(anchor, dict) and anchor.get('identity') == identity
                    and all(donor['parameters'][key] == identity[key] for key in ('dpi', 'language')))
            except (OSError, ValueError, TypeError):
                pass
            if not self.compatible:
                progress.emit('local_import_rejected', donor_run_id=donor['run_id'],
                    reason='Full source/parameters/native resource identity unavailable or different.')

    def import_unit(self, step, sidecar, outputs, expected_identity, validate=None):
        with self.lock:
            return self._import_unit(step, sidecar, outputs, expected_identity, validate)

    def _import_unit(self, step, sidecar, outputs, expected_identity, validate=None):
        if not self.compatible:
            return False
        donor, work = self.donor['work'], self.work
        temporary = []
        try:
            if any((work / name).exists() or (work / name).is_symlink() for name in [sidecar, *outputs]):
                return False  # Existing destination units belong to this run.
            original_path = regular(donor, sidecar)
            original_bytes = original_path.read_bytes()
            saved = json.loads(original_bytes)
            if (not isinstance(saved, dict) or saved.get('schema_version') != 1 or saved.get('status') != 'completed' or
                    saved.get('identity') != expected_identity or
                    not isinstance(saved.get('outputs'), dict) or set(saved['outputs']) != set(outputs.values()) or
                    validate and not validate(saved)):
                raise ValueError('Donor checkpoint identity/schema/output set is invalid')
            hashes = {}
            for relative, key in outputs.items():
                path = regular(donor, relative)
                expected = saved['outputs'][key]
                if source_hash(path) != expected:
                    raise ValueError('Donor output hash differs')
                destination = work / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.parent.is_symlink() or destination.parent.resolve() != destination.parent:
                    raise ValueError('Destination import path contains symlinks')
                with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
                    copy = Path(stream.name)
                    temporary.append(copy)
                    with path.open('rb') as source:
                        for block in iter(lambda: source.read(1024 * 1024), b''):
                            stream.write(block)
                    stream.flush()
                    os.fsync(stream.fileno())
                if source_hash(copy) != expected or source_hash(path) != expected:
                    raise ValueError('Output changed during verified copy')
                hashes[relative] = expected
            if original_path.read_bytes() != original_bytes:
                raise ValueError('Donor checkpoint changed during copy')
            record = {'step_id': step, 'donor_run_id': self.donor['run_id'],
                'destination_run_id': self.progress.run_id, 'import_attempt_id': self.progress.attempt_id,
                'donor_sidecar': sidecar, 'donor_sidecar_sha256': source_hash(original_path),
                'outputs': hashes, 'origin': 'imported_local'}
            if 'command' in expected_identity:
                # Only argv locations 1 (raster) and 2 (output prefix) may move.
                command = list(expected_identity['command'])
                command[1] = str(work / Path(command[1]).relative_to(donor))
                command[2] = str(work / Path(command[2]).relative_to(donor))
                record.update(donor_command=expected_identity['command'], destination_command=command,
                    rebound_argv_slots=[1, 2])
                saved['identity'] = {**expected_identity, 'command': command}
            for copy, relative in zip(temporary, outputs):
                os.replace(copy, work / relative)
            for directory in {str((work / name).parent) for name in outputs}:
                with directory_descriptor(directory) as descriptor:
                    os.fsync(descriptor)
            # A crash without this completed marker cannot be a cache hit.
            saved['import_provenance'] = record
            atomic_json(work / sidecar, saved)
            with directory_descriptor(str((work / sidecar).parent)) as descriptor:
                os.fsync(descriptor)
            self.units[step] = record
            provenance = work / 'local-imports.json'
            previous = json.loads(provenance.read_text()) if provenance.exists() else {'schema_version': 1, 'units': []}
            previous['units'].append(record)
            atomic_json(provenance, previous)
            return True
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.progress.emit('local_import_rejected', step, donor_run_id=self.donor['run_id'], reason=str(error))
            return False
        finally:
            for path in temporary:
                path.unlink(missing_ok=True)

    def origin(self, step, reused):
        record = self.units.get(step)
        return ({'origin': 'imported_local', 'donor_run_id': record['donor_run_id'],
                 'import_provenance': record} if record and reused else
                {'origin': 'same_run_cache' if reused else 'computed'})


@contextmanager
def directory_descriptor(directory):
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        yield descriptor
    finally:
        os.close(descriptor)
