# ShuaBao Competitor C Stability Cross-Validation — 2026-09-08

> Control-tower research note. Documentation only. Competitor analysis is read-only and must not be treated as permission to copy proprietary code/assets or to weaken ShuaBao safety rules.

## Baseline

ShuaBao production-code baseline:

`decb9b6eb3559e39ea51e26864eaada0d648855b`

Current `trial-merge`:

`d1fb4a51310f3f847ebeee110d51d8423050468b`

`d1fb4a5` differs from `decb9b6` only by the two frozen Policy v0.1 documents, so runtime comparison remains anchored at `decb9b6`.

## Verdict

`GROK_COMPETITOR_C_CHECKPOINT_3 = PASS`

`A_C_OWNER_LOCALITY_CROSS_VALIDATION = YES`

`A_C_PAGE_LOCAL_DETECTOR_AUTHORITY = YES`

`A_C_REDUCED_SHARED_TRANSIENT_STATE = PARTIAL`

`EVIDENCE_SUFFICIENT_TO_FREEZE_SHUABAO_S0 = YES`

Further broad competitor reverse-engineering is now HOLD. Do not continue into Competitor B unless a later implementation question creates a specific evidence gap.

## Competitor C execution shape

Readable static bytecode supports a sequential orchestration model:

`startup -> room/window validation -> room start -> per-round reset -> game-window discovery -> menu/load -> battle handlers -> postgame -> exit -> verify window gone -> next round`

The normal progression owner is the master round implementation. A thin outer shell handles game-window loss and retries/cleanup. A separate archive-boost mode is mutually exclusive at startup rather than a concurrent progression FSM. The window watchdog signals window loss; it does not itself click or advance business phases.

This is not proof that C is globally simpler or safer. It is evidence that its explicit shared progression surface is narrow.

## Window ownership

C statically shows distinct platform and game-window lifecycles:

- KK/platform window is explicitly identified and user-bound;
- its handle is validated before each launch;
- invalid KK ownership stops automation instead of authorizing blind input;
- game windows are enumerated fresh per round using a separate title/size contract;
- game HWND state is round-local and is not intentionally reused into the next round;
- input-bearing paths activate the intended HWND first and stop if activation fails;
- a dedicated round-window watchdog only signals loss to the outer owner.

This independently supports the ShuaBao S0 principle that window ownership must be established before page detectors or actions gain authority.

## Detector scheduling and asset inventory

C carries a large image inventory, but static call structure shows that the active detector set is much smaller and page/job-local.

Observed inventory:

- hundreds of BMP assets plus OCR dictionaries;
- required and optional subsets are separated;
- large skill/card/hero libraries are inventory, not a global every-tick scan list.

Observed scheduling pattern:

- room start: approximately 1–2 named detectors;
- menu/load: approximately one named detector each;
- battle idle: a bounded set of color gates plus a few high-priority templates;
- skill panel: only a small user-selected subset rather than the whole skill library;
- bond/card panel: only current-strategy unfinished candidates;
- victory/failure: one strict detector per terminal state.

Therefore the important comparison metric is:

`ACTIVE_DETECTOR_AUTHORITY_FOR_CURRENT_PAGE`

not:

`TOTAL_ASSET_COUNT`.

This independently cross-validates the same signal found in Competitor A.

## Action and postcondition locality

C does not rely uniformly on click-return success. Several important paths re-observe after input:

- room start rechecks the start target and bounds retry;
- battle panel actions re-observe panel/color state and do not retry-click on UNKNOWN;
- victory uses strict re-observation with a bounded additional attempt;
- exit requires the target game window to disappear before the round may advance.

Some C paths are intentionally NOT models for ShuaBao:

- stage/chapter selection relies heavily on fixed coordinates and sleep before later page evidence;
- target disappearance alone is sometimes accepted as completion;
- some recovery uses blind wait durations;
- C assumes foreground-exclusive desktop control.

ShuaBao keeps stricter requirements: fresh business-relevant postcondition, UNKNOWN->ZERO INPUT, and no blind ESC/QUIT/HOME authorization from ambiguity.

## Failure ownership

C has multiple recovery mechanisms, but they are segmented by failure domain rather than all being independent progression FSMs:

- page/modal cleanup owns local panel ambiguity;
- the round-window shell owns game-window loss;
- KK ownership failure is a stop/rebind condition;
- action functions own their bounded click/no-effect retry;
- unresolved exit/window residue stops the script rather than carrying the stale round into the next launch.

A global watchdog exists for window lifetime, but it is not a general business-idle ESC watchdog.

This supports the S0 direction:

`ONE_LIVENESS_OR_RECOVERY_OWNER_PER_FAILURE_DOMAIN`

while preserving strict fail-closed behavior.

## State lifetime and reset

C exposes an explicit distinction between short-lived and long-lived state:

- frame/page observations are re-observed;
- click/retry confirmation is action-local;
- task completion, card/skill/treasure bookkeeping and watchdog HWND lists are round-local;
- room HWNDs, run counts, license/resources and similar mechanical state are session/global;
- user configuration is persistent.

At round start C explicitly rebuilds/resets round-local task ledgers and retry/cooldown guards. Game HWNDs are re-enumerated rather than reused. This does not mean C has no cross-round state, but it supports a disciplined reset boundary for transient recovery/decision state.

## A vs C cross-validation

### H1 — single/narrow progression owner

`CONFIRMED`

A and C use different structures, but both expose a narrow shared progression surface rather than many peer FSMs independently jumping the main flow.

### H2 — inventory is not detector authority

`CONFIRMED`

Both competitors can own many assets while restricting the active detector set to the current job/page.

### H3 — mechanical capabilities separated from business orchestration

`CONFIRMED`

Capture/input/window/image-search capabilities are mechanical helpers; business sequence remains owned by a job/function layer.

### H4 — re-observation preferred over long semantic latch

`PARTIAL`

C strongly re-observes many scene facts and does not expose a long-lived current-page semantic bus, but it still has legitimate round/session state.

### H5 — explicit round reset limits transient contamination

`PARTIAL`

C resets retry/cooldown/task/window-monitoring state at round boundaries while preserving intentional session state.

## Cross-validated S0 principles

The following seven principles are now sufficiently supported by independent A/C evidence to freeze as ShuaBao S0 design constraints:

1. **Single clear progression owner for the active business failure domain.** Nested handlers return outcomes; avoid peer FSMs independently advancing the same flow.
2. **Asset inventory is not scan authority.** Restrict detector authority to the verified current window/page/job and bounded relevant detector set.
3. **Mechanical capabilities are separate from business orchestration.** Capture/click/key/window helpers must not independently create business progression authority.
4. **Re-observe observable scene facts.** Do not preserve re-derivable page state as long-lived semantic latches.
5. **Reset transient state at explicit round boundaries.** Retry cooldowns, pending/recovery episode state, task ledgers and round HWND monitoring require a reset owner.
6. **Window ownership gates input and detector authority.** Platform and game windows have separate roles/lifecycles; activation/ownership failure cannot grant blind input.
7. **Mechanical success is not business success.** Require a fresh business-relevant postcondition; UNKNOWN never grants retry-click or blind navigation authority.

## Do not copy from Competitor C

Do not adopt:

- blind fixed-coordinate room/start/stage/exit behavior;
- pure sleep as a business postcondition;
- target disappearance as sufficient success without context;
- foreground-exclusive desktop assumptions;
- blind long waits after window loss;
- timeout-driven jumps into unrelated business modes;
- credentials, license protocol material, secrets, proprietary code or image assets.

## Research stop

Competitor A and C are now sufficient to freeze the S0 implementation contract. Further broad competitor research has diminishing expected value.

Next step is internal ShuaBao work:

1. freeze a narrow S0 implementation contract;
2. implement on an isolated branch;
3. independently improve test/CI infrastructure in a non-overlapping branch;
4. run targeted tests + Standard CI;
5. perform repeated real Golden Path validation before release convergence.
