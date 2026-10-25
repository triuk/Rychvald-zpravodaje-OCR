# Offline application release

The supported runtime is the selected Linux x86_64-v3 closure with its captured
loader and libraries. A desktop browser/display is an external prerequisite for
normal GUI launch. This is not a claim of compatibility with every Linux system.
Program installation and edition project data must use separate directories.

The existing `capture`, `build`, `install` and `bin/rychvald-ocr` interfaces remain
available. The complete application uses two additional public operations:

```sh
python -B tools/ocr_bundle.py capture-release --selection native/release-inputs.json --inputs /release/inputs
python -B tools/ocr_bundle.py build-release --inputs /release/inputs --output /release/rychvald-ocr.tar.gz
python -B tools/ocr_bundle.py install --archive /release/rychvald-ocr.tar.gz --sha256 ARCHIVE_SHA256 --destination /program/version-1
/program/version-1/bin/rychvald-ocr verify
/program/version-1/bin/rychvald-ocr-gui --root /data/edition-projects --browser Chromium
```

Capture verifies the explicit reviewed resource selection and native lock before
copying SHA-addressed objects. It verifies the pristine context-mode source
against its original complete file inventory, applies only the pinned no-install
adapter, and verifies the prepared tree. It also captures the current `main.py`,
`app/`, `ui/`, `profiles/`, `tools/` and `native/` boundary, including newly added
recovery tools. The descriptor records the source revision, whether the checkout
was dirty, file bytes/modes, original provenance and component pins. A dirty
capture is helper-source evidence; final releases must be captured from the clean
reviewed commit. No account files or home directory are capture sources.

`build-release` uses only the captured directory. It never reads runtime files
from the selection's original paths, downloads, repairs dependencies, or installs
packages. Missing/changed objects fail before an archive is produced. Identical
captured inputs produce byte-identical archives. Installation verifies the full
file/mode inventory and native runtime before publishing a new prefix; it refuses
an existing destination. To replace a version, install into a new program prefix,
stop the old application, and launch the new prefix with the same external
`--root`. Moving the complete program directory also preserves resource lookup.

The GUI launcher verifies the complete inventory before importing application or
WebUI code. This includes the selected native WebUI library and its dependencies,
so the wrapper's downloader cannot repair a missing library. Installed mode
ignores development runtime overrides, selects its bundled OCR/Codex, and reads
`native/bundled-context.json`. Raw native executable hashes remain distinct from
generated loader command vectors. Hooks and MCP use bundled env/Node/Python/
Bash/sh and libraries; their PATH contains only the per-run runtime directory.
Installed per-run interpreter commands are executable shims generated from the
verified descriptor's absolute loader/native vectors. They do not invoke the
bundle's location-relative shell wrappers through symlinks. Each resolved command
set gets a separate directory under `.runtime-bin`; relocation or replacement
selects a new set without rewriting previous run files. Existing generated shims
must still match their expected bytes/modes. The six original context-mode hook
entrypoints are unchanged. Hook/MCP HOME and
CODEX_HOME are per-run storage; the Codex process retains the caller's separately
provided account environment. Credentials are not distributed with the program.

## Native server and external browser seam

```sh
/program/version-1/bin/rychvald-ocr-gui --root /data/edition-projects --serve
```

`--serve` calls the pinned wrapper's `Window.start_server('index.html')` directly,
after `set_public(False)`. It does not call `show`, `show_browser`, or webview
fallback. It prints one flushed JSON object with `operation: "serve"`,
`status: "ready"`, a loopback HTTP `url`, and the application's `pid`. The process
stays alive until SIGINT/SIGTERM; it then closes the application workers and
destroys its native window. `--serve` and `--browser` are mutually exclusive.
An external browser can use this loopback URL without joining the program's
filesystem namespace. Network sharing for this loopback seam is explicit.

## Original installed resources after relocation

A named installed run records its exact original prefix and inventory before
work starts. The registry keeps a deduplicated, immutable byte archive under
`application/installed-resource-archives/`, outside model workspaces. Original
packets and paths remain unchanged. History validation explicitly opts into
this archive only for a missing installed resource whose original absolute
path, relative inventory entry and SHA256 all match the frozen run origin.
Existing changed files and run-local source/review/pixel/publication CAS stay
strict. Archive files are evidence and are never executable runtime selections.

Before retiring an older installation whose runs lack that origin record, use
the current native CLI with the still available original prefix:

```sh
/program/current/bin/rychvald-ocr --root /data/edition-projects --json capture-installed-origin RUN --prefix /program/original
```

This verifies and captures the complete original inventory and exact environment
JSON, then adds separate origin metadata. It does not rewrite old model packets.
Repeated captures reuse the registry archive. If an old environment path is
missing, native work can select the current installation's verified environment
only when its manifest bytes are identical to the frozen original SHA256.
Different normalized JSON is not treated as byte equality or automatically
authorized execution compatibility.

Completed results and history remain readable from the new verified prefix.
An interrupted autonomous pass also freezes its AI command/resource paths.
If moving the program changes that runtime fingerprint, explicit reconciliation
returns `checkpoint_identity_changed` and keeps the original parent, children,
reserved budget and protocols. It admits no replacement work. Restore the
original verified installation and AI/native configuration at their recorded
paths, reconcile the same attempt, then explicitly resume when its original
provider state permits continuation. Relocation never silently normalizes or
redefines an active run's runtime.

The geometry policy retains the exact original `27c12d6d… → 046c6af6…` pair and
adds only explicitly pinned validator-only installed-evidence pairs. Original
adapter bytes must still exist in their run snapshot; copied-adapter drift is
rejected. Generating code, font selection, sample expectations and quality
criteria are unchanged.

The exact selected native WebUI has an additional host-dependent behavior:
`Window.__init__` calls `webui_new_window`, then `webui_new_window_id`, which calls
`webui_set_center`, `_webui_load_gtk_and_webkit`, and the discovered `gtk_init`.
This happens before `start_server`. A host with discoverable GTK and no working
display can therefore exit during window construction even in server mode.
An empty-root namespace containing only the pinned runtime does not expose GTK
to `dlopen`; the same selected library then serves the real UI without a browser
or display. This is the headless isolation test condition. No host GTK is copied
into the package and the selected library is not substituted. Desktop validation
requires its declared browser/display and remains separate from server proof.

## Provenance details

`native/release-inputs.json` pins WebUI wrapper 2.5.8 as installed artifacts.
The original CRLF `RECORD` bytes have SHA256
`5a560358aa463738eeb4614a797cc81df40f1e7587b8f2c8666393477cb699a8`.
The earlier research identity
`e31e52dedc5777ee56a75ea5620d2615f23842e7ccf01463629e66eea2bf8d19`
is explicitly the text normalized to LF, not the raw file hash. Capture preserves
the original bytes. All declared non-bytecode members were checked against
RECORD; each selected file also has its own raw byte pin. Selected clang native
WebUI SHA256 is
`59b7230ee0a6608ea6fa5bd38cf327851c0a0cc980976b13793723d25dacf768`.
It is absent from RECORD; its archive origin is unestablished and is recorded as
a locked installed native artifact, separately from wrapper version/provenance.

Codex and companion match the retained selected package members; package signature
verification was not performed. Node is the pinned CUA build, not a claimed
vanilla Node release. The env pin is the reviewed coreutils 9.12-2.1 installed
file, with its exact local metadata and declared GPL/GFDL license mapping.
The recovered native lock retains the explicitly reviewed jbig/zstd build
differences. `provenance/release.json`, `provenance/input-lock.json`, the complete
inventory and retained license/NOTICE bodies preserve these distinctions.

`tests/test_release_bundle.py` exercises the public capture/build/install/launch
interfaces with real resources, actual native WebUI serving, original six hooks,
real MCP execution, empty-root isolation, tamper rejection, deterministic builds,
relocation/replacement and the existing mandatory native A1–A11 fixture. It needs
the reviewed local capture inputs and bwrap; required checks are not skipped.
These are packaging checks. Actual account/model, desktop GUI and whole-project
B1–B9 acceptance require the final reviewed integrated source and separate proof.
