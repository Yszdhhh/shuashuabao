# 单人整合交接（给本地架构 agent）· 2026-09-15 上午

这是 Claude 编排线和执行 agent Round2 线合并后的状态。先读本文，细节再按需看：
- 证据报告（同目录）：`KB_MECHANICS_SYNTHESIS.md`（游戏机制）、`LIVE_DATA_ANALYSIS.md`（实机定量数据，中间数据在 `live_data_csv\`）、`LOST_LOGIC_ARCHAEOLOGY.md`（退化考古，含 P0/P1/P2 恢复清单）
- 执行 agent 的完成报告：`G:\刷刷宝\handoff_prompts\HANDOFF_SOLO_ROUND2_COMPLETION_20260915.md`，其中含 B5 羁绊顺序研究和 B7 黑商开关研究

## 0. 代码位置与纪律

| 项 | 值 |
|---|---|
| **整合线（以此为准）** | `G:\刷刷宝\Worktrees\solo-orchestration-20260915`，分支 `feat/solo-orchestration-20260915`，HEAD **48654d1**（执行 agent 的 a17ad19 和 ae8a375 都已合入） |
| 执行 agent 线 | `G:\刷刷宝\Worktrees\solo-fixes-20260914`，分支 `fix/solo-round1-20260914`。a17ad19（0970ddb）和 ae8a375（48654d1）都已合进整合线；执行 agent 之后如果再有提交，照样用 merge commit 合进来 |
| 当前 Live 测试线 | `G:\刷刷宝\Worktrees\live-solo-cc17962`（分支 `fix/solo-start-from-kk-20260914`，HEAD 67ab08d）；桌面「刷刷宝 Live 实机测试.lnk」的 `-ProductionSourceSha` = 67ab08d |
| Python | `G:\刷刷宝\GameScript-Local\.venv\Scripts\python.exe`；环境变量 `SHUABAO_OCR_PYTHON=G:\刷刷宝\GameScript-Local\.venv-ocr\Scripts\python.exe`、`SHUABAO_OCR_MODEL_DIR=G:\刷刷宝\GameScript-Local\models\ocr`、`PYTHONUTF8=1` |
| 纪律 | 不在 main 上提交；只用 merge commit；Live lnk 的 SHA 必须等于该工作树 HEAD；改了 `src/` 就要重定身份基线（`tools/live_harness_identity.py` 的 HARNESS_BASE_SHA/FROZEN 和 `tests/test_live_harness_refresh.py` 的 FROZEN/BASE，都改成最后一个改 src 的提交）；`python tools/live_scenario_capture.py identity --production-source-root <树> --production-source-sha <HEAD>` 必须是 READY FOR GT: YES；游戏开着时不跑全量 pytest；不许动门禁基线；不许打外发包 |

## 1. 整合线已包含的内容

### Claude 编排线（67ab08d 之后）
| 提交 | 内容 |
|---|---|
| 447c2f4 | 大秘境框和提前挑战确认框按标题区分。新模板 `env/great_rift_title.png`（红字"大秘境"）和 `env/tqtz_confirm_title.png`，已登记 manifest。模板失效时以"是"按钮为锚 OCR 标题行。新增战后状态 `TQTZ_CONFIRM`，识别到就点"是"。 |
| 2c2b471 | HUD 角标读取：`_hud_skill_points`（G = 未点技能次数）、`_hud_treasure_pending`（V = 待拿宝物次数）。按钮不在返回 None，没有角标返回 0。 |
| 0114845 / 7b17bfc | 单人编排规划器 `_solo_plan_panel`（规则见第 2 节）。另外：单人下"主动开面板但没弹出"不再计入异常上限；白名单按回报排序；属性线门卡移出 80% 分母；开局 8 分钟后兜底放开高级卡组；每次开面板的连拿上限；单帧直点；F 抽价按局计。 |
| 2593dd6 | 宝物 EX（ONEPIECE/至高进化/一身神装/满级大佬/全都要/卡牌大师）出现就拿，不看品质（Owner 已拍板；蹭车模式除外）。 |

### 执行 agent Round2（0970ddb 合入）
| 项 | 内容 |
|---|---|
| B3 | 读任务栏 OCR"主线X-Y"，读到 >(5,5) 就取消自动主线（已经是 OFF 时不点）；提前挑战图标出现作兜底 |
| B4 | 封神卡组补"肉身成圣"；选中某个高级卡组时并入该组全部成员（advanced_groups 里没有 EX 名） |
| B2 | 单帧直点（预设命中、≥0.95、无歧义），和 Claude 的"≥0.95 标题命中"取并集；同屏同名的羁绊视为同一套装，不再要求第二帧；局内面板重开间隔 0.5 s；选卡期间不按 F4 |
| B1 | 同一步最多停留 N 次成功选择或 30 s，N 用编排的按类型上限（F 3 次，开局 1 分钟 6 次；G 5 次） |
| B9 | 连续失败 N 局降一档（`downgrade_after_failures`，0 = 关，看板有输入框）；降级时清零失败计数 |
| B6 | pytest 日志重定向到临时目录 |

全量回归（2593dd6，合入 ae8a375 之前）：2252 通过、5 条失败，见 `pytest_merged.txt`。其中 habit_preference 和 ocr_production_bundle 两条由 ae8a375 修好，合入后已复验通过；剩下的 3 条 `test_live_harness_refresh` 是身份基线，合进 Live 线时重定即可。

门禁 `scene_templates` 快照 399 → 401，就是新增的 2 个标题模板，属于有意新增，**没有**刷新基线。

## 2. 当前单人编排规则

每个 tick 按顺序判断（代码：`_solo_plan_panel` / `_bond_step_blocked` / `_visit_capped` / `_l1_step_visit_exhausted`）：
1. **技能积压 ≥ 4** → 开 G。例外：上次开 G 没选成卡（30 s 退避），或者本轮已连点 5 个。
2. **基础羁绊未满 80%，木材 ≥ 500，并且 F 能推进** → 开 F。每次开 F 最多连拿 3 张（开局 1 分钟 6 张），拿满后羁绊优先暂停，等轮换回到另一个 bond 位置才恢复。
3. **其余按轮换** `bond, skill, bond, skill, treasure, evolve, equipment, pickup, merchant, artifact`：木材 < 500 跳过 F（Owner 规则）；G 或 V 角标为 0 跳过；角标读不到时照常开；任何一步停留超过 30 s 就推进。

白名单顺序：经济类（祝福 > 经济 > 贪婪 > 挑战 > 成长）→ 看板勾选的基础卡 → 属性线（门卡一直到 UR）→ 高级卡组（整组成员）。80% 门槛只统计经济类加基础卡，开局 480 s 后兜底放开（`config/choice_policy.json` 的 `bond.advanced_unlock_s`）。

⚠ **经济类顺序有分歧**：执行 agent 的 B5 研究建议 经济 → 贪婪 → 挑战 → 祝福 → 成长，理由是旧 KB 说经济是贪婪、挑战的前置，但这条"实测未核"。现在代码是祝福第一，理由是开局第 1 分钟抽价只有 20–80，祝福 3 张净赚木材。实机时请核对：没完成经济之前，贪婪和挑战会不会出现在羁绊面板里。如果不会，把 `_ECONOMY_BOND_ORDER` 改成 经济 → 祝福 → 贪婪 → 挑战 → 成长。

**所有阈值（4 / 500 / 3 / 6 / 5 / 30 s / 80% / 480 s）都是依据 KB 和 3 局数据给出的初值，没有做过实机 A/B。**

## 3. Owner 已拍板（2026-09-15 上午）

1. F4：会清掉挑战怪，但不影响自动四挑战，不重要。**保持现状**。
2. 拾取 Z：**物品栏满了才按，而且背包要有空格**；背包没空格时拾取了也用不上。现状只检查了"物品栏 2–6 满"（`mediator.py` 的 pickup 步、`_hud_item_bar_overflowed`），**还缺"背包有空格"这个判断** → 待办 P1-3。
3. 技能路线：**按技能截图和技能机制重新优化** → 待办 P1-4。
4. 宝物 EX 出现就拿，不看品质 → **已完成**（2593dd6）。

## 4. 待办（接手 agent 按顺序做）

### P0
0. ~~合入 ae8a375~~ 已完成（48654d1）。
1. **整合进 Live 线并切 lnk**：
   - 在 `live-solo-cc17962` 执行 `git merge feat/solo-orchestration-20260915`（merge commit）。
   - 全量 pytest：除 OCR 模型目录环境变量那一条外全绿。
   - 按第 0 节重定身份基线，把 lnk 切到新 HEAD，身份检查 READY。
   - 然后通知 Owner 开测（菜单 12）。
2. **测试壳 tick 开销**：harness 每个动作同步写 2 张 1600×900 PNG（`tools/live_scenario_capture.py` 约 1914 行、3564–3575 行），加上 observer 每 tick 做检测，实机 tick 从 0.3 s 涨到约 1.35 s，每张卡多约 4 s。改成异步队列或降采样 JPEG，失败或书签帧再写全尺寸 PNG。验收：离线 tick 中位数 ≤ 0.5 s。

### P1
3. **拾取 Z 加"背包有空格"条件**（Owner 规则 2）：物品栏满，并且公共或个人背包有空格才按 Z。背包空格可以复用 `_bag_layout` 等背包页识别；读不到时保持现状，不按。
4. **技能路线优化**（Owner 规则 3）：Owner 当前配置 skills = asj/asjg/assx/jq，routes = asj:damage、asjg:flood、assx:damage、jq:ice、tl:paralysis。KB 指出：asj/assx 的 damage 路线已判作废；jq 碎冰线需要冰霜新星（不在已选技能里）；普攻被禁后 asj 急速流走不通。依据 `config/skill_routes.json`、`skill_card_catalog.json`、`skill_card_knowledge.json`、KB 报告第 4 节和实机技能面板截图（证据包 frames 里 OpenSkillPanel 的前后帧），给出每个技能族可达的路线和推荐配置，并修正默认路线或策略里的前置、豁免。**改看板默认值前先出方案给 Owner**。
5. **单人黑商恢复**木材礼包和 2 折、5 折（d7d6dc2 在 09-08 全模式收窄成只买吞噬丹；Owner 在 08-27 定的规则是吞噬丹 + 木材 + 2/5 折）。按 `mode_id` 隔离，蹭车不变。杀敌数 OCR 读不到时单人不要无限等。
6. **ui-v2** 基础卡组补 提速、体术，流派预设默认带 祝福（`ui-v2/index.html` 的 BASIC/DEFAULT_PRESETS，`ui-v2/src/main.ts` 的 basicNames）。随正式包生效。
7. **羁绊刷新**：每组最多刷 2 次；木材不够当前刷新价（40/60/80/100）时不刷，改成隐藏。
8. **主线停滞转向**：用 B3 已有的任务栏 OCR。同一个"主线X-Y"停超过 90–120 s，或者出现"主线挑战失败"时，技能积压门槛降到 1，羁绊只拿战力类。
9. **稀有度**改读卡面上的 N/R/SR/SSR 字母，不再采样边框颜色。

### P2
10. 补标题模板：封神、刀刀、修仙、异火、亡灵、藏宝图、肉身成圣、贪婪。
11. `skill_archive_levels` 在 ui-v2 里没有（存成 `{}`），只影响技能排序。
12. B7：看板黑商开关后端字段是全的，UI 在 19cc48a 被移除，是否恢复等 Owner 定。

## 5. 实机验收标准（菜单 12，1-21，Owner 当前看板设置）

| # | 标准 | 从哪里看 |
|---|---|---|
| A1 | 开局 5 分钟内 G 至少点 5 次；G 角标不超过 8 且持续不超过 60 s | trace 的 OpenSkillPanel 和技能选择；抽帧读 G 角标 |
| A2 | 前 10 分钟 treasure、evolve、pickup、merchant、artifact 各至少触发一次；V 角标 ≥1 时 3 分钟内被领 | trace 的 actions reason |
| A3 | 没有超过 30 s 的零输入段（战后转场除外），不出现 COOLDOWN 挂住整局 | trace 的 actions 为空的连续 tick |
| A4 | 木材 ≥500 时羁绊优先，< 500 转技能和支线；日志里能看到"编排：…"和"羁绊暂不推进（木材 …）" | 控制台 / trace |
| A5 | 属性线整条会拿；封神在 8 分钟内开始拿，或者基础卡到 80% 后开始拿；肉身成圣能拿 | trace 的 ocr_bond:<名> |
| A6 | 单张羁绊从开面板到点击，中位数 ≤ 3 s（harness 修好后 ≤ 2 s） | trace 时间戳 |
| A7 | 读到主线 5-6 后取消自动主线；提前挑战点图标再点"是"；打完进秘境：大秘境框点"是"并进入 | trace 的 DisableAutoTask、ClickTQTZ、ConfirmTQTZ、OpenGreatRift、ConfirmGreatRift |
| A8 | 第二局在原房间直接开始；连输 N 局后降一档（需在看板设了 N） | trace 的 RoomStart、SelectStage 目标 |
| A9 | 同难度对照 000229（4-5 卡 7.5 分钟）：4-5 停滞不超过 2 分钟 | 任务栏抽帧 |
| A10 | 宝物面板出现 EX 时直接拿 | trace 的"宝物必拿秒选…（EX 不看品质）" |

不通过时带上证据包路径（`%LOCALAPPDATA%\Temp\shuabao-captures\solo_ingame_chain_*`），不要为了过测试去改阈值或改基线。
