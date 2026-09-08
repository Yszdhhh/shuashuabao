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

As of this cleanup pass, both stale draft PRs were closed without merge:

- PR #15 `feat(entitlement): isolated Windows entitlement client v1` -> CLOSED / SUPERSEDED / NOT MERGED.
- PR #16 `pilot(subscription): gate live start and stage lobby validation` -> CLOSED / SUPERSEDED / NOT MERGED.

There should be no open PRs after this pass.

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

- historical audit/review branches whose unique evidence value has not yet been explicitly checked.

## Legacy branch families requiring one final semantic sweep

The repository still contains many old short-lived branches, especially:

- `cursor/*`
- `work/*`
- old `fix/*`
- old `feat/*`
- `audit/*`
- `review/*`
- old `integration/*`
- `refactor/*`
- `release/*`
- older `codex/*`

Because the repository historically used content-snapshot consolidation that did not preserve ancestry, `git merge-base` / GitHub compare status alone is not sufficient to declare these refs safe to delete. A branch can appear graph-diverged while its semantic content has already landed in current trial.

Required final sweep per branch family:

1. identify unique commits/files vs current `d1fb4a5`;
2. classify unique material as `LANDED`, `SUPERSEDED`, `EVIDENCE_ONLY`, or `NET_NEW_REQUIRED`;
3. preserve any evidence-only material under an archive ref if still useful;
4. delete only `LANDED` / `SUPERSEDED` refs;
5. never merge a stale branch merely to make ancestry look clean.

## No-merge list

Do not merge/cherry-pick wholesale:

- `feat/entitlement-client-v1-20260829`
- `integration/subscription-lobby-pilot-20260831`
- `fix/release-bound-permit-client-20260903`
- `wip/concurrent-lobby-overlay-20260903`
- `wip/cloud-sync-local-overlay-20260903`
- `docs/policy-v01-contract-20260908` (docs already migrated content-exactly)

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
