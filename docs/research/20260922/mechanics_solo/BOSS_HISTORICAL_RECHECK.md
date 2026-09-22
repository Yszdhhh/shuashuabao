# Boss 历史包更正核对（最小 3 样本）

- 判定：**HOLD**（统计已更正；3 样本帧级语义部分 UNKNOWN，不凑证据）
- 范围：仅已定位异常附近原帧；不扩展全量 OCR / 录屏 / 新修复
- 输入：G:\\刷刷宝\\captures\\hitch_lobby_chain_20260922_004851_422384\\（trace.jsonl / manifest.json / frames / incidents）
- 根因参考包：C:\\tmp\\shuabao-captures\\hitch_lobby_chain_20260922_002105_993691\\（f0309→f0310）
- 旧报告：G:\\刷刷宝\\Worktrees\\boss-challenge-20260922\\docs\\BOSS_CHALLENGE_20260922.md（§2 统计以本文为准更正）
- 帧映射纪律：**tick ≠ 帧文件序号**。本文帧名来自 manifest.json 的 events[].frame_before/after，用 t_s≈tick.ts-start 对齐（偏差约 5s）；禁止猜 f0403 一类文件名。

## 1. 更正后的动作分类（传家宝目标 17年兽）

称 **10 个战后事件段**（不是 10 个完整对局；game_count 缺 2、含 10 的映射未核实 → **UNKNOWN**）。

| 动作分类 | n | 证据 |
|---|---:|---|
| 目标点击被接受（input ok=true） | **1** | tick **725** click:17年兽 ok=true，post_confirm=null（manifest e0418） |
| 兜底点击（BossNotUnlockedLast） | **6** | tick **415 / 1306 / 1598 / 1906 / 2462 / 3277** |
| 未点目标（收尾未点 17） | **2** | 事件段 7、9（空滚变体后收尾） |
| 目标点击被拒绝（input ok=false） | **1** | tick **4081** click:17年兽 ok=false，post_confirm=null（e2254） |

**旧报告错误**：原「兜底 7」→ 更正为 **兜底 6**。  
**语义红线**：click ok=true ≠ 挑战成功；BossNotUnlockedLast **不证明**账号未解锁，只表示当时走了末卡兜底；兜底是否违反当时策略（目标应点 17 而改点 12/13）需策略裁决 → **策略合规性 UNKNOWN**。

时光之穴 18瑟莱德丝公主（独立分类，不并入上表）：

| 形态 | n | 说明 |
|---|---:|---|
| 目标点击被接受 | 10 | 每事件段 1 次 click:18瑟莱德丝公主 ok=true |
| 异常收敛（BossAnomalyParkPointer） | 7 | 点击后 3 次 park → 关面板 |
| 空滚变体 + BossLastVisibleFallback→52库林纳克斯 | 3 | 各 2 次 fallback 点击（e1509/e1510、e2044/e2046、e2249/e2250） |

## 2. 三个样本（每样本 ≤4 帧）

代理指标说明：
ight_blobs = 右侧列表 ROI 内亮色连通块数（卡片代理）；ull_diff = 前后全帧平均绝对差。语义判定只在看得见时写「是/否」，否则 **UNKNOWN**。

### 样本 1 · tick 403 后的时光之穴异常（gc=0）

| 项 | 结果 | 证据 |
|---|---|---|
| 真实帧映射 | e0198 / at_s 992.469 | rames/f0300_action_before.png → rames/f0301_action_after.png（**不是 f0403**） |
| 目标看见 | 右侧列表 before 有卡片代理 4 blob，点击点 [1313,376] 落在列表 ROI | trace tick403 + blob |
| 点击被接受 | **input ok=true**（SendInput 成功，≠业务成功） | trace / manifest e0198 |
| 列表变化 | **是：卡片代理 4→0**（right_blobs 4→0，full_diff 5.48） | 同 ROI 计数 |
| 与 f0310 同构 | **形态同构（列表清空 diff≈5.5）**；是否同为「掉落弹窗替换列表」= **UNKNOWN**（未目视弹窗语义） | REF f0309→f0310：blobs 3→0，full_diff 5.52 |
| 掉落/挑战后置确认 | **UNKNOWN**；post_confirm=null | trace tick403 |
| 后续 | tick406 BossAnomalyParkPointer×路径 → CloseArchivePanel → 兜底 12战争之王 | e0199–e0203 |

样本 1 使用帧（≤4）：
1. G:\\刷刷宝\\captures\\hitch_lobby_chain_20260922_004851_422384\\frames\\f0300_action_before.png
2. ...\\frames\\f0301_action_after.png
3. ...\\frames\\f0302_state_change.png（异常窗）
4. ...\\frames\\f0303_action_before.png（关面板前）

### 样本 2 · tick 2778 后的空滚变体（gc=7）

| 项 | 结果 | 证据 |
|---|---|---|
| 真实帧映射 | e1492 / at_s 7074.016 | rames/f2390_action_before.png → rames/f2391_action_after.png（**不是 f2778**） |
| 目标看见 | before 右侧 2 blob；点击点 [1313,373] | trace tick2778 |
| 点击被接受 | **input ok=true** | e1492 |
| 列表变化 | **是：点击后卡片代理 2→0**；随后空滚 e1493 2392→f2393（blobs 仍 0，full_diff 12.59） | 计数 + diff |
| 与 f0310 同构 | **列表清空后仍滚动** = 成功后置缺失 + 空列表滚动；弹窗语义 **UNKNOWN** | 与样本 1 / REF 同为点击后 blobs→0 |
| 掉落/挑战后置 | **UNKNOWN**；post_confirm=null | trace |
| 后续 | 13×scroll → BossLastVisibleFallback 点 52库林纳克斯（×2） | e1509/e1510 |

样本 2 使用帧（≤4）：
1. ...\\frames\\f2390_action_before.png
2. ...\\frames\\f2391_action_after.png
3. ...\\frames\\f2392_action_before.png
4. ...\\frames\\f2393_action_after.png

### 样本 3 · tick 725 前后的 17年兽（gc=1）

| 项 | 结果 | 证据 |
|---|---|---|
| 真实帧映射 | e0418 / at_s 1780.0 | rames/f0650_action_before.png → rames/f0651_action_after.png |
| 目标看见 | **UNKNOWN**（本 ROI 右侧 blobs 0/0；传家宝布局可能不走该 ROI，不能据此断「看不见 17」） | blob 仅代理 |
| 点击被接受 | **input ok=true**；点 [876,548] | e0418 |
| 列表变化 | **几乎无**（full_diff 0.46，blobs 0→0）——点击被接受但画面几乎不变 | diff |
| 掉落/挑战后置 | **UNKNOWN**；post_confirm=null（主架构已独立确认） | trace + manifest |
| 后续 | e0419 DismissHeirloomDialog（close） | f0652→f0653 |

样本 3 使用帧（≤4）：
1. ...\\frames\\f0650_action_before.png
2. ...\\frames\\f0651_action_after.png
3. ...\\frames\\f0652_action_before.png
4. 参考对照（根因包，非 004851）：C:\\tmp\\shuabao-captures\\hitch_lobby_chain_20260922_002105_993691\\frames\\f0310_action_after.png

## 3. 证据路径汇总

| 用途 | 路径 |
|---|---|
| trace | G:\\刷刷宝\\captures\\hitch_lobby_chain_20260922_004851_422384\\trace.jsonl |
| 帧索引 | ...\\manifest.json → events[] / rames[] |
| 根因参考 | C:\\tmp\\shuabao-captures\\hitch_lobby_chain_20260922_002105_993691\\frames\\f0309_action_before.png / 0310_action_after.png |
| 旧报告 | G:\\刷刷宝\\Worktrees\\boss-challenge-20260922\\docs\\BOSS_CHALLENGE_20260922.md |
| 本文 | G:\\刷刷宝\\_facts_20260922\\mechanics_solo\\BOSS_HISTORICAL_RECHECK.md |

## 4. 精确剩余待查

1. 样本 1/2 的「掉落弹窗 = 挑战受理」语义：需目视 0301/2391 全帧是否出现掉落条（当前只有列表清空代理）→ **UNKNOWN**
2. 样本 3：17年兽卡是否在传家宝列表可见（需传家宝列表 ROI，不用右侧时光之穴 ROI）→ **UNKNOWN**
3. tick 4081（ok=false）拒点时窗口/前景状态帧 → 本轮未抽
4. game_count 缺 2、含 10 的事件段映射 → **UNKNOWN**
5. 兜底 6 次是否违反「目标=17年兽」策略（vs 竞品式 NotUnlockedLast 允许）→ **待 Owner/策略**
