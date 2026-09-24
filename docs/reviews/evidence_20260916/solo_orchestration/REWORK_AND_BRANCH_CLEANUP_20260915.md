# 返工 + 分支收敛 · 交接提示词（2026-09-15 09:50）

> **同一时间只允许一个 agent 在 `G:\刷刷宝\Worktrees\live-solo-cc17962` 里改代码、提交。** 09:44 还有 agent 往里提交（ab84752），接手前先确认那个 agent 已经停下。

## 现状（09:50 核实）

- **唯一主工作线**：`G:\刷刷宝\Worktrees\live-solo-cc17962`，分支 `fix/solo-start-from-kk-20260914`，HEAD **ab84752**，工作树干净。
- **桌面 Live lnk** 的 `-ProductionSourceSha` 还是 **a00ccdd**，和 HEAD 不一致，所以身份检查现在是 **READY FOR GT: NO**，要先重定。
- **Live 线已经合进来的**：
  - Claude 编排线：7b17bfc 及以前的提交；
  - 执行 agent Round2：a17ad19（B1/B2/B3/B4/B6/B9）；
  - 测试壳异步写帧：d2be13b；
  - 单人黑商恢复：6af62ec；
  - 看板补提速/体术：1880e4d；
  - 羁绊刷新上限：3623c7f；
  - 拾取加"背包有空格"判断：ab84752。
- **还没进 Live 的**：
  1. `stash@{0}`（live-solo 工作树里；另有同内容的补丁文件 `rework_ex_fastpath_caps.patch`，在本目录）。内容三项：
     - 宝物 EX 出现就拿、不看品质（Owner 已拍板，对应 2593dd6）；
     - 置信度 ≥0.95 的单帧直点，同屏同名的羁绊（祝福(0/3)×3）也算；
     - 按类型区分的连拿上限：F 3 次（开局 1 分钟 6 次）、G 5 次、其它 3 次，外加 30 s 上限。
  2. 执行 agent 的 ae8a375（只改测试：conftest 虚拟环境回退和环境隔离）。
- ⚠ **Live HEAD 上本来就有 1 条失败测试**：`tests/test_solo_b2_pickup_speed_20260915.py::test_refresh_action_still_waits_two_frames_even_when_confident`。原因是 3623c7f 让"读不到木头时刷新改为隐藏"，而测试里读不到木头。

## 提示词 A：返工（给接手 live-solo 的 agent）

```
你接手刷刷宝单人主工作线 G:\刷刷宝\Worktrees\live-solo-cc17962（分支 fix/solo-start-from-kk-20260914）。先确认没有别的 agent 在这个工作树里提交（git log -3 看时间、git status 要干净）。
纪律：
- 不在 main 上提交，只用 merge commit，不许 rebase 或 squash；
- 改了 src/ 就要重定身份基线：tools/live_harness_identity.py 的 HARNESS_BASE_SHA/FROZEN，以及 tests/test_live_harness_refresh.py 的 FROZEN/BASE，都改成最后一个改 src 的提交；
- 桌面「刷刷宝 Live 实机测试.lnk」的 -ProductionSourceSha 必须等于 HEAD，并且 `python tools/live_scenario_capture.py identity --production-source-root <树> --production-source-sha <HEAD>` 必须是 READY FOR GT: YES；
- 不许动门禁基线，不许打外发包；
- Python 用 G:\刷刷宝\GameScript-Local\.venv\Scripts\python.exe，环境变量 SHUABAO_OCR_PYTHON=G:\刷刷宝\GameScript-Local\.venv-ocr\Scripts\python.exe、SHUABAO_OCR_MODEL_DIR=G:\刷刷宝\GameScript-Local\models\ocr、PYTHONUTF8=1。

按顺序做，每步单独提交：
1. 执行 `git merge ae8a375`（merge commit，只改测试）。
2. 执行 `git stash apply stash@{0}`（说明是 "claude 09-15: EX must-take + >=0.95 same-family fast path + per-kind visit caps"）。如果 stash 不在了，就用 G:\刷刷宝\handoff_prompts\solo_orchestration_20260915\rework_ex_fastpath_caps.patch 执行 git apply。然后把下面 5 条测试对齐新规则（都是测试写法问题，不改生产逻辑）：
   a. tests/test_solo_b2_pickup_speed_20260915.py::test_refresh_action_still_waits_two_frames_even_when_confident：给 _bond_refresh_affordable 打桩返回 (True, 1000, 40)，保留"刷新要两帧确认"的原意。这条在 ab84752 上本来就失败。
   b. 同文件 test_offline_tick_count_for_one_card_pick_drops_by_one_ocr_confirm_tick：在"改前基线"那段额外打桩 patch.object(Mediator, "_SINGLE_FRAME_PICK_CONFIDENCE", 1.01)。
   c. tests/test_solo_l1_starvation_20260915.py 里 test_bond_visit_advances_after_three_confirmed_picks 和 test_open_bond_panel_closes_and_advances_at_pick_cap：两条都补一行 med._round_started_at = 0.0。原因是测试把时钟打桩成 110，开局时间却用了真实时钟，算成开局第 0 秒，误用了开局 1 分钟 6 张的上限。
   d. tests/test_live_run_205044_regressions.py::test_owned_bond_select_still_waits_for_second_frame_on_duplicate_slot_names：改名为 test_same_family_duplicate_titles_do_not_need_a_second_frame，断言第一次调用就返回命中。
   跑 tests/test_solo_*.py、tests/test_choice_policy.py、tests/unit/、tests/test_live_run_205044_regressions.py、tests/test_panel_liveness_harness.py、tests/test_l1_cycle_recheck_merchant.py、tests/test_p1b0_post_game.py，必须全绿，然后提交。
3. 游戏关着时跑全量 pytest，允许的失败只有设了 SHUABAO_OCR_MODEL_DIR 时的 test_ocr_production_bundle。然后重定身份基线、切 lnk、确认 READY，再通知 Owner 开测（菜单 12）。
4. 实机验收标准：G:\刷刷宝\handoff_prompts\solo_orchestration_20260915\HANDOFF_SOLO_ORCHESTRATION_20260915.md 第 5 节 A1–A10。另外核对一件事：没完成经济之前，贪婪和挑战会不会出现在羁绊面板里。如果不会，把 choice_policy.py 的 _ECONOMY_BOND_ORDER 改成 经济 → 祝福 → 贪婪 → 挑战 → 成长。
5. 剩余 P1，每项单独提交并回报：
   - 技能路线：先出方案给 Owner，**不许直接改看板默认值**。Owner 当前 skills=asj/asjg/assx/jq，路线 asj:damage、asjg:flood、assx:damage、jq:ice、tl:paralysis。KB 判定 asj/assx 的 damage 路线已作废、jq 碎冰需要冰霜新星、普攻被禁后 asj 急速流不可达。依据 config/skill_routes.json、skill_card_catalog.json、skill_card_knowledge.json、KB 报告第 4 节和实机技能面板截图来定方案。
   - 主线停滞转向：复用 B3 的任务栏 OCR。同一个"主线X-Y"停超过 90–120 s，或出现"主线挑战失败"时，技能积压门槛降到 1，羁绊只拿战力类。
   - 稀有度改读卡面上的 N/R/SR/SSR 字母。
6. P2：补标题模板（封神、刀刀、修仙、异火、亡灵、藏宝图、肉身成圣、贪婪）；ui-v2 的 skill_archive_levels；看板黑商开关（B7，等 Owner 定）。
每步回报：提交 SHA、改了什么、测试名、改前改后的证据。
```

## 提示词 B：分支收敛与清理（等提示词 A 做完、实机验收通过后再做）

```
目标：把单人线收敛到 main，并清理过期的工作树。全程只用 merge commit，不许 rebase/squash/force push，不许在 main 上直接提交。

1. 盘点：
   - 在 G:\刷刷宝\GameScript-Local 执行 git fetch、git worktree list、gh pr list --state open；
   - 对每个工作树的分支执行 git log --oneline origin/main..<branch> | wc -l，列出"领先 main 的提交数、是否已包含在 fix/solo-start-from-kk-20260914 里、最后提交时间"。
2. 已被主工作线吸收、可以归档的线：
   - feat/solo-orchestration-20260915（Worktrees\solo-orchestration-20260915）：内容已通过 8e8691d 和提示词 A 的第 2 步进入主线。它自己的 0970ddb 冲突解法不要整支合并，否则会和主线重复冲突。
   - fix/solo-round1-20260914（Worktrees\solo-fixes-20260914）：a17ad19 已合，ae8a375 由提示词 A 第 1 步合入。
   对这两条：先确认 `git log <主线>..<branch> --no-merges` 里没有未吸收的生产改动（有的话列出来问 Owner）；再打归档标签 `git tag archive/<branch>-20260915 <branch>`；然后 `git worktree remove`，工作树不干净就停下来问。先不删分支。
3. 推送主工作线：`git push -u origin fix/solo-start-from-kk-20260914`，然后 `gh pr create --base main`。PR 描述写清：单人编排升级、执行 agent Round2、实机验收结果（A1–A10）、已知阈值未经 A/B 校准、门禁 scene_templates 快照 399→401 是有意新增的 2 个标题模板。
   合并前检查还开着的 PR（包括之前的 #22/#23，以及 fix/hitch-postgame-latency-20260914）和本 PR 的先后依赖。有冲突就在本分支用 merge commit 解，不改门禁基线。CI 用一次性后台等待，绿了用 `gh pr merge --merge` 合并，红了先区分环境问题还是本次引入的。
4. main 合并后：本地 G 根按 AGENTS.md 与 origin/main 对齐（只 ff），Live lnk 是否切到 main 由 Owner 决定。
5. 其它工作树只列清单，不删：boss-policy-layering-20260913、dev-backup-receipt-20260914(-sparse)、fix-summary-escape-20260913、live-g0-publicbag-v2、live-harness-input-evidence-20260914、live-harness-refresh-20260908、live-test-boss-05ed271、lobby-hitch-surface-test、night-ablation-20260907、review-package-20260913、stability-s0-20260908、subscription-lobby-pilot-20260831、C:\Users\10639\.codex\worktrees\*、GameScript-Local\build\tls_release_d11ac00。每个标注"已并入 main / 有未合提交 N 个 / 建议归档或保留"，交 Owner 决定。stash@{1}（release-signing）不要动。
```
