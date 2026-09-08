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

## 4. Why Policy implementation is temporarily held

A local Grok read-only audit compared several same-game mature competitor scripts and found a high-value pattern:

- stability appears to come less from better CV and more from simpler control authority;
- mature competitors still use many templates, but typically constrain the active detector set by current window/job/page;
- recovery tends to be local rather than distributed among multiple watchdogs/fallback owners;
- long-run stability benefits from small cross-round transient state and clear reset boundaries.

Important evidence limitation:

The first Grok comparison used old ShuaBao `main@7edae990` for some detailed ShuaBao-side observations. Its architectural conclusion is useful, but current-ShuaBao implementation claims must be rechecked against `decb9b6/d1fb4a5` before becoming implementation requirements.

Current cloud spot-check already confirms:

- the old cross-window STAGE_SELECT issue is now fixed;
- window-role authority is improved but not fully unified;
- the large Phase/control surface still exists;
- Core Mediator has a 15s internal-cycle liveness path;
- RuntimeMediator still has a separate 15s HUD-confirmed ESC watchdog with its own bounded retry/error escalation;
- therefore duplicate liveness/recovery ownership remains a real current-SHA simplification candidate.

## 5. Current competitor-research task

Continue the same Grok thread with a second-stage **Deep Stability Decomposition**.

Priority:

`Competitor A > Competitor C >>> Competitor B`

Checkpoint 1 should deep-dissect Competitor A only and stop for review.

Allowed on authorized local competitor copies:

- static unpacking
- decompilation / IL / bytecode inspection
- PyInstaller/resource indexing
- string and call-graph analysis
- asset-to-job/page/function mapping

Do not bypass account authorization, network licensing, anti-cheat, or access-control mechanisms.

The target is not 100% source recovery. The target is to reconstruct the smallest stability architecture:

`startup -> process/window discovery -> HWND binding -> Job/Page -> active detectors -> action authority -> input -> postcondition -> retry/recovery -> round reset -> next round`

Key outputs:

- execution graph
- state lifetime map (`FRAME/PAGE/ACTION/ROUND/SESSION/PERSISTENT`)
- asset authority map
- failure/recovery matrix
- long-run stability mechanisms
- top simplicity advantages over ShuaBao
- unsafe competitor patterns not to copy

No ShuaBao code changes during this research.

## 6. Stability Simplification S0 — candidate, not yet implementation contract

After the deep competitor checkpoint and current-SHA cloud review, the likely next production wave is a narrowly scoped stability simplification before Policy v0.1.

Current candidate themes:

1. Unify `PLATFORM / GAME / UNKNOWN` window-role authority before page detectors obtain transition authority.
2. Make detector scheduling page/job-local on the Golden Path; unrelated detectors may provide high-confidence safety vetoes but should not independently jump the FSM.
3. Remove or consolidate duplicate liveness/recovery ownership, especially overlapping Core vs Runtime 15s mechanisms.
4. Separate observable scene state from minimum action-lifecycle memory: do not cache scene facts that can be re-observed, but retain request/input/fresh-postcondition correlation.
5. Reduce cross-round transient state and make round/session reset boundaries explicit.

Do not implement these until the competitor checkpoint is reviewed and a small S0 contract is frozen.

## 7. Safety invariants that remain non-negotiable

- `UNKNOWN / ambiguous -> ZERO INPUT`.
- Click/key/SendInput success is not a business postcondition.
- A frame mutation/bookmark/fingerprint change is not business success by itself.
- Business transition requires fresh, business-relevant evidence.
- Perception recovery, input recovery, and business fallback are different concepts.
- UNKNOWN may trigger bounded re-observation/reacquisition, but UNKNOWN alone never authorizes blind ESC/QUIT/HOME.
- Do not weaken tests, thresholds, fixtures, or baselines to create a PASS.

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

1. Grok Competitor-A deep stability checkpoint (read-only).
2. Cloud current-SHA validation and freeze of a minimal Stability Simplification S0 contract.
3. Local production Agent implements only that S0 scope.
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
