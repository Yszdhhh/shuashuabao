# G0 后段状态机与 P0 分阶段接线实施细则

**适用分支：** `codex/ocr-hybrid`  
**日期：** 2026-08-11  
**性质：** 仅设计与实施顺序；本文件不授权任何生产接线或功能启用。

## 摘要（≤300字）
G0 以已验证的锚点 Boss 两帧确认作为唯一 LONGZHU 入口；龙珠使用独立、不可续期的 300s deadline 与约 9s 扫描节奏，失败/断线抢占，到期必经 QUIT→回房闭环。秘境、传家宝、黑商/装备均逐模块、默认关闭且各有独立预算。P0 只在强面板锚点后把结构化候选交给纯 `choice_policy`；O4 仅 shadow。顺序固定为每类 shadow 100 个独立 episode→技能 LIVE 监督 30 个零误点→羁绊→宝物。当前冻结：盲测证据为 0/90，禁止接入 LIVE 或启用 G0。

---

## 1. 约束、现状和合法入口

### 1.1 范围与不可违反项

- **首发唯一分辨率：** 实际游戏窗口 `1600x900`。`960x540` 是 `NOT_APPLICABLE`，不得采集、缩放或作为门禁；其它分辨率不在首发验收范围（`SCOPE_OVERRIDE_1600X900_20260811.md`）。
- **输入纪律：** 每 tick 最多一次输入；所有改变 UI 的输入必须有前置锚点、后置画面变化或专用后置锚点、最大尝试次数、总期限和 incident。
- **全局抢占：** `STRONG_FAIL` 连续两帧与 `disconnect` 优先于所有面板、LONGZHU 和后段模块；`AMBIGUOUS_GIVEUP` 不是失败证据。
- **时限纪律：** `round_deadline` 在首次进入 `MAIN_LINE` 时固定；面板、神器、挑战、后段扫描都不得延期。每个后段 episode 另有独立 deadline，二者取先到者进入安全退出。
- **O4 边界：** OCR 只可在强面板锚点成立且模板低置信/unknown 时 lazy 调用；仅记录 trace，不改变动作、不产生坐标、不阻塞核心 FSM。
- **冻结语义：** 当前 `O3_BLIND` 合格 episode 为 `0`，盲测指标为 `N/A`；O3 的 99.48% 是标签辅助训练侧证据，不能变成盲测 PASS。故 O4 生产接线、P0 LIVE、G0 行为均为 **BLOCKED/FROZEN**。本文件描述解冻后的实施顺序，不构成 waiver；不得把 FAIL/BLOCKED 写成 PASS。

### 1.2 已有基线，实施必须复用

| 现有资产 | 已确认语义 | 对本计划的约束 |
|---|---|---|
| `Mediator.Phase` | 已有 `ANCHOR_BOSS`、`LONGZHU`、`RECOVER_FAILURE`、`QUIT`、`NEXT`、`COMPLETE` | 不新建通用工作流；在既有 phase handler 中加最小状态。 |
| S0 | `round_deadline`、面板 FSM、失败/断线恢复、`cycle_num`、回房验证、incident 已建 | G0 不重写 S0；只能调用其退出和 outcome 链。 |
| `choice_policy.py` | 纯函数 `PanelCandidates → PolicyDecision`；只返回有限动作和 slot index | P0 不允许策略读取帧、做匹配、持有会话状态或执行点击。 |
| OCR shadow | `shadow_predict(frame, panel_id, slot, ...) → ShadowResponse`，按 panel fingerprint 缓存 | P0 只能消费规范候选/置信度；unavailable 等同 unknown。 |
| `scenes.json` | `fail` 已限定为 STRONG_FAIL，`giveup` 已拆出，`disconnect` 独立 | 后段不能把 `giveUp` 或泛 `close` 重新并入失败/退出锚点。 |

### 1.3 当前代码缺口

1. `Mediator._tick_l1_tail()` 对 `EARLY_CHALLENGE`、`ANCHOR_BOSS`、`LONGZHU` 仍统一 Fail-Closed；`set_phase(LONGZHU)` 以 `max(archive_boss_time, boss_live_time, 180)` 设置 deadline，既非固定 300s 也未证明不可重入不刷新。
2. `src/gamescript/jobs/longzhu_job.py:LongzhuJob.step()` 调用继承链不存在的 `find()`、`click_match()`；它不是可修补的动作入口，必须在 G0-2 clean cutover 后移除导出和调用者，不能重新启用。
3. 当前尾段 `QUIT → NEXT → PREPARE` 已存在：确认退出后设置 `_awaiting_room_return=True`，`_tick_l0` 验证同一房间、更新 outcome/cycle 后才到 `ROOM_WAITING`。G0 只补齐后段来源、退出原因和跨局临时状态清理。
4. `HEIRLOOM_DIALOG` 和 `GREAT_RIFT_CONFIRM` 现有行为只是受限关闭/取消；`secret`、`boss_entry`、`archive` 仍是未验证入口并 Fail-Closed。`auto_gambling_time` 注释明确为未接线。
5. `Settings` 尚无 `policy_skill`、`policy_bond`、`policy_treasure` 和 G0 模块开关；已有 `round_timeout_s=900`、`find_longzhu_in_game=False`、`auto_secret_realm=False`、`auto_weapon=True` 不能视为 G0/P0 的 LIVE 授权。

---

## 2. 统一实施框架

### 2.1 后段模块包络

每个 G0 模块均实现为一个明确的 episode，状态至少含：

```text
started_at, deadline, attempts[action], next_allowed_at,
anchor_before, input_ok, mutation_seen, post_anchor_seen,
source_phase, exit_reason, panel_fingerprint
```

- `deadline` 仅在**首次满足模块入口锚点**时写入；相同 phase 的重复 `set_phase()`、面板操作、扫描命中、动作重试均不得改写。
- `attempts` 只在真正发出 UI-changing 输入后递增；观察/等待不增加预算，但到 deadline 必须退出。
- 每次输入将 `input_ok`、`anchor_before` 与输入后的 `FrameEvidence` generation 绑定；未观察到 mutation 或后置锚点时，不得推进下一动作。
- 模块超时、预算耗尽、未知页面、锚点消失超出观察窗：写 `incident`（module、source phase、deadline、attempt、anchor、last action、frame/ROI），随后走 `QUIT`；仅当 QUIT 自身无法确认才进入 `ERROR`。
- 凡关闭 feature flag：模块入口检测、状态推进、输入和模块 incident 均不发生；同 replay 与上一个稳定版本 action ledger 完全一致（允许仅版本元数据不同，不允许 action 记录增删改）。

### 2.2 退出优先级和 deadline 关系

每个局内 tick 的固定顺序：

```text
emergency/healthy-frame guard
→ STRONG_FAIL 两帧 / disconnect 抢占到 RECOVER_FAILURE
→ round_deadline 到期：record TIMEOUT → QUIT
→ 当前后段模块 deadline/attempt exhaustion：incident → QUIT
→ 当前 phase 的强入口/后置锚点
→ 最多一个经过授权的模块输入
→ 零输入观察
```

LONGZHU deadline 不是 `round_deadline` 的续期或替代：进入 LONGZHU 时固定为 `min(now + 300s, round_deadline)`；若 `round_deadline` 已更早到期，直接由 S0 的 TIMEOUT→QUIT 处理。LONGZHU 先到期时记录 `longzhu_timeout` incident 后 QUIT；不改变 S0 已记录的 round outcome。其它后段模块同理不得覆盖胜利/失败/断线/TIMEOUT outcome 的一次性记录权。

### 2.3 通用解冻门禁（逐模块、不可复用别的模块证据）

每个 G0 模块必须同时满足：

1. 至少 **10 个真实正 episode** 与 **20 个 hard negative**，均为 `1600x900`，episode 级去重并附素材 SHA、session、时间段、锚点和真值；
2. 对冻结 replay 集的入口/后置锚点召回 **100%**，误动作 **0**；
3. supervised LIVE **连续 5 次**完整成功，逐次有 action ledger、屏幕/ROI 证据和后置确认；
4. 实现独立 deadline、attempt budget、退出路径、incident，且 fail/disconnect 抢占测试通过；
5. 开关关闭时与上一稳定版 action ledger 等价；开关开启但未满足强入口时也为零输入；
6. 不把模拟 matcher、单测或 replay 当真实恢复/真实 LIVE 证据。

除模块门禁外，仍必须满足 `O3/O4/S0` 的全部解冻条件：冻结裁剪、独立 `1600x900` 盲测和真实模型 O4 压测有效；真实断线素材及恢复验证缺失时，后段不得宣称具备断线实机保障。

---

## 3. G0 实施细则（按唯一启用顺序）

### G0-1. 锚点 Boss 检测

| 项目 | 细则 |
|---|---|
| 改动文件 | `src/gamescript/mediator.py`；锚点 fixture/回放测试；必要时新增**特定** scene 条目和模板 manifest。不得把 `boss_entry` 泛模板直接授权为入口。 |
| 状态机 | `MAIN_LINE → ANCHOR_BOSS → LONGZHU`。`ANCHOR_BOSS` 仅代表“候选已出现、等待复核”，不是点击授权。保持字段 `_anchor_boss_candidate_stem`、`_anchor_boss_candidate_gen`、`_anchor_boss_confirm_frames`。 |
| 检测 | 仅在 S0 局尾检查窗/已验证战后过渡内，先命中 boss 名模板，再从模板 stem 解析配置目标。首个支持对象是原版证据中的 `07大法师阿鲁高` stem；配置值必须规范化后与已加载 boss 模板 stem 精确匹配。`boosIcon`、`cjbBoss`、`sgzxBoss`、文本相似或任意 boss 图均不能替代该匹配。 |
| 两帧确认 | 仅相邻、不同 `FrameEvidence.gen` 的两帧命中相同规范 stem、阈值和位置漂移都在 fixture 标定界限内，才计为 2。中间 miss、stem 改变、frame generation 重复、面板锚点出现或 fail/disconnect 都清零。第二帧确认时记录 `anchor_boss_verified` incident/trace，转 `LONGZHU`；不点击。 |
| 时序 | 入口锚点优先于 LONGZHU 泛色/模板扫描；同一 tick 的第二帧确认只转 phase，不能再扫描或点龙珠，下一 tick 才开始 LONGZHU observation。 |
| 门禁映射 | G0 通用门禁 + 10 正 episode 必须包含目标 stem 与非目标 boss；20 hard negatives 必须含 boss UI 相似、普通选择卡中的龙珠图、泛 `boss_entry` 命中、不同 stem、单帧闪现。 |
| 测试 | 同 stem 双帧进入 LONGZHU；单帧、不同 stem、重复 generation、位移越限、选择面板/强失败/断线均不进入；关闭开关时 phase/ledger 无差异。 |

### G0-2. LONGZHU（替换 Legacy `LongzhuJob`）

| 项目 | 细则 |
|---|---|
| 改动文件 | `src/gamescript/mediator.py`、`src/gamescript/settings.py`、与 LONGZHU 对应 tests/fixtures；删除 `jobs/longzhu_job.py` 的导出和全部调用者。不得把坏调用迁移成兼容 shim。 |
| 状态机 | `ENTERED → WAIT_SCAN_DUE → SCAN → WAIT_MUTATION → WAIT_SCAN_DUE`，任何时刻可被 `RECOVER_FAILURE`、`QUIT` 抢占；只允许由 G0-1 的 verified anchor 转入 `ENTERED`。禁止从 `MAIN_LINE`、`boss_entry`、`longzhu` 模板单独命中、恢复返回或直接 `set_phase(LONGZHU)` 获得动作权。直接 set phase 的测试/harness 应建立“无 verified anchor”状态并 Fail-Closed/QUIT，不能绕门。 |
| deadline | 首次进入写 `_longzhu_started_at` 和 `_longzhu_deadline = min(now + 300, _round_deadline)`（round deadline 为 `None` 时为 `now+300`）。重入 LONGZHU 不覆盖；面板 FSM、命中、刷新、扫描、点击均不延期。到期：写 `longzhu_timeout` incident、清 input/evidence token、`set_phase(QUIT, ...)`，无条件不再扫描。 |
| 扫描节奏 | `next_scan_at` 初始为进入后的观察帧；此后约 `9s`（配置可限定在 8–10s）一次。非 due tick 只检查强失败/断线/deadline/后置锚点，零输入。一次 scan 仅在专用 LONGZHU ROI、专用模板/目标上取一次证据；禁止每 tick `find_scene("longzhu")` 或全帧扫。 |
| 输入和后置确认 | 一次 scan 最多识别一个经专用锚点约束的目标，再发**一次**输入。点击后进入 `WAIT_MUTATION`，在固定观察窗内要求目标消失、计数/专用结果变化或明确 close/成功锚点；没有确认不再次点击，等待下一 scan；动作次数到模块预算时 incident→QUIT。目标候选不明确时只记录、等待下一 scan。 |
| 失败/断线 | `_tick_impl` 的 S0 抢占发生在 LONGZHU handler 前；恢复结束后按 S0 到 QUIT，不返回 LONGZHU，以免延长已失败局。`giveUp` 单独出现遵守 S0 ambiguous 语义。 |
| 门禁映射 | 额外验证总时限不可被 50 次 scan/面板动作续期；9s 采样不在每 tick产生输入；进入来源必须是 verified anchor。原版 200s 可作为行为观察，**不**作为上限：本地固定 300s 是安全上限，修复原版约 9.5 分钟无总上限的教训。 |
| 测试 | 入口来源、两帧锚点、300s 不可刷新、`round_deadline` 更早、9s 节流、mutation 成功/超时、attempt 耗尽、fail/disconnect 抢占、到期 QUIT、开关 ledger 等价；定向 test 必须证明旧 `LongzhuJob` 无导入/无调用。 |

### G0-3. QUIT → 回房 → 下一局闭环

| 项目 | 细则 |
|---|---|
| 改动文件 | `src/gamescript/mediator.py`、`tests/test_s0_safety_state_machine.py` 的扩展或 G0 专属回放/实机测试。 |
| 状态机 | 所有 G0 成功、模块到期和预算耗尽统一 `… → QUIT → NEXT → PREPARE(awaiting_room_return) → ROOM_WAITING`；仅 S0 已验证的“同一 KK 房间”锚点才解除 `_awaiting_room_return`。不得从 G0 直接去 `PLATFORM_MAP`、新建房、`MAIN_LINE` 或下一局开始。 |
| 时序 | `QUIT` 最多 3 次寻找/点击专用退出，再等专用确认；`NEXT` 最多 3 次确认；确认后启动回房 deadline。回房未验证到同一房间时 ERROR（零输入），不重建房掩盖错误。 |
| cycle/outcome | `game_count` 只在 S0 的确认回房点增加一次；`success_count/failure_count/timeout_count/disconnect_count` 仍由 `_record_round_outcome` 维护，完整胜利链才清 failure streak。到达 `cycle_num` 后转 `COMPLETE`，绝不点房间开始；后段临时字段在 `STAGE_SELECT` 新局初始化时清零，保留已记录 outcome。 |
| 门禁映射 | G0 通用门禁；5 次 supervised success 必须从模块入口到同房间验证完成，不可把“点击退出成功”计为闭环成功。 |
| 测试 | LONGZHU 到期→QUIT→NEXT→同房间→`ROOM_WAITING`；回房超时不重建房；`cycle_num=1` 不再开始下一局；同一局的重复尾段事件不重复计数。 |

### G0-4. 秘境（GREAT_RIFT）

| 项目 | 细则 |
|---|---|
| 改动文件 | `mediator.py`、`settings.py`、`scenes.json`（若需拆分新锚点）、专属 fixtures/tests。 |
| 状态机 | `MAIN_LINE` 内仅在 `auto_secret_realm` 与独立 `g0_great_rift_enabled` 均开时：`RIFT_OPTION → RIFT_VERIFY_ENTRY → RIFT_ACTIVE → RIFT_RESULT → QUIT/MAIN_LINE`。未实现或不确定状态一律 zero-input/Fail-Closed，不复用当前 `GREAT_RIFT_CONFIRM` 的“否”按钮为进入动作。 |
| 开局选项 | 仅凭专用“秘境可选”锚点与预期位置/配置的双证据，在同一 frame 确认后点击；点击后等待秘境 HUD/计数锚点。没有明确入口，维持主线，不点泛 `secret`、`kaogu` 或 `mijingOk`。 |
| 局内和失败 | `RIFT_ACTIVE` 只检测秘境专用 HUD、杀敌计数和结束结果；阈值取显式配置 `required_kills`，并以可验证计数文本/模板读数作为真值。结束时 `kills < required_kills` 记录 `great_rift_kill_shortfall` incident、标记失败 outcome（如尚未被 S0 记录）并 QUIT；达到阈值仍需结果锚点确认，不凭计数直接宣称成功。 |
| 预算 | 独立 `great_rift_deadline`、入口/确认/结果各自 attempt budget，均不可延长 round deadline；失败/断线抢占。 |
| 测试 | 入口双锚点、入口 click 后 HUD 确认、杀敌数边界 `required-1/required`、未知数字、结果缺失、超时、抢占、关闭开关 ledger 等价。 |

### G0-5. 传家宝

| 项目 | 细则 |
|---|---|
| 改动文件 | `mediator.py`、特定模板 manifest/fixtures（原版目录 `chuanjiaobao` 的 17 图）、`settings.py`、tests。 |
| 状态机 | `HEIRLOOM_ENTRY → HEIRLOOM_VISIBLE → HEIRLOOM_DECIDE → WAIT_MUTATION → RESUME/QUIT`。现有 `HEIRLOOM_DIALOG` 受限关闭逻辑保留为 feature-off 或无已验证任务的安全退出，不能被“自动选择”静默替代。 |
| 触发条件 | 仅在 `g0_heirloom_enabled`、明确传家宝入口模板、面板/槽位锚点和配置目标三者成立时进入。17 图须逐图建立规范 id、ROI、阈值、语义（入口/候选/确认/关闭），不得把目录存在当成已验证行为。 |
| 决策/执行 | 先精确匹配用户配置或明确排序规则；无安全候选只关闭/退出，不点击未知候选。每次动作有面板 fingerprint、次数和 deadline；点击后必须确认选中态/面板变异/结果锚点。 |
| 测试 | 每个目标模板至少正例；17 图的误归类负例；未知候选零点击；入口、确认、关闭、deadline、attempt、抢占、开关等价。 |

### G0-6. 黑商/装备使用

| 项目 | 细则 |
|---|---|
| 改动文件 | `mediator.py`、`settings.py`、专属 scene/fixtures/tests；按**黑商**和**装备使用**分别提交/启用，禁止同次 LIVE。 |
| 模块互斥 | 顶层 `PostgameModule = NONE | BLACK_MARKET | EQUIPMENT`；每次 run/feature rollout 只允许一个为 enabled，另一模块即使检测到锚点也 zero-input 并记录 shadow evidence。现有 `auto_gambling_time`、`auto_weapon` 只作为用户意图，不是动作授权。 |
| 黑商序列 | `MARKET_ENTRY`（专用入口）→ `MARKET_VISIBLE`（商品槽/余额或刷新锚点）→ `MARKET_DECIDE`（配置内物品且预算可验证）→ 单次 `BUY` 或 `REFRESH` → `WAIT_MUTATION`（余额/库存/面板变化）→ `MARKET_DONE`。任一未确认、价格/余额 unknown、目标不在配置、预算耗尽：`MARKET_EXIT → QUIT/MAIN_LINE`，不盲点购买。 |
| 装备序列 | `EQUIPMENT_ENTRY`（专用装备页）→ `EQUIPMENT_VISIBLE`（目标槽+当前装备）→ `EQUIPMENT_DECIDE`（仅配置内、可比较品质/套装字段）→ 单次 `EQUIP` → `WAIT_EQUIPPED`（槽位图标/属性/确认锚点）→ 返回。未知装备、比较字段缺失或确认失败均关闭/退出，禁止“先点再看”。 |
| 预算/测试 | 各自独立 deadline、买/刷/装备 attempt budget、金额/刷新次数预算；测试模块互斥、每次一输入、价格/字段未知零点击、mutation、失败/断线、deadline、关闭开关 ledger 等价。 |

---

## 4. P0 分阶段接线细则

### P0-0. 接线前置与所有权

P0 在 O4 shadow 已完成真实模型压力、off/shadow ledger 完全一致、冻结裁剪的独立 `1600x900` 盲测有有效证据后才可开始。当前只允许维护纯函数和离线/回放证据；**不得**修改 mediator 输入路径把 OCR 或 policy 接入 LIVE。

实施文件：`src/gamescript/mediator.py`（唯一运行时集成者）、`src/gamescript/choice_policy.py`（纯规则）、`src/gamescript/vision/ocr_shadow/client.py`（既有只读契约，除协议缺陷外不扩展为动作接口）、`src/gamescript/settings.py`、相应 tests/fixtures。每波只改一个面板种类的 LIVE 开关。

### P0-1. 精确接线点和执行边界

```text
_tick_main_line
  → _selection_anchor(frame) 成立
  → _classify_choice_panel(frame) 得到 skill|bond|treasure
  → 收集 template candidates / 可验证 rarity / set_progress / refresh_count
  → （模板低置信或 unknown 且 O4 shadow）shadow_predict 每个有效 slot
  → 归一为 PanelCandidates
  → choose_action(PanelCandidates, SessionState)
  → mediator 验证 feature flag、panel FSM 状态、deadline、fingerprint、slot anchor
  → 一次 act_click / 专用 refresh/giveup/close，或 WAIT
  → 等待 mutation 或后置确认并记录 trace
```

- 接线位于 `_selection_anchor/_classify_choice_panel` **之后**，置换现有 `_find_reward_choice` 的“候选扫描/选择”决策分支；不得绕过 `_tick_panel_fsm`、`act_click`、`ui_action_interval_s` 或 S0 的抢占顺序。
- `choice_policy` 仅消费结构化 `PanelCandidates` 与 `SessionState`，不可接触 `Frame`、matcher、`Settings` 可变对象、OCR client、时钟或 InputExecutor。
- 执行层将 `PolicyDecision.SELECT_SLOT.index` 映射到已由当前面板 anchor 校验的 slot ROI/中心；index 越界、slot 无有效前置锚点、unknown、过期 fingerprint 一律零输入并 incident/WAIT。
- `REFRESH`、`GIVEUP`、`CLOSE` 只能经该类型面板的专用受限按钮匹配；无对应按钮时不猜坐标。`WAIT` 与 `NONE` 不输入。

### P0-2. Shadow → policy 数据流与契约对齐

每一个 panel episode 在确认 anchor 后生成稳定 `panel_id` 与 `fingerprint`，slot schema 为：

```python
slot_request = {
    "slot_id": index,
    "bbox": (x0, y0, x1, y1),
    "kind": panel_kind,
}
response = shadow_predict(frame, panel_id, slot_request,
                          session=session_id, fingerprint=fingerprint,
                          panel_bbox=panel_bbox)
```

转换规则：

1. 仅 `response.status == "ok"` 的规范候选进入合并；`unavailable`、超时、崩溃、坏 JSON、空 candidates 均生成 `SlotCandidate(index, name=None, confidence=0, evidence="ocr:<reason>")`，不阻塞 tick。
2. 模板候选与 shadow 候选冲突时不得投票或取最高置信直接点：保留两份 evidence，标记该 slot `name=None`，交由 policy 的 unknown 安全路径。只有词典规范名一致、置信度满足 `PolicySettings.min_confidence`、slot 与当前 fingerprint 绑定，才生成可选 `SlotCandidate`。
3. `SlotCandidate` 必须含 `index/name/confidence/evidence/rarity`；`PanelCandidates` 必须含 `panel_kind/slots/set_progress/refresh_count/has_giveup/settings`。`set_progress` 只来自可验证字段，不能从 OCR 名称推测龙珠或套装进度。
4. `SessionState` 由 mediator 的 panel FSM 单独维护：`attempts` 统计已执行 select/refresh/giveup/close，`refreshes` 统计确认刷新，`waits` 统计连续观察，`deadline_exceeded` 在执行层先判定。policy 不修改它。
5. O4 shadow 阶段只写同一 trace 结构，绝不把 response 写入 `PanelCandidates` 的动作路径；P0 各类解锁后才按该契约启用对应 policy。

### P0-3. 低置信/unknown 的安全规则

| 面板 | 规则 |
|---|---|
| 技能 | 永不点击非预设技能；预设缺失时专用刷新，刷新耗尽后 GIVEUP/CLOSE。OCR unknown、模板低置信或冲突都视为非预设。 |
| 羁绊 | unknown 不得伪装成词典项；只对已规范化且置信满足阈值的预设、接近合成或品质候选决策。无安全候选按有限 WAIT→REFRESH→GIVEUP/CLOSE。 |
| 宝物 | 用户预设/可验证套装进度优先，再按配置品质；套装字段或名称 unknown 即不可选。无安全候选有限刷新/放弃，禁止无限等待。 |

`choice_policy` 已有 `PolicyAction` 有限枚举与确定性 tie-break。P0 集成不得新增“模型建议坐标”“任意首个槽”“F1 非预设兜底”等动作；技能在所有旗标组合下的非预设点击数必须为 0。

### P0-4. 开关、分期与回滚

新增独立、默认 `False` 的设置字段，读取/保存/校验必须显式纳入 `Settings`：

```text
policy_skill_enabled = false
policy_bond_enabled = false
policy_treasure_enabled = false
```

- 三者不是总开关的别名；每个只授权自己的 panel kind。任何未知值或配置缺失都回落 `False`。
- **首发顺序固定：** 技能 → 羁绊 → 宝物。技能未完成 30 个 supervised LIVE 零错误前，bond/treasure 均保持 false；bond 未完成前 treasure 保持 false。
- 每类先在 `1600x900` 完成 **≥100 个独立 panel episode** shadow；episode 以锚点出现到 mutation/关闭为单位，静态相邻帧不重复计数，记录 session/SHA/fingerprint，且 off/shadow action ledger 必须完全一致。
- 达到 shadow 门槛后，单独翻开该类 feature flag，在监督下完成 **≥30 个 LIVE episode，错误点击=0**，才允许下一类 shadow→LIVE。任一错误、ledger diff、未知直接点击、缺后置确认、deadline/attempt 违规均立即关闭该类 flag，归档 incident，回到上一稳定版本，不累计为通过。
- 关闭单个 flag 后，该类仍可进行 O4 shadow记录；其稳定模板路径 action ledger 必须等价。不得因关闭 skill 而让 bond/treasure提前获得动作权。

### P0-5. supervised LIVE trace 格式

每个 episode 写一条可关联 `episode_id` 的 JSONL 记录链；敏感字段延续 `_scrub_sensitive_keys` 规则。最小字段：

```json
{
  "episode_id": "session:panel-fingerprint:first-generation",
  "resolution": [1600, 900],
  "panel": {"kind": "skill", "anchor": "...", "fingerprint": "...", "generation": 123},
  "candidates": [
    {"index": 0, "template": {"name": "...", "confidence": 0.0},
     "shadow": {"status": "ok|unavailable", "candidates": [], "elapsed_ms": 0.0},
     "normalized": {"name": "...|null", "confidence": 0.0, "rarity": "...|null", "evidence": "..."}}
  ],
  "policy": {"input": {"refresh_count": 0, "set_progress": {}},
             "session_state": {"attempts": 0, "refreshes": 0, "waits": 0, "deadline_exceeded": false},
             "rule": "preset|synthesis|quality|unknown_safe_path",
             "decision": {"action": "SELECT_SLOT", "index": 1, "reason": "..."}},
  "execution": {"pre_anchor": "...", "input": "select_slot", "slot": 1, "accepted": true},
  "postcondition": {"observed": true, "kind": "panel_mutated|selected|closed", "generation": 124},
  "result": "confirmed|no_input|failed_closed"
}
```

这是“候选→规则→动作→后置确认”的可还原链。`WAIT`/`NONE` 也必须留下决策记录；没有 `postcondition.observed=true` 的 UI-changing action 不得计入 supervised success。

### P0-6. 验收映射

| 顺序 | 必须完成的证据 | 对应蓝图/范围门禁 |
|---:|---|---|
| 0 | O3/O4 解冻证据；1600x900 独立盲测；O4 off/shadow ledger=0；真实模型压测 | 蓝图 §11 O3、§11 O4；范围文件第 27–37 行；纠偏冻结语义 |
| 1 | skill shadow ≥100 独立 panel episode，shadow 仅 trace | 蓝图 §12、范围第 33–35 行 |
| 2 | skill supervised LIVE ≥30，错误点击 0；非预设点击 0；trace 完整 | 蓝图 §12 技能与验收门禁 |
| 3 | bond shadow ≥100，再 supervised LIVE ≥30，错误点击 0 | 蓝图 §12 羁绊与分阶段 LIVE |
| 4 | treasure shadow ≥100，再 supervised LIVE ≥30，错误点击 0 | 蓝图 §12 宝物与分阶段 LIVE |
| 全程 | 单测覆盖预设、unknown、刷新耗尽、品质、套装进度、tie-break；同输入同输出；有限动作+slot index；每 episode budget/deadline | 蓝图 §12 P0 验收门禁逐项 |

---

## 5. 测试、报告和交付顺序

### 5.1 每个实现任务的测试层次

1. **纯函数：** `choice_policy` 输入/输出表驱动测试；不模拟屏幕、不依赖时间。
2. **Mediator 回放：** 带 generation 的相邻帧 fixture，验证 phase、deadline、attempt、action ledger、trace 和 incident；覆盖 fail+panel、giveup+panel、断线、unknown、黑屏、退出确认、同房间回归。
3. **开关差分：** 对固定 replay 分别运行 feature off / shadow / 单模块 enabled；off 与稳定版 ledger 完全一致，shadow 与 off 完全一致。
4. **真实监督：** 1600x900、独立 episode、逐次 trace 和后置截图；只把完整闭环计入成功。

不得新增 XFAIL、降低阈值、删除失败样本、改变盲测分母或用模拟恢复冒充实机。性能测试还必须确认 LONGZHU 非 due tick 不做全帧高频扫描，且 shadow 超时不会将主 tick 拉至 >1s。

### 5.2 建议提交/启用边界

| 任务 | 单独改动边界 | 允许启用条件 |
|---|---|---|
| G0-1 | 锚点 Boss 检测与 tests | 通用门禁通过后才开启锚点观察；不自动开启 LONGZHU。 |
| G0-2 | LONGZHU FSM，删除 Legacy job | G0-1 + LONGZHU 独立门禁通过。 |
| G0-3 | 退出/回房闭环补齐 | G0-2 的 supervised 闭环证据通过。 |
| G0-4 | 秘境 | 独立正/负 episode 和门禁通过。 |
| G0-5 | 传家宝 | 17 图逐图映射和门禁通过。 |
| G0-6a/6b | 黑商 / 装备（分开） | 仅一个模块 enabled，分别通过门禁。 |
| P0-skill/bond/treasure | 每类一个接线与 flag | 前类 100 shadow + 30 监督零误点完成。 |

### 5.3 当前结论

**BLOCKED：** 当前允许交付本设计与离线/回放准备，不允许开启任何 G0/P0 LIVE。阻塞原因不是 960x540；该范围已 `NOT_APPLICABLE`。实际阻塞为独立 `1600x900` 冻结裁剪盲测尚无合格 episode（0/90）、O4 真实模型压测/解冻证据以及真实断线素材/恢复验证未完成。完成这些硬门禁后，仍必须严格按本文件的技能→羁绊→宝物和锚点 Boss→LONGZHU→退出/回房→秘境→传家宝→黑商/装备顺序执行。
