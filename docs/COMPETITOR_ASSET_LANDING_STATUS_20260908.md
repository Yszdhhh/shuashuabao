# ShuaBao Competitor Asset Landing Status — 2026-09-08

> Control-tower handoff note. Documentation only on `handoff/latest`.
> Purpose: record what the A/C same-game competitor research actually taught us, what has already landed in ShuaBao, what remains partial, and what the next conversation/Agent should do.

## 0. Verified current refs

Production integration branch still frozen:

- `trial-merge@d1fb4a51310f3f847ebeee110d51d8423050468b`

Current S0 / production candidate:

- `refactor/stability-s0-20260908@dc108892d8590c04828dc176482bee32ba348914`

Current test/CI lane:

- `test/ci-speed-and-stability-harness-20260908@c5589d4876aad6ed0625473e20f2542446a2fbe6`

Current Live Harness:

- `test/live-harness-current-20260908@4b19e1005690509dc243dd1870a035422c10e640`
- Harness production baseline: `dc108892d8590c04828dc176482bee32ba348914`
- `dc108892 -> 4b19e100` adds Harness/docs/tests/tools only; no `src/shuabao/**` production delta.

Release state:

- `trial-merge` has not absorbed S0 yet.
- `dc108892` has no GitHub-hosted CI run yet; local test/release-gate results are Agent-reported unless separately cloud-verified.
- Real-machine GT on `dc108892 + 4b19e100` is the next decisive gate.

## 1. What the competitor research actually produced

Competitor research is CLOSED/HOLD for now. The useful assets were not source code, coordinates, images or private implementation details. The reusable assets were architecture constraints:

1. **Single progression/recovery ownership.** One business/failure domain should not have peer watchdogs/FSMs independently advancing or escaping the same condition.
2. **Asset inventory is not detector authority.** A project may own hundreds of templates, while only a small page/job-specific subset has active transition/action authority at a time.
3. **Mechanical capability is not business authority.** Capture/window/input/timer helpers should not independently own business progression.
4. **Prefer fresh re-observation over semantic latches.** If a trusted fresh frame can answer the question, avoid retaining the same fact as a long-lived state latch.
5. **Keep only minimum asynchronous action memory.** Preserve request/input/postcondition correlation where needed; do not delete legitimate PendingAction-like state merely for simplicity.
6. **Explicit transient lifetime/reset ownership.** Action/round retry/cooldown/recovery state must not contaminate the next round; intentional session-global state may persist.
7. **Window ownership gates detector/input authority.** PLATFORM/GAME/UNKNOWN must remain distinct; unresolved ownership fails closed.
8. **Input dispatch success is not business success.** Fresh business-relevant postconditions remain mandatory; UNKNOWN remains zero-input.

These are frozen in `docs/STABILITY_SIMPLIFICATION_S0_IMPLEMENTATION_CONTRACT_20260908.md`.

## 2. Landing matrix — current `dc108892`

### 2.1 Single progression/recovery ownership

Status: **LANDED for the known S0 duplicate-owner domains; not proven globally for every FSM.**

Landed:

- Runtime MAIN_LINE watchdog no longer injects generic ESC; it is telemetry/stall observation only.
- Runtime duplicate panel physical fail-forward/recovery path was removed.
- Core remains the business progression/recovery owner for the affected MAIN_LINE/panel domains.
- Stall telemetry is episode-based rather than per-tick incident spam.

Not claimed:

- ShuaBao still has many legitimate business FSMs/states; S0 did not prove that every possible failure domain across the entire product has exactly one owner.

Verdict: `S0_SINGLE_OWNER_TARGET = PASS`, `GLOBAL_OWNER_GRAPH = PARTIAL / NEEDS_CONTINUED_LIVE_VALIDATION`.

### 2.2 Page/job-local detector authority

Status: **PARTIAL.**

Landed/preserved:

- Window role is classified before game/platform authority is granted.
- Existing context/ROI/hot-path mechanisms continue to constrain many detectors.
- The test/CI branch added detector authority profiling (matcher calls, searched pixels, detector-family calls, context, attempted fake input), giving a before/after measurement surface.

Not yet fully landed:

- S0 did not perform a broad rewrite of the entire Golden Path into a new explicit detector scheduler.
- Representative profiling still showed substantial detector work on some contexts (for example room-waiting/unknown in the pre-S0 baseline), so the competitor lesson “hundreds of assets but a small active authoritative subset per page/job” is not yet fully realized across the whole runtime.

Verdict: `PAGE_LOCAL_DETECTOR_AUTHORITY = PARTIAL`.

This is a real remaining architecture optimization, but it should be driven by current-SHA profiling and real GT, not by deleting assets or rebuilding CV wholesale.

### 2.3 Mechanical capability vs business authority

Status: **LANDED / strengthened.**

- Capture/window enumeration remain mechanical capabilities.
- Runtime watchdog is no longer allowed to turn a stall observation directly into generic physical recovery input.
- Business transitions remain owned by Mediator/page/business flows.

Verdict: `MECHANICAL_CAPABILITY_SEPARATION = PASS_FOR_S0_SCOPE`.

### 2.4 Re-observation vs long semantic latches

Status: **PARTIAL, with meaningful new examples.**

Landed examples:

- Pending lobby join now records the origin HWND and re-observes the new KK surface instead of inferring room state from window size or foreground status.
- A new KK HWND is not accepted as a room unless it has the actual room signature (exit + ready/start evidence).
- Unknown/transition frames remain zero-input.

Still partial:

- S0 did not broadly remove/reclassify every historical latch in Mediator.
- Existing legitimate action/session state remains and requires continued lifecycle validation rather than blanket deletion.

Verdict: `REOBSERVE_OVER_LATCH = PARTIAL / IMPROVED`.

### 2.5 Minimum asynchronous action memory

Status: **PRESERVED, not broadly redesigned.**

- S0 deliberately did not delete PendingAction-like correlation state.
- No Policy Wave 1 request-token/generation framework was forced into S0 without evidence.
- Existing business postcondition contracts were preserved.

Verdict: `ASYNC_ACTION_MEMORY = PRESERVED_WITHOUT_OVERREFACTOR`.

### 2.6 Explicit round/reset lifetime

Status: **PARTIAL / representative validation completed.**

Test lane `c5589d4` added a 50-round synthetic lifecycle audit using production classes + fake input.

It exposed five reset candidates. Main S0 tracing concluded:

- old Runtime ESC-attempt state was removed with watchdog de-inputization;
- choice session resets at panel episode boundaries;
- stage-click cooldown is short-lived and expires naturally;
- equipment/merchant leases are short-lived and return to IDLE under production timing.

S0 additionally made Runtime watchdog current-stall fields explicitly round-local and the cumulative stall episode count explicitly session-global.

What is not proven:

- no exhaustive rewrite/classification of all transient fields was merged into production;
- synthetic STAGE_SELECT->MAIN_LINE reset evidence is not a substitute for repeated real-machine round transitions.

Verdict: `ROUND_LIFETIME = PARTIAL / REPRESENTATIVE_PASS / REAL_GT_PENDING`.

### 2.7 Window ownership gates recognition/action authority

Status: **STRONGLY LANDED in S0 scope.**

Landed:

- typed `WindowRole = PLATFORM | GAME | UNKNOWN` and a centralized role classifier;
- `KK` alone cannot grant GAME authority;
- explicit platform frames cannot drive game-stage authority;
- pending lobby join uses origin/new HWND identity, not a hard-coded popup size;
- a new KK window must prove actual room controls before it can become ROOM_WAITING;
- pending-join dialog surfaces are rejected/closed without clicking Quick Join;
- the fix no longer depends on the earlier 440x260 size heuristic, so this specific popup path is not tied to one window size/full-screen layout.

Verdict: `WINDOW_OWNERSHIP_AUTHORITY = PASS_FOR_CURRENT_SCOPE`.

Important: this does NOT prove arbitrary full-screen/DPI/layout combinations are all GT-approved. That still requires real-machine coverage.

### 2.8 Fresh postconditions / UNKNOWN zero-input

Status: **PRESERVED / strengthened.**

- Generic UNKNOWN is still zero-input.
- Runtime S0 did not replace business confirmation with click success.
- lobby failure/normal exit handoffs were repaired so verified exit does not leave `RECOVER_FAILURE` or `NEXT` in a state that errors on the next tick.
- pending-join popup close is only part of the chain; real PASS still requires return to valid lobby evidence and resumed search.

Verdict: `POSTCONDITION_SAFETY = PASS_FOR_STATIC_CONTRACT / LIVE_GT_PENDING`.

## 3. Important lobby fixes now in the production candidate

Current `dc108892` includes the latest convergence of the lobby hotfixes:

1. pending join records `_hitch_join_origin_hwnd`;
2. if a different KK HWND appears after join, it is checked for actual room signature before ROOM_WAITING authority;
3. a different KK HWND without room controls is treated as a join dialog and dismissed/rejected;
4. same-window generic join dialog remains supported through the explicit dialog path;
5. the temporary fixed 440x260 heuristic is gone;
6. verified failure exit in hitch mode hands off to `LOBBY_ROOM` instead of leaving `RECOVER_FAILURE` with no recovery state;
7. normal confirmed exit in hitch mode hands off to `LOBBY_ROOM` instead of leaving `NEXT` to time out.

This is materially better than the earlier `2e40240` intermediate state, which had reintroduced two phase-handoff regressions while fixing the popup.

## 4. Test/CI Agent progress

Branch:

`test/ci-speed-and-stability-harness-20260908@c5589d4876aad6ed0625473e20f2542446a2fbe6`

Completed:

- removed duplicate full Python pytest execution from Standard CI while preserving the authoritative Standard Release Gate;
- split UI check/unit/build and Python Standard Release Gate into parallel jobs;
- verified wall-time improvement on GitHub Actions from ~17m59s to ~10m14s (~43% reduction) on the measured runs;
- added 50-round zero-real-input lifecycle audit;
- added detector/matcher/search-pixel authority profiling;
- did not modify prohibited production S0 files.

Not yet integrated:

- `c5589d4` is still on its isolated branch;
- it must be adapted/rebased against the final S0 candidate before integration, especially because old watchdog fields changed/vanished;
- final workflow should remove any one-off test-branch trigger before production integration.

## 5. Live Harness / real-machine test progress

Current branch:

`test/live-harness-current-20260908@4b19e1005690509dc243dd1870a035422c10e640`

Current production baseline:

`dc108892d8590c04828dc176482bee32ba348914`

Verified properties:

- Harness is layered on top of the production candidate; it does not carry an alternate `src/shuabao` implementation.
- identity gate pins the expected production SHA and refuses old known harness/runtime identities;
- long lanes call production Mediator flows;
- targeted probes call production handlers/adapters rather than a copied test FSM;
- Live Harness contains GUI/launcher/evidence/replay/probe/test tooling only relative to `dc108892`.

Next gate:

Run real-machine GT. The Harness is the diagnostic/test control surface; the final formal desktop package/Golden Run remains a separate later gate.

## 6. What competitor-derived work is NOT finished

The competitor-derived stability program is not “100% landed” yet.

Remaining/partial:

1. **Page/job-local detector authority:** still partial; use profiling to narrow real active detector authority where evidence shows unnecessary cross-page scanning.
2. **Full transient lifetime proof:** representative synthetic audit exists, but repeated real-machine round boundaries still need to prove no stale pending/recovery contamination.
3. **Full real-machine S0 validation:** not yet completed on `dc108892`.
4. **Formal CI on the exact S0 production candidate:** no GitHub-hosted CI run currently attached to `dc108892`.
5. **Integration:** S0 and test/CI commits are not yet merged into `trial-merge`.

Research itself should remain HOLD. These gaps should be closed by ShuaBao implementation/testing, not by more broad competitor reverse-engineering.

## 7. Product issues intentionally NOT solved by S0

S0 was not the gameplay-policy/intelligence wave. The user's major remaining product concerns therefore stay open until real GT and later waves:

- bond logic not intelligent enough;
- explicit early-game priority: bond/core skill formation first;
- devour pill should accelerate bond formation without being embedded into the bond-panel FSM;
- evolve/treasure/inventory/black-merchant actions need smoother real closure;
- stage/action priority between core formation vs secondary improvements needs a product-level contract;
- archive challenge can still miss a slot in real play until reproduced/closed;
- heirloom / configured Boss compliance requires repeated GT;
- secret realm still lacks a proven complete real-machine successful chain.

These should become later waves after S0 real validation:

- `S1 = In-game Priority / Bond Intelligence`
- `S2 = Action Closure (evolve / treasure / inventory / merchant)`
- `S3 = Post-game Closure (archive / heirloom / Boss / secret realm)`

Policy v0.1 implementation remains HOLD until S0 is validated.

## 8. Next-session execution order

1. Freeze `dc108892 + 4b19e100` for the next live GT episode; do not patch while a probe is running.
2. Real-machine lobby probes first: valid join, full-room dialog, other rejected join, real room child HWND, full-screen variant, kick/dissolve recovery, failure-exit return, normal exit return.
3. Then targeted single-player probes for bond/skill, evolve, devour, treasure, merchant, archive, heirloom/Boss, secret realm.
4. For every FAIL: save bundle/trace/screenshots before any code change.
5. Only after current-SHA GT, make minimal production fixes one defect at a time and re-pin the Harness identity.
6. Adapt the `c5589d4` test/CI improvements to the final S0 candidate and rerun Standard CI/Release Gate.
7. Run repeated real-machine Golden Path / recommended 10-round validation.
8. Only then resume Policy/S1 work and later main/trial reconciliation.

## 9. Current control-tower verdict

- `COMPETITOR_RESEARCH = HOLD / SUFFICIENT`
- `COMPETITOR_CORE_ASSETS_EXTRACTED = YES`
- `S0_SINGLE_OWNER_LANDING = PASS_FOR_TARGETED_DOMAINS`
- `WINDOW_AUTHORITY_LANDING = PASS_FOR_CURRENT_SCOPE`
- `PAGE_LOCAL_DETECTOR_AUTHORITY = PARTIAL`
- `ROUND_LIFETIME_PROOF = PARTIAL / REAL_GT_PENDING`
- `POSTCONDITION_SAFETY = PRESERVED`
- `S0_PRODUCTION_CANDIDATE = dc108892`
- `LIVE_HARNESS_READY = 4b19e100`
- `TEST_CI_LANE = c5589d4 / NOT_INTEGRATED`
- `TRIAL_MERGE = d1fb4a5 / UNCHANGED`
- `REAL_MACHINE_S0_GT = NEXT`
- `POLICY_V01 = HOLD`
- `MAIN_RECONCILIATION = HOLD`
