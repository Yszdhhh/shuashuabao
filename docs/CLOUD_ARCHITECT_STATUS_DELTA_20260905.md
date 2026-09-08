# ShuaBao Cloud Architect Status Delta — 2026-09-05

This is a docs-only control-tower delta to be read together with `docs/CLOUD_ARCHITECT_CONTROL_TOWER_20260905.md`. It records the latest converged state after Architecture Stage 1 integration and the subsequent subscription/VPS-B review work. Repository facts are distinguished from live-ops facts reported by the VPS agents.

## 1. ShuaBao integration state

Verified remote state before this docs-only commit:

- `origin/trial-merge`: `f30c777a0b4b77f5d6ad067cb1806dbd75c0106c`
- Stage 1 merge commit: `ed11a7e8bc8d4bb94b91c60e5b79db3af4f2cbd1`
- Architecture branch: `refactor/architecture-convergence-20260904` @ `82557e9fb41b255ec29f71052c42d9e850ca4702`

Architecture Stage 1 Tasks 1/2/3 are MERGED/PASS. Reported post-merge verification was `1474 passed, 13 skipped, 2 xfailed, 211 subtests`; `python tools/release_gate.py` PASS 4/4. `disconnect_modal_missing` remains the historical BLOCKED item and was not falsified.

Stage 2 remains HOLD. No real KK / SendInput / real-machine GT was executed as part of Stage 1.

Known P2 test-infra debt remains the Windows PyQt6/faulthandler interaction; the release gate uses `-p no:faulthandler` rather than masking pytest failure status.

## 2. Subscription control plane — G2.1

Separate repository: `Yszdhhh/shuashuabao-subscription-lab`.

Verified remote branch:

- `ops/release-lifecycle-g2-20260905` @ `306c66ab10b2a45b9e50e0e436981fd71c1b7fad`

Cloud review status: G2.1 code is accepted for production cutover, subject to normal deploy/rollback execution evidence.

Accepted G2.1 behavior:

- admin endpoints fail closed when `SUBSCRIPTION_ADMIN_PASSWORD` is unset; no `admin/admin` password fallback;
- `recommended_source_sha`, `recommended_manifest_sha256`, and `recommended_channel` survive environment re-seed when not explicitly overwritten;
- public release status is separated from internal operator metadata and does not expose `operator_note` / `updated_by` / `updated_at`;
- `/health` can expose a bounded non-secret `service_revision` / deployment marker for edge-to-origin identity proof;
- staging evidence was sanitized;
- production-import provenance audit reports `BASELINE_MATCH`.

The live production `:8010` state was still pre-G2 at the last operator report; G2 production deployment had not yet occurred. Do not claim G2 production PASS until an explicit cutover report proves the deployed revision, smoke matrix, persistence, signer stability, and rollback point.

`MIN_SUPPORTED`, session grace/continuous renewal, key rotation, and broad entitlement/device redesign remain DEFERRED / out of scope.

## 3. Public edge identity correction

A previous VPS-B report classified the Quick Tunnel as stale using `POST /v1/permits -> 404`. That evidence is invalid because the current permit contract is not a standalone `/v1/permits` route; permits are issued through entitlement validation with `permit_request` context.

Until a unique deployment revision can be compared between localhost production and the public edge, the correct classification is:

`PUBLIC_EDGE_IDENTITY_UNPROVEN`

After G2 production deployment, compare safe `/health` revision markers on localhost and the public Quick Tunnel. Only then classify `PUBLIC_EDGE_MATCHES_PRODUCTION` or `PUBLIC_EDGE_MISMATCH`.

Stable/fixed HTTPS hostname / Named Tunnel remains a later external-beta gate. Do not cut DNS as part of the G2 production cutover unless separately authorized.

## 4. VPS-B passive recovery state

Live-ops facts reported by the VPS-B agent:

- SSH password authentication disabled after key-login validation;
- management remains on the existing non-standard SSH port; stale default port firewall rule removed;
- dedicated `shuabao-backup` account created without sudo/docker/production-key authority;
- backup/restore/status directories are isolated with restrictive permissions;
- backup-only `age` encryption keypair exists; the private key remains on the recovery side and must not be copied to Primary;
- retention, disk/staleness guards, restore-validation timer, and passive health-probe timer were prepared;
- unrelated VPN services remain in place and are accepted for Phase 1 with isolation risk noted;
- no production PermitIssuer, production DB writer, permit signing private key, or manifest signing private key is present on VPS-B.

Current VPS-B verdict remains:

`NEEDS_PRIMARY_WIRING`

A previous restore rehearsal proved encryption/decryption/SQLite-integrity tooling, but its synthetic table names must NOT be treated as production-schema proof. The valid wording is `RESTORE_TOOLING_REHEARSAL_PASS` until a real consistent Primary backup arrives.

Real restore validation must discover the actual table set from `sqlite_master` and verify only tables that really exist. Current code baselines include tables such as `processed_events`, `subscription_bindings`, trial/local-license tables; G2 adds `release_policies` after deployment.

## 5. Remaining convergence sequence

The next system-level convergence should be minimal and sequential:

1. VPS-B produces a non-secret Primary backup wiring handoff (backup-only age public recipient + backup-only SSH destination/host-key verification information; never private keys/passwords in Git).
2. VPS-A/Grok performs one compact production-ops round: deploy accepted G2.1 to `:8010`, smoke and rollback proof, prove public edge revision matches production, export a consistent SQLite snapshot, encrypt with the VPS-B public recipient, transfer it off-host, and enable the bounded backup timer.
3. VPS-B validates the first REAL Primary encrypted backup: decrypt in isolated scratch, SHA/integrity check, discover actual schema, row-count sanity only, remove plaintext, and update the recurring restore check.
4. Only after the above three are PASS should the project decide the fixed HTTPS/Named Tunnel cutover and external-beta client/release work.
5. Architecture Stage 2 / real-machine business-transition work remains a separate explicit gate and is not automatically unlocked by subscription/backup completion.

## 6. Grok Bot usage policy

Grok Bot should now be treated as a scarce VPS-A production operator, not as the default architect/reviewer.

Use Grok only when a task requires VPS-A-local production state, process/systemd/tunnel/DB access, deployment/rollback, or secrets that must remain on VPS-A. GitHub code review, architecture analysis, test review, documentation, ShuaBao core work, and VPS-B work should be handled by the cloud architect/local agents/VPS-B agent instead.

The intended remaining Grok work is therefore small: one compact G2 production + edge proof + first real off-host backup wiring round, followed later by a separately approved fixed-hostname cutover if needed.

## 7. Safety invariants unchanged

The game automation invariants remain unchanged:

`Frame -> Perception -> Scene/FSM -> Policy -> Input -> Business Postcondition`

UNKNOWN / ambiguous / stale / unclassified evidence => ZERO INPUT. Click/SendInput success, frame change, button disappearance, bookmark, replay, or synthetic evidence alone are not business PASS. Business FSM advancement requires a fresh-frame explicit business postcondition. Recovery input must remain known-scene-authorized and bounded.
