# Historical evidence archive

`tools/ocr_evidence_archive.py` captures and verifies an explicit inventory of
historical evidence. It does not discover aliases. Every identity contains the
original normalized absolute path, original trusted lowercase SHA256, kind,
source and explicit proof. One path can retain multiple historical hashes.

The public Python interfaces are:

```python
resolve_bound(original_path, expected_sha256, *, catalog=None)  # verified Path
load_bound({'path': original_path, 'sha256': expected_sha256}, *, catalog=None)
resolve_fragment(original_path, expected_sha256, *, line, byte_offset, catalog=None)
verify_catalog(catalog)
capture(inventory_path, output_directory)
```

`resolve_bound` first accepts matching bytes at the original path. Otherwise it
requires an exact whole-file catalog entry. It never matches just a hash, a
filename or a latest version. `load_bound` parses those verified bytes as JSON.
Both leave the original pointers and JSON untouched. A fragment is a separate
kind: `resolve_fragment` checks its one-based line number, zero-based byte offset
and SHA256 of the exact line including LF. A fragment hash cannot resolve through
the whole-file interface.

Pass `catalog={'path': '/absolute/catalog.json', 'sha256': '<trusted SHA256>'}`
for an externally pinned catalog. Passing an absolute catalog path uses its
`catalog.json.sha256` sibling. `OCR_EVIDENCE_CATALOG` supplies that path when no
argument is passed. The catalog and pin are trusted configuration: retain the
pin independently when checking an untrusted copy. Catalog changes, missing or
changed CAS objects, duplicate identities, symlinks and path traversal fail
closed. Relocating the whole archive directory preserves relative CAS references.

The standalone CLI is separate from `ocr_projects.py`:

```sh
python -B tools/ocr_evidence_archive.py capture --inventory /absolute/inventory.json --output /absolute/new-archive
python -B tools/ocr_evidence_archive.py verify --catalog /absolute/new-archive/catalog.json
python -B tools/ocr_evidence_archive.py resolve --catalog /absolute/new-archive/catalog.json --path /original/evidence.json --sha256 <trusted-SHA256>
```

Capture requires a previously absent output directory and publishes only after
all sources verify. Objects, the original capture inventory and catalog are
stored as read-only files. Capture can read an explicitly named exact Git commit
and confined member as bytes; it never executes historical code. No downloads,
source reconstruction or missing-byte substitution occurs.

An inventory has `records` and optional `workspace_bindings`:

```json
{
  "records": [{
    "original_path": "/original/work/image.png",
    "sha256": "<trusted lowercase SHA256>",
    "kind": "whole_file",
    "source": {"path": "/canonical/work/image.png"},
    "proof": {"origin_manifest": "/preserved/origin-map.json"}
  }],
  "workspace_bindings": [{
    "original_prefix": "/original/work",
    "canonical_prefix": "/canonical/work",
    "proof": {"origin_manifest": "/preserved/origin-map.json"}
  }]
}
```

`protocol_line` records also require `line` and `byte_offset`. Exact Git sources
use `source={"repository": "/absolute/repo", "commit": "<40-hex commit>",
"path": "relative/member"}`. Unavailable prepared evidence has
`status="unavailable"` and explicit classification proof; capture preserves the
record without an object. It remains unavailable.

`verify_visual_turn` keeps its existing signature and strict model, completion,
hook, context statistics, image and iteration checks. An original requested image
path may differ from the relocated workspace only through an explicit preserved
workspace binding and an exact original path+SHA catalog entry. Equal pixels or
equal encoded image hashes alone do not prove workspace lineage. Original native
protocols and model JSON are never rewritten.

Archive availability is historical read evidence. It grants no adapter
compatibility, active compare-and-swap precondition, executable/runtime resource
replacement, or installed-resource pin exception. Installed resources and the
single reviewed geometry compatibility pair retain their own strict checks.
`ocr_quality.check_bindings(records)` always checks current files strictly, even
when a catalog is configured. Audited historical reads explicitly opt into
`check_bindings(records, historical=True)` or use `load_bound`. Publication/CAS
and execution/resource call sites must retain the strict default.

The concrete release23 capture is retained in
`.scratch/ticket-23-proof/archive-resolver/`. Its pinned catalog contains 2,289
identities: 2,283 available and six proven unsubmitted prepared/preflight variants
marked unavailable. It includes 27 exact protocol fragments and 54 explicit
workspace bindings. The public verifier and independent verifier checked all
1,198 CAS objects. Original research maps, source freeze, RED/GREEN logs and
independent results remain beside it. This is not cleanup clearance or proof
that every unsupported/path-only historical string is an alias.
