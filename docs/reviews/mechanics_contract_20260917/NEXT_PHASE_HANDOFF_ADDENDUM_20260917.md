# ShuaBao Next Phase Handoff Addendum — 2026-09-17

## Latest branch state

### Production candidate

- Branch: `fix/solo-live-regression-20260915`
- Candidate HEAD: `4f57f1e1d632b394a1f25811f60b57708fb75ebd`
- Status: Pre-GT candidate
- No merge to main.
- Harness baseline unchanged.

### Mechanics research

- Branch: `docs/mechanics-contract-20260917`
- Research: `MECHANICS_CONTRACT_RESEARCH_20260917.md`
- This branch is documentation/control tower only.

### GT test branch

- Branch: `test/pirate-necromancy-gt-20260917`
- HEAD: `dab22268bb383ddaf7f8aa9739dd0aaf66ac12d3`
- Purpose: evidence capture, test profiles, manual GT preparation.
- Not a production branch.

Important:
The GT branch was created before the latest production candidate was frozen. Before real GT execution, the test branch must be aligned to the production candidate `4f57f1e` without modifying production history.

---

## Production system vs test branch boundary

### Production branch (`fix/...`)

Only contains:

- Runtime behavior fixes.
- Input ownership safety.
- Scheduler semantics.
- Production tests.
- GT evidence after validation.

Do NOT add:

- Pirate-specific hardcoded branches.
- Test-only build orders.
- Experimental card rules.
- Guide-derived heuristics.

### Test branch (`test/pirate-necromancy-gt-20260917`)

Allowed:

- Test profile.
- Dashboard experiment configuration.
- GT capture scripts.
- Evidence documents.
- Manual GT bookmarks.
- TEST_ONLY / PROPOSED_PRODUCTION_CHANGE prototypes.

Not allowed:

- Copying a second RuntimeMediator.
- Building a parallel pirate automation engine.
- Claiming manual actions as AUTO PASS.

---

## Current Pirate / Necromancy GT status

All actual mechanics GT remain unexecuted:

- PIRATE_GT: BLOCKED / NOT_RUN
- NECROMANCY_GT: BLOCKED / NOT_RUN
- Bounty GT: NOT_RUN
- Bag consumable GT: NOT_RUN
- Full inventory replacement GT: NOT_RUN
- Postgame secret realm GT: NOT_RUN

Prepared only:

- Test profile wiring.
- Evidence directory.
- Offline profile validation.
- HWND capture prerequisite fixes.

---

## Next GT execution order

1. Align test branch to production candidate.
2. Prove valid game HWND + visible game frame.
3. Run normal single-player path with manual assistance allowed.
4. Capture:

### Secret realm

Victory → postgame → NPC → confirm → real secret realm HUD → MAIN_LINE recovery.

### Pirate

藏宝图 → 开进码头 → pirate pool changes.

### Inventory

- Full item bar.
- Z pickup routing.
- Bag open.
- Consumable left click.
- Full bond-card replacement window.

### Necromancy

Only verify Settings/policy/runtime observation path first.
Do not implement new mechanics from screenshots without GT.

---

## Current evidence rules

Use labels:

- AUTO
- USER_ASSISTED
- MANUAL_GT
- USER_CONFIRMED
- UNKNOWN

Never convert:

- screenshot → production rule
- template exists → feature complete
- click success → business PASS

---

## Agent assignment

Codex/Sol:
- Production fixes.
- Runtime tests.
- Candidate maintenance.

Claude:
- Read-only mechanics review.
- Pirate lifecycle analysis.
- Advanced card strategy review.
- Adversarial architecture review.

Gemini:
- Visual evidence analysis.
- Screenshot/frame understanding.
- GT evidence assistance.

Cloud control tower:
- Branch truth.
- Evidence validation.
- GT gate.

---

## Next conversation entry

Start by reading:

1. This addendum.
2. `NEXT_PHASE_HANDOFF_20260917.md`.
3. `MECHANICS_CONTRACT_RESEARCH_20260917.md`.
4. Current production branch HEAD.

Do not rely on old chat context.
