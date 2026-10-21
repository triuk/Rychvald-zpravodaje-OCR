# Pozastavení, přerušení a pokračování průchodu

Ticket #19 extends the first complete pass through the public
`Application.dispatch` operations used by the native WebUI. The source scan,
frozen profile, original attempts, original protocol and usage observations stay
preserved. Continuing a run uses its existing parent identity and records another
execution session; an interrupted AI attempt keeps its own terminal record.

## Public operations and saved evidence

`pause_autonomous`, `interrupt_autonomous`, `reconcile_autonomous` and
`resume_autonomous` take `run_id` and the exact parent `attempt_id` returned by
`autonomous_status`. Resume also takes the saved `reconciliation_id`. A different
or changed attempt is rejected. Native stage buttons cannot bypass reconciliation
of an interrupted autonomous pass.

The parent manifest is under
`application/autonomous-attempts/<attempt_id>/attempt.json`. Each stage has a
durable intent identity and the exact child attempt identity. Child manifests
also bind that parent intent before starting their processes, covering the crash
between child allocation and the parent's final child-ID write. The registry
execution lock is acquired before an autonomous start can allocate another run.

Reconciliation saves its own JSON, integrity record and read-only inspection
protocols alongside the parent. The OCR checkpoint result and original provider
turn result are separate fields. A recovered thread does not validate OCR files;
a valid local checkpoint does not prove that a submitted provider turn failed.
Resume checks source bytes, immutable profile, pinned native and AI resources,
checkpoint evidence and completed child validators again before continuation.

The native `verify-resume RUN [--environment FILE] [--output]` operation preserves
the bounded version-1 process protocol. `--output` also verifies the current
PDF/TXT/source and frozen export input bindings. Verification does not publish a
new export iteration or send an AI turn.

## Pause and interrupt

The optional native `--control-file` is confined to the run workspace and bound
to a native attempt. Without it, existing CLI preparation behavior is unchanged.
Native page/OCR admission and a pause request share a file lock. The request is
recorded in history before the lock is released: no later unit-start event is
admitted. The two OCR workers finish only their already admitted units and retain
their atomic cache records. The unfinished preparation marker becomes `paused`;
it is not a verified completed preparation checkpoint.
After reconciliation, a new preparation attempt uses explicit native `resume`
when the original identity exists. Completed raster/OCR units retain their bytes
and modification times; a pause before identity creation can still start the
first preparation normally.

AI pause finishes the admitted turn and checks admission before another turn,
including phases inside reading, geometry and output examination. Completed
source reading can be referenced from its original evidence and continued with
the accounting turn through the original thread, without repeating source images.
Context diagnostic continuation similarly retains completed routing/recovery
records. Reused conversation evidence remains distinct from newly observed usage.

Interrupt closes admission, sends supported `turn/interrupt` for a known active
thread/turn, consumes available terminal/usage events during a bounded grace
period and stops owned processes. A locally interrupted transport may still have
unknown provider state. Native preparation, export, validation and native work
inside AI workers have owned process groups; observed helper start identities
allow cleanup even after a leader exits. Close blocks new starts, interrupts work
and saves the final parent/child state before the native adapter exits.

Original outgoing `turn/start` frames are correlated with their original response
or turn-start event. A submitted request with a missing acknowledgement remains
unknown if its exact accepted identity cannot be recovered. Such work cannot be
automatically retried. For identified turns, a separate supported `thread/read`
inspects the original turn before continuation. Completed provider output with
failed local publication is revalidated/published locally where its original
validated proposal is available, with a separate recovery record and no new AI.
If the provider reports the exact original turn completed but a reusable local
result is missing, reconciliation keeps the truthful provider `completed` state
and marks continuation unavailable. Resume fails with `original_result_unavailable`
before allocating any replacement child or submitting a turn. Supported completed
partial source/context results remain reusable; completion alone never authorizes
replaying their original work.

## Verification

Canonical local evidence is in repository `.scratch/ticket-19-proof`, outside the
disposable ticket worktree. Its logs distinguish earlier failed checks from the
final affected regression run. Tests use the existing pinned native Python/OCR
prefix with explicit `OCR_ENVIRONMENT`, `LD_LIBRARY_PATH`, `-B` and
`PYTHONDONTWRITEBYTECODE=1`; no runtime installation or change to the inventoried
prefix is part of this work.

`tests/test_webui_recovery.py` exercises the public operations and saved artifacts:

- Pause, close, create a new Application and continue the same named run.
- Pause while a native OCR unit is running, observe zero unit starts after the
  durable pause marker and at most two completions already in flight; resume the
  partial preparation using cached units without rewriting completed artifacts.
- Interrupt an actual native process, retain durable state and reject changed
  source bytes before resume.
- Interrupt a controlled AI peer through exact `turn/interrupt`, preserve partial
  original usage and reconcile the exact original turn through `thread/read`.
- Keep a lost submission acknowledgement unknown and block both resume and manual
  stage-button replay.
- Preserve completed source reading in a new child attempt and resume only the
  missing accounting turn through `thread/resume`.
- Reject changed environment/profile and a corrupted completed native artifact;
  provider reconciliation can succeed while the independent checkpoint fails.
- Reject a second Application's competing start before allocating another run.

The affected regression suite also covers native preparation, existing Codex and
context diagnostics, reading, geometry, export and metrics. The original metrics
tests retain their expected priced counts; control sidecars are excluded from
attempt enumeration. Legacy preflight records do not require new recovery fields
unless they actually have a new recovery record.

Before integration sync, all 57 affected tests passed in 331.421 seconds. After
sync with #22, a 29-test recovery/comparison/preparation run found four native
error-contract regressions and one invalid identity in the new pause-import test.
The error fix preserves original `ProjectError` codes and checkpoint bytes except
for the intentional pause transition. A fresh six-test run covering all five
failures plus partial preparation pause/resume passed in 33.996 seconds. The
earlier failed run stays preserved, rather than being relabelled as a full pass.
The donor-import check verifies that an already paused native attempt imports no
next raster/OCR unit and leaves the donor bytes and modification times unchanged.

The merger's lost-completion scenario has a separate controlled RED proof:
`completed-original-no-local-result-red.log` observed two provider starts before
the fix. `completed-original-recovery-green.log` passed all four targeted cases
in 44.701 seconds, including missing acknowledgement, interrupted usage and partial
reading continuation. After syncing #18, `correction-admission-red.log` exposed
correction allocation after a pause at native validation. Allocation now happens
inside the durable parent stage admission gate and carries the parent intent.
`post-18-recovery-admission-green.log` passed five cases in 114.386 seconds,
including the existing full automatic correction workflow. These are controlled
peers and fictional scan fixtures; no actual AI or GUI runs were added.
The final two-case check (`final-admission-original-count-green.log`, 30.057
seconds) also asserts exactly one outgoing original `turn/start` across all
diagnostic attempts and rejects manual correction replay after a saved pause.

## Native GUI close and restart

`tools/smoke_webui_recovery.py` runs `close` and `resume` in separate OS processes
against one durable fictional two-page case. It uses real local OCR plus the
explicit controlled process peer. It does not call an actual model or repeat
the real source/geometry/output examinations from tickets #15–#17.

The saved GUI case is
`.scratch/ticket-19-proof/native-gui/case.json`. The ordinary native window close
saved an interrupted context-preflight attempt with zero context `turn/start`
frames. Completed preparation and model preflight were retained. After relaunch,
the same run showed interrupted work, an enabled verification action and a
disabled resume action. Independent checkpoint verification enabled resume;
continuation completed validation as `ready_with_open_items`, with acceptance
`not_recorded` and the earlier interrupted attempt still visible.

Four saved PNGs show running controls, interrupted state after restart, verified
resume availability and completed validation. Root visually reviewed all four in
`ROOT-VISUAL-REVIEW.md`. The final screenshot's metrics panel was still loading;
it is not metrics evidence. One earlier resume harness had a DOM wait bug and
was rejected explicitly in `first-resume-harness-failure.json`; the corrected
resume phase is separately recorded with `errors: []`. The owned display and
browser profiles were released, without stopping unrelated desktop processes.

This ticket proves first-pass lifecycle behavior independently of correction
cycles. The optional correction manager receives the same pause/interrupt
control; combined interruption, descendant-turn reconciliation and preserved
cycle counting are part of final acceptance with #18/#23. Until that combined
recovery is implemented, an unfinished correction stage is explicitly unknown
and cannot resume or bypass reconciliation through a manual correction start.
Persistent queue
ordering and global AI availability handling are the downstream #20 increment.
