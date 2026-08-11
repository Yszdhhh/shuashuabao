# 局外主链 ui_scale / blue_button 权限审计（2026-08-12）

> 审计者：LOBBY-AUDIT（只读，未修改任何生产代码）
> 依据：`docs/CURRENT_STATUS_AND_HANDOFF_20260812.md` §3.2/§3.3（r6/r7）、外部审查 goal-objective.md 问题 4/5/6/7、`src/gamescript/mediator.py`、`src/gamescript/vision/matcher.py`、`src/gamescript/vision/stage_selector.py`、`config/scenes.json`、`tools/diagnose_lobby.py`
> 范围：平台页→建房→选关→PREPARE 全部局外页面；验收分辨率 1600×900；每 tick ≤1 输入（`_action_gate_ok` 已确认按 generation + `_input_seq` 强制）。
> 证据：代码走读 + 定向测试 `tests.test_lobby_detectors` + `tests.test_p0a_create_room_gate`（20 tests OK）+ 运行时实证（`_l0_scales`/`_adapt_scales` 排序反转）。

## 0. 结论摘要

1. **r6 同类遗漏：零残留**。所有由 `find_scene` 驱动的局外 KK 平台页面（地图页/建房弹窗/房间页）均已走 `_L0_GATE_SCENES` 绝对尺度路径（r7 已把 `map_create_room`、`create_room_confirm` 补入）。
2. **但发现 1 个新的尺度序 bug（P1）**：`_adapt_scales()` 末尾 `sorted()` 把 `_l0_scales()` 的"绝对 1.0 优先"顺序反转成升序，非 1.0 窗口（如 1328×945→0.83）下 L0 门闩会先扫 0.78/0.83/0.88 再扫 1.0。当前无假命中（r7 原帧回放仍命中 1.0），但违背 N2.4 文档序，且放大 early-stop 假阳性风险（r5/r6 误点同族）。1600×900 验收窗口不受影响（us=1.0 不合并）。
3. **blue_button 权限**：平台地图页创房**零蓝色权限**（r6 已修复并测试锁定）；**建房弹窗确认按钮仍保留 1 处 gated 蓝色兜底**（`_find_create_confirm`，小窗 ≤800×700 + 候选上方 ≥2 输入框），是"创房路径"内唯一的蓝色点击权——按字面验收标准需明示或移除。
4. **选关页主路径天然尺度自适应**（字形解析 resize-to-glyph + 相对 ROI），ui_scale 风险低；退出确认页走 hot scales，1600×900 下等于绝对 1.0，非 1.0 游戏窗待 960×540 实测（外部审查 Q9 未验）。

## 1. 局外页面清单

| 页面 | 模板（scenes.json） | 搜索尺度策略 | ui_scale 风险 | blue_button 点击权 | 建议 |
|---|---|---|---|---|---|
| KK 大厅/初始页（LOBBY_ROOM, `lobby_start`/`lobby_room`/`start`） | kk_start, lobby/room_start(_alt), startGameBtn | 生产 mediator **无 find_scene 调用点**（L0 成员闲置）；legacy auto_job 走 `match_any` 默认 scales（绝对 1.0，无 ui 邻域） | 低（生产不搜索） | 无 | 保留 L0 成员；legacy 路径无 ui_scale 适配，仅参考 |
| 平台地图页（PLATFORM_MAP） | `map_create_room`: lobby/create_room，**fallback=null** | `_find_map_create_room` → `find_scene` → **L0 绝对 1.0 优先**（r7） | **已修复**（1328×945/0.83 回归测试） | **零**（r6 移除；超时→ERROR 不点快速加入） | 无 |
| 建房弹窗（CREATE_ROOM） | `create_room_confirm`: lobby/create_room_confirm，fallback="blue_bottom_dialog_roi"（死配置） | 模板走 **L0 绝对**（r7）；模板未命中 → `_find_create_confirm` 蓝色兜底（小窗 ≤800×700 且候选上方 ≥2 输入框，`find_blue_buttons` ROI (0.25,0.72,0.90,0.99)） | 低（弹窗 584×488 固定尺寸；大窗/地图页因 width>800 被排除） | **有（1 处，gated）**：CREATE_ROOM 阶段 `act_click(confirm, "CreateRoom-confirm")` | 保留（语义门强：2 输入框=房名/密码表单）；建议补"大窗恒不走兜底"断言；素材齐后换小窗模板 |
| 房间页（ROOM_WAITING） | `room_start`: kk_start, lobby/room_start(_alt), startGameBtn，**fallback="blue_room_start_roi"（死配置，代码未实现）** | `_find_room_start` → `find_scene` → **L0 绝对** | 低（r7 已 L0；1040×719 fixture 1.0 命中） | 无（代码无任何蓝色兜底） | 建议把 config fallback 置 null，与 map_create_room 对齐（消灭误导性配置） |
| 选关页（STAGE_SELECT） | `stage_page`: stage/stage1-4；`stage_start`: lobby/stage_begin_btn, lobby/roomStart, lobby/startChallenge, startGameBtn；`stage`（alias） | 主路径 `_find_stage_page` = `visible_stage_rows` 字形解析（**resize-to-glyph 天然尺度自适应** + 相对 ROI x∈[0.62,0.72]w, y∈[0.12,0.88]h）；`_find_stage_target` 同解析器；`_find_stage_start` → **L0 绝对**；**遗留模板 fallback 直调 `find(..., scales=_hot_scales())` 绕过 find_scene/L0**（stage_page 的 L0 成员资格对该路径无效） | 低-中（主路径自适应；遗留 fallback 非 1.0 窗口依赖"游戏窗缩放渲染"假设；行高/灰度绝对阈值在低尺度窗口需 960×540 实测） | 无 | P2：统一路由（fallback 改走 find_scene 或删 L0 误导）；960×540 实测行解析 |
| 英雄模式弹窗（HERO_SETUP） | lobby/stage_hero_mode_btn, hero_modal_start/cancel, hero_kenrito_unselected, hero_level_zero | `find()` 默认 scales (1.0,)+`_adapt_scales` 邻域；**`_hero_reference_frame` 硬门=恰好 1600×900**，绝对像素位置门（1170-1270, 790-840 等） | 无（非 1600×900 直接 Fail-Closed 拒绝，见 `_tick_hero_setup`） | 无 | 无（Fail-Closed 是设计；勿移除参考帧门） |
| 退出确认弹窗（QUIT→NEXT） | lobby/exit_confirm_btn, lobby/exit_cancel_btn（scenes.json `exit_confirm`，代码硬编码 names） | `_find_exit_confirm` → `find(..., scales=_hot_scales(), roi=(0.38,0.50,0.50,0.68))` | 低：游戏窗 1600×900 → hot=(1.0,) 等价绝对；非 1.0 游戏窗按缩放渲染语义正确，**待 960×540 实测（Q9）** | 无 | 与 L0 集保持一致（可选）；960×540 实测 |
| 局内退出按钮（QUIT） | quit（`_find_game_exit`） | hot scales + ROI (0,0,0.12,0.15) | 同上（局内缩放渲染） | 无 | 960×540 实测 |
| 失败/断线恢复弹窗（RECOVER_FAILURE） | fail/disconnect/ok/close（find_scene，非 L0，带场景 ROI） | hot scales | 同上（局内） | 无（`_find_failure_exit_button` 是红/绿 HSV 组件+`fail` 模板锚+≥1000×600，非蓝色；1.4.11 失败弹窗专用） | 960×540 实测 |
| 挑战券为 0 考古切换（STAGE_SELECT 叠层） | lobby/ticket_zero | `_ticket_exhausted` 显式 scales=(0.9,1.0,1.1,1.2)（绝对带）+ 相对裁剪 | 低 | 无 | XFAIL 属素材缺失（ticket_zero_archaeology），与尺度无关 |

### 未覆盖但可能受 ui_scale 影响的页面/入口（需 960×540 或实机验证）

- **选关页遗留模板 fallback**（`_find_stage_page` 尾部，`find` 直调 hot scales）——游戏窗非 1.0 时依赖缩放渲染假设，无实测；
- **退出确认 / 局内退出 / 失败恢复弹窗**——全部 hot scales，非 1.0 游戏窗语义正确但全部未经实机验证（外部审查 Q9 即此）；
- **选关行字形解析的绝对阈值**（gray>180、行高>35 跳过、最小 run 8px）在 ≤0.6 尺度窗口的理论偏移；
- **legacy auto_job**（非生产 runner）所有 lobby 场景只按绝对 1.0 搜索，无 ui_scale 邻域——仅文档提及，不建议修复（mediator 才是生产路径）。

## 2. `_L0_GATE_SCENES` 成员逐一核实（mediator.py:948-953）

全部 13 成员：`lobby_start, lobby_room, map_create_room, create_room_confirm, room_start, stage_start, start, stage, stage_page, coin_challenge, wood_challenge, experience_challenge, treasure_challenge`。

| 成员 | 生产中 find_scene 调用点 | 是否真走绝对尺度（1.0 优先） |
|---|---|---|
| map_create_room | `_find_map_create_room`（3794） | ✅ L0 绝对（r7；1328×945 回归测试锁定） |
| create_room_confirm | `_find_create_confirm` 模板分支（3804） | ✅ L0 绝对（r7） |
| room_start | `_find_room_start`（3752） | ✅ L0 绝对 |
| stage_start | `_find_stage_start`（3755） | ✅ L0 绝对 |
| coin/wood/experience/treasure_challenge | `_is_in_game_hud`（504-508）、`_find_challenge_button`（2466） | ✅ L0 绝对（HUD 挑战开关；含 ui 邻域兜底） |
| lobby_start / lobby_room / start / stage | **无 find_scene 调用点**（仅 legacy auto_job 按模板名引用） | 成员资格闲置；若被调用会走 L0 绝对 |
| stage_page | **find_scene 无调用点**；真实现 `_find_stage_page`（3764）绕开 find_scene：主=字形解析（尺度自适应），遗留模板 fallback 直调 `find(..., scales=_hot_scales())`（3782） | ⚠️ 主路径自适应（非 matchTemplate 缩放搜索）；**遗留 fallback 不享受 L0 绝对优先**（见发现 P2） |

结论：**r6 同类遗漏（页面在非 1.0 ui_scale 窗口下搜错尺度）= 零残留**，前提是"由 find_scene 驱动的 KK 平台页面"。两个旁路（stage_page fallback、退出确认）不属于 r6 类（对象是游戏窗缩放渲染而非 KK 绝对资产），但需按发现 P1/P2 处理。

## 3. blue_button_color 调用点逐点清单

| # | 位置 | 角色 | context/phase | 点击权 | 理由/建议 |
|---|---|---|---|---|---|
| 1 | `vision/matcher.py:373-436` `find_blue_buttons` | **生产者**（HSV 轮廓→`blue_button_color` 候选） | 任意 | 无（返回值本身无动作权） | 保持 |
| 2 | `mediator.py:3811-3818` `_find_create_confirm` 蓝色兜底 | 唯一生产**点击权**消费点 | CREATE_ROOM：`act_click(confirm, "CreateRoom-confirm")`；PLATFORM_MAP：仅检测弹窗存在（3999-4008，不点击） | **有（CREATE_ROOM 内）** | 门：frame.width≤800 ∧ height≤700（小窗）∧ 候选上方 ≥2 输入框（房名/密码表单语义）。建议：(a) 增测试断言 1600×900/1328×945 大窗恒不走该分支；(b) 素材齐后以小窗专用模板替换；(c) 若按字面"创房路径零蓝色权限"验收，本点是唯一需移除/替换处 |
| 3 | `vision/matcher.py:439-464` `find_blue_button`（side=only/left/right） | 生产**无调用点**（仅测试引用） | — | 无 | 语义已收紧（地图 ROI 单候选拒绝）；建议保留为测试辅助或删除 |
| 4 | `tests/test_lobby_detectors.py:20-42` | 测试 | — | — | 锁定"地图页蓝色不授权"契约（`test_map_blue_fallback_rejects_one_ambiguous_candidate`、`test_match_any_has_no_global_blue_fallback`） |

**创房路径（PLATFORM_MAP→CREATE_ROOM）确认**：

- 平台地图页创建按钮：`_request_create_room`（3726）只接受 `_find_map_create_room` 返回值（`map_create_room` 模板、L0 绝对、config fallback=null）→ **零 blue_button 点击权** ✅；超时/未命中 → `ERROR "create room button not found"` 停机，绝不点快速加入（4039-4061）✅；
- 建房弹窗确认按钮：模板优先，**gated 蓝色兜底保留点击权**（上表 #2）⚠️；
- 每 tick ≤1 输入：`_action_gate_ok`（863）+ 滚轮手动 `_input_seq += 1`（4164-4169）✅。

其它颜色类点击权（非 blue，参考）：`_find_failure_exit_button`（3247，红/绿 HSV 组件 + `fail` 模板锚 + 窗≥1000×600，1.4.11 失败弹窗专用）——不在局外主链。

## 4. 选关页 / 退出确认页的 ui_scale 影响（外部审查 Q4/5/6/7 相关）

- **STAGE_SELECT**：主检测器 `visible_stage_rows` 把模板字形 resize 到观测字形尺寸再比对（`_classify_glyph`，stage_selector.py:131-150）→ **天然尺度自适应**；相对 ROI 列带 + 相对滚动点（`stage_list_scroll_point`=0.675w/0.52h）→ 非 1.0 窗口主路径仍可工作（理论；低尺度绝对阈值需实测）。`_find_stage_start` 为 L0 绝对 ✅。外部审查 Q4 的 STAGE_SELECT 误判（局内任务栏/Boss 倒计时命中字形）已由 `_compute_context` 中 `_is_in_game_hud` 前置裁决（532-535）+ MAIN_LINE 内守卫（5428）处理，与尺度无关。
- **QUIT 退出确认**：`_find_exit_confirm` hot scales——对游戏窗缩放渲染**语义正确**；1600×900 时退化为绝对 1.0。Q7（确认按钮无模板）已由 `lobby/exit_confirm_btn` 覆盖（离线回放通过）。非 1.0 游戏窗（Q9 的 960×540）未实测。
- Q5 giveUp/fail 评分波动：fail/giveup 场景走非 L0 hot scales + 场景 ROI（`_SCENE_ROIS`），1600×900 下等价绝对；波动治理属局内阈值/双锚点议题，不在本审计修复范围。

## 5. 发现清单（按优先级）

### P1（新增，推荐本轮修）：`_adapt_scales` 升序排序反转 L0 绝对优先序
- 位置：`mediator.py:718-732`（`return tuple(sorted(out))`，732）。
- 实证（ui_scale=0.83）：`_l0_scales()`=(1.0, 1.1, 0.9, 1.15, 1.2, 0.83, 0.78, 0.88)；经 `_adapt_scales` 后=(0.78, 0.83, 0.88, 0.9, **1.0**, 1.1, 1.15, 1.2)。`match_one(early_stop_scale=True)`（matcher.py:369-370）按尺度顺序首个过阈即返回 → 非 1.0 KK 窗口上 L0 门闩**先扫 ui 邻域后扫绝对 1.0**，与 N2.4 注释（"绝对 0.9-1.2 档主尺度优先"）相悖。
- 影响：① 违背文档序；② 每个非 1.0 tick 每个 L0 场景多扫 3 档（57-tick 卡死场景即此类）；③ **early-stop 假阳性面扩大**：忙碌 KK 页上 0.78-0.88 尺度的杂散命中会在 1.0 真命中之前被采纳——这正是 r5/r6 误点族。当前 r7 原帧无杂散命中故未发作，1600×900 验收窗 us=1.0 不触发。
- 修复：`_adapt_scales` 改为保序追加（去掉 `sorted`），或按 `|s−1.0|` 排序，或 L0 分支绕过 `_adapt_scales`（`_l0_scales` 已含邻域）。

### P2（低）：`_find_stage_page` 遗留模板 fallback 绕过 find_scene/L0
- 位置：`mediator.py:3782`（`self.find(..., scales=self._hot_scales(), roi=self._STAGE_ROWS_ROI)`），而 `stage_page` 同时在 `_L0_GATE_SCENES`（成员资格对该路径无效，属误导）。
- 影响：1600×900 无影响（hot=(1.0,)）；非 1.0 游戏窗依赖"缩放渲染"假设，未实测。
- 修复：fallback 改走 `find_scene(frame, "stage_page")` 复用 L0 路径（需小心 names 过滤语义），或移除 L0 成员并注释原因。

### P3（低）：config 死配置 fallback
- `config/scenes.json:130` `room_start.fallback="blue_room_start_roi"`、`:57` `create_room_confirm.fallback="blue_bottom_dialog_roi"`——全仓无代码消费（已实证）。room_start 的蓝色兜底**不存在于代码**（好事）；create_room_confirm 的代码内兜底与之同名但硬编码、不读配置。
- 修复：`room_start.fallback` 置 null（与 map_create_room 对齐，使"KK 页面零蓝色权限"在配置层显式）；create_room_confirm 保留字符串并在代码内加注释关联，或统一改为显式枚举。

### P4（低）：建房弹窗蓝色兜底（§3 #2）——按验收口径明示
- 若验收标准"创房路径（PLATFORM_MAP→CREATE_ROOM）无任何 blue_button 点击权限"为字面要求，则 CREATE_ROOM 弹窗确认的 gated 蓝色兜底是唯一不合规点。建议保留 + 补断言测试（大窗恒不走兜底、兜底必须 2 输入框），或素材齐后以小窗模板替换。

## 6. 修复建议（按优先级汇总）

1. **P1** `_adapt_scales` 保序（去 `sorted()`）或按距 1.0 排序 → 恢复 L0 绝对优先序；加一个 ui_scale=0.83 下单测断言 L0 顺序（绝对档先于 ui 邻域）。这是本轮唯一影响 r7 尺度保证正确性的代码序 bug。
2. **P2** stage_page 遗留 fallback 统一走 L0 路径或注释澄清。
3. **P3** `room_start.fallback` 置 null；对齐配置与代码语义。
4. **P4** 补建房弹窗蓝色兜底的负向断言测试（大窗零兜底）+ 决定保留/替换。
5. 后续：960×540 实机（Q9）验证选关行解析 + 退出确认 + 失败弹窗三组 hot-scales 路径。

## 7. 验收对照

- ✅ 局外页面清单齐全（§1，含"未覆盖但可能受 ui_scale 影响"清单）；
- ✅ r6 同类遗漏零残留（§2）；新增 P1（序 bug）不改变"1.0 在列表中→可命中"的事实，但需按 §5 修复；
- ✅ blue_button 权限逐调用点（§3）；创房路径：地图页零权限，弹窗确认 1 处 gated 权限（明示，P4）；
- ✅ 不提交、未修改生产代码（仅新增本报告文件）。

## 8. 证据

- `tests.test_lobby_detectors` + `tests.test_p0a_create_room_gate`：20 tests OK（0.377s，venv 实跑）；
- `_l0_scales`/`_adapt_scales` 排序反转：venv 实跑输出（§5 P1 实证）；
- 引用主干：mediator.py 948-953（L0 集）、955-972（_l0_scales）、718-732（_adapt_scales）、788-798（_hot_scales）、3752-3819（lobby finders）、3989-4067（PLATFORM_MAP/CREATE_ROOM handler）、2450-2458（_find_exit_confirm）、2687-2749（hero 门）、3247-3270（失败弹窗红绿按钮）；matcher.py 299-371（match_one early_stop_scale）、373-464（blue 生产者/helper）；stage_selector.py 173-303、387-392；scenes.json map_create_room/create_room_confirm/room_start/stage_start/stage_page/stage/exit_confirm。
