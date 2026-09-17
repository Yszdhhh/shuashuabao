# GT — Pirate Starter (藏宝图) — 2026-09-17

- Starting SHA: `5b0f2436c5fe8ec2057f4266f42170edd6a95e4a`
- Branch: `test/pirate-necromancy-gt-20260917`
- Mode: `MANUAL_GT` (human-operated GT). This round **executed: false**.
- Overall: **NOT_RUN / BLOCKED at preflight**

## Preflight outcome

- First probe (`bash diagnose_lobby`): ctypes HWND `OverflowError`, exit 0. No log from this attempt — not `preflight/diagnose_lobby.log`.
- Second probe (later `eval` of a separate Python process): `ModuleNotFoundError: No module named 'cv2'`, exit 1. That traceback is `preflight/diagnose_lobby.log`. Do not conflate the two.
- Independent PowerShell process enumeration found **no KK / war3 / game window** (`preflight/window_processes.json`).
- PIL `ImageGrab` capture succeeded; the image shows the terminal desktop, not the game (`preflight/desktop_live.png` — **local only, contains other terminal sessions, must not be pushed**).
- Decision: stop further detection. No game launched, no game input sent.

## Planned GT observations (not executed this round)

1. Treasure map count observed via **F card header** (not HUD header): `0/3 → 1/3 → 2/3 → 3/3`.
2. At `3/3`, observe whether N is placed into 开进码头, whether original components disappear, and slot occupancy. Not an "enter the wharf" action.
3. Observe the subsequent card pool (海盗池). Observation only — does not imply a starter draw loop is implemented.

## NOT_OBSERVED — no data exists for any of:

- full frame, F panel, slots, OCR raw, header
- concrete-name, rarity, wood, occupancy
- before / after / combine states

## Owner-confirmed constraints applied (no retest)

- F reopen is free; refresh costs. Reopening the current drawn group does not charge again (USER_CONFIRMED).
- Full bond bar replacement rules deferred to `GT_FULL_BOND_REPLACEMENT.md`.
- Historical mechanics source: branch `docs/mechanics-contract-20260917` — cited only, not presented as new live GT.

## Result

Every step above is NOT_RUN. No capture, no OCR, no before/after pair, no combine observation exists. No AUTO PASS is claimed.
