# Boss 后置契约只读审查（2026-09-22）

- **判定：HOLD**
- 范围：只读审查；不改业务代码、不跑完整门禁、不启动游戏
- 依据输入：
  - G:\刷刷宝\_facts_20260922\mechanics_solo\BOSS_VISUAL_ACCEPTANCE_20260922.md（已完整读取）
  - G:\刷刷宝\_facts_20260922\mechanics_solo\BOSS_HISTORICAL_RECHECK.md
  - G:\刷刷宝\Worktrees\boss-challenge-20260922\docs\BOSS_CHALLENGE_20260922.md
  - G:\刷刷宝\Worktrees\boss-challenge-20260922\src\shuabao\mediator.py（与 GameScript-Local 同源后置逻辑）
- 本轮 **同意撤回**旧掉落结论；不再坚持。见 §A。

---

## A. 原帧证据（n=8，主架构直查 + 本审查 SHA/数值代理交叉）

### A.0 文件同一性

| 帧 | 完整路径 | SHA-256 | n |
|---|---|---|---|
| REF f0310 | C:\tmp\shuabao-captures\hitch_lobby_chain_20260922_002105_993691\frames\f0310_action_after.png | 48edd9417e9d2c2af2a80c547bdb00c93a74ef3c85f9485f79ca74729f60c2c7 | 1 |

**与主架构给定 SHA256 一致** → 双方看的是同一文件。旧报告若写「f0310 有掉落条目+击杀BOSS」，在**该哈希文件**上不成立；本审查 **撤回**旧报告 §1.3/§1.4 中「掉落弹窗/击杀BOSS 已证实」表述。不把「当前看不到」推断为伪造或文件被替换。

### A.1 逐帧直接可见事实（经视觉验收文档核对，本审查数值代理交叉）

| 样本 | 原帧 | manifest event | 直接可见 | 数值代理（本审查） | 不能推出 |
|---|---|---|---|---|---|
| 参考 | ...\002105_993691\frames\f0309_action_before.png → 0310_action_after.png | 002105 包 | before 右侧列表开；after 右侧列表关、存档八卡仍在；**未见**掉落弹窗/「击杀BOSS」 | right_blobs 3→0，full_diff 5.52 | 不能说掉落弹窗替换列表、不能说挑战成功 |
| S1 tick403 | ...\004851_422384\frames\f0300_action_before.png → 0301_action_after.png | **e0198** at_s 992.469，target 18瑟莱德丝公主，point [1313,376]，input_success=True，postcondition.observed=False | before 列表及公主卡可见；after 列表消失，存档八卡仍在；**未见**掉落弹窗 | right_blobs 4→0，full_diff 5.48 | 不能说掉落/受理/成功 |
| S2 tick2778 | ...\frames\f2390_action_before.png → 2391_action_after.png | **e1492** at_s 7074.016，target 18瑟莱德丝公主，point [1313,373]，input_success=True，postcondition.observed=False | before 列表+公主卡可见；after 列表消失，存档八卡仍在 | right_blobs 2→0，full_diff 7.55 | 像素差/连通块归零 **不能**当掉落/受理证据 |
| S3 tick725 | ...\frames\f0650_action_before.png → 0651_action_after.png | **e0418** at_s 1780.0，target 17年兽，point [876,548]，input_success=True，postcondition.observed=False | **before 年兽卡清楚可见**；after 年兽卡有亮边框，列表仍在 | full_diff 0.46（几乎不变） | 亮边=悬停/选中，**不能**证开战/胜利；**不能**外推六次兜底时的解锁状态 |

补充帧（同链，未计入 n=8 目视主证据）：S2 空滚 2392_action_before.png→2393_action_after.png；S3 关闭前 0652_action_before.png。

### A.2 撤回与保留

| 旧表述 | 处置 |
|---|---|
| f0310「掉落瑟莱德丝之眼/剑师护手…+击杀BOSS」 | **撤回**（同一 SHA256 文件上未见） |
| 「列表关闭=挑战已受理」 | **撤回**为证据不足 |
| 「点击输入成功后列表关闭，旧链随后仍滚动」 | **保留**（输入+列表关闭+空滚，证据成立） |
| 「与 f0310 同根因=成功被误判」 | **撤回**；改为「点击后列表关闭（原因未知）+旧链空滚」 |

---

## B. 代码审查：_time_cave_boss_result_visible 与两处调用

代码位置：G:\刷刷宝\Worktrees\boss-challenge-20260922\src\shuabao\mediator.py（HEAD 含 027a8f4；与主目录 9ed8b52 同逻辑）。

### B.1 事实分层（禁止混用）

| 层级 | 当前证据能否证明 | 证据 |
|---|---|---|
| 1. 输入被接受（SendInput ok） | **能** | manifest input_success=True / trace ok=True |
| 2. 列表关闭（卡片 ROI 无卡） | **能**（双帧） | _time_cave_boss_result_visible 仅此语义；blobs→0 |
| 3. 业务受理（游戏接受挑战） | **不能** | 无掉落/无「击杀BOSS」/post_confirm=null/postcondition.observed=False |
| 4. 挑战成功（击杀/胜利） | **不能** | 本包无战果 HUD/结算 |

### B.2 结论：列表关闭 **不足以** 设置 
esult_confirmed

- 函数 _time_cave_boss_result_visible（**8435–8458**）：双帧 _find_visible_post_game_boss_cards 为空 → True。**只证明卡片识别为空**。
  - 双帧空也可能是识别失败/遮挡（docstring 8438–8442 仍写「掉落弹窗替换+击杀BOSS」，**与原帧不符，应更正注释**）。
- 调用点 1 _maybe_challenge_configured_boss（**8099–8103**）：True → _time_cave_boss_done=True **且** _time_cave_boss_result_confirmed=True。
- 调用点 2 _tick_impl ARCHIVE_PANEL（**17262–17266**）：同上，日志 **17263**「确认挑战受理」。
- 超时路径（**8104–8114 / 17267–17278**）→ unconfirmed + incident，合理。

**判定**：停止空滚/UI 收敛 ← 列表关闭 **足够**；
esult_confirmed/「挑战受理」← **证据不足（OVERCLAIM）**。

### B.3 最小修改建议（本轮不实施）

1. **拆语义**（最小、行为几乎不变）：
   - _time_cave_boss_result_visible 更名或 docstring 明确为 _time_cave_boss_list_closed（列表关闭=停止空滚）。
   - 两处调用：列表关闭时 _time_cave_boss_done=True + 记 list_closed=True；**不要**置 
esult_confirmed=True；日志改为「列表已关闭，停止重复定位」。
   - 保留 _time_cave_boss_confirm_unconfirmed 超时路径。
   - 注释 8438–8442 按原帧改为「点击后列表关闭（未观察到掉落/击杀文本）」。
2. **可选加强**（仍最小）：
esult_confirmed 仅当出现正向业务锚（掉落条/「击杀BOSS」/战果 HUD）才 True；否则超时保持 unconfirmed。
3. **影响范围**：mediator.py 8435–8458、8099–8116、17257–17281；及测试中依赖 
esult_confirmed=True 的断言。
4. **应调整的测试**（worktree 	ests/）：
   - 	ests/test_boss_challenge_20260922.py：	est_time_cave_result_visible_after_click → 断言 **列表关闭/done**，**不断言** 
esult_confirmed；新增「无业务锚不得 confirmed」。
   - 	est_no_scroll_after_click_on_replaced_list：保留「零滚动」；_time_cave_boss_done 可仍 True。
   - 	ests/test_p1b0_post_game.py::test_archive_chain_end_to_end_fallback_flow：去掉对 
esult_confirmed=True 的依赖（若存在）。
   - C2 INGAME_POLLUTION：若 
esult_confirmed 语义降级，清单保持同步即可。

**不回滚**有界滚动 / 无锚点零输入 / 超时 unconfirmed——UI 收敛仍有独立价值。

---

## C. 不能证明的事项

1. 挑战业务受理 / 成功（无掉落、无击杀文本、无战果 HUD）— **UNKNOWN**
2. 列表关闭的真实原因（用户关面板 vs 战斗替换 vs 识别空）— **UNKNOWN**
3. 双帧无卡 = 真关闭 还是 识别失败 — **UNKNOWN**（须页面身份约束内复查）
4. 六次兜底时 17 是否未解锁 — **UNKNOWN**（本轮不改传家宝策略）
5. tick4081 拒点窗口状态、game_count 映射 — **积压**，本轮不查

---

## D. 交付摘要

| 项 | 值 |
|---|---|
| 判定 | **HOLD** |
| 原帧证据 | n=8（002105×2 + 004851×6）；f0310 SHA256 已对齐 |
| 旧掉落结论 | **撤回** |
| 代码 | mediator.py 8435–8458 / 8099–8103 / 17262–17266 **OVERCLAIM** 
esult_confirmed |
| 最小修改 | 列表关闭≠受理；confirmed 需业务锚；改注释与测试 |
| 本轮动作 | 只读；未改代码、未跑门禁、未启动游戏 |
