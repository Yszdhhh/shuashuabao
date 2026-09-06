# ShuaBao Cloud Architect Control Tower — CURRENT

> Canonical short-form handoff for the current execution state. New cloud/Astra/Aster/Codex conversations should read this file first from branch `handoff/latest`, then independently re-read the live GitHub branch HEADs before trusting any Agent report.
>
> Historical/deeper context remains in `docs/CLOUD_ARCHITECT_CONTROL_TOWER_20260905.md`. Where this CURRENT file conflicts with the older handoff, this CURRENT file wins for active priorities and next-step ordering.

## 0. Current operating mode: REAL-MACHINE FIRST

The project is temporarily in **Real-Machine First** mode.

Primary goal:

`formal desktop package -> Start -> real lobby search -> join room -> floor-1 condition fails -> exit -> real exit confirm -> fresh lobby -> at least one subsequent real refresh/search`

Until this bounded chain runs successfully once:

- do not start Architecture Stage 2;
- do not perform broad refactors or code slimming;
- do not expand OCR/FSM/watchdog/recovery frameworks;
- do not reopen already-accepted subscription/release architecture unless it is the direct runtime blocker;
- do not fix speculative P2/P3 issues before they appear in the current real-machine chain;
- do not turn one observed failure into a multi-module cleanup campaign;
- use targeted regression only for the direct blocker, then rebuild and return to real-machine execution quickly.

Required iteration loop:

`real run -> preserve evidence at first blocking point -> identify one direct root cause -> minimal fix -> targeted regression -> one clean package -> resume real run`

Do **not** use this loop:

`one failure -> audit many modules -> speculative fixes -> large redesign -> huge test pass -> first real run reveals a new basic integration failure`.

Validation priority is now:

`real business closure > fresh real-machine evidence > targeted regression > full regression > architectural elegance`.

A large pytest count is regression evidence only. It is never a substitute for a real business PASS.

## 1. Git state at this handoff

Main repository:

`Yszdhhh/shuashuabao`

Main integration branch:

`trial-merge`

GitHub independently verified current HEAD:

`52d89a2ab336f245d28588bc47ae0af24b7622d7`

Commit:

`fix(vision,hud,mediator): exclude ToolTipSaveBits HWND, anchor HUD by HWND identity, and whitelist in-game failure preempt`

Parent:

`1c4066602a6f5402caf08c4c6e63026a50558e5e`

This `handoff/latest` branch is deliberately separate from `trial-merge` so documentation updates do not change the current code-bearing release identity.

Current cloud verdict for `52d89a2...`:

`CODE_REVIEW_PASS_WITH_TEST_DEBT`

`APPROVED_FOR_ONE_CLEAN_REBUILD_AND_IMMEDIATE_HITCH_GT`

Do not request another speculative repair round before the next real run unless the package/cold-start gate itself fails.

## 2. Why `52d89a2...` exists

The previous real-machine attempt exposed three direct runtime defects:

1. KK window capture selected a `308x800` transient helper window with class `Qt5152QWindowToolTipSaveBits` instead of the real approximately `1334x947` platform window.
2. HUD anchoring followed changing frame rectangles/HWNDs and visibly jumped between windows.
3. Generic disconnect/fail detection could preempt pre-game/L0 phases and enter `RECOVER_FAILURE` before the Hitch search chain began.

### Accepted production changes in `52d89a2...`

#### A. Window identity / transient helper exclusion

`src/shuabao/vision/capture.py`

- explicitly rejects ToolTip/SaveBits transient helper classes during target enumeration;
- includes the observed physical class `Qt5152QWindowToolTipSaveBits`;
- removes the old generic rule that blindly gave the smallest KK window a large priority boost;
- leaves real create/join/exit child-window selection to the existing semantic probes in `_capture_best()`.

For the exact observed `main KK window + Qt5152QWindowToolTipSaveBits` topology, the transient helper is now removed before capture selection.

#### B. HUD HWND identity anchoring

`src/shuabao/shell/overlay_hud.py`

- stores an anchor HWND;
- same non-game HWND may update geometry;
- a different non-game HWND cannot steal the HUD anchor;
- an explicitly identified game HWND may take over from the L0 anchor and then remains authoritative.

This directly addresses the observed cross-window HUD jump rather than only small geometric jitter.

#### C. In-game-only strong failure preemption

`src/shuabao/mediator.py`

Global disconnect/fail preemption is now authorized only for the explicit in-game whitelist:

- `MAIN_LINE`
- `EARLY_CHALLENGE`
- `ANCHOR_BOSS`
- `LONGZHU`
- `QUIT`

Pre-game/lobby/stage-transition phases are outside this authority set.

The safety invariant remains:

`UNKNOWN / ambiguous / stale / unauthorized evidence => ZERO INPUT`.

## 3. Independent cloud findings that are NOT reasons for another pre-GT repair round

Two debts were found during cloud review. Record them, but do not reopen code before the next real run solely for these items.

### Test debt A — the 12-phase negative disconnect test is not actually a healthy-frame test

`tests/test_hitch_l0_and_hud_fixes.py` labels the frame as healthy but constructs it with a constant `np.full(..., 100)` image.

Production `check_frame_health()` marks frames with standard deviation `< 1.0` as `LOW_ENTROPY`, so this test may return before the failure-preempt block. Therefore the reported claim that all 12 cases exercised a healthy high-entropy forced disconnect path is stronger than the test actually proves.

This is a **test-quality debt**, not a current production blocker, because the production authority check itself is a simple positive whitelist and the excluded phases are visibly outside it.

Fix this later during the stability/ablation work unless the next real run shows a failure-preempt regression.

### Test/design debt B — comment says “large KK main window default”, ranking code only removes the small-window boost

The new capture ranking gives ordinary KK candidates the same base KK score and still gives foreground a bonus. It does not explicitly add an area/main-window preference despite the comment saying the large lobby is the default baseline.

For the exact observed ToolTipSaveBits failure this is not blocking because that helper HWND is now excluded entirely.

If a future real run shows a **different non-transient KK child HWND** stealing capture, promote this debt to the next direct blocker. Do not patch it speculatively now.

## 4. Test evidence boundary

Agent-reported local results for `52d89a2...` include targeted tests, full pytest, and release gate PASS.

GitHub currently exposes no combined CI statuses for this commit. Therefore:

- treat the Agent pytest/release-gate numbers as local execution evidence;
- do not call them cloud CI;
- do not infer real-machine PASS from them.

The reported total pytest count also differs from an earlier report despite added tests. Do not spend the current real-machine window investigating that count discrepancy unless a test gate actually fails during the next clean build.

## 5. Immediate next action — no more design work first

From `trial-merge @ 52d89a2ab336f245d28588bc47ae0af24b7622d7`:

1. confirm worktree clean and remote HEAD still exactly `52d89a2...`;
2. perform **one** clean immutable build;
3. run the existing release gate/signature/package verification;
4. exact-approve that package against the subscription release policy using the existing approved mechanism;
5. atomically switch `current.json`, preserving `previous`;
6. cold-start from the real desktop shortcut;
7. confirm saved DPAPI license restores automatically, subscription is ACTIVE, LIVE permit is verified, OCR worker is READY, and no immediate HUD/window regression appears;
8. if cold start passes, immediately execute the bounded Hitch real-machine GT below.

Do not insert another broad Astra review between clean build and GT.

## 6. Bounded Hitch GT boundary

Use the **formal production dashboard**, real KK/game windows, and the current frozen package.

Required boundary:

`大厅 -> keyword search/rotation -> join room -> floor1 condition fails -> exit -> real exit confirmation -> fresh lobby -> at least one subsequent real refresh/search -> STOP`

Do not continue into the next successful join or MAIN_LINE during this bounded pass.

Only three final classifications are valid:

- `REAL_MACHINE_PASS`
- `BLOCKED_REAL_MACHINE_GT`
- `BLOCKED_GT_ENVIRONMENT`

Rules:

- click success is not business PASS;
- SendInput success is not business PASS;
- button disappearance/frame change is not business PASS;
- business advancement requires fresh explicit postcondition evidence;
- UNKNOWN/ambiguous/stale/unclassified means zero input;
- if the run fails, preserve the evidence bundle first and fix only the first direct blocker;
- do not use a failure as permission to redesign unrelated modules.

## 7. First successful run becomes the Golden Run

When the first complete bounded Hitch pass succeeds:

- preserve the full logs/traces/screenshots/identity metadata as the first **Golden Run**;
- do not immediately “optimize” that successful path;
- future OCR/window/FSM/HUD/release changes should be compared against this Golden Run before being accepted.

The purpose is to stop each architecture upgrade from behaving like a fresh integration project.

## 8. Stability ablation — DEFERRED UNTIL TONIGHT / AFTER CURRENT REAL RUN

A stability ablation task is intentionally deferred so it cannot derail the current real-machine objective.

The ablation phase is **observation and experiment design first**, not another architecture rewrite.

Initial layers to isolate later:

- WindowIdentity / HWND topology
- Capture
- Scene perception / template matching
- OCR
- Authority / role+phase ownership
- FrameEvidence / action authorization
- FSM
- HUD
- RuntimeWatchdog

Goal:

identify which layer creates instability and which upstream evidence failure cascades through the control tower.

Do not start implementation, broad refactors, package churn, or production behavior changes as part of the first ablation pass.

A likely later architectural concern is that `mediator.py` carries too many responsibilities and that L0/L1/authority concepts are repeated in multiple places, but this is **not** a reason to interrupt the current attempt to get one real run working.

## 9. Architecture and known debt freeze

Architecture branch:

`refactor/architecture-convergence-20260904`

Stage 2 remains **HOLD** until the current real-machine path is working and the later ablation evidence says what should actually be extracted.

Known RuntimeWatchdog P1 remains deferred unless it directly blocks the bounded GT. Do not build a new watchdog/recovery system before then.

The FrameEvidence/action-gate safety model remains accepted. Do not weaken stale-evidence or one-input-per-fresh-authority protections merely to make the script “keep moving”. Availability improvements should reacquire valid evidence rather than authorize actions from stale/unknown evidence.

## 10. Subscription/release operational notes

The subscription/release control plane and immutable package model are already accepted architecture. Do not reopen them unless the next package cannot obtain exact approval/permit.

A subscription admin credential was previously exposed in conversational text. Never copy that credential into Git, docs, logs, packages, or future prompts. Rotate it before relying on it for further sensitive/admin operations if rotation has not already occurred.

The current `trycloudflare.com` endpoint may be used only for the current dev/GT path while it is demonstrably healthy; it is not proof of a fixed External Beta production hostname. External Beta remains a separate later gate.

## 11. New-conversation bootstrap

If context is lost or a new Agent/chat takes over:

1. read `handoff/latest:docs/CLOUD_ARCHITECT_CONTROL_TOWER_CURRENT.md` first;
2. independently verify `origin/trial-merge` before trusting any reported SHA;
3. if `trial-merge` has moved beyond `52d89a2...`, inspect only the delta before proceeding;
4. preserve **Real-Machine First** priority until one bounded Hitch Golden Run exists;
5. do not restart broad architecture/audit work merely because context changed;
6. continue from the first unresolved real-machine blocker and keep scope minimal.
