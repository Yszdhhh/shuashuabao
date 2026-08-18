# ShuaBao Stability Foundation V1 - Comprehensive Audit Report

## 1. Executive Summary
- **Target Branch**: `stabilize/runtime-foundation-v1-20260819`
- **Baseline Commit**: `abf3d35` (plus choice-panel liveness & state-alignment history)
- **Automated Gate Result**: **4/4 PASS** (pytest 1004 passed, 2 xfailed, 4 skipped; frozen replay 7/7 pass; templates 132/132 ok; contract 68/1 pass)

## 2. Core Stability Invariants Verified
1. **Action Lifecycle Closure & Mutation Confirmation**:
   - Implemented `ActionLifecycle` states: `OBSERVED -> ACTION_AUTHORIZED -> INPUT_SENT -> VERIFYING -> CONFIRMED / UNCONFIRMED / RECOVERING`.
   - Actions (card select, buy, use, challenge, etc.) are only committed to acquired state after visual mutation verification.
2. **Panel Episode Liveness & Hard Deadlines**:
   - Formalized `panel_episode_id`, `first_seen_at`, `last_progress_at`, `hard_deadline_s` (default 15.0s, bounded).
   - Zero-input deadlock prevented when OCR or matching returns None.
3. **Silent Background OCR Productization**:
   - Enforced `CREATE_NO_WINDOW` and `STARTUPINFO.wShowWindow = SW_HIDE` on Windows.
   - Zero command-prompt/PowerShell popups during launch, ping, inference, or restart.
   - Implemented True READY health check (process alive, protocol handshake, SHA256 model verification, warmup inference).
   - Bounded restart state machine (max 3 restarts, exponential backoff, cooldown).
   - Path resolution supports development checkout and packaged runtime without hardcoded machine paths.
4. **Nomenclature & Namespace Migration**:
   - Internal paths, temp files, and environment variables migrated to `ShuaBao` / `shuashuabao`.
   - External legacy C# upstream path `%APPDATA%\GameScript\Settings\Settings.json` cleanly isolated under `LEGACY_UPSTREAM_SETTINGS_PATH`.
5. **Window Focus & Network Recovery Foundation**:
   - Window loss detection suspends inputs immediately and invalidates stale frame coordinates.
   - `reacquire_target_window` brings target window to foreground with verification.
   - Network recovery FSM enforces bounded 120.0s hard timeout with progress checks and fail-closed termination.

## 3. Security & Boundary Verification
- Subprocess executions are restricted to verified local virtual environments with no shell injection surfaces.
- Logging omits sensitive data such as room passwords.
- Privilege elevation and UIPI requirements documented and safeguarded.
