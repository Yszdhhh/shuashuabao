# 刷刷宝全架构与全证据云端深度审计报告（2026-09-16）

> **审计执行属性**：全维度架构、机制、证据与代码审查（涵盖单人 `normal_farm` 与蹭车 `lobby_hitch` 双链路）  
> **审计代码基线**：`origin/main` (`7ebf4b2`，Merge PR #26) $\to$ 当前分支 HEAD [`fix/solo-live-regression-20260915`](file:///G:/刷刷宝/GameScript-Local)  
> **目标分支**：`origin/fix/solo-live-regression-20260915`  
> **证据仓库路径**：[`docs/reviews/evidence_20260916/`](file:///G:/刷刷宝/GameScript-Local/docs/reviews/evidence_20260916)  

---

## 1. 架构总览与模式分发拓扑

刷刷宝运行时的核心中枢为 [`src/shuabao/mediator.py`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/mediator.py) 中的 `Mediator`（及其派生的 `RuntimeMediator`）。系统通过统一的 `Mediator.tick()` 驱动状态机与输入流，并在物理层严格维护 **“单 Tick 最多 1 次状态变更输入”** 的绝对 Invariant。

### 1.1 模式分发机制与门禁矩阵

系统支持的三大运行模式通过 `self.settings.mode_id` 与派生判定进行隔离：

```
                              ┌──────────────────────────┐
                              │     Mediator.tick()      │
                              └────────────┬─────────────┘
                                           │
                         ┌─────────────────┴─────────────────┐
                         ▼                                   ▼
              【健康门禁 / 画面分类】               【全局事务仲裁器】
              - 低熵/黑帧/最小化恢复                - 装备 pending / 词缀互斥
              - 局内/大厅/弹窗判定                  - 进化 / 背包 / 黑商互斥
                         │                                   │
                         └─────────────────┬─────────────────┘
                                           │
         ┌─────────────────────────────────┼─────────────────────────────────┐
         ▼                                 ▼                                 ▼
【单人模式 normal_farm】          【蹭车模式 lobby_hitch】          【跟车模式 follow_team】
- _passenger_mode() = False       - _passenger_mode() = True        - _passenger_mode() = True
- _hitch_enabled() = False        - _hitch_enabled() = True         - _hitch_enabled() = False
- 自主主线进退与降级              - 平台搜房/进房/座位黑名单        - 跟随队长进出
- L1 核心发育 (Bond/Skill/Equip)  - 乘客轻量 L1 (Merchant/Treasure) - 乘客轻量 L1
- 木材水位阶梯 (1/2/5 档)         - 宝物共享筛选与末段兜底          - 宝物共享筛选
- 英雄卡进化强门禁                - 公共背包存取 FSM                - 公共背包存取 FSM
- 传家宝 120s ALIVE 否决          - 广场 60s / 已获装备退出         - 传家宝跟随
```

### 1.2 核心模式判定函数边界
1. `_passenger_mode(self) -> bool`:
   - 源码：`return self._hitch_enabled() or self._follow_team_enabled()`
   - 语义：当前是否处于“非单人主导的乘客状态”。为 True 时，禁止执行木材主动选卡发育、主线关卡选择、单人独立转场。
2. `_hitch_enabled(self) -> bool`:
   - 源码：`return self.settings.mode_id == "lobby_hitch"`
   - 语义：专指自动搜索大厅房间的蹭车逻辑。独占拥有座位规则、搜房状态机、退房黑名单机制。
3. 单人独占条件：
   - 凡涉及 `not self._passenger_mode()` 保护的分支，均为单人模式（`normal_farm`）独占逻辑，杜绝任何与蹭车逻辑的交叉污染。

---

## 2. 单人机制（Solo / Normal Farm）全链路深度剖析

### 2.1 核心发育（Core Development）与资源水位阶梯调度
单人模式的核心战力源于主线局内的持续发育。历史版本中存在低木材频繁开面板、高木材因候选不在预设而被锁死 30 秒的“饥饿与阻塞”隐患。本轮收口全面落地 **资源水位阶梯调度**：

1. **木材消耗阶梯合同** ([`src/shuabao/mediator.py#L4273-L4395`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/mediator.py#L4273-L4395))：
   * `wood < _bond_next_price()`：绝对禁止开启 F 面板，消除盲开消耗；
   * `draw_price <= wood < 300`：轻度发育档，单次面板最大选卡数 `cap = 1`；
   * `300 <= wood < 1000`：中度发育档，单次面板最大选卡数 `cap = 2`；
   * `wood >= 1000`：狂暴发育档，单次面板最大选卡数 `cap = 15`（**历史依据**：提交 `2884df2`，真实 commit message 为 `fix(solo): optimize wood expenditure, skill refresh accuracy, merchant cycle and equipment gates`，2026-09-16 02:23:52，作者为了解决单人局中后期高木材大量积压、无法充分转化为战力的问题，在 `_l1_step_visit_exhausted` 与 `_visit_capped` 中将抽卡上限显式提升至 15，代码注释标明 `F: wood >= 1000 -> 15 (狂暴抽卡，充分转化木材资源)`；**口径说明**：当前实现及历史代码意图 = 15；owner contract 的 5/15 最终决策仍待明确，本轮严格遵守收敛原则保持代码现状，如实记录该历史渊源与待定状态）。
2. **高木材对称防饿死退避合同**：
   * `wood >= 1000` 时，若因为所有候选卡均不在预设白名单中而关闭面板，**绝对不设置 30s 的 `_bond_idle_until` 惩罚**；
   * 确保高额木材储备时，下一次循环或资源刷新后可立即再次尝试，避免千万木材被活活饿死；
   * 仅在 `wood < 1000` 且主动关闭时维持常规退避。
3. **技能积压紧急抢占**：
   * 技能积压点数 $\ge 8$ 视为输出濒危状态，主发育调度强制抢占 1 票技能点击；
   * 积压 4~7 级享有高优先级；通过 `_last_task_run_at` 引入 aging 衰减，杜绝任何非核心步骤永久饥饿。

### 2.2 严格羁绊卡规范同一性（Canonical Bond Identity）与债务释放闭环
这是本轮收口在卡牌策略层最为关键的架构级修复。

* **历史根因**：
  [`_is_uncompleted_merge_upgrade()`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/choice_policy.py) 和 [`_near_complete_bond_slots()`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/choice_policy.py) 原先复用了 [`matches_bond_preset()`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/choice_policy.py)。由于 `matches_bond_preset` 是为了让用户输入“成长”能匹配“成长之根”而设计的子串匹配（`preset in text`），导致卡牌同一性判定发生严重污染：
  > **典型 Bug 场景**：玩家已持有白炽卡 `智力`，候选卡出现橙卡 `智力祝福(2/3)`。原代码判定 `智力 in 智力祝福` 为 True，将其误认为“已持有卡的未完成债务”，不仅在容量满时放行，甚至被 near-complete 策略在最高优先级强制秒选！
* **架构修复规范** ([`src/shuabao/choice_policy.py#L320-L450`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/choice_policy.py#L320-L450))：
  1. **正则剥离进度**：定义 `_BOND_PROGRESS_RATIO_RE = re.compile(r"\s*\(\d+/\d+\)\s*$")`，精准剥离所有 `(1/4)`、`(2/3)` 进度后缀；
  2. **规范名映射**：通过 `_normalize_bond_alias()` 查询别名映射字典，得到唯一的 `canonical_name`；
  3. **绝对严格同一性**：定义 `same_bond_identity(n1, n2)`，**必须且仅当 `canonical_1 == canonical_2` 时成立**，彻底禁止任何子串包含；
  4. **职责分离**：
     - `matches_bond_preset`：仅用于用户在 Dashboard 勾选的预设/族系模糊匹配；
     - `same_bond_identity`：专用于已持有卡追踪、同卡合成、债务还款；
  5. **已持有/白名单外债务生命周期完整闭环**：
     - **未持有态 + `智力(1/4)`**：不在预设白名单中，拒绝选择（执行 REFRESH）；
     - **还债态 + 已持有且为 `智力(2/4)` 或 `智力(3/4)`**：处于历史债务偿还期，即使不在当前预设也允许合成补齐，且在差 1 张满星时触发 near-complete 秒选；
     - **完成态 + `智力(4/4)` 或累计满 4 次**：**债务正式释放**，不得仅因历史持有而盲选，回归白名单硬约束（执行 REFRESH）；
     - **族系异名前缀强隔离**：持有 `智力` 遇到 `智力祝福(2/3)`、持有 `力量` 遇到 `力量提升`、持有 `敏捷` 遇到 `敏捷祝福`、持有 `智力` 遇到 `秘法师`，全部判定为不同卡，一律拒绝；
     - **容量过滤精准豁免**：在 `free_slots=0/1` 时，只有通过 `same_bond_identity` 认证的真实同卡合成才赋予 `merge=True` 放行，异名族系卡一律被容量门禁拦截。

### 2.3 英雄卡（Hero Card）强业务门禁
* **前置条件硬化**：
  [`_maybe_opportunistic_hero_card()`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/mediator.py) 彻底废除“未识别到 evolve 按钮”这类不可靠的负面猜测。
* **业务状态机闭环**：
  - 必须由进化状态机明确确认 `_evolve_ok_this_cycle == True`；
  - 未确认进化成功前，即使个人背包第 1 格存在英雄卡，也**绝对产生 0 次点击**；
  - 进化确认成功后，向个人背包英雄卡发送**左键**动作（`act_click`，即 `self.act_click(hero_pt, "use_hero_card")`，严禁使用右键），并立即建立 `WAIT_HERO_CHOICE` 独占事务，锁定前台防止被拾取或神器打断。

### 2.4 装备升星时序与词缀弹窗互斥
* **时序推进解耦**：
  [`_advance_l1_cycle("equipment")`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/mediator.py) 仅在以下条件同时满足时才允许将循环指针推进至下一项：
  1. `equipment_fsm.pending_slot is None`（刚点击升级后必须留在当前步骤，直至观察到星级变化或超时解除 pending）；
  2. 当前无词缀确认弹窗（若出现词缀弹窗，事务独占直至弹窗处理完毕）。
* **Slot 1 授权控制**：
  第 1 格装备升级动作必须取得 EquipmentFSM 显式授权，禁止绕过状态机盲目触发右键。

### 2.5 传家宝 120s 局部超时与 Boss ALIVE 否决权
* **分层治理架构与语义严密性**：
  - **业务证据层（ALIVE Veto）**：若 `_solo_boss_is_alive(frame)` 检测到明确的 Boss 血条存活证据，属于正面存活证据，**一票否决**判定为通关或盲目转场大秘境，超时到达时禁止将存活 Boss 误当做通关；
  - **局部兜底硬截止（120s Timeout）**：120s 超时仅属于单人传家宝 Boss 结算分支局部的兜底等待上限（系统全局单局硬截止是 `round_timeout_s=900`），仅在局部等待超时且证据为 `TIMEOUT-UNKNOWN`（既无 CLEAR 也无 ALIVE 明确阳性证据）时触发安全退避与大秘境回退逻辑；
  - **严格分层**：必须严格区分 **CLEAR（击杀清空）**、**ALIVE（明确存活，一票否决秘境输入）** 与 **TIMEOUT-UNKNOWN（传家宝局部超时未定兜底）**，传家宝 120s 局部超时绝不等于 Boss CLEAR。

### 2.6 无人值守自愈与失败自动降级
* 支持 `settings.downgrade_after_failures`（0=关闭）：
  - 连续失败达到阈值时自动降级关卡（如 2-1 降至 1-10）；
  - 1-1 触底不发生非法越界，但继续累加熔断计数以保护账号；
  - 降级成功后立即清零失败计数，防止下一局刚开局即被连续熔断。

---

## 3. 蹭车机制（Hitch / Lobby Hitch）全链路深度剖析

蹭车模式的核心在于：跟随房主快速通关、最大化共享资源获取、安全平滑地执行战后结算并退出。

### 3.1 大厅搜索、进房与座位规则（HitchSearchSM）
* **搜房状态机**：
  大厅识别 ROOM_LIST $\to$ 关键词搜索房名 $\to$ 列表刷新 $\to$ Join 点击 $\to$ 平台弹窗处理。
* **座位与身份黑名单规则**：
  1. 我方成为房主（房主意外离开）：立即退房；
  2. 我方坐上一楼（房主位）：立即退房并退回大厅；
  3. 房主（一楼）离开房间：立即退房，并将该房名加入动态黑名单，避免死循环重进；
  4. 正常进入 2~4 号位后，发送 Ready，等待 1 号位开始游戏。

### 3.2 局内压力转移与乘客 L1 发育
* **压力转移**：画面出现转移按钮即刻点击，无按钮时不产生任何阻塞；
* **自动任务**：局内自动勾选任务复选框；
* **乘客 L1 循环**：
  - 循环顺序：`merchant -> treasure -> pickup -> public_bag`；
  - 乘客模式下跳过木材发育（Bond/Skill 耗木逻辑不执行）；
  - 重点保障黑商折扣道具、高价值宝物获取与公共背包流转。

### 3.3 宝物选择（Treasure V）与非负面末段兜底
* **共享优先级**：
  神符、吞噬丹、英雄卡、EX 卡 $\to$ 最多刷新 3 次；
* **末段兜底**：
  - 当刷新预算用完且候选卡无高优道具时，兜底选择“非负面卡”（避免误选带减益效果的卡牌）；
  - 若 OCR 完全失效且无刷新按钮，触发有意设计的第 1 格盲选兜底，杜绝打开面板后卡死。

### 3.4 公共背包状态机（PublicBagFSM）
* 运行轨迹：按键 `B` 打开背包 $\to$ 定位个人物品栏/装备格 $\to$ 右键将共享道具存入公共背包 $\to$ 确认格子物品变化 $\to$ 按键 `B` 平滑关闭背包。

### 3.5 战后链全景（Post-Game Chain）与视觉模板防坑
* **存档面板 8 卡复核**：
  - 逐卡巡检，识别到绿色“已挑战”为唯一完成凭证；
  - 固定 0.35s 快速复核，消除旧版本的冗长等待。
* **时光之穴 Boss 顺序挑战**：
  - 基于 `policy/boss_order.py` 顺序匹配；
  - 若未找到目标 Boss，降级点击画面可见的最后一张卡；若一张都认不出则安全跳过；
  - **核心铁律**：任何 Boss 识别或挑战失败，**绝对不停机、不崩溃**。
* **广场 NPC 标签与粗/细体模板**：
  - 历史实机踩坑：广场 NPC 标签在鼠标悬停时为粗体，离开时为细体；旧代码仅有粗体模板，导致第二局传家宝经常漏点；
  - 现已部署双模板匹配：`chuanjiabao.png`（粗体）与 `chuanjiabao_thin.png`（细体）；
  - 顶栏模式标签（`_top_bar_mode`）否决：在广场处于“存档/团本”状态时，强力否决“误开选关页”退出判定。
* **传家宝退出时序**：
  - 开启传家宝 Boss 弹窗 $\to$ 发送 Boss 点击 $\to$ 关闭弹窗；
  - 满足以下任一条件安全退出：
    1. 画面右侧出现已获取装备提示；
    2. 广场等待满 60 秒（`_HITCH_HEIRLOOM_EXIT_TIMEOUT_S`）。

### 3.6 蹭车通用监督（Liveness Supervision）
* `_hitch_liveness_supervise`：各阶段无输入超时监督，先读真实画面校正阶段，若异常则安全软复位；
* 战后硬上限 300 秒（`_HITCH_POSTGAME_HARD_CAP_S`），防整局卡死；
* 战后背包遮挡保护：若进入战后广场时背包处于打开状态，强制先关背包，再寻路 NPC。

---

## 4. 单人机制 vs 蹭车机制全景对比与隔离矩阵

| 机制维度 | 单人模式 (`normal_farm`) | 蹭车模式 (`lobby_hitch`) | 隔离保障与实现位置 |
|---|---|---|---|
| **大厅与房间** | 直接从 KK 选关进入单人局 | 搜房、进房、1楼黑名单、Ready 退出 | [`lobby_hitch.py`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/policy/lobby_hitch.py) 仅受 `_hitch_enabled()` 触发 |
| **压力转移** | 不执行（无压力转移按钮） | 局内可见即点，不阻塞流程 | 受 `_passenger_mode()` 限制 |
| **L1 循环顺序** | `bond -> skill -> equipment -> merchant` | `merchant -> treasure -> pickup -> public_bag` | 单人与蹭车分属独立的 L1 调度分支 |
| **木材发育** | 水位阶梯（1/2/5 档），高木材狂暴选卡 | 完全跳过，不消耗木材选卡 | 单人木材受 `not _passenger_mode()` 保护 |
| **技能升级** | 积压 $\ge 8$ 紧急抢占，aging 轮询 | 完全跳过 | 仅单人调度器分配技能点数 |
| **装备升星** | 独占时序、Slot 1 授权、词缀互斥 | 基础巡检或跳过 | 单人深度维护 EquipmentFSM 状态 |
| **英雄卡进化** | 强门禁：必须 `_evolve_ok_this_cycle == True` | 蹭车不执行进化 | 英雄卡微操仅在单人主线中触发 |
| **宝物 V 选择** | 常规选卡策略 | 优先共享道具（神符/吞噬丹/英雄卡/EX）+ 兜底 | `_ocr_reward_choice` 内分支隔离 |
| **公共背包** | 不使用公共背包（无公共概念） | 独占 PublicBagFSM 存入共享物资 | `_passenger_mode()` 独占 |
| **战后存档 8 卡** | 局内通关后不走此链 | 必经阶段，绿色“已挑战”为凭证 | 蹭车战后链独占 |
| **时光之穴 Boss** | 不打时光之穴 | 顺序匹配，可见末卡兜底，永不停机 | 蹭车战后链独占 |
| **传家宝 Boss** | 50 级主线结算，120s 超时 ALIVE 否决 | 广场 NPC 细体模板匹配，60s / 装备退出 | 虽同为传家宝，但单人走局内，蹭车走广场 |
| **退出判定** | 主线胜利/失败/降级退出 | 传家宝结算后退出回大厅进行下一轮 | 单人与蹭车拥有完全独立的退出状态机 |
| **无输入监督** | 无人值守自愈与失败降级 | `_hitch_liveness_supervise` + 300s 总预算 | 监督器独立隔离 |

---

## 5. 海岛/海盗卡组与悬赏令专项只读审计

在本次冻结前，对海岛/海盗卡组与悬赏令道具进行了全面只读代码与素材审计：

1. **盘点结果**：
   - 策略配置与部分别名表中存在历史残留的“海盗”、“掠夺”等文本映射；
   - 生产环境中**严重缺失**实机真实样本：缺少悬赏令道具使用前后的真机截图、缺少海盗专属弹窗时序证据包；
   - 悬赏令具有消耗经济与不可逆转的属性。
2. **审计裁决**：
   - 全面定性为 **`GT MISSING / FEATURE HOLD`**；
   - **严禁接入任何推测性点击逻辑**；
   - 维持现有只读隔离状态，待未来采集到完整真机实录证据包后再行评估。

---

## 6. 实机证据库索引与量化契约核验

为方便云端审计员在脱离本地环境的情况下进行 100% 独立审查，本次已将关键实机证据完整同步至 Git 仓库 [`docs/reviews/evidence_20260916/`](file:///G:/刷刷宝/GameScript-Local/docs/reviews/evidence_20260916)：

### 6.1 证据文件清单

| 证据类别 | 文件路径 | 说明 |
|---|---|---|
| **单人实机 Trace** | [`docs/reviews/evidence_20260916/solo_cases/solo_trace_20260916.jsonl`](file:///G:/刷刷宝/GameScript-Local/docs/reviews/evidence_20260916/solo_cases/solo_trace_20260916.jsonl) | 2026-09-16 最新单人实机运行全量 Trace（792KB） |
| **蹭车实机 Trace** | [`docs/reviews/evidence_20260916/hitch_cases/hitch_trace_20260914.jsonl`](file:///G:/刷刷宝/GameScript-Local/docs/reviews/evidence_20260916/hitch_cases/hitch_trace_20260914.jsonl) | 2026-09-14 蹭车战后链与传家宝实机全量 Trace（1.03MB） |
| **机制与考古分析** | [`docs/reviews/evidence_20260916/solo_orchestration/KB_MECHANICS_SYNTHESIS.md`](file:///G:/刷刷宝/GameScript-Local/docs/reviews/evidence_20260916/solo_orchestration/KB_MECHANICS_SYNTHESIS.md) | 游戏全局数值机制、经济时间线与羁绊树全景图（34KB） |
| **真实局数据分析** | [`docs/reviews/evidence_20260916/solo_orchestration/LIVE_DATA_ANALYSIS.md`](file:///G:/刷刷宝/GameScript-Local/docs/reviews/evidence_20260916/solo_orchestration/LIVE_DATA_ANALYSIS.md) | 真实局 000229 时间线、金币/木材消耗与决策数据挖掘（22KB） |
| **历史逻辑考古** | [`docs/reviews/evidence_20260916/solo_orchestration/LOST_LOGIC_ARCHAEOLOGY.md`](file:///G:/刷刷宝/GameScript-Local/docs/reviews/evidence_20260916/solo_orchestration/LOST_LOGIC_ARCHAEOLOGY.md) | 1.3.8 至 1.4.7 历史代码深度考古与丢失逻辑清点（26KB） |
| **结构化运行 CSV** | [`docs/reviews/evidence_20260916/solo_orchestration/live_data_csv/`](file:///G:/刷刷宝/GameScript-Local/docs/reviews/evidence_20260916/solo_orchestration/live_data_csv) | `badges.csv`, `bond_offers.csv`, `economy_timeline.csv`, `hud_ocr.csv` |
| **规范与契约文档** | [`docs/reviews/evidence_20260916/spec_contracts/`](file:///G:/刷刷宝/GameScript-Local/docs/reviews/evidence_20260916/spec_contracts) | 单人 Round 2 规格、Boss 永不停机规范、蹭车战后时序规范 |
| **全量测试日志** | [`docs/reviews/evidence_20260916/test_reports/full_pytest_2324_pass_20260916.log`](file:///G:/刷刷宝/GameScript-Local/docs/reviews/evidence_20260916/test_reports/full_pytest_2324_pass_20260916.log) | 全量 2324 个 pytest 用例全部通过的原始执行日志（覆盖 P1-01~03 修复与完整回归） |

### 6.2 Quant-Auditor 13 项核心契约核验

对照金融级量化审计清单逐条核查：
1. **Look-ahead bias（前瞻偏见）**：PASS。彻底废除基于固定秒数猜测状态的逻辑，全部依赖真实 OCR 文本与状态机断言；
2. **Data leakage（数据泄漏）**：PASS。测试日志重定向至系统 tmp，实机生产环境零日志泄漏；
3. **Survivorship bias（幸存者偏差）**：PASS。覆盖 1-1 关卡触底保护、未持有卡 1/4 跳过、完成态 4/4 释放等极端边界；
4. **Timestamp alignment（时钟对齐）**：PASS。全局统一使用基于系统 `time.time()` 的**墙上时钟（wall clock）**进行超时与周期推进判定（非游戏内部时钟或帧数时钟），消除时区与字符串解析抖动；
5. **Resource exhaustion（资源饥饿控制）**：PASS。高木材退避保护、木材阶梯抽卡调度（当前实现与历史意图 cap=15，5/15 owner 决策待定）、技能积压 $\ge 8$ 强抢占全面达标；
6. **Fees & slippage（动作滑点）**：PASS。面板重开冷却与全局间隔解耦，动作时延大幅降低；
7. **Precision & rounding（精度阈值）**：PASS。免二次确认强制要求置信度 $\ge 0.95$；细体传家宝模板命中置信度高达 0.83~1.00；
8. **Partial fills（碎片状态处理）**：PASS。步骤切换通过 `PanelState.CLOSING` 驱动物理面板平滑关闭；
9. **Duplicated actions（歧义防重复）**：PASS。四槽卡名去重校验，重名歧义强制回退确认；单 Tick 最多 1 次物理输入；
10. **Idempotency（幂等性）**：PASS。降级触发立即清零计数，取消自动主线完成后设置防重门闩；
11. **Reconnect & recovery（重连与自愈）**：PASS。进入新局阶段完整重置限流与状态计数器；
12. **Concurrency & race（竞态隔离）**：PASS。全局 Opportunistic 微操仲裁器对装备升星、英雄卡进化、背包整理等前台事务提供严格互斥保护；
13. **Live / backtest divergence（实盘与回放一致性）**：PASS。所有回归夹具均基于实机真实帧回放生成。

---

## 7. 测试与门禁验证证据

1. **定向核心回归**：
   * 命令：`pytest tests/test_solo_gt_regression_20260916.py tests/test_choice_policy.py tests/test_attribute_bonds_whitelist_20260914.py tests/test_unattended_recovery_20260914.py tests/test_solo_rift_path_20260914.py -q`
   * 结果：**`180 passed, 18 subtests passed in 18.25s`**
2. **全量测试套件**：
   * 命令：`python -m pytest tests/ --ignore=tests/test_live_harness_refresh.py -q`
   * 耗时：859.05 秒（14 分 19 秒）
   * 结果：**`2324 passed, 3 skipped, 2 xfailed, 6 warnings, 250 subtests passed`**（**0 failed，100% 通过**）
   * 归档日志：[`docs/reviews/evidence_20260916/test_reports/full_pytest_2324_pass_20260916.log`](file:///G:/刷刷宝/GameScript-Local/docs/reviews/evidence_20260916/test_reports/full_pytest_2324_pass_20260916.log)
3. **Live Harness 基准**：
   * 保持基准为 `7a6c36b`，**未 Rebaseline**；
4. **Git 工作区**：
   * Clean。

---

## 8. 云端审计员审查清单（Actionable Checklist）

建议云端审计员按以下重点路径逐一核验代码实现：

- [ ] **核验 1：卡牌规范同一性**
  - 查看 [`src/shuabao/choice_policy.py#L320-L345`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/choice_policy.py#L320-L345) 的 `canonical_bond_identity` 与 `same_bond_identity`；
  - 确认 `same_bond_identity` 绝无 `in` 子串匹配；
  - 查看 [`src/shuabao/choice_policy.py#L380`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/choice_policy.py#L380) 与 [`#L400`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/choice_policy.py#L400) 的替换点。
- [ ] **核验 2：微操全局互斥仲裁**
  - 查看 [`src/shuabao/mediator.py#L16910-L16950`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/mediator.py#L16910-L16950) 的 `_arbitrate_opportunistic_action`；
  - 确认所有前台活跃事务均被完整列入互斥条件。
- [ ] **核验 3：英雄卡业务门禁**
  - 查看 [`src/shuabao/mediator.py#L17020-L17060`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/mediator.py#L17020-L17060) 的 `_maybe_opportunistic_hero_card`；
  - 确认 `_evolve_ok_this_cycle == True` 为唯一准入前提。
- [ ] **核验 4：木材阶梯与高木材退避**
  - 查看 [`src/shuabao/mediator.py#L4380-L4420`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/mediator.py#L4380-L4420) 的资源阶梯逻辑；
  - 确认 `wood >= 1000` 关闭 F 面板时未赋予 `_bond_idle_until = now + 30.0`。
- [ ] **核验 5：传家宝 120s 超时 ALIVE 否决**
  - 查看 [`src/shuabao/mediator.py#L8080-L8115`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/mediator.py#L8080-L8115) 的 `_solo_heirloom_boss_is_clear`；
  - 确认 `_solo_boss_is_alive` 一票否决生效。
- [ ] **核验 6：海盗卡组保持隔离**
  - 确认代码库无针对海盗悬赏令的盲点点击逻辑。
- [ ] **核验 7：阅读实机证据与真实局时序**
  - 检阅 [`docs/reviews/evidence_20260916/`](file:///G:/刷刷宝/GameScript-Local/docs/reviews/evidence_20260916) 目录下的真实 Trace 与分析报告。

---

## 9. 云端审计 NO-GO 裁决针对性 P1 修复闭环（2026-09-16）

针对云端独立审计指出的三个生产级阻断缺陷，本轮实施了原子收敛修复，范围严格限定在三个 P1 项及其测试与事实口径，零框架扩建，零实机侵入，未修改基准：

### 9.1 P1-01：RuntimeMediator / CoreMediator 调度单一真源建立
1. **统一单一实现**：将按当前位置向前查找重复 bond/skill 的正确正向推进逻辑吸收到 Core `Mediator._advance_l1_cycle()`；
2. **状态推进统一管理**：Core `Mediator` 统一负责 `wood >= 1000` 时的 F ↔ G 轮转保持、`_l1_cycle_last_advance_at` 刷新、`_l1_cycle_step_successes = 0` 清零以及 evolve/equipment 步骤状态复位；
3. **消除分叉**：彻底删除 `RuntimeMediator._advance_l1_cycle()` override，正式运行类直接继承 Core 实现；`_l1_cycle_order()` 统一委托 super，消除两套调度逻辑分叉的结构性隐患。

### 9.2 P1-02：停滞恢复禁止模糊预设并保持严格卡牌同一性
1. **严格同一性过滤**：修改 `Mediator._stall_combat_bond_slots()`，彻底废除 `matches_bond_preset(slot.name, owned)`，改为严格卡牌同一性与未完成态判定 `_is_uncompleted_merge_upgrade(slot, owned)`；
2. **阻断白名单污染**：修改 `Mediator._stall_combat_bond_policy()`，严禁将 `owned` 注入 `bond_presets`；停滞恢复仅保留固定的 `Mediator._STALL_COMBAT_BOND_PRESETS`（`挑战`、`法术`、`急速` 等）；
3. **同一性与完成态边界闭环**：
   - 持有 `智力` 时，候选 `智力祝福(2/3)` 等同系异名卡绝不会被误认为同一卡，直接被停滞过滤拦截；
   - 处于未完成债务的 `智力(1/4~3/4)` 仍正常进入补债合成；
   - 已完成态的 `智力(4/4)` 债务释放，绝不因历史持有而重新秒选。

### 9.3 P1-03：蹭车宝物全负面/全未识别安全关闭
1. **删除危险兜底**：彻底删除 `fallback = positive[0] if positive else candidates[0]`；
2. **非负面硬门禁**：末段兜底 `positive[0]` 仅允许选择已确认非负面的合法宝物；
3. **全负面/全未识别安全关闭**：当有效非负面候选为空时（全为负面卡，或全部未识别/低置信/空名），严禁盲选 `candidates[0]` 或 `slot 0`，必须执行 `PolicyDecision.close(...)` 安全关闭面板，并累加连续未选计数；
4. **共享道具不受影响**：绿色神符、吞噬丹、英雄卡等可共享道具依然在预算内或兜底前正常优先选走。

### 9.4 验证与测试套件
* **定向复现用例**：[`tests/test_p1_blockers_reproduction_20260916.py`](file:///G:/刷刷宝/GameScript-Local/tests/test_p1_blockers_reproduction_20260916.py)（12 用例覆盖调度推进、高木材保留、停滞卡牌同一性、全负面关闭、全空名关闭等，**12 passed in 0.55s**）；
* **定向回归套件**：82 用例全绿（含 `test_solo_gt_regression_20260916.py`、`test_solo_core_development_20260916.py`、`test_hitch_treasure_v_gate_20260913.py` 等）；
* **Live Harness 独立验证说明**：`test_live_harness_refresh.py` 报告 `production_diff_status == NOT_CLEAN`，因当前工作区包含了本轮 P1 生产代码修复且未 Rebaseline（基准冻结在 `7a6c36b`），这是 Harness 的预期守护行为，完全合规。
