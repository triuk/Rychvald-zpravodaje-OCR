# Archived native verification fixtures

These files retain exact repository bytes for the public prior-generation
geometry scenario in `test_webui_geometry_preview.py`. They are test inputs,
not production imports or an alternative application implementation.

| File | Source revision | SHA-256 |
| --- | --- | --- |
| `geometry-adapter-before-phase-previews.py` | `91ae8a1`, unchanged from `31c9e19` | `ce6d912f9bddc7d58a61e8ce1b37fb733a2768a3bdb6c7637e76734281b4d2ae` |
| `visual-evidence-before-activity-overrides.py` | `91ae8a1` | `dd36b0732befec14f4a6df91e7af6e61fac4e5fd75ffcde11b0856e582f03754` |
| `output-review-before-activity-overrides.py` | `91ae8a1` | `fed8d69ee1a5173cc332c2f9cb83c426a3d1a43fd80dd6f913cd74270666a585` |

The test builds an explicitly selected temporary native prefix with these prior
calling contracts and a frozen common model profile. It produces actual native
geometry, switches to the current public application/native validator, and
verifies the original evidence without rewriting it. Changing the archived
generating adapter is rejected. This proves the narrow reviewed validator
migration; it does not claim acceptance of an entire historical portable runtime
or availability of a live model.
