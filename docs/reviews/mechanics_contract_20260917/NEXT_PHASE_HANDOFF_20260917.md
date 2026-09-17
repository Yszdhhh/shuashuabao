# ShuaBao Next Phase Handoff — 2026-09-17

## 0. Canonical refs

- Production working branch: `fix/solo-live-regression-20260915`
- Current production branch HEAD verified by cloud: `5b0f2436c5fe8ec2057f4266f42170edd6a95e4a`
- Last archived candidate source SHA inside the current evidence: `ff0d7ca948084f598a76877f5a080595dd4de840`
- Mechanics research branch: `docs/mechanics-contract-20260917`
- Mechanics research commit: `9565923203a4fda8b79c134d6cd9655b0a8e896c`
- Frozen live harness baseline: `7a6c36bbbdc39064ceed1aebd9ffc301bfeea342`
- Main: keep unchanged until formal GT and final review.

This document is the next-phase control handoff. Do not treat the 2351-pass regression suite or candidate-injection READY as sufficient proof of formal GT readiness by themselves.

---

## 1. Current verdict after reconciling Gemini and Claude

### Confirmed closed and should remain closed

- P0: TQTZ / early challenge must not preempt an active modal / interaction surface.
- P0: equipment slots 2–6 must never receive blind LMB inspection clicks.
- periodic F4 in `normal_farm` is disabled.
- bond identity / near-complete / unnamed treasure safety work from the recent repair series should be preserved unless a new failing reproduction proves otherwise.

### Regressions still present at `5b0f243`

The final Gemini report says these areas are CLOSED, but the actual commit chain and Claude's read-only incremental audit show later regressions:

1. **High-wood scheduler regression**
   - `7d034de` removed the hard F<->G lock and added bounded treasure service.
   - `25092cbdc4a4842303aaecf2e38f65eaff2c5797` re-added the `wood >= 1000` hard F<->G lock and removed the treasure exemption.
   - `ff0d7ca` then changed the test back to explicitly assert "strict F <-> G, no side branches".
   - Result: V / evolve / equipment / pickup / merchant / artifact starvation risk is back by design.

2. **Positive-HUD gate regression**
   - `6952660` added a positive `_is_in_game_hud(frame)` gate before normal in-game actions.
   - `25092cbd...` removed that gate.
   - UNKNOWN / unclassified in-game surfaces therefore need re-audit before GT.

3. **QUIT / NEXT recovery regression**
   - `6952660` added surface reclassification and fallback from NEXT back to QUIT when the confirm disappeared but HUD remained.
   - `25092cbd...` restored unattended infinite re-arm behaviour.

4. **Room form input contract regression**
   - the staged multi-tick room-name/password fill was replaced by same-call name + password input using direct executor hotkey/paste operations.
   - Re-check single-input ownership and livelock with a real input recorder; current "no livelock" test is not sufficient proof of one-input-per-tick compliance.

Because of these four regressions, the current state is:

- CODE AUDIT: **HOLD**
- INPUT SAFETY: **PARTIAL GO** (the two original P0s closed, positive-HUD ownership needs re-closure)
- SCHEDULER: **HOLD**
- MULTI-ROUND: **HOLD**
- FORMAL GT: **HOLD**
- HARNESS REBASELINE: **FORBIDDEN**
- MAIN MERGE: **HOLD**

---

## 2. New mechanics conclusions from Claude research

The mechanics report changes the implementation plan in several important ways.

### 2.1 Observation is the current bottleneck

The game exposes two different concepts on F cards:

- bond/set header + progress, e.g. `祝福(2/3)`, `藏宝图(0/3)`;
- concrete card name below the icon, e.g. `智力祝福`, `藏宝图(一/二/三)`, `姜子牙`.

Current production OCR mostly observes the header, while advanced mechanics need concrete card identity, rarity, inventory identity/count and per-slot state. Do not continue adding card-name business rules until the observation layer can prove those identities.

### 2.2 Pirate is not "just another advanced group"

Pirate needs a lifecycle spanning:

`藏宝图 gate -> 开进码头 -> pirate card acquisition -> bounty/pill consumption -> inventory/backpack pressure -> 毁灭战舰 persistent engine -> handoff to later sets`

It must coexist with inventory-capacity management even after the set is "formed".

### 2.3 Scheduler should be bounded-priority, not hard F/G ownership

Use the mechanics research direction:

1. active modal / transaction owner;
2. capacity emergency;
3. F stuck-draw recovery;
4. bounded waiting for V/G;
5. expiring opportunity;
6. planned F/G/V service;
7. deferrable economy actions.

Do not tune magic thresholds first. First add observability for wait time and capacity pressure, then calibrate with GT.

### 2.4 F hidden draw persistence is a real mechanism

A hidden F draw can remain the same across repeated reopen attempts. If the policy neither selects nor refreshes it, reopening F can livelock. This needs an explicit draw fingerprint / repeated-draw counter and bounded refresh/backoff behaviour.

### 2.5 Current advanced-card policy must stay fail-closed where identity is not observable

Do not wire guide-only card names, pirate bounty use, backpack-item use, golden monkey, warship fuel, or set completion into production based only on static templates or guide screenshots.

---

## 3. Immediate next execution phase — before any formal GT

### Owner: Gemini or Codex executor

Create a small follow-up commit series on `fix/solo-live-regression-20260915`. Do not rebase, merge main, or rebaseline.

#### A. Re-close the four regressions above

1. restore bounded scheduler semantics from `7d034de` without restoring unsafe behaviour;
2. restore positive HUD evidence before opportunistic in-game input;
3. restore bounded QUIT/NEXT surface reclassification and Round1 -> Round2 progression;
4. restore staged room form transaction so click/hotkey/paste do not bypass one-input ownership.

Do not merely change tests. Add failing reproductions first and prove they fail on `5b0f243`.

#### B. Add F-draw livelock protection

Minimum requirement:

- stable draw fingerprint;
- count repeated reopen of the same actionable draw;
- if no safe selection occurs: refresh if budget/resources permit, otherwise close + bounded backoff;
- no infinite 3-second reopen loop at high wood.

A live example exists in the mechanics evidence where the same draw persisted for ~155 seconds and included `智力(2/4)`.

#### C. Add shadow-only observability, not a new runtime policy engine

Add trace fields needed for the next GT:

- wood, G badge, V badge, kill currency every ~3 s;
- scheduler selected service and wait age per F/G/V;
- F draw fingerprint, refresh count, reopen count;
- bond-bar occupancy; item-bar occupancy;
- bag free-slot count when the bag is positively identified;
- current transaction owner / interaction surface;
- round transition state and reason.

Do **not** implement card-name OCR or pirate automation in this same patch set unless the evidence is already strong and isolated.

#### D. Tests and evidence

- RuntimeMediator tests for all four regression closures.
- Round1 -> Round2 offline integration.
- unknown/no-positive-HUD -> zero physical input.
- F repeated-draw livelock regression.
- full pytest; archive exact pass/skip/xfail/warning counts.
- zero-input candidate injection identity/readiness bound to the final candidate SHA.

Stop after push. No formal GT yet; wait for cloud re-audit.

---

## 4. Formal GT phase — after cloud confirms the re-closure

Run two layers, in this order.

### GT-0: controlled normal-farm smoke / safety GT

One short controlled run to prove:

- no modal/HUD ownership regression;
- no slot2-6 blind clicks;
- no periodic solo F4;
- F/G/V all receive service under high wood;
- F repeated-draw does not livelock;
- quit -> room -> Round2 works once.

If any of these fail, stop and save a bundle before changing code.

### GT-1: mechanics acquisition runs

Prioritise the minimum mechanics GT list from `MECHANICS_CONTRACT_RESEARCH_20260917.md`:

1. bounty use in HUD + bag, with and without a valid target;
2. swallow-pill target behaviour across rarity / slot arrangements;
3. left-click consumable from bag;
4. Z pickup: item bar full + bag free slot;
5. taking a stack-completing bond while the bond bar is full;
6. complete `藏宝图 -> 开进码头 -> pirate pool` run;
7. cost of reopening a hidden F draw;
8. hero-card left click before evolution;
9. one complete single-player resource timeline;
10. warship fuel insertion frequency / full-bar behaviour if reachable.

These GT runs are evidence acquisition. Do not immediately auto-wire each observed fact into production.

---

## 5. Architecture / mechanics development after GT

### Owner: Codex/Sol for implementation; Claude for read-only research/review

Implement gradually, in this order:

### Phase M1 — GameStateSnapshot (shadow only)

Typed observation snapshot with UNKNOWN states:

- F header, concrete card name when observable, rarity;
- per-slot bond/item state;
- wood, G/V badges, kill currency;
- bag capacity;
- interaction surface + active transaction.

No input changes.

### Phase M2 — ResourceScheduler shadow mode

Pure function:

`GameStateSnapshot + current build intent -> desired service`

Trace shadow decision vs actual production decision. No input authority yet.

### Phase M3 — MechanicsFacts

Plain data, evidence-classed facts, no DSL. Start with negative safety facts first. Guide-only facts can help OCR normalisation but cannot grant click authority.

### Phase M4 — BuildState

One pure state machine per advanced set. Pirate first, because it exposes the capacity / consumable / scheduler integration requirements.

### Phase M5 — Transaction wiring

Reuse existing InteractionSurface / PendingAction / EquipmentFSM / MerchantFSM / PublicBagFSM. Mediator remains an adapter; do not duplicate transactions in build logic.

---

## 6. Pirate-specific roadmap

Before implementation, resolve/GT:

- bounty interaction and postcondition;
- whether bag left-click uses bounty/pill;
- how bounty chooses target;
- colour/tier compatibility and whether higher tier may consume lower-tier targets;
- protected pirate cards;
- pill target rule;
- bag pressure / reserved slots;
- `藏宝图(一/二/三)` observation and gate progression;
- `开进码头` and warship counters.

Do not treat five bounty colours as aliases of one item; they require distinct tier identities.

---

## 7. Owner decisions to keep explicit

Do not let an agent silently decide these:

1. `wood >= 1000` F-visit cap 5 vs 15. This is less urgent than removing starvation; defer until GT calibration.
2. V/G bounded-wait thresholds.
3. wood reserve for refresh / build plan.
4. bag reserved free slots.
5. meaning of "木材不用吞噬丹".
6. bounty downgrade/substitution rule when exact colour is missing.
7. protected-card list for pirate / pill use.
8. whether the secret-realm build-order screenshot becomes product policy.
9. whether current skill presets should be changed from the six guide builds.
10. golden-monkey policy (keep fail-closed until explicit GT/owner approval).

---

## 8. Agent assignment

### Gemini / Codex executor

Best for:

- the immediate four regression re-closures;
- F-draw livelock guard;
- trace/observability additions;
- tests, evidence and candidate preflight;
- later M1/M2 implementation.

### Claude

Best for read-only:

- review the new re-closure commit after cloud first-pass;
- analyse mechanics GT bundles;
- refine Pirate lifecycle, advanced-group definitions and skill graphs;
- adversarial review of state ownership / input ownership / evidence classes.

Claude should not share the production worktree while the executor is writing.

### Cloud control tower

- verify remote refs and diff;
- reconcile executor claims against actual code/evidence;
- decide GT gate;
- maintain canonical handoff and branch/PR policy.

---

## 9. Git / branch / PR policy

For now keep exactly two active lines:

1. `fix/solo-live-regression-20260915` — production fixes + tests + GT evidence only.
2. `docs/mechanics-contract-20260917` — Claude mechanics research + this handoff only.

Do not merge the docs branch into the fix branch before the next GT candidate is frozen, because doing so only changes branch SHA and forces another identity record with no production benefit.

After formal GT and final cloud + Claude review:

1. integrate the docs commit(s) into the production branch once;
2. rerun final zero-input identity/readiness on the resulting final HEAD;
3. open **one** PR from `fix/solo-live-regression-20260915` to `main`;
4. attach the final GT summary and mechanics report links in the PR body;
5. merge only after review; then delete the temporary fix/docs branches.

Avoid opening a separate mechanics-doc PR unless the production PR is delayed for a long time.

---

## 10. Next gate

The next gate is **not** "more architecture implementation" and is **not yet** formal GT.

The next gate is:

> Re-close the four regressions at `5b0f243`, add F-draw livelock observability/protection, rerun Runtime/full regression + candidate preflight, then cloud re-audit.

If that passes, immediately move to controlled GT instead of continuing offline optimisation.
