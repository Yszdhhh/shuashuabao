# Live Scenario Capture → Frozen Replay

`tools/live_scenario_capture.py` is a thin adapter over the existing
`ReplayCaseLoader / FakeClock / FakeInputExecutor / ScenarioRunner`. Normal
capture calls `Mediator.tick()`; a conditional probe calls one named existing
production entry. A blocked target calls no production handler at all. Frames
are event-driven only: first observation, state change, action before/after,
bookmark, and blocked/break evidence.

```powershell
python tools/live_scenario_capture.py readiness
python tools/live_scenario_capture.py contracts
python tools/live_scenario_capture.py runbook --target black_merchant
```

## Readiness semantics

`HARNESS_READINESS=READY` means only that this adapter can capture evidence,
write bookmarks/failure summaries, convert a bundle, and run the existing
offline replay path. It never means production behavior is wired or allowed.

| Target | Harness readiness | Production readiness | Current live scope |
| --- | --- | --- | --- |
| `black_merchant` | READY | CONDITIONAL | One integrated encounter: an empty strip refreshes first, then the existing handler can take swallow pill / wood; refresh alone is not PASS. |
| `inventory_item` | READY | CONDITIONAL | Swallow pill only, using the existing `WAIT_DEVOUR_DAN` verifier. |
| `boss_challenge` | READY | CONDITIONAL | One existing `Mediator.tick()` bundle for `tqtz → configured Boss → post-game` evidence; time-cave/heirloom boundaries remain Ground Truth-only. A narrow configured-Boss probe is still available from an already-open list. |
| `time_cave` | READY | BLOCKED | Postgame time-cave NPC is not wired; complete human-chain Ground Truth only. |
| `heirloom` | READY | BLOCKED | Boss selection is not wired; current production only verifies safe close; Ground Truth only. |
| `secret_realm` | READY | CONDITIONAL | Existing `OpenGreatRift` / `ConfirmGreatRift` only; success requires real HUD plus `_secret_realm_active=True`. |

Changing a `BLOCKED` row requires a separate production design. The capture
tool must not make it green by adding temporary business logic.

## Hard live-input preflight

Every `--live-input` command records and requires:

- tested source SHA and a clean source worktree;
- the actual `ShuaBao.exe` path and SHA-256;
- its adjacent `build_identity.json`, whose source SHA, build ID, clean-tree
  attestation, and EXE hash must match;
- settings snapshot, OCR bootstrap health, HWND/title/size, and live-lane
  single-instance ownership.

`build_release.ps1` writes `build_identity.json` beside `ShuaBao.exe`. If the
identity differs, OCR bootstrap is unhealthy, the game window is unavailable,
or the live lane is busy, the command writes a `BLOCKED_PRECHECK` bundle and
returns without dispatching a business handler or a game input.

For a conditional live probe, replace the EXE path below with the deployed
build:

```powershell
python tools/live_scenario_capture.py probe --target inventory_item `
  --out C:/tmp/shuabao-captures --duration 15 `
  --automation-exe C:/path/to/ShuaBao.exe `
  --live-input --confirm-live-input --continue-after-failure --generate
```

For a production-blocked target, omit `--live-input`; the probe is forced to
Ground Truth / zero-input mode:

```powershell
python tools/live_scenario_capture.py probe --target time_cave `
  --out C:/tmp/shuabao-captures --duration 25 --continue-after-failure --generate
```

## Target contracts

The machine-readable contract is `TARGET_CONTRACTS` plus
`TARGET_PRODUCTION_FACTS` in
[`tools/live_scenario_capture.py`](../tools/live_scenario_capture.py). Print a
contract with `contracts --target <target>`.

- `black_merchant`: `DETECT → SCAN → REFRESH → VERIFY_REFRESH → TARGET_FOUND
  → TAKE → VERIFY_TAKE → EXIT`. An empty strip is detected through the
  refresh control and refreshed before the same encounter is scanned.
  `REFRESH_PASS` proves only refresh mutation; `LIVE_PROBE_PASS` requires a
  recognized target purchase and its existing business postcondition.
- `inventory_item`: `DETECT_SLOT → IDENTIFY → USE → VERIFY_CONSUMED →
  VERIFY_NO_REPEAT`. Only the swallow-pill route can pass.
- `boss_challenge`: the integrated capture uses the existing
  `Mediator.tick()` route (`tqtz → configured Boss → transition → post-game`);
  its local diagnostic stages remain `ENTRY_VISIBLE → CLICK → TRANSITION →
  DESTINATION_CONFIRMED`, and the same bundle records the existing safe-close
  `heirloom` boundary plus the zero-input `time_cave` Ground Truth boundary.
  A click result alone never passes. The already-open-list `probe` remains a
  narrow `_maybe_challenge_configured_boss()` check.
- `time_cave` / `heirloom`: `POSTGAME_DETECT → ENTRY_VISIBLE →
  CLICK/REQUEST → CONFIRM → TRANSITION → DESTINATION_CONFIRMED` are retained
  as diagnostic labels for human Ground Truth. No production input is sent and
  no Live Probe PASS is possible this checkpoint.
- `secret_realm`: `POSTGAME_DETECT → ENTRY_VISIBLE → REQUEST → CONFIRM →
  TRANSITION → DESTINATION_CONFIRMED`. The probe is test-side restricted to
  `OpenGreatRift` / `ConfirmGreatRift`; any unrelated `_tick_main_line()`
  action is blocked before dispatch.

The secret-realm probe seeds only existing postgame state required by
`_tick_main_line`; it does not reproduce request, confirmation, or transition
logic. Probe success is local evidence, never a full postgame Natural E2E.

## Bookmarks, failure evidence, and replay

During a running capture/probe:

- `p`: human evidence bookmark only; it never declares `PROBE PASS`.
- `f`: save `FAIL` evidence and a failure summary.
- `m`: record `MANUAL_INTERVENTION`; later material stays Ground Truth eligible
  but the bundle can never become a Natural E2E PASS.

Formal probe pass is only `AUTO_POSTCONDITION_PASS` from the target's recorded
business postcondition. Timeout therefore ignores a `p` bookmark and fails
unless that automatic postcondition occurred.

Every `FAIL`, `BLOCKED`, and `BLOCKED_PRECHECK` prints:

```text
TARGET: black_merchant
FAILURE_CLASS_HINT: L8_TEST_EVIDENCE
BUNDLE_PATH: C:\tmp\shuabao-captures\black_merchant_...
BOOKMARK_ID: b0000
REPLAY_COMMAND: python tools/live_scenario_capture.py reproduce --bundle "C:\tmp\shuabao-captures\black_merchant_..."
RELEVANT_FILES:
- ...\manifest.json
- ...\trace.jsonl
- ...\bookmarks\b0000.json
- ...\failures\b0000_blocked_precheck.json
```

A captured bundle converts to the existing schema-v1 replay cases and runs its
baseline plus `click_rejected`, `postcondition_missing`, `frame_unchanged`, and
`timeout` variants without altering original screenshots:

```powershell
python tools/live_scenario_capture.py reproduce `
  --bundle C:/tmp/shuabao-captures/black_merchant_YYYYMMDD_HHMMSS_ffffff
```

Frozen replay is offline regression evidence only. Formal Live PASS remains a
later uninterrupted Natural E2E on the real game.
