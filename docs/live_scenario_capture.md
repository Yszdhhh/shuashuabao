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

## Solo Full-Cycle (GUI 12)

`12 单人完整循环（推荐）` is the primary single-player acceptance lane. It reads
the settings already saved by the production dashboard from
`%LOCALAPPDATA%\\ShuaBao\\user_settings.json` (or
`config/default_settings.json` when no user file exists) and immediately
writes a timestamped Harness copy below `%TEMP%\\shuabao-captures`; no manual
re-entry is required and it never writes production settings. The optional
`单人临时设置` button exposes the normal-farm stage target, skills, bonds,
optional Heirloom/Time Cave Boss, Secret Realm, and merchant values. An
override applies to the next run once; later runs return to the current
dashboard settings. Every copy is forced to `mode_id=normal_farm` and
`auto_create_room=true`, then runs the existing
`RuntimeMediator.tick()` path. The Harness has no room/stage/hero/main-line,
choice, merchant, Boss, post-game, quit, or next-round implementation.

The launcher resolves an OCR Python worker and a complete OCR model directory
from explicit environment variables, the Harness worktree, or the existing
local main worktree. It exports those values only to the invoked Harness
process, so an intentionally model-light Harness worktree does not cause a
false `model_missing` preflight failure and the production environment/package
remains unchanged. Solo preflight starts from a real KK L0 window because the
production runtime itself owns BOOT alignment and later game-HWND acquisition.

The GUI front door is intentionally limited to preflight, the single-player
full cycle, the hitch complete-cycle lane, and failure inspection/replay. The
older probes and the arbitrary-state takeover target remain available to the
CLI/replay contracts, but are no longer competing primary GUI lanes.

The run records these observation checkpoints: `PRECHECK_OK`, room request and
confirmation, stage target/start confirmation, game HWND/HUD, auto-task/four
challenge observation, L1 activity, victory/continue/post-game route, return
to baseline, and next-round request/confirmation. Random merchant or choice
panels remain `NOT_OBSERVED`; they cannot fail an otherwise valid run.

Natural E2E PASS is issued only when the first production round completed,
returned to a real L0 surface (`room_start` or `map_create_room` production
classifier), then production made a next-round request and a different, fresh
frame is classified by production as a real Stage surface, Hero setup, or HUD.
Internal phase, a valid frame, a successful click, room-start click,
stage-start click, or generic frame mutation is never enough. `MANUAL_INTERVENTION`,
production `ERROR`, or an input observed on `UNKNOWN` disqualifies the run.

Every run is written below `%TEMP%\shuabao-captures\solo_full_cycle_<timestamp>`
and includes `manifest.json`, `timeline.jsonl`, `actions.jsonl`, `summary.md`,
`screens/` (event-driven frames), `trace/trace.jsonl`, incident references,
and a read-only `config_snapshot.json`. The manifest and GUI show the harness
branch/SHA, source runtime identity, EXE path, `mode_id`, and config snapshot
hash. `SOURCE_RUNTIME` means the harness instantiates RuntimeMediator from the
checked-out source; a selected EXE is recorded as package identity only and is
not confused with the executing runtime.

## Solo arbitrary-state takeover (GUI 13)

GUI 13 offers one selector for `Stage Select`, `Mid-game HUD`,
`Skill/Bond/Treasure panel`, `Pause`, `Victory`, `Archive Panel`, `Heirloom`,
and `NPC Hub`. The selected value is operator-provided Ground Truth metadata.
The tool starts the normal production tick from `BOOT` and does not force a
phase, click a page, dismiss a dialog, or add an alternate recovery policy.
It is the acceptance lane for production Arbitrary-State Takeover work, not a
replacement FSM.
