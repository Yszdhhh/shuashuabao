# ShuaBao Cloud Architect Control Tower — CURRENT

> Canonical handoff for the active ShuaBao control-tower state.
> Always read this file first from `handoff/latest`, then independently verify live Git refs before trusting any local Agent report.
> This branch is documentation-only. Do not merge `handoff/latest` into production merely to carry status notes.

## 0. Executive state

Repository:

`https://github.com/Yszdhhh/shuashuabao`

Current production-integration branch:

`trial-merge`

Current verified `trial-merge` HEAD:

`d1fb4a51310f3f847ebeee110d51d8423050468b`

Parent production-code baseline:

`decb9b6eb3559e39ea51e26864eaada0d648855b`

`d1fb4a5` differs from `decb9b6` only by the two frozen Policy v0.1 documentation files. No production code, tests, config, fixtures, thresholds, baselines, or workflows changed in that migration.

Current status:

- `FINAL_FREEZE_HYGIENE = PASS`
- `CORRECTIVE_C_RELEASE_DEBT = CLOSED`
- `STANDARD_CI = PASS`
- `STANDARD_RELEASE_GATE = PASS`
- `STRICT_ZERO_DEFECT = NOT_RUN`
- `FROZEN_OCR_RELEASE_SMOKE = NOT_RUN`
- `LOCAL_WINDOWS_LAUNCHER_GT = SELF_REPORTED_PASS`
- `PRODUCT_GOLDEN_RUN = NOT_RUN`
- `PRODUCT_RELEASE_APPROVAL = NO`
- `COMPETITOR_A_DEEP_DECOMPOSITION = COMPLETE_FOR_S0_REFERENCE`
- `STABILITY_SIMPLIFICATION_S0 = RESEARCH_ONLY / IMPLEMENTATION_HOLD`

Do not describe the current branch as full production-release PASS.

## 1. Frozen refs / Git topology

Durable refs created by the cloud control tower:

- `archive/final-green-trial-20260908` -> `decb9b6eb3559e39ea51e26864eaada0d648855b`
- `archive/final-policy-base-20260908` -> `d1fb4a51310f3f847ebeee110d51d8423050468b`
- `archive/old-main-20260908` -> `7edae9909ab1c757da27a45c4409f464aae66b04`

The old public `main` still points to:

`7edae9909ab1c757da27a45c4409f464aae66b04`

A two-parent ancestry-repair candidate exists at:

`integration/reconcile-main-trial-20260908`

candidate commit:

`1c8ef1ac53e2ee83dec73420f8ffef4aabb2b5a4`

Its parents are old `main` and `d1fb4a5`, and its tree is content-identical to `d1fb4a5`. It is currently a **pre-stability reconciliation candidate only**. Do not move `main` to it yet.

## 2. Final freeze hygiene closure

`decb9b6` closed the final two freeze-hygiene items.

### 2.1 Windows launcher capability semantics

The physical Desktop shortcut probe remains semantically equivalent to the actual operation:

- real Desktop
- Unicode `.lnk`
- VBS TargetPath
- WorkingDirectory
- Save
- COM read-back

If the equivalent capability probe fails:

- on GitHub Actions -> the physical-desktop section may be `SKIP / CI_ENVIRONMENT_NOT_CAPABLE`;
- on an ordinary local Windows host -> the test must `FAIL / LOCAL_WINDOWS_SHORTCUT_GT_FAILED`.

A local report stated the launcher smoke passed without skip. Cloud cannot independently execute the physical local desktop test, so this remains self-reported local GT.

### 2.2 Stage-page ownership

Current production now rejects explicit KK/platform-title frames before stage-row authority and requires game-client ownership before lobby hitch may transition to `STAGE_SELECT`.

This closes the known old WIP safety delta where KK/platform numeric rows could obtain stage-selection authority.

Do not cherry-pick the old WIP branch.

## 3. Policy v0.1 contract

Frozen source research baseline:

`a3bc4cdad0b11decaa578140e1a03c4b5380b8e7`

Frozen docs source commit:

`80e0bd89ee926bcf433f7492c9657f0b95f7c42b`

Canonical docs migrated content-exactly onto final trial at:

`d1fb4a51310f3f847ebeee110d51d8423050468b`

Files:

- `docs/policy/POLICY_V01_IMPLEMENTATION_CONTRACT_20260908.md`
- `docs/policy/POLICY_V01_EVIDENCE_APPENDIX_20260908.md`

The production Policy call path remained unchanged through the freeze and docs migration.

Policy implementation is currently **held** while a stability-simplification review is completed.

## 4. Same-game competitor stability research — current status

Canonical research synthesis:

`docs/COMPETITOR_STABILITY_DECOMPOSITION_20260908.md`

The first broad Grok audit and two subsequent Competitor-A checkpoints are now reviewed.

### 4.1 What survives current-SHA validation

High-value findings that remain useful:

- mature same-game tools may own hundreds of templates without running all of them as global authorities every tick;
- the important metric is the active detector/authority set for the current window/job/page, not total asset inventory;
- Competitor A exposes a narrower explicit shared orchestration surface: one abstract `Run`, 20 current concrete `Run` owners, and `LoopAction.Continue/Break` as a small visible return surface;
- common mechanical capabilities such as capture/input/quit live on a shared job base surface while business orchestration appears more subclass-local;
- this is evidence for **owner locality / narrow shared orchestration**, not proof that Competitor A is globally simpler or safer;
- long-run design should minimize unnecessary cross-round transient state and make reset ownership explicit.

### 4.2 Claims that were deliberately downgraded

Because the current Competitor-A production method bodies are obfuscated, these are NOT current-build facts:

- old named LaunchGame/BeginGame/CreateRoom/SelectStage execution order;
- `FindNodeWithTimeOut` as the current postcondition implementation;
- old infinite scrolling / exact historical thresholds;
- UNKNOWN always continuing instead of erroring;
- absence of global ESC/watchdog/fail-streak;
- old UIA/InputSimulator runtime behavior;
- Tesseract being on the active OCR path.

Missing readable metadata is not proof of runtime absence.

### 4.3 Precision on Competitor-A window ownership

`AutoJob.GameWindow` is an instance `InitOnly` field. This proves the reference field is per-instance and cannot be reassigned after construction. It does **not** prove:

- each job owns a unique underlying window object;
- the object is immutable;
- the underlying HWND cannot change internally;
- multiple jobs do not share the same referent.

Use this only as a narrow ownership-shape signal.

### 4.4 Current ShuaBao-side comparison

Current ShuaBao production still explicitly exposes:

- 21 top-level `Phase` values;
- `ChallengeState`;
- `RecoveryKind / RecoveryStep / RecoveryState`;
- `PanelState`;
- `ActionLifecycle`;
- `InteractionSurface`;
- general `PendingAction` state;
- lobby-specific hitch/follow state machines;
- bounded attempt/deadline objects;
- Mediator-owned session/transient latches.

These abstractions are not individually condemned. The risk is combinatorial authority: several locally correct FSMs, latches, watchdogs, deadlines, and fallback paths can compose into a much larger implicit control graph.

Current-SHA spot checks continue to support duplicate liveness/recovery ownership as a real simplification candidate, especially overlapping Core-vs-Runtime liveness mechanisms.

## 5. Current competitor-research task

Competitor A is now considered **sufficient for S0 reference**. Do not spend another broad reverse-engineering round on A unless a specific unresolved implementation question becomes blocking.

Next checkpoint:

`Competitor C — narrow structural and long-run stability cross-validation`

Purpose:

Determine whether the same high-value patterns independently recur in another same-game mature implementation:

- page/job ownership locality;
- active detector scheduling vs total asset inventory;
- window binding lifecycle;
- action/postcondition locality;
- recovery ownership;
- UNKNOWN handling;
- round/session reset boundaries;
- cross-round transient state.

This is cross-validation, not a second exhaustive reverse-engineering project.

Competitor B remains low priority unless a new authorized readable surface appears.

No ShuaBao production code changes during this research.

## 6. Stability Simplification S0 — candidate, not yet implementation contract

Current candidate principles are now better defined:

1. **Localize orchestration authority.** One clear business owner should progress the active page/job/episode. Shared capture/input helpers remain mechanical capabilities and should not independently progress business state.
2. **Restrict detector authority by verified window/page ownership.** Large template inventories are acceptable; only a bounded relevant set should hold transition authority for the current context.
3. **Separate observable scene state from action-lifecycle state.** Re-observe current scene facts where possible; retain only minimum request/input/fresh-postcondition correlation for genuinely asynchronous actions.
4. **One liveness/recovery owner per failure domain.** Core FSM, runtime wrapper, modal recovery, watchdog and fallback layers must not independently escape/progress the same failure.
5. **Make state lifetime explicit.** Classify important control state as `FRAME_LOCAL / PAGE_LOCAL / ACTION_LOCAL / ROUND_LOCAL / SESSION_GLOBAL / PERSISTENT`, with explicit reset owner/boundary.
6. **Prefer simplification/consolidation over new fallback layers.** S0 should remove or unify control authority before adding new detectors/retries/watchdogs.

Do not implement these until Competitor C cross-validation is reviewed and a minimal S0 contract is frozen.

## 7. Safety invariants that remain non-negotiable

- `UNKNOWN / ambiguous -> ZERO INPUT`.
- Click/key/SendInput success is not a business postcondition.
- A frame mutation/bookmark/fingerprint change is not business success by itself.
- Business transition requires fresh, business-relevant evidence.
- Perception recovery, input recovery, and business fallback are different concepts.
- UNKNOWN may trigger bounded re-observation/reacquisition, but UNKNOWN alone never authorizes blind ESC/QUIT/HOME.
- Do not weaken tests, thresholds, fixtures, or baselines to create a PASS.
- Do not copy proprietary competitor code or image assets into ShuaBao; extract architecture/stability principles only.

## 8. Release-gate distinction

A normal `trial-merge` push executes Standard CI, but current workflow design does not make Strict Zero-Defect or Frozen OCR execute on every normal push.

Therefore:

`STANDARD_CI = PASS`

is not equivalent to:

`PRODUCT_RELEASE_GATE = PASS`.

Before final main reconciliation/release, explicitly prove the required release gates and remaining real-machine GT.

## 9. Git cleanup / stale branch policy

Do not merge orphan branches merely because they contain unique commits.

Already classified:

- `fix/release-bound-permit-client-20260903` -> superseded by current trial; do not merge/cherry-pick.
- `integration/subscription-lobby-pilot-20260831` -> superseded by current trial architecture plus historical docs value; do not merge.
- `feat/entitlement-client-v1-20260829` -> stale alternative architecture; do not merge.
- `test/solo-live-harness-20260907` -> harness/evidence archive; preserve until any useful harness-only changes are deliberately ported.
- `wip/concurrent-lobby-overlay-20260903` -> stale experiment with unsafe timeout-driven confirmation; do not merge.
- `wip/cloud-sync-local-overlay-20260903` -> old WIP; its one useful stage-page ownership safety idea is now implemented in current trial; do not merge.
- `docs/policy-v01-contract-20260908` -> immutable source archive; its two canonical docs have already been migrated content-exactly to `d1fb4a5`.

Stale branches may be deleted only after durable archive refs exist where needed and after the cloud cleanup manifest confirms no remaining unique semantic value.

## 10. Immediate sequencing

Current recommended order:

1. Grok Competitor-C narrow stability cross-validation (read-only).
2. Cloud review of A+C evidence and freeze of a **minimal** Stability Simplification S0 contract.
3. Local production Agent implements only that frozen S0 scope.
4. Targeted tests + Standard CI.
5. Fresh real-machine Golden Path run, aiming for repeated consecutive rounds, not one lucky pass.
6. Re-audit Policy production call path and then start Policy v0.1.
7. Explicit Strict Zero-Defect / Frozen OCR / remaining product GT gates.
8. Only then finalize ancestry reconciliation and move `main` + `trial-merge` together to the same final commit.

Until step 8, keep:

- `main` at old snapshot,
- `trial-merge` as active integration,
- archive refs immutable,
- `integration/reconcile-main-trial-20260908` as a pre-stability candidate only.
