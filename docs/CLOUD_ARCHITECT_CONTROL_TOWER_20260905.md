# ShuaBao Cloud Architect Control Tower — 2026-09-05

> Purpose: a cloud-side control-tower handoff for the next ChatGPT/cloud reviewer or a new conversation window. It summarizes the latest accepted architecture decisions, current workstreams, trust boundaries, merge order, and stop conditions.
>
> This document is a coordination/status artifact. Repository facts are distinguished from operator/VPS facts that were reported from the live environment and are not independently reproducible from this repository alone.

## 1. Repository / release baseline

Repository: `Yszdhhh/shuashuabao`

Main integration branch: `trial-merge`

Verified integration baseline immediately before this document was created:

`f1d10ba7ebec2fa61f4a6210bd6ff07868b93d0c`

That SHA is the accepted Release P0 implementation and was fast-forwarded from `release/versioned-install-p0-20260904` after:

- full pytest: `1455 passed, 13 skipped, 2 xfailed`;
- `python tools/release_gate.py`: PASS;
- Windows launcher smoke: PASS;
- failed-install staging/atomicity regressions: PASS;
- rollback full package-validation regressions: PASS;
- launcher-before-pointer and legacy-archive-after-shortcut-proof ordering regressions: PASS.

The commit that adds this document advances `trial-merge` by one docs-only commit. Future agents MUST verify the actual current `origin/trial-merge` SHA rather than assuming `f1d10ba...` is still HEAD.

### Release P0 accepted model

The old mutable deployment:

`Desktop/ShuaBao/ShuaBao.exe`

has been replaced by a versioned-install model under canonical app data:

- `app-<version>-<channel>-<source12>/`
- stable `launcher/`
- atomic `current.json`
- current + previous rollback
- desktop shortcut points to the stable launcher, not directly to one versioned EXE.

Important accepted invariants:

1. bundle copies to `.staging`, validates, then renames to final `app-*`;
2. incomplete failed installs do not become final immutable version dirs;
3. rollback reuses package validation and checks attested file hashes;
4. stable launcher is written before `current.json` is switched;
5. old mutable Desktop install / old shortcuts are archived only after new package validation, harness, promotion, launcher creation, and shortcut readback proof succeed;
6. Release P0 does NOT change subscription/permit trust semantics.

External-beta frozen release is NOT yet declared PASS. A real external build with operational signing credentials/Authenticode remains a later release gate.

## 2. Frozen trust model — do not redesign casually

Current release/LIVE identity is intentionally bound across:

- device identity;
- `source_sha`;
- canonical `release_manifest_sha256`;
- `release_channel`;
- `mode_id` / allowed modes.

The permit verifier is fail-closed and the permit maximum lifetime is short (15 minutes in current client code). Current design does not imply a continuously renewed session lease.

Do NOT casually adopt the following ideas without a dedicated proof/audit:

- moving `release_channel` out of the signed manifest / trust boundary;
- adding expiry to the immutable local release manifest;
- introducing session grace / continuous renew semantics;
- active-active subscription nodes;
- full TUF/update framework;
- delta updater;
- broad Nuitka/PyArmor/anti-debug work;
- resource hot-update as a secrecy mechanism.

Recommended separation remains:

- immutable local release manifest = provenance/integrity identity;
- freshness/expiry = online release feed / permit / trusted-key metadata when later needed.

## 3. Core automation architecture decisions

The core game architecture remains:

`Frame -> Perception -> Scene/FSM -> Policy -> Input -> Business Postcondition`

Hard invariants:

- UNKNOWN / ambiguous / stale / unclassified evidence => ZERO INPUT;
- click/SendInput success is not business PASS;
- frame change/button disappearance/bookmark/synthetic replay alone are not business PASS;
- only a fresh-frame explicit business postcondition advances business FSM;
- recovery may input only from independently recognized whitelisted known recovery scenes;
- no generic UNKNOWN -> ESC/back/home fallback;
- mechanical retry may be shared; business fallback stays in caller Policy/FSM;
- one decision should use one fresh frame authority/generation;
- retry must be time/attempt/rate bounded and must re-observe the same precondition;
- no second FrameEvidence, second action FSM, second incident service, second OCR service, BT, workflow DSL, or generic game engine unless a later audit proves existing types cannot express the invariant.

Existing architecture to reuse:

- `FrameEvidence`
- `MatchResult`
- `ActionLifecycle`
- `PendingAction`
- `InteractionSurface`
- `IncidentArchiver`
- existing matcher/color helpers
- existing production OCR bootstrap/client

## 4. Architecture-convergence workstream

Branch:

`refactor/architecture-convergence-20260904`

Original audit base:

`59833447b40706c533b4caecddcb94c3ee32e9f1`

Stage 0 audit: PASS.

Stage 1 Task 1 (typed expected-value OCR): PASS and cloud-reviewed.

Task 1 accepted rollback point:

`4aa065554206556746f6ef3a2f938d45a15db0ca`

Task 1 accepted behavior:

- one `verify_expected_text()` authority for bounded expected-value OCR;
- NFKC normalization on observed and expected values;
- empty/overlong/disallowed values fail closed;
- exact equality, not containment/fuzzy acceptance;
- strict bounded counter parser;
- lobby helper delegates expected-value authority to the verifier;
- no production OCR service/model rewrite.

Known non-blocking P2 debt: settings-loading normalization for `hitch_stage_prefix` still has historical truncation/default behavior that is not the Task 1 match authority. Do not mix this cleanup into unrelated Task 2 work without a focused contract/test.

### Approved remaining Stage 1 scope

Task 2: reset only proven transient state at real episode boundaries.

Fields identified by Stage 0/plan include:

- `_pending_action`
- `_pending_action_unconfirmed_count`
- runtime watchdog HUD latch
- `_hitch_floor_exit_pending`
- `_hitch_floor_exit_confirmed`

Do not reset unrelated transition budgets/timers without a failing regression proving leakage.

Task 3: bound ONE existing mechanical recovery path (preferred candidate: runtime watchdog ESC unstuck, if actual code/test evidence supports it).

Required Task 3 invariants:

- known-scene authority;
- one mechanical target;
- bounded attempts/deadline;
- fresh postcondition;
- click success alone never advances business state;
- UNKNOWN produces zero input;
- retry re-observes same precondition;
- no second retry/recovery framework.

The intended unattended execution boundary is the END OF STAGE 1:

sync latest `trial-merge` -> Task 2 + review/fix -> Task 3 + review/fix -> full pytest -> release gate -> push branch -> STOP.

Do NOT auto-enter Stage 2 or real-machine KK/SendInput work.

Current execution status after Task 1 is not assumed here; the next reviewer must inspect the branch/agent report to determine whether Task 2/3 have already started or completed.

## 5. Grok Bot / subscription control-plane — live ops facts

The following are operator/live-environment facts reported from the Grok Bot/VPS-A audit and G1 cutover, not facts derivable solely from this repository.

G1 production cutover verdict: `PRODUCTION_CUTOVER_PASS`.

Reported production state:

- previous production tree: `46d9aaf...`, dirty/old, no PermitIssuer;
- validated candidate: `c9e1aa44e1f0c195560604e9767dffc7d3a3e67e`;
- actual deployed production: `c9e1aa44e1f0c195560604e9767dffc7d3a3e67e`;
- production listener: uvicorn on `:8010`;
- PermitIssuer: present in production;
- production permit signer key id: `shuabao-prod-2`;
- entitlement regression: PASS;
- exact release binding negative tests: PASS;
- no destructive DB/schema migration;
- no session-grace/continuous-renew product was added;
- rollback point/runbook was preserved by the ops agent.

Current main external-beta blocker on the control plane:

- stable/fixed HTTPS hostname is NOT ready; temporary Quick Tunnel remains in use.

Do not treat a temporary tunnel hostname as a formal external-beta endpoint.

### Grok G2 planned boundary

The next approved design is a THIN release lifecycle on top of the existing exact release approval fact source:

- approved (already exists)
- blocked
- recommended
- outdated
- `min_supported` only if current data/version model supports it safely

Semantics:

- BLOCKED => no new permit, stable code `RELEASE_BLOCKED`;
- not approved => `RELEASE_NOT_APPROVED`;
- recommended/outdated are advisory and must not bypass or replace exact permit binding;
- no entitlement/device redesign;
- no session grace;
- no key rotation/movement;
- no remote game-policy/input authority.

Safe unattended boundary for G2:

implement/test -> isolated/staging listener -> contract matrix/soak -> production rollout + HTTPS runbook -> STOP.

Do NOT auto-deploy G2 to production or change production DNS while the user is away unless a separately authorized task explicitly grants that action.

## 6. VPS-B workstream

VPS-B is a PASSIVE RECOVERY NODE, not a second production brain.

Confirmed by the user at this handoff: the FIRST VPS-B task has already been dispatched and is currently running.

Therefore DO NOT start a second competing VPS-B agent/task in parallel.

The later, more detailed “target mode” VPS-B plan is a continuation/extension of the same workstream, not a separate node/project.

The first task already substantially covers:

- host baseline/inventory;
- passive backup receiver design/setup within safe bounds;
- restore rehearsal/readiness;
- external health probe;
- no production API/signer/DB-writer role.

Let the currently running VPS-B agent reach its defined STOP and inspect its report before issuing another task. A follow-up should be incremental only for gaps such as:

- minimum hardening not completed;
- backup retention/disk guard;
- receiver wiring to Primary;
- first real encrypted backup arrival;
- restore rehearsal against a real Primary backup;
- timers/alerts/health-probe persistence.

Hard VPS-B boundaries:

- no production PermitIssuer;
- no production DB writer;
- no production permit signing private key;
- no manifest signing private key;
- no active-active;
- no automatic DNS failover;
- no new monitoring platform unless proven necessary.

## 7. Current workstream ordering / merge strategy

Preferred convergence order:

1. Release P0: DONE and merged to `trial-merge`.
2. Architecture Stage 1: sync latest `trial-merge`, finish Tasks 2/3, full gate, cloud review.
3. Grok G2: isolated/staging only until cloud/user production review.
4. VPS-B first passive-recovery task: allow current running agent to finish; then review gaps before follow-up.
5. Stable HTTPS hostname: explicit ops decision/change window.
6. Release P1 / external-beta client integration: only after server release-lifecycle + hostname contract are stable.
7. Architecture Stage 2 / real business transitions / real-machine GT: explicit later gate; do not start automatically.

Do not run multiple agents that modify the same ShuaBao core files/worktree concurrently.

## 8. External-reference conclusions already accepted

External projects are pattern references, not frameworks to import.

Useful patterns:

- Airtest: bounded visual loop/timeouts;
- ok-script: simplest recognizer by semantic job + scene-local scheduling;
- MAA/MaaFramework: RGB/HSV color evidence can supplement template shape evidence; current upstream fusion fact previously verified as direct multiplication, not the stale geometric-mean claim;
- OAS/OnmyojiAutoScript: typed OCR and bounded polling/intervals;
- Alas: known-scene recovery, bounded waits, click rate limiting, incident evidence.

Rejected overreach:

- broad YOLO replacement for fixed UI;
- Behavior Tree/statechart migration;
- workflow task DSL in recognition config;
- universal recovery actions from UNKNOWN;
- framework duplication around already-existing FrameEvidence/ActionLifecycle/IncidentArchiver.

## 9. Release/control-plane recommendations currently classified

ADOPTED / IN PROGRESS:

- immutable release identity;
- versioned install dirs;
- stable launcher/current pointer;
- N-1 local rollback;
- UI/log release identity visibility;
- production PermitIssuer cutover;
- passive VPS-B backup/restore/health role.

ADOPT SOON, after current reviews:

- thin blocked/recommended/outdated lifecycle;
- stable HTTPS hostname;
- signed update/release status feed or notification-only update contract;
- operational Authenticode external-beta build.

DEFER / EXPERIMENT LATER:

- one small Cython/Nuitka protection experiment only after release reproducibility is stable;
- warm standby VPS-B only after passive backup/restore is proven;
- signed resource pack for fast vision fixes, if later needed.

REJECT FOR NOW:

- active-active VPS;
- 24–72 hour offline permit lease;
- full TUF implementation;
- delta patching;
- project-wide obfuscation/anti-debug stack.

## 10. What the next cloud architect must do first

Before making any new recommendation:

1. fetch/verify current `origin/trial-merge` HEAD;
2. inspect `refactor/architecture-convergence-20260904` current HEAD and agent report;
3. treat Grok production and VPS-B status as OPS facts requiring their latest reports, not repository assumptions;
4. read these existing architecture docs:
   - `docs/ARCHITECTURE_CONVERGENCE_20260904.md`
   - `docs/LOCAL_AGENT_REFACTOR_HANDOFF_20260904.md`
   - `docs/FABLE_EXTERNAL_REVIEW_NOTES_20260904.md`
   - `docs/LOCAL_AGENT_EXTERNAL_REFERENCE_ADDENDUM_20260904.md`
   - `docs/ARCHITECTURE_STAGE0_AUDIT_20260904.md` (on architecture branch if not yet merged)
   - `docs/RELEASE_P0_INSTALL_AUDIT_20260904.md`
5. do not claim real-machine business PASS from pytest, replay, click success, or synthetic evidence;
6. preserve UNKNOWN zero-input and explicit business postcondition requirements;
7. prefer minimal diffs and existing architecture reuse over new abstractions.

## 11. Next control-tower checkpoint

The next useful whole-system review should happen when the following reports are available:

- Architecture Stage 1 final report;
- Grok G2 isolated/staging final report (if G2 has been dispatched);
- VPS-B first-task final passive-recovery report.

At that checkpoint decide together:

1. Architecture Stage 1 merge / no-merge;
2. Grok G2 production deployment / hold;
3. VPS-B official daily backup enrollment / follow-up gaps;
4. stable HTTPS hostname cutover plan;
5. Release P1 / external-beta unlock;
6. whether to enter Architecture Stage 2 and real-machine GT work.

Until then, do not add another broad architecture/release workstream.
