# Local Architecture Reality Audit (2026-09-10)

## 1. Executive Summary & Inventory Topology

On 2026-09-10, an exhaustive, multi-dimensional audit of the local development environment, active Git worktrees, desktop execution chains, frozen runtime artifacts, and competitor decomposition assets was conducted.

### 1.1 Git Worktrees & Working State

Canonical repository: `G:\刷刷宝\GameScript-Local`

| Worktree Path | Branch | Current HEAD | Working Tree Status | Role / Identity |
| :--- | :--- | :--- | :--- | :--- |
| `G:\刷刷宝\GameScript-Local` | `refactor/stability-s0-20260908` | `3e9c50a` (Clean + untracked test prompt) | **CANONICAL FORMAL REPO** / Primary source baseline |
| `G:\刷刷宝\Worktrees\trial-merge-p0-ff` | `trial-merge` | `2d4090b` (Clean) | Historical trial-merge candidate |
| `G:\刷刷宝\Worktrees\GameScript-Core02-Core03-Integration-20260816` | `integration/core02-core03-20260816` | `5325d38` (Clean) | Historical integration line |
| `G:\刷刷宝\Worktrees\GameScript-TrialMerge-P0-FeatureFreeze` | `trial-merge-p0-feature-freeze` | `4329243` (Clean) | Feature freeze branch |
| `G:\刷刷宝\Worktrees\GameScript-P0-FeatureFreeze` | `p0-feature-freeze` | `6290bb6` (Clean) | Frozen baseline |
| `G:\刷刷宝\Worktrees\GameScript-S0-RegressionAudit` | `s0-regression-audit` | `6df5c68` (Clean) | S0 Regression audit branch |

**Findings**:
- No parallel test agent is currently running dirty worktrees in the background.
- Primary production line is `refactor/stability-s0-20260908` at commit `3e9c50a` ("test: fix stale kick-detect and platform modal test references at HEAD").

---

## 2. Desktop Execution Chain & Runtime Identity Audit

### 2.1 The Execution Chain

```
Desktop Shortcut: "刷刷宝.lnk"
  Target: C:\Users\10639\AppData\Local\ShuaBao\app-0.3-dev-b15da05f4fd7\ShuaBao.exe
  Working Directory: C:\Users\10639\AppData\Local\ShuaBao\app-0.3-dev-b15da05f4fd7
  Icon: C:\Users\10639\AppData\Local\ShuaBao\app-0.3-dev-b15da05f4fd7\ShuaBao.exe,0

Desktop Shortcut: "刷刷宝-最新版.lnk"
  Target: powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File C:\Users\10639\AppData\Local\ShuaBao\ShuaBaoLauncher.ps1
  Working Directory: C:\Users\10639\AppData\Local\ShuaBao
```

### 2.2 The "Running Old Version" Root Cause Analysis

A major pain point reported historically is: *"The developer fixed the code, but when the user clicks the desktop shortcut, it still runs an old version."*

Our physical filesystem inspection revealed the exact mechanism:
1. **Squirrel / Electron-style Multi-Folder Layout**:
   `C:\Users\10639\AppData\Local\ShuaBao\` contains:
   - `app-0.3-dev-0128342e0ebd/` (Source SHA `0128342e0ebd`, built 2026-09-06T17:16:14)
   - `app-0.3-dev-b15da05f4fd7/` (Source SHA `b15da05f4fd7`, built 2026-09-07T06:29:14)
   - `current.json` pointing to `app-0.3-dev-b15da05f4fd7`
   - `ShuaBaoLauncher.ps1`
2. **Hardcoded Static Target in Primary Shortcut**:
   The primary shortcut `C:\Users\10639\Desktop\刷刷宝.lnk` is **hard-pinned** directly to `C:\Users\10639\AppData\Local\ShuaBao\app-0.3-dev-b15da05f4fd7\ShuaBao.exe`.
   Even when a newer package is built into a new folder `app-0.3-dev-<new_sha>/`, clicking `刷刷宝.lnk` will **forever launch `app-0.3-dev-b15da05f4fd7`** unless the shortcut is overwritten or updated.
3. **Secondary Dynamic Shortcut is Non-Default**:
   `刷刷宝-最新版.lnk` reads `current.json`, but regular users click the prominent `刷刷宝.lnk`.
4. **Source vs Package Divergence**:
   Current Git HEAD is `3e9c50a` (2026-09-09). The installed package on the desktop is `b15da05` (2026-09-07). All work done between `b15da05` and `3e9c50a` (including G0 closure, hitch refactors, and test fixes) is **not present in the running desktop executable**.

---

## 3. Runtime Authority Audit

### 3.1 Input Authority Map

We audited all invocations of keyboard and mouse simulation across `src/shuabao`:

1. **Unified Win32 Wrapper**:
   `src/shuabao/input/keyboard_mouse.py` encapsulates `ctypes.windll.user32.SendInput` with 64-bit union alignment (`MOUSEINPUT` 32 bytes + padding to 40 bytes).
2. **Primary Consumers**:
   - `src/shuabao/loop_action.py`: `LoopAction` acts as the primary action executor for game ticks.
   - `src/shuabao/jobs/auto_job.py`: Directly calls `click as _click, press_key as _press_key`.
   - `src/shuabao/interaction_surface.py`: Uses `ActionIntent` and `InteractionSurface` priority gates.
3. **Safety Violations / Direct Bypass**:
   - `auto_job.py` imports functions directly from `keyboard_mouse.py`, bypassing arbitration layers.
   - In several places, coordinates are computed relative to screen coordinates rather than verified client-rect coordinates, creating vulnerability to window shifts.

### 3.2 Progression Authority Map

Who advances the high-level business state machine?
- **Exclusive Authority**: `src/shuabao/mediator.py` (`Mediator.set_phase(Phase)`).
- **Phases Controlled**:
  `BOOT` → `LOGIN` → `LOBBY_IDLE` → `ROOM_SEARCH` → `ROOM_JOINED` → `ROOM_STARTING` → `LOADING` → `IN_GAME` → `POST_GAME` → `LOBBY_RETURN`
- **Finding**: Progression is centralized in `Mediator`, which is architecturally clean. However, the progression triggers rely heavily on visual template matching without temporal heartbeat verification.

### 3.3 Recovery Ownership Map

Who initiates recovery when an error occurs?
- **Lobby & Hitch Recovery**: `src/shuabao/lobby_hitch.py` and `Mediator._hitch_pressure_core_failed`.
- **In-Game Modal Recovery**: `src/shuabao/interaction_surface.py` arbitrates `POPUP_CONFIRM`, `REVIVE`, `SURRENDER`.
- **Watchdog Recovery**: `Mediator` timer-based fallback.
- **Duplication Hazard**:
  Both `Mediator` and `lobby_hitch.py` attempt to handle "room list missing" or "kick event". If `lobby_hitch` initiates room search while `Mediator` detects disconnect modal, their action queues can interleave and create race conditions.
