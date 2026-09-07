# ShuaBao Cloud Architect Control Tower — CURRENT

> Canonical short-form handoff for the active ShuaBao execution state.
> New cloud/Aster/Opus/Sol conversations should read this file first from branch `handoff/latest`, then independently re-read the live `origin/trial-merge` HEAD before trusting any older Agent report.
> This handoff branch is documentation-only. Do not merge it into `trial-merge` merely to carry status notes.

## 0. Current phase

The project is no longer blocked on release packaging, UAC diagnosis, basic lobby-tab switching, or physical search-box input.

The first real-machine Hitch GT on the current release reached:

`formal desktop package -> room-list tab -> search box -> physical input '4' -> real filtered room results`

and then deadlocked before Refresh/Join.

The direct blocker has now been localized with real video frames + runtime logs. Aster is currently assigned a READ-ONLY system-level root-cause / liveness audit. Production code must remain frozen until that audit is reviewed.

Planned sequence:

`real evidence -> Aster read-only root-cause audit -> review/accept architecture direction -> Opus 5 as sole code writer -> GPT-5.6 Sol independent review -> rebuild exact final SHA -> exact approval -> bounded real-machine Golden Run`

## 1. Live code/release baseline

Repository:

`Yszdhhh/shuashuabao`

Integration branch:

`trial-merge`

Current accepted code-bearing baseline:

`0128342e0ebde7754e3cabb7f2f6908580716c36`

Commit message:

`fix(tests,mediator): green the release gate - seed room authority, drop duplicate-capture counts`

At the last verified state:

- local `trial-merge` and `origin/trial-merge` were exactly aligned;
- worktree was clean;
- production code had not changed after the release-gate closure.

Current immutable package:

`C:\Users\10639\AppData\Local\ShuaBao\app-0.3-dev-0128342e0ebd`

Identity:

- source SHA: `0128342e0ebde7754e3cabb7f2f6908580716c36`
- EXE SHA256: `6fce123e5dc4c94bacd46b07c2428d8d7c1d4ef82aaa0f48cd14a07422f65186`
- release manifest SHA256: `c6f3f68e688ac4b139050a026ef7464861dcff3e373d25ba76082f62428844a8`

Last accepted full release gate on this production SHA:

- pytest: `1577 passed, 0 failed`
- frozen replay: PASS
- scene templates: PASS
- contract: PASS
- overall release gate: `PASS 4/4`

A later isolated night worktree reported environment-dependent skips; those were audited as expected environment/display/fixture skips and did not change production code.

## 2. Release approval / startup state

The current package was successfully approved for the bounded GT with exact release identity and mode restriction:

- source SHA: `0128342e...`
- manifest SHA: `c6f3f68e...`
- channel: `dev`
- allowed mode: `lobby_hitch`
- approval command returned `status='approved'`

Operator credentials and the external manifest trust anchor are deliberately kept outside Git. Never write usernames, passwords, private keys, tokens, or secret values into this handoff.

Windows UAC remains an expected security boundary because the shipped EXE uses `requireAdministrator`. User confirmation of UAC is not a ShuaBao product failure.

## 3. First real-machine GT — actual observed behavior

Real evidence archive on the local machine:

`G:\测试视频+抽帧\现场抽帧_20260907_104852`

Key frames:

- `00s_00_start.png`
- `30s_01_room_list_tab.png`
- `35s_02_search_box_blank_matched.png`
- `38s_03_search_box_input_4_typed.png`
- `40s_04_search_results_visible_room_rows.png`
- `60s_05_looping_blocked_on_search_box.png`
- `90s_06_still_blocked_zero_input.png`

Runtime log:

`ShuaBao_run_20260907_104852.log`

Observed business progression:

1. Room List tab was reached successfully.
2. Empty search box was located and clicked.
3. Physical input `4` succeeded.
4. KK visibly showed `4` in the search box.
5. Real filtered room rows became visible.
6. Automation did not perform subsequent Refresh or Join.
7. It then remained in ZERO INPUT waiting.

Relevant log sequence:

```text
10:49:30,473 INFO [L0] hitch 点击搜索框并输入 '4' (screen=(1746, 346))
10:49:31,071 INFO [L0] hitch 等待搜索词 '4' 生效确认（零输入）
10:49:32,137 INFO [L0] hitch 搜索词 '4' 未获视觉确认，零输入重试
10:49:33,184 INFO [L0] hitch 未识别搜索框，零输入等待
```

The last message then repeated for roughly 84 seconds.

## 4. Current first blocker — self-invalidating search evidence

The current evidence strongly localizes the direct deadlock to the search postcondition/locator seam.

Real-frame measurements:

- empty `lobby_search_box` template match: about `0.9568`
- after typing `4`: about `0.6447`
- scene threshold: about `0.70`

The shipped `lobby_search_box` template represents the empty search box. The automation successfully types `4`, which changes the pixels inside that same ROI. The subsequent search-confirmation path calls `find_scene(frame, "lobby_search_box")` again. The box therefore stops matching precisely because the action succeeded.

Current deadlock hypothesis, to be independently verified by Aster from source:

`empty search-box locator -> type '4' -> UI mutates -> _hitch_search_pending -> _hitch_search_prefix_confirmed -> same empty-box template no longer matches -> prefix never confirmed -> _hitch_prefix_searched remains false -> _find_hitch_joinable_row / _find_hitch_refresh never become reachable -> ZERO INPUT loop`

Classification:

`CURRENT_FIRST_BLOCKER = SELF_INVALIDATING_SEARCH_EVIDENCE`

Do not treat the fix as merely lowering the template threshold or adding a one-off filled-`4` template unless the architecture review proves that is correct.

## 5. Why this matters beyond the current screenshot

The repeated project failure pattern is broader than one template:

- unit/targeted tests can validate Refresh, Join, Exit, duplicate-room avoidance, etc.;
- production still requires the full chain:
  `WindowIdentity -> Capture -> Context -> Evidence/OCR -> Authority -> FSM -> Hit -> InputExecutor -> FreshFrame -> BusinessPostcondition`;
- if one upstream Evidence/Authority gate is unreachable, all downstream functions can remain perfectly tested yet never execute on the real client.

A previous release-gate incident already showed test/production wiring divergence: synthetic tests could call Hitch logic without following the same production Authority lifecycle. That class of problem must not recur.

Three systemic themes are now under audit:

1. **Locator / State Evidence / Business Postcondition conflation** — mutable UI content may invalidate a locator that is incorrectly reused as post-action proof.
2. **Distributed Authority / lifecycle coupling** — multiple modules can independently block the same business progression with implicit state dependencies.
3. **Liveness policy too coarse** — recoverable or low-value uncertainty can become indefinite FAIL-CLOSED / ZERO INPUT, blocking the long-running primary objective.

The lobby is especially exposed because it has dynamic tabs, search content, room rows, multiple KK surfaces, popups and window/focus changes. In-game scenes are often more spatially stable.

## 6. Safety and liveness policy being audited

Do not weaken the existing safety invariant globally.

Target policy:

- **Dangerous ambiguity** (unknown application/window/unauthorized surface): `ZERO INPUT / FAIL_CLOSED`.
- **Recoverable progress ambiguity** (known target-owned search/list/modal/subflow): bounded `RETRY / RE-ANCHOR / ABORT_SUBFLOW / RETURN_TO_SAFE_BASELINE`.
- **Low-value best-effort choice** (where an imperfect legal choice costs less than freezing the main run): bounded `FAIL_FORWARD` using an explicit safe default/policy.

Examples such as an unreadable hero-card name should not automatically block later evolution/equipment flow forever if the scene is positively identified and a legal bounded default exists.

However, do NOT implement a generic blind `close any X`, generic UNKNOWN->ESC, unlimited retry, or watchdog-driven forced progression. Secondary-window recovery is only legal when target ownership and recovery action are positively established.

## 7. Aster task — ACTIVE / READ ONLY

Aster is currently asked to inspect the local real evidence and current source without modifying code, building, committing, pushing, or sending real input.

Aster must independently verify:

- the exact search deadlock call chain and state-variable lifecycle;
- whether `lobby_search_box` mixes stable locator, mutable state detector and postcondition roles;
- other `SELF_INVALIDATING_EVIDENCE` patterns in Search/Refresh/Join/Ready/Exit/ExitConfirm/room controls/HUD anchors;
- tests that mock/preseed intermediate Evidence/Authority and therefore bypass production wiring;
- recurrent causes behind historical “tests pass, old real functionality breaks again” incidents;
- which ZERO INPUT / WAIT states are genuinely safety-critical versus recoverable or low-value;
- the minimal architecture change that reduces state space rather than adding fallbacks;
- a production-chain regression topology using the real pre/post-action frames.

Expected Aster output includes:

`CURRENT_FIRST_BLOCKER`
`EXACT_DEADLOCK_CHAIN`
`ROOT_CAUSE_TREE`
`SELF_INVALIDATING_EVIDENCE_FINDINGS`
`LOCATOR_VS_STATE_EVIDENCE_PROBLEMS`
`TEST_PRODUCTION_GAPS`
`RECURRENT_SYSTEMIC_CAUSES`
`MINIMAL_CORRECT_FIX`
`FILES_AND_FUNCTIONS_TO_CHANGE`
`REGRESSION_TEST_TOPOLOGY`
`HUD_LIFECYCLE_FINDING`
`OPUS_IMPLEMENTATION_BRIEF`

No production writer should begin until this audit is reviewed.

## 8. HUD shutdown drift — separate issue

User observed that when the script is stopped/closed, the HUD visibly shifts downward once immediately before disappearing.

Treat this as a separate lifecycle/ordering investigation, not as part of the current Hitch search fix.

Working hypothesis only:

`target/anchor authority cleared -> HUD layout/update executes once more -> fallback/stale geometry used -> HUD moves -> hide/destroy`

This remains `NEEDS_RUNTIME_TRACE` unless Aster or later runtime evidence proves it. Do not hide it with a fixed Y-offset patch.

## 9. Implementation policy after Aster review

If the Aster audit is accepted, use **one production code writer**.

Preferred writer:

`Opus 5`

Scope:

- fix the current self-invalidating Evidence seam;
- implement only the minimal reusable architectural/liveness mechanism justified by the evidence;
- add production-wiring regressions from the real frames;
- do not rewrite the whole Mediator/FSM;
- do not add broad fallback/retry/watchdog state explosion.

After Opus produces the implementation and tests, use **GPT-5.6 Sol as an independent reviewer**, not as a concurrent writer.

The reviewer must specifically check:

- whether the diff reduces, rather than increases, state space;
- whether locator identity is separated from mutable UI state/postcondition where needed;
- whether tests exercise production wiring instead of manually pre-seeding `_hitch_prefix_searched`, room authority or equivalent intermediate state;
- whether safety-critical UNKNOWN remains fail-closed;
- whether bounded recovery/fail-forward is only used on positively identified recoverable/low-value states;
- whether package/release identity must be regenerated because code changed.

## 10. Real-machine acceptance after code changes

Any accepted production-code change invalidates the current package as the final GT artifact.

Required sequence after implementation:

`targeted regressions -> full release gate -> commit/push exact final trial-merge SHA -> one clean immutable package -> verify source/build/current/manifest identity -> exact release approval for the new SHA -> user UAC/start -> bounded real-machine GT`

Required bounded business chain:

`arbitrary lobby tab -> room list -> search -> visible results -> autonomous refresh/room selection -> join -> confirmed real room HWND -> evaluate floor condition -> reject/exit when needed -> real exit confirmation -> fresh lobby -> at least one subsequent real refresh/search -> STOP`

Only the complete chain may be labeled:

`REAL_MACHINE_PASS / GOLDEN_RUN_001`

Click success, SendInput success, frame change, synthetic replay, or isolated unit-test PASS are not substitutes.

## 11. Hard rules for the next conversation

1. Re-read live `origin/trial-merge` before acting; live Git wins over this document if it has advanced.
2. Keep `trial-merge` code frozen while Aster is still auditing.
3. Do not run Opus and another code writer concurrently on the same repair.
4. Do not solve the current incident by merely lowering `0.70` to `0.60`, adding a `filled_4` special-case template, sleeping longer, infinite retry, or forcing `_hitch_prefix_searched=True`.
5. Preserve fail-closed behavior for genuinely unknown/unauthorized surfaces.
6. Add liveness only where the state and recovery action are positively bounded.
7. Never copy operator credentials/secrets into Git, prompts, logs, packages, or handoff docs.
8. The acceptance gate is the real Golden Run, not test count.

## 12. New-conversation bootstrap

For the next cloud conversation:

1. read `handoff/latest:docs/CLOUD_ARCHITECT_CONTROL_TOWER_CURRENT.md`;
2. independently verify current `origin/trial-merge` and any Aster report/commit location;
3. review Aster's output before authorizing implementation;
4. if the audit is sound, convert only its accepted minimal architecture plan into the Opus implementation brief;
5. keep Opus as the sole writer and GPT-5.6 Sol as the independent reviewer;
6. after a production change, rebuild/approve the exact new SHA before another real-machine GT.
