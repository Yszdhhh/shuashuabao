# ShuaBao Live GT + External Alpha Status — 2026-09-09

> Scope: synchronize the current real-machine test findings, production/harness identity, lobby-hitch product intent, and the latest long-run candidate review. This is a docs-only handoff branch. It does not change production or Harness code.

## 1. Current refs

- Production integration branch: `refactor/stability-s0-20260908`
- Current production HEAD: `5fbd513876d8236770f4bdd77dca3256836d4c1d`
  - `fix(lobby): preserve room identity and dismiss host kick modal`
- Live Harness branch: `test/live-harness-current-20260908`
- Current Harness HEAD: `ff54891d1cf3087471ab1ec1a7b66e7fc27bd8da`
- Harness identity is pinned to production `5fbd513876d8236770f4bdd77dca3256836d4c1d`.
- New long-run candidate branch: `ops/external-alpha-g0-long-run-20260909`
- Long-run candidate HEAD: `e44fd08ea516bff69d46e6b94654d9aa3d165133`
- `e44fd08` is exactly 4 commits ahead of `5fbd513`, behind by 0.

Do not merge/repin only from these notes; verify refs again before action.

## 2. Current real-machine Lobby Hitch findings

### 2.1 Real room was misclassified as join popup

Observed real room frame: about `1224x904`.

The room was visually complete and the player row already showed ready state, but the script sent repeated Esc instead of executing the normal room-wait/ready chain.

Root cause found in production logic:

- `room_exit_btn` on the real frame matched about `0.872`;
- the old room identity threshold was `0.90`;
- once the room signature failed, the new window could fall into popup handling.

`5fbd513` changed room identity so `room_exit_btn` uses `0.85`, still requiring a second room-specific control. It also prevents a large unanchored window from being treated as a compact join popup.

This fixes the observed case, but the larger architectural concern remains: ROOM identity is still mainly implemented as fixed template Boolean gates rather than a robust page-level multi-evidence classifier.

### 2.2 Host-kick main-window overlay was not handled

Observed modal text: `您已被房主移出了房间`, with `立即购买` / `取消`.

Real evidence from the failed frame:

- OCR effectively failed (only a fragment such as `2` was returned);
- `lobby_popup_dialog` matched only about `0.720`;
- the modal was an overlay in the main KK window rather than always a separate compact child HWND.

`5fbd513` added a lower-threshold known-popup route for `ROOM_WAITING`, allowing bounded Esc without clicking purchase/create-room actions.

Important test-trust caveat: the new regression for this exact path used a synthetic `np.full(...)` frame and mocked/fabricated `MatchResult`. That proves routing after recognition is injected, not that the real screenshot is recognized by the production detector.

### 2.3 A second platform modal still stalled after the first case was fixed

This exposed the architectural problem: current lobby popup handling is fragmented across conditions such as:

- `pending_join`
- `ROOM_WAITING` / `LOBBY_ROOM`
- child HWND vs main-window overlay
- compact dimensions
- popup template hit
- OCR hit
- Esc budget / cooldown

There remains a generic-modal path where an already-visible KK blocking modal can become `UNKNOWN_GENERIC_MODAL -> zero input` instead of being neutral-dismissed.

Conclusion: this is not another independent text-specific popup bug. It is a production `L0 modal ownership / routing` problem.

## 3. Canonical Lobby Hitch product intent

The lobby should stay conceptually simple.

Fresh evidence should classify the KK platform into four coarse surfaces:

1. `ROOM`
2. `ROOM_LIST / LOBBY`
3. `PLATFORM_MODAL`
4. `UNKNOWN`

Classification should use process/window identity + current HWND + fresh screenshot + page-level structure + multiple independent anchors.

### ROOM

A real room should be recognized from multiple room-specific structures, for example:

- exit control
- ready / cancel-ready / start control
- room/player layout
- stable HWND continuity

A single template dropping from e.g. 0.90 to 0.87 must not erase an otherwise obvious room page.

### ROOM_LIST / LOBBY

Use the room-list/search/refresh/tab/rows structure. Fullscreen, common window sizes and DPI scaling must not require separate business logic.

### PLATFORM_MODAL

For `lobby_hitch`, once fresh evidence proves the current KK platform surface is a blocking platform modal and it is **not** an active transaction confirmation created by our own action, the default business action is `NEUTRAL DISMISS`.

Typical texts are not separate business cases:

- full room
- password problem
- level mismatch
- host left
- kicked by host
- room dissolved
- membership / purchase prompt
- other unknown-text platform notices

All mean: current join flow is blocked -> dismiss -> reclassify -> continue searching.

Default neutral action should be Esc, with X / Cancel / Leave only as bounded neutral fallbacks if necessary. Never click positive modal actions such as Create Room / Buy Now / Quick Join.

OCR body text may be telemetry/classification help, but must not be the core authority for whether an already-proven KK blocking modal can be dismissed.

### ACTIVE_TRANSACTION_MODAL

This has higher priority than the generic modal owner. Example: our own explicit leave-room request followed by a confirm-leave dialog. It must use its dedicated confirm handler and must not be cancelled by generic Esc.

Priority:

`ACTIVE_TRANSACTION_MODAL > GENERIC_PLATFORM_MODAL > UNKNOWN`

`pending_join` / Phase may help decide what to do after the modal disappears, but should not be the main gate deciding whether a proven blocking modal may be dismissed.

### UNKNOWN

Only truly unknown surfaces should stay zero-business-input and enter bounded reobserve/reacquire/reclassify. “Unknown body text but known platform modal shell” is not UNKNOWN.

Input dispatch success is not business success. A dismiss request requires a fresh frame proving the modal disappeared before claiming recovery.

## 4. Required next Lobby action

Do not continue adding text-specific popup cases.

The next production correction should converge fragmented lobby modal handling into one `HITCH_PLATFORM_MODAL_OWNER` / equivalent single owner while preserving dedicated active-transaction handlers.

Real GT screenshots from the recent failures should be used as recognition regressions. Do not mock `find()` / fabricate `MatchResult` for the recognition-level proof.

After the Codex modal-owner correction is frozen, run a read-only Opus `Lobby Hitch Product Intent Drift Audit` against **production code**, not just Harness code.

The Opus audit should specifically check:

- page-level ROOM and ROOM_LIST robustness;
- local detector authority vs whole-page identity;
- gates introduced by recent safety fixes;
- generic modal owner unification;
- child/main/fullscreen/DPI handling;
- bounded liveness after failed dismiss;
- which tests are real-GT recognition vs mocked routing only.

## 5. Long-run candidate `e44fd08` — independent cloud verification

The branch exists and the reported SHA is correct.

`5fbd513 -> e44fd08` is 4 commits ahead, 0 behind. The branch changes include roughly:

- `src/shuabao/mediator.py`: +922 / -206
- new `src/shuabao/run_exit.py`
- small runner attribution changes
- multiple hitch continuity/regression tests

The four-commit chain includes:

1. `99545e5` — `fix(hitch): keep long-run continuity without false optional success`
2. `7cae280` — `test(hitch): lock long-run continuity without weakening postconditions`
3. `c84f1d6` — `fix(hitch): bound recovery yield so optional pages cannot hide outcome`
4. `e44fd08` — `fix(hitch): do not stop soak on archaeology, create-room, or missing recovery`

The latest commit does statically remove the three reported hitch stop sinks (archaeology, create-room alignment timeout, missing recovery state) while keeping non-hitch fail-closed behavior.

However, the branch is **not yet acceptable as the final External-Alpha G0 production candidate** for the current product contract.

### P0 product-contract mismatch: Pressure Transfer

The latest product requirement is:

> In `lobby_hitch`, pressure transfer is the core in-game business action, not an optional bonus.

Current `e44fd08` explicitly implements bounded pressure **SKIP**:

- attempt limit: 3
- budget: 45s
- sets `_hitch_pressure_skipped = True`
- `_hitch_pressure_released()` returns true when either transferred **or skipped**
- the continuity test is named `test_optional_pressure_cannot_block_victory_observation`
- another test explicitly expects unconfirmed pressure to become skipped and the run to continue

This is inconsistent with the user-defined product contract.

Correct target semantics:

- pressure transfer must be attempted/recovered as a `CORE_ACTION_WITH_RECOVERY`;
- no click-success-only PASS;
- only fresh business postcondition can set `PRESSURE_CONFIRMED`;
- if the current round cannot achieve pressure after bounded recovery, record `PRESSURE_CORE_FAILURE`, keep outcome watching alive, and do not count the round as a hitch business PASS;
- do not let the pressure failure deadlock the controller;
- do not treat pressure as an ordinary optional feature.

The exact policy for other in-game optional actions after `PRESSURE_CORE_FAILURE` should follow the latest product decision; the key point is that `skipped` must not be semantically equivalent to `transferred`.

### G0 scope gap: normal-farm core loop / archaeology handoff

The latest G0 goal also requires proof of:

- normal victory -> verified exit -> create next room;
- normal failure -> verified exit -> create next room;
- configured normal rounds complete or tickets exhausted -> enter the next game -> open archaeology mode -> fresh-confirm archaeology opened -> then stop with explicit completion reason.

The current agent report is almost entirely a hitch-soak liveness report and does not provide these normal-farm / archaeology-handoff proofs.

`e44fd08` specifically changes hitch archaeology to skip rather than stop; this does not by itself prove the required normal-farm archaeology handoff contract.

### Liveness claim remains stronger than current proof

The branch improves bounded recovery substantially, but `REMAINING_UNBOUNDED_HANG_PATHS = []` should not be accepted solely from the agent report.

The surface-recovery code can enter a yielded zero-input state and continue reclassification until fresh GAME or proven PLATFORM+GAME-absent evidence appears. That may be correct safety behavior, but a persistent UNKNOWN/environment state still needs real soak evidence and termination/diagnostic telemetry before claiming there is no practical unbounded stall.

Therefore:

- `SAFE_TO_DIAGNOSTIC_SOAK = YES` after contract correction / selected targeted tests;
- `SAFE_TO_FORMAL_SOAK_GT = HOLD` until the pressure contract and Lobby modal-owner drift are corrected and the Harness is repinned once to the resulting final production SHA.

## 6. Test / Harness state and promotion rule

Current Harness is still `ff54891` pinned to `5fbd513`.

Do **not** repin it to `e44fd08` yet.

Reason:

1. Codex unified Lobby Modal Owner correction is still pending/finalizing;
2. `e44fd08` has the pressure-transfer semantic mismatch described above;
3. the normal-farm G0 lifecycle and archaeology handoff still need explicit closure.

After the production owner freezes one final production SHA:

1. Opus read-only static audit;
2. if no blocking P0/P1, repin Harness once;
3. verify `src/shuabao` (+ relevant production config) diff is CLEAN;
4. run real GT scenarios;
5. production defects return as evidence + regression + minimal production fix; Harness-only bugs stay in Harness;
6. repeat until soak candidate is stable.

## 7. Immediate control-tower decision

- Keep `refactor/stability-s0-20260908` unchanged until the next explicit integration decision.
- Treat `e44fd08` as a valuable long-run liveness candidate, not final G0 approval.
- Complete the unified Lobby modal-owner correction first.
- Correct pressure-transfer semantics on the G0 candidate so `skipped` is not equivalent to business success/release.
- Close/verify the normal-farm victory/failure recreate loops and archaeology handoff.
- Then freeze one FINAL_PRODUCTION_SHA, run Opus static review, repin Harness once, and begin soak GT.

## 8. Status summary

- `CURRENT_PRODUCTION = 5fbd513`
- `CURRENT_HARNESS = ff54891 (pinned to 5fbd513)`
- `LONG_RUN_CANDIDATE = e44fd08`
- `LOBBY_GENERIC_MODAL_UNIFIED = NO / pending correction`
- `PRESSURE_CORE_CONTRACT_MATCH = NO on e44fd08`
- `NORMAL_CORE_LOOP_G0_PROOF = INCOMPLETE`
- `ARCHAEOLOGY_HANDOFF_G0_PROOF = INCOMPLETE`
- `READY_TO_REPIN_HARNESS = NO`
- `READY_FOR_FORMAL_SOAK_GT = NO`
