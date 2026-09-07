# ShuaBao Cloud Architect Control Tower — CURRENT

> Canonical short-form handoff for the active ShuaBao execution state.
> New cloud/Opus/Sol/Codex conversations should read this file first from branch `handoff/latest`, then independently re-read the live `origin/trial-merge` HEAD before trusting any older Agent report.
> This handoff branch is documentation-only. Do not merge it into `trial-merge` merely to carry status notes.

## 0. Current phase

The project has moved beyond the original 2026-09-07 Hitch search-box deadlock. That defect was fixed in the `b15da05` line, but subsequent real-machine runs exposed broader runtime-state / surface-authority / window-ownership / post-game / choice-policy gaps.

The current work is now split into three layers:

1. **Runtime correctness / arbitrary-state takeover** — make the production runtime align from the current physical surface instead of depending on a prescribed historical path.
2. **Natural E2E acceptance harness** — independently capture/verify real production behavior without copying the production FSM or treating click success as business PASS.
3. **Choice Policy evolution** — after runtime/state alignment is stable, evolve from rigid hard-whitelist rules toward a deterministic, explainable utility-scoring policy using structured KB facts and live evidence.

Do not mix these three layers in one implementation wave.

Current intended sequence:

`Corrective A runtime closure -> Sol exact-SHA review -> Corrective B solo production blockers -> Sol exact-SHA review -> Choice Policy v0.1 minimal rules -> align Harness to exact production candidate -> fresh Natural E2E bundle -> Opus targeted/final red-team -> Sol final exact-SHA review -> build -> exact release approval -> bounded multi-entry Golden Run`

## 1. Live Git state

Repository:

`Yszdhhh/shuashuabao`

Integration branch:

`trial-merge`

Last independently verified remote HEAD:

`ea9776cc3f1836624ce058240b447a0ff890fbe1`

Commit message:

`fix(hitch): fix cold-start reconcile, ready 180s budget, and observation foreground thrash`

Parent:

`b15da05f4fd7313b02b2cc466e319d9683aa979c`

The `ea9776` commit changed only:

- `src/shuabao/mediator.py`
- `src/shuabao/vision/capture.py`
- four real fixture images
- `tests/test_b15da05_real_regressions.py`

The branch had no GitHub CI/status checks attached when last inspected. Local Agent test summaries are useful evidence but are not independently equivalent to a cloud-verified CI result.

### Important Sol review result for `ea9776`

`ea9776` is **NOT accepted as a final runtime candidate yet**.

The local report claimed all seven P0/P1 items were closed, but exact remote source review found multiple gaps between the report and the code actually pushed. Therefore:

`EA9776_STATUS = PARTIAL / CORRECTIVE_REQUIRED`

Do not build/package/approve/live-test `ea9776` as the final candidate before Corrective A.

## 2. Historical accepted baseline before `ea9776`

The immediately preceding code baseline was:

`b15da05f4fd7313b02b2cc466e319d9683aa979c`

This line had already fixed the original real-machine Hitch search deadlock by separating the Room List tab acquisition / search locator / search transaction / OCR confirmation lifecycle and by removing search-icon authority from Room List surface authority.

The old immutable package built from `b15da05` was:

`C:\Users\10639\AppData\Local\ShuaBao\app-0.3-dev-b15da05f4fd7`

That package and its approval are historical only once production code advances. Exact release approvals do not inherit across source/manifest identity changes.

Do not overwrite historical packages.

## 3. Real-machine findings after the original Hitch search fix

### 3.1 Leaderboard -> Room List false authority

A real launch from the KK Hero detail `Leaderboard` tab produced:

`hitch 未识别搜索框，零输入等待`

The user manually clicked `房间列表 99+`, after which the search flow immediately resumed.

Root cause was proven:

`real Leaderboard frame`
-> weak `lobby_room_list_selected` template false-positive (almost plain grey background)
-> `_lobby_room_list_evidence(frame) == True`
-> `_tick_hitch_room_list_tab()` bypassed
-> real Leaderboard has no search box
-> search locator fails
-> zero-input loop.

`ea9776` correctly removed this weak `lobby_room_list_selected` template as independent Room List selected authority. Keep this direction.

### 3.2 Kicked-room modal

Real modal:

`平台提示`
`您已被房主移出了房间`

Buttons include:

- `立即购买`
- `取消`
- top-right `X`

Product rule remains:

`confirmed KK modal + confirmed not active game + safe dismiss class -> Esc / X / Cancel`

Never click `立即购买`.

UNKNOWN/unclassified modal remains ZERO INPUT.

Important evidence-quality caveat: the `ea9776` added regression injects `_hitch_ocr_override="你已被房主踢出房间"`; this proves handling only after test-injected classification, not real production recognition of the user modal. Real recognition/dispatch remains to be proven in Corrective A with the actual frame and production path.

### 3.3 Ready room with absent host

Real behavior observed: guest successfully Ready, host did not start for ~4–5 minutes.

User product decision:

`Ready business postcondition confirmed -> start 180s READY_WAIT`

If trusted Hero L1/game evidence appears within 180s:

`cancel wait -> reconcile to L1`

If no game after 180s:

`safe leave flow -> fresh exit/lobby postcondition -> session blacklist stable room_key -> never Join same room again in the current run`

Use the existing session `_hitch_blacklisted_room_keys`; do not create a second blacklist.

`ea9776` currently blacklists too early (before confirmed exit) and can call `_hitch_after_exit()` immediately after an Esc when no Exit button is found. This is not an accepted business postcondition and must be corrected.

### 3.4 L0 -> L1 handoff / KK foreground thrash

A real room successfully started the game and the `英雄三国KK` game HWND appeared, yet the script remained on L0/Platform behavior and kept pulling `KK官方对战平台` back to the foreground.

The same run showed no in-game bootstrap actions:

- Pressure Transfer not clicked
- Auto Task not enabled
- four challenges not initialized

Offline real-frame replay showed the in-game detectors themselves were healthy; the common upstream blocker was that MAIN_LINE / correct L1 ownership was not reached.

Important exact-source review of `ea9776`:

- local report claimed passive L1 probe was expanded to `BOOT + ROOM_WAITING`;
- exact pushed source still probes L1 only under `if self.phase == Phase.BOOT`;
- `ROOM_WAITING` remains in the L0 role set.

Therefore:

`ROOM_WAITING_PASSIVE_L1_TAKEOVER = NOT ACTUALLY CLOSED IN EA9776`

### 3.5 Observation foreground side effects

User rule:

**Observation must not change foreground.**

Capture / detector / OCR / FSM observation should not restore, activate, bring-to-top, or reacquire a window. Focus is legal only immediately before an already-authorized real input action, and the target must match the current business surface authority.

`ea9776` removed one `see()` minimized-window activation path, but exact source still contains observation-side focus mutation paths, including:

- `_capture_best.capture_one()` activating an invalid Hero target before recapture;
- main tick reacquiring foreground when `frame.hwnd` is not foreground before an actual business action intent exists.

Therefore:

`OBSERVATION_ZERO_FOREGROUND_SIDE_EFFECT = NOT CLOSED IN EA9776`

Corrective A must audit every remaining `activate/reacquire/BringWindowToTop/SetForegroundWindow` caller and classify it as ACTION or OBSERVATION.

## 4. Arbitrary-state takeover / state reconciliation

The desired product behavior is no longer “start only from a prescribed page.”

ShuaBao should, whenever safely possible:

`Observe current physical surface -> classify strong evidence -> establish business authority -> reconstruct the minimum state -> enter the existing FSM at the correct point`

Examples:

- Leaderboard/detail tab -> navigate to Room List in Hitch mode
- already in room, not Ready -> evaluate/Ready
- already Ready -> start/restart bounded Ready wait from first observed Ready evidence
- mid-game HUD -> resume normal MAIN_LINE; Hitch checks Pressure/AutoTask/challenges from the current UI state
- Stage Select -> resume Stage FSM
- POST_VICTORY -> resume post-game route
- ARCHIVE_PANEL -> resume archive/Boss logic
- HEIRLOOM_DIALOG -> resume configured Boss logic
- NPC_HUB -> resume post-game hub route
- UNKNOWN -> ZERO INPUT

Important design rule:

Do not build a giant second Router/FSM. Use a thin Surface Reconciliation seam that maps current strong physical evidence to existing phase/FSM entry points.

### `ea9776` cold-start status

`ea9776` added partial post-game reconciliation, but the exact `_startup_state()` still checks Stage Select before `_post_game_state()` for a game client. The local report claimed the opposite ordering.

A fresh solo run also showed post-game classifier cross-contamination around Archive/NPC Hub, proving surface precedence/mutual exclusion remains incomplete.

Corrective A must fix the actual physical-surface precedence and remove repeated `_startup_state(frame)` calls in `_tick_l0`.

## 5. Pressure Transfer bootstrap semantics

User expects Hitch in-game bootstrap roughly:

`trusted HUD -> Pressure Transfer if still available -> AutoTask -> four challenges -> normal L1 loop`

`ea9776` correctly moved Pressure Transfer before the AutoTask gate. Preserve that priority.

However exact source still has incorrect state semantics:

- `main_line_duration > 25s -> _hitch_pressure_transferred = True`
- `act_click(...) SUCCESS -> _hitch_pressure_transferred = True`

Both are invalid.

Timeout/opportunity expiration != successful transfer.

SendInput/click success != business transfer success.

Corrective A must make `_hitch_pressure_transferred` mean only a fresh business postcondition. If the opportunity naturally expires or is absent on cold-start, stop trying without claiming success.

## 6. Solo Live Harness — independent test branch

Dedicated Harness branch:

`test/solo-live-harness-20260907`

Latest independently verified remote HEAD:

`144c0c9adc366a35548f6e1c2e52fad8387da090`

This branch is intentionally isolated from `trial-merge`.

It modifies only:

- `tools/live_scenario_capture.py`
- `live_scenario_launcher.ps1`
- `tests/test_live_scenario_capture.py`
- `docs/live_scenario_capture.md`
- `docs/live_harness_opus_review_20260907.md`

The Harness continues to call real production `RuntimeMediator/Mediator.tick()` and does not copy the game FSM or send direct business input itself.

Current GUI has a `solo_ingame_chain` path starting from a real Stage Select for focused single-player in-game/post-game testing. The original BOOT->room->next-round full-cycle contract remains in CLI/data but is not the current primary menu path.

### Critical version-alignment warning

The Harness branch diverged from `trial-merge` at `b15da05`. Because it runs `SOURCE_RUNTIME`, running the current Harness worktree does **not** automatically test `ea9776` or future production SHAs.

Before formal Natural E2E acceptance, rebase/cherry-pick the pure Harness commits onto the exact final production candidate so that:

`Harness runtime source == production candidate source`

Do not claim a Harness PASS against one production SHA when SOURCE_RUNTIME actually loaded another.

## 7. Fresh Solo Harness findings / current production blockers

A real single-player in-game/post-game diagnostic found the following production issues. The Harness correctly refused to promote these to PASS merely because clicks succeeded.

### 7.1 Early Challenge / TQTZ

Production saw the real `5-5 + 10min` `提前挑战` icon and emitted `ClickTQTZ`.

Input returned SUCCESS, but the fresh frame still showed the same icon and no business postcondition was confirmed.

`TQTZ_REQUEST = OBSERVED`
`TQTZ_BUSINESS_CONFIRMATION = NOT PROVEN`

Future Corrective B must treat TQTZ as request + fresh postcondition, not click-success success.

### 7.2 `auto_close_main_line=true` conflict

The official configuration snapshot had:

`auto_close_main_line = true`

Production first emitted `DisableAutoTask`, then later repeatedly emitted `EnableAutoTask`.

This is a production ordering/gating conflict, not a Harness defect.

Corrective B must ensure that a user-configured “close/disable main line” policy cannot be immediately undone by the generic `_ensure_auto_task_enabled()` path.

### 7.3 Archive loot challenge 7/8

Real archive panel showed loot challenge approximately `7/8`, yet no `ArchiveChallenge-loot` action occurred.

Read-only analysis localized this to `_archive_hitch_card_unavailable()` using a warm/red pixel heuristic that can misclassify a valid red progress counter as “unavailable”.

Corrective B should replace the weak heuristic with business-state evidence that distinguishes `0/8 unavailable` from `7/8 available`.

### 7.4 NPC Hub / post-game route

After the Archive panel closed, the client showed an NPC-Hub-like post-game surface, but production failed to confirm `NPC_HUB`, and the route eventually hit:

`post-game transition timeout`

This is a production classifier/surface-precedence problem. Harness intentionally did not invent a fake detector.

Corrective B should enforce mutual exclusion between Archive / NPC Hub / Stage Select / other post-game surfaces based on real frames.

### 7.5 External window obstruction

Real run observed:

- `CANCELLED_WINDOW_CHANGED`
- `CANCELLED_WINDOW_OBSCURED`
- `CANCELLED_SENDINPUT_FAILED`

The foreground/covering window was Chrome (`Chrome_WidgetWin_0`).

Harness now treats external obstruction as environment `BLOCKED` and requests a safe stop instead of pretending it is a production business FAIL or automatically using ESC/F1/focus hacks.

Natural E2E for that run remains:

`NOT PASSED / BLOCKED_BY_PRODUCTION_AND_ENVIRONMENT`

## 8. Opus stage review — PAUSED, findings retained

An Opus review was started on the Solo Harness / old real bundle and then intentionally paused because the production and Harness baselines were moving.

Do not discard the findings; do not continue reviewing the obsolete snapshot.

Useful stage findings included:

- Harness post-game progress could still be over-promoted from internal state/request rather than strong physical confirmation in some paths;
- StageStart could admit stale-frame confirmation;
- BLOCKED safe-stop handling / ordering needed tightening;
- environment BLOCKED could mask a later product FAIL if precedence is wrong;
- the real Solo run used an older Harness snapshot than the acceptance code later reviewed, so the latest Harness tightening did not have real-machine coverage.

Recommended use of Opus:

After Corrective A/B and Harness exact-source alignment, give Opus one frozen package:

`PRODUCTION_SHA + HARNESS_SHA + fresh exact-version real bundle + prior Opus findings`

and request a targeted no-write final red-team review.

## 9. `肉身成圣` / Fengshen finding

A key forensic correction:

The real OCR did **not** primarily fail to read `肉身成圣`.

The raw run showed `肉身成圣` recognized repeatedly with high confidence (about 0.94–0.998). The real reason it was refreshed away was the current hard-whitelist / advanced-group policy filtering it out.

Current structure:

- KB knows `肉身成圣` and describes it as a 3-card accelerator related to Fengshen;
- choice lexicon can identify it;
- current hard whitelist / `choice_policy.json` Fengshen group and official defaults do not include it as a legal runtime candidate;
- mechanics evidence is not yet fully live-verified even though identity evidence is now live-verified.

Do **not** solve this by an OCR threshold tweak.

Do **not** simply pretend `肉身成圣` is a normal persistent `owned_bond_cards` card; its consumable/accelerator semantics differ from ordinary held/synthesis cards.

## 10. Choice Policy v0.1 — user-approved minimal behavior (after runtime closure)

Do not implement this concurrently with Corrective A/B.

After core runtime is stable, the user wants a conservative first policy improvement with only two behavioral changes.

### 10.1 High refresh cost + empty slots

User rule:

If the next bond refresh is already around `100 wood` and the bond slots are still relatively empty, do not continue refreshing blindly.

Safe v0.1 interpretation:

If a **trusted structured refresh-cost evidence** proves:

`next_refresh_cost >= 100`

and:

`free_slots >= 3`

then REFRESH loses its default priority.

- if an already-legal/safe current candidate exists -> take the best candidate under the existing ranking;
- if no legal safe candidate exists -> CLOSE/HIDE;
- do not loosen hard-whitelist safety merely to save wood.

Evidence gate: do not hard-code a price ladder from memory. First prove the refresh-cost source from KB/trace/UI/runtime data.

### 10.2 Fengshen-stage `肉身成圣`

When the current active advanced route is provably Fengshen, and a slot is confidently recognized as `肉身成圣`, it should be allowed as a Fengshen accelerator candidate even if absent from the ordinary hard whitelist.

Conservative v0.1 ordering:

1. deterministic near-complete synthesis
2. deterministic duplicate/merge improvement
3. Fengshen-active `肉身成圣`
4. ordinary legal Fengshen/base preset
5. REFRESH
6. CLOSE/GIVEUP

Do not fabricate 1/3, 2/3, 3/3, consumed-state, or Fengshen-progress facts if runtime evidence cannot prove them.

## 11. Choice Policy v1 direction — dynamic utility, NOT IMPLEMENTED YET

The longer-term goal is to make choice behavior less rigid while remaining deterministic, auditable and safe.

Desired action space:

- `TAKE(slot_i)`
- `REFRESH`
- `GIVEUP`
- `CLOSE/HIDE`
- possibly `DEFER` only where the real UI supports temporarily hiding and safely returning

Recommended architecture:

### Layer A — Eligibility / hard safety

Hard constraints remain non-negotiable:

- unknown / low-confidence irreversible candidate cannot be selected;
- unsafe/negative effects can be excluded;
- impossible resource action cannot be selected;
- ambiguous surface -> ZERO INPUT;
- mutual exclusion / verified prerequisite constraints remain gates.

### Layer B — Structured current state

Use explicit facts such as:

- game phase/time
- hero attributes / dominant stat
- current skills and skill tags
- owned cards
- verified set/progress
- free slots / slot pressure
- resource balance and next refresh cost
- current advanced route (e.g. Fengshen)
- expected near-term slot release where mechanics are actually verified
- evidence confidence / source quality

### Layer C — Explainable utility features

Examples requested by user:

- **growth card early-game bonus** — growth/scaling cards have higher utility earlier and decay later;
- **easy synthesis bonus** — cards requiring only one or two additional copies have higher utility because synthesis is near and can release slot pressure;
- **hero-stat synergy** — if Intelligence is currently the dominant scaling attribute, Intelligence-related cards gain utility;
- **skill-element/tag synergy** — fire/burn cards gain utility when current skills are fire/burn-oriented; energy/magic cards gain utility when a skill such as `奥术箭` is the main carry;
- **slot pressure / expected release** — a full slot bar is a penalty, but a verified near-term consumable/synthesis release can reduce that penalty;
- **resource opportunity cost** — REFRESH utility drops as refresh cost rises, especially when slots are empty and a safe card is already available.

### Layer D — deterministic action selection + business postcondition

Compute an explainable utility for every eligible action, choose the highest deterministic action, then require the normal fresh business postcondition.

No reinforcement learning is required for the first versions.

### Decision telemetry requirement

Future policy should log the candidate action ledger, e.g. feature contributions and final score, so a bad decision can be audited and weights can be tuned from real runs.

Do not make the score a black box.

## 12. Why the current system still feels rigid

The current `choice_policy.py` is deterministic and safety-oriented, but much of the current behavior is a sequence of hard filters and lexicographic priorities:

`whitelist -> prerequisite -> base/advanced gate -> capacity gate -> near-complete -> must-take -> duplicate -> preset -> refresh -> synthesis -> quality -> close`

This is robust but cannot naturally compare tradeoffs such as:

`take a decent card now vs spend 100 wood refreshing vs preserve a nearly-full slot vs pursue a route accelerator`.

The KB is currently consumed mostly as lookup/gating/ranking metadata rather than as a structured game-mechanics model. Therefore “more KB” does not automatically produce smarter decisions.

The architectural goal is not to delete safety rules. It is to separate:

- **hard legality/safety constraints** from
- **soft value/tradeoff evaluation**.

The first stays rule-based; the second becomes feature/utility-based.

## 13. Corrective A — NEXT production task

Corrective A is the immediate next production step and should be executed by one writer only.

Required closure:

1. implement true `ROOM_WAITING -> passive L1 candidate -> strong surface reconcile` without focus side effects;
2. remove all observation-path foreground activation/reacquisition; focus only action-scoped;
3. correct Surface Reconciliation precedence/mutual exclusion, especially post-game vs Stage;
4. make Pressure Transfer state mean fresh business postcondition only;
5. prove real kicked-modal recognition/dispatch without `_hitch_ocr_override` test injection;
6. make Ready-180s timeout wait for fresh exit/lobby confirmation before blacklisting/resetting;
7. add real transition regressions and run the full mandatory release gate.

Do not build, approve or LIVE during Corrective A.

After push, GPT-5.6 Sol must re-read exact remote SHA/diff before authorizing Corrective B.

## 14. Corrective B — planned after Corrective A review

Use the fresh Solo real evidence to fix only these production blockers:

- TQTZ request -> fresh business postcondition;
- `auto_close_main_line=true` cannot be undone by generic AutoTask enable path;
- Archive loot `7/8` vs unavailable distinction;
- NPC Hub / Archive / Stage post-game classifier mutual exclusion;
- UNKNOWN post-game/surface remains ZERO INPUT.

Do not mix Fengshen/Choice Policy v1 into Corrective B.

## 15. Acceptance policy

Final acceptance remains real-machine, not unit-test count.

Required hierarchy:

`real physical surface -> production classifier/evidence -> business authority -> real production action -> fresh frame -> business postcondition`

Forbidden substitutions:

- click success
- SendInput success
- phase change alone
- frame changed
- seeded test boolean/state
- synthetic replay
- old-version bundle

Formal future Golden Run should be multi-entry, including at least:

- arbitrary L0 tab / Leaderboard -> Room List -> Hitch search/join/Ready;
- Room Ready -> external host start -> passive L1 takeover;
- mid-game cold-start;
- Stage Select cold-start;
- POST_VICTORY / ARCHIVE_PANEL / HEIRLOOM_DIALOG / NPC_HUB cold-start;
- solo full-cycle or stage-to-post-game chain with fresh business evidence;
- UNKNOWN safety zero-input.

## 16. Hard rules

1. Always re-read live `origin/trial-merge` before acting; live Git wins over this handoff.
2. Keep one production code writer at a time.
3. Keep Harness changes isolated from production; align SOURCE_RUNTIME to the exact production candidate only for formal acceptance.
4. Do not use Opus to keep reviewing an obsolete moving snapshot. Use it on a frozen final candidate + fresh bundle.
5. Observation must not steal foreground.
6. HWND/title presence alone never grants business authority.
7. UNKNOWN / unauthorized surface remains fail-closed / ZERO INPUT.
8. Do not weaken safety with generic ESC/watchdog/fixed-coordinate/global-threshold hacks.
9. Do not treat KB guide text as verified runtime mechanics without evidence metadata.
10. Never place operator credentials, private keys, tokens or secret values into Git, prompts, packages, logs or this handoff.
11. Exact package/release approval must be regenerated after accepted production-code changes.
12. The real Golden Run is the acceptance gate, not local test counts.

## 17. New-conversation bootstrap

For the next cloud conversation:

1. read `handoff/latest:docs/CLOUD_ARCHITECT_CONTROL_TOWER_CURRENT.md`;
2. independently verify live `origin/trial-merge`;
3. if Corrective A has landed, compare its exact SHA against `ea9776` and review the actual diff before trusting the Agent summary;
4. only after Sol accepts Corrective A authorize Corrective B;
5. keep Choice Policy v0.1 separate from runtime stabilization;
6. later align the Harness worktree to the exact production candidate and generate a fresh bundle;
7. then resume Opus as targeted final red-team, followed by Sol final review;
8. only then build, exact-approve and run the bounded multi-entry Golden Run.
