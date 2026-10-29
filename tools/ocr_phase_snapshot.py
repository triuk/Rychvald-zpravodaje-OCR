"""Immutable first-completion inputs for diagnostic phase previews."""
import os
from pathlib import Path
import shutil
import tempfile

from ocr_projects import ProjectError, atomic_json, source_hash


def preserve_reading(work, project, packet, proposal_path):
    """Publish the whole first-reading archive at once under the project lock.

    A later reading or correction never updates this directory, including when
    the old archive has been damaged. The read view reports that damage.
    """
    parent = work / 'phase-previews'
    destination = parent / 'reading'
    if destination.exists():
        return
    parent.mkdir(parents=True, exist_ok=True)
    if not parent.resolve().is_relative_to(work.resolve()):
        raise ProjectError('reading_preview_invalid', 'First-reading archive must remain within this run.')
    with tempfile.TemporaryDirectory(prefix='.first-reading-', dir=parent) as temporary:
        stage = Path(temporary)
        files = {}
        for name, source in [('review.json', work / 'review.json'),
                             ('publication.json', work / 'reading-publication.json'),
                             ('input.json', work / 'reading-input.json'),
                             ('source-manifest.json', work / 'input-manifest.json'),
                             ('proposal.json', proposal_path)]:
            shutil.copyfile(source, stage / name)
            files[name] = source_hash(stage / name)
        atomic_json(stage / 'manifest.json', {'schema_version': 1, 'phase': 'reading',
            'run_id': project['run_id'], 'source_sha256': project['source_sha256'],
            'profile_sha256': packet.get('profile_sha256'),
            'run_manifest_sha256': packet.get('run_manifest_sha256'), 'files': files,
            'meaning': 'First completed reading, before subsequent corrections.'})
        os.rename(stage, destination)


def preserve_geometry(work, project, packet):
    """Freeze the first validated native publication, also used by recovery."""
    parent = work / 'phase-previews'
    destination = parent / 'geometry'
    if destination.exists():
        return
    parent.mkdir(parents=True, exist_ok=True)
    if not parent.resolve().is_relative_to(work.resolve()):
        raise ProjectError('geometry_preview_invalid', 'First-geometry archive must remain within this run.')
    names = ['geometry-checkpoint.json', 'geometry-preparation.json', 'input-manifest.json',
        'reviewed-lines.json', 'pages.json', 'geometry.json', 'review.json',
        'segmented-review.json', 'segment-manifest.json']
    with tempfile.TemporaryDirectory(prefix='.first-geometry-', dir=parent) as temporary:
        stage = Path(temporary)
        files = {}
        for name in names:
            shutil.copyfile(work / name, stage / name)
            files[name] = source_hash(stage / name)
        atomic_json(stage / 'manifest.json', {'schema_version': 1, 'phase': 'geometry',
            'run_id': project['run_id'], 'source_sha256': project['source_sha256'],
            'profile_sha256': packet['identity'].get('profile_snapshot_sha256'),
            'run_manifest_sha256': packet['identity'].get('run_manifest_sha256'), 'files': files,
            'meaning': 'First completed geometry before subsequent automatic corrections.',
            'geometry_status': 'approximation_requires_character_review'})
        os.rename(stage, destination)
