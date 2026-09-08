# ShuaBao Git Cleanup Manifest — 2026-09-08

> Control-tower cleanup manifest. This file is documentation-only and lives on `handoff/latest`.
> Do not merge this branch into production merely to carry status notes.

## Current primary refs

KEEP:

- `main` -> old public snapshot; do not move until final stability/release convergence.
- `trial-merge` -> active integration, currently `d1fb4a51310f3f847ebeee110d51d8423050468b`.
- `handoff/latest` -> canonical control-tower documentation.
- `archive/final-green-trial-20260908` -> immutable production-code green baseline `decb9b6...`.
- `archive/final-policy-base-20260908` -> immutable docs-migrated baseline `d1fb4a5...`.
- `archive/old-main-20260908` -> immutable old-main anchor `7edae99...`.
- `integration/reconcile-main-trial-20260908` -> pre-stability ancestry-repair candidate only; keep, do not merge yet.

## Open PR cleanup

Both stale draft PRs were closed without merge:

- PR #15 `feat(entitlement): isolated Windows entitlement client v1` -> CLOSED / SUPERSEDED / NOT MERGED.
- PR #16 `pilot(subscription): gate live start and stage lobby validation` -> CLOSED / SUPERSEDED / NOT MERGED.

Current open PR count after the cleanup pass: 0.

## Confirmed superseded branch candidates

These branches have already been semantically reviewed by the control tower. They must not be merged or cherry-picked wholesale into current trial.

### Strong delete candidates after remote-ref deletion is explicitly executed

- `feat/entitlement-client-v1-20260829`
  - stale alternative entitlement architecture;
  - PR #15 closed as superseded.

- `integration/subscription-lobby-pilot-20260831`
  - stale pilot architecture;
  - PR #16 closed as superseded.

- `fix/release-bound-permit-client-20260903`
  - current trial already contains the intended release-bound permit behavior plus later hardening.

- `wip/concurrent-lobby-overlay-20260903`
  - stale experiment;
  - contains timeout-driven presumed search confirmation and must not be resurrected.

- `wip/cloud-sync-local-overlay-20260903`
  - old WIP;
  - its one useful stage-page ownership guard has now been independently reimplemented and regression-tested in current trial.

These refs may be deleted once a local/authorized Git client performs the remote ref deletion. No production content depends on merging them.

## Semantic branch sweep — Pass 1

Reference target for this pass:

`trial-merge@d1fb4a51310f3f847ebeee110d51d8423050468b`

### LANDED_BY_ANCESTRY / SAFE_REF_DELETE

For each branch below, GitHub compare proves the branch tip is an ancestor of `d1fb4a5` (`status=ahead` from old tip to current trial, `behind_by=0`). Deleting the branch ref therefore loses no commit history. This is a ref-retention statement only; it does not endorse every historical design choice in the old commit.

- `release/versioned-install-p0-20260904@f1d10ba7ebec2fa61f4a6210bd6ff07868b93d0c`
- `refactor/architecture-convergence-20260904@82557e9fb41b255ec29f71052c42d9e850ca4702`
- `fix/formal-auth-release-closure-20260905@c2a1f73945cd2f7f72eeca258a45957e758a931b`
- `fix/release-signing-closure-20260903@d10f73a4de06df125471e1c37e574faaf6187c0b`
- `codex/live-test-handoff-20260831@dcbc7b4fa6b52e75fe6746e0b12835531f275a43`
- `feat/web-shell-align-20260826@64de316002d6f367b475b7ab5179eb799e5dc759`
- `codex/ocr-hybrid@20679520b4134b056557ed7d2f6ba8be289177ca`
- `cursor/treasure-negative-fixtures-5d04@82cd732a3732f49a52e3ad9585bc55bc302355f1`
- `cursor/choice-policy-wiring-l1-9866@7f642f76c1ea717c154c46dad028cb637e2c900f`
- `cursor/b-card-lexicon-bidirectional-1245@21f0528e2baaca62990de42e38106eb1bc5603ca`
- `cursor/learning-mode-replace-dry-run-bb96@cb7df0c1dd1b4c7fd4128941cd32fdc184a1cd1e`

Special note: `cursor/b-card-lexicon-bidirectional-1245` historically included a baseline-refresh / platform-skip change that should not be treated as a design precedent. Its ref is safe to delete only because that commit is already retained by current ancestry.

### DIVERGED / HOLD FOR SEMANTIC DECISION

Do not delete these merely because they are old. Each retains unique/diverged material or evidence that still needs a disposition:

- `cursor/setup-dev-environment-7bf3@0cb08e47f3f5a31d63f3dd7b10016ed66e61385b`
  - `NET_NEW_NONPRODUCTION_DEV_ENV / HOLD_UNTIL_TOOLING_DECISION`;
  - unique Cloud Agent `.cursor/environment.json` + install tooling; current production tree does not carry the same `.cursor` setup.

- `feat/ui-quickstart-wizard-and-stability-v1@7170c8c910e193bf7521329effb7e26c34aea912`
  - `HOLD`;
  - changed startup/window/UNKNOWN liveness semantics; requires current-SHA semantic spot-check before deletion.

- `fix/choice-panel-liveness-20260818@abf3d351140093f5027d3e26b009704cda6fff15`
  - `HOLD`;
  - OCR sidecar/family-source/live-OCR behavior likely superseded but not yet proven semantically.

- `infra/integration-clean-20260816@6f80f016df8a4efec5c6004fc437f7b1f574dd28`
  - `EVIDENCE/HISTORICAL_DOCS / HOLD`;
  - tip is documentation-only normalization from an older integration line.

- `stabilize/runtime-foundation-v1@54d0d4c23a0a41de0e81f298582cf289bd535cfa`
  - `STALE_ALTERNATIVE_RUNTIME_UI / HOLD` pending final semantic decision.

- `integration/core02-core03-20260816@ab4242fb13ddb66355093fbd4748e23133e974ab`
  - `EVIDENCE_ONLY / HOLD`;
  - historical reference-script deconstruction material.

- `fix/state-alignment-stability-20260818@77e42011084d25384c60c14557da97fb4aa81091`
  - `EVIDENCE_ONLY / HOLD`;
  - same tip as `work/state-alignment-execution-20260818`; likely duplicate evidence refs.

- `work/state-alignment-execution-20260818@77e42011084d25384c60c14557da97fb4aa81091`
  - `EVIDENCE_ONLY / HOLD`; duplicate-tip candidate.

- `work/state-alignment-gated-v2-20260818@dac5cf17f6ef580d9fe5cde18378f7148de82538`
  - `HOLD`; old formal-gate/CI line.

- `work/state-alignment-gated-v3-20260818@064f9cb4f6367383f2a0678880e6bae29b9bc473`
  - `HOLD`; old formal-gate/CI line.

- `work/choice-liveness-execution-20260818@e9ad9516be9c40fa2baa399bc35ca8470a20f9d5`
  - `EVIDENCE_ONLY / HOLD`; tip records a historical live liveness incident.

- `work/choice-liveness-gated-20260818@00cbf9477ec0237509a9c02f2146256fae6a29da`
  - `HOLD`; old CI regression-alignment line.

- `work/choice-liveness-trigger-20260818@53f45990722711891dbae3a468b4d2993e39cc50`
  - `HOLD`; old CI rerun trigger line.

- `fix/incident-20260818-ocr-treasure-deadlock@73f6a0515635b43f9d617e0a6d1dae5bf29a5ce8`
  - `HOLD`;
  - tip changes bond-pick behavior after presets complete; requires current Policy semantic check before deletion.

- `review/e496e95-full-audit-20260820@e496e9520436580435f2695b2d96c0cfb1a20b25`
  - `FORENSIC_EVIDENCE_ONLY / UNTRUSTED_KB / HOLD_OR_ARCHIVE`;
  - mixed analyst/video-derived mechanics and KB claims must not be merged as production truth.

- `audit/20260814@1edb9aedab2fe573b3820819891e8c6dbacd3c9d`
  - `EVIDENCE_ONLY / HOLD`;
  - historical cloud audit provenance.

### Cleanup rules frozen by Pass 1

1. If an old branch tip is an exact ancestor of `d1fb4a5`, the branch ref is safe to delete because history remains reachable.
2. If a branch is diverged, age is not enough. First classify its unique material as `SUPERSEDED`, `EVIDENCE_ONLY`, `NET_NEW_REQUIRED`, or `HOLD`.
3. Never merge a stale branch merely to preserve history or make the graph look cleaner.
4. Branch-ref deletion is not design endorsement.
5. The cloud connector currently has no remote branch-delete action. No branch refs have been deleted by this control-tower pass.

## Preserve as evidence/archive for now

Do not delete yet:

- `test/solo-live-harness-20260907`
  - harness/evidence archive; contains useful non-production capture/test work.

- `stability/night-ablation-20260907`
  - preserve until stability-simplification evidence review is complete.

- `docs/policy-v01-contract-20260908`
  - immutable original Policy v0.1 docs source; content already migrated to `d1fb4a5`, but keep as provenance until Policy implementation begins.

- `archive/pre-main-consolidation-20260828`
  - historical content-snapshot anchor; useful while ancestry reconciliation is not final.

- historical audit/review branches listed above until their evidence has a durable destination or an explicit archive/delete decision.

## Remaining sweep scope

Pass 1 substantially reduced uncertainty but does not authorize indiscriminate deletion of all old refs. Remaining work is primarily:

1. resolve the diverged HOLD branches above;
2. decide whether the unique `.cursor` dev-environment branch is still useful;
3. archive or retire duplicate historical evidence refs;
4. keep `test/solo-live-harness-20260907` and `stability/night-ablation-20260907` until Stability S0 evidence use is complete;
5. produce the final local `git push origin --delete ...` list only after semantic disposition is complete.

## No-merge list

Do not merge/cherry-pick wholesale:

- `feat/entitlement-client-v1-20260829`
- `integration/subscription-lobby-pilot-20260831`
- `fix/release-bound-permit-client-20260903`
- `wip/concurrent-lobby-overlay-20260903`
- `wip/cloud-sync-local-overlay-20260903`
- `docs/policy-v01-contract-20260908` (docs already migrated content-exactly)
- `review/e496e95-full-audit-20260820` (forensic/historical evidence only)

## Main reconciliation hold

Do not move `main` yet.

`integration/reconcile-main-trial-20260908@1c8ef1a...` is content-identical to `d1fb4a5` and has the intended two-parent ancestry, but it was prepared before the new competitor-driven Stability Simplification S0 work.

Treat it as:

`PRE_STABILITY_RECONCILIATION_CANDIDATE`

not as the final release/main target.

Final main/trial convergence occurs only after:

- Stability Simplification S0 is defined and implemented if approved;
- repeated real Golden Path validation;
- explicit Strict Zero-Defect execution;
- explicit Frozen OCR release smoke;
- remaining required product GT closure.
