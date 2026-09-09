# ShuaBao Cloud Architect Control Tower — 2026-09-09

> Dated handoff snapshot for new ChatGPT / Agent sessions.
> Canonical live entry remains `docs/CLOUD_ARCHITECT_CONTROL_TOWER_CURRENT.md` on `handoff/latest`.
> This is a documentation-only handoff. Do not merge the handoff branch into production merely to carry status notes.

## 0. Read-first rules

1. Read `docs/CLOUD_ARCHITECT_CONTROL_TOWER_CURRENT.md` from `handoff/latest` first.
2. Independently verify all live Git refs before trusting any Agent report.
3. GitHub proves committed code state; Windows/live-test claims remain local evidence unless their exact SHA and artifacts are pushed.
4. Mechanical click/input success is never business success. Fresh business postcondition is required.
5. `UNKNOWN` / ambiguous surface => zero input.
6. Do not let multiple Agents modify the same production integration line simultaneously.

## 1. Cloud source of truth verified on 2026-09-09

Repository:

`https://github.com/Yszdhhh/shuashuabao`

Formal G0 / production candidate:

`refactor/stability-s0-20260908@d9148c893f160a6486aeedc8f106fa764be7d931`

Formal G0 parent immediately before current reconciliation:

`3e9c50ab9dbf53b384e5460101f428e305d8db78`

Validated Lobby test candidate retained for provenance:

`test/lobby-hitch-surface-correction-20260909@53afb4376bd371c3e7bdffd7fff1f13eb6cfd1a5`

Live Harness branch:

`test/live-harness-current-20260908@ff54891d1cf3087471ab1ec1a7b66e7fc27bd8da`

Stable public integration branch remains unchanged:

`trial-merge@d1fb4a51310f3f847ebeee110d51d8423050468b`

Important: `ff54891` must not be assumed to be pinned to `d9148c`. Re-verify/repin only after cloud review explicitly approves the exact G0 candidate for live GT.

## 2. Executive status

- `FORMAL_G0 = d9148c`
- `LOBBY_53AF_RECONCILED_INTO_G0 = YES`
- `PRESSURE_UNBOUNDED_WAIT_FIX = COMMITTED_IN_G0`
- `ARCHAEOLOGY_BLIND_COORDINATE_FALLBACK = REMOVED_IN_G0`
- `ROOM/ROOM_LIST + READY/CANCELREADY + SINGLE_HWND + MODAL_LIVENESS = RECONCILED_IN_G0`
- `TRIAL_MERGE = UNCHANGED`
- `LIVE_GT_ON_D9148C = NOT_YET_PROVEN`
- `FORMAL_RELEASE = HOLD`
- `PUBLIC_BAG_TRANSFER = LOCAL_TEST_AGENT_ACTIVE / NOT_PROMOTED`
- `COMP3_DECOMPILATION = CLOSED`
- `COMP3_METHOD_TRANSFER / CLOUD_TRUTH_REBASE = ISSUED_TO_COMPETITOR_AGENT`

Do not describe the project as production-release PASS.

## 3. Main Agent lane — formal G0 repair/reconciliation

### 3.1 Current committed result

Current formal HEAD `d9148c` records the following reconciliation:

- pressure transfer: when `yalizhuanyi` never appears, use a bounded fresh-reobserve budget; exhaustion becomes `PRESSURE_CORE_FAILURE`, does not mark transfer success, does not release optional authority, and keeps OutcomeWatcher semantics intact;
- archaeology handoff: remove the blind `(0.86W, 0.903H)` coordinate fallback; template miss becomes bounded zero-input reobserve and fail-closed rather than a fabricated click request;
- Lobby candidate `53afb437` manually reconciled into G0: ROOM/ROOM_LIST page identity, Ready/CancelReady contract, seat `UNKNOWN` no destructive exit, single-HWND topology support, modal liveness freshness, and GO_HOME/exit authority state machine;
- G0 anchors such as RunExitReason, postgame-before-pressure ordering, and fresh postconditions are intended to remain intact.

The commit message reports `Release gate 4/4 PASS` and `pytest 1751 passed, 0 failed`; treat this as committed Agent-reported evidence, not independent cloud execution.

### 3.2 Main Agent ownership from here

Main Agent is the sole production integrator for this line.

Immediate policy:

- do not start another broad mediator rewrite;
- independently cloud-audit `d9148c` before further promotion;
- after cloud review, run Live Harness / Natural GT on the exact frozen SHA;
- any real failure must preserve an immutable bundle first;
- fixes discovered by local test must return through an isolated candidate branch, then cloud review, then Main Agent reconciliation;
- do not move `trial-merge` until required live/release gates clear.

### 3.3 Still not proven

- repeated multi-round real-machine continuity on `d9148c`;
- real pressure-transfer successful business postcondition in hitch mode;
- archaeology handoff real page/HUD chain;
- full victory/failure -> verified leave -> lobby -> next round loop;
- final Harness identity/pin for `d9148c`;
- external-alpha soak / 10-round golden run.

## 4. Local Test Agent lane — devour pill / green talisman -> Public Bag

This is a separate local Windows test/feature lane. It must not directly edit the formal G0 branch.

### 4.1 Product intent

In `lobby_hitch` mode only:

- `吞噬丹` should be transferred into the Public Bag;
- green talismans whose OCR/name evidence confirms `神符` should be transferred into the Public Bag;
- this is a transfer/storage flow, not an item-use flow.

### 4.2 Non-negotiable interaction contract

Personal source item:

`fresh source-item evidence -> RIGHT CLICK only -> B -> fresh Bag page -> fresh Public Bag identity -> derive public empty slot from panel/grid geometry -> LEFT CLICK public slot -> fresh transfer postcondition`

Critical safety rule:

`LEFT CLICK PERSONAL SOURCE ITEM = FORBIDDEN`

because left-clicking a personal source item can directly use/consume it.

Global hard-coded public-slot coordinates are forbidden. Coordinates must be derived from fresh panel bbox + grid row/column geometry.

### 4.3 Required state labels / GT

At minimum:

- `PERSONAL_BAG`
- `PUBLIC_BAG`
- `PUBLIC_BAG_EMPTY_SLOT`
- `PUBLIC_BAG_OCCUPIED_SLOT`
- `SOURCE_DEVOUR_PILL`
- `SOURCE_TALISMAN`
- `SOURCE_SELECTED`
- `DEPOSIT_REQUESTED`
- `DEPOSIT_CONFIRMED`
- `PUBLIC_BAG_FULL`

Hard negatives include personal empty slots, occupied public slots, dark non-slot regions, selected/highlighted slots, borders/tooltips, and animation frames.

### 4.4 Evidence boundary

Existing solo recording/screenshots may prove layout, source-slot recognition, right-click behavior, and `B` transition.

They do **not** prove real Public Bag deposit success in hitch mode.

`PUBLIC_BAG_DEPOSIT_GT = PASS` requires a real before-transfer public slot + requested transfer + fresh after-transfer business postcondition on the exact candidate SHA.

### 4.5 Promotion workflow

`local test candidate -> offline real GT -> local Live Harness real GT -> commit/push isolated test branch -> cloud audit -> Main Agent manual integration -> final repin/soak`

If Live GT is blocked only because no usable KK window exists, after offline real GT + release gates the candidate may still be committed/pushed for cloud review, but must be labeled:

- `LIVE_GT_BLOCKED`
- `LIVE_GT_REQUIRED_BEFORE_PROMOTION=YES`
- `PRODUCTION_PROMOTION_ALLOWED=NO`

Do not commit raw `live-captures/` unless evidence policy explicitly requires it.

## 5. Competitor Decomposition Agent lane

### 5.1 Completed local Competitor-3 work

Local artifact root reported by the Agent:

`C:\Users\10639\Desktop\竞品\拆解资产落库\02_参考脚本3\分析报告`

Reported artifacts:

- `COMP3_ASSET_CATALOG.csv` — 548 image assets with metrics;
- `COMP3_ASSET_QUALITY_SUMMARY.md` / `.json`;
- `COMP3_TO_SHUABAO_TRANSFER_MAP.md`;
- `dis_evidence.json`;
- two reproducible analysis scripts.

Reported competitor result:

- `COMP3_REVERSE_ENGINEERING_COMPLETE = YES`
- `NEED_MORE_COMP3_DECOMPILATION = NO`
- `COMP3_ASSETS_SHOULD_ENTER_SHUABAO = NO`
- `COMP3_METHODS_WORTH_TRANSFERRING = YES`

High-value transferable methods include evidence-layer separation, mutation-as-auxiliary-not-success, tight ROI for low-information locators, positive bounded-stop evidence, and explicit recognition-vs-state separation.

Reject direct transfer of competitor fixed-coordinate authority, click+sleep without postcondition, panel-closed==purchase-success, unknown fallback clicks, or competitor asset copying.

### 5.2 Newly issued task

Task name:

`CLOUD_TRUTH_REBASE_AND_GT_LAB_BOOTSTRAP`

Status:

`ISSUED / AWAITING RETURN`

First responsibility is to stop using stale local line numbers and rebase all ShuaBao findings against current cloud refs:

- Formal G0: `d9148c...`
- Lobby provenance candidate: `53afb437...`
- Harness: `ff54891...`

Required outputs:

- `SOURCE_OF_TRUTH_MANIFEST_20260909.md`
- `GAP_REBASE_MATRIX`
- refresh mutation evidence status;
- quarantine/watchdog starvation status;
- merchant `purchases==0` provenance/current status;
- formal-vs-53afb Lobby low-information asset comparison;
- battle real-GT coverage matrix;
- ShuaBao authority-asset hygiene report if time allows.

### 5.3 Role boundary with Test Agent

Competitor Agent does **not** own Public Bag production behavior.

It may support:

- GT taxonomy;
- hard-negative inventory;
- asset/ROI quality analysis;
- Merchant Refresh three-state GT (`MUTATED / UNCHANGED / SAMPLE_FAILED`);
- read-only source-of-truth reconciliation.

Test Agent remains sole owner of the actual devour-pill / green-talisman Public Bag operation candidate and its live transfer validation.

Competitor Agent must not modify:

- `src/shuabao/**`
- formal `refactor/stability-s0-20260908`
- Lobby candidate branch
- Harness pin

unless a later explicit task changes ownership.

## 6. Critical safety / architecture contracts

- one progression/recovery owner per failure domain;
- mechanical capability != business authority;
- frame/window mutation != business success;
- click/input dispatch != business success;
- fresh re-observation is preferred to semantic latches;
- UNKNOWN permits bounded reacquire/reobserve only, no blind action;
- trusted KK platform modal shell is a known surface and may allow bounded neutral dismiss, but must not be conflated with UNKNOWN;
- only fresh verified leave can finalize a round / increment counted completion;
- pressure transfer is core in hitch mode, never optional business success;
- timeout may trigger reclassification/reobserve, never prove a business transition;
- tests/fixtures/thresholds/baselines must not be weakened to manufacture PASS.

## 7. Branch / Agent ownership map

| Lane | Owner | Writable target | Current state |
|---|---|---|---|
| Formal G0 | Main Agent | `refactor/stability-s0-20260908` | `d9148c`, freeze pending audit/GT |
| Lobby provenance | Cloud review / historical test candidate | `test/lobby-hitch-surface-correction-20260909` | `53afb437`, already reconciled into G0 |
| Live Harness | Test/Harness Agent | `test/live-harness-current-20260908` | `ff54891`, do not assume d914 pin |
| Public Bag feature/GT | Local Test Agent | isolated local test candidate | active / not promoted |
| Competitor methods / GT audit | Competitor Agent | docs/tools-only local lane unless explicitly changed | task issued |
| Stable integration | nobody during current gate | `trial-merge` | unchanged `d1fb4a5` |

Do not let Test Agent or Competitor Agent directly write the formal G0 branch while Main Agent owns integration.

## 8. Next control-tower sequence

1. Cloud audit exact `d9148c` diff and safety contracts.
2. Receive Test Agent Public Bag candidate/GT report; if pushed, independently verify exact branch/SHA/diff before acceptance.
3. Receive Competitor Agent `GAP_REBASE_MATRIX`; only current-ref-confirmed debt may become a production task.
4. Repin/run Harness only after the exact production candidate is approved for GT.
5. Run real Lobby/hitch multi-round GT, including pressure business success and exit-to-next-round continuity.
6. Run real Public Bag transfer GT for devour pill + green talisman on the exact test candidate.
7. Any validated local production fix goes through cloud review, then Main Agent manual reconciliation.
8. Keep `trial-merge` unchanged until release gates and real GT are explicitly green.

## 9. New-conversation start prompt

Use this minimum handoff:

> Take over ShuaBao. First read `handoff/latest:docs/CLOUD_ARCHITECT_CONTROL_TOWER_CURRENT.md`, then `docs/CLOUD_ARCHITECT_CONTROL_TOWER_20260909.md`. Independently verify live refs before trusting Agent reports. Formal G0 was last verified at `d9148c893f160a6486aeedc8f106fa764be7d931`; Lobby provenance candidate `53afb4376bd371c3e7bdffd7fff1f13eb6cfd1a5`; Live Harness `ff54891d1cf3087471ab1ec1a7b66e7fc27bd8da`; `trial-merge` remains `d1fb4a51310f3f847ebeee110d51d8423050468b`. Main Agent owns formal integration; local Test Agent owns devour-pill/green-talisman -> Public Bag candidate and GT; Competitor Agent owns cloud-truth/asset/GT audit only. Do not modify code before verifying current refs and pending Agent returns.
