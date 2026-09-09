# ShuaBao Cloud Architect Control Tower — CURRENT

> Canonical handoff for the active ShuaBao control-tower state.
> Always read this file first from `handoff/latest`, then independently verify live Git refs before trusting any Agent report.
> This branch is documentation-only. Do not merge `handoff/latest` into production merely to carry status notes.

## 0. Current verified refs

Repository:

`https://github.com/Yszdhhh/shuashuabao`

Formal G0 / production candidate:

`refactor/stability-s0-20260908@d9148c893f160a6486aeedc8f106fa764be7d931`

Lobby provenance candidate:

`test/lobby-hitch-surface-correction-20260909@53afb4376bd371c3e7bdffd7fff1f13eb6cfd1a5`

Canonical Live Harness:

`test/live-harness-current-20260908@ff54891d1cf3087471ab1ec1a7b66e7fc27bd8da`

Tier-0 scenario Harness:

`test/live-scenarios-tier0-lobby-20260909@87594d474724798775ffbc89bea619addfb41cf3`

GT / Evidence Lab delivery:

`test/gt-lab-public-bag-merchant-refresh-20260909@fddb17299a7b0e761e8987aea80a3cb56dbfebad`

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
- `PUBLIC_BAG_AUTO_DEPOSIT = NOT_PROVEN / GT_REQUIRED`
- `COMP3_REVERSE_ENGINEERING_COMPLETE = YES`
- `GT_LAB_CLOUD_DELIVERED = YES @ fddb172`
- `BROAD_FEATURE_DEVELOPMENT = FROZEN UNTIL CURRENT LIVE VALIDATION`

Do not describe the project as production-release PASS.

---

## 1. Main Agent — sole formal production integrator

Current formal commit `d9148c` reconciles three previously separate blockers:

1. **Hitch pressure transfer** — bounded fresh reobserve if `yalizhuanyi` never appears; exhaustion records `PRESSURE_CORE_FAILURE`, does not mark pressure transferred, and does not unlock optional-success semantics.
2. **Archaeology handoff** — removes the fabricated `(0.86W, 0.903H)` coordinate fallback; template miss is zero-input bounded reobserve, then fail-closed.
3. **Lobby candidate 53afb437** — ROOM/ROOM_LIST page identity, Ready/CancelReady contract, seat-UNKNOWN non-destructive behavior, single-HWND support, modal freshness/liveness, and GO_HOME/exit authority logic were reconciled into Formal G0.

From here:

- freeze broad G0 rewrites and new product features;
- run exact `d9148c` real-machine validation first;
- only validated `PRODUCTION_BUG` evidence should create a Main-Agent code task;
- preserve immutable bundles before any fix to a live failure;
- local fixes return through isolated candidate -> cloud review -> Main Agent manual reconciliation;
- do not move `trial-merge` yet.

Main Agent may still do bounded non-behavioral hardening when needed for testability/identity/observability, but must not use architecture cleanup as a reason to alter unproven business behavior before Live GT.

Still unproven:

- repeated multi-round real-machine continuity;
- real pressure business postcondition;
- Merchant / Treasure / devour-pill behavior on exact Formal G0;
- Victory/Failure -> real exit -> ROOM_LIST -> next-round continuity;
- disconnect/modal long-thread behavior;
- external-alpha soak / golden run.

---

## 2. Test / Harness Agent — current primary execution lane

Current Production under test:

`d9148c893f160a6486aeedc8f106fa764be7d931`

Current Tier-0 scenario Harness:

`87594d474724798775ffbc89bea619addfb41cf3`

Important identity correction:

- `53afb437` is frozen Lobby provenance, not the current Production Test Candidate.
- `87594d` already supports external Production source injection via `--production-source-root` and `--production-source-sha`.
- therefore **do not create a Harness repin commit merely to test `d9148c`**.
- before live input, require exact source SHA, clean production source, and actual imported module path to resolve to the intended `d9148c` worktree.

Current priority is evidence acquisition, not Harness expansion.

Required first live sequence:

`ROOM_LIST -> search/join -> ROOM -> Ready -> GAME/HUD -> Pressure -> normal round -> Merchant/Treasure/resources -> Victory/Failure -> verified exit -> ROOM_LIST -> next round`

After one-round smoke, continue in the same runtime process for multi-round / long-thread validation. Do not restart merely to make subsequent rounds pass.

Core long-thread evidence must distinguish:

- process alive;
- worker alive;
- business progress.

Repeated capture/OCR activity is not business progress.

Any manual intervention must be recorded and prevents that chain from being called natural E2E PASS.

Any live failure must preserve bundle/trace/video timestamp before changes.

Current local test modifications are still local/pending user validation. Once the user reports tests passed and pushes them, first verify the exact branch/SHA/diff before assigning integration or architecture work.

---

## 3. GT / Evidence Lab Agent — former Competitor Agent

Competitor-3 broad reverse engineering is closed. Do not continue broad decompilation.

Cloud delivery verified:

`test/gt-lab-public-bag-merchant-refresh-20260909@fddb17299a7b0e761e8987aea80a3cb56dbfebad`

The delivery is docs/tools-only and must remain separate from Production. It contains exactly:

1. `SOURCE_OF_TRUTH_MANIFEST_20260909.md`
2. `GAP_REBASE_MATRIX_20260909.md`
3. `SHUABAO_AUTHORITY_ASSET_MANIFEST.csv`
4. `docs/gt_lab/PUBLIC_BAG_GT_SPEC_20260909.md`
5. `docs/gt_lab/MERCHANT_REFRESH_GT_SPEC_20260909.md`
6. `tools/gt_lab/extract_bag_gt.py`
7. `tools/gt_lab/extract_merchant_gt.py`

Current role:

- real-GT taxonomy and provenance;
- hard-negative construction;
- asset / ROI quality analysis;
- Merchant Refresh observation analysis;
- Public Bag real-transfer GT processing;
- battle-resource GT coverage;
- evidence-to-current-cloud-ref reconciliation.

It must not independently modify `src/shuabao/**`, Formal G0, `trial-merge`, or Harness behavior.

Current gap disposition:

- GAP B quarantine starvation: historical/wrong-ref, no current action.
- GAP D pressure unbounded wait: already fixed in `d9148c`.
- GAP E archaeology blind coordinate: already fixed in `d9148c`.
- GAP A Merchant/Treasure refresh mutation evidence: needs real GT.
- GAP C Merchant `purchases==0` fail-open behavior: current-production concern; evaluate with real GT before production change.
- GAP F Lobby low-information asset authority: architectural debt; do not route old `53afb437` back into production. Validate current `d9148c` only.
- GAP G battle GT coverage: real GT required for talisman/devour-pill/public-bag/wood/disconnect and other unproven battle surfaces.
- GAP H asset hygiene: real debt, but defer cleanup until current live-validation baseline is stable.

Merchant thresholds such as `5% mutation` or `unchanged_streak >= 2` are GT hypotheses, not production constants until calibrated against real samples.

---

## 4. Public Bag / protected-resource contract

For `lobby_hitch`:

- transfer `吞噬丹` to Public Bag;
- transfer green talisman only when OCR/name evidence confirms `神符`;
- transfer/storage, not item use.

Required chain:

`fresh valid source evidence -> RIGHT CLICK personal source item -> B -> fresh valid Bag page -> fresh Public Bag identity -> derive empty public slot from panel/grid geometry -> LEFT CLICK public slot -> fresh source-after + public-after reconciliation`

Hard rule:

`LEFT CLICK PERSONAL SOURCE ITEM = FORBIDDEN`

because that may directly consume/use the item.

The prohibition must ultimately live in a shared input-safety policy rather than rely only on each caller behaving correctly.

Public destination must be derived from fresh panel-local geometry; no hardcoded global coordinates.

Required labels include:

`PERSONAL_BAG`, `PUBLIC_BAG`, `PUBLIC_BAG_EMPTY_SLOT`, `PUBLIC_BAG_OCCUPIED_SLOT`, `SOURCE_DEVOUR_PILL`, `SOURCE_TALISMAN`, `SOURCE_SELECTED`, `DEPOSIT_REQUESTED`, `DEPOSIT_CONFIRMED`, `PUBLIC_BAG_FULL`.

Solo video may prove layout/right-click/B-open only. It cannot prove multiplayer deposit success.

Public Bag is a concurrent UI system: teammates may act at the same time. Therefore transfer outcome must allow at least:

- `COMMITTED`
- `NOT_COMMITTED`
- `AMBIGUOUS`

Do not force ambiguous visual evidence into PASS/FAIL.

If deposit result is ambiguous or failed, protected team resources must remain consumption-blocked until fresh evidence resolves the item state, the round ends, the item disappears, or explicit product policy releases it.

`PUBLIC_BAG_DEPOSIT_GT=PASS` requires fresh real multiplayer before/after business evidence.

---

## 5. Authoritative safety / evidence contracts

These remain authoritative and are extended by the external architecture review where useful:

- one progression/recovery owner per failure domain;
- mechanical capability != business authority;
- input/click success != business success;
- frame mutation/window change != business success;
- timeout never proves leave/success;
- only fresh verified leave may finalize a round transition;
- pressure transfer is core in hitch mode, not optional;
- no blind coordinate fallback for archaeology or page transitions;
- never weaken tests, GT, thresholds, fixtures, or baselines to manufacture PASS.

### 5.1 UNKNOWN semantics — corrected

Do not interpret UNKNOWN as “literally no system output of any kind.”

Use:

`UNKNOWN => DENY NEW BUSINESS INPUT`

Allowed risk-reducing operations may include:

- release keys/buttons currently held by ShuaBao;
- cancel/revoke a pending internal input lease;
- stop/pause;
- bounded reacquire/reobserve.

UNKNOWN must never be used to justify a guessed business action.

### 5.2 Freshness is necessary but not sufficient

A fresh frame may still be wrong/unusable.

Before high-risk authority, require a valid observation envelope such as:

`Fresh + Correct Source + Valid Geometry + Supported Surface + Current Generation`

Relevant provenance includes HWND/PID identity, capture source, frame identity, client rect/DPI transform, image-quality flags, and generation.

### 5.3 Business outcome is not binary

For high-risk/non-idempotent operations, use explicit outcomes such as:

- `CONFIRMED_SUCCESS`
- `CONFIRMED_NO_EFFECT`
- `REJECTED`
- `AMBIGUOUS`
- `OBSERVATION_FAILED`

`AMBIGUOUS` is a legitimate business result and must not be collapsed into success/failure merely to keep the thread moving.

### 5.4 Strategy cannot own mechanical input

Future card/treasure/merchant/Boss intelligence may output `Choice/Intent` only.

Input authority must remain behind surface/evidence/policy/safety verification.

---

## 6. Accepted Architecture North Star — backlog, not immediate rewrite

An external architecture assessment was reviewed as an advisory/desk-study artifact only. It did **not** independently inspect `d9148c`, execute Windows/KK, or qualify release. Its useful recommendations are accepted as architecture backlog, not current code facts.

The target direction is:

`Observation -> Evidence + Provenance -> Intent + Policy + Ownership -> Authorization -> Input Gateway -> Fresh Verification -> Business Outcome`

The project should avoid both extremes:

- endlessly stacking fallback/watchdog/test count;
- wholesale rewrite merely to make the architecture look cleaner.

### 6.1 G0/G0.1 hardening backlog — accepted

These are real implementation candidates after current live validation determines sequencing:

1. **Progress token separate from heartbeat**
   - process heartbeat proves process liveness;
   - worker heartbeat proves capture/OCR responsiveness;
   - progress token proves business movement.
   - repeated OCR/capture alone must not refresh business-progress timeout.

2. **Observation provenance / validity envelope**
   - unify source identity, frame id, HWND/PID, geometry/DPI, quality flags, generation, and evidence expiry.

3. **Generation semantics**
   - start with a minimal set, preferably `binding_generation`, `round_generation`, `transaction_generation`;
   - HWND/PID rebinding, capture rebuild, round transition, transaction cancel/restart invalidate stale evidence/actions.

4. **Protected Action Policy / Action Safety Kernel**
   - high-risk actions require current evidence + policy + ownership + target-region constraints;
   - shared deny rules include personal-source LEFT CLICK, wrong-HWND/foreground-loss business input, UNKNOWN business input, and blind retry of unresolved non-idempotent transactions.
   - initially wrap/strengthen the existing single Input Gateway; do not create a second input runtime.

5. **Explicit transaction outcomes**
   - apply first to Merchant refresh/purchase, Public Bag transfer, and high-risk exit/re-entry flows.

6. **Artifact identity beyond source SHA**
   - future release identity must bind source SHA + clean state + final artifact digest + dependency lock + OCR model/dictionary/preprocessing + assets/templates + web bundle + effective config + capture/input backend + Harness/instrumentation identity.

7. **Stable Launcher / immutable release identity**
   - future desktop shortcut should point to a stable launcher, not a worktree/version-specific executable;
   - launcher validates approved artifact metadata, starts selected immutable version, and handshakes runtime/model/asset identity;
   - Dashboard should expose Channel / Version / Source SHA / Artifact ID / Model-Asset version / verified package status.

8. **Subscription state-axis cleanup**
   - keep Billing separate from License Authority;
   - production should use one authoritative License engine, with any second engine shadow-only;
   - internally consider separating `commercial_state`, `authorization_state`, and `lease_state` instead of forcing all meaning into one enum;
   - external assessment does not itself verify current Keygen/Keygate/FOSSBilling deployment details.

### 6.2 Deferred / do not start during current validation

Do not currently launch broad work for:

- full Mediator rewrite;
- all-domain Behavior Tree rewrite;
- full-screen OCR as default path;
- immediate PP-OCR replacement;
- WGC/DXcam capture backend switch without benchmark;
- UIA as a new input owner;
- full TUF implementation;
- native launcher rewrite before current package identity problem is concretely scoped;
- Nuitka migration primarily for anti-reverse-engineering;
- RL/MCTS/LLM realtime input planning;
- active-active subscription/license architecture;
- broad asset cleanup that would invalidate the current test baseline.

These remain research/controlled-PoC topics after the current G0 is qualified or rejected by real evidence.

---

## 7. Agent / branch ownership

| Lane | Owner | Writable target | State |
|---|---|---|---|
| Formal G0 | Main Agent | `refactor/stability-s0-20260908` | `d9148c`, freeze pending real GT |
| Lobby provenance | historical test candidate / cloud audit | `test/lobby-hitch-surface-correction-20260909` | `53afb437`, frozen provenance |
| Canonical Live Harness | Test/Harness Agent | `test/live-harness-current-20260908` | `ff54891` |
| Tier-0 scenario Harness | Test/Harness Agent | `test/live-scenarios-tier0-lobby-20260909` | `87594d`, external Production injection supported |
| Local current test fixes | Local Test Agent | isolated local branch until user validation/push | pending |
| GT / Evidence Lab | GT Lab Agent | `test/gt-lab-public-bag-merchant-refresh-20260909` docs/tools only | `fddb172`, delivered |
| Stable integration | nobody during current gate | `trial-merge` | unchanged `d1fb4a5` |

No concurrent production ownership.

---

## 8. Immediate control-tower sequence

1. Finish the current local Test-Agent corrections and user-side validation.
2. When the tested local changes are pushed, independently verify exact branch/SHA/diff and whether they touch Production, Harness, fixtures, thresholds, assets, or only test infrastructure.
3. Do not merge simply because local tests pass.
4. Re-run identity/readiness on clean exact intended Production source.
5. Execute one-round natural smoke including Lobby, Ready, GAME/HUD, Pressure, Merchant/Treasure/resources, Victory/Failure, verified exit, and ROOM_LIST return.
6. Continue the **same runtime process** into multi-round long-thread validation.
7. Capture real Merchant/devour-pill/treasure GT when naturally encountered; `COVERAGE_NOT_HIT` is not feature failure.
8. Capture Public Bag final transfer GT in real multiplayer conditions before implementing/promoting auto-deposit.
9. Any validated Production failure -> immutable bundle -> cloud classification -> Main Agent minimal fix -> exact-SHA revalidation.
10. Keep `trial-merge` unchanged until required release and real-GT gates are explicitly green.

---

## 9. Next architecture/foundation round after tonight's tested push

Once the user has validated the local fixes and pushed them, the next architecture round should be evidence-led, not a blanket rewrite.

Order of work:

### A. Reconcile latest cloud truth

- verify pushed test branch/SHA/diff;
- verify Formal G0 / Harness / GT Lab refs;
- determine whether any local fixes need Main-Agent reconciliation;
- refresh this handoff again.

### B. Build only the highest-ROI foundation exposed by current failures

Preferred foundation candidates, in order:

1. heartbeat vs business-progress instrumentation;
2. minimal observation provenance + generation;
3. shared protected-action deny policy at the existing Input Gateway;
4. explicit `AMBIGUOUS` / observation-failed outcomes for Merchant/Public Bag/exit transactions;
5. artifact/runtime/model/assets identity manifest groundwork.

Do not implement all five blindly. Select the smallest set justified by live/test evidence.

### C. Architecture synchronization

- map current progression/recovery owners from actual code;
- identify duplicate owners and stale-latch paths;
- reduce one concrete failure domain at a time;
- prefer strangler-style extraction from Mediator over wholesale rewrite;
- Merchant/Inventory transaction is the first likely extraction candidate only after current behavior is proven/understood.

### D. Packaging / release foundation

If current testing again proves source/package/desktop identity confusion, promote artifact identity + stable-launcher design to P0 release engineering. Otherwise keep it behind live-runtime blockers.

### E. Strategy intelligence remains later

Card/Treasure/Merchant/Boss strategy evolution:

`explicit rules -> utility scoring -> data/shadow evaluation -> limited lookahead -> learning only if evidence supports ROI`

Strategy must never gain direct input authority.

---

## 10. New-conversation start instruction

A new conversation should begin with:

> Take over ShuaBao. Read `handoff/latest:docs/CLOUD_ARCHITECT_CONTROL_TOWER_CURRENT.md` first, then independently verify all live refs before trusting Agent returns. Formal G0 was last verified at `d9148c893f160a6486aeedc8f106fa764be7d931`; Lobby `53afb4376bd371c3e7bdffd7fff1f13eb6cfd1a5` is frozen provenance; canonical Harness `ff54891d1cf3087471ab1ec1a7b66e7fc27bd8da`; Tier-0 scenario Harness `87594d474724798775ffbc89bea619addfb41cf3` supports external Production injection; GT/Evidence Lab delivery is `fddb17299a7b0e761e8987aea80a3cb56dbfebad`; `trial-merge` remained `d1fb4a51310f3f847ebeee110d51d8423050468b`. Formal release remains HOLD pending real exact-candidate Live GT. Current user-side local test fixes may have been pushed after this handoff; verify them before assigning integration or architecture work. Do not start broad refactors before reconciling that push and the newest live evidence.
