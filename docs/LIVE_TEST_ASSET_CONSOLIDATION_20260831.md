# Live 实机测试资产收敛（2026-08-31）

## Scope and evidence rules

This inventory was made from the authoritative worktree, its committed fixtures and
templates, and the original bundles under
`C:\Users\10639\AppData\Local\Temp\shuabao-captures`.  A capture is real evidence
only when its manifest and saved frames prove the stated postcondition.  A successful
SendInput result, a bookmark, a frame transition, or a synthetic replay alone is not a
business PASS.

Classifications used here:

- **GOLDEN**: current-production real bundle with authoritative postcondition.
- **VALID BUT OLD**: real evidence for a historical production version; it remains
  valuable for replay/regression but cannot certify the current version.
- **SUPERSEDED**: evidence whose diagnosed implementation fault has a later, focused
  production correction; retain it for regression.
- **FAIL REGRESSION**: real failure to preserve as a replay candidate.
- **GROUND_TRUTH_ONLY**: real observation that deliberately does not authorize
  production input or readiness.
- **UNKNOWN**: insufficient frame, manifest, or postcondition evidence.

## Feature inventory

| Feature | Production implementation | Existing real evidence | Validated facts | Test-only duplication | Missing Ground Truth | Next required live test |
|---|---|---|---|---|---|---|
| Black Merchant | `Mediator._maybe_black_merchant`, `MerchantScanner`, fixed five-slot centres, and `_normalize_merchant_discount`; harness composes existing merchant/inventory/artifact handlers. | `black_merchant_20260830_014111_091497` (吞噬丹 postcondition), `...023440_018574` (吞噬丹使用、木材), `...024611_475051` (木箱误命中), `...233034_305060` (吞噬丹使用). All predate the latest slot/OCR correction. | Five fixed slots; refresh is not purchase PASS; known real aliases `15折→5`, `12折→2`, `A2→2`; `2S` must remain unknown. | Bundles, generated cases and FakeInput/FakeClock are evidence only. No merchant detector/FSM is copied into the harness. | Current-SHA samples for canonical 2/5/8, wood and 吞噬丹; post-purchase item-state frame for every required route. | On a matching build: collect one natural sample each for 2折、5折、8折、木材、吞噬丹; require correct slot and actual item state; record absent RNG outcomes as `MISSING_REAL_SAMPLE`. |
| Bag devour pill | Existing `_maybe_use_inventory_item` route, invoked after merchant acquisition. | `black_merchant_20260830_014111_091497`, `...023440_018574`, and `...233034_305060`. | Merchant purchase and bag consumption are separate; consumption still requires the existing bond/postcondition logic. | Replay cases exercise the production handler through the existing mediator. | Current-SHA after-frame proving bag appearance then consumption. | Re-run only after a black-merchant pill acquisition; retain one bundle spanning both postconditions. |
| Hero card | Existing inventory handler and hero-card postcondition contract. | No qualifying current bundle. | Probe must wait for the real hero-choice page; obtaining the card is not equivalent to consuming it. | Harness only maps the existing action reason to its postcondition. | Real card, selection-page anchor and result frame. | Collect a targeted `inventory_item` bundle; otherwise remain `MISSING_REAL_SAMPLE`. |
| Boss / eight archive cards | Existing post-game route and archive challenge flow in `Mediator`; boss catalogue/templates under `assets/Images/boss`. | `boss_challenge_20260831_001844_095557` recorded all eight archive actions before the later heirloom fault. Several earlier `boss_challenge_*` bundles are environment/preflight failures. | Existing archive flow can proceed through all eight configured cards; archive click alone is not final-chain PASS. | Frozen replay is a ScenarioRunner consumer of production mediator behavior. | Current build full route with final postcondition. | Only after targeted module checks; run long-chain Boss capture last. |
| Heirloom | Existing `_maybe_challenge_configured_boss`, `_heirloom_boss_result_visible`, current `cjb_boss` setting and inherited boss templates. | `boss_challenge_20260831_001844_095557` is a **FAIL REGRESSION**: configured boss was not clicked because combat red VFX appeared result-like. `heirloom_20260831_005452_972761` has one frame and no authoritative result (**UNKNOWN**). | `2bbc709` adds a bounded red connected-region guard. A valid result requires selected target, actual challenge HUD, Boss-active history and lawful completion—not click success. | Regression tests/frozen frames must call production result detection and state, not a parallel detector. | Three independent current-build success bundles, including one list-scroll target, with HUD and final postcondition. | Menu 7, one run at a time: target/scroll → input → real Boss HUD → active → real completion. Do not use `m`; preserve all non-PASS bundles. |
| Secret Realm | Existing post-game NPC/confirm/HUD route and `_secret_realm_active` in `Mediator`; menu 5 invokes the existing handler. | `secret_realm_20260831_005902_990468` is `BLOCKED_PRECHECK` before handler dispatch; no qualifying success bundle. | PASS requires `_is_in_game_hud()` plus `_secret_realm_active=True`; NPC/confirm/click/frame-change are not PASS. | The probe bootstraps only existing production state; capture/replay is evidence. | Three natural completed entries with HUD state. | First clear Harness identity block, then three isolated menu-5 runs; convert any failure into a replay case before further live changes. |
| Time Cave | Production entry intentionally remains blocked; menu 6 is zero-input Ground Truth capture. | No complete Ground Truth chain in the current asset root. | Current `PRODUCTION_READINESS=BLOCKED`; no automatic interaction is authorized. | Ground Truth bundle is evidence, not a test FSM. | NPC/page/confirm/loading/HUD sequence with before/after frames, anchors, ROI/OCR and click data. | Menu 6 only: record the complete human-driven chain; keep production readiness BLOCKED until it exists. |

## Bundle status and replay retention

| Asset / range | Classification | Reason and disposition |
|---|---|---|
| `black_merchant_20260829_224812_222785` | FAIL REGRESSION | Preflight block; retain for L8 evidence. |
| `black_merchant_20260829_233547_894387` through `...001815_571970` | FAIL REGRESSION | Early real failures; retain raw frames and failure summaries. |
| `black_merchant_20260830_010555_176097` | SUPERSEDED | Product-strip pixel fingerprint prevented actions; regression candidate for the later five-slot occupancy logic. |
| `black_merchant_20260830_014111_091497` | VALID BUT OLD | Real devour-pill route success, but before later refresh/slot fixes. |
| `black_merchant_20260830_015744_427554` | SUPERSEDED | Refresh coordinate landed outside the intended control; retain to prevent regression. |
| `black_merchant_20260830_023440_018574` | VALID BUT OLD | Real pill use and wood observation; reroll cap was later corrected. |
| `black_merchant_20260830_024611_475051` | FAIL REGRESSION | Wood template/adjacent-slot risk and stale refresh state; preserve for slot mapping replay. |
| `black_merchant_20260830_111130_217792` through `...233034_305060` | VALID BUT OLD | Long-run and pill-chain observations, all before the final `41e4681` slot/OCR correction. |
| `boss_challenge_20260830_135632_119010` through early one-frame captures | FAIL REGRESSION | L0/L8 capture/preflight evidence, not business evidence. |
| `boss_challenge_20260831_001844_095557` | FAIL REGRESSION | Authoritative evidence for premature heirloom-result detection; preserve for the `2bbc709` regression test path. |
| `boss_challenge_20260831_005535_200618` | FAIL REGRESSION | Archive close attempts exhausted after a card-panel false context; inspect/reproduce before changing archive logic. |
| `heirloom_20260831_005452_972761` | UNKNOWN | One frame and no result/postcondition; not a success or failure diagnosis. |
| `secret_realm_20260831_005902_990468` | FAIL REGRESSION | Exact source/EXE identity mismatch stopped input before the production handler; L8 only. |
| `fixtures/replay/*`, `fixtures/baselines/replay_frozen/*` | KEEP_AS_REGRESSION | Committed frozen test evidence; it must continue to invoke the production mediator. |
| Templates in `assets/Images/*`, scenes and boss catalogue | KEEP_AS_PRODUCTION_FACTS | These are production inputs; only facts supported by real evidence should be added. |

## P0 Harness findings

The immediately reproducible blocker is a provenance mismatch, not a target handler
failure.  The branch HEAD is `b297332` (documentation handoff), while
`dist/ShuaBao/build_identity.json` identifies the built EXE as `2bbc709`.  The current
identity checker correctly requires an exact source SHA and therefore records
`BLOCKED_PRECHECK` before it creates a live input executor or calls a target handler.
The `secret_realm_20260831_005902_990468` manifest proves this fail-closed behavior.

Resolution must keep the exact identity rule: rebuild/package the specified worktree at
the current committed SHA (or otherwise restore a branch/EXE pair with the same SHA).
Do not weaken the preflight merely because the delta is documentation; doing so would
make the source/executable fact ambiguous for later live bundles.

The persisted prior P0 lifecycle evidence is incomplete: the capture root contains
individual failures and no recorded five-run, start/probe/stop/menu-return matrix.
Accordingly, **P0 five-run acceptance is `MISSING_REAL_SAMPLE`**, not PASS.

### This run — 2026-08-31 02:41 CST

The worktree was packaged locally without deployment after the inventory commit.  Its
source SHA `0e1e66eaa98e599c7bc34043308209da143e4591`, the packaged EXE hash, and
`dist/ShuaBao/build_identity.json` were all verified by the unchanged exact-identity
preflight.  `readiness` also passed its existing replay self-check for all six targets.

One isolated live-input `heirloom` probe then produced
`C:\Users\10639\AppData\Local\Temp\shuabao-captures\heirloom_20260831_024122_274276`.
It is **FAIL REGRESSION / L8_TEST_EVIDENCE**, not a production-chain result: OCR
bootstrap was healthy and EXE identity was READY, but no window matching `英雄三国`
existed.  Preflight stopped before lock acquisition, target-handler dispatch, or any
game input.  The bundle has no frame/events, so the existing `reproduce` command
correctly reports that no replay case can be generated.  Keep the manifest and failure
summary as environment evidence; a blank capture must not be converted into synthetic
game evidence.

### Full pytest stability follow-up — 2026-08-31

Before any new repository change, the local package was reconfirmed against
`4b07e37b8c83fc4d658cf33181c50838cccd4282`: Git HEAD and the
`build_identity.json` source SHA were identical, and the EXE SHA-256 matched its
sidecar.  This closes the earlier identity evidence gap for that commit.

The full-suite Windows fast-fail was then reduced to two independent Qt test-lifecycle
faults.  First, `test_desktop_main_preserves_theme_loaded_by_real_window` relied on the
default shell selection while patching only the native-window objects.  The default
WebConfigShell could therefore create real Qt objects outside the fake application,
and later garbage collection could access-violate.  The test now explicitly selects
`SHUABAO_SHELL=native`.  Second, two dashboard modules created a process-global
`QCoreApplication`; a later desktop test could not upgrade that singleton into the
`QApplication` required by widgets.  Those shared fixtures now create an offscreen
`QApplication` from the outset.  These are test-only corrections; no production FSM,
detector, fallback, or baseline changed.

After the correction, the previously crashing module boundary completed, and the full
command `python -X faulthandler -m pytest tests -q --tb=short` reached 100% without a
native-process crash: **31 failed, 1063 passed, 5 skipped, 2 xfailed, 207 subtests
passed in 193.35s**.  Native-process stability is therefore **PASS**, but the full
pytest acceptance state remains **FAIL / OPEN**.  The remaining reproducible assertion
failures are tracked separately; no common root cause is inferred:

| Failure area | Count | Status |
|---|---:|---|
| Atlas/catalog projection | 7 | OPEN; includes canonical-name and knowledge/bond expectations. |
| Desktop settings/policy projection | 2 | OPEN. |
| Pause overlay | 1 | OPEN. |
| Habit preference | 1 | OPEN. |
| Lobby detectors | 2 | OPEN. |
| P0A create-room gate | 4 | OPEN. |
| P1A1 main-line controls | 7 | OPEN. |
| P1A2 challenge controls | 1 | OPEN. |
| Scenario replay | 1 | OPEN. |
| Skill metadata presets | 1 | OPEN. |
| Temporal same-room loop | 1 | OPEN. |
| Ticket archaeology | 1 | OPEN. |
| Trace JSONL redaction | 1 | OPEN. |
| UI scale fallback | 1 | OPEN. |

The focused regression across both dashboard modules and the two relevant desktop
tests reports **55 passed in 3.11s**.  P0 five-run lifecycle acceptance remains
`MISSING_REAL_SAMPLE`; no long-chain live run is authorized by this test-only result.

### Dashboard wiring and Boss fallback follow-up — 2026-08-31

The formal dashboard wiring is present: merchant controls, `cjb_boss`, `sgzx_boss`
and `auto_secret_realm` persist into the same settings consumed by the production
`Mediator`.  The Live menu remains a thin evidence harness around those production
handlers and does not own a second feature FSM.  This establishes integration, not a
current-build end-to-end PASS.

The default Web dashboard previously coupled stage selection to hard-coded Boss and
heirloom recommendations.  Chapter/stage changes could therefore overwrite explicit
choices, and settings restoration could render a stale recommended label.  The Web
shell now changes only `stage_targets`; persisted Boss/heirloom values are applied
before their labels are rendered.  Production selection is also page-scoped:
`ARCHIVE_PANEL` consumes only `sgzx_boss`, while `HEIRLOOM_DIALOG` consumes only
`cjb_boss`.

The existing production Boss handler now implements the requested bounded default:
the explicit target remains first priority; after that target is absent through the
existing three classified-list scrolls, it scans the production templates in
descending numeric order and clicks the highest-numbered recognized card still
visible in the classified ROI.  An unclassified page, `UNKNOWN`, or zero template
hits still produces zero input.  The click continues to use `BossConfigured` and the
existing business postcondition—input success alone is not PASS.

Existing real material is sufficient for safe offline optimization of this mechanism:

| Material | Result from production helper |
|---|---|
| `fixtures/reborn_wow/endgame/archive_challenge_panel.png` | `12卡尔加`, score 0.844816 |
| `fixtures/reborn_wow/endgame/heirloom_challenge_bosses.png` | `03洛卡纳哈`, score 0.806868 |
| `boss_challenge_20260831_005535_200618/frames/f0006_action_before.png` | `12战争之王`, score 0.762833 |

These are offline recognition results over real frames, not new live-chain PASS
claims.  The current status remains: merchant/heirloom/Boss have historical partial
real success suitable for regression; Secret Realm lacks qualifying HUD state; the
Time Cave Boss list has real interaction material but its complete NPC-entry Ground
Truth remains `BLOCKED`; and the current-SHA long-chain postconditions are not closed.

Focused Boss/challenge regression is **56 passed, 2 subtests passed**.  The curated
release gate remains **4/4 PASS**.  A new full-suite run reached 100% without native
fast-fail and reported **31 failed, 1068 passed, 5 skipped, 2 xfailed, 207 subtests
passed in 206.89s**.  Thus the previous native-process crash/exit blocker is cleared,
while the unchanged set of ordinary assertion failures remains `FAIL / OPEN`.

### Final offline closure addendum — 2026-08-31 11:52 CST

This addendum supersedes the earlier provisional counts above.  It records the
follow-up after the dashboard/Boss changes and the OCR asset migration; it does not
grant any live target a business PASS.

#### Root Cause Summary

- The prior Windows `0xC0000409` was isolated to Qt test lifecycle/state setup.  The
  corrected fixtures now reach 100% and the process exits normally.
- A false release-gate `0 passed` observation came from invoking the runtime `.venv`,
  which intentionally has no pytest module.  The repository test interpreter is the
  Python 3.11 environment used for all final results; no baseline was changed.
- The remaining four assertions were a real data-contract mismatch: runtime OCR
  names use current `奥术*`, while D0 human-reviewed truth still contains historical
  `奥数*`.  Three `_legacy_truth_only` audit entries preserve that evidence, and the
  production lookup explicitly skips them.

#### Asset Consolidation

The exact `fixtures/ex_finals_20260814` real screenshots were restored from the
matching committed/archive copies and indexed.  Existing merchant, Boss, heirloom,
and stage fixtures remain regression inputs.  No synthetic frame was added and no
historical bundle was relabeled as a current production PASS.

#### Feature Matrix / current acceptance

| Chain | Formal dashboard and production state | Current acceptance |
|---|---|---|
| Black Merchant | Settings, fixed slot mapping, discount aliases, purchase/use handlers are wired into the formal `Mediator`. | `VALID BUT OLD / MISSING_REAL_SAMPLE`: current-SHA 2/5/8, wood, and 吞噬丹 postconditions still need real bundles. |
| Heirloom | `cjb_boss` is persisted and page-scoped; explicit target is tried first, then bounded scroll and highest-numbered recognized fallback on a classified page. | `CONDITIONAL`: historical partial evidence only; three current-build HUD→active→completion successes, including one scroll, are missing. |
| Time Cave | `sgzx_boss` is persisted and page-scoped; unavailable target fallback is bounded and fail-closed. | Complete NPC-entry Ground Truth remains `BLOCKED`; no production interaction is authorized. |
| Secret Realm | `auto_secret_realm` is on the same production mediator path and requires real HUD plus `_secret_realm_active=True`. | `MISSING_REAL_SAMPLE`: no qualifying entry bundle. |
| Boss long chain / eight cards | Existing production handler and archive sequence remain intact; no second FSM was introduced. | Historical clicks exist, but current-SHA final postcondition is not closed. |
| Dashboard stage/Boss selection | Chapter/stage changes no longer rewrite `cjb_boss`/`sgzx_boss`; selected values render as selected. | Offline wiring PASS; live confirmation still pending. |

Thus existing real material can be used directly for offline optimization of trigger,
condition, ending, stability, and accuracy logic.  It does **not** justify saying that
all chains except Secret Realm are already current-build, formally runnable live.

#### Real live evidence

No live-input action was executed in this follow-up.  The retained real bundles are
historical/partial: black-merchant purchase and pill-use runs, the eight archive-card
run, and the heirloom regression/one-frame captures.  The latest Secret Realm bundle
is a fail-closed preflight artifact without game frames; it is not a Secret Realm
entry.  `disconnect_modal_missing` likewise remains a real-material gap.

#### Failure Matrix

| Failure / gap | Status | Evidence-safe disposition |
|---|---|---|
| Full-suite native crash / hard exit | RESOLVED OFFLINE | `python -m pytest tests -q` reached 100%; keep Qt lifecycle regression tests. |
| D0/runtime `奥数` ↔ `奥术` truth mismatch | RESOLVED OFFLINE | Audit-only compatibility entries; runtime lookup remains current-name only. |
| `disconnect_modal_missing` | BLOCKED | Missing real disconnect-modal frames; do not synthesize or update baseline. |
| P0 five-run lifecycle | MISSING_REAL_SAMPLE | Need 5 natural start→probe→stop/F12→bundle→menu-return runs. |
| Black Merchant current canonical 2/5/8/wood/pill | MISSING_REAL_SAMPLE | Re-run on identity-matched build with item-state postconditions. |
| Heirloom three successes / scroll | MISSING_REAL_SAMPLE | Require real HUD, active state, and completion postconditions. |
| Secret Realm entry | MISSING_REAL_SAMPLE | Require real HUD and `_secret_realm_active=True`. |
| Time Cave NPC entry | BLOCKED | Ground Truth only; production remains zero-input. |

#### Tests and Git

- Full: `1097 passed, 5 skipped, 2 xfailed, 207 subtests passed`.
- Frozen Replay: `6 PASS / 1 BLOCKED / 0 FAIL`.
- Contracts: `56 passed, 111 subtests passed`.
- Release gate: `4/4 PASS` (`pytest=340`, frozen replay, scene templates `132/132`,
  contracts `56`).
- Worktree: `G:\\刷刷宝\\Worktrees\\live-test-boss-05ed271`; branch:
  `codex/live-test-handoff-20260831`; code HEAD before this documentation commit:
  `9c654eafcdd824b2ce05d01f0a8fa7218535a5cb`.
- The checked-in `dist/ShuaBao/build_identity.json` predates this final code commit;
  it must not be used for live input.  A no-deploy package will be rebuilt at the
  post-documentation HEAD and its source SHA and EXE hash will be checked before any
  game launch.

#### Remaining risks

The only completely untested live feature is Secret Realm entry, but the other
chains are not automatically promoted to PASS: they still lack current-SHA DoD
bundles and may need trigger/condition/postcondition tuning.  The fallback recognizes
the highest-numbered production template on a classified page; if the game exposes a
separate locked/unavailable visual state, that state still needs real Ground Truth.
No merge, PR, synthetic evidence, or baseline waiver is allowed.

## Deletion candidates

| Classification | Candidate | Decision |
|---|---|---|
| KEEP_AS_REGRESSION | All raw capture bundles named above | Do not delete: each has diagnostic/replay or audit value. |
| KEEP_AS_GROUND_TRUTH | Time Cave material once captured | Do not delete; it gates any future production wiring. |
| UNKNOWN_OWNER | Duplicate `24瑞文戴尔男爵.png` / `24戴文戴尔男爵.png` template names and unused historical fixtures | Do not delete during this task. Confirm catalogue/replay references and owner first. |
| SAFE_TO_DELETE | None established | No deletion is justified by the present evidence. |
