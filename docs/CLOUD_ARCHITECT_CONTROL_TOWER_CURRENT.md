# ShuaBao Cloud Architect Control Tower — CURRENT

> Canonical handoff for the active ShuaBao control-tower state.
> Always read this file first from `handoff/latest`, then independently verify the live `origin/trial-merge` HEAD before trusting any local Agent report.
> This branch is documentation-only. Do not merge `handoff/latest` into `trial-merge` just to carry status notes.

## 0. Current executive state

Repository:

`https://github.com/Yszdhhh/shuashuabao`

Production integration branch:

`trial-merge`

Last independently verified remote HEAD:

`21c33c727f7f9521db39c8c6ef70876b9b890eda`

Commit:

`fix(runtime): close fresh-evidence and bounded lifecycle gaps`

Parent:

`a3bc4cdad0b11decaa578140e1a03c4b5380b8e7`

Verified commit chain:

`ea9776cc3f1836624ce058240b447a0ff890fbe1`
→ `474d1bce932a1a533d768cb4ebcd3ffa866edb01`  Corrective A
→ `a3bc4cdad0b11decaa578140e1a03c4b5380b8e7`  Corrective B
→ `21c33c727f7f9521db39c8c6ef70876b9b890eda`  Corrective C

Current cloud verdict:

`CORRECTIVE_C_ACCEPTANCE = REJECT / BLOCKED_WITH_CODE_DEFECTS`

Therefore:

- `BUILD_AUTHORIZATION = NO`
- `RELEASE_APPROVAL = NO`
- `GOLDEN_RUN_AUTHORIZATION = NO`

The next production task is a narrow **Corrective C-D** on top of `21c33c7`, not a new feature wave.

In parallel, a local **Astra read-only architecture review** is being run for the future KB / decision-policy redesign. Astra must not modify production while Corrective C-D is active.

## 1. Historical context

The original 2026-09-07 Hitch search deadlock was fixed in the `b15da05` line. Subsequent real-machine runs then exposed broader problems in:

- Room List surface authority
- ROOM_WAITING → L1 takeover
- foreground ownership
- arbitrary-state startup reconciliation
- Ready 180s timeout lifecycle
- Pressure Transfer postcondition
- TQTZ early-challenge lifecycle
- Archive 7/8 availability
- NPC Hub / Archive / Stage mutual exclusion
- rigid choice-policy behavior / KB under-wiring

The current project is intentionally split into three independent workstreams:

1. **Runtime correctness** — physical-surface authority, bounded lifecycles, fresh business postconditions.
2. **Natural E2E Harness** — real-production execution/evidence capture without copied FSM or fake success.
3. **Choice Policy / KB evolution** — future deterministic, explainable, less-rigid strategy layer.

Do not mix these into one implementation commit.

## 2. Corrective A — landed

Commit:

`474d1bce932a1a533d768cb4ebcd3ffa866edb01`

A addressed:

- ROOM_WAITING passive L1 probing
- observation-path focus removal
- post-game/startup precedence
- Pressure Transfer request/postcondition direction
- Kick detection path
- Ready 180s exit sequencing

Cloud review after A/B found that several claimed closures were still partial, which led to Corrective C.

## 3. Corrective B — landed

Commit:

`a3bc4cdad0b11decaa578140e1a03c4b5380b8e7`

B addressed:

- TQTZ no longer treating click-success as business success
- `auto_close_main_line=true` vs generic AutoTask re-enable conflict
- Archive 7/8 false-unavailable issue
- NPC Hub / Archive mutual exclusion
- UNKNOWN post-game zero-input intent

Cloud review found B still had stale/fresh-evidence gaps and weak availability authority, which led to Corrective C.

## 4. Corrective C — exact-SHA review

Current HEAD:

`21c33c727f7f9521db39c8c6ef70876b9b890eda`

C changed:

- `src/shuabao/mediator.py`
- `tests/test_b15da05_real_regressions.py`
- `tests/unit/test_startup_state_priority.py`
- `tests/test_p1b0_post_game.py`

### 4.1 C1 Cold-start / arbitrary takeover

This direction is accepted at code level:

- old `std > 8 => IN_GAME` weak authority was removed;
- game-client startup now prefers known PostGame / Pause / Stage / trusted HUD;
- unclassified game-client frames become `UNKNOWN` rather than automatically entering MAIN_LINE.

This closes an important class of arbitrary noisy-frame takeover errors.

### 4.2 C2 Pressure Transfer

Direction is largely accepted at code level:

- click success no longer equals transfer success;
- timeout no longer equals transfer success;
- request stores FrameEvidence generation;
- confirmation requires a later generation plus trusted HUD plus pressure locator disappearance;
- Pressure path no longer intentionally owns Ready-timeout semantics.

Keep this lifecycle isolated.

### 4.3 C3 Kick modal — NOT PROVEN

The C report claimed:

`override = NO`

but exact remote tests still contain `_hitch_ocr_override` injection in the kick regression.

Therefore the real chain remains unproven:

`real kicked frame -> production OCR -> typed kick classification -> safe dismiss`

Known real incident path to inspect locally before declaring missing GT:

`C:\Users\10639\AppData\Local\ShuaBao\incidents\incident_160515_883_314868a6`

Also re-audit generic modal handling:

- **KNOWN_KICK** may safely dismiss via Esc/X/Cancel when not in active game authority;
- **UNKNOWN_GENERIC_MODAL** must remain ZERO INPUT;
- never click `立即购买`.

Do not use OCR override or synthetic text as Ground Truth.

### 4.4 C4 Ready 180s — still defective

The C report and exact source disagree.

Reported:

- 30s hard deadline
- `AttemptBudget(actions_left=3)`
- `_hitch_host_started(frame)` based cancellation

Exact code instead uses:

- a 20s timeout episode deadline;
- plain `_hitch_ready_timeout_attempts < 3` plus >=5s spacing;
- `_is_game_client_frame(frame)` / game-window title as a cancellation signal.

The main code defect is semantic:

`game client HWND/title exists != host/game business start confirmed`

A Ready-timeout leave episode may only be cancelled by a trusted L1 business surface (for example trusted HUD / Stage / another already-validated L1 surface), not by title presence alone.

Current rule remains:

`Ready business confirmed -> 180s wait -> bounded safe leave -> fresh lobby/no-room confirmation -> blacklist stable room key`

Never blacklist before physical exit confirmation.

### 4.5 C5 TQTZ — P0 cross-round lifecycle leak

C added explicit `_tqtz_abandoned=True` after retry exhaustion, which is correct for the current round.

However current round-reset code clears `_tqtz_clicked` / pending fields but does not clearly reset:

- `_tqtz_abandoned = False`
- `_tqtz_attempts = 0`
- request-generation lifecycle state

Because `_maybe_click_tqtz()` returns immediately when `_tqtz_abandoned` is true, one exhausted round can permanently suppress TQTZ in future rounds.

Required regression:

`round 1 -> exhaust 3 attempts -> ABANDONED`
→ round-reset seam
→ `round 2 -> TQTZ must be eligible again`

Do not solve this with a second parallel lifecycle.

### 4.6 C6 Archive availability — still not authoritative enough

C correctly removed the old red-pixel `>=60` UNAVAILABLE authority.

Current code can parse OCR text like `num/den`, but exact review found remaining weaknesses:

- `0/x` can be generalized too broadly unless denominator is explicitly validated as the expected archive counter (e.g. exact `0/8` when that is the true mechanic);
- OCR confidence/status must be strong enough before creating business authority;
- a green-pixel count still directly returns `AVAILABLE` in the fallback path;
- most importantly, the compatibility wrapper returns only `unavailable: bool`, so `UNKNOWN` can collapse to `False` and the caller may continue to challenge-card lookup/click.

Required typed semantics:

- `AVAILABLE` -> action may proceed if other authority holds
- `UNAVAILABLE` -> skip safely
- `UNKNOWN` -> ZERO INPUT / no challenge click

Green pixels may remain diagnostic/supporting evidence but should not independently authorize a business click.

Required negative tests should include:

- exact trusted `0/8`
- `0/3`
- low-confidence `0/8`
- green-noise ROI
- `UNKNOWN + card template hit`

Do not use synthetic colored rectangles as production proof.

### 4.7 B5 UNKNOWN post-game zero-input

The rewritten test is better than the prior version because it no longer patches a business helper to force an early return.

Keep the full-dispatch requirement:

real/unclassified frame -> production `_tick_main_line()` -> no click/key/scroll -> no fake business phase advance.

## 5. Corrective C full gate status

The Agent reported:

`python tools/release_gate.py --json`

with raw top-level:

`verdict = FAIL`

Pytest stage:

- passed: 384
- failed: 1

The failing test was reported as:

`test_lobby_room_list_evidence_rejects_wrong_tab_template_hit`

Do not automatically accept the claim that this is “historical debt.”

Correct attribution requirement for C-D:

Run that exact test on a detached `a3bc4cd` worktree and on the new C-D SHA.

Only if both fail with the same failure signature can it be classified as pre-existing baseline debt.

Do not modify the test / threshold / baseline just to obtain green status.

## 6. Corrective C-D — NEXT production task

Start from:

`21c33c727f7f9521db39c8c6ef70876b9b890eda`

Scope is intentionally narrow:

1. **TQTZ per-round reset**
   - reset `_tqtz_abandoned`, `_tqtz_attempts`, request/pending generation state at the existing round-reset seam;
   - add a two-round regression.

2. **Ready-timeout cancellation authority**
   - remove game-window-title / `_is_game_client_frame` as sufficient “host started” evidence;
   - require an already trusted L1 business surface;
   - unclassified Hero/game window must not cancel the bounded leave episode.

3. **Kick Ground Truth**
   - inspect `incident_160515_883_314868a6` and related local incident material;
   - use a real raw frame if recoverable;
   - no `_hitch_ocr_override` for proof;
   - UNKNOWN generic modal = ZERO INPUT.

4. **Archive typed availability**
   - only trusted exact progress evidence may yield UNAVAILABLE/AVAILABLE;
   - validate denominator/mechanic and OCR confidence;
   - no green-pixel-only action authority;
   - UNKNOWN must not collapse into “not unavailable” and proceed to click.

5. **Release-gate attribution**
   - A/B the specific Lobby Room List test on `a3bc4cd` and C-D final;
   - run complete `python tools/release_gate.py --json` after targeted tests.

Corrective C-D must remain one narrow production commit.

Do not:

- build
- approve release
- run Golden Run
- modify Choice Policy
- modify Harness
- add generic watchdog/fallback
- loosen global thresholds

After C-D push, Sol must independently verify exact remote SHA/diff before any build/live authorization.

## 7. Solo Live Harness

Dedicated Harness branch:

`test/solo-live-harness-20260907`

Last independently verified Harness HEAD:

`144c0c9adc366a35548f6e1c2e52fad8387da090`

Harness remains useful for evidence capture, but its branch diverged from the production line at the old `b15da05` baseline.

Therefore current Harness must **not** be treated as formal acceptance authority for `21c33c7` or future C-D code until the pure Harness commits are rebased/cherry-picked onto the exact frozen production candidate.

Formal rule:

`Harness SOURCE_RUNTIME == exact production candidate SHA`

before new Natural E2E acceptance.

Current Harness architecture isolation was directionally acceptable, but prior Opus review found acceptance weaknesses such as internal-state promotion, stale confirmation, BLOCKED/safe-stop ordering, and incomplete real-machine coverage of latest Harness changes.

Carry those findings into the future rebased Harness review.

## 8. Choice Policy / KB modernization — parallel READ-ONLY research

The user wants ShuaBao to stop behaving like a rigid rule script.

Current diagnosis:

The project has accumulated many KB facts, guides, lexicons, presets and policy rules, but much of that knowledge is consumed as:

- hard whitelist
- prerequisite gate
- rank
- fixed lexicographic priority
- threshold

rather than as a structured game-state / mechanics / tradeoff model.

This creates the observed behavior:

“more KB -> more rules -> still rigid.”

### Current desired long-term properties

The future strategy layer should remain:

- deterministic
- replayable
- testable
- explainable
- low-latency
- safe/fail-closed

Do not use online LLM decisions, opaque RL, black-box neural control, or a giant second FSM.

### User-supplied strategy examples

Future policy should eventually be able to reason about:

- growth cards having higher value earlier;
- cards one or two copies from synthesis having higher value;
- hero-stat synergy, e.g. high Intelligence -> INT-linked value rises;
- skill synergy, e.g. fire/burn build -> fire/burn cards rise;
- `奥术箭` as main carry -> energy/magic/INT synergy rises;
- slot pressure vs expected near-term synthesis/consumption slot release;
- TAKE vs REFRESH vs GIVEUP/HIDE tradeoff;
- refresh-resource opportunity cost.

### Immediate user-approved v0.1 behaviors

Do not implement until runtime correctness is frozen.

1. If trusted `next_refresh_cost >= 100 wood` and bond slots are still relatively empty, REFRESH should no longer be the blind default. Existing safe/legal candidate may beat refresh; if no safe candidate exists, CLOSE/HIDE is preferable to blindly burning resources.

2. When the current route is provably Fengshen, confidently recognized `肉身成圣` must be allowed as a high-priority Fengshen accelerator candidate rather than being discarded merely because the ordinary hard whitelist does not include it.

Important forensic correction:

`肉身成圣` OCR itself was good in the real run (roughly 0.94–0.998). The failure was policy/KB wiring, not OCR recognition.

Do not treat `肉身成圣` as an ordinary persistent owned-card model without proving its consumable/accelerator lifecycle.

## 9. Astra strategy review — in progress / expected next

A local Astra Agent has been assigned a **read-only architecture/mechanics study** on a frozen strategy-review worktree.

The intended Astra role is open-ended diagnosis/design, not production coding.

It should independently answer why the current system has “lots of KB but still feels dumb,” audit actual KB wiring, and propose the smallest useful next-generation decision architecture.

The working hypothesis offered to Astra is only a candidate, not a mandate:

`hard safety/eligibility -> structured current state -> soft value/tradeoff evaluation -> deterministic action -> fresh business postcondition`

Astra is free to reject Goal layers / utility scoring / lookahead if it finds a simpler better structure.

Astra should distinguish knowledge classes/evidence such as:

- Fact
- Mechanics
- Strategy / preference
- LIVE_VERIFIED
- REPLAY_VERIFIED
- GUIDE
- INFERRED
- UNKNOWN

and explain which evidence can authorize irreversible actions vs only influence soft score/telemetry.

Next cloud conversation is expected to receive:

1. Astra architecture review report;
2. Corrective C-D Agent delivery report.

Cloud must independently verify C-D exact Git SHA before trusting the Agent report.

## 10. Opus sequencing

Do not ask Opus to modify production now.

Recommended sequence:

Astra independent architecture study
→ Corrective C-D closes runtime blockers
→ Sol exact-SHA C-D review
→ freeze production candidate
→ align Harness SOURCE_RUNTIME to exact candidate
→ fresh real Natural E2E bundle
→ Opus second-pass red-team using Astra report + actual code + fresh evidence
→ Sol final synthesis/review
→ only then implementation of the approved Choice Policy migration / build/release as authorized.

For policy architecture specifically:

- Astra = open-ended model/mechanics designer
- Opus = adversarial simplifier / assumption challenger
- Sol = final integration/decision reviewer

Avoid two independent “big designs” that are never reconciled.

## 11. Hard product/engineering rules

1. Live Git beats all Agent summaries.
2. One production code writer at a time.
3. Click/SendInput success is never business success.
4. Same-frame/stale-frame mutation is not a fresh postcondition.
5. Physical surface evidence -> business authority -> action -> fresh physical postcondition.
6. UNKNOWN / ambiguity -> FAIL_CLOSED / ZERO INPUT.
7. HWND/title presence alone is not business authority.
8. Observation must not change foreground; focus is action-scoped only.
9. Do not weaken safety with generic ESC, watchdogs, global threshold loosening or fixed-coordinate hacks.
10. Real fixtures and real-machine bundles outrank synthetic fixtures for acceptance.
11. Guide/KB text must not silently become verified runtime mechanics.
12. Do not mix Choice Policy redesign into runtime corrective commits.
13. No build/release/Golden Run while current runtime candidate is rejected or blocked.
14. Never commit tokens, secrets, credentials or sensitive operator data.

## 12. New-conversation bootstrap

In the next conversation:

1. Read this handoff from `handoff/latest`.
2. Independently verify live `origin/trial-merge` HEAD.
3. User will likely provide the Astra review and Corrective C-D report.
4. For C-D, compare exact `21c33c7..FINAL_SHA`, inspect changed production functions/tests, and verify release-gate attribution rather than trusting summary prose.
5. Re-check especially:
   - TQTZ two-round reset
   - Ready-timeout strong cancellation authority
   - real Kick GT / no override / UNKNOWN generic popup zero-input
   - Archive AVAILABLE/UNAVAILABLE/UNKNOWN typed authority
   - exact Lobby Room List baseline A/B test
6. Classify findings P0/P1/P2 and decide whether production is ready to freeze.
7. Separately review Astra's architecture proposal; do not let it drive production until runtime correctness is accepted.
8. If production becomes accepted, next step is Harness exact-source alignment + fresh Natural E2E before build/release authorization.
