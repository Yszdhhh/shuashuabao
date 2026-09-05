# ShuaBao Cloud Architect Control Tower — 2026-09-05

> Canonical cloud-side handoff for ShuaBao. Read this file first in any new cloud/Astra/Codex review.
>
> This file records the latest accepted repository state, live-ops evidence, architecture decisions, evidence boundaries, workstream ordering, and stop conditions. Older handoffs/status deltas remain historical context; where they conflict with this file, **this file is authoritative after its latest commit**.

## 0. Evidence classes — never collapse them

Always distinguish:

- **GitHub independently verified**: branch/commit/file facts read directly from GitHub.
- **Agent-reported local tests**: pytest/release-gate/Windows results reported by an execution Agent.
- **VPS live-environment evidence**: production/backup/restore facts reported from VPS-A/VPS-B.
- **Real-machine Ground Truth (GT)**: actual KK/game-machine business-path evidence.

Never promote pytest, replay, click success, SendInput success, frame change, button disappearance, bookmark, synthetic evidence, or a watchdog action into real-machine business PASS.

## 1. Current repository state

Repository:

`Yszdhhh/shuashuabao`

Main integration branch:

`trial-merge`

GitHub-verified `trial-merge` HEAD immediately before this handoff refresh:

`54f89ff6245da60ab888b25abdebe493c1c472e7`

Commit:

`fix: recover hitch exit after dismissed confirmation`

Parent:

`b2f492d979fcbaba05c34246b8efdef7fea0636a`

This handoff refresh is docs-only and will advance `trial-merge`; all Agents MUST fetch the actual remote HEAD before pushing later code. Do not force-push over the docs commit.

Current main project thread:

**CORE FUNCTION COMPLETION**

Architecture Stage 2 remains **HOLD**.

## 2. Frozen game safety architecture

The game-control chain remains:

`Frame -> Perception -> Scene/FSM -> Policy -> Input -> Business Postcondition`

Hard invariants:

- UNKNOWN / ambiguous / stale / unclassified => **ZERO INPUT**;
- click/SendInput success is not business PASS;
- frame change/button disappearance is not business PASS;
- only a **fresh-frame explicit business postcondition** may advance business state;
- recovery input requires an independently recognized known recovery scene;
- no generic UNKNOWN -> ESC / Back / Home;
- mechanical retry may be shared, business fallback stays in caller Policy/FSM;
- retries are attempt/time/rate bounded and re-observe preconditions;
- one authority decision should use one fresh frame/evidence generation.

Reuse first:

- `FrameEvidence`
- `MatchResult`
- `ActionLifecycle`
- `PendingAction`
- `InteractionSurface`
- `IncidentArchiver`
- existing matcher/color helpers
- existing production OCR bootstrap/client

Do not add without concrete proof:

- second FrameEvidence / VerifiedAction / action FSM;
- second retry/recovery framework;
- second OCR service;
- second incident system;
- Behavior Tree;
- statechart migration;
- workflow DSL;
- generic game engine.

## 3. Release P0 — closed

Accepted implementation baseline:

`f1d10ba7ebec2fa61f4a6210bd6ff07868b93d0c`

Accepted model:

- immutable versioned install dirs: `app-<version>-<channel>-<source12>/`;
- stable launcher;
- atomic `current.json`;
- N-1 rollback;
- failed install does not pollute final version dirs;
- launcher-before-pointer;
- legacy archive only after new package/shortcut proof;
- no change to subscription/permit trust semantics.

Historical Agent-reported acceptance evidence:

- `1455 passed, 13 skipped, 2 xfailed`;
- release gate PASS;
- Windows launcher smoke PASS.

**Release P0 = PASS / MERGED.** Do not redesign it without a concrete regression.

## 4. Architecture decision provenance — external review -> code-grounded convergence

The architecture decisions did not come from one report. The accepted chain is deliberately replayable and should be reviewed in order.

### Round 1 — Fable external hypotheses / corrections

Read:

`docs/FABLE_EXTERNAL_REVIEW_NOTES_20260904.md`

Purpose:

- preserve useful external hypotheses;
- record corrections to weak/stale external claims;
- explicitly reject generic UNKNOWN recovery, broad framework imports, blanket offline leases, and other overreach.

Important: this document itself says it is **not** the implementation source of truth; Git and GT remain authoritative.

### Round 2 — external-reference verification and translation into ShuaBao boundaries

Read:

`docs/LOCAL_AGENT_EXTERNAL_REFERENCE_ADDENDUM_20260904.md`

Purpose:

- compare Airtest, ok-script, MAA/MaaFramework, OAS and Alas patterns;
- identify what is useful as a pattern versus what must not be imported as a framework;
- map external ideas onto existing ShuaBao abstractions;
- preserve corrections such as current MAA color fusion behavior and no generic workflow DSL.

This is the second decision filter: an external idea is not accepted merely because a mature project uses it.

### Round 3 — code-grounded Stage 0 audit

Read:

`docs/ARCHITECTURE_STAGE0_AUDIT_20260904.md`

and the execution contract:

`docs/LOCAL_AGENT_REFACTOR_HANDOFF_20260904.md`

Purpose:

- inspect actual ShuaBao code;
- classify which external suggestions were already present;
- separate code facts from hypotheses;
- choose only the smallest high-value convergence work;
- prevent duplicate FrameEvidence/action/retry/OCR/incident frameworks.

### Convergence plan and implementation result

Then read:

`docs/ARCHITECTURE_CONVERGENCE_20260904.md`

`docs/ARCHITECTURE_STAGE1_REPORT_20260905.md`

The accepted progression is therefore:

**external hypothesis -> external-reference verification -> real-code audit -> bounded convergence plan -> Stage 1 implementation/report -> cloud control-tower acceptance**.

Do not skip directly from an external recommendation to a new framework.

## 5. Architecture Convergence status

Architecture branch:

`refactor/architecture-convergence-20260904`

Accepted branch HEAD:

`82557e9fb41b255ec29f71052c42d9e850ca4702`

Stage 0: **PASS**.

Stage 1: **DONE / MERGED / PASS**.

Stage 1 integration commit:

`ed11a7e8bc8d4bb94b91c60e5b79db3af4f2cbd1`

Accepted Stage 1 scope:

1. Typed expected-value OCR verifier
   - NFKC;
   - bounded input;
   - exact equality;
   - malformed/overlong/invalid expected values fail closed;
   - containment/fuzzy matching is not expected-value authority.

2. Transient lifecycle reset
   - only proven leaking transient state was reset;
   - legitimate transition budgets were not globally cleared.

3. RuntimeWatchdog-EscUnstuck bounded recovery
   - ESC cap = 2;
   - action-send success is not business PASS;
   - unverified recovery consumes budget;
   - budget exhaustion enters existing `Phase.ERROR`;
   - UNKNOWN receives no ESC authority;
   - no second recovery framework.

Agent-reported Stage 1 verification:

- `1474 passed, 13 skipped, 2 xfailed, 211 subtests`;
- release gate PASS 4/4;
- `disconnect_modal_missing` remains historical BLOCKED and was not falsified.

Known P2 test-infra debt: Windows PyQt6/faulthandler interaction; release-gate pytest uses `-p no:faulthandler` rather than hiding failure status.

**Architecture Stage 2 = HOLD.** Product completion has priority.

## 6. Core Function Completion Sprint 1 — current live status

Current highest-priority blocker selected by the Local Agent was lobby hitch exit recovery after a dismissed/rejected exit confirmation.

Initial local fix was rebased onto the then-current handoff commit and pushed as:

`54f89ff6245da60ab888b25abdebe493c1c472e7`

Files changed:

- `src/shuabao/mediator.py`
- `tests/test_live_scenario_capture.py`

Agent-reported verification for that commit:

- focused hitch tests: `35 passed, 41 deselected`;
- full pytest: `1477 passed, 13 skipped, 2 xfailed, 211 subtests`;
- release gate: PASS 4/4;
- worktree clean;
- no force push.

Real-machine GT was **not run**, because no KK process/window was present. The Agent correctly returned `BLOCKED_REAL_MACHINE_GT` instead of fabricating PASS.

### Cloud review finding on `54f89ff`

Cloud independently reviewed the GitHub diff and found a **P0 business-postcondition defect** in the new implementation:

- a `stale_exit > 3s` timeout can allow the exit latch to finalize even when tangible room evidence remains;
- `tangible_room == False` plus `lobby_visible == False` can also fall through into `Phase.LOBBY_ROOM`;
- conflicting `tangible_room == True` and `lobby_visible == True` is not explicitly held fail-closed.

This violates the frozen rule that time/absence alone cannot replace a fresh explicit lobby business postcondition.

A minimal corrective task has been issued with the required semantics:

- finalize exit **only** when `lobby_visible == True` AND `tangible_room == False`;
- tangible room only => zero-input wait;
- neither room nor lobby => zero-input wait;
- conflicting room+lobby => ambiguous, zero-input wait;
- remove timeout as exit-success authority;
- no new watchdog/retry/recovery framework.

**Current Sprint 1 verdict: P0 BLOCKED pending corrective commit.**

Do not run the Hitch real-machine GT until this corrective commit receives cloud code review PASS.

Because this handoff refresh advances `trial-merge` with a docs-only commit, the in-flight Local Agent must fetch/rebase/replay its corrective commit onto the new remote HEAD before a normal push if it is still based on `54f89ff`. Never force push.

## 7. Subscription control plane / VPS-A — closed, maintenance-only

Separate repository:

`Yszdhhh/shuashuabao-subscription-lab`

Accepted G2.1 branch:

`ops/release-lifecycle-g2-20260905`

Accepted/deployed commit:

`306c66ab10b2a45b9e50e0e436981fd71c1b7fad`

Final reported VPS-A verdicts:

- `G2_PRODUCTION_CUTOVER_PASS`;
- `PUBLIC_EDGE_MATCHES_PRODUCTION`;
- `FIRST_REAL_PRIMARY_BACKUP_READY`;
- VPS-A = `MAINTENANCE_ONLY`.

Reported live production:

- listener `:8010`;
- `/health service_revision = 306c66a...`;
- signer key id `shuabao-prod-2`, not rotated;
- PermitIssuer preserved;
- thin release lifecycle: exact approval + BLOCKED + advisory recommended/outdated;
- public release status redacts operator metadata;
- admin endpoints fail closed without configured admin secret;
- permit contract remains `POST /v1/entitlements/validate` + `permit_request`.

Do not use `/v1/permits -> 404` as an edge-identity test.

Grok is now reserved only for unavoidable VPS-A production operations. Do not use Grok for ordinary code review, architecture, docs, prompts, or card generation.

## 8. VPS-B Passive Recovery — closed, maintenance-only

Role:

**PASSIVE RECOVERY NODE**

Forbidden permanently:

- production PermitIssuer;
- production DB writer;
- production permit/manifest signing private keys;
- active-active;
- automatic DNS failover.

Accepted reported state:

- key-only SSH on management port 50022;
- dedicated non-privileged `shuabao-backup` account;
- isolated backup/restore paths;
- age encryption;
- partial-upload gating + checksum verification;
- retention/disk/staleness guards;
- recurring passive health and restore validation;
- existing Hysteria/Shadowsocks left intact for Phase 1.

First real encrypted Primary artifact:

`shuabao_backup_primary-substate-20260905T034025Z.tar.gz.age`

Primary-reported SHA256:

`57a49d2922a26837ca8fef6929ad88e14b1fd8542ba938558340fc59b51bc84b`

Final VPS-B real restore report:

- encrypted checksum MATCH reported;
- age decrypt SUCCESS;
- restored `subscription_state.db` size 77,824 bytes;
- `PRAGMA integrity_check = ok`;
- dynamic `sqlite_master` discovery;
- row-count sanity PASS;
- close/reopen PASS;
- plaintext scratch cleanup PASS;
- recurring restore tooling compatibility PASS.

Reported real table set:

- `local_activations`: 4
- `local_licenses`: 6
- `processed_events`: 0
- `release_policies`: 0
- `subscription_bindings`: 0
- `trial_accounts`: 0
- `trial_devices`: 0
- `trial_reservations`: 0

Accepted verdicts:

`REAL_PRIMARY_RESTORE_PASS`

`READY_FOR_PASSIVE_BACKUP`

VPS-B = `MAINTENANCE_ONLY`.

No further VPS construction work unless a concrete production/backup regression appears.

## 9. External Beta / network placement

External Beta remains **HOLD**.

Remaining major gates:

1. fixed HTTPS hostname / Named Tunnel / DNS cutover;
2. final external-beta client endpoint/identity integration;
3. operational Authenticode-signed external build;
4. final external-beta-specific smoke.

The current Quick Tunnel is temporary only, although localhost/public `service_revision` has been reported matching.

Current network-placement decision:

- do **not** add a mainland-China VPS now;
- main product completion has higher priority;
- before external beta, measure real China Telecom/Unicom/Mobile DNS/TLS/health/entitlement/permit reliability and p50/p95/timeout behavior against the fixed endpoint;
- if current overseas Primary is materially unreliable, prefer evaluating a Hong Kong Primary before adding a mainland active node;
- do not reopen active-active / multi-writer architecture casually.

## 10. License/card operations — auxiliary workstream only

Product decision:

- bulk cards should be generated without LLM/Grok involvement;
- card validity starts on **first successful activation**, not creation time;
- UNUSED cards keep `activated_at = NULL`, `expires_at = NULL`;
- first successful activation atomically sets `activated_at` and `expires_at = activated_at + duration`;
- repeated validation must not extend expiry;
- daily operator workflow should eventually run from Windows through a deterministic CLI/admin tool, with VPS-A remaining the production authority;
- VPS-B never generates/activates cards.

A small `shuashuabao-subscription-lab` feature task may implement bulk generation + deferred activation + CSV export on an isolated branch. It must not deploy production until cloud code review. This auxiliary task must not steal the main ShuaBao implementation Agent from Core Function Completion.

## 11. Main project priority

Resource intent:

- ~80% actual ShuaBao user-flow / gameplay completion;
- ~10% stability/recognition/FSM regressions discovered while doing functions;
- ~5% small architecture fixes required by a concrete blocker;
- ~5% high-capability model review on difficult problems.

Functional priority:

1. startup -> subscription/permit -> preflight -> dashboard start -> actual input authority;
2. lobby search -> keyword rotation -> room join/hitch -> in-game loop -> post-game -> next-game continuation;
3. post-game NPC/Boss -> 时光之穴 -> 传家宝 with known-scene fallback only;
4. 秘境 / 黑商 / secondary paths;
5. architecture cleanup only when a real blocker proves it necessary.

Allowed completion labels:

- `REAL_MACHINE_PASS`
- `CODE_AND_TEST_PASS_GT_MISSING`
- `OFFLINE_REPLAY_PASS`
- `PARTIAL`
- `BLOCKED`
- `UNKNOWN`

## 12. Local Agent execution policy

Preferred loop:

`highest-value blocker -> failing regression -> minimal existing-abstraction fix -> focused tests -> relevant/full regression -> cloud review -> real-machine GT if needed -> STOP`

One blocker, one writer. Additional Agents should be read-only review/evidence roles unless explicitly authorized.

Do not automatically start a second blocker after finishing the first.

Avoid broad mediator refactors, framework imports, unrelated cleanup, mass renames, or new abstractions without proof.

## 13. Astra / external architecture review entrypoint

Astra is being used as a **read-only independent reviewer**, not as a new implementation Agent.

### Branch to review

Use:

`trial-merge`

Do **not** review `main` as the current product baseline. Do not use archive branches as the primary line. The architecture branch is historical/reference only because accepted Stage 1 is already integrated into `trial-merge`.

### Required reading order

Start with:

1. `docs/CLOUD_ARCHITECT_CONTROL_TOWER_20260905.md` — current authoritative status and stop conditions.

Then reconstruct the architecture decision chain:

2. `docs/FABLE_EXTERNAL_REVIEW_NOTES_20260904.md`
3. `docs/LOCAL_AGENT_EXTERNAL_REFERENCE_ADDENDUM_20260904.md`
4. `docs/ARCHITECTURE_CONVERGENCE_20260904.md`
5. `docs/LOCAL_AGENT_REFACTOR_HANDOFF_20260904.md`
6. `docs/ARCHITECTURE_STAGE0_AUDIT_20260904.md`
7. `docs/ARCHITECTURE_STAGE1_REPORT_20260905.md`

Release/reliability context:

8. `docs/RELEASE_P0_INSTALL_AUDIT_20260904.md`
9. `docs/LIVE_TEST_HANDOFF_20260831.md`
10. `docs/LIVE_TEST_ASSET_CONSOLIDATION_20260831.md`
11. `docs/CLOUD_SUBSCRIPTION_AUDIT_PACKAGE_20260903.md` only if reviewing release/subscription boundaries.

Historical delta:

12. `docs/CLOUD_ARCHITECT_STATUS_DELTA_20260905.md` only as historical context; this control-tower file overrides it where later state differs.

### Astra review goals

Astra should independently verify code, not merely summarize documents. Ask it to identify:

- contradictions between accepted decisions and current code;
- duplicated abstractions/framework creep;
- weak/implicit business postconditions;
- stale evidence/incorrect PASS claims;
- overengineering that should be removed/deferred;
- missing high-value simplifications;
- whether the current priority shift to Core Function Completion is correct;
- whether any proposed optimization is important enough to interrupt the main function roadmap.

Explicitly require it to review the current Hitch exit area around `54f89ff` and the cloud-found P0 postcondition concern, while recognizing that a corrective commit may be in flight.

Astra must **not** modify code, start Stage 2, or recommend a framework migration without concrete code evidence.

## 14. Current control-tower verdicts

- Release P0: **PASS / MERGED**
- Architecture Stage 0: **PASS**
- Architecture Stage 1: **PASS / MERGED**
- Architecture Stage 2: **HOLD**
- Core Function Completion Sprint 1 / Hitch exit: **P0 BLOCKED pending corrective commit; GT HOLD**
- G2.1 code review: **PASS**
- G2.1 production cutover: **PASS**
- Public edge identity: **PUBLIC_EDGE_MATCHES_PRODUCTION**
- First real off-host Primary backup: **PASS**
- First real Primary restore on VPS-B: **REAL_PRIMARY_RESTORE_PASS**
- VPS-A: **MAINTENANCE_ONLY**
- VPS-B: **READY_FOR_PASSIVE_BACKUP / MAINTENANCE_ONLY**
- External Beta: **HOLD**
- Main project thread: **CORE FUNCTION COMPLETION**

## 15. Immediate next steps

1. Local Agent completes the minimal Hitch postcondition corrective commit.
2. Because this handoff update advances `trial-merge`, Local Agent fetches the new remote HEAD and safely replays/rebases its unpushed corrective commit if necessary; no force push.
3. Cloud independently reviews the corrective diff.
4. Only after cloud code PASS, run the narrow Hitch real-machine GT.
5. If GT PASS, close Sprint 1 and update this handoff.
6. Select Sprint 2 from the Functional Completion Map; do not auto-start Architecture Stage 2.
7. Astra may perform an independent read-only audit in parallel because it does not write the repository.
8. The auxiliary card-generator task may run on the separate subscription repository/branch without involving Grok or VPS-B.

## 16. Handoff maintenance rule

Update this canonical file after major state changes, including:

- major PASS/BLOCKED/HOLD/MAINTENANCE_ONLY transitions;
- production deployment/cutover/rollback;
- external-beta gate changes;
- major branch/integration baseline changes;
- real-machine GT milestones;
- architecture stage authorization/completion/abandonment;
- backup/restore/DR changes;
- project-priority changes.

Do not update it for every tiny commit or ordinary focused test.

For every future major update:

1. independently verify GitHub state first;
2. distinguish GitHub facts from Agent/VPS/GT evidence;
3. update this handoff docs-only;
4. commit/push the handoff update;
5. report the resulting handoff commit SHA.
