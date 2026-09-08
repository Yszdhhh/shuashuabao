# ShuaBao Cloud Architect Control Tower — CURRENT

> Canonical handoff for the active ShuaBao control-tower state.
> Always read this file first from `handoff/latest`, then independently verify live Git refs before trusting any Agent report.
> This branch is documentation-only. Do not merge `handoff/latest` into production merely to carry status notes.

## 0. Executive state

Repository:

`https://github.com/Yszdhhh/shuashuabao`

Current production integration branch:

`trial-merge@d1fb4a51310f3f847ebeee110d51d8423050468b`

Current S0 / production candidate:

`refactor/stability-s0-20260908@dc108892d8590c04828dc176482bee32ba348914`

Current test/CI lane:

`test/ci-speed-and-stability-harness-20260908@c5589d4876aad6ed0625473e20f2542446a2fbe6`

Current Live Harness:

`test/live-harness-current-20260908@4b19e1005690509dc243dd1870a035422c10e640`

Live Harness production baseline:

`dc108892d8590c04828dc176482bee32ba348914`

Current status:

- `FINAL_FREEZE_HYGIENE = PASS`
- `CORRECTIVE_C_RELEASE_DEBT = CLOSED`
- `COMPETITOR_A_C_CROSS_VALIDATION = COMPLETE`
- `COMPETITOR_RESEARCH = HOLD`
- `COMPETITOR_CORE_ASSETS_EXTRACTED = YES`
- `STABILITY_SIMPLIFICATION_S0 = IMPLEMENTED_TO_CURRENT_CANDIDATE / REAL_GT_PENDING`
- `S0_SINGLE_OWNER_TARGET = PASS_FOR_TARGETED_DOMAINS`
- `WINDOW_AUTHORITY = PASS_FOR_CURRENT_SCOPE`
- `PAGE_LOCAL_DETECTOR_AUTHORITY = PARTIAL`
- `ROUND_LIFETIME_PROOF = PARTIAL / REAL_GT_PENDING`
- `POSTCONDITION_SAFETY = PRESERVED`
- `TEST_CI_LANE = COMPLETE_ON_ISOLATED_BRANCH / NOT_INTEGRATED`
- `LIVE_HARNESS = READY_FOR_GT`
- `TRIAL_MERGE = UNCHANGED`
- `REMOTE_CI_ON_DC108892 = NOT_RUN`
- `PRODUCT_GOLDEN_RUN = NOT_RUN`
- `POLICY_V01_IMPLEMENTATION = HOLD_UNTIL_S0_VALIDATED`
- `MAIN_RECONCILIATION = HOLD`
- `PRODUCT_RELEASE_APPROVAL = NO`

Do not describe the current state as full production-release PASS.

## 1. Canonical detailed docs

Read these next when relevant:

- S0 implementation contract:
  `docs/STABILITY_SIMPLIFICATION_S0_IMPLEMENTATION_CONTRACT_20260908.md`
- competitor stability synthesis:
  `docs/COMPETITOR_STABILITY_DECOMPOSITION_20260908.md`
- competitor C cross-validation:
  `docs/COMPETITOR_C_CROSS_VALIDATION_20260908.md`
- current competitor-asset landing matrix:
  `docs/COMPETITOR_ASSET_LANDING_STATUS_20260908.md`
- Git cleanup manifest:
  `docs/GIT_CLEANUP_MANIFEST_20260908.md`
- frozen Policy v0.1 contract:
  `docs/policy/POLICY_V01_IMPLEMENTATION_CONTRACT_20260908.md`
- Policy evidence appendix:
  `docs/policy/POLICY_V01_EVIDENCE_APPENDIX_20260908.md`

## 2. Immutable / historical refs

Keep immutable:

- `archive/final-green-trial-20260908` -> `decb9b6eb3559e39ea51e26864eaada0d648855b`
- `archive/final-policy-base-20260908` -> `d1fb4a51310f3f847ebeee110d51d8423050468b`
- `archive/old-main-20260908` -> `7edae9909ab1c757da27a45c4409f464aae66b04`

Old public `main` remains:

`7edae9909ab1c757da27a45c4409f464aae66b04`

Pre-stability ancestry-repair candidate remains:

`integration/reconcile-main-trial-20260908@1c8ef1ac53e2ee83dec73420f8ffef4aabb2b5a4`

Do not move `main` to it. S0 and later integration create a newer final convergence target.

## 3. Competitor research — what is actually reusable

Broad competitor research is stopped. A/C evidence was sufficient to freeze internal ShuaBao constraints, not to copy competitor source/assets.

Core reusable architecture assets:

1. one clear progression/recovery owner per active failure domain;
2. asset inventory is not detector authority — only the verified current page/job subset should be authoritative;
3. capture/window/input/timers are mechanical helpers, not independent business owners;
4. prefer fresh re-observation over long-lived semantic latches where the frame can answer the question;
5. retain only minimum legitimate asynchronous action memory;
6. explicit action/round/session state lifetime and reset ownership;
7. PLATFORM/GAME/UNKNOWN ownership gates detector/input authority;
8. input dispatch success is never business success; UNKNOWN remains zero-input.

Current landing summary is maintained in:

`docs/COMPETITOR_ASSET_LANDING_STATUS_20260908.md`

Key current verdict:

- single-owner/liveness target: landed for known S0 duplicate-owner domains;
- window ownership authority: strongly landed for current scope;
- detector authority narrowing: only partial;
- full transient lifetime proof: only partial until repeated real-machine rounds;
- postcondition/UNKNOWN safety: preserved.

No more broad competitor reverse engineering unless a specific current implementation question creates an evidence gap.

## 4. Current S0 production candidate — `dc108892`

The current S0 branch is six commits ahead of `d1fb4a5` and includes the original S0 refactor plus live lobby fixes discovered during current-SHA testing.

### 4.1 S0 architectural changes landed

- centralized typed `WindowRole = PLATFORM | GAME | UNKNOWN`;
- `KK` alone cannot grant GAME authority;
- Runtime MAIN_LINE watchdog no longer injects generic ESC and is telemetry-only;
- Runtime duplicate panel physical recovery/fail-forward authority removed;
- Core remains the relevant business owner for those domains;
- watchdog stall telemetry is episode-based and its current-round/session lifetime is explicit;
- dead Runtime panel fail-forward API/residue removed;
- existing business postcondition and UNKNOWN zero-input contracts preserved.

### 4.2 Latest lobby convergence

Current `dc108892` no longer uses the temporary popup-size heuristic.

Pending join now records the lobby origin HWND. If a different KK HWND appears, it must prove the real room signature (exit + ready/start controls) before ROOM_WAITING authority. A different KK HWND without room controls is treated as a pending-join dialog and safely dismissed/rejected. Same-window explicit dialog handling remains available.

The two hitch exit phase-handoff defects are also restored/fixed:

- verified failure exit: `RECOVER_FAILURE -> LOBBY_ROOM` after the verified exit/hitch cleanup;
- normal confirmed exit: `NEXT -> LOBBY_ROOM` after the verified exit/hitch cleanup.

These fixes prevent stale RECOVER_FAILURE/NEXT state from producing next-tick ERROR/timeout after a successful exit.

### 4.3 Important boundary

This does not prove arbitrary full-screen/DPI/layout variants are fully supported. The specific pending-join popup fix is now based on window/surface identity rather than `440x260`, but full layout robustness still requires real-machine GT.

## 5. Test/CI lane — `c5589d4`

Completed on the isolated branch:

- removed duplicate full Python pytest execution while retaining the authoritative Standard Release Gate;
- split UI check/unit/build from Python Standard Release Gate into parallel jobs;
- measured GitHub Actions wall-time reduction from about `17m59s` to `10m14s` (~43% on the observed runs);
- added a 50-round zero-real-input lifecycle audit using production classes with fake input;
- added detector/matcher/search-pixel authority profiling;
- did not modify prohibited S0 production files.

Important:

- this branch is not yet integrated into the current S0 candidate;
- its lifecycle audit must be adapted to current S0 fields because old watchdog fields changed/vanished;
- the temporary test-branch workflow trigger should not be carried into final production CI.

Do not merge `c5589d4` blindly before rebasing/adapting it to the final candidate.

## 6. Live Harness — `4b19e100`

Current branch:

`test/live-harness-current-20260908@4b19e1005690509dc243dd1870a035422c10e640`

Current production baseline:

`dc108892d8590c04828dc176482bee32ba348914`

The Harness is now a diagnostic control surface layered on current production, not an alternate product implementation.

Verified structure:

- `dc108892 -> 4b19e100` adds Harness/launcher/docs/tests/tools only;
- no `src/shuabao/**` production delta;
- identity gate pins the expected production SHA and rejects known old runtime/harness identities;
- long lanes call current production Mediator flows;
- targeted probes call current production handlers/adapters rather than copied FSM logic.

Current intended use:

- Harness = targeted real-machine diagnosis and integration testing;
- final desktop production package = later formal Natural E2E / Golden Run.

## 7. Real-machine GT — next decisive phase

Freeze this pair for the next live episode:

- Production: `dc108892d8590c04828dc176482bee32ba348914`
- Harness: `4b19e1005690509dc243dd1870a035422c10e640`

Do not patch while a probe is running. For every FAIL, save bundle/trace/screenshots before changing code.

Recommended order:

### 7.1 Lobby first

Validate independently:

- valid room join -> real ROOM_WAITING;
- full-room/pending-join dialog -> close/reject -> fresh lobby -> continue next room;
- password/other join-reject dialogs;
- true room child HWND is not mistaken for a popup;
- full-screen/layout variant;
- kicked/dissolved -> fresh lobby -> continue searching;
- in-game failure -> red exit -> fresh exit -> hitch LOBBY_ROOM -> no ERROR;
- normal round exit -> hitch LOBBY_ROOM -> no NEXT timeout.

### 7.2 Targeted single-player/business probes

Then test:

- bond / core skill;
- hero evolve;
- devour pill;
- treasure;
- inventory/hero-card path;
- black merchant;
- archive challenge 1..8 (especially the previously missed slot);
- heirloom/configured Boss compliance;
- secret realm complete entry chain.

A targeted PASS proves the feature itself can close on real GT. A long-chain PASS then proves orchestration/integration does not break it.

### 7.3 Long chains

After targeted probes:

- 13 lobby-hitch full chain;
- 12 solo full chain;
- 11 hitch in-game full chain.

## 8. Product issues intentionally not solved by S0

Do not confuse S0 stability work with gameplay-policy intelligence.

Still open after S0:

- bond logic is not yet intelligent enough;
- early-game policy should strongly prioritize bond + core skill formation;
- devour pill should accelerate bond formation without embedding inventory logic into the bond-panel FSM;
- evolve/treasure/inventory/black-merchant actions still need real-machine closure and smoother orchestration;
- core-vs-secondary stage/action priority needs a formal product contract;
- archive challenge can still miss an item until current-SHA GT closes it;
- heirloom/configured Boss compliance needs repeated GT;
- secret realm still lacks a proven complete successful real-machine chain.

Planned later waves after S0 real validation:

- `S1 = In-game Priority / Bond Intelligence`
- `S2 = Action Closure (evolve / treasure / inventory / merchant)`
- `S3 = Post-game Closure (archive / heirloom / Boss / secret realm)`

Policy v0.1 remains HOLD until S0 validation.

## 9. Release / integration status

Current integration branch remains:

`trial-merge@d1fb4a51310f3f847ebeee110d51d8423050468b`

Do not merge S0 into `trial-merge` yet.

Before integration/release:

1. current-SHA real-machine GT;
2. adapt/integrate the `c5589d4` CI/test improvements onto the final candidate;
3. run Standard CI / Standard Release Gate on the actual final candidate;
4. repeated real-machine Golden Path, recommended 10 consecutive rounds;
5. explicit Strict Zero-Defect / Frozen OCR release gates;
6. only then resume Policy/S1 and main/trial ancestry reconciliation.

Current exact S0 candidate `dc108892` has no GitHub-hosted CI run attached yet. Local regression results may be used as evidence but must not be mislabeled remote CI.

## 10. Immediate next-session instructions

A new conversation should:

1. read this file first;
2. read `docs/COMPETITOR_ASSET_LANDING_STATUS_20260908.md` if architecture status matters;
3. independently verify `trial-merge`, `refactor/stability-s0-20260908`, `test/ci-speed-and-stability-harness-20260908`, and `test/live-harness-current-20260908` before trusting any fresh Agent report;
4. treat `dc108892 + 4b19e100` as the current frozen live-test pair unless refs have advanced;
5. consume real-machine bundles before proposing further production changes;
6. keep competitor research, Policy v0.1, and main reconciliation on HOLD unless the current gates explicitly clear them.

Do not let a later Agent silently replace real GT with click success, replay success, frame mutation, or self-reported test counts.
