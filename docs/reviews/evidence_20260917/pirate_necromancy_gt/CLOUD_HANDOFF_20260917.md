# Cloud handoff — pirate + necromancy GT 2026-09-17

独立测试分支进度，供云端规划下一轮实机，不是 production 合入材料。禁止 PR / merge main / rebase fix。

## Identity

| Field | Value |
|---|---|
| Starting SHA | `5b0f2436c5fe8ec2057f4266f42170edd6a95e4a` (`fix/solo-live-regression-20260915`) |
| Test branch | `test/pirate-necromancy-gt-20260917` |
| Worktree | `G:/刷刷宝/Worktrees/pirate-necromancy-gt-20260917` |
| Production worktree | not edited |
| PR | none |

Pushed commits after this handoff are listed in FINAL_STATUS. Do not treat `beaf697` as the latest if later TEST_ONLY commits exist.

## What is actually done

1. Test profile `海盗+亡灵机制GT` in `config/dashboard_test_profiles.json`, still via Dashboard → Settings → choice_policy → RuntimeMediator. No mediator `if testing` branch.
2. Minimal Settings/Dashboard wiring on this branch only, marked TEST_ONLY / PROPOSED_PRODUCTION_CHANGE (`b60835c`).
3. One-click entry: root `one_click_test.cmd` → `tools/one_click_test.ps1` → existing `live_scenario_capture.py capture --target solo_ingame_chain`. Stage `1-12` comes from Settings.stage_targets, not CLI `--target`.
4. HWND FFI type patch in `src/shuabao/vision/capture.py` (TEST_ONLY / PROPOSED_PRODUCTION_CHANGE): pointer-sized HWND signatures + EnumWindowsProc `BOOL` (not `c_bool`). Live: EnumWindows visits hundreds of windows with no OverflowError; HWND `33950972` `英雄三国KK` / `Game_x64h.exe` is found when not dropped by the minimized-size filter.
5. Evidence tree under `docs/reviews/evidence_20260917/pirate_necromancy_gt/`.

## What is not done (all mechanism GT = NOT_RUN)

| Item | Mode | Status |
|---|---|---|
| GT-1 藏宝图 0/3→3/3→开进码头 | AUTO / USER_ASSISTED | NOT_RUN |
| GT-2 五色悬赏令同档 / 无目标 | MANUAL_GT | NOT_RUN |
| GT-3 背包左键普通丹 / 悬赏令 | MANUAL_GT | NOT_RUN |
| GT-4 满卡牌栏替换窗口 B | MANUAL_GT | NOT_RUN |
| 亡灵卡头前后 progress | USER_ASSISTED | NOT_RUN |
| Victory → 秘境两帧 HUD + MAIN_LINE | AUTO | NOT_RUN |
| EX 神级吞噬丹 live crop | — | NOT_OBSERVED (USER_CONFIRMED only; attachment missing) |

Owner-confirmed rules in `OWNER_CONFIRMED_RULES.md` stay USER_CONFIRMED. Do not retest them.

## Runtime evidence already collected

- `one_click_test.cmd -WhatIf` exit 0. Isolated session Settings/manifest/argv written. Not a live PASS.
- First live capture wrapper died on PowerShell 5.1 `NativeCommandError` (stderr + `$ErrorActionPreference=Stop`). Launcher logging rewritten; not a game-logic fail.
- Second live capture, separate stdout/stderr: OCR LIVE READY, then **exit 3 `BLOCKED_PRECONDITION` ZERO INPUT**. Then-current `IsWindowVisible` HWND OverflowError. Bundle: `captures/pirate_necromancy_20260917_121327/entry_retry/solo_ingame_chain_20260917_121740_654041`. Archive: `entry_failure/`.
- Manual 2-frame client crop (HWND 33950972, 1600×900, no input): `gt_live/smoke_capture/`. Capture chain only.
- Real stage-select frame while visible: `gt_live/002_game_window.png` (1-1 selected, 1-12 present).
- Full `release_gate.py --json`: ~1192s, exit 255, output only `[gate] pytest ...`. No suite PASS/FAIL. Does not block this test-branch push; blocks production promotion.
- HWND regression tests: `python -m pytest tests/test_capture_hwnd_ffi.py -q` → 4 passed.
- After BOOL patch, default `find_window_targets('英雄三国', role='l1')` is `[]` while the client is **minimized** (`IsIconic=1`, rect `-32000`). `allow_minimized=True` returns HWND 33950972. Preflight of `solo_ingame_chain` does not restore windows (zero-input). Operator must leave the game **visible** before one-click.

## Profile actually prepared

From WhatIf session (example `captures/pirate_necromancy_20260917_121905`):

- `stage_targets=['1-12']`, `cycle_num=1`, `auto_secret_realm=true`, `auto_devour_dan=false`
- `bond_advanced_unlock_s=60.0`, `bonds=['经济']`, `bond_must_take=['藏宝图(三)']`
- `cards=['zhufu','jj','藏宝图(三)','海盗','亡灵']`
- Skills inherited read-only from operator `user_settings.json`
- Pirate first advanced pack, Necromancy second; production defaults unchanged

## Recommended next test (cloud plan)

Do not invent a second pirate loop. Use the existing one-click path.

1. Operator: restore/unminimize `英雄三国KK` so the stage-select (or KK map / create-room / room) is **visible**. Record as USER_ACTION.
2. Double-click `G:\刷刷宝\Worktrees\pirate-necromancy-gt-20260917\one_click_test.cmd`. Allow UAC. Do not use the old production Live shortcut.
3. Confirm the new session `captures/pirate_necromancy_<stamp>/` binds `--production-source-root/sha` to this branch HEAD, `--settings` to the session file, `--target solo_ingame_chain`.
4. If preflight still BLOCKED_PRECONDITION with ZERO INPUT: dump whether EnumWindows now lists the visible client; do not click through a missing surface.
5. If Runtime takes over: AUTO until a panel the production policy cannot close (满栏替换 / 背包丹 / 悬赏令). Bookmark `m` + USER_ACTION. Never write AUTO PASS for those.
6. Priority once in F: 藏宝图 0/3→3/3→开进码头 (GT-1). Then natural 悬赏令 / 满栏 / 亡灵 / 战后秘境.
7. Keep `auto_devour_dan=false`. Ordinary pill remains MANUAL_GT.

Stop after one honest live session + evidence push. Do not start production replacement automation.

## Do not

- Merge/rebase onto `fix/solo-live-regression-20260915`
- Change Harness baseline / scheduler / QUIT / room-form / HUD gate on this branch
- Point the production desktop shortcut at this worktree
- Treat OCR READY, click success, or `-WhatIf` as mechanism PASS
