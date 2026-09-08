# ShuaBao Same-Game Competitor Stability Decomposition — 2026-09-08

> Control-tower research note. Documentation only. Do not merge this branch into production merely to carry research notes.

## 1. Scope and baselines

Current ShuaBao production-code baseline:

`decb9b6eb3559e39ea51e26864eaada0d648855b`

Current `trial-merge`:

`d1fb4a51310f3f847ebeee110d51d8423050468b`

`d1fb4a5` differs from `decb9b6` only by the two frozen Policy v0.1 documentation files. Production runtime/code is therefore compared at `decb9b6`.

Competitor work to date was read-only. No ShuaBao production code was modified as part of this research.

## 2. Research status

- Initial same-game competitor overview: complete.
- Competitor A Deep Stability Decomposition Checkpoint 1: PASS with precision corrections.
- Competitor A structural Checkpoint 2: PASS with precision corrections.
- Further Competitor A reverse-engineering: HOLD; expected marginal value is now low.
- Next recommended checkpoint: Competitor C structural/long-run decomposition for independent cross-validation.
- Competitor B remains low-evidence because its internal implementation is not sufficiently observable under the current read-only/static boundaries.

## 3. Competitor A — strongest current facts

The current production binary statically preserves an `AutoJob` abstraction with one abstract `Run` and 20 concrete `Run` implementations. The comparable 1.4.1 build had 18 concrete implementations. The obfuscated current build does not permit a safe name-for-name mapping from old PDB source filenames to current concrete types, so the identities of the two additional jobs are UNKNOWN.

The following helper/capability surface is statically visible in the current build:

- `GameWindow` as an instance `InitOnly` field on `AutoJob`;
- `PressKey` on `AutoJob`;
- `QuitGame` on `AutoJob`;
- `CaptureWin` on `AutoJob`;
- `LoopAction.Continue / Break`;
- `Settings.get_Default` as a static settings singleton entry;
- image-search/OpenCV dependency surface;
- mouse click/scroll/double-click/right-click references;
- `Thread.Sleep` reference;
- `MonitorGameOver` symbol remains present, but call sites are UNKNOWN.

Precision boundary: `GameWindow` being an instance `InitOnly` reference proves only that the reference field is per-object and cannot be reassigned after construction. It does NOT prove that each job owns a unique underlying window object, that the referent is immutable, or that the underlying HWND cannot change internally.

## 4. Competitor A — explicit orchestration shape

The strongest reusable structural signal is not that Competitor A is proven globally simpler. Current method bodies are obfuscated and cannot support that claim.

What is supported is narrower:

- explicit shared orchestration is exposed as one abstract `Run`, a set of concrete `Run` owners, and a two-value `LoopAction` return surface;
- common mechanical capabilities are provided by a relatively thin `AutoJob` base surface;
- individual concrete jobs can own private state fields without expanding the global visible orchestration type surface;
- static metadata exposes fewer named shared control-state concepts than ShuaBao's current production architecture.

This should be described as:

`NARROWER_EXPLICIT_SHARED_ORCHESTRATION_SURFACE`

not as:

`COMPETITOR_A_PROVEN_SIMPLER_OVERALL`.

## 5. Checkpoint-1 claims deliberately downgraded

The current 8 MB production build has obfuscated/encrypted method bodies for the relevant paths. Therefore these older-build observations are NOT current-build facts:

- the old named sequence such as LaunchGame / BeginGame / CreateRoom / EntryF1 / SelectStage;
- `FindNodeWithTimeOut` as the current postcondition mechanism;
- old infinite stage scrolling behavior and old numeric matching thresholds;
- old UNKNOWN->Continue runtime behavior;
- absence of a global ESC path;
- absence of watchdog/fail-streak behavior;
- old UIA/InputSimulator runtime usage;
- Tesseract being on the actual active OCR execution path.

They may remain historical evidence or strong inference where appropriate, but the current production method body is UNKNOWN.

Absence of a readable MemberRef/TypeDef name is never sufficient to prove runtime absence.

## 6. ShuaBao current-SHA comparison

Current ShuaBao production still exposes a broad explicit control surface, including:

- 21 top-level `Phase` values;
- `ChallengeState`;
- `RecoveryKind` / `RecoveryStep` / `RecoveryState`;
- `PanelState`;
- `ActionLifecycle`;
- `InteractionSurface` arbitration;
- general `PendingAction` lifecycle memory;
- lobby-specific `HitchSearchSM` / follow-state machinery;
- bounded attempt/deadline structures;
- Mediator-owned session/transient latches.

This does not mean these abstractions are individually wrong. Most were introduced for valid safety reasons.

The current concern is combinatorial authority: multiple locally reasonable state machines, latches, deadlines, watchdogs, and recovery paths can compose into a large implicit control graph.

A current-SHA example remains important: Core Mediator and RuntimeMediator have had separate liveness/recovery ownership, including overlapping 15-second mechanisms. Duplicate liveness ownership is therefore still a concrete S0 simplification candidate and should be reviewed explicitly rather than adding another fallback layer.

## 7. What the research does and does not support

Supported:

1. Same-game mature competitors also use many image assets; raw template count is not the key stability variable.
2. The meaningful metric is the detector/authority set active for the current job/page, not total asset inventory.
3. Competitor A exposes a narrower shared orchestration surface and stronger job-local ownership shape than ShuaBao's current explicit control model.
4. Long-run stability work should focus on authority locality, bounded local recovery, explicit state lifetime, and round/session reset boundaries.
5. ShuaBao should examine whether observable scene state is being unnecessarily cached across ticks/rounds.
6. Minimum action-lifecycle memory remains necessary where request->input->fresh postcondition correlation is required.

Not supported:

1. Competitor A is not proven globally simpler or safer.
2. Competitor A is not proven to have no watchdog, no global ESC, no retry cap, or no recovery state.
3. Soft `Continue`, blind sleep, blind ESC/QUIT, or unbounded retries must not be copied as safety patterns.
4. A missing readable symbol in obfuscated metadata is not proof that a runtime behavior is absent.
5. Historical thresholds/ROI/input behavior from old builds are not current-production ground truth.

## 8. Reusable S0 design signals

The current research justifies these candidate principles for a future Stability Simplification S0 contract:

### 8.1 Localize orchestration authority

Business progression should have one clear owner for the active page/job/episode. Common capture/input helpers may remain shared mechanical capabilities, but they should not create independent business progression authority.

### 8.2 Restrict detector authority by window/page ownership

Large asset libraries are acceptable. The active detector set and transition authority should be constrained by verified window role and current business page/job.

### 8.3 Distinguish observable scene state from action lifecycle state

If a fact can be freshly re-observed from the current trusted frame, prefer re-observation over long-lived semantic latches.

Retain only the minimum state needed for a real asynchronous action contract, such as:

- request/action identity;
- precondition evidence generation/fingerprint;
- input attempt;
- bounded deadline/attempts;
- expected business postcondition;
- fresh outcome evidence.

### 8.4 One liveness/recovery owner per failure domain

Do not allow Core FSM, Runtime wrapper, watchdog, modal recovery, and fallback layers to independently progress or escape the same business failure.

Perception recovery, input recovery, and business fallback must remain distinct.

### 8.5 Make state lifetime explicit

Classify nontrivial control state as:

`FRAME_LOCAL / PAGE_LOCAL / ACTION_LOCAL / ROUND_LOCAL / SESSION_GLOBAL / PERSISTENT`

Round-local/transient state should have an explicit reset owner and boundary. Long-running stability should be validated across repeated rounds, not inferred from one successful path.

## 9. Safety rules that competitor simplicity must not override

- `UNKNOWN / ambiguous -> ZERO INPUT`.
- UNKNOWN may authorize bounded re-observation/reacquisition, not blind ESC/QUIT/HOME.
- Click or key dispatch success is not a business postcondition.
- Frame mutation/fingerprint change alone is not business completion.
- Fresh business-relevant evidence is required for business state transitions.
- No fixture/threshold/baseline weakening to make tests pass.
- Do not copy proprietary competitor code or image assets into ShuaBao; extract architecture and stability principles only.

## 10. Next research checkpoint

Do not spend another large round reverse-engineering Competitor A unless a specific unresolved question becomes implementation-blocking.

Next, perform a narrow read-only Competitor C decomposition to test whether the same independent structural patterns recur:

- page/job ownership locality;
- active detector scheduling vs total assets;
- window binding lifecycle;
- action/postcondition locality;
- recovery ownership;
- UNKNOWN behavior;
- round/session reset boundaries;
- cross-round transient state.

The purpose is cross-validation, not a second exhaustive reverse-engineering project.

If A and C independently show the same high-value structure, the control tower may freeze a minimal ShuaBao Stability Simplification S0 implementation contract. Until then, production refactoring remains HOLD.
