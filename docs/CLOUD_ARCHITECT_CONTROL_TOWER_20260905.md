# ShuaBao Cloud Architect Control Tower — 2026-09-05

> Canonical cloud-side handoff for ShuaBao / 刷刷宝. Read this file first in any new cloud/Astra/Aster/Codex review.
>
> This document is the current control-tower source of truth for accepted Git state, local/VPS evidence boundaries, active blockers, product priorities, pending Agent work, and next-step ordering. Older handoffs remain historical context; where they conflict with this document, this document wins after its latest commit.

## 0. New-conversation bootstrap

At the start of a new conversation:

1. Read this file first.
2. Re-read current GitHub branch HEADs before accepting any new Agent report.
3. Treat local Windows/VPS results as reported evidence unless independently observable.
4. Do not promote test/replay/click/input success into real business PASS.
5. Review incoming Main Agent and Astra/Aster reports independently before authorizing another build or real-machine run.

The user is intentionally migrating to a new conversation because the previous context became too long. At this handoff point, two reports are expected next:

- **Main Agent repair report** — current OCR/runtime-root-cause repair work is still pending return.
- **Astra/Aster read-only audit report** — current formal-dashboard integration + authorization-persistence audit is still pending return.

Do not assume either report has passed until its Git/code/evidence is independently checked.

## 1. Evidence classes — never collapse them

Always distinguish:

- **GitHub independently verified**: branch/commit/file facts read directly from GitHub.
- **Agent-reported local tests**: pytest/release-gate/Windows build/runtime results reported by an execution Agent.
- **VPS live-environment evidence**: production/backup/restore facts reported from VPS-A/VPS-B.
- **Real-machine Ground Truth (GT)**: actual KK/game-machine business-path evidence.

Never treat any of the following as real business PASS by themselves:

- pytest or synthetic replay;
- click success or SendInput success;
- button disappearance;
- frame change;
- bookmark / p-f-m marker;
- watchdog action sent;
- old screenshot or historical fixture.

A business state may advance only on a fresh frame with the required explicit business postcondition.

## 2. GitHub-verified repository state at this handoff

Main repository:

`Yszdhhh/shuashuabao`

Main integration branch:

`trial-merge`

### Code-bearing baseline immediately before this docs refresh

GitHub-verified HEAD before this handoff commit:

`6290bb6378dca141d310607c5e28098d5d5ae8c9`

Commit:

`fix: restrict HitchConfirmLeave authority to explicit exit-specific modal evidence`

Parent:

`7649fd44273761d9a2702c453c6b514bd10eeec4`

This handoff update is **docs-only** and therefore advances `trial-merge` beyond `6290bb...`. Future Agents must distinguish:

- current remote branch HEAD after this document commit;
- accepted code-bearing baseline `6290bb...` underneath the docs-only commit.

Never force-push over the handoff commit. Fetch/rebase normally before future code pushes.

Architecture branch remains:

`refactor/architecture-convergence-20260904`

GitHub-verified architecture branch HEAD:

`82557e9fb41b255ec29f71052c42d9e850ca4702`

Architecture Stage 0 = PASS.

Architecture Stage 1 = DONE / MERGED / PASS.

Architecture Stage 2 = **HOLD** while product flow completion has priority.

## 3. Frozen game safety architecture

The control chain is frozen as:

`Frame -> Perception -> Scene/FSM -> Policy -> Input -> Business Postcondition`

Hard invariants:

- UNKNOWN / ambiguous / stale / unclassified => **ZERO INPUT**;
- click/SendInput/frame-change/button-disappear are not business PASS;
- only fresh explicit business postconditions advance state;
- recovery input requires a known/whitelisted recovery scene;
- no generic UNKNOWN -> ESC / Back / Home;
- mechanical retry may be shared, business fallback belongs to caller Policy/FSM;
- retries must be attempt/time/rate bounded and must re-observe preconditions;
- one authority decision should be based on one fresh evidence generation.

Reuse existing abstractions first:

- `FrameEvidence`
- `MatchResult`
- `PendingAction`
- `ActionLifecycle`
- `InteractionSurface`
- `IncidentArchiver`
- existing matcher/color helpers
- existing production OCR bootstrap/client

Do not create a second FSM/retry/recovery/OCR/incident framework without proof that the existing abstraction cannot satisfy the concrete blocker.

## 4. Release / desktop packaging foundation — accepted

Accepted Release P0 baseline:

`f1d10ba7ebec2fa61f4a6210bd6ff07868b93d0c`

Accepted deployment model:

- immutable versioned install dirs;
- stable launcher;
- atomic `current.json`;
- N-1 rollback;
- failed install does not pollute final version dirs;
- source/build identity must be explicit;
- production current pointer changes only after package verification.

Do not redesign this release architecture without a concrete regression.

## 5. Hitch / lobby Sprint 1 — code review PASS, GT still pending

Historical chain:

1. Earlier implementation allowed exit completion from timeout/absence instead of an explicit lobby postcondition.
2. `4210cb66190f49c62289ad451dc1fd6ad0f45ec3` corrected the stale-exit authority: finalize only from fresh lobby evidence with room controls absent.
3. Independent pre-GT review then found `_tick_l0()` could clobber Hitch room evidence before `_tick_lobby_hitch`, allowing conflicting evidence to be misinterpreted.
4. `7649fd44273761d9a2702c453c6b514bd10eeec4` preserved pending Hitch evidence through `_tick_l0()` and added regression coverage, but its modal identity still treated generic popup evidence too broadly.
5. `6290bb6378dca141d310607c5e28098d5d5ae8c9` narrowed `HitchConfirmLeave` authority to explicit exit-specific evidence only.

Accepted `6290bb...` semantics:

- direct exit markers such as `lobby/lobby_popup_leave`, `lobby/exit_confirm_btn`, `lobby/exit_cancel_btn`, or exit-specific recognized scenes may authorize exit-confirm interaction;
- generic `lobby_popup_dialog/title` may prove only that a popup exists, never that it is the leave-confirm modal;
- generic popup + blue block without exit-specific identity => ZERO INPUT;
- exit finalization requires fresh lobby room-list evidence and absence of tangible room controls;
- conflicting or unknown evidence => ZERO INPUT.

Cloud verdict for `6290bb...`:

`CODE_REVIEW_PASS`

Agent-reported tests on this baseline:

- Hitch-focused: 41 passed;
- full suite: 1492 passed, 5 skipped, 2 xfailed, 248 subtests;
- release gate: 4/4 PASS.

These are Agent-local test results, not GitHub CI.

### Required Hitch real-machine GT boundary

Run from the **formal production dashboard**, not the test dashboard:

`大厅 -> keyword search/rotation -> join room -> floor1 condition fails -> exit -> real exit confirmation -> fresh lobby -> at least one subsequent real refresh/search`

Then **STOP**.

Do not continue into the next successful join / MAIN_LINE in this GT pass. The stop boundary intentionally isolates the known RuntimeWatchdog debt described below.

Allowed GT outcomes:

- `REAL_MACHINE_PASS`
- `BLOCKED_REAL_MACHINE_GT`
- `BLOCKED_GT_ENVIRONMENT`

If no visible real KK/game window is available, return `BLOCKED_GT_ENVIRONMENT` and do not fabricate PASS.

## 6. Known RuntimeWatchdog P1 — deferred until Hitch GT passes

Known code issue in `src/shuabao/runtime_mediator.py`:

After watchdog ESC is sent, production code calls `_mark_runtime_progress(now)` even though successful input transmission is not business progress.

Risk:

- it may mask a stuck condition or distort retry pacing/authority after the Hitch GT boundary;
- it violates the evidence principle if treated as business advancement.

This is a known **P1 architecture/runtime correctness debt**, but it is intentionally deferred until the bounded Hitch GT above is complete.

Fix it minimally after Hitch GT; preserve retry pacing and do not add a new watchdog/recovery framework.

## 7. Local desktop identity — old-package drift found and corrected

A read-only local audit previously found that the stable desktop shortcut still launched an old package:

`C:\Users\10639\Desktop\刷刷宝.lnk`

through the stable launcher under:

`C:\Users\10639\AppData\Local\ShuaBao\launcher\`

The old selected package was:

`app-0.3-dev-4210cb66190f`

with source identity `4210cb...`.

That explained the recurring class of problem where source had advanced but the actual desktop shortcut still launched an older frozen package.

The Main Agent then performed a controlled clean rebuild/install from:

`G:\刷刷宝\Worktrees\trial-merge-p0-ff`

Agent-reported pre-build identity:

- local HEAD = `6290bb...`;
- `origin/trial-merge` = `6290bb...` at build time;
- worktree clean;
- no `-AllowDirty`;
- no `-SkipGate`.

Agent-reported installed state after build:

- `current = app-0.3-dev-6290bb6378dc`;
- `previous = app-0.3-dev-4210cb66190f`;
- `current_source_sha = 6290bb...`;
- current EXE SHA256 = `e167d998f9759211cb65c15187cb2a579188036568916dc85f6acc65725aad82`;
- package manifest/build identity source SHA = `6290bb...`;
- UI build manifest source SHA = `6290bb...`;
- previous package retained for rollback.

Agent-reported build verification:

- release gate 4/4 PASS;
- pytest 1492 passed / 5 skipped / 2 xfailed;
- release/security harness 26 gates PASS;
- manifest Ed25519 signed;
- worktree clean after build.

Accepted status from that evidence:

`DESKTOP_IDENTITY_PASS / READY_FOR_COLD_START`

This is **not** equivalent to first-launch, OCR-runtime, subscription-runtime, formal-runner, or real-machine business PASS.

## 8. Current Aster/Astra read-only audit — PENDING

Aster/Astra is a local **read-only reviewer**, not a writer. Do not infer a specific external model identity unless the local tool explicitly proves it; provenance should be recorded as an external/local Agent review with model identity UNKNOWN when uncertain.

The current pending audit should cover two product-integration questions before the next rebuild/GT decision.

### A. Test/live dashboard capabilities vs formal production dashboard

Determine whether functionality already proven in the Live/Test dashboard was actually wired into the formal desktop dashboard/runtime path, especially:

- lobby search;
- multi-keyword rotation;
- room join / Hitch FSM;
- formal config -> controller/runtime mediator -> input authority;
- preflight gate -> real runner availability;
- no mock/test fallback in production bridge failure cases.

The goal is to find integration omissions, not redesign the dashboard or create a second runtime path.

### B. Card/license persistence after closing and reopening the formal client

Observed product problem:

After a card is entered and successfully authorized in the formal dashboard, closing the client and reopening it asks for the card again.

This is not the intended product behavior.

Expected lifecycle:

`first card entry -> successful activation/bind -> persist safe device/auth state -> close -> reopen -> recover device identity -> revalidate entitlement/permit -> authorized dashboard`

Same-device restart must **not** require the original card again and must **not** restart or extend the paid duration.

Audit the full chain:

`formal card input -> activate/validate -> server response -> local persistence location -> shutdown -> bootstrap -> device identity restore -> entitlement/permit revalidation -> dashboard start gate`

Check specifically for:

- state living only in memory/session;
- WebView/localStorage profile/origin changing per launch;
- frozen package using a different data directory from source/test mode;
- machine/device identity being regenerated;
- persistent data existing but formal bootstrap not reading it;
- test dashboard persistence present but production dashboard path missing;
- activate identity and later validate/permit identity not forming one closed chain.

Security constraint:

Do **not** accept “store plaintext card in localStorage/sessionStorage” as the default fix. Prefer existing device binding / entitlement / permit / secure persistent client state. Raw card secrets must not be written into URLs, logs, or unsafe Web storage.

Expected audit output:

- `AUTH_PERSISTENCE_PASS`, or
- `AUTH_PERSISTENCE_GAP_FOUND`

with root cause, file/function, current storage location, startup restore path, test-vs-formal difference, severity, and minimal fix recommendation.

### C. Cold-start/runtime integration evidence when included in the audit

If the pending Aster/Astra audit also performs the previously planned cold-start check, it must use the real desktop shortcut and remain zero-business-input.

Check:

- launcher selects the expected current package;
- one ShuaBao process/window, no immediate crash/black/white/duplicate window;
- formal Web UI appears and is interactive;
- WebChannel/DashboardFacade/bridge ready;
- OCR worker bundled and starts exactly as intended;
- model/self-check status;
- first legal OCR request latency/status;
- packaged subscription endpoint actually used;
- entitlement/permit success;
- preflight PASS implies the production runner is really available, not UI text only.

Do not click “开始” into real game automation during this audit.

## 9. Main Agent OCR/runtime repair — PENDING RETURN

A Main Agent repair report is still pending at the time of this handoff.

Important interpretation rule:

The Stage 1 **typed expected-value verifier** is only a fail-closed validation layer. It is **not** itself an OCR engine reliability improvement.

When the Main Agent returns, independently verify:

- actual changed commit and branch;
- exact root cause claimed;
- whether it modifies OCR worker/bootstrap/model packaging/client IPC versus only downstream validation;
- focused regression + full/relevant suite;
- whether frozen build/package identity has changed;
- whether a new desktop rebuild is required;
- whether first-start latency, first legal OCR request, EMPTY/ERROR/misread behavior, and worker recovery evidence support the claimed fix.

Do not accept “tests pass” as proof that the frozen desktop OCR runtime has actually started correctly.

If the OCR repair changes production source beyond `6290bb...`, the current installed desktop package becomes stale again until a controlled rebuild is done.

## 10. Subscription control plane / VPS-A — production baseline accepted, maintenance-only

Separate repository:

`Yszdhhh/shuashuabao-subscription-lab`

Production branch:

`ops/release-lifecycle-g2-20260905`

GitHub-verified production branch HEAD:

`306c66ab10b2a45b9e50e0e436981fd71c1b7fad`

Accepted production state includes:

- exact release identity / lifecycle policy;
- BLOCKED + advisory recommended/outdated behavior;
- public status redaction;
- admin fail-closed without configured secret;
- no default `admin/admin`;
- reseed preservation;
- baseline provenance record;
- `/health service_revision` support;
- permit contract remains `POST /v1/entitlements/validate` + `permit_request`.

Reported VPS-A verdicts:

- `G2_PRODUCTION_CUTOVER_PASS`;
- `PUBLIC_EDGE_MATCHES_PRODUCTION`;
- `FIRST_REAL_PRIMARY_BACKUP_READY`;
- VPS-A = `MAINTENANCE_ONLY`.

The current development/GT desktop package was built with the temporary Quick Tunnel:

`https://quebec-luis-flooring-kenneth.trycloudflare.com`

Agent-reported build-time `/health` returned HTTP 200 with:

- service `shuashuabao-entitlement-bridge`;
- `service_revision = 306c66ab10b2a45b9e50e0e436981fd71c1b7fad`;
- `provider_mode = inmemory`;
- `active_provider = inmemory_keygen`;
- `shadow_provider = keygate`.

For current local development/GT, this temporary endpoint was accepted because its service revision matched the accepted production baseline. It is **not** an External Beta endpoint.

Do not reopen VPS-A architecture unless a real regression or required deployment exists.

## 11. VPS-B passive recovery — closed / maintenance-only

VPS-B role:

**PASSIVE RECOVERY NODE**

Never use it as:

- production PermitIssuer;
- production DB writer;
- active-active node;
- automatic DNS failover;
- holder of production signing private keys.

Accepted reported recovery evidence includes:

- key-only SSH on management port 50022;
- isolated backup/restore paths;
- age encryption;
- checksum and partial-upload gating;
- recurring restore validation;
- first real encrypted Primary artifact;
- successful decrypt + SQLite integrity + row-count + reopen checks;
- plaintext restore scratch cleanup.

Primary artifact:

`shuabao_backup_primary-substate-20260905T034025Z.tar.gz.age`

Primary-reported SHA256:

`57a49d2922a26837ca8fef6929ad88e14b1fd8542ba938558340fc59b51bc84b`

Accepted final labels:

`REAL_PRIMARY_RESTORE_PASS`

`READY_FOR_PASSIVE_BACKUP`

VPS-B = `MAINTENANCE_ONLY`.

## 12. Bulk license/card feature — separate auxiliary branch, not production-deployed

Separate feature branch:

`feat/bulk-license-cards-activation-lifecycle-20260905`

GitHub-verified branch HEAD at this handoff:

`3fbfd59cd45c443257dad3fe18556f9a09a79b34`

Commit message:

`feat(cards): enforce HTTPS on remote admin CLI, strict batch CAS/FSM, and fail-closed missing batch handling`

Parent:

`00de77c72d0c3109be243db1555040078062c7bd`

This branch has advanced beyond the last previously reviewed `00de77c...` baseline. Do **not** silently mark `3fbfd59...` accepted merely from its commit message. If this workstream resumes, independently review its diff/tests before merge/deploy.

Product requirements remain:

- secure random cards;
- bulk generation/inventory;
- states such as UNUSED / ACTIVE / EXPIRED / REVOKED;
- validity starts on first successful activation, not generation time;
- first activation atomically sets activation/expiry;
- repeated validation does not extend expiry;
- failed activation does not start duration;
- Windows operator workflow eventually talks to the VPS-A authority through secure Admin API;
- VPS-B never generates or activates cards.

This auxiliary branch has **not** been deployed to the current VPS-A production baseline described above unless later evidence explicitly says otherwise.

## 13. External Beta — HOLD

Remaining major gates:

1. fixed HTTPS hostname / Named Tunnel / DNS cutover;
2. final external-beta client endpoint/identity integration;
3. operational Authenticode-signed external build;
4. final beta-specific smoke.

The current Quick Tunnel is temporary and is suitable only for local development/GT where explicitly accepted.

Do not add a mainland-China VPS by default. First measure real China Telecom/Unicom/Mobile DNS/TLS/health/entitlement/permit reliability against the eventual fixed endpoint. If the overseas Primary is materially unreliable, evaluate a Hong Kong Primary before reopening multi-node architecture.

## 14. Product priority / execution policy

Current resource intent:

- ~80% actual user-flow/gameplay completion;
- ~10% stability/recognition/FSM defects encountered while completing functions;
- ~5% architecture changes only when a concrete blocker proves them necessary;
- ~5% difficult independent review/experiments.

Functional order:

1. startup -> subscription/permit -> preflight -> formal dashboard start -> actual input authority;
2. lobby -> keyword rotation -> room join/Hitch -> in-game -> post-game -> next cycle;
3. post-game NPC/Boss -> 时光之穴 -> 传家宝;
4. 秘境 / 黑商 / secondary flows;
5. architecture cleanup only for proven blockers.

Preferred Local Agent loop:

`highest-value blocker -> failing regression -> minimal fix using existing abstractions -> focused tests -> relevant/full regression -> cloud review -> real GT if required -> STOP`

One writer per blocker. Additional Agents should be read-only unless explicitly assigned to write.

Do not automatically start a second blocker after finishing the first.

## 15. Decision tree when the pending reports arrive in the new conversation

When the user brings the Main Agent and Aster/Astra reports into a new chat:

1. Read this handoff and re-check actual GitHub HEADs.
2. Review Main Agent code changes independently; classify P0/P1/P2 and verify whether the current desktop package became stale.
3. Review Aster/Astra findings separately; especially formal-vs-test dashboard integration and card/license restart persistence.
4. Consolidate blockers before rebuilding. Avoid one build per tiny issue.
5. If source changes are accepted, perform one controlled clean build from the accepted Git commit with release gates and source/package identity recorded.
6. Run read-only cold-start/preflight validation from the real desktop shortcut.
7. Only after local startup/OCR/subscription/formal-runner readiness passes, run the bounded formal-dashboard Hitch GT.
8. After Hitch GT passes, close Sprint 1 and then fix the known RuntimeWatchdog P1.
9. Move to the next highest-value functional blocker; Architecture Stage 2 remains HOLD.

Allowed functional labels remain:

- `REAL_MACHINE_PASS`
- `CODE_AND_TEST_PASS_GT_MISSING`
- `OFFLINE_REPLAY_PASS`
- `PARTIAL`
- `BLOCKED`
- `UNKNOWN`

## 16. Key historical documents to preserve

Read these only as supporting history after this control tower:

- `docs/FABLE_EXTERNAL_REVIEW_NOTES_20260904.md`
- `docs/LOCAL_AGENT_EXTERNAL_REFERENCE_ADDENDUM_20260904.md`
- `docs/ARCHITECTURE_STAGE0_AUDIT_20260904.md`
- `docs/LOCAL_AGENT_REFACTOR_HANDOFF_20260904.md`
- `docs/ARCHITECTURE_CONVERGENCE_20260904.md`
- `docs/ARCHITECTURE_STAGE1_REPORT_20260905.md`

Accepted architectural progression:

`external hypothesis -> external-reference verification -> code-grounded Stage 0 audit -> bounded convergence plan -> Stage 1 implementation -> cloud acceptance`

Do not jump directly from a third-party recommendation to a new framework.

---

**Current handoff status:** waiting for the Main Agent repair report and the Aster/Astra read-only audit report. No new architecture sprint, no VPS expansion, and no Hitch real-machine GT should be started solely from this document without first reconciling those incoming results and current Git/package identity.
