# ShuaBao Cloud Architect Control Tower — 2026-09-05

> Purpose: canonical cloud-side handoff for the next ChatGPT/cloud reviewer or a new conversation window.
>
> This document records the latest accepted repository state, live-ops evidence, architecture boundaries, workstream ordering, stop conditions, and the current product-development priority. Where historical sections or older status-delta documents conflict with this file, **this file is authoritative after the latest commit**.
>
> Evidence classes must remain distinct:
> - **GitHub independently verified**: branch/commit/file facts read directly from GitHub.
> - **Agent-reported local tests**: pytest/release-gate/local Windows results reported by an execution agent.
> - **VPS live-environment evidence**: production/backup/restore facts reported from VPS-A/VPS-B.
> - **Real-machine Ground Truth**: actual KK/game-machine business-path evidence. Never infer this from pytest/replay/click success.

## 1. Repository / release baseline

Repository: `Yszdhhh/shuashuabao`

Main integration branch: `trial-merge`

GitHub-verified `trial-merge` immediately before this handoff refresh:

`dc9e65bfaab7a7b645b7ec380aa299dd179e99d7`

This handoff refresh is docs-only and advances `trial-merge`; future agents MUST fetch the actual remote HEAD before doing any work.

Accepted Release P0 implementation baseline:

`f1d10ba7ebec2fa61f4a6210bd6ff07868b93d0c`

Accepted Release P0 model:

- versioned immutable install dirs: `app-<version>-<channel>-<source12>/`;
- stable launcher;
- atomic `current.json`;
- current + N-1 rollback;
- failed install does not pollute final version dirs;
- launcher is created before pointer switch;
- legacy archive only after new shortcut/package proof succeeds;
- Release P0 does not alter subscription/permit trust semantics.

Historical accepted Release P0 evidence reported by the local agent:

- full pytest: `1455 passed, 13 skipped, 2 xfailed`;
- `python tools/release_gate.py`: PASS;
- Windows launcher smoke: PASS.

Do not redesign Release P0 unless a concrete regression proves the current model insufficient.

## 2. Frozen release / trust boundary

Current release/LIVE identity remains bound across:

- device identity;
- `source_sha`;
- canonical `release_manifest_sha256`;
- `release_channel`;
- `mode_id` / allowed modes.

The permit verifier remains fail-closed. Current design does not imply a long offline lease or continuously renewed gameplay session.

Do NOT casually introduce without a dedicated proof/audit:

- removing `release_channel` from signed trust identity;
- expiry inside the immutable local manifest;
- session grace / continuous permit renewal;
- active-active subscription nodes;
- full TUF/update framework;
- delta updater;
- broad Nuitka/PyArmor/anti-debug work;
- resource hot-update as a secrecy mechanism.

Recommended separation remains:

- immutable local release manifest = provenance/integrity identity;
- freshness/expiry = online release feed / permit / trusted-key metadata when later needed.

## 3. Core game architecture — frozen safety invariants

The core architecture remains:

`Frame -> Perception -> Scene/FSM -> Policy -> Input -> Business Postcondition`

Hard invariants:

- UNKNOWN / ambiguous / stale / unclassified evidence => ZERO INPUT;
- click success / SendInput success is not business PASS;
- frame change / button disappearance / bookmark / synthetic replay is not business PASS;
- only a fresh-frame explicit business postcondition advances business FSM state;
- recovery may input only from independently recognized whitelisted known recovery scenes;
- no generic UNKNOWN -> ESC / Back / Home fallback;
- mechanical retry may be shared, but business fallback stays in caller Policy/FSM;
- one decision should use one fresh-frame authority/generation;
- retries must be attempt/time/rate bounded and must re-observe preconditions.

Reuse existing architecture first:

- `FrameEvidence`
- `MatchResult`
- `ActionLifecycle`
- `PendingAction`
- `InteractionSurface`
- `IncidentArchiver`
- existing matcher/color helpers
- existing production OCR bootstrap/client

Do not introduce without evidence:

- second FrameEvidence;
- second action FSM / VerifiedAction framework;
- second retry/recovery framework;
- second OCR service;
- second incident system;
- Behavior Tree;
- statechart migration;
- workflow DSL;
- generic game engine.

## 4. Architecture Convergence status

Architecture branch:

`refactor/architecture-convergence-20260904`

GitHub-verified accepted branch HEAD:

`82557e9fb41b255ec29f71052c42d9e850ca4702`

Stage 0: **PASS**.

Stage 1: **DONE / MERGED / PASS**.

Stage 1 merge commit on `trial-merge`:

`ed11a7e8bc8d4bb94b91c60e5b79db3af4f2cbd1`

Accepted Stage 1 scope:

1. Typed expected-value OCR verifier
   - NFKC;
   - bounded input;
   - exact equality;
   - malformed/overlong/invalid expected values fail closed;
   - containment/fuzzy matching is not expected-value authority.

2. Transient lifecycle reset
   - resets only proven leaking transient state such as `_pending_action`, `_pending_action_unconfirmed_count`, runtime-watchdog HUD latch, and hitch floor-exit transient state;
   - legitimate transition budgets are not globally cleared.

3. RuntimeWatchdog-EscUnstuck bounded recovery
   - ESC attempt cap = 2;
   - action-send success is not business PASS;
   - unverified recovery consumes budget;
   - budget exhaustion enters existing `Phase.ERROR`;
   - UNKNOWN receives no ESC authority;
   - no second recovery/action framework.

Agent-reported post-Stage1 verification:

- `1474 passed, 13 skipped, 2 xfailed, 211 subtests`;
- `python tools/release_gate.py`: PASS 4/4;
- `disconnect_modal_missing` remains historical BLOCKED and was not falsified.

Known P2 test-infra debt remains Windows PyQt6/faulthandler interaction; release-gate pytest uses `-p no:faulthandler` rather than hiding pytest exit status.

**Architecture Stage 2 = HOLD.**

Do NOT auto-enter Stage 2. Architecture work is now subordinate to concrete product-function blockers.

## 5. Subscription control plane / VPS-A — production closed and maintenance-only

Separate repository:

`Yszdhhh/shuashuabao-subscription-lab`

Accepted G2.1 branch:

`ops/release-lifecycle-g2-20260905`

Accepted G2.1 commit:

`306c66ab10b2a45b9e50e0e436981fd71c1b7fad`

Cloud code-review status before deployment: **PASS / approved for production cutover**.

VPS-A live-ops final verdict reported on 2026-09-05:

- `G2_PRODUCTION_CUTOVER_PASS`;
- `PUBLIC_EDGE_MATCHES_PRODUCTION`;
- `FIRST_REAL_PRIMARY_BACKUP_READY`;
- VPS-A operator: **STOP / MAINTENANCE_ONLY**.

Reported production live state:

- listener: `:8010`;
- deployed revision: `306c66ab10b2a45b9e50e0e436981fd71c1b7fad`;
- `/health service_revision`: same revision;
- production signer key id: `shuabao-prod-2`;
- signer was not rotated;
- rollback preserve point exists under `/home/box/services/_shuabao_preserve/g2-cutover-20260905T033826Z/` with pre-G2 revision `c9e1aa44...`;
- no destructive DB migration was reported.

Accepted G2 behavior now reported live in production:

- thin release lifecycle supports exact approval plus `BLOCKED`, advisory `recommended`, advisory `outdated`;
- public release status does not expose `operator_note`, `updated_by`, `updated_at`;
- admin endpoints fail closed without configured admin secret;
- recommended fields survive environment re-seed unless explicitly overwritten;
- `/health` exposes bounded non-secret `service_revision` for deployment identity proof;
- permit contract remains `POST /v1/entitlements/validate` with `permit_request` context;
- do not use `/v1/permits -> 404` as an edge-freshness test.

Current public edge is still a temporary Quick Tunnel. Local and public `service_revision` were reported equal at `306c66a...`, therefore the current classification is:

`PUBLIC_EDGE_MATCHES_PRODUCTION`

This does **not** make the Quick Tunnel an acceptable final external-beta endpoint.

Do not wake Grok for normal code review, documentation, architecture discussion, prompt writing, or routine test analysis. Grok is now reserved for unavoidable VPS-A production operations only.

## 6. VPS-B Passive Recovery Node — PASS and maintenance-only

VPS-B role remains strictly:

**PASSIVE RECOVERY NODE**

It must never become:

- production PermitIssuer;
- production DB writer;
- holder of production permit-signing private key;
- holder of manifest-signing private key;
- active-active peer;
- automatic DNS failover authority.

Reported Phase-1 host posture:

- Ubuntu 24.04;
- SSH key-only authentication;
- management port `50022/tcp`;
- dedicated non-privileged `shuabao-backup` account;
- isolated `/srv/shuabao-backup`, `/srv/shuabao-restore-test`, `/opt/shuabao-ops` paths;
- backup-only age encryption identity;
- retention / disk / staleness guards;
- passive health probe;
- recurring restore validation;
- existing Shadowsocks/Hysteria services left intact and accepted for Phase 1.

### First real Primary backup

VPS-A reported first off-host encrypted artifact:

`shuabao_backup_primary-substate-20260905T034025Z.tar.gz.age`

Primary-reported encrypted artifact SHA256:

`57a49d2922a26837ca8fef6929ad88e14b1fd8542ba938558340fc59b51bc84b`

VPS-B reported:

- `REAL_PRIMARY_BACKUP_INGESTED_AND_VERIFIED`;
- encrypted checksum/ingest completed;
- no claim of restore PASS until the later real restore validation.

### Final real restore validation

VPS-B final live-ops report states the first real Primary artifact was validated end-to-end in an isolated restore sandbox:

- encrypted artifact located in `/srv/shuabao-backup/archive/`;
- SHA256 recomputation reported MATCH against the Primary value / companion checksum;
- age decrypt: SUCCESS;
- restored SQLite: `subscription_state.db`, 77,824 bytes;
- reported `journal_mode = wal`, `user_version = 0`;
- `PRAGMA integrity_check = ok`;
- dynamic `sqlite_master` discovery, not synthetic hard-coded schema authority;
- close/reopen validation: PASS;
- plaintext scratch cleanup: PASS;
- recurring restore tooling compatibility: PASS;
- `shuabao-restore-validation.timer` remains active for daily UTC 03:30 validation.

Reported real user-table set and row-count sanity:

- `local_activations`: 4
- `local_licenses`: 6
- `processed_events`: 0
- `release_policies`: 0
- `subscription_bindings`: 0
- `trial_accounts`: 0
- `trial_devices`: 0
- `trial_reservations`: 0

Final accepted VPS-B verdict:

`REAL_PRIMARY_RESTORE_PASS`

`READY_FOR_PASSIVE_BACKUP`

`VPS-B = MAINTENANCE_ONLY`

No further VPS-B construction work is authorized unless a concrete backup/restore regression appears.

Note: the final pasted VPS-B report omitted the literal recomputed hash value in one field but explicitly reported MATCH against the already recorded Primary hash and companion checksum. This is treated as a P2 reporting omission, not a reason to reopen the node.

## 7. Off-host backup operating contract

Primary -> VPS-B backup is now reported operational.

Accepted properties:

- Primary creates a consistent SQLite snapshot (not bare copy of live WAL/DB);
- age encryption occurs before transfer;
- encrypted artifact + SHA256 are transferred;
- dedicated Ed25519 transport identity is used;
- VPS-B SSH target: `shuabao-backup@172.245.52.129:50022`;
- partial uploads are ignored until complete artifact/checksum pairing is present;
- encrypted archive is promoted only after checksum verification;
- real restore tooling dynamically discovers schema via `sqlite_master`;
- plaintext restore scratch is cleaned after validation.

Primary backup schedule reported live:

- every 6 hours via the existing VPS-A supervisor mechanism (VPS-A does not use systemd for this task).

VPS-B restore validation schedule reported live:

- daily UTC 03:30 via `shuabao-restore-validation.timer`.

Do not confuse transfer/ingest success with restore PASS; both have now been separately demonstrated for the first real Primary artifact.

## 8. External Beta status

External Beta is still **HOLD**.

Remaining major gates:

1. fixed HTTPS hostname / Named Tunnel / DNS cutover;
2. final external-beta client endpoint/identity integration;
3. operational Authenticode-signed external build;
4. any final external-beta-specific release smoke.

G2 production deployment and real off-host restore are no longer blockers.

Quick Tunnel is acceptable as current temporary live connectivity evidence but must not be treated as the final formal endpoint.

Do not start fixed-hostname work automatically while Core Function Completion is the current main product priority unless external-beta release is explicitly being prepared.

## 9. Project priority shift — Core Function Completion

The infrastructure/control-plane/DR construction phase is considered sufficiently closed for now.

The project main thread is now:

**ShuaBao Core Function Completion**

The objective is no longer broad architecture refinement. The objective is to make the actual user workflow complete and reliably usable.

Target resource allocation:

- ~80%: real ShuaBao product functions / end-to-end gameplay loop completion;
- ~10%: stability, recognition, FSM regressions found while completing functions;
- ~5%: small architecture convergence strictly required by a concrete blocker;
- ~5%: high-value model/GPT experimentation on difficult development problems only.

Infrastructure/VPS work is maintenance-only unless a production incident or release gate requires it.

### Current functional priority order

1. User can actually start the product
   - startup;
   - subscription/permit;
   - preflight;
   - dashboard start;
   - actual input authority.

2. Main挂机 loop
   - lobby search;
   - multi-keyword rotation;
   - room join/hitch;
   - in-game main loop;
   - post-game handling;
   - next-game continuation.

3. Post-game/Boss chain
   - post-game recognition;
   - NPC flow;
   - Boss selection;
   - 时光之穴;
   - 传家宝;
   - fallback only from known recognized post-game state;
   - UNKNOWN remains zero-input.

4. Secondary gameplay functions
   - 秘境;
   - 黑商;
   - other secondary resources/interactions.

5. Architecture cleanup only when a concrete product blocker proves it necessary.

### Required Functional Completion Map classifications

Each major function should be classified only as one of:

- `REAL_MACHINE_PASS`
- `CODE_AND_TEST_PASS_GT_MISSING`
- `OFFLINE_REPLAY_PASS`
- `PARTIAL`
- `BLOCKED`
- `UNKNOWN`

Never upgrade a function to `REAL_MACHINE_PASS` from pytest, click success, SendInput success, frame change, bookmark, or synthetic replay.

## 10. Local Agent execution policy from now on

Local Agent is the primary implementation worker.

Preferred loop:

`highest-value real blocker -> minimal failing regression -> minimal existing-abstraction fix -> focused tests -> relevant regression -> real-machine GT if needed -> STOP`

After one highest-priority blocker is completed, the Agent should STOP and return evidence for cloud review instead of automatically opening a second broad workstream.

Avoid:

- broad mediator refactor;
- architecture astronautics;
- framework imports;
- unrelated cleanup;
- mass renames/directory migrations;
- building new abstractions before proving existing ones cannot express the invariant.

Architecture Stage 2 remains HOLD while this product-completion loop is active.

## 11. Model / GPT assistance policy

Advanced models are a development-plane accelerator, not a runtime control authority.

Use high-cost/high-capability models for the hardest minority of problems, for example:

- cross-module root-cause analysis after ordinary local work stalls;
- complex FSM/race-condition review;
- difficult evidence synthesis;
- high-risk minimal-diff design review.

Do not put a general LLM into the runtime decision loop as:

`Frame -> remote LLM -> SendInput`

The deterministic fail-closed game architecture remains authoritative.

A separate broad “GPT system upgrade” workstream is not authorized while major product functions remain incomplete.

## 12. Current control-tower verdicts

- Release P0: **PASS / MERGED**
- Architecture Stage 0: **PASS**
- Architecture Stage 1: **PASS / MERGED**
- Architecture Stage 2: **HOLD**
- G2.1 code review: **PASS**
- G2.1 production cutover: **PASS**
- Public edge identity: **PUBLIC_EDGE_MATCHES_PRODUCTION**
- First real off-host Primary backup: **PASS**
- First real Primary restore on VPS-B: **REAL_PRIMARY_RESTORE_PASS**
- VPS-A: **MAINTENANCE_ONLY**
- VPS-B: **READY_FOR_PASSIVE_BACKUP / MAINTENANCE_ONLY**
- External Beta: **HOLD**
- Main project thread: **CORE FUNCTION COMPLETION**

## 13. What the next cloud architect must do first

Before making a new recommendation:

1. fetch and verify actual `origin/trial-merge` HEAD;
2. read this document first;
3. read `docs/CLOUD_ARCHITECT_STATUS_DELTA_20260905.md` only as historical delta context where useful;
4. do not reopen completed VPS/G2/Release-P0 work without concrete contradictory evidence;
5. inspect the latest Local Agent Core Function Completion report;
6. classify each claimed result by evidence level;
7. select the next highest-value functional blocker, not the next broad architecture idea;
8. preserve UNKNOWN zero-input and explicit fresh-frame business-postcondition requirements.

## 14. Next checkpoint

The next control-tower checkpoint is the Local Agent **Core Function Completion Sprint 1** return.

Expected return:

- Functional Completion Map;
- P0/P1/P2;
- one selected highest-value blocker;
- root cause;
- minimal diff;
- regression/test evidence;
- whether real-machine GT is still required;
- branch / commit / push / merge state.

Cloud review should then decide only the next smallest useful action:

- `PASS`
- `CONDITIONAL PASS`
- `BLOCKED`
- `READY_FOR_REAL_MACHINE_GT`
- `MERGE PASS`
- `HOLD`

Do not automatically start a second blocker or Architecture Stage 2.

## 15. Handoff maintenance rule

This file is the canonical cloud control-tower handoff and should be updated after **major project state changes**, so a new cloud reviewer does not have to reconstruct state from chat history.

Update this file when any of the following occurs:

- a major workstream moves PASS/BLOCKED/HOLD/MAINTENANCE_ONLY;
- a production deployment/cutover/rollback occurs;
- an external-beta gate opens or closes;
- a major branch/merge baseline changes;
- a real-machine GT milestone materially changes function status;
- a major architecture stage is authorized/completed/abandoned;
- backup/restore/DR status materially changes;
- project priority/order changes.

Do not update it for every tiny code commit or ordinary focused test result.

For every future major update:

1. independently verify GitHub state first;
2. distinguish GitHub facts from Agent/VPS/GT evidence;
3. update this handoff docs-only;
4. commit/push the handoff update;
5. report the resulting handoff commit SHA.
