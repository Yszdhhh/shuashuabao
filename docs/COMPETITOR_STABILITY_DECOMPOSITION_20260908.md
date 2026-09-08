# ShuaBao Same-Game Competitor Stability Decomposition — 2026-09-08

> Control-tower research note. Documentation only. Do not merge `handoff/latest` into production merely to carry research notes.

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
- Competitor C Stability Cross-Validation Checkpoint 3: PASS.
- Further broad A/C reverse-engineering: HOLD; expected marginal value is now low.
- Competitor B: HOLD / low evidence; do not continue unless a later implementation question creates a specific evidence gap.
- `EVIDENCE_SUFFICIENT_TO_FREEZE_SHUABAO_S0 = YES`.

Detailed C synthesis:

`docs/COMPETITOR_C_CROSS_VALIDATION_20260908.md`

Frozen implementation contract:

`docs/STABILITY_SIMPLIFICATION_S0_IMPLEMENTATION_CONTRACT_20260908.md`

## 3. Competitor A — strongest current facts

The current production binary statically preserves an `AutoJob` abstraction with one abstract `Run` and 20 concrete `Run` implementations. The comparable 1.4.1 build had 18 concrete implementations. The obfuscated current build does not permit a safe name-for-name mapping from old PDB source filenames to current concrete types, so the identities of the two additional jobs are UNKNOWN.

The visible current helper/capability surface includes `GameWindow` as an instance `InitOnly` field, `PressKey`, `QuitGame`, `CaptureWin`, `LoopAction.Continue / Break`, `Settings.get_Default`, image-search/OpenCV dependencies and input references.

Precision boundary: `GameWindow` being an instance `InitOnly` reference proves only that the reference field is per-object and cannot be reassigned after construction. It does NOT prove unique ownership of the underlying window object, immutability of the referent, or immutability of the HWND.

A supports:

`NARROWER_EXPLICIT_SHARED_ORCHESTRATION_SURFACE`

not:

`COMPETITOR_A_PROVEN_SIMPLER_OVERALL`.

## 4. Competitor A — claims deliberately downgraded

Because the current A production method bodies are obfuscated/encrypted, these older-build observations are NOT current-build facts:

- old named LaunchGame/BeginGame/CreateRoom/SelectStage order;
- `FindNodeWithTimeOut` as current postcondition implementation;
- old infinite scrolling / exact historical thresholds;
- UNKNOWN always continuing instead of erroring;
- absence of global ESC/watchdog/fail-streak;
- old UIA/InputSimulator runtime behavior;
- Tesseract being on the active OCR path.

Missing readable metadata is not proof of runtime absence.

## 5. Competitor C — independent cross-validation

C provides stronger readable static evidence for the seven questions relevant to long-run stability.

Observed execution shape:

- one normal master round sequence owns main business progression;
- one thin outer shell owns game-window-loss cleanup/retry;
- an alternate archive mode is mutually exclusive at startup rather than a parallel progression FSM;
- a window watchdog signals loss but does not itself click or change business phase.

Observed window model:

- platform/KK and game windows use separate discovery/lifecycle logic;
- KK ownership is validated before launch;
- game HWNDs are re-enumerated each round;
- failure to activate/validate the intended target prevents blind input;
- unresolved stale game windows stop progression into the next round.

Observed detector model:

- C owns hundreds of assets, but current page/job functions enable only a small relevant detector subset;
- room/menu/load phases use very small named sets;
- battle uses bounded color gates plus limited high-priority template sets;
- skill/card scans are filtered by user choice/current strategy/completion state rather than scanning the whole inventory every tick.

Observed postcondition model:

- several important actions re-observe after input;
- panel UNKNOWN does not authorize repeat-click;
- victory retry is bounded;
- exit requires game-window disappearance before the round advances.

C also contains unsafe patterns that MUST NOT be copied: fixed-coordinate business actions, pure sleep in some stage paths, foreground-exclusive assumptions, blind long waits, and some weak disappearance-only completion semantics.

## 6. A vs C cross-validation

### H1 — narrow/single progression ownership

`CONFIRMED`

A and C use different structures, but both expose a narrow shared progression surface rather than many peer FSMs independently advancing the same flow.

### H2 — asset inventory is not detector authority

`CONFIRMED`

Both competitors can own large asset inventories while restricting the active detector set to the current business job/page.

### H3 — mechanical capabilities separated from business orchestration

`CONFIRMED`

Capture/input/window/image-search helpers are mechanical capabilities; business progression remains owned by the job/function layer.

### H4 — re-observation over long semantic latch

`PARTIAL`

C strongly re-observes page state and has explicit local/round state, but still retains legitimate session-global values.

### H5 — explicit round reset limits transient contamination

`PARTIAL`

C resets retry/cooldown/task/window-monitor state at round boundaries while intentionally preserving room bindings and session counters.

Overall:

- `A_C_OWNER_LOCALITY_CROSS_VALIDATION = YES`
- `A_C_PAGE_LOCAL_DETECTOR_AUTHORITY = YES`
- `A_C_REDUCED_SHARED_TRANSIENT_STATE = PARTIAL`
- `EVIDENCE_SUFFICIENT_TO_FREEZE_SHUABAO_S0 = YES`

## 7. ShuaBao current-SHA comparison

Current ShuaBao production explicitly exposes a broad control surface including:

- 21 top-level `Phase` values;
- `ChallengeState`;
- `RecoveryKind / RecoveryStep / RecoveryState`;
- `PanelState`;
- `ActionLifecycle`;
- `InteractionSurface` arbitration;
- general `PendingAction` lifecycle memory;
- lobby-specific hitch/follow state machinery;
- bounded attempt/deadline structures;
- Mediator-owned session/transient latches.

These abstractions are not individually condemned. The risk is combinatorial authority: multiple locally reasonable state machines, latches, deadlines, watchdogs and recovery paths can compose into a much larger implicit control graph.

A current-SHA simplification target remains duplicate liveness/recovery ownership, including overlapping Core-vs-Runtime liveness mechanisms.

## 8. Cross-validated S0 principles

The research now supports freezing seven internal design constraints:

1. one clear business progression owner per active failure domain;
2. asset inventory is not detector authority — restrict authority to current verified window/page/job;
3. mechanical capabilities do not independently own business progression;
4. freshly re-observable scene facts should not be kept as long-lived semantic latches;
5. transient retry/pending/recovery state needs explicit round reset ownership;
6. window ownership/activation gates detector and input authority;
7. mechanical input success is not business success — require fresh business-relevant postconditions and keep UNKNOWN fail-closed.

These principles are now frozen in:

`docs/STABILITY_SIMPLIFICATION_S0_IMPLEMENTATION_CONTRACT_20260908.md`

## 9. Safety rules that competitor simplicity must not override

- `UNKNOWN / ambiguous -> ZERO INPUT`.
- UNKNOWN may authorize bounded re-observation/reacquisition, not blind ESC/QUIT/HOME.
- Click/key dispatch success is not a business postcondition.
- Frame mutation/fingerprint change alone is not business completion.
- Fresh business-relevant evidence is required for business transitions.
- No fixture/threshold/baseline weakening merely to obtain PASS.
- Do not copy proprietary competitor code, image assets, credentials or license material into ShuaBao.

## 10. Research stop / next phase

Broad competitor research is now stopped.

Next phase is internal ShuaBao execution:

1. implement the frozen Stability Simplification S0 contract on an isolated production branch;
2. in parallel, run a non-overlapping test/CI-efficiency branch;
3. targeted tests + Standard CI;
4. repeated real-machine Golden Path validation;
5. re-audit Policy call path, then resume Policy v0.1;
6. explicit Strict Zero-Defect / Frozen OCR / remaining product GT;
7. only then finalize main/trial ancestry reconciliation.
