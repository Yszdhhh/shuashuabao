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

## Deletion candidates

| Classification | Candidate | Decision |
|---|---|---|
| KEEP_AS_REGRESSION | All raw capture bundles named above | Do not delete: each has diagnostic/replay or audit value. |
| KEEP_AS_GROUND_TRUTH | Time Cave material once captured | Do not delete; it gates any future production wiring. |
| UNKNOWN_OWNER | Duplicate `24瑞文戴尔男爵.png` / `24戴文戴尔男爵.png` template names and unused historical fixtures | Do not delete during this task. Confirm catalogue/replay references and owner first. |
| SAFE_TO_DELETE | None established | No deletion is justified by the present evidence. |
