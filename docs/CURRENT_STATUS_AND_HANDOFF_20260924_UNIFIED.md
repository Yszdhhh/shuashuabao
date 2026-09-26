# 统一版本交接（2026-09-24）


## Owner 2026-09-26 调度口径更正

Owner 2026-09-26 更正版：木材持续溢出（≥500）时专心推羁绊并快速合成 EX，不去黑商；木材未溢出（<500）时黑商按现有购买逻辑正常推进。缺吞噬丹且羁绊栏占格≥8 时保留应急插队。羁绊刷新每面板最多 3 次；刷新用尽或木材不足时优先拿白名单候选（祝福 > 成长/经济 > 当前高级组 > 其它白名单），没有白名单候选才按稀有度兜底；显式负面名单仍禁止，全部候选被禁时 fail-closed。技能/宝物面板不使用羁绊兜底。祝福不依赖看板勾选且每局必拿。暂时隐藏仅用于调度器让路处理地面、背包或其它面板；无可读目标时保留面板并零输入等待。

默认高级卡组选序：海盗 → 大圣 → 刀刀 → 异火 → 海贼王 → 封神 → 修仙；亡灵仍为实验项且不默认勾选。低木材且技能积压时先点技能规则保持不变。KB 已确认海贼王终卡为 EX、不可吞噬；但 `_BOND_BAR_EX_TEMPLATES` 无海贼王 EX 模板，当前高级组解锁计数依赖羁绊栏模板命中，海贼王成型后可能无法解锁下一组。按 Owner 本轮要求只记录风险，待真机素材齐备后另议模板。发布门禁通过后仍需真机验证刷新用尽/木材不足兜底、显式负面卡 fail-closed、祝福强制必拿及高级组解锁。

## 组成

`claude/project-thread-fqyf7h` 分支上的统一版本，由三部分组成：

1. PR #37（`fix/desktop-sync-20260923`，头 `1b0a1a8`）。它已经包含 PR #36 的前 125 个提交（两者分叉点是 `94f5023`）。
2. PR #36 在 `94f5023` 之后的独有提交：
   - 直接叠上：`985d350` `d5d7107` `5fcb253` `661773a` `c3f42f5` `e5838f5` `6b9bf9e`。
   - 已在 #37 里，跳过：`7f847c2` `3ecd095` `6717cad`。
   - `3f4f9af`：取 #37 这一侧解冲突后没有剩余改动，说明它的内容已被 #37 的 `8a0f02e` 和 `f082f0a` 覆盖，因此跳过。
   - `533e7b5`（UI-24 看板）：在 `ui-v2/index.html` 上有 3 处冲突。日志条保留 #37 的高度过渡动画；龙珠图标和负面宝物手风琴采用 UI-24 的写法。
3. `fix/launch-summary-escape-20260913` 的两个 XSS 转义提交：`9f60c97` 和 `4519970`。

所有原始提交都保留，合并时用 merge commit，可以二分定位。

## 未完成，需要在本机做

- `python tools/release_gate.py`：云端 Linux 缺 Qt 和 OCR venv，只能跑部分 pytest，不能算门禁 PASS。确认 failed=0 后，再用 `--update-baseline --reason` 更新 pytest 计数。
- 身份锚点：`config/runtime_identity_manifest.json` 仍指向 `94f5023` 一系的候选。合入 main 后，需要补一个锚点提交，指向合入后的 HEAD。
- `build_release.ps1` + `release_harness.py`，并核对桌面 `build_identity.json` 的 `source_sha`（AGENTS.md §6）。
- 需要重新真机验证：蹭车→考古交接和局数计数（`f082f0a`）、Boss 点击后确认、宝物负面默认不拿、#37 的满槽顶替和 F1 兜底、银月之晶、UI-24 看板（含上面 3 处冲突的取舍）、启动摘要转义。

## Owner 2026-09-24 决策修正（7 个提交，叠在本统一分支之上）

Owner 2026-09-24 三条决策加审查发现的问题，按层分成 7 个提交，都未经真机验证：

- 感知：技能面板改点真正的【刷新(N)】按钮（通用 `refresh`）。`skill_refresh_btn` 是「技能免费刷新次数+1」文字截图，命中点压在【放弃】上沿。bond/treasure 恢复"专用钮优先"的顺序查找（`1b0a1a8` 曾改成全面板取最高分）。契约 `test_skill_refresh_btn_priority_contract.py`、冻结回放 `giveup_panel_not_fail` 的期望已按真帧改正。`select_hero.png` 已登记进运行资产清单。
- L1 调度：木材 < 500 且有技能积压时先点技能；木材 ≥ 1000，或基础羁绊未成型且木材 ≥ 500 时先点羁绊。500 是 Owner 给的初值，要在实机上调。木材低时宝物恢复在自己那一步打开。`RuntimeMediator._bond_presets_complete` 恒为 False，拿齐预设后不再整局跳过或关闭 F。
- L1 选卡：本页出现还没拿到的预设基础羁绊时，先拿基础羁绊，排在"差一张合成"之后；已经起步的高级卡组（持有同组卡）不受影响。80% 基础完成比例未改，待实机调。
- L1 英雄焦点：看板丢失时按 F1。【▲选择英雄】提示改到面板已关、局内 HUD、提权和 dry_run 这几道门禁之后才处理。
- 恢复与战后：画面飞走按 F2（游戏内「返回阵地」），局内和战后通用（Owner 09-24：自己英雄打怪/Boss、存档挑战/传家宝所在的广场就是常规战斗主画面）。证据是小地图上的白色视野框：本局从 3 个稳定帧（跨 ≥3s）学到阵地位置，视野框偏离阵地 >0.12（小地图尺度）且两个不同帧间隔 ≥2s 才按；只在面板会话之间按，每 8s 最多一次，回到阵地前最多 3 次。大秘境确认后重新学阵地；挑战路线进行中、传家宝/秘境等待、团本、背包打开时不判。实现 `_maybe_recover_battle_view`，取代原来只看战后页面的 `_maybe_recover_post_game_view`。
- L1 满槽顶替：OCR 改用真实接口 `shadow_predict`（原来调用的 `predict_sync` 不存在）。只点 OCR 认出、且不是目标合成卡组也不是刚拿的同名卡的槽位，认不出就零输入。
- L0 蹭车：QUIT 落到房主选难度页时，只要处于蹭车模式就发一次语义 Esc。

云端门禁（Linux）：冻结回放 PASS（6 PASS、1 BLOCKED 断线素材），contract 67 PASS。scene_templates 只剩资产数量 404→405 与快照不一致，这是有意新增的 `select_hero.png`。pytest 有 8 个桌面/发布模块因缺 Qt/EGL 无法收集。快照没有在云端刷新（刷新必须跑全阶段，云端 pytest 不完整），需要在本机跑 `python tools/release_gate.py --update-baseline --reason "select_hero.png 资产 + 技能刷新真按钮期望纠正"`。

需要真机验证：木材 20~1000 区间技能/宝物是否还会被饿死；基础羁绊优先后高级卡组的成型时间；【▲选择英雄】的触发场景；战后 F2 的触发与回广场效果；满槽顶替 OCR 在卡槽栏上能否读出卡名（读不出就不会顶替）；蹭车选难度页 Esc 后能否回到房间。
后续回归修复（叠在上面 5 个提交）：
- L1：必拿/白名单的低置信读数恢复第二帧确认，只有"差一张合成""已持有合成"和单槽无歧义高置信才免确认（`test_solo_planner` 首帧、`test_solo_b2_pickup_speed`、`test_live_run_205044` 二帧）。
- L1：进化金条改为要求一整块金色连通区域，散落的金色噪点不再触发 ClickEvolve（`test_s0_safety_state_machine` 面板可见性）。
- L0：KK 平台弹窗恢复先 Esc、fresh 帧复核仍在再点叉（Owner 09-24：活动弹窗 Esc 关不掉就点叉）。`e0ad7f6` 曾改成先点叉，`test_b15da05_real_regressions` 5 条、`test_live_scenario_capture` 2 条转绿；`test_hitch_l0_and_hud_fixes` 里 e0ad7f6 的用例同步改成 Esc→X 两步。
- 测试同步：默认必拿「祝福」与满槽核心卡的策略期望（`test_solo_gt_regression`、`test_policy_near_complete`）；`test_external_review_regressions` 的全局 find mock 排除【▲选择英雄】（Windows 提权环境下才触发）。

卡族 `dashengzailin`（大圣再临）、`haizeiwang`（海贼王）已登记为 `templates_index.json` 的 `pending_live_capture`：当前只走 OCR 标题识别，下次实机在羁绊选卡面板截卡顶卡族标题补图，补图后移入 `shortcodes`。`test_solo_main_line_close_task` 5 条在 main 上同样失败（云端缺 `.venv-ocr`），属环境问题。身份锚点已在云端改指 `4e0b917`（最后一个改动 `src/shuabao` 的提交，09-24 本地门禁复查时的 OCR 读线程修复），`test_live_harness_refresh` 全过；之后 `src/shuabao` 再有提交要重新锚定。

需要真机验证（新增）：F2 的触发时机和回阵地效果（尤其大秘境、传家宝 Boss 前后）；平台活动弹窗 Esc 后点叉。

入口 12 的 `solo_ingame_chain` 收尾现已由 observer 的整链路结果决定：普通动作 post-confirm 不再直接记为 target PASS；`auto_secret_realm=true` 时要求确认进入秘境，并观察秘境结束后回到选关页或战后页。此链路需要 Owner 在真机重新验证秘境胜利、失败/超时后的收尾表现。

## 本地门禁单次失败的处理（2026-09-24 晚）

本地首跑 `release_gate.py` 的 pytest 阶段 2679 passed / 1 failed，重跑 2680 全过，失败用例名没有留下（门禁只保留输出最后 3 行）。云端判断与处理，三个提交，未改业务逻辑：

- `263cb59` 门禁：pytest/contract 加 `-rfE`，汇总逐条打印失败用例 node ID（`--json` 里是 `failed_nodes`），完整输出存 `logs/release_gate_<阶段>_<时间>.log`；pytest 或 contract 红着时 `--update-baseline` 直接拒绝（退出 1）。
- `4e0b917` 感知：OCR worker 被 `_terminate` 关管道时，stdout/stderr 读线程抛 `ValueError`，就是重跑里 `test_corrupt_model_is_unavailable` 那 2 条线程告警。现在读线程安静退出。
- `4a15327` 测试：本机有 OCR 运行时时，pytest 会话开始先起一次真实 OCR worker 预热（`SHUABAO_SKIP_OCR_PRIME=1` 可关）。

失败原因是推断，未证实：只在首跑出现、重跑不复现，最可能是 OCR 冷启动第一次推理超过单请求 1.5s 预算，worker 被杀，某条读真帧的 OCR 断言拿到空结果。这类用例只在本机有 OCR 运行时时才真跑，云端复现不了。本轮改动没有碰 OCR 推理路径（`ocr_shadow` 除 `659ab71` 资产外未改），所以判为环境性的首跑失败，不是本轮回归。门禁现在会打印 node ID，下次再出现就能直接定位。

第二次本地续跑定位到失败用例是 `tests/test_windows_launcher_smoke.py::test_windows_launcher_shortcut_vbs_ps1_current_and_rollback`：门禁里失败，单独跑 3/3 通过。它自 09-11 未改、与 main 一致。每一步都冷启动 powershell/wscript 或首跑刚编译的未签名 PE，全量负载下超出原来 8/12/15/20s 上限；`dd7d91b` 把成功路径上限放宽到 45–60s（完成即返回），失败信息带 rc 和耗时。仍是推断，需本地门禁复核。

PR #40（本地门禁记录，只改本文件末尾）内容与本地报告一致，可以合进 fqyf7h；本节插在前面以免与它冲突。

## Owner 局内规则锁（2026-09-24）

Owner 指出以前写好的局内规则在多轮架构收敛里被删掉。下表是逐条核对统一分支的结果。每条规则都有一个行为测试锁住；`tests/test_owner_ingame_rules_lock_20260924.py` 里的登记表 `OWNER_RULES` 指向这些测试，删掉或改名任何一条都会让登记检查变红。改动或废止规则时，必须同时改登记表，并写明 Owner 原话的日期。

| # | 规则 | 来源 | 统一分支状态 |
|---|---|---|---|
| 1 | 用英雄卡前先把「点击进化」用完：金条亮着、或进化还在等反馈/选英雄时，物品栏一格都不点 | B8-3 2026-08-10；Owner 09-24 重申 | **丢失后补回**。09-23 加的 2–6 格逐格左键没有看进化状态，真机帧 f0581（金条亮、五格满）上会先点物品栏 |
| 2 | 英雄卡模板路径要求进化已确认 | B8-3 | 生效 |
| 3 | 看板丢失两帧确认后按 F1，不按 F2 | Owner 09-24（纠正 09-15 的 F2） | 09-24 补回 |
| 4 | 战斗主画面（打怪/Boss、存档/传家宝广场）飞走，按 F2 返回阵地 | Owner 09-24 | 09-24 新增（小地图视野框） |
| 5 | 木材 < 500 且技能积压：先点技能 | Owner 09-15，09-24 定 500 | 09-24 补回（#37 删过） |
| 6 | 木材 ≥ 500 且基础羁绊未成型：先点羁绊 | Owner 09-20 优先羁绊，09-24 | 生效 |
| 7 | 木材 ≥ 1000：羁绊压过技能积压 | Owner 09-15 | 生效 |
| 8 | 勾选的基础羁绊与高级羁绊同页：仅祝福优先于高级卡，高级卡与其余基础卡平级 | Owner 2026-09-25（修订 09-24 全基础优先） | 09-25 改写；同页只有祝福优先于高级卡，高级卡与其余基础卡平级 |
| 9 | 宝物在自己那一步能打开，不被 F 饿死 | Owner 09-15 | 09-24 补回（#37 删过） |
| 10 | 拿齐预设后 F 整局不关（重复卡升级/合成） | 09-24 审查恢复 | 09-24 补回（#37 改过） |
| 11 | 技能面板点真正的【刷新(N)】，不点「刷新次数+1」文字 | Owner 09-24 | 生效 |
| 12 | 满槽顶替只点 OCR 认出的非目标卡，认不出零输入 | AGENTS §5 | 09-24 补回（#37 曾随机点） |
| 13 | 负面宝物默认不拿，OCR 读不到描述也拦 | Owner 09-22 | 生效；09-24 按研究补入生命献祭（无实机帧，单列） |
| 14 | EX 宝物出现就拿，不受品质采样约束 | Owner 09-15 | 生效 |
| 15 | 高级卡组不设硬门槛：不等基础 80%、不等开局 480s | Owner 09-23（EX 直通组），09-24 扩到全部 | 09-24 晚改（topic 分支） |
| 16 | 单人物品栏满时 2–6 格左键试用（进化不可用时） | Owner 09-23 | 生效（受第 1 条约束） |
| 17 | 蹭车不动物品栏（队伍资产） | Owner 09-23 | 生效 |
| 18 | 打不过自动降级 | Owner 09-15 | 生效 |
| 19 | KK 平台弹窗先 Esc，关不掉再点叉 | Owner 09-24 | 09-24 补回（e0ad7f6 改过） |
| 20 | 基础羁绊同页顺序：祝福 → 成长 → 经济 → 挑战 → 力量线 → 智力线 → 敏捷线 → 其他基础卡（贪婪归其他）；只排勾选的 | Owner 09-24（取代 09-15 经济在前） | 09-24 晚新增（topic 分支） |
| 21 | 同一时刻只推进一组高级卡组，羁绊栏出现蓝色 EX（海盗为 UR）才解锁下一组 | Owner 09-24 | 同上；EX 模板待实机截图 |
| 22 | EX 靠合成链得到，不从面板拿 | Owner 09-24 | 同上 |
| 23 | 刀刀/修仙/海盗/亡灵按看板勾选从首卡拿到白名单末卡 | Owner 09-24 | 同上 |
| 24 | 单人默认吃吞噬丹（看板不加开关），羁绊栏空位 ≤ 2（≥8/10）就吃（亡灵例外见下） | Owner 09-24；Owner 09-25 改为 ≥8/10 | 09-25 更新 |
| 25 | 羁绊栏空位 ≤ 2 没丹、木材 < 500：插队去黑商，绕一趟回到被打断的步骤 | Owner 09-24；Owner 09-25 | 09-25 更新 |
| 26 | 黑商一步按 H 开店：羁绊栏空位 ≤ 2 找吞噬丹，木材 < 500 买木材 | Owner 09-24；Owner 09-25 | 09-25 更新 |
| 27 | 亡灵卡组进行中（持有亡灵卡、兵主 EX 未出）不吃吞噬丹：提前吞倒计时卡会断碎片 | Owner 09-24 | 同上 |
| 28 | 木材 < 500 以支线循环为主：F 每次最多 1 张（500–1000 两张，≥1000 十五张） | Owner 09-24 | 同上（原 300 分档） |

以上是离线结论，全部要在下一次实机短测里按表核对（见 `docs/handoff_20260924/LOCAL_QUICK_TEST_PROMPT_20260924.md`）。

## 上线主线与卡组拿取现状（2026-09-24）

Owner 09-24 定的优先级：先用"模板匹配 + 简单阈值"把现有逻辑跑通上线。主线有四块：大调度逻辑跑通、各系列卡组拿取跑通、长时间运行兜底、UI 看板功能接入与逻辑梳理。动态软阈值等科学调度放到上线后。数据采集只在本地测试时顺带做。本地看板已收敛为正式版、快速测试、UI 测试三个。

卡组拿取的逐系列核对见 `docs/handoff_20260924/CARD_FAMILY_PICKUP_AUDIT_20260924.md`（离线结论，未改代码）。要点：
- 三条属性线和大圣、异火、封神有端到端锁定测试。刀刀、修仙、海盗、亡灵 09-24 补了 `tests/test_slow_pack_pickup_lock_20260924.py`（按看板 `ADV_PACK_CARDS` 勾选 + 真实 config，锁当前行为）：未达基础 80% 且未到 480s 不拿；解锁后从首卡拿到白名单末卡；同页缺基础羁绊时先拿基础；EX 终卡不拿（待 Owner 定，定了改测试）。还没登记进 Owner 规则锁表（登记表不得删改，要 Owner 点头）。
- 新发现（离线）：`choice_lexicon` 把修仙萌新、修仙大成归一成「修仙」，持有修仙后这两张走"已持有合成"，压过同页缺的基础羁绊；同时它们在换组计数里和修仙算同一张。卡顶标题实机确认后再判断对不对。
- 海盗的藏宝图（开池卡）不在白名单里，推断勾选海盗后可能开不了池，需实机确认卡顶标题。
- 慢卡组的 EX 终卡不拿、直通组的终卡拿，两边口径不一致，待 Owner 定。
- 多选慢卡组时第二组可能永远不启动。
- 海贼王没有拿取路径。

## 分支收敛

远端分支清单和删除建议见项目文件 `branch_convergence/分支收敛方案_20260924.md`。统一版本合入后，#36、#37 关闭，被吸收的分支按清单删除。

## 本地 quick-test 记录（2026-09-24）

本机默认工作根 `G:\刷刷宝\GameScript-Local`；分支 `local/quicktest-20260924`，源码 HEAD `bef1d3cb27b9e5fb05fc3baf2fda8fc24e471494`。`8a0266d` 是 HEAD 祖先，`config/choice_lexicon.json` 存在且工作树与统一分支版本一致。

门禁命令 `python tools/release_gate.py` 退出码 1：
- `pytest`：FAIL，2679 passed、1 failed、2 xfailed、2 skipped。门禁汇总未保留失败 node ID；本机 `.pytest_cache/v/cache/lastfailed` 在诊断前含有 34 条历史记录，不能据此确认本次用例名。
- `frozen_replay`：PASS；6 个场景 PASS，`disconnect_modal_missing` 为 BLOCKED。`giveup_panel_not_fail` 实际 PASS。
- `scene_templates`：FAIL；模板 ok=148、missing=0；资产文件与 allowlist 均为 405，对比快照 404。此为预期的 `select_hero.png` 资产差异。
- `contract`：PASS，67 passed。

为取得 pytest 失败详情，重跑同一子命令 `python -m pytest tests -q --tb=short -p no:faulthandler`，退出码 0：2680 passed、2 skipped、2 xfailed、389 subtests；有 2 条 `test_ocr_shadow.py::TestClientLifecycle::test_corrupt_model_is_unavailable` 的 `PytestUnhandledThreadExceptionWarning`（stderr reader 在线程读已关闭文件时抛出 `ValueError`）。重跑未复现门禁的 1 个失败，因此该失败的具体 node ID 仍未知。

由于首次门禁除预期资产计数差异外还有 pytest 失败，本轮没有运行 `--update-baseline`、身份锚点刷新、第二次门禁、`build_release.ps1`、发布 harness 或真实游戏入口。门禁结果仍记 FAIL；没有构建产物 hash / `build_identity.json`，没有局内 trace/capture bundle。Owner 规则 1–19 本轮全部 `NOT_OBSERVED`（未启动实机入口，无对应 trace 行号/截图）；大圣再临与海贼王标题截图也未产生。

用户指定的桌面快捷方式 `C:\Users\10639\Desktop\刷刷宝 实机测试台.lnk` 当前指向 `G:\刷刷宝\Worktrees\desktop-sync-20260923\live_scenario_launcher.ps1`，固定 `-ProductionSourceSha 1b0a1a86b76db73bd91d7963743ec4cad998891c`。快捷方式未改动。本轮结果与 pytest 诊断日志已放入测试台使用的 capture root：`G:\刷刷宝\captures\local_quicktest_20260924_20260924_185305\REPORT.md`；日志同目录 `pytest_detail.log`。

本轮现场保全：起始分支 `fix/hitch-goal-archaeology-20260920` / `94f502335dd3575926fc78e853f992edbb401fab` 的未提交内容已原样提交到 `wip/local-dirty-20260924` / `71888d8bbdf3eb9d57b89fc8478d8ea025fefabe`。B 类研究差异和 A–F 分类详见 `G:\刷刷宝\handoff_prompts\backup_20260924_20260924_175833\classification.txt`。

下次恢复本地实测前，先解决/复现首次 pytest 的单次失败并使完整 release gate 退出码为 0，再运行发布构建与双次冻结包 harness；确认测试台快捷方式应改指向的源码 SHA 后再从入口 12 跑两局。

## Owner 2026-09-24 晚：拿卡顺序与紧急资源（已并入 fqyf7h）

分支 `claude/brave-tesla-qt93nd`，从 fqyf7h `66bde83` 开出，按层提交，都没有实机证据：

- L1 选卡 `bd04a2d`：基础羁绊顺序改为 祝福 → 成长 → 经济 → 挑战 → 力量线 → 智力线 → 敏捷线 → 其他基础卡（贪婪在其他里最前），只排看板勾选的；这个顺序只决定同页多张时先拿哪张，单张出现按预设照拿。取消高级卡组的"基础 80% / 480s"拿卡门槛（`base_completion_ratio`、`advanced_unlock_s` 只剩调度用：木材 ≥500 且基础未成型时 F 优先）。所有高级卡组（含大圣/异火/封神）同一时刻只推进一组，`PanelCandidates.completed_advanced_groups`（羁绊栏 EX 数）决定当前组。同页有还没拿到的勾选基础羁绊时先拿基础，高级卡组起步后也一样，只让位于"差一张合成"。
- 感知 `718366f`：`_bond_bar_ex_count` 在羁绊栏 10 格里匹配 `assets/Images/bond_bar/ex_card.png`（海盗 UR：`ur_card_haidao.png`）。**模板还没有**，缺模板时返回 None，调度停在第一组、不会换组。
- L1 调度：单人默认吃吞噬丹，不再看 `auto_devour_dan`，羁绊栏 ≥6/10 就吃（Owner：吞噬只提前腾格子，不影响合成进度）。羁绊栏过半且物品栏没丹、或木材 < 500 时，从当前步骤绕到黑商一步（冷却 45s），黑商一步结束回到被打断的步骤；黑商不在场时按 H 开店（找丹或买木材）。本局 EX 数每 3s 随木材一起读，只增不减。
- 规则锁表新增 20–26，改写 8、15（Owner 09-24 允许修改登记表）。
- L1 调度 `5a23ce4`：亡灵卡组进行中（持有亡灵卡、羁绊栏还没出现它的 EX）不吃吞噬丹、不为买丹去黑商（Owner：吞噬只腾格子不影响进度，唯一例外是提前吞掉亡灵倒计时卡会断碎片、兵主合成不了）；F 每次拿卡上限的木材分档 300 → 500，与"木材 < 500 支线为主"统一。
- 规则锁新增 27、28。身份锚点最终改指 `5a23ce4`（这批最后一个改动 `src/shuabao` 的提交）。
- 流程 `361c1f8`：AGENTS.md §1.1 纯资料提交（只改 `docs/`、`fixtures/live_captures/`）不跑门禁，只跑 `tools/check_material_commit.py`。
- 单人调度链路梳理成一页：`docs/handoff_20260924/SOLO_SCHEDULING_CHAIN_20260924.md`（每 tick 的优先级梯子、F 面板拿卡顺序、木材三档、trace 关键字）。下一轮本地提示词：`docs/handoff_20260924/LOCAL_ROUND4_PROMPT_20260924.md`。本分支并入 fqyf7h 用 merge commit 保留原 SHA；并入后 `src/shuabao` 再有提交就要重钉。
- 云端验证（Linux，不算门禁）：冻结回放 6 PASS / 1 BLOCKED（断线素材，同前）；contract 67 PASS；全量 pytest 与本分支起点对比没有新增失败（剩余失败都是缺 OCR/Qt 的环境类，同基线）。

需要实机验证：同页基础优先后高级卡组成型时间；木材 < 500 时去黑商的频率是否挤占技能/宝物；吞噬丹 6/10 就吃之后羁绊栏占用曲线；H 开店后能否识别出吞噬丹和木材礼包并买到。

EX 模板（`a57d697`）：从 Owner 的卡面截图 `fixtures/ex_finals_20260814` 切了 11 张（10 张 EX + 海盗 UR），放 `assets/Images/bond_bar/`，已登记运行资产清单（405→416）。羁绊栏卡图上半截叠着卡组名，模板只取下半截画面缩到 50px 格；243 张真机帧上非 EX 卡最高 0.64，阈值 0.80。**还没在羁绊栏实拍的 EX 上验证过**：认不出时停在当前卡组不换组。下一轮本地门禁的资产数会从 405 变 416，门禁绿后用 `--update-baseline --reason "EX 卡羁绊栏模板 11 张"` 刷新。身份锚点随之改指 `a57d697`。

需要实机素材：羁绊栏里真实出现的 EX 卡（整屏帧 + 悬停详情），用来校准上面的模板；吞噬丹完整一次事务（点丹前后、是否弹出选目标界面、哪张消失），见 GPT 调研 PR #42 的 P0 清单。

还没做：物品栏满时的消耗品识别与溢出整理、单人背包放置逻辑，等 GPT 调研（`gpt/urgent-resources-20260924`）和实机 tooltip 截图。

本地第三轮（`local/quicktest-20260924b`，HEAD `88eb4d2`）：门禁首跑启动器冒烟测试临时 EXE `PermissionError`，单跑 3/3 过，重跑全绿；快照已刷新（404→405）。`build_release.ps1 -NoDeploy` 因缺操作员 Ed25519 manifest 私钥 BLOCKED（第 113–121 行，所有冻结渠道都要，设计如此），冻结包 harness 未跑。云端决定继续用源码模式跑入口 1 和入口 12。

## 2026-09-26 L1 选卡模板直判接线（worktree `perf/pick-speed-20260925`）

- 在羁绊固定 3/4 槽面板先匹配卡族标题；只有槽数有效、索引完整且唯一、所有槽位都有名称且模板分数均 ≥0.85 时才用模板结果。模板不完整或低分时保持原 OCR 回退。
- `choice_policy` 的排序、规则锁与输入执行路径未改；完整高置信直判沿用其策略结果，并跳过 OCR 等待和第二帧确认。冷却及面板 FSM 未调整。
- 两包真实帧共 93 个羁绊 OCR 面板：12 个满足直判门槛，逐槽卡族/布局与 trace OCR 一致；相同策略配置下两路决策 12/12 动作类型与槽位一致，81 个走 OCR 回退。热缓存模板耗时约 50 ms 中位数（包 1 P90 96.98 ms；包 2 P90 74.98 ms）。完整数据记在 `G:\刷刷宝\nightwatch\pick_speed.md`。
- 离线真帧核对不是实机新运行；下次真机需观察模板覆盖率、当帧输入后面板是否正常变化，识别异常仍按 fail-closed 处理。
- 定向验证：`test_card_slot_template_matcher.py`、`test_choice_policy.py`、`test_mediator_choice_four_slot_integration.py`、第一帧高置信选卡用例及 Owner 规则锁通过；`tests/contract` 67 passed / 232 subtests passed；4 个选卡自然面板/OCR miss 用例 4 passed。组合运行整份 `test_live_run_205044_regressions.py` 时有 3 个进化弹窗用例失败（不经过羁绊模板直判路径，待单独排查）。`test_live_harness_refresh.py` 在重钉前因旧锚点报告 NOT_CLEAN；candidate 重钉到 `2b3ba108e9c653d9dc04f2a2514c65a160968cab` 后通过，23 passed。身份提交：`e2011ecf`，UTF-8 格式修复：`ab39726c`。

## 2026-09-26 局内分类递归修复

- Mediator._classify_choice_panel 的英雄几何候选改为显式调用 Core 检测，防止 Runtime 覆写互递归；无锚点帧保持返回 None。
- 未启动游戏；真机局内面板及进化点击流程需所有者后续验证。

## 2026-09-26 羁绊面板关闭失败 fail-closed

- Trace `solo_ingame_chain_20260925_230841_870781` 的 tick 291 显示 hard-deadline 后转 `CLOSING`；后续锚点持续存在而决策无输入。指定基线的单人 episode 上限分支已经会推进 `_L1_CYCLE_ORDER`，因此方案文档所述漏 advance 不是这次 trace 的直接根因。
- `_tick_panel_fsm` 的 `CLOSING` 现在最多尝试 3 次；关闭锚点缺失、点击被拒或 3s 超时后进入 `COOLDOWN` 并耗尽本次关闭预算。锚点仍在时保持零输入，直到锚点消失后再清理面板 episode。未加 Escape/盲点。
- FakeClock 回放覆盖 episode 上限推进和关闭失败后的有界重试；定向用例 8 passed，`tests/contract` 68 passed / 232 subtests passed，候选身份锚点更新后 `tests/test_live_harness_refresh.py` 23 passed。源码提交 `46ec6a3a078aeb05595817cdc90f9e66d65be6e0`。没有启动游戏；面板物理关闭及后续主线恢复仍待真机验证。
- OCR 的白名单目标路径已支持 ≥0.85 单帧免确认，模板完整快路已跳过 OCR 与双帧确认。本次不再调低通用 OCR 的 0.95 门槛；trace 真帧 f0352 上 ≥0.85 的「封神 / 箭术 / 三国」与卡面文字一致，f0355 上重复「法术」槽位仍被唯一性门控排除。该样本只支持维持现有门控，不代表整体误点率测量。
## 2026-09-26 进化二选一召回修复

- Perception 修复提交：`bce9c1bc941574b647b7fd2d8902ff0d70c10cfc`；身份清单独立提交：`09eef1ebb6e95e0c32343b436c7bb577ac9b6e0a`。
- 根因定位：`4da9790e` 在 `_find_evolution_choice` 新增固定 `x=540` 左边缘硬门槛；原回归夹具左框从 `x=550` 起，该采样带落空，进化选择被识别为 None，连带三项 205044 用例失败。
- 修复：移除过严左边缘条件；采用已有 `toHero` 专用模板与双卡边框联合确认；明确战后页优先排除。未增加局内状态字段，`INGAME_POLLUTION` 无需调整。
- 选择性离线探针：基线英雄真帧 `0/3` 命中，修复后 `3/3`；羁绊 `0/3`、空闲 `0/3`、scene_audit 冲突样本 `0/10` 命中；探针统计 C1=`0`、C1b=`0`。其中 2 张 ARCHIVE_PANEL 战后帧修复前曾误命中，战后排除后为 0。未重跑完整 1908 帧审计。
- 验证：`tests/contract` + `test_live_run_205044_regressions.py` 共 124 passed、234 subtests passed；`test_live_harness_refresh.py` 23 passed。未启动游戏；正式运行链路仍需真机验证。
- 额外试跑 `tests/test_runtime_stability_hotfix_20260821.py` 时，`test_physical_panel_deadline_is_telemetry_only_never_recovers_by_input` 失败；此项与本次 Perception 差异无关，按当前任务范围未处理。

## 2026-09-26 全量门禁分诊续跑

- L1 提交 `f8888272`：物理面板 watchdog 恢复为只记录遥测，关闭仍由 Core 面板 FSM 负责；旧选卡测试夹具补齐真实三槽布局，并按已验证的卡组目标保留规则校正期望。感知提交 `45890fda`：普通 HUD 上的 `toHero` 不再绕过进化弹窗几何条件，修复蹭车真帧 `f1028` 被误判、面板隐藏链无法进入 `CLOSING`；真实英雄二选一夹具继续通过。身份锚点由 `99d88cde` 单独重钉到 `45890fda`。
- 上述验证仅为离线夹具和测试，未启动游戏。蹭车选择面板的物理隐藏与主线恢复、局内进化二选一召回、羁绊面板超时关闭仍需下一次真机复核；不要把此次离线门禁结果当作实机通过。

## 2026-09-26 海贼王家族卡策略

- 配置将“海贼王”系列名放到海贼王高级组首位，并从 EX 终卡剥离名单删除。Owner 规则：家族槽位按系列名快速命中；同名 EX 海贼王也看到就拿。异火及大圣多子卡组继续通过现有家族匹配命中；同页只有未获得的祝福优先于勾选高级卡组。
- 两份 solo 真机 trace 未记录海贼王槽位；同批 trace 确认槽位含原始进度文本（如“齐天大圣(0/3)”“棍法(2/3)”，OCR 输出规范家族名）。抽帧未找到清晰的独立海贼王系列标签，未新增合成或裁切模板。
- 发布门禁本次结果：pytest 阶段 FAIL（2228 passed、1 failed、2 xfailed、16 skipped、373 subtests；pytest 生成失败详情时发生 MemoryError，退出前未输出失败 traceback）；冻结回放、模板完整性、contract 三阶段 PASS。模板资产 430 与 manifest 一致，未更新基线。单独重跑失败项 `test_real_f0245_reads_card_rarity_badge_letters_and_bands` 为 1 passed；全量 pytest/release_gate 仍需在资源稳定时重跑至 0 退出码。海贼王家族标签仍需有清晰真帧时再确认原始文字与模板需求。

## 2026-09-26 祝福优先与挑战批量开启提速

- L1：羁绊模板家族达到 0.85 即按未完成祝福、成长/经济、当前高级组、其它目标顺序直接选卡；只有最高目标家族出现多个槽位时读取稀有度徽标，否则选最左槽。没有命中目标时保留现有 OCR 与充分性回退门。
- L1：祝福集未满时优先进入羁绊选择，且不因羁绊访问成功次数上限推进；保留面板既有硬超时及 fail-closed 行为。自动技能队列的强制上限没有修改。
- L1：四个挑战按固定控制顺序批量右键，随后截图检查；仍为 OFF 的控制在同 tick 立即补点，最多两次重试。输入门禁只对当前 tick 同一证据帧中的挑战批量右键开放；重试仍 OFF 时记录 `challenge_toggle_unverified` incident 并停止。
- 离线 trace 重放：现场包 1/1 面板走直拿；指定旧 trace 两包共 93 面板中 64 面板直拿；总计 65/94 覆盖，65/65 与 trace OCR 的动作槽位一致，未发现不一致。直拿耗时中位数 162.617 ms、P90 271.987 ms（包含同家族并列时徽标识别）；均未启动游戏或发送真实输入。
- 定向选择/模板测试 `160 passed, 37 subtests passed`；本次新增用例 `10 passed`；`tests/contract` 为 `68 passed, 232 subtests passed`。`tests/test_live_harness_refresh.py` 待重钉身份后运行。所有行为仍需后续 Owner 实机验证。
