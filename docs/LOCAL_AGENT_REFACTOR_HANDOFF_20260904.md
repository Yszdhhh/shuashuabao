# ShuaBao Local Agent Refactor Handoff — 2026-09-04

This handoff implements `docs/ARCHITECTURE_CONVERGENCE_20260904.md` and is intentionally staged. The local agent must treat the architecture document as the controlling contract and must not interpret it as permission for a broad rewrite.

## Mission

Perform a code-grounded architecture convergence of ShuaBao that improves long-thread stability, visual evidence quality, retry/postcondition discipline and incident replayability while preserving the current FSM and already validated business semantics.

## Baseline

Repository: `https://github.com/Yszdhhh/shuashuabao`

Start from the exact current `trial-merge` HEAD. Record it before any work. The architecture plan was added after `0baa2e5f17f7cfafca1b008a2070f49b03cf9748`, so do not assume that older SHA is still HEAD.

Create an isolated worktree and branch. Recommended:

- branch: `refactor/architecture-convergence-20260904`
- worktree: `G:\刷刷宝\Worktrees\architecture-convergence-20260904`

Do not reuse an unrelated dirty worktree.

## Non-negotiable safety rules

- UNKNOWN / ambiguous / unclassified / no reliable evidence => ZERO INPUT.
- Click/SendInput success is never business PASS.
- No BT/statechart rewrite, microservices, plugin system, generic DSL, YOLO-everywhere, second OCR service or UI rewrite.
- Do not add a second FrameEvidence/VerifiedAction/Incident service when existing structures can be evolved.
- Mechanical retry may be shared; business fallback must remain visible in Policy/FSM.
- A generic action helper may not introduce a second target.
- Do not weaken tests, thresholds, fixtures or baselines to obtain green.
- Synthetic replay cannot be reported as real business PASS.
- Do not perform real SendInput/KK testing unless the user explicitly authorizes the local machine session.

## Phase 0 — establish facts before editing production behavior

Read at minimum:

- `docs/ARCHITECTURE_CONVERGENCE_20260904.md`
- `src/shuabao/mediator.py`
- `src/shuabao/runtime_mediator.py`
- `src/shuabao/interaction_surface.py`
- `src/shuabao/incidents.py`
- `src/shuabao/vision/matcher.py`
- `src/shuabao/vision/choice_ocr.py`
- `src/shuabao/vision/ocr_shadow/*`
- `src/shuabao/lobby_hitch.py`
- relevant policy/FSM modules
- tests/fixtures/tools related to the above

Create `docs/ARCHITECTURE_STAGE0_AUDIT_20260904.md` with evidence-backed findings for the five questions below.

### A. OCR usage map

Enumerate production OCR call sites and classify each as:

- `VALUE_OPEN`
- `VALUE_TYPED`
- `EXPECTED_VALUE`
- `CATEGORY`
- `DISPLAY_DEBUG_ONLY`

For each call site record:

- file/function;
- ROI source;
- current OCR kind/model path;
- how the return value is consumed;
- whether exact text value changes Policy;
- whether a cheaper finite verifier/template/color/anchor can satisfy the business need;
- Ground Truth required before changing it.

Do not replace anything yet.

### B. Transient-state scope/reset map

Search long-lived fields and timers including patterns like:

- `_retry*`
- `_attempt*`
- `_last_*`
- `_cooldown*`
- `_next_at`
- cached target/rect/score/signature
- watchdog confirmations
- pending-action state

Classify each as:

- step-scoped
- scene-scoped
- round-scoped
- session-scoped

Record where it resets. Flag only state that can outlive its intended scope or whose reset depends on one fragile branch.

### C. Frame freshness map

Document:

- how `FrameEvidence.gen` advances;
- where input invalidates old evidence;
- whether all recognizers in one authority decision read the same frame;
- whether any postcondition can consume a pre-input frame;
- whether any compatibility cache bypasses generation semantics.

Do not create a new frame/evidence type unless the existing one cannot represent a required invariant.

### D. Recovery/input-authority map

Enumerate all production paths that may send recovery/liveness input, especially:

- ESC/back/close;
- fixed-coordinate actions;
- watchdog actions;
- disconnect/failure recovery;
- panel hide/close fallback;
- retry loops that send the same input repeatedly.

For each record:

- scene/visual authority;
- fresh-frame requirement;
- postcondition;
- retry/time budget;
- reset scope;
- whether UNKNOWN can reach it.

Pay special attention to the runtime watchdog ESC path: do not remove it merely because it is an ESC. Verify whether its two-frame HUD authority, modal exclusions, budget and next-frame semantics are sufficient or whether it still needs a safer pending-action/postcondition contract.

### E. Existing architecture reuse map

Explicitly record what is already provided by:

- `FrameEvidence`
- `MatchResult`
- `ActionLifecycle`
- `PendingAction`
- `IncidentArchiver`
- matcher caches/margin/ROI/color helpers
- OCR production bootstrap/warmup

Any proposed new abstraction must explain why one of these cannot be extended.

## Phase 0 gate

No behavior-changing production change until the Stage 0 audit exists and can answer:

1. Which 2–4 changes have the highest evidence-backed benefit/risk ratio?
2. Which external-review suggestions are already implemented and therefore must not be rebuilt?
3. Which suspected long-thread failures are actual code facts versus hypotheses?

Commit Stage 0 audit separately.

## Phase 1 — low-risk convergence only

Choose 2–4 items from the Stage 0 evidence. Do not automatically implement every item below.

### Candidate 1: typed OCR read / expected-value verifier

If Stage 0 confirms an OCR path only needs a finite value/category:

- prefer a parameterized typed-read helper rather than an OCR class hierarchy;
- supported initial kinds should remain minimal, e.g. `digit`, `counter`, `lexicon_name`;
- parse/validation failure => UNKNOWN;
- preserve raw text/confidence/profile in diagnostics;
- for lobby prefix `4/3`, prefer an expected-glyph verifier if GT shows that is sufficient; do not create 0–9 assets unless actually needed.

### Candidate 2: count-based color evidence

Only for confirmed NCC blind spots with real fixtures.

Implement one small reusable helper/profile using existing matcher conventions:

- RGB or HSV mask range;
- count/coverage or F1-style evidence;
- optional morphology;
- explicit geometry/semantic constraints remain at caller/profile level;
- hard AND authority for safety-critical actions;
- optional fused score only for ranking experiments.

Pilot only 2–3 targets with existing Ground Truth, e.g. enabled/disabled or ready/not-ready.

Do not replace all template matching.

### Candidate 3: PendingAction/ActionLifecycle convergence

Before adding a new `VerifiedAction`, test whether current `PendingAction` + `ActionLifecycle` can be evolved.

Desired common behavior:

- fresh precondition;
- one recognized target;
- one mechanical action;
- business postcondition;
- timeout;
- same-target bounded retry;
- re-observe before every retry;
- typed failure reason.

Business fallback remains in Policy/FSM.

Migrate only one repeated mechanical pattern first.

### Candidate 4: scoped transient reset

If Stage 0 finds a real leakage path:

- introduce the smallest centralized reset boundary possible;
- do not mass-delete fields or move them into a new state container without evidence;
- write a regression test proving the stale value used to survive and now resets.

### Candidate 5: incident enrichment

Extend `IncidentArchiver` rather than creating another trace service.

Add only missing high-value metadata such as frame generation, recognition method/score/margin/ROI, pending action, postcondition attempts, scoped retry/timer values, release/resource identity and runtime-health summary.

Keep storage bounded and passive.

## Phase 1 tests

For every behavior change:

- add/adjust focused tests first;
- use existing real fixtures whenever available;
- wrong-positive regression is blocking;
- critical positive UNKNOWN/recall must not regress beyond baseline;
- preserve UNKNOWN zero-input tests;
- preserve click-success-vs-postcondition tests.

Run focused tests, then:

`python -m pytest tests -q --tb=short`

and the current release gate tooling used by this branch.

If a full suite is too slow, still run it before final handoff.

## Phase 2 — limited business migration

Only after Phase 1 is green, migrate 2–5 high-value transitions that already have GT.

Select from actual evidence. Likely candidates include:

- lobby prefix/search confirmation;
- room ready/start confirmation;
- one card/panel choice lifecycle;
- one post-game transition.

For each transition write a short migration note:

- old authority;
- old action/postcondition;
- new authority;
- new action/postcondition;
- mechanical retry budget;
- business fallback location;
- real fixtures used;
- false-positive behavior;
- rollback condition;
- what still requires Windows/KK real validation.

High-risk transition may use two fresh confirmations and semantic-ROI stability. Do not require whole-frame freeze on animated screens.

## Recovery governance scope

Do not implement a universal recovery engine.

In this project phase only allow:

- L0: bounded observe/no input;
- L1: independently recognized known popup/known recovery page + verified action;
- L4: BLOCK/stop + incident.

Defer generic L2/L3 navigation/restart until business idempotency and multiplayer side effects are proven per scene.

## Soak / real-machine phase

Do not claim production readiness from offline tests.

When explicitly authorized to run locally, capture a baseline and then a post-change soak. Desired target is 50–100 rounds, but use the available business window honestly.

Record at minimum:

- completed rounds;
- UNKNOWN rate and longest UNKNOWN episode;
- wrong-input incidents;
- recovery/watchdog actions;
- pending-action timeouts;
- OCR worker restarts;
- memory/handle/thread slope;
- incident bundle count;
- any manual intervention.

A shorter run can be evidence but not a substitute for the stated long-thread target.

## Cleanup phase

Only after migrated paths pass offline and real-machine evidence:

- remove duplicated special cases made obsolete by the migration;
- remove stale tests only with a documented replacement/semantic equivalence;
- do not optimize for mediator line count;
- do not add another abstraction while cleaning up.

## STOP conditions

Stop the current change and report instead of forcing completion if:

- UNKNOWN gains input authority;
- a generic action helper needs a second target/fallback;
- click/frame-change becomes the business postcondition;
- a new concept duplicates `FrameEvidence`, `PendingAction`, `IncidentArchiver` or matcher infrastructure;
- real incident fixture produces a wrong positive;
- critical positive recall collapses into UNKNOWN;
- a perception config starts containing workflow/action policy;
- the only evidence of improvement is synthetic replay;
- the change requires weakening an existing release/safety gate.

## Git delivery

At start, report:

- base branch;
- exact base SHA;
- worktree path;
- new branch;
- initial `git status --short`.

Commit coherently, suggested order:

1. `docs(arch): audit convergence candidates`
2. `refactor(vision): converge evidence and typed recognition` (only if selected)
3. `refactor(runtime): consolidate verified mechanical actions` (only if selected)
4. `test(arch): add real-incident and lifecycle regressions`

Do not use `git add .` / `git add -A`.

Push the branch. Do not merge automatically. Do not create a PR unless explicitly requested or the repo's active workflow requires one; if a PR is created, keep it draft until local/CI evidence is attached.

Final handoff must report:

- branch/base/head;
- commits;
- files changed;
- Stage 0 findings;
- which Phase 1/2 items were actually chosen and why;
- focused/full test commands + exact results;
- CI/release-gate result;
- offline GT/replay evidence;
- real-machine evidence separately, or explicitly `NOT RUN`;
- known blockers;
- rollback points;
- whether merge is recommended: `NO`, `READY FOR REVIEW`, or `READY AFTER LIVE VALIDATION`.

The mission is not to make the architecture look cleaner. The mission is to reduce error propagation and duplicated mechanics while preserving fail-closed, postcondition-driven behavior.
