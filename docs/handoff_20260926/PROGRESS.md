# Round-4 live test handoff progress (2026-09-26)

Keep this file current. Whoever picks the work up (any Claude, GPT or the Owner) starts here.

## Where things are

- Local test build: `G:\刷刷宝\GameScript-Local`, branch `chore/gate-baseline-20260925`, pushed to `origin/claude/round4-live-20260926` (PR #51, draft, base `claude/project-thread-fqyf7h`).
- Desktop test bench: `C:\Users\10639\Desktop\刷刷宝 实机测试台.lnk`, argument `-ProductionSourceSha <40-hex>`. Only that SHA is changed; check with `python tools/live_scenario_capture.py identity --repo-root . --production-source-root . --production-source-sha <sha> --json` (`ready_for_gt: true`).
- Fast lane (AGENTS.md): related tests + `tests/contract` + `tests/test_live_harness_refresh.py`, then re-pin `config/runtime_identity_manifest.json` `candidate_sha = git log -1 --format=%H -- src/shuabao`. Full `tools/release_gate.py` only before the merge tier.
- Owner rules: `G:\刷刷宝\素材\系列标签\README_Owner口径.md` and the lock table `tests/test_owner_ingame_rules_lock_20260924.py`.

## PR #51 merge close-out (2026-09-26)

- PR #64 merged from `gpt/owner-bond-fallback-20260926` (`9acf0e9c`) as merge commit `dcf40b4c`. Kept its immediate-merge-only 10/10 capacity gate and advanced-group fallback. Excluded its removal of PR #58's `bond_negative_names`: default remains empty, dashboard `bond_banned` remains configurable, and normal, template-direct, and refresh-fallback picks all filter banned cards.
- PR #63 merged from `claude/pr51-merchant-surface-20260926` (`1fa2583b`) as `cb9c742c`; merchant transactions are not treated as ordinary HUD.
- PR #65 merged from `claude/pr51-blessing-priority-scope-20260926` (`0a0df021`) as `b9d45089`; blessing priority no longer blocks pickup/equipment/merchant handling while blessings remain incomplete.
- PR #62 was not merged: it duplicates #64's capacity work, and #64 is stricter because a full 10/10 bar accepts only a card that immediately completes a merge.
- Identity manifest is UTF-8 without BOM. `candidate_sha` is `b9d45089c07cc7cebf09a0994a003d860c512a9d`, the latest commit touching `src/shuabao`. Branch HEAD before this handoff update: `31511e0e43695872ca6c3c3610ecdaf0da79ffce`.
- Fast lane: bond/owner/policy group **112 passed, 11 subtests passed**; selected `choice_policy` groups **54 passed, 11 subtests passed**; black-market plus PR #63/#65 group **249 passed, 13 subtests passed**; `tests/contract` plus `tests/test_live_harness_refresh.py` **93 passed, 232 subtests passed**. No remaining fast-lane failures.
- One stale assertion expected an owned 2/4 bond to be selected with `free_slots=0`; it conflicted with #64's immediate-merge-only rule. Updated the expectation and reran that test: **1 passed**. A first combined exploratory run was interrupted while stalled and is not counted; the final split runs above completed.
- Mimo owns the remaining close-out: run the full release gate; if all other stages pass and the only asset delta is the expected 430→436 templates, update `docs/baselines/GATE_BASELINE.json` with the documented reason, commit it, and rerun for 4/4 PASS; switch the desktop test bench to `b9d45089c07cc7cebf09a0994a003d860c512a9d` and verify `ready_for_gt: true`; complete the five live re-checks below. No gate, bench switch, or game run was done here.

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
| PR #62 capacity proposal | cloud PR #62 | intentionally not merged; #64 duplicates it and enforces the stricter immediate-merge-only rule at 10/10 |
| Owner hand-cut series labels (海贼王, 海盗, 刀刀装备, 三国, 修仙, 魔法师/元素师/屠戮者) | branch `feat/owner-labels-20260926` (worktree `G:\刷刷宝\Worktrees\pick-speed2-20260926`), WIP 9b103ab1 + merge 54c69e80 | verify hit/false-hit on the 93 bond panels, then merge |
| Unified exclusive screen classifier | brief `scene_classifier.md` (Claude scratchpad), paused by Owner until one EX run passes | resume later |

### Four-red repair evidence (2026-09-26)

- Root cause: idle-HUD blessing-priority opening returned before emergency merchant arbitration and before the normal merchant step could skip. Emergency arbitration now runs first inside the existing closed-panel / positive-HUD / no-active-transaction gates; the blessing opener does not preempt a merchant step. Ordinary blessing selection priority is unchanged.
- Owner rules are unchanged: wood `<500` uses the normal merchant cycle; wood `>=500` does not visit unless no pill and bond occupancy `>=8`. Unknown occupancy never grants emergency authority. While the undead pack holds pills, missing pills do not trigger either normal or emergency pill trips; low wood still permits the normal wood visit. Only undead holds pill consumption.
- The obsolete label fixture now reads `config/fetter_labels.json`: `qiji.png` resolves to `奇技`; an unknown stem stays unchanged. An explicit unrelated advanced group isolates label normalization from default 大圣 pack expansion (the default group legitimately contains 奇技). Neither runtime policy nor label config is changed.
- Repaired tests command: `python -m pytest tests/test_choice_policy.py::TestAssemblePolicySettings::test_cards_resolve_through_fetter_labels tests/test_decision_reasons.py tests/test_solo_r2_issue2_merchant_bypass.py tests/test_urgent_merchant_20260924.py -q`, UTF-8 and OCR-prime off: exit `0`, **20 passed in 7.97s**. The three originally red merchant cases are `test_main_line_tick_detours_to_merchant_when_urgent`, `test_solo_cycle_skips_merchant_when_unneeded`, and `test_solo_skip_merchant_notes_decision_reasons`; the H-opening parametrized cases also pass.
- Related policy assembly command: `python -m pytest tests/test_choice_policy.py::TestAssemblePolicySettings -q`, same environment: exit `0`, **17 passed, 11 subtests passed in 3.26s**. An attempted full `test_choice_policy.py` plus the three merchant files stalled under the PTY runner and was stopped without a completed result; it is not counted as PASS. The parent still owns broader related tests / contract / identity harness.
- Focused Owner/devour command: `python -m pytest tests/test_owner_ingame_rules_lock_20260924.py tests/test_p0_devour_failclosed_20260917.py -q` with `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`, `SHUABAO_SKIP_OCR_PRIME=1`: exit `0`, **31 passed in 27.59s**. In particular `test_undead_pack_in_progress_does_not_visit_merchant_for_pill` preserves the hold boundary.
- Throwaway smoke command: `python _red4_smoke.py` with UTF-8, `PYTHONPATH=src`, subscription off: exit `0`. Production `_tick_main_line` reached emergency detour and dry-run `H` (`OpenBlackMerchantForDevourPill`), preserved interrupted skill, and sent no input/detour under an active transaction. Real recorded frame: `G:\刷刷宝\Worktrees\red4-20260926\tests\fixtures\solo_live_20260914\hud_wood_1111_f0200.png`. Signal reads were controlled; this is offline smoke, **not live-game proof**. The throwaway script is removed after verification. Game/KK was not started; live verification remains outstanding.

## Closing steps

1. Mimo runs `python tools/release_gate.py`. Expected asset baseline delta is 430→436 (+6 bond family templates, genji/shenfa recut); only if all other stages pass, update the baseline with the documented reason, commit it, and rerun for 4/4 PASS.
2. Mimo points the desktop test bench at the source candidate SHA above, checks `ready_for_gt: true`, and records the SHA and gate result in the PR #51 description.
3. Owner completes the five live re-checks below. No synthetic-frame result substitutes for live evidence.

## Owner live re-checks (morning)

1. Entry 12 solo with stage target 1-23: stage starts after the cut-off last row is clicked.
2. Bond panel: 祝福 taken first until 3/3, by series label without OCR delay; 成长/经济 next, then the current advanced deck.
3. Hero evolution two-card screen: picks the higher rarity (e.g. UR 小鱼), no freeze; if the hero screen never appears the run continues.
4. Opening four challenges: all four on within one step, wood challenge re-clicked if missed.
5. After 3 refreshes the bond panel takes one card (no unselected-deck starter, no overflow on a full bar); black market only when wood < 500 or no pill with 8 slots used, never for pills while 亡灵 is running.
