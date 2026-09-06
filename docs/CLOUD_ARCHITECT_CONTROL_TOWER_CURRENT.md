# ShuaBao Cloud Architect Control Tower — CURRENT

> Canonical short-form handoff for the current execution state.
> New cloud/Aster/Astra/Opus/Codex conversations should read this file first from branch `handoff/latest`, then independently re-read the live `origin/trial-merge` HEAD before trusting any Agent report.
>
> Historical/deeper context remains in `docs/CLOUD_ARCHITECT_CONTROL_TOWER_20260905.md` and `docs/reviews/REAL_MACHINE_HITCH_DIAGNOSIS_20260906.md`.
> Where this CURRENT file conflicts with older docs, this file wins for active priority and next-step ordering.

## 0. Operating mode: REAL-MACHINE FIRST

Current priority is not architecture elegance or broad cleanup. The only product objective is to make the formal desktop package complete one bounded Hitch chain on the real KK client:

`arbitrary lobby tab -> room list -> keyword search/rotation -> join room -> confirm real room HWND -> floor-1 condition fails -> exit -> real exit confirmation -> fresh lobby -> at least one subsequent real refresh/search -> STOP`

Until this chain succeeds once:

- no Architecture Stage 2;
- no broad Mediator refactor;
- no speculative OCR/FSM/watchdog/recovery expansion;
- no unrelated P2/P3 cleanup before the current real-machine blocker is resolved;
- a large pytest count is regression evidence only, never business PASS;
- click/SendInput success is not business PASS;
- UNKNOWN / ambiguous / stale / unauthorized evidence => ZERO INPUT.

Required iteration loop:

`real run -> preserve first blocker evidence -> minimal root-cause fix -> targeted regression -> commit/push -> one clean package -> exact approval -> resume real run`

The current local execution Agent is authorized to continue through the next 1–2 direct blockers in the same bounded Hitch chain without stopping for a new cloud instruction, unless new user Ground Truth or an external environment decision is genuinely required.

## 1. Git state — independently verified

Repository:

`Yszdhhh/shuashuabao`

Main integration branch:

`trial-merge`

### Current remote HEAD

At this handoff update, GitHub independently shows:

`origin/trial-merge = 614bad89fe27ac3c11e739160ebfa19b19dec5e9`

Commit:

`fix(input): accept target-owned CEF child windows in obscured gate`

Parent:

`d8de9ef69a2f7d19371d9af228b51ac08c39023c`

Important: Opus is actively executing the local closure task. New conversations must re-read `origin/trial-merge` because it may advance beyond `614bad89...`.

This handoff lives on the separate branch `handoff/latest` so documentation refreshes do not mutate the code-bearing release identity on `trial-merge`.

## 2. Recent real-machine progression

### 2.1 Earlier runtime blockers already resolved

The recent Hitch real-machine campaign found and addressed:

1. `Qt5152QWindowToolTipSaveBits` 308x800 helper HWND being captured instead of the real KK lobby;
2. HUD jumping between unrelated HWNDs;
3. pre-game/L0 disconnect/fail false preemption;
4. generic blue lobby controls being treated as room controls;
5. floor-exit pending deadlock after returning to lobby;
6. assuming `>=2 KK HWNDs` automatically means a room exists;
7. source/package/current identity drift between Git and the installed desktop package.

Do not reopen these areas without new real-machine evidence.

### 2.2 Room HWND identity — accepted direction

A critical Ground Truth correction was established from user-provided real screenshots:

- KK can have a second non-room window such as the pet/exploration UI;
- therefore `KK HWND count >= 2` is only a topology hint, not room identity;
- the true room is a distinct KK HWND with room-specific structure/actions.

Commit `6c71828888f1442993ba82295c7cbf49d586d96a` introduced:

- `_confirmed_room_hwnd`;
- strict composite room signature;
- real screenshot fixtures for pet and room windows;
- lobby+pet => no room;
- lobby+room => select room;
- lobby+pet+room => ignore pet, select room.

The current room signature is intentionally stronger than generic blue geometry:

`room_exit_btn AND (room_start OR room_ready OR readyBtn OR room_cancel_ready)`

Generic blue controls, `context==ROOM_WAITING`, or window count alone must not grant room identity.

### 2.3 Packaged-project path repair

Commit `d8de9ef69a2f7d19371d9af228b51ac08c39023c` added packaged `_internal` fallbacks for:

- `config/scenes.json`;
- relative image/template paths.

This commit is a packaging/runtime path fix, not a replacement for the room identity work in its parent `6c718288...`.

## 3. Current direct blocker discovered before Opus takeover

The Hitch state machine had progressed to the room-list search action and correctly found the real search box:

`HitchSearchBox @ (1746,331)`

The input was then cancelled by:

`CANCELLED_WINDOW_OBSCURED`

Physical diagnosis:

- `WindowFromPoint(1746,331)` returned `HWND=37164458`;
- class: `Chrome_RenderWidgetHostHWND`;
- title: `Chrome Legacy Window`;
- its root HWND was `31985540`;
- that root HWND was the KK official platform target itself.

Therefore this was NOT an external Chrome browser covering KK.
It was KK's own embedded CEF/Chromium renderer child surface.

The old obscured gate compared exact HWND / PID semantics and could reject a CEF renderer that belongs to KK but runs in a different renderer process.

## 4. Opus local takeover — ACTIVE EXECUTION

Opus 5 was explicitly assigned as the local Windows execution Agent, not as a cloud-only reviewer.

Its job is to operate directly in the local `trial-merge` worktree and close the real chain:

1. modify local production code;
2. targeted tests;
3. commit + push;
4. clean build;
5. manifest/signature/release gates;
6. exact remote release approval;
7. immutable package + atomic `current.json` switch;
8. launch from the real desktop shortcut;
9. run the bounded Hitch real-machine chain;
10. after the chain works, perform only a light local simplicity audit of the touched window/input/Hitch code.

Do not ask Opus to stop after every normal direct blocker. It may continue the same minimal repair loop until the bounded chain passes or a genuinely new Ground Truth/environment blocker appears.

## 5. Opus progress already visible in Git

Opus has already pushed the first code fix:

`614bad89fe27ac3c11e739160ebfa19b19dec5e9`

Changed production area:

`src/shuabao/input/keyboard_mouse.py`

New targeted test file:

`tests/test_input_window_ownership.py`

The commit introduces a root-window ownership concept using Win32 ancestry (`GetAncestor(..., GA_ROOT)`) instead of a class-name whitelist.

Intended ownership semantics:

- exact target HWND => target-owned;
- same non-zero root HWND => target-owned, including KK embedded CEF renderer children even when renderer PID differs;
- existing legal same-process top-level/modal behavior remains compatible;
- unrelated external Chrome/Terminal/VS Code/Explorer with a different root remains `CANCELLED_WINDOW_OBSCURED`;
- unresolved ancestry is fail-closed;
- no blanket `Chrome_RenderWidgetHostHWND` allowlist.

At the time of this handoff update, this code commit exists remotely, but its final package/deployment/real-machine business result has NOT yet been accepted. Do not label it REAL_MACHINE_PASS until the actual UI postconditions below are observed.

## 6. Package/release identity state

Last locally reported installed package before the Opus input fix:

`app-0.3-dev-6c71828888f1`

That package is now behind both `d8de9ef...` and `614bad89...`.

Expected Opus next step is to build ONE new immutable package from the final code-bearing SHA after the current direct fix set stabilizes.

Before real GT, require four-way local identity readback:

- local Git / `origin/trial-merge` code-bearing SHA;
- `build_identity.source_sha`;
- `current.json.current_source_sha`;
- actually running `ShuaBao.exe` package path/source identity.

They must match exactly.

Do not push a docs-only commit to `trial-merge` after the final package is built; put subsequent handoff documentation on `handoff/latest` instead.

## 7. Immediate real-machine acceptance path for Opus

### Stage A — lobby/search

With the pet window allowed to remain open:

`arbitrary lobby tab -> start lobby_hitch -> pet HWND ignored -> lobby parent selected -> room-list tab selected -> HitchSearchBox found -> KK-owned CEF child accepted by input guard -> keyword entered -> search result visibly takes effect`

Search PASS requires a real UI postcondition. `SendInput SUCCESS` alone is insufficient.

### Stage B — join/room identity

`search/refresh -> join -> confirmed_room_hwnd resolves to the true room HWND -> pet HWND remains ignored -> floor-1 condition evaluated`

### Stage C — exit/return

`floor-1 rejection -> exit -> real exit-confirm modal -> confirm -> fresh lobby -> room HWND disappears/loses authority -> at least one new refresh/search -> STOP`

Do not continue into the next successful room join during the bounded pass.

Valid final classifications:

- `REAL_MACHINE_PASS`
- `BLOCKED_REAL_MACHINE_GT`
- `BLOCKED_GT_ENVIRONMENT`

## 8. Evidence to preserve on the next blocker

If the chain blocks again, preserve before changing code:

- complete log slice around the first blocker;
- screenshot/frame;
- current phase/context;
- current action + ActionResult;
- all relevant HWNDs with title/class/PID/root HWND;
- current package/source identity;
- whether the observed postcondition exists.

Then repair only that direct blocker.

## 9. Light code audit AFTER the real chain works

Only after the bounded chain succeeds, Opus may perform a low-risk local audit limited to:

- `src/shuabao/input/keyboard_mouse.py`;
- Hitch/window identity paths in `src/shuabao/mediator.py`;
- related capture/window selection paths in `src/shuabao/vision/capture.py`;
- directly related tests.

Audit goal:

make the authority boundaries easy to understand:

- Window identity;
- Room identity;
- Input safety.

Allowed low-risk cleanup:

- remove obvious duplicate conditions/dead local branches;
- extract/reuse 1–2 small behavior-equivalent helpers;
- correct stale comments;
- remove clearly obsolete local compatibility logic if proof is strong.

If cleanup may alter business behavior, record it as debt and do not implement it in this closure task.

No broad Mediator decomposition or Architecture Stage 2 here.

## 10. Golden Run and deferred stability ablation

The first complete bounded Hitch success becomes the first Golden Run.
Preserve its full logs, screenshots, HWND topology, package identity and business postconditions.

The previously planned stability ablation remains deferred until after the current real-machine closure. Its purpose is to isolate WindowIdentity/Capture/Perception/OCR/Authority/FrameEvidence/FSM/HUD/Watchdog instability, not to interrupt the current GT with another rewrite.

Architecture Stage 2 remains HOLD.

## 11. Subscription/release notes

The subscription/release control plane and immutable package model remain accepted. Reopen only if the new package cannot obtain exact approval/permit.

Never copy previously exposed admin credentials into Git, logs, packages or future prompts.

The current `trycloudflare.com` endpoint may support the dev/GT path while healthy, but it is not proof of a permanent External Beta hostname. External Beta remains a later independent gate.

## 12. New-conversation bootstrap

If context is lost or a new Agent/chat takes over:

1. read `handoff/latest:docs/CLOUD_ARCHITECT_CONTROL_TOWER_CURRENT.md`;
2. independently read the live `origin/trial-merge` HEAD — Opus may have advanced it beyond `614bad89...`;
3. inspect only the delta after the last verified SHA instead of restarting a full repository audit;
4. preserve REAL-MACHINE FIRST priority;
5. if Opus is still executing locally, do not start a second concurrent code writer on the same branch/worktree;
6. continue from the first unresolved real-machine blocker;
7. do not call the task complete until the bounded chain reaches fresh lobby + one subsequent real refresh/search.
