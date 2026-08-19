# GameScript-Local 全系统缺陷与冲突审计报告

- 审计对象：`G:\刷刷宝\Worktrees\GameScript-Core02-Core03-Integration-20260816`
- 审计日期：2026-08-17
- 审计方式：全量静态深读 + 交叉 grep 验证（mediator.py 6551 行、choice_policy.py、settings.py、main_window.py、runner_service.py、mode_catalog.py、capture.py、keyboard_mouse.py、emergency_stop.py、bond_capacity.py、choice_policy.json / mode_specs.json / default_settings.json / official_strategy_defaults.json / settings.py 全量对读）
- 结论速览：**Blocker 3 项 / Critical 10 项 / Major 13 项**。六大重灾区全部命中实锤，其中"英雄模式 0 声望回退"是**空实现（`pass`）**、"UR 进阶链注入"**只注入首尾两卡，中间环全部缺失**、"EX 必拿宝物 must_take_names"是**死配置**。

---

## 0. 问题总览

| 编号 | 级别 | 一句话 | 重灾区映射 |
|---|---|---|---|
| B-01 | Blocker | 英雄模式"今日0声望"检测是 `pass` 空实现，0 声望时无回退、全停 | #3 |
| B-02 | Blocker | 紧凑 G/F/V 面板处理器是死代码，面板常驻遮挡 HUD 与黑市 ROI | #1 |
| B-03 | Blocker | 自动任务 UNKNOWN 无超时无预算，整局零输入直到 900s 强退 | #1 |
| C-01 | Critical | `must_take_names` 死配置 + 特权名单硬编码，宝物优先级=边框色 | #2 |
| C-02 | Critical | `set_progress` 恒 None、`treasure_presets` 恒空，套装/龙珠优先级死代码 | #2 |
| C-03 | Critical | 属性线只注入 门卡+UR，秘法师/法神等中间环不进白名单，UR 永远合不成 | #4 |
| C-04 | Critical | `skill_archive_levels`/`lab_focus` 不是 Settings 字段，填了就丢 | #4 |
| C-05 | Critical | 进化/装备/黑商/OCR/物品栏全部 1600×900 硬门禁，非基准分辨率全部静默失效 | #1/#6 |
| C-06 | Critical | 硬白名单空刷烧木：`cards=[]` 默认 + `choice_interval` 未接线 → 每局白烧 ~2000 木 | #2 |
| C-07 | Critical | 英雄等级上限 1–5，与"关卡 N 分配 N 点（单系上限 10）"规格冲突 | #3 |
| C-08 | Critical | worker 线程猴补丁 `builtins.print`，进程级全局副作用 | #6 |
| C-09 | Critical | pyautogui FAILSAFE 未禁用，鼠标在角落时按 Z 直接抛异常崩掉整个 run | #6 |
| C-10 | Critical | `round_timeout_s=900` 硬期限 + TIMEOUT 计入熔断；mode_specs `budgets` 未接线 | #5 |
| M-01~M-13 | Major | 16 个死设置字段、3 个不可达 Phase、bond_capacity 未接 live、OCR 指纹 id() 复用等 | 全部 |

---

## 1. Blocker（致命阻塞）

### B-01 英雄模式「今日 0 声望」检测为空实现，无干净回退，直接全停

- **位置**：`src/gamescript/mediator.py:3506-3510`
```python
# 今日可获得声望检测：若检测到今日可得声望为 0，立即点击取消退出英雄模式，降级为常规模式
reputation_box = self._hero_roi(frame, (1000, 750, 1400, 880))
if reputation_box is not None:
    # 优先识别右下角可得声望数字
    pass
```
- **触发场景与复现链路**：
  1. `default_settings.json:27` 默认 `auto_reputation: true`、`reputation_level: 5`；
  2. 选关页高亮确认后走 `_begin_hero_setup`（mediator.py:4990-4991 → 3375）；
  3. 当天声望已领完（右下角"今日可获得声望点数 == 0"），点加号无任何效果；
  4. WAIT_MODAL 能通过（`_hero_initial_zero_confirmed` 只验证"未选中卡+0 级"模板，见 3338-3356，0 声望时恰好**更容易**通过），点击 plus → 进入 `WAIT_LEVEL_CHANGE`；
  5. 数字永不变化（`_hero_changed_pixels < 50`，3526-3529），`_hero_step_deadline`（`_hero_observation_timeout()` = 20–60s，3373）到期；
  6. `_hero_fail("英雄模式步骤 WAIT_LEVEL_CHANGE 超时")` → `set_phase(ERROR)` + `stop()` → **整个脚本停机**。
- **后果**：既没有"点取消退出弹窗"，也没有"降级为常规单人模式"；英雄弹窗残留在选关页上（连取消按钮都没点过）。每天声望领完后第一局必停机，且用户看到的只是"英雄模式步骤超时"。
- **修复方案（伪代码）**：
```python
# WAIT_MODAL 阶段，弹窗按钮确认后先做 0 声望判定（OCR/模板皆可）
if rep_today_zero_detected(frame):          # 右下角 ROI (1000,750,1400,880) 数字==0
    cancel = self._hero_modal_buttons(frame)[1]   # 已有 cancel 锚点 (3329)
    if self.act_click(cancel, "CancelHeroMode-NoRepToday"):
        self._hero_state = "IDLE"
        self.set_phase(Phase.STAGE_SELECT, "hero rep exhausted; fallback normal")
        self._hero_fallback_today = True     # 本日不再自动尝试英雄模式
    return LoopAction.Continue
# 兜底：WAIT_LEVEL_CHANGE 超时分支，不 _hero_fail，而是点 cancel → 回 STAGE_SELECT
```
配套：`_hero_fail` 增加 `degradable=True` 参数，凡英雄链失败一律先尝试点 cancel 清弹窗再决定停机/降级。

### B-02 紧凑面板处理器 `_handle_self_opened_compact_panel` 是死代码；G/F/V 紧凑面板常驻屏幕并遮挡黑市/物品栏

- **位置**：
  - 死代码本体：`src/gamescript/mediator.py:2817-2836`（`_handle_self_opened_compact_panel`）、`2800-2815`（`_find_compact_skill_choice`）；
  - 唯一调用点：`mediator.py:6300`（仅在 `_panel_state == CLOSED` 且无锚点时执行）；
  - 互斥根因：`mediator.py:5707-5713`（WAIT_VISIBLE 超时进入 COOLDOWN 时置 `_panel_opened_by_us = None`）与 `5696-5716`（OPEN_REQUESTED/WAIT_VISIBLE 期间 FSM 在 6253 处拦截返回 Continue）。
- **不变量推导（为何永远不可达）**：`_panel_opened_by_us ∈ {"skill","bond","treasure"}` 的全部赋值窗口内，`_panel_state` 恒为 OPEN_REQUESTED/WAIT_VISIBLE/ACTIVE/WAIT_MUTATION（均 ≠ CLOSED）；而 `_tick_main_line:6253` 的门闩 `selection_anchor is not None or self._panel_state != PanelState.CLOSED` 在这些状态下会把控制流全部交给 `_tick_panel_fsm` 并返回 Continue。等状态回到 CLOSED 时（COOLDOWN 到期 → `_finish_panel_episode`），`_panel_opened_by_us` 已被清为 None。因此 6300 处 `kind` 恒为 None，紧凑面板分支零执行。
- **触发场景与复现链路**：
  1. L1 循环 `_maybe_open_choice_panel` 点 G（`CHOICE_BUTTON_RATIOS["skill"]=(0.9025,0.867)`，2348-2352）；
  2. 游戏弹出的是右下角紧凑候选条（无中央 `_selection_anchor`，注释 6298-6299 自己承认存在此 UI）；
  3. FSM WAIT_VISIBLE 等 2s（`panel_visible_timeout_s=2.0`）→ COOLDOWN → `_finish_panel_episode` → 循环推进（`_panel_kind` 在点击时已写入，2481/2501/2519，所以**不会**永久卡在 skill——这点与"整条 L1 卡死"的猜想不同）；
  4. 但紧凑条**没人关、没人选**，常驻 (0.68–0.95, 0.62–0.80) 区域；该区域与黑市商人检测 ROI (0.70–0.94, 0.67–0.79)（`2712-2729`）和物品栏 ROI (0.64–0.77, 0.77–0.98)（`2650-2652`）**直接重叠** → 黑市绿色像素误判 / 买木点击被条遮挡；
  5. 下一轮循环再点 G 形成开-关抖动，紧凑选卡功能（含 `_find_compact_skill_choice` 的 0.45–0.60 缩放档扫描）完全不存在。
- **修复方案（伪代码）**：
```python
# 方案 A（推荐）：在 WAIT_VISIBLE 超时进入 COOLDOWN 前，先给紧凑面板一次处理机会
elif now >= self._panel_visible_deadline:
    compact = self._handle_self_opened_compact_panel(frame)   # 先尝试选卡/关条
    if compact is not None:
        return compact
    # 再走原有 COOLDOWN 收口，并且 COOLDOWN 前主动再点一次同 HUD 按钮关闭紧凑条
    self._panel_state = PanelState.COOLDOWN
    ...
# 方案 B：_panel_opened_by_us 清空动作从 WAIT_VISIBLE 超时分支挪到 _finish_panel_episode 统一处理，
# 并在 _tick_main_line 6253 门闩放宽为
#   if selection_anchor is not None or self._panel_state != CLOSED or self._panel_opened_by_us:
```

### B-03 自动任务（auto_task）UNKNOWN 状态无超时、无预算 → 整局零输入直到 900s 强退并累计熔断

- **位置**：
  - 全局门闩：`src/gamescript/mediator.py:6267-6273`
```python
auto_res = self._ensure_auto_task_enabled(frame)
if auto_res is not None:
    ...
if not self._auto_task_done:
    print("[L1] 尚未确认【自动任务】已开启，阻断四挑战和其他局内动作")
    return LoopAction.Continue
```
  - UNKNOWN 无出路：`mediator.py:1560-1642`。`_auto_task_state_detail`（1504-1528）在模板缺失（`auto_task_on/off` 文件不存在 → "UNKNOWN"）、ROI (0.85–0.95, 0.50–0.65) 未命中、双分数差 <0.06 时返回 UNKNOWN；`_find_auto_task_toggle`（1553-1558）仅对 OFF 给点击候选；`attempts>=3 → ERROR` 分支（1615-1620）**只有在真的点过 3 次**才会触发——UNKNOWN 时一次 attempt 都不消耗。
- **触发场景与复现链路**：非基准分辨率/模板资产缺失/右侧任务栏被 UI 遮挡 → state 恒 UNKNOWN → `_ensure_auto_task_enabled` 返回 None → 6271 门闩每 tick 拦截 → G/F/V、进化、装备、拾取、黑市、神器、四挑战**全部饿死**；唯一出口是 `round_deadline`（900s）→ `RoundOutcome.TIMEOUT` → `failure_streak+1`（4100-4108）→ 连续 3 局（`failure_streak_limit=3`）→ 彻底停机。用户观察到的"下游饿死、整条 L1 卡死"，这是最大单点。
- **修复方案（伪代码）**：
```python
# _ensure_auto_task_enabled 增加 UNKNOWN 总预算
if state == "UNKNOWN":
    self._auto_task_unknown_since = self._auto_task_unknown_since or now
    if now - self._auto_task_unknown_since > max(30, min(query_timeout, 120)):
        # 降级：视为已开启（放行下游），记录 incident，而不是让整局烂掉
        self._auto_task_done = True
        self._auto_task_degraded = True
        self._record_incident("auto_task_unknown_timeout_degrade")
    return None
# 并在周期复查中看到 ON 证据时清除 degraded 标记
```

---

## 2. Critical（高危逻辑冲突）

### C-01 `must_take_names` 死配置 + 宝物特权名单硬编码：EX 必拿不生效，消耗品与成长道具的优先级完全交给边框颜色

- **位置**：
  - 配置侧：`config/choice_policy.json:49-55`（`treasure.must_take_names = [ONEPIECE, 至高进化, 一身神装, 满级大佬]`，注释称"出现即优先拿，压过品质降级"）；
  - 代码侧缺口 1：`src/gamescript/choice_policy.py:141-215`（`PolicySettings` 无 `must_take_names` 字段，`from_mapping` 不读）；
  - 代码侧缺口 2：`src/gamescript/mediator.py:1810-1848`（`_policy_settings()` 组装 mapping 时也没有该键）；
  - 代码侧现状：`choice_policy.py:449-456` 硬编码特权仅 `"全都要" in name or "卡牌大师" in name`；
  - 唯一消费者是展示层：`main_window.py:133、1033-1058`、`atlas_view.py:1034+`（只画图标）。
- **后果（优先级排序冲突实锤）**：
  1. ONEPIECE/至高进化/一身神装/满级大佬 出现时**不会**优先拿；
  2. 龙珠（套装成长）、属性提升类永久道具没有任何特权路径（`treasure_presets` 恒空，见 C-02）；
  3. 最终裁决退化为 `_match_quality`（choice_policy.py:661-678）＝按边框品质色：一张红/橙边的**神符消耗品**会压过绿/蓝边的永久成长道具——正是用户提出的"神符 vs 龙珠/我全都要/卡牌大师"冲突，当前答案是"按颜色随机撞"。
- **修复方案（伪代码）**：
```python
# choice_policy.PolicySettings 增加字段
must_take_names: tuple[str, ...] = ()
# from_mapping 读取 raw["must_take_names"]
# mediator._policy_settings() 组装：
"must_take_names": tuple(treasure_cfg.get("must_take_names") or ()),
# _decide_collectible 特权层统一：
priv = {"我全都要", "卡牌大师", *settings.must_take_names}   # 单一来源，删硬编码
for slot in eligible:
    if slot.name in priv:
        return PolicyDecision.select(slot.index, f"宝物特权秒选【{slot.name}】")
# 神符/消耗品降权：给 SlotCandidate 增加 consumable: bool（识别层按词典标注），
# 排序键改为 (is_priv, not consumable, rarity_rank, index)
```

### C-02 `set_progress` 恒为 None、`treasure_presets` 恒空：套装接近合成（含龙珠）整条优先级链是死代码

- **位置**：`src/gamescript/mediator.py:2098`（`_ocr_reward_choice` 构造 `PanelCandidates(..., set_progress=None, ...)`）、`mediator.py:2230`（shadow 路径同样 None）、`mediator.py:1840`（`"treasure_presets": ()` 硬编码空）。
- **后果**：`_match_synthesis`（choice_policy.py:607-658）第一行 `if not prog: return None` 永远返回 None —— "差 1 张合成优先""龙珠进度来自可验证字段"这些设计在生产接线里从未生效；宝物层实际只有 特权(C-01) → 品质色 → WAIT/REFRESH/GIVEUP。
- **修复方案（伪代码）**：
```python
# 识别层最小实现：bond_bar_occupancy 已能数格子（2069-2081）；
# 龙珠进度可用 dragon_ball_count 设置 + 局内图标计数器维护一个 SessionState.set_progress：
progress = self._track_set_progress(kind, slots)   # 从 _choice_session 累积每局已拿卡名
decision = choose_action(PanelCandidates(..., set_progress=progress, ...))
# treasure_presets 接入 Settings（看板增加宝物预设多选），不再硬编码 ()
```

### C-03 看板属性线只注入"门卡+UR"两张，UR 进阶链中间环与 support 卡全部缺席 —— 用户问题 #4 的答案是"否"

- **位置**：
  - `src/gamescript/shell/main_window.py:1384-1397`（`_attr_line_tokens`：`for name in (row.get("gate"), row.get("ur"))` —— 只取首尾两项）；
  - `main_window.py:203-213`（`route_fetter_codes`：能展开完整 `chain`，**全仓库零调用**，grep 验证）；
  - `main_window.py:1416-1431`（`assemble_whitelist_cards`：basic pack 勾选 + attr tokens + advanced packs + scheme）；
  - 数据源：`config/official_strategy_defaults.json` `attr_routes.intelligence.chain = [智力, 秘法师, 法神, 湮灭者]`、`support = [法术, 魔能, 魔术, 魔法师, 元素师]`（力量/敏捷同构）。
- **触发场景与复现链路**：看板勾选"智力" → `settings.cards` 只新增 `zhili, yanmiezhe` 两码 → bond 白名单 hard（choice_policy.json:14-16）→ 三选一出现**秘法师/法神**时判定"白名单外不可选"（choice_policy.py:472-475）→ 刷新/放弃 → **法神×3 永远凑不齐 → 湮灭者永远合不出来**；support 卡（法术/魔能等高频法）同样全被硬禁。用户以为勾了流派就在走 UR 链，实际链路在第二环就断了。
- **次生断层**：`_on_attr_route_clicked`（1348-1350）不调 `_sync_bonds_from_scheme`，羁绊网格的已选显示与实际白名单不一致；`apply_settings_to_ui` 反推路线只认 4 个短码（1824-1831）。
- **修复方案（伪代码）**：
```python
def _attr_line_tokens(self):
    tokens = []
    for rid in selected_routes:
        route = ATTR_ROUTES[rid]
        for name in [*route["chain"], *route.get("support", [])]:   # 用现成 route_fetter_codes
            tokens.append(code_for_bond_name(name) or name)
    return dedupe(tokens)
# 同时 _on_attr_route_clicked 末尾追加 self._sync_bonds_from_scheme() 刷新网格显示
```

### C-04 `skill_archive_levels` / `lab_focus` 不是 Settings 字段：技能存档等级"填了就丢"

- **位置**：`src/gamescript/shell/main_window.py:1872`（`settings.lab_focus = ""`）、`1882`（`settings.skill_archive_levels = self.archive_grid.get_levels()`）——动态属性；`src/gamescript/settings.py:55-146`（dataclass 无此二字段）；`settings.py:183-185`（`_from_dict` 丢弃未知键）；`mode_catalog.py:96-100`（`asdict(settings)` 只序列化声明字段）。
- **链路**：UI 填等级 → `collect_settings_from_ui` 挂到动态属性 → `_write_user_bundle` → `asdict()` **静默丢弃** → 重启后 `getattr(settings, "skill_archive_levels", None)` 为 None → 网格回到"未知"。`skill_meta.json/skill_archive_unlocks.json` 支撑的"按存档等级做技能优先级"因数据不持久而完全无从谈起（用户问的"高等级奥术箭最高权重"现状：**不存在**，技能只按预设名+稀有度 tie-break，choice_policy.py:519-562）。
- **修复方案**：Settings 增加 `skill_archive_levels: dict[str,int] = field(default_factory=dict)`（含 int 值域清洗），`_from_dict` 增加类型校验；`lab_focus` 已在 `PERSIST_DENYLIST`，直接删除 1872 行的动态赋值。

### C-05 进化/装备/物品栏/黑市/OCR/词缀/进化双卡 全部 `== (1600,900)` 硬门禁：感知层有 ui_scale 适配，动作层没有

- **位置**（全部为 `(frame.width, frame.height) != (1600, 900) → return`）：
  - OCR 槽位：`mediator.py:1721`（`_ocr_panel_slots`）→ live 模式下 960×540 窗口选卡直接降级为"bond 立即关面板 / skill 刷 3 次后隐藏 / treasure 品质色"；
  - 装备槽占用：`2534-2540`；词缀四选一：`2543-2544`；进化双卡识别：`2582-2589`；黑市在场：`2712-2714`；羁绊栏非空（吃丹前置）：`2731-2734`；刷新金币：`2746-2748`；羁绊格占用：`2069-2081`。
- **对照**：模板匹配层明确支持 0.6x 窗口（`_adapt_scales`，951-970；注释自述 960x540=0.6x 场景）。结果是"找得到按钮、点得了面板，但进化/装备/黑商/吃丹/OCR 全部静默 no-op"——用户重灾区 #1 中 evolve/物品栏/黑市"被饿死"的边界条件：**任何非 1600×900 客户区**。且这些 no-op 无日志、无 incident，纯静默。
- **修复方案（伪代码）**：
```python
# 统一虚拟坐标系：所有像素 ROI/阈值写成 1600x900 基准比例（多数已是），
# 采样时先 warp/resize 到基准再判断，或按 ui_scale 换算：
def _at_base(self, frame) -> np.ndarray | None:
    if (frame.width, frame.height) == (1600, 900): return frame.bgr
    if self._ui_scale <= 0: return None
    return cv2.resize(frame.bgr, (1600, 900), interpolation=cv2.INTER_AREA)
# 门禁替换为 _at_base(frame) is not None；并在 None 时打一条 [WARN] 而非静默
```

### C-06 羁绊硬白名单空刷烧木：默认 `cards=[]` + `choice_interval` 从未接线 → 每局白烧 1800–2400 木材

- **位置**：
  - 默认空白名单：`config/default_settings.json:43`（`"cards": []`）+ `settings.py:93`；bat/CLI/测试夹直接 `Settings.load` 不经看板组装（看板路径会由 `assemble_whitelist_cards` 补 13 张基础卡，main_window.py:1416-1431）→ **同一产品两条路径行为迥异**；
  - 硬白名单全 miss 行为：`choice_policy.py:472-475` → `_no_safe_candidate`（494-513）＝WAIT×5 → REFRESH×3 → GIVEUP/CLOSE。bond 刷新按钮是"刷新40"（木材 40/次，mediator.py:1367 注释）；
  - 节流失效：`settings.py:100`（`choice_interval: int = 120  # 主动开面板的最小间隔（秒）`）——**grep 全仓库无任何消费**（仅定义与范围钳制）。L1 循环实际周期 ≈ 40–60s（G 2s + F 一个 episode 20–30s + V 同理 + 下游各 1 tick）。
- **量化**：15 分钟局 ≈ 15–20 个完整循环 × 每 F episode 3 次刷新 × 40 木 ≈ **1800–2400 木/局**，产出为零；V 面板每次 3 点刷新币同样空烧。这不是无限循环（有界），但正是"空刷破产"的机制本体。
- **修复方案（伪代码）**：
```python
# 1) 接线 choice_interval（mediator._maybe_open_choice_panel 顶部）
if kind != "skill" and now < getattr(self, f"_{kind}_next_cycle_at", 0):
    self._advance_l1_cycle()      # 未到间隔直接跳过该类面板
    return LoopAction.Continue
# 成功关掉一个 episode 后：self._{kind}_next_cycle_at = now + settings.choice_interval
# 2) 空白名单短路：choose_action 入口
if kind == BOND and not settings.bond_presets and whitelist_mode == HARD:
    return PolicyDecision(CLOSE, None, "空白名单：直接关闭，禁止刷新")   # 不烧 40 木
# 3) default_settings.json cards 给基础卡组默认值，与看板路径对齐
```

### C-07 英雄模式声望分配上限 1–5，与"关卡 N 分配 N 点、单系上限 10"规格冲突

- **位置**：`mediator.py:3378-3379`（`if not 1 <= rep_level <= 5: return self._hero_fail("英雄模式仅支持 1–5 级")`）；`main_window.py:813-814`（spinbox `setRange(1, 5)`）；`settings.py:86-88`（`reputation_level` 默认 1，范围钳制 `(1,10)` 但 GUI/mediator 双重限死 5）；`reputation_stage1/reputation_stage2/cjb/sgzx`（settings.py:87-89、33-35）全部 0 引用（死配置）。
- **冲突**：用户规格是"根据关卡 N 分配 N 点（单系上限 10）"——按关卡推导点数的逻辑**不存在**（无任何 `stage→rep` 映射），>5 直接 Fail-Closed 停机；默认目标 1-15（default_settings.json:4-6）在规格语境下需要 15 点，当前体系无法表达。
- **修复方案**：
```python
# mediator：把逐次点加号的循环上限从 5 放宽到 spec 上限（10），
# 分配策略独立成纯函数（与 FACTION_SPECS 解耦）：
def allocate_rep_points(stage_n: int, cap_per_line: int = 10) -> dict[faction, int]: ...
# GUI spinbox setRange(1, 10)；reputation_level 语义文档改为"本局分配点数"
# 或新增 auto_reputation_from_stage: bool + stage→points 映射表
```

### C-08 worker 线程猴补丁 `builtins.print`：进程级全局副作用

- **位置**：`src/gamescript/shell/runner_service.py:89-102`（`builtins.print = hook_print`）、`111-114`（finally 恢复）。
- **风险链路**：
  1. 运行期间**全进程**的 print（GUI 线程、PySide6 内部、第三方库、另一个 worker）都被劫持并 emit Qt 信号；
  2. `hook_print` 里 `"失败" in text` 等关键字决定日志级别，任何含关键字的库输出都会被标 error；
  3. 恢复时直接 `builtins.print = real_print`——若未来出现嵌套 start/并发 worker，恢复顺序互相覆盖；
  4. interpreter shutdown 阶段 emit 到已销毁的 QObject 有崩溃窗口。
- **修复方案**：删掉猴补丁。Mediator 增加 `log_hook: Callable[[str, str], None]` 注入（`print` 之外的第二通道），或用 `logging` + QtHandler 桥接（queue handler，线程安全）。

### C-09 pyautogui FAILSAFE 未禁用：鼠标停在屏幕角落时，一次按 Z（拾取）即抛异常崩掉整个 run

- **位置**：`src/gamescript/input/keyboard_mouse.py:382-389`（`press_key` → `pyautogui.press`）、`392-399`（`hotkey`）、`502-510`（`scroll` 先 `pyautogui.moveTo`）。
- **链路**：`_tick_main_line` pickup 步骤 `act_key("z", "Pickup-Z")`（mediator.py:6377）→ `executor.press_key` → `pyautogui.press("z")` → pyautogui 的 failsafe 检查发现光标在 (0,0) 等角落 → 抛 `FailSafeException` → `act_key` 无 try → `tick()` 只 `finally` trace 不捕异常 → `run()` while 循环外抛 → `MediatorWorker.run` 的 `except Exception` → "任务异常退出"。**不是 Fail-Closed，是未分类崩溃**，且 stop_signal/紧急停止语义全被绕过。
- **修复方案**：
```python
# keyboard_mouse.py 模块顶部（导入 pyautogui 处）
pyautogui.FAILSAFE = False        # 急停已有 Shift+F12 + StopSignal，双保险不靠角落
# 或最小侵入：press_key/hotkey/scroll 外层包 try except FailSafeException → ActionResult(False, "FAILSAFE")
```

### C-10 `round_timeout_s=900` 不可续期硬期限 + TIMEOUT 计入熔断 + 分模式 budgets 死配置

- **位置**：`mediator.py:3741-3745`（进入 MAIN_LINE 固定 deadline，注释"不可续期"）、`5907-5917`（到期记 TIMEOUT 转 QUIT）、`4084-4108`（TIMEOUT 计入 `failure_streak`）、`settings.py:121`（默认 900s）、`default_settings.json:59`；`config/mode_specs.json:27-29、84-86`（`budgets.round_timeout_s`：normal_farm 900 / gambling_wood 180）——但 `mode_catalog.py:90-93` 的 `apply_mode_overlay` **只应用 hidden_defaults，从不应用 budgets**。
- **冲突场景**：1-15 全清 + 秘境 + Boss 拉锯的真实战局 >15 分钟 → 5911 行强转 QUIT：Boss 未打完即退出，outcome=TIMEOUT，`failure_streak+1`；连续 3 局 → 4629-4633 全停。"秘境进入后重置 deadline"（6121-6122）是唯一续期点，普通长局没有任何合法延期通道（idle watchdog 与 hard deadline 分离的设计注释在 settings.py:113-120，但游戏真实时长的上界没有被建模）。
- **修复方案**：
```python
# 1) apply_mode_overlay 应用 budgets（mode_catalog.py）
for k, v in spec.budgets.items():
    if k in _SETTINGS_FIELDS: kwargs[k] = v
# 2) round deadline 增加"活跃证据延期"：局尾窗口内每看到新的强进展
#    （Boss 血条变化/新波次/选择面板），允许 deadline = now + tail_window（有上限次数）：
if self._round_tail_checks_active() and self._progress_evidence_fresh():
    self._round_deadline = min(self._round_deadline_cap, now + self.settings.round_tail_window_s)
# 3) TIMEOUT 是否计入 failure_streak 单独开关（超时≠失败，可能是配置错误）
```

---

## 3. Major（体验设计缺陷）

### M-01 16 个死设置字段 + 3 个不可达 Phase：配置面与执行面大面积脱节
- **位置**：grep 计数（mediator.py 引用为 0）：`auto_card, damage_increase_card, develop_priority, auto_close_main_line, close_main_line_time, auto_clean_interval, treasure_num, dragon_ball_count, kill_boss_num, new_room_every_times, continue_reputation, develop_time, auto_gambling_time, room_create_side, reputation_stage1/2` + `choice_interval`（C-06）；`Phase.EARLY_CHALLENGE/ANCHOR_BOSS/LONGZHU` 无任何 `set_phase` 调用（6403-6414 的 Fail-Closed 分支不可达，"提前挑战/锚点 Boss/找龙珠"功能整体缺席，仅 LONGZHU deadline 重置逻辑残留 3782-3786）。
- **修复**：加"配置消费守卫"——`tools/release_gate.py` 里对 Settings 字段做引用计数检查，未消费字段要么删除要么显式标注 `dead: true`；Phase 枚举删掉不可达成员。

### M-02 bond_capacity 决策引擎未接入 live 链路，看板文案与实现不符
- **位置**：`src/gamescript/bond_capacity.py`（完整"自由度=空槽+丹数"决策机）在 mediator/auto_job 中零 import；看板文案 `main_window.py:1006`："吞噬丹：满槽先吃丹→再黑商（bond_capacity）"。实际 live 路径是 `_maybe_use_inventory_item`（2650-2689）+ `_maybe_black_merchant`（2765-2798）的硬编码启发式：吃丹前置 `_bond_bar_nonempty`（只查一个 1600×900 ROI），且吃丹/英雄卡只在 equipment 步骤的访问里执行（每 L1 循环至多 1 丹 + 2 卡），高吞吐局丹会积压。
- **修复**：`_decide_collectible` 输入 `set_progress`（C-02）后接 `bond_capacity.decide()`；或至少把 `_maybe_use_inventory_item` 从 equipment 步骤解耦为独立周期动作。

### M-03 帧指纹缓存以 `id(frame)` 为键，存在地址复用回放旧 OCR 结果的正确性风险
- **位置**：`mediator.py:5213-5221`（`_trace_fingerprint_cache = (id(frame), fingerprint)`，弱持引无强引用）；被 `_ocr_panel_slots:1726` 用作 `panel_id` 的一部分（shadow OCR 缓存键）。旧帧对象每 tick 释放，新帧可能复用同一地址 → 命中旧指纹 → sidecar 返回**上一个面板**的槽位识别。
- **修复**：缓存持有 `(frame_ref, fingerprint)` 强引用比较 `is`，或直接以 `(hwnd, width, height, md5)` 每帧现算（md5 已在算，只是被 id 短路）。

### M-04 战后辅助弹窗重试上限被单帧分类漂移无限重置
- **位置**：`mediator.py:5922-5924`（`for dialog in self._aux_dialog_attempts: if post_game != dialog: attempts=0`）。传家宝/大秘境关闭点击 3 次上限，但分类器任一帧返回 None/PAUSED 即清零——闪烁场景下可无限重试关闭点击（有 round deadline 兜底，非死锁）。
- **修复**：计数衰减改为"连续 N 帧非该弹窗才清零"，或上限改为滑动窗口计数。

### M-05 `SessionState.attempts` 从不递增，`max_attempts=12` 抢占分支是死守卫
- **位置**：`choice_policy.py:348-353`（`attempts >= max_attempts → giveup/close`）；`mediator.py:1861-1888`（`_record_choice_session` 只同步 refreshes/waits，注释声称"成功点击后提交 attempts"但代码从未提交）。
- **修复**：FSM ACTIVE 点击成功处（5754 附近）`self._choice_session = replace(cur, attempts=cur.attempts+1)`。

### M-06 `_last_skill_panel/_last_bond_attempt/_last_treasure_attempt` 未在 `__init__` 初始化
- **位置**：`mediator.py:2466-2468` 首读；仅在 `set_phase(MAIN_LINE)`（3749-3751）创建。生产路径安全（该函数只在 MAIN_LINE 执行），但 benchmark/harness 直调 `_maybe_open_choice_panel` 即 `AttributeError`。
- **修复**：`__init__` 补三行 `= 0.0`。

### M-07 `_capture_print_window` 尺寸自证失败仍继续使用：坐标体系可能整体错位
- **位置**：`capture.py:522-529`（捕获尺寸≠client 尺寸时仅 print"不裁剪，先观察"）。窗口被遮挡走 PrintWindow 路径时若含边框/DPI 缩放，Frame.left/top 与 bgr 尺寸不匹配 → 所有模板/ROI 判定整体偏移，动作全部失准且无告警。
- **修复**：尺寸不一致时返回 `is_valid=False, error="size mismatch"`，交给 FrameHealth 的 Fail-Closed 路径处理。

### M-08 Fail-Closed 粒度过粗 + 固定像素偏移
- **位置**：`mediator.py:3217-3222`（挑战开关 3 次未确认 → **全停**）、`1615-1620`（auto_task 3 次点击失败 → 全停）；`3062-3072`（挑战点击点 = label.y − 42 **固定像素**，非基准分辨率下比例失真易连续 miss → 直接触发上述全停）。
- **修复**：开关类失败降级为"跳过该开关 + incident"而非停机；−42 改为 `int(label.h * k)` 比例偏移。

### M-09 `closeEvent` 在 worker 仍在运行时即释放 live.lock
- **位置**：`main_window.py:2066-2080`：`worker.wait(15000)` 超时后 `worker.wait(60000)` **不检查结果**就 `release_after_finish()` → 锁先于线程释放，另一 LIVE（lab CLI）可抢锁并发操作同一游戏窗口。
- **修复**：仅当 `not worker.isRunning()` 才 release；否则保留锁并提示。

### M-10 默认配置双标准 + 机器特定路径入库
- **位置**：`default_settings.json:43`（`cards: []`，见 C-06）与看板组装的 13 卡基础包不一致；`default_settings.json:71`（`ocr_repo_root: "C:/Users/10639/Desktop/..."` 开发者本机绝对路径进仓库默认值）；`ocr_mode: "live"` 作为出厂默认（依赖 sidecar 存在，缺失时全部选卡退化为 C-05 描述的行为）。
- **修复**：出厂 `cards` 与看板一致、`ocr_repo_root` 置空 + 首启向导探测。

### M-11 每 tick 大量 print 经信号洪泛 GUI
- **位置**：`mediator.py:928-933`（每 tick capture 行）、各决策行；`runner_service.py:91-100` 全量 emit。`txt_log` 有 1000 块上限（main_window.py:1021），但 **queued signal 本身**在长局中堆积（GUI 线程 200ms 轮询 + 逐条 append），内存与卡顿随局数增长。
- **修复**：日志加级别/采样（trace 级只进 JSONL 不进 GUI），或 log_emitted 改为批量缓冲（如每 500ms flush 一次 list）。

### M-12 英雄链中的死代码佐证与 `_hero_fail` 硬停
- **位置**：`mediator.py:3507`（`reputation_box` 计算后弃用）；`_tick_hero_setup` 所有异常分支都 `_hero_fail`（3358-3362）——包括"弹窗丢失/尺寸变化"这类可恢复抖动。结合 B-01，英雄链任何意外=全停。
- **修复**：异常分类：可重试（尺寸抖动→重新 WAIT_MODAL）/可降级（0 声望→cancel 回普通）/致命（才停机）。

### M-13 神器释放用固定 HUD 坐标点击而非 Q/W/E 键，无后置确认
- **位置**：`mediator.py:2383-2427`（`_maybe_fire_artifacts` 点 (0.753, 0.827+idx·0.069)），无点击效果验证、无按键回退；槽位空判据 `_slot_has_artifact`（2363-2381）饱和像素阈值 300 无分辨率换算（依赖 C-05 同一问题）。
- **修复**：优先 `act_key("q"/"w"/"e")`（键位语义稳定），保留像素判空；点击路径加 CD 后首帧确认。

### M-14 战后多锚点分类的顺序性误点击窗口
- **位置**：`mediator.py:2926-2932`：POST_VICTORY（continueGame 0.80）先于 HEIRLOOM_DIALOG 判定。若传家宝弹窗悬浮在胜利层之上且 continueGame 模板仍从缝隙命中，会先点"继续游戏"——点击落到弹窗上（同进程窗口，`_check_point_obscured` 的 `foreground_matches_target` 按 PID 放行，keyboard_mouse.py:61-73，不拦）。用户链条"传家宝关闭→时光之穴→NPC→大秘境"（6030-6132）整体存在，但该顺序耦合是隐性断裂点；`_post_game_pending` 30s 内未确认存档面板/广场即 ERROR 全停（6240-6248），NPC_HUB 需要 quit+HeroChallenge+damijing 三锚点同时命中（2950-2955），任一模板 miss 即走超时停机。
- **修复**：分类顺序改为"独占弹窗（传家宝/确认框）优先于可穿透层（victory）"；`_post_game_pending` 超时先降级为"回 QUIT 链"而非 ERROR。

---

## 4. 六大重灾区逐项回答（对照用户提问）

1. **L1 轮询饿死/阻塞**：G/F/V 点数用尽时**不会**永久卡死在前两步（`_panel_kind` 在点击时写入，WAIT_VISIBLE 超时→COOLDOWN→`_finish_panel_episode` 会推进循环，5601-5608）；真正的三个洞是 **B-02**（紧凑面板死代码+常驻遮挡）、**B-03**（auto_task 门闩整局拦截）、**C-05**（evolve/物品栏/黑商的 1600×900 硬门禁）。进化有 P0-2 后置确认与 3 次失败预算（6321-6366），边界完整；吞噬丹/英雄卡被限制在 equipment 步骤内（每循环 1 丹/2 卡，M-02）；黑市在场判定/买木/刷新有 15s/120s 节流（2765-2798），但同样受 C-05 门禁。
2. **选卡决策与硬白名单**：三卡全不命中时流程有界（WAIT5→REFRESH3→GIVEUP/CLOSE），**不是**无限循环；但配合默认空 `cards` 与未接线的 `choice_interval`（C-06）构成持续烧木。宝物层特权仅硬编码两张（C-01），龙珠/套装优先级死代码（C-02），神符 vs 成长道具由边框色裁决。技能层无等级/升级权重（C-04），只有预设名+稀有度。
3. **英雄模式**：N 点分配不存在、上限 1-5（C-07）；"今日 0 声望"是 `pass` 空实现，无回退、有残留弹窗、直接全停（B-01）。
4. **看板与底层数据断层**：流派注入**不完整**（UR 链中间环缺失，C-03）；存档等级不持久化（C-04）；基础卡包在看板路径生效但默认配置为空（M-10/C-06）；`budgets`/`choice_interval` 等配置未接线（C-10/M-01）。
5. **战后流转与超时**：传家宝→继续→存档→广场→秘境链条已实现且有界（5929-6132），断裂点在 M-14（分类顺序耦合、三锚点全命中要求、pending 超时即停机）；`round_timeout_s=900` 硬期限确实会在 Boss 未打完时强退并累计熔断（C-10）。
6. **线程/异常**：Qt 信号跨线程用法本身规范（LogSignal 在 GUI 线程创建、worker emit 为 queued）；真正的风险是 `builtins.print` 猴补丁（C-08）、pyautogui FAILSAFE 崩溃（C-09）、`closeEvent` 提前放锁（M-09）、OCR 指纹 id 复用（M-03）。`act_click`/`find_scene` 在分辨率变化下多数有 ui_scale 适配与 Fail-Closed 兜底（5275-5340），但动作层硬门禁见 C-05；窗口失焦由 `check_can_execute` 强制激活+遮挡检查（keyboard_mouse.py:150-239），防御良好。

---

## 5. 底层状态机流转重构建议

1. **三层解耦：感知仲裁 → 预算仲裁 → 动作执行**。当前 `_tick_main_line` 是 300+ 行的优先级瀑布（post_game → fail_gift → affix → evolution → panel FSM → auto_task → challenge → stage handback → 20s gate → compact → open panel → artifact → evolve → equipment → pickup → merchant → idle watchdog），任何一层 return 都可能永久屏蔽下游。重构为：
```python
@dataclass
class Step:                    # 每步显式声明预算，而不是散落的 next_at/attempts 字段
    name: str
    ready: Callable[[Frame], bool]
    run: Callable[[Frame], LoopAction]
    budget: Budget             # per_episode / per_round / cooldown 三元组
    degrade: DegradePolicy     |  # 超预算时 SKIP（记 incident）而非停机或无限等

class L1Scheduler:
    steps = [PostGameStep, RecoveryStep, PanelStep, AutoTaskStep(降级可), ChallengeStep, ...]
    def tick(self, frame):
        for s in self.steps:               # 固定序但每步有独立预算与降级策略
            if s.ready(frame):
                return s.run(frame)        # 单 tick 单动作不变量保留
```
   关键是把"停机"从默认值改为显式声明：只有 `DegradePolicy.FATAL` 才 `set_phase(ERROR)`。
2. **统一虚拟坐标系**：以 1600×900 为规范坐标系，Frame 建立时一次性 `warp` 或记录 `scale_matrix`，所有像素 ROI/阈值/固定偏移（含 −42 挑战偏移、神器槽、英雄 ROI）全部改比例表达，消除 C-05/M-08/M-13 的整类问题。
3. **配置单一来源 + 消费校验 gate**：`release_gate.py` 增加（a）Settings 字段引用计数（抓 M-01/C-06 死键）；（b）choice_policy.json 键与 `PolicySettings.from_mapping` 键集合 diff（抓 C-01）；（c）mode_specs `budgets`/`hidden_defaults` 键必须属于 Settings 字段且被 apply_mode_overlay 消费（抓 C-10）。
4. **面板会话 FSM 补两条迁移**：`WAIT_VISIBLE --timeout--> COMPACT_TRY`（B-02）与 `ANY --health/scale change--> RESET_BASELINE`；同时把 `_panel_opened_by_us` 的清理收敛到 `_finish_panel_episode` 单点。
5. **英雄模式改为独立子状态机 + 可降级终态**：`WAIT_MODAL → CHECK_REP_TODAY(新) → ALLOCATE(n) → START → VERIFY_INGAME`，所有异常终态先走 `CANCEL_CLEANUP`（点取消、确认弹窗消失）再决定降级/停机（B-01/C-07/M-12）。
6. **回合期限分层**：`hard_deadline`（防失控，可设 3600s）与 `soft_budget`（按模式 budgets 接线，活跃证据可续期）分离；TIMEOUT 单独计数不进 failure_streak（C-10）。
7. **线程纪律**：删除 print 猴补丁改 logging 桥（C-08）；`pyautogui.FAILSAFE=False` + FailSafeException 捕获（C-09）；closeEvent 的锁释放与线程退出强绑定（M-09）。

---

## 附录：验证方法备注

- 全部行号以 worktree `GameScript-Core02-Core03-Integration-20260816` 当前工作区为准（2026-08-17 读取）。
- "死配置/死代码"结论均经全仓库 grep 复核（`choice_interval`、`must_take_names`、`route_fetter_codes`、`reputation_stage*`、16 个 Settings 字段、`set_phase(Phase.EARLY/ANCHOR/LONGZHU)`、`bond_capacity` import）。
- B-02 的不可达性由 `_panel_opened_by_us` 全部写点（2480/2500/2518/5785/5790/5712/5832/6207/3669/3675/3748）与 `_panel_state` 门闩（6253）联合推导。
