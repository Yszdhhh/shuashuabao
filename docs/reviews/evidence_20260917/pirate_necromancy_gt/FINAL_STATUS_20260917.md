# Final status — 2026-09-17

## Current Owner authorization (supersedes earlier delivery hold)

Owner authorizes commit/push of this independent TEST/GT branch before a full release-gate result, including explicitly incomplete evidence. No PR, merge or production promotion is allowed. Ninety seconds was an insufficient full-suite deadline, not a test failure. Existing MANUAL_GT/USER_ASSISTED observations remain valid regardless of the eventual offline gate result. The state below is the prior snapshot, not a claim that new experiments are pre-blocked. On resumption, KK官方对战平台 was found (PID 42576, HWND 10551702); game-client/ingame state still requires observation.

Starting SHA: `5b0f2436c5fe8ec2057f4266f42170edd6a95e4a`
Test branch: `test/pirate-necromancy-gt-20260917` (independent worktree at `G:/刷刷宝/Worktrees/pirate-necromancy-gt-20260917`)
Production worktree was not edited by this session. Its HEAD was observed at `922ed1a` during initial discovery; another agent may have advanced it since. No merge, rebase, or PR. Test-branch commit/push is Owner-authorized.

## Overall

- PIRATE_GT: BLOCKED (AUTO/USER_ASSISTED not executed; no available game surface).
- INVENTORY_OVERFLOW_GT: BLOCKED (not executed).
- BAG_CONSUMABLE_GT: BLOCKED (not executed).
- NECROMANCY_GT: BLOCKED (not executed).
- POSTGAME_SECRET_REALM_GT: BLOCKED (not executed).

No game launch, no game input, no synthetic or historical frames recorded as new live GT.

## Configuration deliverable (tested offline)

- `config/dashboard_test_profiles.json` adds 海盗+亡灵机制GT: bonds=[经济], attributes=[], bond_must_take=[藏宝图(三)], bond_advanced_unlock_s=60.0, cards=[zhufu, jj, 藏宝图(三), 海盗, 亡灵], cycle_num=1, auto_secret_realm=true, treasure_allow_negative=[]. The true flag incorporates the Owner's added same-run post-game GT scope.
- Minimal Settings/profile/Dashboard wiring added on the test branch only, marked TEST_ONLY / PROPOSED_PRODUCTION_CHANGE; existing production defaults remain 0.8 / 480 seconds and all existing profiles keep their behavior.
- The real 单人 live path (Settings → choice policy → RuntimeMediator) is the same as production; no Pirate-specific mediator branching exists.
- POSTGAME_SECRET_REALM_GT is enabled on the combined profile through the existing Settings.auto_secret_realm path. The existing 秘境一局 profile remains unchanged. No secret-realm mechanism was rewritten and no real post-game run occurred.
- SOLO_INVENTORY_PRESSURE prototype: NOT implemented. The source-level path (HUD 2–6 positive confirmation → press [B] → dual-anchor BAG_OPEN confirmation → personal free slot → Z → real postcondition) was not built without a live environment, and copying public-bag semantics into solo mode was forbidden.

## Verification actually run

- `python tools/check_pirate_necromancy_profile.py` — exit 0, offline_contract PASS (actual Settings + policy assembly; production defaults 0.8/480 preserved; ordered existing groups; hard whitelist/min-confidence unchanged).
- `python -m pytest tests/test_desktop_app.py -k test_profile_replaces_stale_shell_state -q -p no:faulthandler` — exit 0, 1 passed, 102 deselected.
- Actual PySide6 `MainWindow` with isolated temp AppData: real builtin profile applied, collected settings retained the override (unlock 60.0), advanced_packs=[haidao,wangling]; genuine offscreen capture saved, exit 0.
- After the bool guard, the targeted Dashboard test passed again: 1 passed, 102 deselected. `True` and negative seconds now load as None; absent override remains None.
- After enabling auto_secret_realm=true, the actual profile assembly script returned exit 0 / offline_contract PASS.
- Additional bounded selections: `pytest tests -k secret_realm -x -q --tb=short -p no:faulthandler`: exit 0, 12 passed / 2363 deselected; `-k "inventory or bag"`: exit 0, 116 passed / 2259 deselected. These are offline checks, not live GT or a full gate.

## Verification not obtained

- Full `python tools/release_gate.py --json` did not produce a final verdict: a later full run lasted 1191.81s and exited 255 with only `[gate] pytest ...`. No full-suite PASS or FAIL is claimed. This blocks production promotion, not Owner-authorized test-branch commit/push.
- Actual Dashboard visual acceptance: offscreen capture exists but is the subscription-locked surface with missing-font glyphs; it does not prove visible profile selection. No subscription gate bypass.
- Desktop deployment: the provided shortcut still launches the production source root, not this test branch. `SHUABAO_APP_DATA` isolation requires the Harness to also receive explicit `--settings`; AppData alone does not guarantee settings isolation, and `desktop_app.py` still migrates legacy data from outside the root.

## Runtime access (for the next session, with the operator present)

- Official path: `SHUABAO_APP_DATA` to an isolated directory + `python desktop_app.py`, then select 海盗+亡灵机制GT through the real Dashboard; do not modify `user_settings.json` by hand as the product path.
- Harness/live observation must pass explicit `--settings` and `--production-source-root/sha` matching this test root's actual HEAD; the fixed shortcut remains the production launcher and was not repointed.
- The pre-game window-enumeration OverflowError at `capture.py` is a real prerequisite failure: any single-action or auto GT must first prove valid HWND + frame identity, and click success must never count as business PASS (including GREAT_RIFT_CONFIRM → two distinct real HUD frames → MAIN_LINE recovery).

## Blocked reasons

1. No available game window in the visible session; game availability UNKNOWN until the operator prepares a real client.
2. Full gate incomplete: blocks production promotion, not the Owner-authorized test-branch commit/push or manual evidence acquisition.
3. EX pill screenshot never actually attached (rule USER_CONFIRMED; file MISSING_ATTACHMENT). No matcher built from it.

No AUTO PASS was recorded for any human-assisted step; USER_ACTION would be labeled in bookmarks when live.

## Delivery bookkeeping

The requested INDEX.json, six initial evidence documents, and `CLOUD_HANDOFF_20260917.md` exist. Mechanism scenarios remain unexecuted. Commit SHAs for this test branch are recorded at push time in the git log, not as production promotion.

## Latest archived state (supersedes earlier availability snapshots)

- One-click entry `one_click_test.cmd` → `tools/one_click_test.ps1` is landed. `cmd /c one_click_test.cmd -WhatIf` exit 0 wrote Settings/argv/manifest; not live PASS.
- HWND FFI: `src/shuabao/vision/capture.py` now declares pointer-sized Win32 signatures and EnumWindowsProc `BOOL`. `pytest tests/test_capture_hwnd_ffi.py -q` → 4 passed. Live EnumWindows no longer OverflowError. Default `find_window_targets('英雄三国', role='l1')` is empty while the client is minimized; `allow_minimized=True` returns HWND 33950972 `英雄三国KK`. Preflight still ZERO INPUT and will not restore a minimized window.
- Earlier live capture exit 3 `BLOCKED_PRECONDITION` (OCR READY, then HWND OverflowError) remains archived under `entry_failure/`. That run predates the BOOL restype fix.
- Full gate: 1191.81s exit 255, only `[gate] pytest`; no suite verdict. Blocks production promotion only.
- Mechanism GT items remain NOT_RUN. Cloud planning doc: `CLOUD_HANDOFF_20260917.md`.
- Desktop screenshots that contain other sessions (`preflight/desktop_*.png`, `current_action_precheck.png`, `gt_live/001_stage_select.png`) are local-only and must not be pushed.
