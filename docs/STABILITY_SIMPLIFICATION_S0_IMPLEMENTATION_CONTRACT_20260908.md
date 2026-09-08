# ShuaBao Stability Simplification S0 — Implementation Contract — 2026-09-08

> Control-tower contract. Documentation only on `handoff/latest`. This freezes the allowed intent and acceptance criteria before production implementation. It does not itself modify ShuaBao runtime behavior.

## 0. Baseline and purpose

Production-code base:

`decb9b6eb3559e39ea51e26864eaada0d648855b`

Current integration base:

`d1fb4a51310f3f847ebeee110d51d8423050468b`

`d1fb4a5` differs from `decb9b6` only by the frozen Policy v0.1 documentation migration.

Purpose of S0:

Reduce long-run control-state complexity and duplicate authority without weakening existing fail-closed safety semantics, business postconditions, or current verified functionality.

S0 is a simplification/consolidation wave, not a feature-expansion wave and not Policy v0.1 implementation.

## 1. Frozen design principles

A and C same-game competitor research independently supports these constraints:

1. **One clear progression owner per active business/failure domain.** Peer FSMs/watchdogs/fallbacks must not independently advance or escape the same business condition.
2. **Detector authority is page/job-local.** Asset inventory size is irrelevant; only the bounded detector set relevant to the verified current window/page may grant transition/action authority.
3. **Mechanical capability is not business authority.** Capture, click, key, window enumeration/activation and timers are helpers; they do not independently advance business state.
4. **Re-observe scene facts where possible.** State that is directly derivable from a fresh trusted frame should not become a long-lived semantic latch.
5. **Keep only minimum asynchronous action memory.** Request/input/fresh-postcondition correlation remains necessary where a business action spans ticks.
6. **Explicit state lifetime and round reset.** Important state is classified as `FRAME_LOCAL / PAGE_LOCAL / ACTION_LOCAL / ROUND_LOCAL / SESSION_GLOBAL / PERSISTENT`; transient round/action state has an explicit reset owner.
7. **Window ownership gates recognition/action authority.** Platform/game/unknown roles remain distinct and ownership/activation failure is fail-closed.

## 2. Non-negotiable safety invariants

S0 must preserve or strengthen all of the following:

- `UNKNOWN / ambiguous -> ZERO INPUT`.
- Click/key/SendInput dispatch success is not business success.
- Frame mutation, bookmark, frame ID or generic fingerprint change alone is not a business postcondition.
- Business transitions require fresh, business-relevant evidence.
- Perception recovery, input retry, and business fallback remain distinct concepts.
- UNKNOWN may authorize bounded re-observation/reacquisition only; it never by itself authorizes blind `ESC`, `QUIT`, `HOME`, stage click, or unrelated fallback.
- Tests, fixtures, thresholds and gate baselines must not be weakened merely to obtain PASS.
- Existing real-GT gaps remain gaps; S0 must not relabel them as confirmed.

## 3. S0 implementation scope

The implementation Agent must begin with a current-SHA control-authority inventory and a short Failure Model + Contract Matrix before editing code.

### 3.1 Progression/liveness authority audit and consolidation

Identify every current owner that can:

- change top-level `Phase`;
- send generic recovery input;
- escape a stalled business state;
- force a terminal/error/quit path;
- retry a business transition.

The known Core-vs-Runtime overlapping liveness mechanisms are mandatory review targets.

Target property:

For any one failure domain, exactly one layer owns business progression/recovery. Other layers may observe, emit telemetry, or raise a typed signal, but must not independently send competing recovery input or advance the same business state.

Do not replace duplicate owners with a new third watchdog.

### 3.2 Window-role authority

Define/centralize the authoritative interpretation of:

`PLATFORM / GAME / UNKNOWN`

before page detectors obtain transition or input authority.

Requirements:

- the token `KK` alone must not be sufficient to grant GAME role;
- known game identity such as verified game title/process/binding may grant GAME according to current proven behavior;
- explicit platform identity cannot be promoted to GAME merely because it contains numeric rows, blue buttons, or other visual confounders;
- current titleless compatibility must not be removed without GT showing it is safe to do so;
- all input-bearing paths remain foreground/ownership gated.

### 3.3 Detector authority scheduling

Audit the Golden Path first:

`LOBBY/ROOM -> STAGE -> MAIN_LINE -> POSTGAME -> QUIT/NEXT`

For each page/episode record:

- allowed detector families;
- detectors that may grant transition authority;
- detectors that are safety veto only;
- detectors that must not run or must not change progression in that context.

Do not delete useful assets merely to reduce counts. The target is a narrower active authority set, not a smaller asset folder.

### 3.4 Scene state vs action lifecycle

Classify current latches/state fields.

Prefer fresh re-observation for values that can be derived from a trusted frame.

Retain minimum action-lifecycle state where required for asynchronous correlation, including as applicable:

- request/action identity;
- precondition evidence generation/fingerprint;
- whether input was attempted;
- bounded deadline/attempt budget;
- expected business postcondition;
- fresh postcondition/outcome evidence.

`PendingAction` or equivalent action memory must not be deleted merely because competitors use fewer explicit types. Simplify only duplicated semantic state or ownership.

### 3.5 Round/reset boundary

Create an explicit inventory of all nontrivial state and its lifetime.

At a successful round boundary, prove that ACTION_LOCAL and ROUND_LOCAL recovery/pending/cooldown/episode state cannot contaminate the next round unless explicitly documented as SESSION_GLOBAL.

Do not reset intentional session state such as user configuration, stable entitlement context, or other justified cross-round values.

## 4. Explicitly out of scope

S0 must not become a general rewrite.

Do not implement in this wave:

- Policy v0.1 economic decision logic;
- new strategy scoring/utility/planning;
- MCTS/planner/parallel business FSM;
- new OCR model or CV framework migration;
- bulk template replacement;
- Boss/Archive/TQTZ/Kick feature redesign unless a minimal authority consolidation directly requires a mechanical refactor with unchanged behavior;
- subscription/auth architecture changes;
- UI redesign;
- release/build/deployment changes;
- Golden Run evidence fabrication or baseline updates.

Do not copy competitor code, images, secrets, coordinates, blind sleeps, blind ESC/QUIT, or foreground-exclusive assumptions.

## 5. Required tests for S0

At minimum add/strengthen tests for the actual changed contracts.

Required categories:

1. **Window ownership:** explicit KK/platform confounders cannot gain GAME/page action authority; verified game frame retains required current behavior.
2. **UNKNOWN safety:** ambiguous scene/window role produces zero input and cannot be escaped by a second watchdog/fallback owner.
3. **Single-owner liveness:** when a failure signal is raised, only the designated owner may progress/recover; observing wrappers remain input-free unless they are the designated owner.
4. **Round reset:** representative ACTION_LOCAL/ROUND_LOCAL pending/retry/recovery state is cleared or reconstructed at the round boundary; justified SESSION_GLOBAL state persists.
5. **Postcondition integrity:** simplification does not replace business confirmation with click success, generic mutation, fixed sleep, or stale evidence.
6. **Golden Path regression:** existing lobby/stage/mainline/postgame/quit safety regressions remain green.

Tests must exercise production code rather than reproduce a second copy of the FSM in test helpers.

## 6. Acceptance gates

Implementation candidate is not complete until:

- targeted S0 tests pass;
- full repository Standard CI passes;
- Standard Release Gate passes;
- no Policy v0.1 production call-path change is introduced unintentionally;
- diff review confirms scope did not expand;
- a fresh repeated real-machine Golden Path run is executed after code integration.

Recommended real-machine target after S0:

`10 consecutive rounds`

with:

- unauthorized input = 0;
- window-role misbind = 0;
- false scene transition = 0;
- generic ESC/QUIT/HOME from UNKNOWN = 0;
- cross-round stale pending/recovery contamination = 0;
- each business transition either has fresh confirmation or remains bounded/fail-closed.

A valid safety stop/ERROR caused by genuinely unresolved ownership is not counted as a false failure; the goal is not "never stop", but "never progress from ambiguity".

Strict Zero-Defect and Frozen OCR release smoke remain separate release gates and are not substituted by S0 tests.

## 7. Parallel work isolation

A separate test/CI-efficiency branch may proceed in parallel if it does not edit production runtime files owned by S0.

Recommended branch:

`test/ci-speed-and-stability-harness-20260908`

Allowed files for that parallel lane:

- `.github/workflows/ci.yml`;
- test-only files under `tests/`;
- benchmark/audit-only tooling that performs zero real input;
- documentation for the harness.

The parallel lane must not edit:

- `src/shuabao/mediator.py`;
- `src/shuabao/runtime_mediator.py`;
- `src/shuabao/vision/capture.py`;
- `src/shuabao/interaction_surface.py`;
- Policy production/config files;
- fixtures/thresholds/gate baselines merely to pass.

If a test-only audit reveals a production defect, report it to the S0 owner rather than fixing production in the test branch.

## 8. CI efficiency opportunity already verified

Current `.github/workflows/ci.yml` runs the full Python `tests/` suite once in `Run Core Python Test Suites`, then invokes `tools/release_gate.py`.

`tools/release_gate.py` itself defines `stage_pytest()` as the authoritative offline check and runs the complete `tests/` tree again.

Therefore the Standard CI currently duplicates the full Python test suite in the same job.

A test/CI-only branch may remove this duplication after verifying that:

- the Standard Release Gate still executes the entire test suite exactly once;
- failure visibility remains adequate;
- no gate stage is skipped or weakened;
- before/after workflow conclusions are semantically equivalent.

UI typecheck/unit/build and Python Standard Release Gate may also be evaluated as parallel jobs because the release gate has no direct `ui-v2` dependency. Any workflow refactor must preserve all existing gate semantics and produce a clear final workflow failure if either side fails.

Do not add hosted-runner wall-clock performance thresholds as hard gates unless reproducibility is demonstrated; use deterministic call-count/search-surface contracts where possible and keep hardware-sensitive benchmark timing as benchmark evidence.

## 9. Status

`S0_CONTRACT = FROZEN_FOR_IMPLEMENTATION`

`COMPETITOR_RESEARCH = HOLD`

`POLICY_V01_IMPLEMENTATION = HOLD_UNTIL_S0_VALIDATED`

`MAIN_RECONCILIATION = HOLD`
