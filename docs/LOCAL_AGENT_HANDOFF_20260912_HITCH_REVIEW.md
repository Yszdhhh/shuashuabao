# 本地 Agent 交接：蹭车（lobby_hitch）链路架构审查 / 逻辑冲突审查（2026-09-12）

面向：本地架构审查 / 逻辑冲突审查 Agent。**本任务不需要看图**：所有实机证据都已转成文字（下文 §5）和离线测试（真实帧已进 `tests/fixtures/hitch_live_20260911/`，测试会自己读图）。需要验证的都用脚本/测试完成。

---

## 0. 可直接粘贴给本地 Agent 的提示词

```
你是本地代码审查 Agent，负责「刷刷宝」蹭车模式（mode_id=lobby_hitch）的架构审查与逻辑冲突审查，不负责实机测试、不需要看截图。

工作目录：G:\刷刷宝\Worktrees\prod-source-3904913-20260911（detached HEAD，本地分支 fix/hitch-live-closure-20260912 指向当前候选）。
Python：G:\刷刷宝\GameScript-Local\.venv\Scripts\python.exe
先读：docs/LOCAL_AGENT_HANDOFF_20260912_HITCH_REVIEW.md（本文件）、docs/CURRENT_STATUS_AND_HANDOFF_20260911_HITCH_HOST_EXIT.md、docs/reviews/HITCH_LIVENESS_AUDIT_20260912.md。
主要代码：src/shuabao/mediator.py（~14.9k 行，核心状态机）、src/shuabao/runtime_mediator.py（LIVE 实际使用的子类，覆盖了部分核心方法）、src/shuabao/lobby_hitch.py、src/shuabao/policy/public_bag.py、src/shuabao/input/keyboard_mouse.py。

任务（按优先级）：见本文件 §6「审查任务」A–H。每项输出：结论（有/无问题）、证据（文件:函数/行）、最小修复建议或补丁、需要新增的离线测试。
约束：
- 不要一次跑全量 pytest（曾挂 19h、吃 3.7GB）。按 tests/test_*.py 排序后分两半顺序跑，每批加 timeout；跑完确认没有残留 python/pytest 进程（会影响实机加载游戏）。
- 已知既有失败 5 个（与本链路无关）：test_live_harness_refresh.py 3 个（工作树身份检查）、test_live_scenario_capture.py::test_lobby_hitch_uses_default_and_custom_search_text、test_mode_catalog.py::…hitch_dashboard_contract…（读本机用户配置）。
- 不改 G:\刷刷宝\GameScript-Local 下的实机 harness（有身份基线）；不 push、不改桌面快捷方式；commit 只在本地、信息末尾带协作署名。
- 行为改动必须配离线测试；优先写「用真实帧驱动完整 Mediator.tick()」的测试，而不是直接调单个 handler + 合成帧（后者多次假绿）。
- 用中文输出审查报告，放 docs/reviews/。
```

---

## 1. 背景

- 项目：英雄三国（KK 平台，魔兽地图「重生魔兽刷刷刷」）挂机脚本。蹭车 = 在 KK 大厅搜房 → 进别人房间准备 → 房主开局后当「乘客」：点压力转移、开自动任务和四挑战、宝物/拾取/把队伍物资搬进公共背包、黑商买吞噬丹；战后走存档挑战/传家宝，然后退出游戏、回大厅找下一局。
- 实机测试：桌面「刷刷宝 Live 实机测试.lnk」→ `G:\刷刷宝\GameScript-Local\live_scenario_launcher.ps1 -ProductionSourceRoot <本工作树> -ProductionSourceSha <HEAD>`，菜单 13 = hitch_lobby_chain 整链。需要用户点 UAC。每次实机产出 bundle：`%TEMP%\shuabao-captures\hitch_lobby_chain_*`（trace.jsonl 每 tick 一行、frames/ 事件截图、manifest.json 结论）。harness 的 FAIL 结论有自己的规则（例如「在未识别画面上发输入」即判 FAIL），不等同于生产逻辑出错。
- 用户确认过的业务规则（改代码不得违反）：
  - 未知画面绝不盲点；看不懂就零输入，但零输入必须有上限（§3 监督器）。
  - 座位：无论是否已准备，①我方成为房主 ②我方坐一楼 ③一楼玩家离开 → 退房并拉黑该房。
  - 英雄三国游戏窗存在 = 游戏流程接管（不能再按大厅逻辑处理）。
  - 压力转移：画面上有按钮就永远优先点；没有按钮绝不阻塞其它工作。
  - 背包：物品栏 2–6 格有东西才开背包；所有物品（含英雄卡）都搬进公共背包；手动关背包要尊重。
  - 传家宝点完后：广场上看到右侧「已获取」装备 → 退；广场上满 60s → 退；失败 → 失败链退；传送进秘境/团本 → 不退，等失败/胜利页再退。
  - 聊天输入条 = Enter 开关；只在确认它开着时按 Enter 关。

## 2. 这些轮做了什么（按提交）

| 提交 | 实机证据 | 根因 | 修复 |
|---|---|---|---|
| 52f0c22 | 进房后 275s/11min 死锁；升房主后点自己头像 | 旧房间残留纯黑 HWND 被当成进房子窗口，健康门禁拦下后 `_tick_lobby_hitch` 永不执行；房主视角未识别 → 大厅 Tab 固定槽位落在头像；退房确认框是独立 HWND | 黑窗口排除、进房探测只认新 HWND；座位规则；退房事务（退出→独立确认 HWND→fresh 大厅，有界重试+BLOCKED）；KK 主窗口导航兜底 |
| 8b84614 | 不点压力转移先开挑战；背包常驻 | `mainIdentifier` 其实是「等待玩家1选难度」横幅却被当局内 HUD；自然进局备注让 set_phase 跳过新局初始化；自动任务熔断；背包无租期 | 删错误锚点；自然进局 = 新局初始化 + 武装压力门禁；背包 30s 租期/冷却/手动关闭尊重 |
| 4a412ad | 金色皮肤房间不认；游戏在跑却按大厅处理 7 分钟 | 房间识别依赖蓝色按钮；大厅阶段不看游戏窗 | 房间识别改为皮肤无关（封面+槽位+白字像素数）；大厅阶段先探测游戏窗；压力转移规则重写 |
| 6556f63 | 失败页卡住 | 聊天条盖住失败弹窗按钮行 | 失败改走左上角退出；聊天条检测 |
| 9eeec80 | （审计）| 零输入分支 165 个、各自为政 | **统一无进展监督器** `_hitch_liveness_supervise` + 活锁停留上限；退局后 25s 不接管正在关闭的游戏窗；trace flush 回归修复 |
| 91aa9b6 | 局内 4 分钟/第 2 局整局零操作；背包空开；英雄卡不放；传家宝 9 分钟不选 BOSS | 宝物「次数不足」计失败→上限后 COOLDOWN 死循环且计数不跨局清零；开背包无前置；英雄卡饱和像素 135<140；时光之穴/传家宝共用 BOSS 点击计数 | V 无面板不计失败+30s 重试+上限跳过+每局清零；HUD 物品栏 2–6 门禁；HUD 同格佐证；BOSS 计数按页面分开 |
| 87f9d56 | 玩家手动退出被当成大秘境取消；广场不认；传家宝退出规则 | 通用橙色「确认」模板命中退出确认框；NPC 标签要求两个同时可见 | 大秘境只认灰色「是」≥0.85 且排除退出确认框；顶栏「存档」模式标签识别广场；秘境/团本场景变化识别；传家宝 60s/装备/秘境规则；聊天条 Enter 关闭 |
| （本轮，未提交前见 git log） | 12:03 局：胜利不点继续；吞噬丹不买 | ① 胜利横幅动画先于「继续游戏」出现且垫在存档面板上 → 先被判 ARCHIVE_PANEL → 乘客接管存档链置 `_post_game_pending=True` → 完整胜利页把它读成「已点继续，等待消失」而点击时间为空 → 永不超时；② 我们点完 [Z]/[B]/[V]/挑战图标后鼠标停在按钮上，说明框盖住右下黑商栏，吞噬丹（露出时 0.99）在黑商步从未被看到 | ① 新素材 `env/victory_banner`（胜利帧 0.97–1.0，其它 ≤0.65）→ 横幅即 POST_VICTORY、等按钮；「已点继续」必须有点击时间；② 通用「自身遮挡清理」：底部 HUD/右缘点击后标记，下一次读 HUD 前先把鼠标挪到空地（新输入原语 `InputExecutor.move`，只移动不点击） |

## 3. 已有的通用机制（审查时要当作「系统不变量」核对）

1. **无进展监督**（`_hitch_liveness_supervise`，每 tick 在 `_tick_impl` 返回 Continue 后执行，仅蹭车 LIVE）：各阶段无有效输入预算 → 读真实画面（游戏窗优先）交给正确阶段/软复位 → 离开 → BLOCKED。盲键（`_LIVENESS_BLIND_REASONS`：Esc 兜底、误开选关 Esc、聊天 Enter、ParkPointer）不算进展。设计内有界等待用 `_hitch_declared_wait_until` 声明。活锁：退出链 240s / 失败恢复 180s / 房间 600s 停留上限。
2. **真实画面优先**：大厅阶段先探测游戏窗；监督器按「画面归属」而不是按当前阶段处理。
3. **自身遮挡清理**：背包租期与战后先关背包；聊天条 Enter 关闭（两帧确认）；鼠标停车（本轮）。
4. **每局状态边界**：`set_phase(MAIN_LINE)` 的 `entering_main_line` 块 = 新局初始化（备注含 reconcile/existing game/already in game 等会跳过）；`_hitch_after_exit` = 蹭车 episode 边界（所有回大厅路径汇合处）。**注意：部分字段只在 STAGE_SELECT 分支清零，蹭车从不经过选关。**

## 4. 反复出现的缺陷形态（审查重点）

1. **信念与画面错位**：阶段以为在 X，画面其实是 Y（黑窗口、换肤房间、游戏已开局、胜利动画）。
2. **一个标志多种含义 / 跨上下文共享计数**：`_post_game_pending`（「战后链进行中」vs「已点继续」）、`_boss_challenge_attempts`（时光之穴 vs 传家宝）、`_panel_episode_count`（不跨局清零）。
3. **自身 UI 遮挡下一步识别**：按钮说明框、物品说明框、聊天条、背包页。
4. **无上限零输入 / 「预算耗尽→重新武装」循环**。
5. **通用模板跨页面误命中**：`ok`/确认、`mijingOk`、`mainIdentifier`、`exit_confirm_btn`。
6. **测试与实机的差距**：LIVE 用 `runtime_mediator.Mediator`（覆盖 `_advance_l1_cycle`、`_tick_panel_fsm`、`_maybe_open_choice_panel`、`_tick_main_line` 包装），很多测试只测核心 `mediator.Mediator`；很多测试直接调单个 handler、patch `find`/`act_click`，绕过门禁。

## 5. 实机证据（文字版，不必看图）

- `hitch_lobby_chain_20260912_120333_103843`（本轮）：12:03 进房，12:05:34 压力转移，宝物/拾取/背包存入正常 5 轮（`public_bag_deposit_attempts 34`），**黑商操作 0 次**；黑商栏在 101 帧可见，吞噬丹模板在其中 21 帧 0.99 命中——全部是刚点完宝物面板、鼠标在屏幕中间的帧；其余帧右下被 `[Z] 一键拾取 / [B] 背包 / [V] 宝物 / 宝物挑战[右击开启自动挑战]` 说明框覆盖（说明框区域约 x 0.72–0.93, y 0.57–0.76，正好压住黑商栏 x 0.70–0.90, y 0.66–0.76）。12:13:39 胜利横幅动画开始（`f0234`：「胜利」+三星，无「继续游戏」，背后是存档面板/时光之穴列表），之后 2 分钟每帧指纹都在变（画面在动），脚本零输入，stall_s 到 131s 时用户停止。harness 在 12:13:39 以「UNKNOWN 画面上发输入（Pickup-Z）」判 FAIL 后不再存截图。
- `hitch_lobby_chain_20260912_101930_846970`：第 1 局完整跑通；第 2 局宝物步骤死循环（面板 COOLDOWN）；传家宝面板打开 9 分钟不选 BOSS；10:53:58 玩家手动点退出后脚本点了「取消」（误判大秘境）。
- 更早的包见 `docs/CURRENT_STATUS_AND_HANDOFF_20260911_HITCH_HOST_EXIT.md` 各轮。

## 6. 审查任务（按优先级）

**A. 多义状态标志清点（最高）**
- 列出蹭车局内/战后所有布尔/计数型状态（`_post_game_pending`、`_post_game_route`、`_victory_continue_since`、`_boss_challenge_*`、`_hitch_heirloom_exit_since`、`_secret_realm_*`、`_panel_*`、`_public_bag_*`、`_l1_cycle_step`…），标出每个的「写入点 / 读取点 / 含义」。
- 找出一个字段承载两种含义、或被两个上下文共享的情况（本轮已修两例，见 §2）。建议是否把战后链改成显式子状态枚举（例如 VICTORY_WAIT_BUTTON / VICTORY_CONTINUE_SENT / ARCHIVE / HEIRLOOM_GRID / HEIRLOOM_SENT / PLAZA_WAIT / INSTANCE）。给出迁移步骤，不要一次性重写。

**B. 每局重置完整性**
- 对比 `set_phase` 中 STAGE_SELECT 分支、`entering_main_line` 块、`_hitch_after_exit`、`_finish_hitch_round` 的清零字段。列出「只在 STAGE_SELECT 清零」的字段（蹭车从不走选关），逐个判断蹭车下是否会跨局泄漏。
- 同样核对 `runtime_mediator.set_phase` 的附加重置。

**C. `_tick_main_line` 早返回清单**
- 逐个列出 `return LoopAction.Continue` 且零输入的分支，标注：谁拥有它、上限是什么、上限到期后去哪。重点：「预算耗尽 → 重新武装继续等待」的乘客分支（战后继续×2、存档面板关闭、传家宝弹窗关闭、局内退出、退出确认）。确认它们都被监督器或停留上限覆盖，且监督器的「进展」不会被这些分支里的盲键掩盖。

**D. 监督器与局部计时器冲突**
- 核对 `_HITCH_STALL_BUDGET_S`、`_HITCH_DWELL_CAP_S` 与各局部等待（准备 70s、退房宽限 60s、成员房间保持 150s、找房 SLEEP_RETRY 120s、传家宝 60/120s、胜利页 30s、整局 3600s）是否有互相打断或永不触发的组合。
- 核对 `_LIVENESS_BLIND_REASONS` 是否完整（任何重复发送、不改变画面的输入都应列入）。

**E. RuntimeMediator 与核心分叉**
- 列出 `runtime_mediator.Mediator` 覆盖的方法及语义差异（尤其 `_advance_l1_cycle` 用位置索引、核心用 `order.index`）。确认本轮/前几轮只改在核心里的逻辑在 LIVE 子类下同样生效；给出「LIVE 子类跑一遍」的测试补法（很多现有测试只实例化核心类）。

**F. 新输入原语 `move` 的边界**
- `InputExecutor.move`（keyboard_mouse.py）与 `Mediator.act_move`：检查前置检查（前台/遮挡/急停）与 click 一致；`act_move` 走 `_action_forbidden` / `_action_gate_ok` / `_finish_input`。
- 实机 harness 的 `RecordingInputExecutor`（GameScript-Local/tools/live_scenario_capture.py）没有包装 `move`，会继承基类直接执行、不经 harness 记录/guard（生产 trace 里有 `intent: move`）。评估是否需要在 harness 侧补包装（harness 有身份基线，改动需走基线流程，不要擅自改）。
- `_note_pointer_on_hud` 的判定（点击点 y ≥ 0.55H 或 x ≥ 0.85W）与 `_maybe_park_pointer` 的跳过条件（背包事务中/面板非 CLOSED/有待确认动作）是否会漏停或在不该停的时候停。

**G. 模板分类器交叉混淆矩阵（可脚本化，无需看图）**
- 写一个脚本：对 `_post_game_state`、`_is_in_game_hud`、`_host_choosing_difficulty`、`_top_bar_mode`、`_find_exit_confirm`、`_game_chat_input_visible`、`_hitch_room_surface_evidence` 等分类函数，跑遍 `tests/fixtures/**`、`fixtures/**` 全部真实帧，输出「每帧 × 每分类器」结果表；找出同一帧被两个互斥分类器同时判真的情况。产出 CSV + 结论，发现的混淆补成测试。

**H. 结构（不改行为）**
- mediator.py 已 ~14.9k 行 / 400+ 方法。提出拆分方案（例如：蹭车大厅/房间、局内乘客循环、战后链、公共背包、监督器、分类器），给出第一步可独立落地、零行为变化的抽取（只移动代码 + 保持测试全绿）。

## 7. 已知限制 / 未决事项

- 秘境/团本的真实画面还没有样本；「离开广场」判定（顶栏「存档」消失 + 左上退出按钮在，连续 3 帧）未经实机验证。
- 退出确认点击被吞、游戏没关时，25s 后会重新接管并再次退出，局数可能多记 1。
- release gate 的 scene_templates 快照数（393）因新增已登记素材而漂移（现 398），刷新快照需跑全量 gate，未做。
- 最近两个提交 + 本轮提交只在本地，未推送（9eeec80 及之前已推 origin/fix/hitch-live-closure-20260912）。
- 实机工具在 FAIL 结论后不再存截图但生产循环继续运行——事后分析时 trace 有、截图没有。

## 8. 运行测试

```
cd G:\刷刷宝\Worktrees\prod-source-3904913-20260911
# 蹭车相关（~4 分钟）
G:\刷刷宝\GameScript-Local\.venv\Scripts\python.exe -m pytest tests/test_hitch_victory_merchant_20260912.py tests/test_hitch_postgame_20260912.py tests/test_hitch_bag_panel_20260912.py tests/test_hitch_ingame_bootstrap_20260911.py tests/test_hitch_liveness_20260912.py tests/test_hitch_live_chain_20260911.py tests/test_s0_l1_hitch_bounds.py tests/test_p1b0_post_game.py tests/test_public_bag_transfer.py -q -p no:cacheprovider
# 全量：tests/test_*.py 排序后分两半，顺序跑，每批 timeout 2400s；结束后确认无残留 python/pytest 进程。
```
