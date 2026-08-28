# CODEX 实机 Run 1 诊断（2026-08-11）

**范围。** 只读诊断 `dist_ocr_shadow` 的 1600×900 实机 trace；未修改生产代码、配置或测试，未提交。约束维持：未知状态零输入、Fail-Closed、每 tick 最多一个输入。

**结论。** 本局的直接停止原因不是技能/羁绊/宝物等选择面板处理器，而是 `treasure_challenge` 在 1.10 秒内连续发送三次右键、始终未获得 ON 确认后按既定 Fail-Closed 规则进入 `ERROR`。这把 MAIN_LINE 截断在进入后 **5.55 s**；因此所有选择、战后挑战和退出均不可达。选择面板模板/ROI 在本 trace 中无阳性，但 trace 没有证据证明当时面板实际出现，不能据此判为 1600×900 检测失败。

---

## 证据基线

- Trace 文件共 222 个 JSONL record；下文以 **record/tick** 引用。`tick` 与 record 序号均从 1 递增。
- `tick 211`：`HERO_SETUP → MAIN_LINE`，`ts=1786430737.555`，固定 `round_deadline=1786431637.6`（900 s 后），`panel_state=CLOSED`。
- `tick 212–214`：三次 `click:auto_task_toggle`；`tick 215` 金币右键；`217` 木材右键；`218` 经验右键；`219–221` 宝物右键；均为每 record 一个输入。
- `tick 222`：`MAIN_LINE → ERROR`，`interrupt_reason=treasure_challenge attempt limit reached`，`game_count=0`，无 post-game/QUIT action。
- 进入 MAIN_LINE 至 ERROR 的 wall-clock 为 `1786430743.103 - 1786430737.555 = 5.548 s`；宝物三次输入跨 `1.099 s`。

---

## A. 选择面板零命中：判定为**先被时序/挑战门闩截断；检测失败尚未证实**

### 事实

1. `Mediator._tick_main_line()` 每 tick 先做 `_post_game_state()`，随后调用 `_selection_anchor()`；锚点存在才进入 `_tick_panel_fsm()`（`src/gamescript/mediator.py:4116-4118, 4226-4266`）。所以执行顺序没有绕过选择逻辑。
2. `_selection_anchor()` 对 1600×900 的已知按钮位置使用 `(0.20, 0.50, 0.80, 0.75)` ROI、阈值 `min(0.70, match_threshold)`、主尺度，只有 DPI 放大才宽尺度回退（`mediator.py:1029-1105`）。分类按钮 ROI 也被收紧（`1119-1136`）。
3. `tick 211–222` 的 `scenes`、`panel` 都没有 `selection_anchor` 或 choice panel 命中，且 `s0.panel_state` 一直为 `CLOSED`；但 trace 对 **match miss 不写候选分数或“屏幕上存在面板”事实**。这只能说明“当前模板未命中”，不能说明“面板当时已经可检测而 ROI 错了”。
4. 更关键的是，当锚点未命中时，自动任务和四挑战在选择/主动开面板之前执行（`mediator.py:4276-4308`）。`_ensure_challenge_buttons()` 每次右键都 `return Continue`，所以它可连续占有 tick（`1915-1921, 1979-1999`）。本局在 MAIN_LINE 的 5.55 s 内从未到达技能、羁绊、宝物、神器或进化分支。

### 判定

- **(a) 是本局功能零执行的已证实根因：**挑战设置在局初把运行提前终止，选择面板没有获得合理等待时间。
- **(b) 不是当前可证实根因：**1600×900 ROI/模板可能仍有问题，尤其 `_selection_anchor()` 的 y=50–75% 假定来自特定录屏；但现有 trace 无“面板可见且 anchor miss”的反例。不能据此修改 ROI 或降低阈值。

### 必需验证

1. 先完成 P0 挑战确认节流后，以同一 1600×900 窗口重跑，保留至少一个实际出现的技能、羁绊、宝物选择帧。
2. 对每种帧离线调用 `_selection_anchor()` 与 `_classify_choice_panel()`，记录命中名、score、ROI 和 scale；断言 anchor 非空且分类正确。将经脱敏/许可的 1600×900 原帧加入 fixture。
3. 若面板肉眼可见而 anchor 仍为空，才以该帧量测按钮中心，调整**单一**锚点 ROI/模板；不得先做全帧宽搜或阈值盲降。

---

## B. 宝物挑战右键三次失败：**确认状态机过快是已证实问题；模板/坐标是否错误未定**

### 证据与代码

| trace record/tick | 证据 | 含义 |
|---|---|---|
| 215 | `coin_challenge score=0.746`，右键 `(339,739)` | 低于宝物的分数仍可在下一帧被确认，score 不是“右键必然失败”的依据。 |
| 219 | `treasure_challenge score=0.825`，右键 `(568,739)` | 模板在阈值内稳定命中。 |
| 220–221 | score=0.810，向同一坐标再次右键 | 两帧间仅约 0.55 s；没有观察/settle 窗。 |
| 222 | attempt limit reached | 第三次发送后下一 tick 直接 ERROR；没有等待 UI 反馈。 |

- `_find_challenge_button()` 用标签位置派生图标点击点 `label.y - 42`（`mediator.py:1861-1877`）。
- ON/OFF 由标签上方 35 px ROI 的绿色像素计数决定：`>=30` 为 ON，`<10` 为 OFF（`1880-1908`）。这不是右键成功回执；trace 也未记录 `green_count`、label bbox 或右键后的像素变化。
- `_ensure_challenge_buttons()` 将输入发送成功只标记 `PENDING`，却不保存“等待确认至何时”；下一帧只要仍判 OFF 就立即重发，并在下一个 tick 检查到 `attempts >= 3` 后停机（`1979-1999` 与 `1934-1939`）。`Settings.ui_action_interval_s=1.5` 仅在面板 FSM 使用，挑战 FSM 未使用（`settings.py:123-126`；`mediator.py:3950-4065`）。

### 根因判定

- **确认逻辑缺少 post-click settle/观察状态，是确定缺陷。**三次动作没有给游戏或图像状态以可验证的响应时间，且浪费了三次有限重试预算。
- **“宝物模板/坐标错”目前未定。**宝物标签匹配分数高于成功金币的分数，不能支持“低 score 所致”；`act_right_click.ok=true` 只证明输入执行器发送成功，不证明游戏接受。需记录点击派生 bbox、绿色计数和点击后像素 mutation，再以实际帧区分：
  - 标签 bbox/图标 ROI 错位或点击后目标无变化 → 模板/坐标问题；
  - 图标变化而绿色计数仍 OFF/UNKNOWN → 状态识别阈值/ROI问题；
  - 两者均正确但游戏不响应 → 输入交互或游戏规则问题。

---

## C. 自动任务三点：**没有等待“勾选状态变化”的 pending 状态，造成重试过密**

- `tick 212–214` 在约 **1.065 s** 内连续点击同一 auto-task 控件；第三帧才被下一次 `_is_auto_task_enabled()` 判为 ON。每次 action 约 395–408 ms，说明 UI 读回发生在相邻帧而非等状态稳定。
- `_ensure_auto_task_enabled()` 的流程是“本帧读 ON；否则读 OFF；立即 click；下一帧重复”；没有 click time、pending state、最小观察期或状态连续帧条件（`mediator.py:1194-1224`）。
- `_auto_task_state()` 有双模板相对分数和 `0.72`/`0.06` 不确定门槛（`1159-1185`），但其结果未写 trace；因此无法判断前两帧是游戏尚未切换、模板读回滞后，还是 OFF/ON 临界误判。

**最小方向：**首次成功点击后只做零输入观察，直至达到 `ui_action_interval_s` 或明确 ON；若到期仍明确 OFF 才消费下一次重试。附加 trace 字段应记录 `on_score/off_score/state`，不改变 Fail-Closed 的三次上限。

---

## D. 战后挑战与退出：ERROR 前不可达；退出已实现，自动战后挑战未实现

### 本局可达性

`tick 222` 已 `stop()` 并进入 `ERROR`；`_tick_main_line()` 只有先识别 `POST_VICTORY`、完成继续游戏和后续页面确认，才转 `QUIT`（`mediator.py:4116-4184`）。故用户本局没有战后挑战或退出，是当前 ERROR 的结构性后果，不是 QUIT 分支未被调用的证据。

### 当前实现状态

| 功能 | 当前代码状态 | 结论 |
|---|---|---|
| 胜利→继续游戏 | 已实现，至多 3 次（`4143-4152`） | 可达，需实机模板验证。 |
| 存档面板 | 仅识别并关闭（`4154-4172`） | **未实现自动进入/挑战存档。** |
| 时光之穴/大秘境 | 仅识别确认框并点击“否”（`4203-4218`） | **未实现 `startChallenge` 或自动挑战。** |
| 传家宝 | 仅识别并关闭弹窗（`4186-4201`） | **未实现进入/选择/开始挑战。** |
| `EARLY_CHALLENGE`、`ANCHOR_BOSS`、`LONGZHU` | 没有 `set_phase()` 进入点；即使被外部置入也直接 Fail-Closed ERROR（`4342-4353`） | **状态机骨架，不是可用功能。** |
| 配置门闩 | `auto_secret_realm`、`auto_close_main_line` 等在 `Settings` 存在（`settings.py:72-75`）；现代 mediator 未引用自动秘境，旧 `jobs/auto_job.py` 有遗留点击逻辑 | 设置不等于当前 mediator 可达功能。 |
| 局内退出→确认→回原房 | 已实现：`QUIT` 找左上退出，`NEXT` 找确认，成功后 `PREPARE` 且 `_awaiting_room_return=True`（`4359-4397`；回房由 L0 分支处理） | 正常胜利链到 NPC_HUB 后可达。 |

因此，“结束后没有退出”在本局由提前 ERROR 解释；“自动挑战存档/时光之穴/传家宝”即使局内恢复正常也仍是**真实功能缺口**。

---

## E. STAGE_SELECT 稳定复核：**确有过严风险，但本局已自恢复并继续英雄链**

- Trace 中 `tick 174` 首次 `SelectStage-target`，`tick 182` 再次点击，`tick 186` 成功 `OpenHeroModeModal` 并最终到 MAIN_LINE；所以本局的复核拒绝是额外延迟/重复点击，不是最终停止原因。
- `verify_stage_selection()` 要求目标行亮度显著高于相邻行（`stage_selector.py:311-384`），但 mediator 已注释实机列表没有可靠的持久高亮。其 fallback 又要求点击前后的目标**同名、坐标偏差 ≤6 px、相邻连续、开始/英雄入口存在**（`mediator.py:3291-3322`）。
- 点击选中后列表自动滚动、重排或行高动画会使同一 `1-14` 合理地超过 6 px；此时“同坐标”不是安全语义，而是脆弱的视觉偶然条件。

**判定：**应移除/放宽“点击后同坐标 ≤6 px”作为必要条件，保留更强的语义证据：同一目标标签、连续相邻行、专用开始/英雄入口、以及点击后短 settle。不得因为本次最终成功而忽略其误拒风险。

---

## 最小修复方案（施工顺序）

### P0 — 先解除 5.55 秒内的挑战门闩

| 改动文件 | 方案 | 必须测试 |
|---|---|---|
| `src/gamescript/mediator.py` | 给 auto-task 和每个 challenge 增加最小的 `pending_since`/`next_observe_at` 状态。成功发送输入后，在 `ui_action_interval_s` 内只重读、零输入；明确 ON 立即完成；明确 OFF 且观察窗到期才重试。维持固定顺序、每 tick 最多一个输入、三次上限和最终 Fail-Closed。 | 扩展 `tests/test_p1a2_challenge_controls.py`：FakeClock 下验证 1.5 s 内无第二右键、三次未确认仍 Error、ON 在等待期内立即完成、单 tick 最多一个输入。新增 auto-task 等待测试。 |
| `src/gamescript/mediator.py`（trace payload） | 每次 auto/challenge 判断写入 `state`、on/off score 或 `green_count`、label bbox、derived click point、pending age。只记录已有识别值，不增加输入。 | JSONL schema 回归：OFF→click→pending→ON 和 OFF→settle→retry 的字段/顺序可解析。 |
| 实机 1600×900 验收 | 用相同窗口做一局；检查同一 toggle 输入间隔 ≥1.5 s，宝物在三次预算耗尽前至少有观察期，且运行越过挑战设置并产生后续 MAIN_LINE tick。 | trace 断言：无 `attempt limit reached` 于首个观察窗内；每 record `actions` 长度 ≤1。 |

### P1 — 用真实 1600×900 面板与选关动画校准

| 改动文件 | 方案 | 必须测试 |
|---|---|---|
| `src/gamescript/mediator.py`、新增许可的 1600×900 fixture | 先用真实技能/羁绊/宝物帧验证 anchor/classifier。仅当“肉眼可见+anchor miss”复现时，按量测值调整 `_selection_anchor()`/`_PANEL_BUTTONS_ROI` 或补专用模板；不做全帧搜。 | 每种面板 fixture 断言 anchor、panel kind 和首个选择动作；无面板 HUD 断言 anchor 为 None。 |
| `src/gamescript/mediator.py`、`tests/test_stage_selector.py` | 以同名目标+相邻连续+专用入口为主确认；允许点击后的正常列表位移，保持 settle 和错误关卡拒绝。 | 构造目标移动 >6 px 但语义证据完整时开始；标签变化、邻行不连续或入口缺失时零输入拒绝。 |

### P2 — 明确实现战后挑战，不把“关闭弹窗”宣称为自动挑战

| 改动文件 | 方案 | 必须测试 |
|---|---|---|
| `src/gamescript/mediator.py`、`config/scenes.json`、必要的 `settings.py` | 基于每个真实战后页面录制，分别实现“入口确认→目标选择→`startChallenge`→转场/局内 HUD确认”的有界 FSM。存档、时光之穴/大秘境、传家宝各自独立；任一步 UNKNOWN 零输入，超时/错误 Fail-Closed。完成挑战链后才到已有 QUIT/NEXT。 | 每个 FSM 的 success、模板缺失、错误目标、确认超时、重试上限；全链路 victory→challenge→HUD/return→QUIT→NEXT→same room。 |
| `src/gamescript/mediator.py` | 仅在 P2 的每条前置和实机帧都验证后，加入到相应 phase 的 `set_phase()`；删除当前“存在但不可达”的误导性路径或保留为明确 disabled gate。 | 静态可达性测试：启用配置时有唯一进入点；未启用时不扫描/不输入。 |

---

## 是否必须实机再跑

**必须。** P0 修复后的 1600×900 再跑是区分“选择面板未出现（时序）”与“出现但 anchor ROI/模板失配”的唯一充分证据。当前 trace 已足以先修挑战确认节流；不足以安全修改选择面板阈值、ROI、宝物点击坐标或战后入口逻辑。

## 约 300 字摘要

本局不是六类局内功能同时失效，而是在 MAIN_LINE 仅 5.548 秒时被宝物挑战三次未确认直接 Fail-Closed。212–214 tick 又在约 1.065 秒内三点自动任务，说明两个 toggle FSM 都没有点击后的观察窗口；`ui_action_interval_s=1.5` 已存在却未用于挑战。宝物 0.810–0.825 的匹配高于成功金币 0.746，不能归咎于低 score；trace 仅证明右键已发送、绿色 ON 未读到，尚不能区分坐标、游戏响应或绿色判定错误。选择 anchor 在每 tick 都有机会运行但没有命中，且本局没有“面板确实可见”的证据，因此应先修 P0 并实机复跑，而非盲改 ROI。战后方面，胜利继续、关闭存档、关闭传家宝、取消大秘境、QUIT/NEXT 已有代码；存档/时光之穴/传家宝自动挑战和 `startChallenge` FSM 实际未实现，三个战后 phase 也不可达/Fail-Closed。选关复核本局最终恢复，但同坐标≤6 px 会误拒列表正常位移，列为 P1。