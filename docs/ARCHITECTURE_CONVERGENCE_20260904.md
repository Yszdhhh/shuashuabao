# ShuaBao Architecture Convergence Plan — 2026-09-04

Baseline: `trial-merge@0baa2e5f17f7cfafca1b008a2070f49b03cf9748`

This document freezes the architecture direction after external review (Fable 5.1), independent review, and direct inspection of the current Git tree. It is intentionally conservative: the goal is to reduce cognitive load and long-thread failure propagation without rewriting the FSM or changing business semantics in one large step.

## 1. Current code already contains more of the target architecture than the external review assumed

Do **not** rebuild these concepts under new names:

- `Mediator.FrameEvidence` already provides a strong frame reference, monotonic generation, per-frame recognition cache, UI scale/HWND context, and input-driven invalidation semantics.
- `interaction_surface.ActionLifecycle` and `PendingAction` already model input -> verification -> confirmed/unconfirmed lifecycle and deterministic postconditions.
- `IncidentArchiver` already captures unknown/abnormal evidence with before/now/after frames, metadata, ROI crops, retention and deduplication.
- `vision.matcher` already has ROI/multiscale matching, gray candidate search, local color NCC verification, margin-aware search, HSV blue-button detection, contour/geometry filters and caches.
- `runtime_mediator` already has bounded OCR bootstrap/warmup, production-only liveness guards and some two-frame HUD confirmation.

Therefore the convergence work is **integration and boundary cleanup**, not a second architecture beside the current one.

## 2. Frozen architecture principles

### 2.1 Keep the existing FSM

No Behavior Tree, statechart migration, generic workflow engine, plugin system, microservices, event sourcing or generic game DSL.

The outer structure remains:

`Frame -> Perception -> Scene/FSM -> Policy -> Input -> Business Postcondition`

The main refactor objective is to make each layer's authority explicit while preserving already proven scene transitions.

### 2.2 UNKNOWN never grants input authority

`UNKNOWN`, ambiguous evidence, unclassified pages, missing templates and recognition exceptions default to **zero input**.

Recovery may only act after independently identifying a whitelisted known recovery scene. There is no universal `UNKNOWN -> ESC` path.

### 2.3 Click success is not business success

`SendInput=True`, a changed frame, a vanished button or a bookmark cannot advance the business FSM. Only an explicit business postcondition on a fresh frame may do so.

### 2.4 Mechanical retry may be shared; business fallback stays in Policy

A shared action primitive may own:

- precondition re-check on a fresh frame;
- one mechanical input target;
- postcondition wait;
- timeout;
- same-target retry with a small fixed bound;
- cooldown/rate limit;
- typed failure result.

It may **not** own:

- switching room/prefix/stage;
- choosing a different target;
- going back to lobby;
- restarting a challenge;
- deciding to stop or recover.

A simple boundary rule: **a generic action primitive may not introduce a second target**.

### 2.5 Perception can be data-driven; workflow cannot

Safe to data-drive gradually:

- ROI / anchor name;
- template path;
- threshold / margin;
- RGB/HSV ranges;
- masks;
- OCR aliases/expected regex/value range;
- temporal confirmation count.

Do not move these into YAML/resource data:

- `next` / `on_error` / business fallback;
- action sequences;
- arbitrary click coordinates;
- scene-transition policy.

The project must not accidentally grow a mini-MAA DSL.

## 3. External review corrections that are binding for implementation

### 3.1 MAA color matching factual correction

The current MAA `dev-v2` `Matcher.cpp` computes color-count F1 and multiplies it with the template match result. Do not implement from a stale changelog assumption that current MAA uses a geometric mean unless re-verified against the exact source revision being compared.

### 3.2 Where count-based color evidence is actually useful

Current ShuaBao local color verification is NCC/correlation-like. Add count-based RGB/HSV evidence only where hue/saturation/coverage carries business meaning, for example:

- enabled vs disabled controls;
- selected vs unselected states;
- rarity borders;
- ready/not-ready indicators;
- colored status lights;
- progress/health bars.

Do not apply color-count evidence to every template.

For fail-closed authority decisions prefer **hard independent gates** (`shape >= T AND color_count >= C`). A fused score may be tested for ranking among multiple candidates, but must not silently weaken either authority threshold.

### 3.3 OCR should become typed reads, not a new OCR class hierarchy

Do not copy OAS's class count. Prefer a small typed-read contract such as:

- `digit`;
- `counter`;
- `lexicon_name`.

The type controls parse/validation/UNKNOWN semantics, not a second framework.

For a tiny expected-value problem (for example lobby prefix `4` or `3`), prefer the smallest expected-glyph verifier that the Ground Truth supports; do not create a full digit bank unless the business actually needs all digits.

### 3.4 Temporal confirmation must be risk-tiered

Do not require whole-frame freeze everywhere. Animated game UIs may never be globally still.

Use:

- high-risk transition: 2 fresh consistent observations plus semantic-ROI stability when needed;
- normal page anchor: one fresh candidate, debounced scene update if necessary;
- informational read that cannot drive Policy: one fresh observation.

### 3.5 Incident regression has two gates

Safety gate:

- GT = X -> X or UNKNOWN is acceptable;
- GT = absent -> absent/UNKNOWN;
- wrong positive classification is blocking.

Availability/recall gate:

- critical positive fixtures must not regress into excessive UNKNOWN;
- track recall/UNKNOWN against the established baseline.

This prevents a "safe but unusable" recognizer from passing forever.

## 4. Architecture workstreams

### Workstream A — Current-state audit before refactor

The local agent must first produce evidence for these hypotheses:

1. Which production recognition paths still return only bool/rect rather than sufficient traceable evidence despite `FrameEvidence` already existing?
2. Which OCR call sites are used for category/expected-value decisions rather than actual open values?
3. Which retry/cooldown/cached-target fields are long-lived and not centrally reset at step/scene/round boundaries?
4. Where, if anywhere, a decision crosses an input boundary using stale frame evidence or combines recognizers that captured different frames?
5. Which current fallback/recovery actions have explicit scene authority and postconditions, and which are heuristic/liveness shortcuts?

No production refactor may begin before this map exists.

### Workstream B — Recognition evidence convergence

Do not create a new parallel perception framework.

Extend the existing `FrameEvidence` / `MatchResult` ecosystem only where required so traceable recognition decisions can carry, when applicable:

- value/result;
- score;
- margin;
- ROI;
- frame generation/sequence;
- recognizer/method;
- reason (`ok`, `ambiguous`, `low_signal`, `no_match`, etc.).

Keep existing call signatures compatible during migration where practical.

### Workstream C — Count-based color evidence

Introduce one small reusable color-count helper/profile only after fixture-based A/B evidence confirms a real NCC blind spot.

Minimum behavior:

- RGB or HSV range mask;
- optional morphology, explicitly disabled for text-like masks;
- target coverage / F1-style evidence;
- geometry-aware caller remains responsible for semantic meaning;
- output is evidence, never direct input authority by itself unless the caller's profile explicitly defines a pure-color semantic object.

Pilot targets must come from existing Ground Truth, not newly invented synthetic-only cases.

### Workstream D — Verified action convergence

Do not introduce a second action state machine beside `PendingAction` / `ActionLifecycle`.

First determine whether those existing types can be evolved to cover the common contract. Prefer extending/consolidating them over adding `VerifiedAction` as a parallel concept.

Target contract:

- precondition evidence on a fresh frame;
- target derived from recognized evidence (not a magic absolute coordinate when a recognizer is available);
- one mechanical input;
- business postcondition;
- timeout;
- same-target bounded retry with re-observation before retry;
- typed result/failure.

Business fallback remains explicit in the caller/Policy.

### Workstream E — Recovery governance

Inventory current recovery/watchdog/unstuck behavior first.

Target governance:

- L0: observation only, bounded by time and fresh-frame count;
- L1: known popup/known recovery scene only, using ordinary production thresholds and explicit postcondition;
- L2/L3: defer until each scene's business idempotency and side effects are documented;
- L4: BLOCK / stop / incident bundle.

Special review target: production liveness shortcuts that send ESC/key input after a stall. They are not automatically wrong if independently authorized by a known HUD, but they must prove:

- fresh scene authority;
- no modal/postgame conflict;
- bounded attempt budget;
- postcondition or explicit no-progress result;
- reset scope;
- no conversion of UNKNOWN into input authority.

### Workstream F — Incident/trace convergence

Extend the existing `IncidentArchiver`; do not build a second trace service.

Desired incident evidence, added only where missing:

- frame generation/sequence;
- scene before/after;
- recognizer method/ROI/score/margin/result;
- OCR raw text/conf/profile when relevant;
- pending action + target;
- SendInput outcome (explicitly marked non-business);
- postcondition attempts and elapsed time;
- scoped retry/cooldown/timer values;
- release SHA/resource identity;
- round/session index and runtime health summary.

Keep recording passive and bounded.

## 5. Execution stages

### Stage 0 — Audit + measurement only

No behavior change.

Deliverables:

- OCR usage map (`value`, `expected-value`, `category`, `debug/display`);
- transient-state scope/reset map;
- recovery/input-authority map;
- frame freshness/invalidation map;
- current incident/trace coverage map;
- 20-round or equivalent existing-real-capture baseline when real-machine access is available.

### Stage 1 — Lowest-risk convergence

Choose only 2–4 items justified by Stage 0 evidence. Preferred candidates:

- typed OCR reads / expected-glyph verifier at confirmed overused call sites;
- count-color hard gate at 2–3 proven color-state targets;
- central reset for proven leaking round/scene transient state;
- enrich existing incidents/evidence metadata without changing decisions;
- consolidate one repeated mechanical retry into the existing pending-action lifecycle.

No broad mediator rewrite.

### Stage 2 — Limited structural migration

Migrate only 2–5 high-value business transitions with existing Ground Truth.

Candidates may include lobby prefix confirmation, ready/start transition, one card-choice path and one postgame transition, but the actual pilot set must be chosen by evidence.

Each migrated transition must retain:

- old-behavior baseline;
- explicit new authority/postcondition contract;
- offline regression;
- rollback condition;
- declaration of what still requires Windows/KK real-machine validation.

### Stage 3 — Soak and cleanup

Only after Stage 2 is stable:

- 50–100 round real-machine soak;
- measure completion count, UNKNOWN rate, incident count, recovery count, worker restarts, memory/handle/thread slope;
- delete/merge only code proven redundant after migration;
- no new abstraction introduced during cleanup.

## 6. Stop conditions

Stop/reject a proposed refactor if any of these occurs:

- UNKNOWN gains new input authority;
- click success/frame change replaces a business postcondition;
- a generic action primitive gains a second target/business fallback;
- an existing `FrameEvidence`, `PendingAction`, `IncidentArchiver` or matcher capability is duplicated under a new name;
- real incident regression produces a wrong positive;
- critical positive recall/UNKNOWN regresses beyond the accepted baseline;
- a workflow/control DSL begins to emerge in perception configuration;
- production complexity grows without deleting at least an equivalent special-case burden;
- a change is justified only by synthetic replay and has no corresponding business/GT evidence.

## 7. Git governance

Use a dedicated branch/worktree for the implementation phase.

Recommended branch: `refactor/architecture-convergence-20260904`

Rules:

- base from the exact current `trial-merge` HEAD and record the SHA;
- no `reset --hard`, `git clean`, `git add .` or `git add -A`;
- preserve existing captures/fixtures/baselines unless a separately reviewed task explicitly changes them;
- do not weaken thresholds/tests to obtain green;
- commit by stage or coherent workstream;
- push branch, but do not merge automatically;
- PR only after Stage 0 findings are recorded and Stage 1 has focused/full test evidence;
- real-machine PASS may only be claimed from actual Windows/KK Ground Truth.

## 8. Expected end state

The project should converge toward fewer concepts, not more:

- existing `FrameEvidence` as the frame/freshness/cache authority;
- existing matcher + small count-color extension where proven useful;
- typed OCR reads rather than open text for Policy paths;
- existing `PendingAction`/`ActionLifecycle` evolved toward a verified mechanical action contract;
- business fallback left visibly in Policy/FSM;
- existing `IncidentArchiver` enriched into the trace-to-fixture backbone;
- recovery governed by known-scene authority, not universal escape actions;
- FSM preserved.

Success is not "mediator.py is small". Success is: fewer duplicated concepts, smaller error propagation radius, explicit authority/postconditions, and demonstrably better 50–100 round stability without regressing fail-closed behavior.
