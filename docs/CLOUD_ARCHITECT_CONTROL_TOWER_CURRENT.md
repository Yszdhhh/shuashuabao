# ShuaBao Cloud Architect Control Tower — CURRENT

> Canonical handoff for the active ShuaBao control-tower state.
> Always read this file first from `handoff/latest`, then independently verify live Git refs before trusting any Agent report.
> This branch is documentation-only. Do not merge `handoff/latest` into production merely to carry status notes.

## 0. Current verified refs

Repository:

`https://github.com/Yszdhhh/shuashuabao`

Formal G0 / production candidate:

`refactor/stability-s0-20260908@d9148c893f160a6486aeedc8f106fa764be7d931`

Lobby test-candidate provenance:

`test/lobby-hitch-surface-correction-20260909@53afb4376bd371c3e7bdffd7fff1f13eb6cfd1a5`

Live Harness:

`test/live-harness-current-20260908@ff54891d1cf3087471ab1ec1a7b66e7fc27bd8da`

Stable integration branch:

`trial-merge@d1fb4a51310f3f847ebeee110d51d8423050468b`

Dated detailed snapshot:

`docs/CLOUD_ARCHITECT_CONTROL_TOWER_20260909.md`

Current executive state:

- `FORMAL_G0 = d9148c`
- `LOBBY_53AF_RECONCILED_INTO_G0 = YES`
- `PRESSURE_BOUNDED_FAILURE_CONTRACT = COMMITTED`
- `ARCHAEOLOGY_BLIND_COORDINATE_FALLBACK = REMOVED`
- `LOBBY_SURFACE/READY/SINGLE_HWND/MODAL_LIVENESS = RECONCILED`
- `TRIAL_MERGE = UNCHANGED`
- `LIVE_GT_ON_D9148C = NOT_PROVEN`
- `FORMAL_RELEASE = HOLD`
- `PUBLIC_BAG_TRANSFER = LOCAL_TEST_AGENT_ACTIVE / NOT_PROMOTED`
- `COMP3_REVERSE_ENGINEERING_COMPLETE = YES`
- `COMP3_CLOUD_TRUTH_REBASE_TASK = ISSUED / AWAITING RETURN`

Do not describe the project as production-release PASS.

## 1. Main Agent — sole formal production integrator

Current formal commit `d9148c` reconciles three previously separate blockers:

1. **Hitch pressure transfer** — bounded fresh reobserve if `yalizhuanyi` never appears; exhaustion records `PRESSURE_CORE_FAILURE`, does not mark pressure transferred, and does not unlock optional-success semantics.
2. **Archaeology handoff** — removes the fabricated `(0.86W, 0.903H)` coordinate fallback; template miss is zero-input bounded reobserve, then fail-closed.
3. **Lobby candidate 53afb437** — manually reconciled ROOM/ROOM_LIST page identity, Ready/CancelReady contract, seat-UNKNOWN non-destructive behavior, single-HWND support, modal freshness/liveness, and GO_HOME/exit authority state machine.

The commit message reports `Release gate 4/4 PASS` and `pytest 1751 passed, 0 failed`; this is committed Agent-reported evidence, not independent cloud execution.

From here:

- freeze broad G0 rewrites;
- cloud-audit exact `d9148c` before promotion;
- then run real Live Harness / Natural GT on the exact frozen candidate;
- preserve immutable bundles before any fix to a live failure;
- local fixes return through isolated candidate -> cloud review -> Main Agent manual reconciliation;
- do not move `trial-merge` yet.

Still unproven: repeated multi-round real-machine continuity, real pressure business postcondition, archaeology handoff real chain, final Harness repin to the approved SHA, external-alpha soak / golden run.

## 2. Local Test Agent — 吞噬丹 / 绿色神符 -> 公共背包

This is a separate local Windows feature/GT lane. It must not directly modify the formal G0 branch.

Product contract for `lobby_hitch`:

- transfer `吞噬丹` to Public Bag;
- transfer green talisman only when OCR/name evidence confirms `神符`;
- treat this as transfer/storage, not item use.

Required interaction chain:

`fresh source evidence -> RIGHT CLICK personal source item -> B -> fresh Bag page -> fresh Public Bag identity -> derive empty public slot from panel/grid geometry -> LEFT CLICK public slot -> fresh transfer postcondition`

Hard rule:

`LEFT CLICK PERSONAL SOURCE ITEM = FORBIDDEN`

because that can directly use/consume the item.

Required labels include:

`PERSONAL_BAG`, `PUBLIC_BAG`, `PUBLIC_BAG_EMPTY_SLOT`, `PUBLIC_BAG_OCCUPIED_SLOT`, `SOURCE_DEVOUR_PILL`, `SOURCE_TALISMAN`, `SOURCE_SELECTED`, `DEPOSIT_REQUESTED`, `DEPOSIT_CONFIRMED`, `PUBLIC_BAG_FULL`.

Do not use global fixed coordinates for public slots. Derive from fresh panel bbox + grid row/column geometry.

Solo screenshots/recording may prove layout/right-click/B-transition only. They do not prove real hitch Public Bag transfer success. `PUBLIC_BAG_DEPOSIT_GT=PASS` requires before/after fresh business evidence on the exact candidate SHA.

Promotion path:

`local candidate -> offline real GT -> local Live Harness GT -> isolated branch commit/push -> cloud audit -> Main Agent reconcile -> final repin/soak`

If Live GT is blocked only by no usable KK window, a fully offline-gated candidate may still be pushed for cloud review, but must remain:

`LIVE_GT_REQUIRED_BEFORE_PROMOTION=YES`

`PRODUCTION_PROMOTION_ALLOWED=NO`

## 3. Competitor Decomposition Agent — current task

Competitor-3 broad reverse engineering is closed.

Local reported artifact root:

`C:\Users\10639\Desktop\竞品\拆解资产落库\02_参考脚本3\分析报告`

Reported outputs:

- `COMP3_ASSET_CATALOG.csv`
- `COMP3_ASSET_QUALITY_SUMMARY.md/.json`
- `COMP3_TO_SHUABAO_TRANSFER_MAP.md`
- `dis_evidence.json`
- two reproducible analysis scripts

Reported final competitor status:

- `COMP3_REVERSE_ENGINEERING_COMPLETE=YES`
- `NEED_MORE_COMP3_DECOMPILATION=NO`
- `COMP3_ASSETS_SHOULD_ENTER_SHUABAO=NO`
- `COMP3_METHODS_WORTH_TRANSFERRING=YES`

New task issued:

`CLOUD_TRUTH_REBASE_AND_GT_LAB_BOOTSTRAP`

Status:

`ISSUED / AWAITING RETURN`

Its first job is to rebase all old local ShuaBao findings against the current cloud truth instead of reusing stale line numbers.

Required current refs:

- Formal G0 `d9148c...`
- Lobby provenance `53afb437...`
- Harness `ff54891...`

Required return includes:

- `SOURCE_OF_TRUTH_MANIFEST_20260909.md`
- `GAP_REBASE_MATRIX`
- refresh mutation evidence status
- quarantine/watchdog starvation status
- merchant `purchases==0` provenance/current status
- formal-vs-53afb Lobby low-information asset comparison
- battle real-GT coverage matrix
- optional ShuaBao authority-asset hygiene manifest

Role boundary:

- Competitor Agent = cloud-truth reconciliation, GT taxonomy, hard negatives, asset/ROI quality, Merchant Refresh three-state GT support.
- Local Test Agent = sole owner of actual devour-pill/green-talisman Public Bag operation candidate + live transfer validation.
- Competitor Agent must not modify `src/shuabao/**`, formal G0, Lobby candidate, or Harness pin unless explicitly reassigned.

## 4. Agent / branch ownership

| Lane | Owner | Writable target | State |
|---|---|---|---|
| Formal G0 | Main Agent | `refactor/stability-s0-20260908` | `d9148c`, freeze pending audit/GT |
| Lobby provenance | historical test candidate / cloud audit | `test/lobby-hitch-surface-correction-20260909` | `53afb437`, reconciled into G0 |
| Live Harness | Test/Harness Agent | `test/live-harness-current-20260908` | `ff54891`; do not assume `d9148c` pin |
| Public Bag feature/GT | Local Test Agent | isolated local test candidate | active / not promoted |
| Competitor methods/GT audit | Competitor Agent | docs/tools-only local lane unless reassigned | task issued |
| Stable integration | nobody during current gate | `trial-merge` | unchanged `d1fb4a5` |

No concurrent production ownership.

## 5. Safety contracts that remain authoritative

- one progression/recovery owner per failure domain;
- mechanical capability != business authority;
- input/click success != business success;
- frame mutation/window change != business success;
- fresh re-observation over long semantic latches;
- UNKNOWN => zero input except bounded reacquire/reobserve;
- a known trusted KK platform-modal shell may permit bounded neutral dismiss, but is not the same as UNKNOWN;
- timeout never proves leave/success;
- only fresh verified leave may finalize a round transition;
- pressure transfer is core in hitch mode, not optional;
- no blind coordinate fallback for archaeology or page transitions;
- never weaken tests, GT, thresholds, fixtures, or baselines to manufacture PASS.

## 6. Immediate control-tower sequence

1. Cloud-audit exact `d9148c`.
2. Receive Public Bag Test Agent return; if pushed, verify exact branch/SHA/diff before accepting.
3. Receive Competitor Agent `GAP_REBASE_MATRIX`; only current-ref-confirmed debt may become a production task.
4. Approve and repin Harness only after the exact candidate is accepted for GT.
5. Run real Lobby/hitch multi-round GT including pressure business success and exit->next continuity.
6. Run real Public Bag transfer GT for devour pill + green talisman on exact test candidate.
7. Any validated local production patch returns through cloud review and Main Agent reconciliation.
8. Keep `trial-merge` unchanged until all required release and real-GT gates are explicitly green.

## 7. New-conversation start instruction

A new conversation should begin with:

> Take over ShuaBao. Read `handoff/latest:docs/CLOUD_ARCHITECT_CONTROL_TOWER_CURRENT.md` first and then `docs/CLOUD_ARCHITECT_CONTROL_TOWER_20260909.md`. Independently verify all live refs. Formal G0 was last verified at `d9148c893f160a6486aeedc8f106fa764be7d931`; Lobby provenance candidate `53afb4376bd371c3e7bdffd7fff1f13eb6cfd1a5`; Live Harness `ff54891d1cf3087471ab1ec1a7b66e7fc27bd8da`; `trial-merge` remains `d1fb4a51310f3f847ebeee110d51d8423050468b`. Main Agent owns production integration; Local Test Agent owns the Public Bag transfer candidate/GT; Competitor Agent owns cloud-truth/asset/GT audit only. Do not modify code before verifying refs and pending Agent returns.
