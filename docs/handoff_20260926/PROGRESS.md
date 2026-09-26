# Round-4 live test handoff progress (2026-09-26)

Keep this file current. Whoever picks the work up (any Claude, GPT or the Owner) starts here.

## Where things are

- Local test build: `G:\刷刷宝\GameScript-Local`, branch `chore/gate-baseline-20260925`, pushed to `origin/claude/round4-live-20260926` (PR #51, draft, base `claude/project-thread-fqyf7h`).
- Desktop test bench: `C:\Users\10639\Desktop\刷刷宝 实机测试台.lnk`, argument `-ProductionSourceSha <40-hex>`. Only that SHA is changed; check with `python tools/live_scenario_capture.py identity --repo-root . --production-source-root . --production-source-sha <sha> --json` (`ready_for_gt: true`).
- Fast lane (AGENTS.md): related tests + `tests/contract` + `tests/test_live_harness_refresh.py`, then re-pin `config/runtime_identity_manifest.json` `candidate_sha = git log -1 --format=%H -- src/shuabao`. Full `tools/release_gate.py` only before the merge tier.
- Owner rules: `G:\刷刷宝\素材\系列标签\README_Owner口径.md` and the lock table `tests/test_owner_ingame_rules_lock_20260924.py`.

## Merged into round4 today (latest first)

| What | Source |
|---|---|
| Pack whitelist (刀刀 8 equipment, 修仙 五极山, 海盗 藏宝图) + 12 rules registered in lock table | cloud PR #59 |
| Refresh button must be missing 3 frames before fallback | cloud PR #60 |
| Banned list restored | cloud PR #58 |
| Devour hold only for 亡灵 (Owner 06:57) | cloud PR #57 |
| 三国四选三 | cloud PR #55 |
| Stage-select truncated last row judged by pixels | cloud PR #56 |
| 祝福 finished first; no black-market pill trip while 亡灵 is running | omp `fix/restore-owner-rules-20260926` (5bb5d9ab) |
| Bond fallback guard: no unselected advanced-deck cards, full bar only merges | omp `fix/bond-fallback-guard-20260926` (81b8b203) |
| GPT rework of PR #51 (0838ff4c: fallback gate 禁字法/安身法, hero anchor only inside evolve transaction, stage truncation evidence) | pushed by GPT |
| Evolve wait releases instead of stopping (PR #54), four-card fast-path tests (PR #53), four-card bond not hero (PR #52) | cloud |
| Series-label direct pick, 祝福 direct, four challenges batch click + verify | codex `perf/direct-family-pick-20260926` |
| Hero two-card screen recognised; evolve wait bounded | codex `fix/evolve-feedback-deadlock-20260926` |

## Waiting / not merged

| Item | Where | Next step |
|---|---|---|
| Owner rules full reconciliation | cloud thread "Owner 规则全面对账" | small PRs to round4, merge one by one |
| `tests/test_urgent_merchant_20260924.py` 3 failures after omp owner-rules merge (merchant step no longer opens H for wood at wood=300) | local | check after #57 lands; if still red, fix in `_solo_wants_merchant` |
| Owner hand-cut series labels (海贼王, 海盗, 刀刀装备, 三国, 修仙, 魔法师/元素师/屠戮者) | branch `feat/owner-labels-20260926` (worktree `G:\刷刷宝\Worktrees\pick-speed2-20260926`), WIP 9b103ab1 + merge 54c69e80 | verify hit/false-hit on the 93 bond panels, then merge |
| Unified exclusive screen classifier | brief `scene_classifier.md` (Claude scratchpad), paused by Owner until one EX run passes | resume later |

## Closing steps

1. Merge everything in "Waiting" that is ready; fast lane must be green.
2. `python tools/release_gate.py`. The only intended asset delta is +6 bond family templates (genji/shenfa recut). If every other stage is green: `python tools/release_gate.py --update-baseline --reason "PR #51: add 6 verified bond family templates; genji/shenfa recut from live frames"`, commit `docs/baselines/GATE_BASELINE.json`, push, rerun the gate and require 4/4 PASS, exit 0. Never refresh the baseline while pytest is red.
3. Point the test bench at the final SHA, confirm `ready_for_gt: true`, put the SHA and gate result in the PR #51 description.

## Owner live re-checks (morning)

1. Entry 12 solo with stage target 1-23: stage starts after the cut-off last row is clicked.
2. Bond panel: 祝福 taken first until 3/3, by series label without OCR delay; 成长/经济 next, then the current advanced deck.
3. Hero evolution two-card screen: picks the higher rarity (e.g. UR 小鱼), no freeze; if the hero screen never appears the run continues.
4. Opening four challenges: all four on within one step, wood challenge re-clicked if missed.
5. After 3 refreshes the bond panel takes one card (no unselected-deck starter, no overflow on a full bar); black market only when wood < 500 or no pill with 8 slots used, never for pills while 亡灵 is running.
