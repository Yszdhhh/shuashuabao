# ShuaBao Local Agent Handoff Addendum — External Reference Matrix (2026-09-04)

This document is part of the architecture-convergence handoff pack. Read it together with:

- `docs/ARCHITECTURE_CONVERGENCE_20260904.md`
- `docs/LOCAL_AGENT_REFACTOR_HANDOFF_20260904.md`
- `docs/FABLE_EXTERNAL_REVIEW_NOTES_20260904.md`

Purpose: preserve the concrete lessons from the external projects reviewed in cloud research so the local agent does not have to rediscover them and does not copy a mature project's framework wholesale. The references are patterns to compare against current ShuaBao code, not permission to import dependencies or rewrite architecture.

## 1. Airtest — borrow bounded visual primitives, not the framework

Reference: `AirtestProject/Airtest`.

Useful patterns:

- `loop_find(...)` performs bounded repeated recognition with explicit timeout and interval instead of an unbounded busy loop.
- `Template` supports thresholding, recorded position/resolution hints, RGB-aware verification and multi-scale behavior.
- The important architectural lesson is not “use Airtest”; it is that recognition/waiting is a bounded primitive and that visual localization can combine shape evidence with color-sensitive verification.

ShuaBao mapping:

- Existing `FrameEvidence`, matcher ROI/multiscale/cache and local color verification already cover much of the same territory.
- Do **not** add Airtest as a runtime dependency merely to obtain `loop_find`/template behavior.
- Audit every retry/wait loop for both a time budget and an attempt/rate budget.
- Keep recognition tied to the same fresh frame for one authority decision; do not combine observations captured at different moments into one logical AND.

What to experiment with:

- only if current local color NCC has a demonstrated color-semantic blind spot, compare count-based color evidence rather than simply cloning Airtest RGB correlation.

## 2. ok-script — borrow “simplest recognizer for the semantic job” and scene-local scheduling

Reference: `ok-oldking/ok-script`.

Useful patterns:

- traditional CV remains the first choice for stable game UI: template, color and geometry before heavier inference;
- OCR is for text/value tasks and object detection is reserved for objects whose position/scale/occlusion make fixed UI recognition insufficient;
- resolution adaptation and annotation/ROI metadata belong in the recognition layer rather than leaking into business policy;
- scene/task logic should decide which recognizers are active instead of running every detector every tick.

ShuaBao mapping:

- Keep OpenCV + typed PaddleOCR as the main path.
- Do not introduce YOLO for fixed lobby/card/post-game UI unless a specific target cannot be constrained by anchor/ROI/template/color.
- Stage 0 must identify OCR/category misuse and recognition calls whose polling frequency is unnecessarily high.
- Prefer scene-local recognition rate limits over global busy scanning.

## 3. MAA / MaaFramework — borrow count-color evidence and bounded task semantics; do not copy the control DSL

Reference: `MaaAssistantArknights/MaaAssistantArknights`.

### 3.1 Color evidence

Current `dev-v2` `Matcher.cpp` behavior observed in review:

- template matching uses normalized correlation;
- `RGBCount` / `HSVCount` construct color-range masks;
- a color F1-style score is computed from active pixels;
- current source multiplies the template result by the color-count result;
- `pureColor` can make a task depend only on color evidence.

Important correction: do not implement from a stale changelog claim that current MAA necessarily uses a geometric mean. Re-check the exact source revision if this detail matters.

ShuaBao policy:

- for safety-critical input authority, prefer independent hard gates: `shape >= T AND color_count >= C`;
- fused scores may be tested for ranking multiple candidates, but must not hide a weak modality;
- pure color is suitable only when the business semantic itself is color/coverage (indicator, border, progress state) and geometry/scene authority is already constrained.

Best pilot targets:

- enabled vs disabled;
- selected vs unselected;
- ready/not-ready;
- rarity/color border;
- red/green/blue indicator;
- health/progress bar.

Do not add color counting to every template.

### 3.2 Task semantics

Useful MAA ideas include explicit ROI, thresholds, masks, retry/maximum attempt controls, delays and error/next handling.

However MAA's data-driven pipeline also demonstrates how a resource description can grow into a control DSL (`next`, error branches, sub-tasks, retry/exceeded branches, etc.). ShuaBao must stop before this boundary.

Safe to data-drive gradually:

- ROI / anchor;
- template path;
- threshold / margin;
- color ranges / masks;
- OCR expected regex/lexicon/value range;
- temporal confirmation count.

Keep in Python Policy/FSM:

- workflow order;
- business fallback;
- action sequence;
- room/prefix/stage switching;
- stop/restart decisions.

## 4. OnmyojiAutoScript (OAS) — borrow typed OCR and bounded polling, not the class hierarchy

Reference: `runhey/OnmyojiAutoScript`.

Useful patterns observed:

- `RuleImage` supports template matching and SIFT/feature matching for cases that actually need scale/feature tolerance;
- `RuleOcr` distinguishes semantic OCR modes such as Full/Single/Digit/DigitCounter/Quantity;
- `BaseTask.appear(...)` can be interval-limited with per-target timers;
- wait/appear/click-until helpers express bounded observation/action loops;
- scene detection and task logic remain explicit Python rather than a universal external DSL.

ShuaBao mapping:

- borrow the semantic idea, not six subclasses;
- prefer one typed-read contract such as `digit`, `counter`, `lexicon_name`, with parse/validation failure -> UNKNOWN;
- for tiny expected-value problems such as lobby prefix `4`/`3`, an expected-glyph verifier may be simpler than a full OCR mode or 0–9 digit bank;
- only use SIFT/feature matching for a proven scale/feature problem; small fixed UI buttons should stay on cheaper ROI/template paths;
- audit recognition intervals so expensive OCR does not run every tick.

## 5. Alas / AzurLaneAutoScript — secondary reference for long-running liveness, but verify exact current source before copying details

The external Fable review used Alas as a reference for long-running Python automation: page recognition, timers, bounded stuck/click handling, wait-until-stable style behavior and incident screenshots/logging.

Use it as a design comparison only. Exact helper names/default timings from the external report were not all independently re-verified in this Git pass.

ShuaBao lessons that remain valid independent of exact Alas APIs:

- recovery input must start from a known scene, not from UNKNOWN;
- every wait/retry is bounded;
- repeated same-target input is rate-limited;
- transient state must have an explicit step/scene/round/session scope;
- errors must stop propagating into later scene assumptions;
- capture enough structured evidence to diagnose a multi-hour failure without reproducing it immediately.

## 6. Cross-project recognition decision rule for ShuaBao

Use the simplest recognizer that answers the business question.

| Business question | Preferred evidence | Secondary/fallback | Notes |
|---|---|---|---|
| Is this a known page? | anchor/template + ROI + margin | second independent anchor if needed | no OCR as the default page detector |
| Is a fixed button present? | anchor-relative template | color hard gate if enabled/disabled color matters | click only from recognized target |
| Enabled/disabled or selected/unselected? | count-based HSV/RGB in semantic ROI | template/geometry hard gate | UNKNOWN between state bands |
| Rarity / color border / indicator | HSV/RGB count + geometry | template if structure is meaningful | pure color is allowed only when semantic meaning is truly color |
| Lobby prefix is expected `4`/`3`? | expected-glyph verifier in anchor-relative ROI | typed OCR candidate + independent confirmation | no open Chinese OCR requirement if business only asks MATCH/NO_MATCH/UNKNOWN |
| Card title / fixed lexicon name | typed OCR + lexicon + margin | one bounded preprocess fallback | ambiguous -> UNKNOWN |
| Counter / progress x/y | typed numeric/counter read + range grammar | finite glyph verifier where practical | parse/range failure -> UNKNOWN |
| Dynamic free-position object | color/contour/feature or detector only if proven necessary | temporal continuity | YOLO remains deferred for current fixed-UI problems |

## 7. Long-thread invariants to verify in Stage 0/Stage 1

These are the cross-project lessons most relevant to 50–100 rounds / multi-hour execution:

1. One fresh frame provides authority for one decision; old pre-input evidence cannot authorize post-input behavior.
2. Multiple recognizers combined in one decision must read the same frame/evidence generation.
3. Recognition output should retain enough evidence for diagnosis (result/value, score/margin, ROI, method, frame generation), not collapse everything into an untraceable bool where avoidable.
4. Every wait/retry has explicit time and attempt/rate bounds.
5. Same-target input has a minimum interval and bounded count.
6. Mechanical retry re-observes the same precondition before re-sending; it never silently changes target.
7. Business postcondition is the only authority to advance the FSM.
8. UNKNOWN has a bounded observation budget; budget exhaustion produces incident/BLOCK, not blind recovery input.
9. Transient values are explicitly step/scene/round/session scoped and reset at their boundary.
10. Expensive recognizers are scene/rate limited; OCR is persistent/warmed/restart-bounded rather than repeatedly constructed.
11. High-risk transitions use risk-tiered temporal confirmation and semantic-ROI stability, not mandatory whole-frame freeze.
12. Round boundary is a deliberate reset point for round-scoped state and a useful place to observe resource drift (memory/handles/threads/worker restarts).

## 8. Trace / incident / regression lessons

Do not create a new trace subsystem. Extend `IncidentArchiver` only where current evidence is insufficient.

Desired evidence for hard-to-reproduce long-thread failures, subject to current code audit:

- recent frames / exact raw failure frame where needed;
- frame generation/time/HWND/client size/DPI;
- scene and recognizer method/ROI/score/margin/result;
- OCR raw result/conf/profile when applicable;
- pending action/target/input result;
- postcondition attempts and elapsed time;
- retry/cooldown/timer state with declared scope;
- round/session index and release/resource identity;
- worker restart/runtime health summary.

Testing split:

- historical real-incident wrong-positive regression: blocking;
- critical positive recall/UNKNOWN: availability/score gate against baseline;
- policy and action-contract tests: blocking;
- frozen startup/OCR smoke: blocking for release;
- synthetic replay: auxiliary only, never called real business PASS;
- real-machine soak: release/acceptance evidence, not a substitute for unit/fixture gates.

## 9. Explicit non-goals from the external comparison

Do not introduce in this convergence phase:

- Airtest/MAA/ok-script/OAS as a new runtime framework dependency merely to copy primitives already present;
- Behavior Tree/statechart rewrite;
- generic workflow YAML/DSL;
- universal `UNKNOWN -> ESC/back/home` recovery;
- YOLO for fixed UI;
- a second OCR service;
- a second frame/evidence abstraction;
- a second action state machine beside `PendingAction`/`ActionLifecycle`;
- a second trace/incident service;
- hot-updatable business policy/action sequences/arbitrary click coordinates.

## 10. Stage 0 external-reference checks

The local agent must explicitly state, in `ARCHITECTURE_STAGE0_AUDIT_20260904.md`, whether each of the following would add new value or duplicate existing code:

- Airtest-style bounded `loop_find` semantics;
- Airtest-style color correlation verification;
- ok-script-style scene-local recognizer scheduling/rate limiting;
- MAA RGB/HSV count evidence and pure-color semantics;
- MAA-style perception data configuration without workflow control fields;
- OAS-style typed OCR semantics;
- OAS-style per-target recognition intervals;
- feature/SIFT matching for any actually proven target;
- semantic-ROI stability before high-risk transitions;
- same-target click/retry budget;
- incident evidence sufficient to turn a real failure into a regression fixture.

For every proposed adoption, identify: current ShuaBao equivalent, missing capability, fixture/GT used, expected gain, regression risk, rollback condition. If the capability already exists, mark `ALREADY PRESENT` and do not rebuild it.
