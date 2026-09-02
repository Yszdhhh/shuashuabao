# Release Security Blockers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development or executing-plans to implement this plan task-by-task.

**Goal:** Close the repository-addressable findings from the cloud release-security review and create one clean, independently reviewable commit on `trial-merge` without including the existing lobby/material dirty work.

**Architecture:** Preserve the existing Ed25519 and layered LIVE gates. Add the missing production boundary checks at the narrowest shared functions: frozen builds use a non-overridable device identity, Permit payloads enforce domain and lifetime, replay claims survive process boundaries through a standard-library SQLite store, manifest identity uses one canonical hash, package verification rejects extra/reparse files, external build rejects in-tree signing keys, and Dashboard evidence uses the same signed snapshot verifier as LIVE.

**Tech Stack:** Python standard library, existing `cryptography`, PowerShell 5.1-compatible build script, pytest.

**Spec:** `docs/SIGNED_ENTITLEMENT_PROTOCOL.md` plus the attached cloud review findings SEC-01..SEC-07 and REL-01.

## Global Constraints

- Canonical root: `G:/刷刷宝/GameScript-Local`.
- Target: `trial-merge`; current remote/base: `c120eaf4296736f497be8c1814f5ea251e68b14b`.
- Existing dirty lobby/capture/material files are user work and must not enter the security commit.
- No new dependency.
- External production prerequisites that do not exist in this repository (Subscription Server, operator keys, CA certificate, real package evidence) remain explicit BLOCKED prerequisites; do not fabricate them.
- Every behavior change gets a failing test first, then the full affected test module.

### Task 1: Permit domain, device identity, lifetime, and replay

**Files:** `src/shuabao/subscription_client.py`, `src/shuabao/subscription_permit.py`, `src/shuabao/shell/live_execute.py`, related permit/client tests.

- Add fixed signed `product_id`, `audience`, and `issuer` fields; reject mismatch before replay claim.
- Enforce a maximum Permit lifetime of 15 minutes.
- Frozen external LIVE must ignore `SHUABAO_SUBSCRIPTION_DEVICE_FINGERPRINT`; source/dev test injection remains available only outside frozen mode.
- Replace the LIVE default process-only replay store with an atomic SQLite-backed store under the application-data boundary; retain `InMemoryReplayStore` for isolated unit tests.
- Add tests for wrong domain, overlong lease, frozen env override rejection, and cross-instance replay.

### Task 2: Release manifest and signing boundaries

**Files:** `src/shuabao/release_signing.py`, `src/shuabao/shell/live_execute.py`, `src/shuabao/shell/dashboard_facade.py`, `build_release.ps1`, release-signing tests.

- Add one canonical manifest identity helper and use it for envelope, LIVE Context, build identity, and Dashboard comparisons.
- Verify actual package files equal the signed manifest file set plus explicit metadata exceptions; reject symlink/junction/reparse paths.
- Reject external manifest signing keys resolved under the repository, `build`, `dist`, `assets`, `src`, `config`, or `ui-v2` trees.
- Keep runtime signature verification and Authenticode hooks; do not claim a signed installer or real CA evidence that is absent.
- Add tests for extra files, path-link/reparse handling where the host supports it, in-tree key rejection, and canonical identity consistency.

### Task 3: Dashboard evidence and CI closure

**Files:** `src/shuabao/shell/dashboard_facade.py`, `tests/test_sign_release_manifest.py`, existing dirty `tests/test_desktop_app.py` only if the isolated fix is retained.

- Make frozen Dashboard preflight call `verify_packaged_release_snapshot` with the pinned registry requirement instead of trusting unsigned sidecar metadata.
- Preserve honest `MISSING/STALE/BLOCKED` states when trust anchors are absent.
- Make the signer test deterministic on Windows console encoding without weakening the production error contract.
- Retain the existing `DevStartCapability` test correction that addresses the remote DesktopPanel failure.

### Verification and commit

- Run full affected Python modules, not only individual tests.
- Run the release gate relevant to the changed contract.
- Recheck `git diff --name-only` and ensure only security files/tests/plan are staged; exclude all pre-existing lobby/material dirty files.
- Commit with a security-specific message; do not push unless separately authorized after local verification.
