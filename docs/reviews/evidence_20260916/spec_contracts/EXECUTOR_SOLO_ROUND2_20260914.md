# 执行 agent 第二阶段任务（单人 Round2）— 2026-09-14

你的上一轮回传（B8 测试 7fba402、B4/B1/B2/B3 方案）已经验收。下面是 Claude 的裁决和本轮任务。
**先做第 0 步，再按顺序做 B3 → B4 → B2 → B1(剩余) → B9 → B6，每项单独提交。**

## 0. 同步基线（必须先做）

Live 线在你出方案的同时又落了一批修复（第二局实机发现的问题），提交 **67ab08d**（分支 `fix/solo-start-from-kk-20260914`，工作树 `G:\刷刷宝\Worktrees\live-solo-cc17962`，你只能读、不能改）：

| 问题（第二局实机） | 修复 |
|---|---|
| 提前挑战弹出「是否确认提前挑战？」后零输入 180s，Owner 手点「是」 | 该弹窗与大秘境确认框同款灰色「是」(mijingOk 0.91)，被分类成 GREAT_RIFT_CONFIRM，找不到「否」→零输入。现在局内（非战后）+ 点图标后 30s 内或提前挑战字样仍在 → 点「是」(ConfirmTQTZ)，不再等不存在的 Boss 选择面板 |
| 属性线只拿门卡（智力/力量/敏捷） | 按 KB `attr_routes.*.chain` 展开：门卡→中环→次环→UR。后面 3 张进新字段 `bond_chain_presets`：任何阶段可拿，**不计入基础卡 80%**，也不是高级卡组。support（法术/魔法师/箭术…）不随属性线自动拿 |
| 魔法师/元素师不能在看板勾选 | ui-v2 基础卡组 BASIC 加入这两张（index.html + main.ts；随下次正式包生效） |
| 单人第二局房主被点到二楼 | 离开旧房间（G0 契约 #7）现在只在「每局新建房间 new_room_every_times」开启时执行；否则回原房间直接开始 |
| 秘境右键点在「大秘境」文字上、第 3 次右键 2s 后就放弃 | 右键 NPC 本体（标签中心左 0.28w、下 0.045h）；每次右键后等 5s 让英雄走过去，第 3 次也等完再判定 |

在你的分支 `fix/solo-round1-20260914` 上执行（只许 merge commit，不许 rebase/squash）：
```
git fetch 2>nul & git merge 67ab08d
```
冲突预期在 `src/shuabao/choice_policy.py` 的 `assemble_policy_settings`（你要做 B4）和 `tests/fixtures/solo_live_20260914/`。以 Live 线为准合并；合完跑 `tests/test_attribute_bonds_whitelist_20260914.py tests/test_solo_tqtz_confirm_20260914.py tests/test_solo_rift_path_20260914.py` 必须全绿。

## B3（最高优先级）：5-5 后取消自动主线 —— 任务栏 OCR 触发

裁决：**同意方案，但触发条件改成 (章,节) > (5,5)**，不是 ≥。
- 理由：看板原文是「5-5 **后**取消自动主线」；任务栏读到「主线5-5 击杀阿克蒙德」时 5-5 还没打，此时关自动任务会导致 5-5 不打、提前挑战（需 5-5 已过）永远不出现。读到 5-6…5-9 或 6-x（含「已完成当前难度全部主线」）才触发。
- 实机时间线：第一局 f0250（6.7min）主线5-5；f0410（11.3min）主线6-1。第二局 f0582（11:28）已是主线5-6——现在只绑提前挑战，关得太晚。
- 第二局还观察到：提前挑战确认「是」之后自动任务已是 OFF（f0584 `_auto_task_state`=OFF 0.85）。所以 `_maybe_close_main_line_after_5_5` 读到 OFF 就只记日志不点，这是对的，保留。
- **Owner 补充（提前挑战开放时间因人而异）**：常规 10 分钟；有 UR 道具「时间管理大师」提前到 8 分钟；再叠远古神藏 EX「圣剑」最快 6 分钟。前提都是 5-5 已打完。因此：①**任何代码都不得用固定时长（600s 等）去门控或推断提前挑战/5-5**，提前挑战只认图标出现；②5-5 取消自动主线只认任务栏 >(5,5)，提前挑战图标出现作为兜底（图标出现必然 5-5 已过）；③测试里至少覆盖 6 分钟就出现图标的情形。
- 实现：局内每 10s 最多一次 OCR（复用现有 OCR worker，禁止新进程），ROI 归一化（约 x 0.89–0.99, y 0.32–0.37 @1600x900，你自己用 f0250/f0410/f0582 校准）；正则 `主线\s*(\d+)\s*[-一—]\s*(\d+)`；命中 >(5,5) 置 `_close_main_line_triggered=True`。提前挑战触发保留作兜底。
- 真实帧回归：f0250 → 不触发；f0582（`G:\刷刷宝\Worktrees\live-solo-cc17962\tests\fixtures\solo_live_20260914\tqtz_confirm_dialog_f0582.png` 是弹窗帧，另取同局 f0581 无弹窗帧，证据包 `%TEMP%\shuabao-captures\solo_ingame_chain_20260914_225835_837539\frames\`）→ 触发；f0410 → 触发。再加一条完整 `_tick_main_line`：自动任务 ON + 任务栏 5-6 → 发出 `DisableAutoTask`。

## B4：封神卡组补「肉身成圣」

裁决：**同意**。
1. `config/choice_policy.json`：`advanced_names` 与封神 `advanced_groups` 加「肉身成圣」。
2. `assemble_policy_settings`：用户选中某个高级卡组（任一成员出现在 settings.cards）时，把该 catalog group 全部成员并入 bond_presets/advanced_presets（补足看板未展开的新成员）。注意与 Live 线新加的 `chain_presets` 共存：链路卡不能被误并入高级组。
3. `ui-v2/src/main.ts` `ADV_PACK_CARDS.fengshen` 加「肉身成圣」（index.html 里若有同名常量一起改）。
4. 真实帧：第一局 8 次出现（OCR 0.9975）任取 1 帧，断言封神组激活后选中它。

## B1：局内步骤饥饿 —— 主体已由 Claude 在 Live 线修复（252e35f），你只做剩余部分

已修（第三局实机 000229：前 5 分半只开 F、G 一次没开；木材耗尽后整局只剩每 60s 一次 F4）：
- `_L1_CYCLE_ORDER` 里 bond/skill 重复，按名字 `order.index()` 推进永远 bond↔skill，宝物/进化/装备/拾取/黑商/神器从 08-21（d919544）起就走不到 → 改按位置推进。
- 80% 基础羁绊锁只在 F 能推进时生效：HUD 木材 OCR（新 `_hud_wood_balance`，ROI 在骷髅左侧）≥500、F 没有长冷却、F 没到 episode 上限、上次开 F 拿到了卡（否则 30s 退避）。Owner：木材 <500 先技能，再宝物/进化/物品栏/神器/黑商。
- 单人 episode 上限 = 该面板 60s 退避 + 轮换前进（原来每 tick 重设 60s，F 本局再没开过）；长冷却也前进，短冷却（≤10s）仍原地等。
- COOLDOWN 且画面上无面板时释放 tick → F1 英雄焦点兜底能跑了。

你还要做的：
- 有上限的抽干：同一步骤一次访问最多 3 次成功选择或 30s 就推进。
- 离线整局回归：用 `solo_ingame_chain_20260915_000229_642428` 的帧序列模拟 10 分钟 tick，断言 skill/treasure/evolve/equipment/pickup/merchant/artifact 都至少轮到一次、没有 >20s 的零输入段。
- V 积压插队不做了（轮换修好后不再需要），除非整局回归证明仍饿。

## B2：拿卡提速

裁决：
- ✅ 1 WAIT_VISIBLE 当帧见 anchor 立即进 ACTIVE 并在同 tick 读卡。
- ✅ 2 免二次确认：仅当卡名**完整命中白名单**、OCR ≥0.95、四个槽位无重名/歧义时；其余保持两帧确认。
- ✅ 3 局内面板关闭→下次打开间隔 1.5s → 0.5s（不是 0.3s；只影响局内选卡面板，不改全局 ui_action_interval_s）。
- ❌ 不要取消 F4 压力清怪；只保证它不插在一次面板会话（OPEN_REQUESTED→CLOSED）中间。
- 交付：同样的 trace 拆分表，改后用离线 tick 序列估算单卡周期（目标 ≤5s）。

## B6：pytest 不得写真实日志

测试进程写到了 `%LOCALAPPDATA%\ShuaBao\logs\ShuaBao.log`（1970 时间戳，已污染实机日志）。在 `tests/conftest.py` 用 tmp 目录重定向 log sink；回归：跑一个会打印的测试后真实日志 mtime 不变。

## B9（新功能，Owner 2026-09-15）：打不过自动降级

- 看板新增设置「连续失败 N 局降一档」（整数，0 = 关闭）。例：目标 1-21、N=2 → 连续两局失败后第三局开 1-20；再连续 N 局失败继续降；最低 1-1。
- 失败 = 现有 `_record_round_outcome(RoundOutcome.FAILURE…)` 同一口径；胜利清零降级计数。
- 降级后把连续失败计数（`_failure_streak`，failure_streak_limit=3 的停机熔断）清零，否则降级那局还没打就会被熔断停机；熔断只对「降到 1-1 仍失败」生效。
- 选关：复用现有 `stage_targets` 选关路由，只改本次运行的目标，不回写 user_settings.json；日志和 trace 打印「降级 1-21→1-20（连续失败 2 局）」。
- 后端字段名 `downgrade_after_failures`；ui-v2 在关卡设置旁加数字框（随下次正式包生效）。
- 测试：两局失败后第三局 SelectStage 目标为 1-20；胜利后计数清零；N=0 时行为不变。

## B5 / B7（有空再做，只出报告或小改）
- B5 羁绊研究只出报告。
- B7 看板黑商开关：先报告 ui-v2 当前入口与后端字段，**不改 UI**，等 Owner 定。

## 纪律（不变）
- 不许改 `live-solo-cc17962` 工作树和 Live lnk；不许在 main 上提交；只许 merge commit。
- 每项提交后重定身份基线（`tools/live_harness_identity.py` + `tests/test_live_harness_refresh.py`）只在**最后一次**做一次。
- 不许动门禁基线、不许把 mode_evidence 改 PASS。
- 游戏开着时不要跑全量 pytest（内存不足会出 0xC0000142 假失败）；针对性测试可以。
- 回传格式：每项 = 提交 SHA + 改了什么 + 真实帧测试名 + 修复前失败/修复后通过的证据。
