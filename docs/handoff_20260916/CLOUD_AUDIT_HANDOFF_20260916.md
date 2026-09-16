# 刷刷宝全量收口与云端审计交接文档（2026-09-16）

> 本文档由本地开发/收敛会话生成，用于向云端外部审计员及技术负责人全面交接单人回归收口（`fix/solo-live-regression-20260915`）的全部代码改动、架构演进、测试结果与安全边界。
> 
> **配套深度文档与实机证据**：
> - 📘 **主审底册**：[`docs/reviews/COMPREHENSIVE_ARCHITECTURE_AND_EVIDENCE_AUDIT_20260916.md`](file:///G:/刷刷宝/GameScript-Local/docs/reviews/COMPREHENSIVE_ARCHITECTURE_AND_EVIDENCE_AUDIT_20260916.md)（单人与蹭车全链路机制、隔离矩阵、实机证据索引与量化契约核验）
> - 📁 **实机证据库**：[`docs/reviews/evidence_20260916/`](file:///G:/刷刷宝/GameScript-Local/docs/reviews/evidence_20260916)（包含 2026-09-16 单人实机 Trace、2026-09-14 蹭车实机 Trace、真实局 CSV、历史考古分析与全量测试日志）

---

## 1. 版本与基线信息

| 属性 | 设定值 | 说明 |
|---|---|---|
| **目标分支** | `fix/solo-live-regression-20260915` | 单人模式回归与收敛专用分支 |
| **远端仓库** | `github.com/Yszdhhh/shuashuabao` | 已完全同步至远端 `origin` |
| **Main 最新远端** | `7ebf4b2` | 生产主线最新提交（Merge PR #28，`7ebf4b205a1fd3acd8d9d64fd84d184db6447ebc`） |
| **当前代码 HEAD** | `origin/fix/solo-live-regression-20260915` | 本分支核心代码冻结点 |
| **Harness 基线** | `7a6c36b` | 严格保持冻结，**未 Rebaseline** |
| **验证总状态** | **CODE AUDIT GO / READY FOR CLOUD RE-AUDIT** | 单元测试全绿，P1 阻断项全面修复，实机 GT 处于 HOLD |

---

## 2. 变更范围与 Diff 概况

相较于 `origin/main`，本分支包含收敛提交与本轮 P1 修复提交：

### 核心生产代码文件分布：
1. [`src/shuabao/mediator.py`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/mediator.py):
   - P1-01: 建立 `_l1_cycle_order()` 单一真源与 `_advance_l1_cycle()` 正向查找/高木材 F ↔ G 保持/计数时间重置；
   - P1-02: `_stall_combat_bond_slots()` 严格同一性 `_is_uncompleted_merge_upgrade()` 判定与 `_stall_combat_bond_policy()` 固定战斗预设；
   - P1-03: `_ocr_reward_choice()` 蹭车宝物末段兜底只选非负面卡，全负面/全未识别严格安全关闭；
   - HUD Opportunistic 微操互斥门禁与单 Tick 物理输入保证；
   - 核心发育资源水位阶梯调度与高木材防饿死退避；
   - 英雄卡使用业务门禁（`_evolve_ok_this_cycle=True`）；
   - 装备 FSM 独占推进与词缀弹窗互斥；
   - 传家宝 120s 超时 ALIVE 证据否决权（Veto）。
2. [`src/shuabao/choice_policy.py`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/choice_policy.py):
   - 引入规范卡名同一性判定 `canonical_bond_identity()` 与 `same_bond_identity()`；
   - 完善 `_is_uncompleted_merge_upgrade()` 排除完成态卡牌（如 4/4）的逻辑；
   - 已持有/白名单外羁绊债务 1/4 ~ 4/4 完整生命周期闭环与完成态自动释放。
3. [`src/shuabao/runtime_mediator.py`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/runtime_mediator.py):
   - P1-01: 彻底删除 `_advance_l1_cycle()` override，正式运行类直接继承单一实现；`_l1_cycle_order()` 统一委托 super。
4. [`src/shuabao/policy/equipment_fsm.py`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/policy/equipment_fsm.py):
   - 修复装备升级时序与 pending 解锁状态判定。

---

## 3. 六大核心架构设计与收敛细节

### 3.1 羁绊卡同一性（Canonical Bond Identity）与债务释放闭环
* **历史缺陷**：`_is_uncompleted_merge_upgrade()` 和 `_near_complete_bond_slots()` 曾复用 `matches_bond_preset()`。由于后者采用 `preset in text` 子串匹配，导致已持有 `智力` 遇到 `智力祝福(2/3)` 时被误判为“已持有卡债务”，甚至被 near-complete 策略在第一优先级秒选。
* **重构方案**：
  1. 正则匹配 `r"\s*\(\d+/\d+\)\s*$"` 剥离所有诸如 `(1/4)`、`(2/3)` 等 OCR 进度后缀；
  2. 经由 `_normalize_bond_alias()` 字典映射，得到唯一 canonical card name；
  3. `same_bond_identity(a, b)` 仅在两者的 canonical 名称完全相等时返回 True；
  4. 严格将 `matches_bond_preset()` 局限在 Dashboard 用户配置项的族系包含场景；
  5. 明确债务生命周期：
     - 未持有 + `智力(1/4)`：不在预设中且未持有，拒绝（REFRESH）；
     - 已持有 + `智力(2/4)` 或 `智力(3/4)`：属于在偿还债务，即使 off-whitelist 也优先合成补齐；
     - 完成态 + `智力(4/4)` 或已累计 4 次：债务正式释放，不再因历史持有而盲选，回归白名单约束（REFRESH）。

### 3.2 统一事务仲裁与 HUD Opportunistic 微操防冲突
* **单 Tick 物理输入 Invariant**：严格保持每 1 个执行 Tick 最多产生 1 次改变界面的输入操作（Zero Blind Double Click）。
* **全局事务互斥仲裁**：
  - `_arbitrate_opportunistic_action()`：当以下任一前台事务进行中时，神器（F2）、吞噬丹（B开包使用）、一键拾取（Z）等微操**绝对禁止抢占**：
    1. 装备升级待观察态（`equipment_fsm.pending_slot is not None` 或词缀弹窗打开）；
    2. 英雄卡/进化结算事务进行中；
    3. 黑商验证（`VERIFYING`）中；
    4. 背包整理/物品转移中；
    5. 当前已有未提交物理动作 `_pending_action is not None`。
* **仅限纯净 HUD 触发**：微操必须满足 `self._panel_state == PanelState.CLOSED` 且画面无全屏遮挡/锚点。
* **时钟基础**：全局超时与周期推进均基于系统 `time.time()` 的**墙上时钟（wall clock）**，绝非帧数或游戏逻辑时钟。

### 3.3 英雄卡（Hero Card）强业务门禁
* **历史隐患**：代码曾试图以“当前画面没识别到 evolve 按钮”作为依据去使用英雄卡，可能在过渡帧或遮挡时误点。
* **硬门禁收敛**：
  - 强制复用 `_evolve_ok_this_cycle == True` 作为唯一业务前置条件；
  - 若未确认进化成功，即使背包里存在英雄卡，也**绝对产生 0 次点击**；
  - 进化确认成功后，才允许向背包英雄卡槽位发送**左键**动作（`act_click`，即 `self.act_click(hero_pt, "use_hero_card")`，严禁使用右键），并立刻建立 `WAIT_HERO_CHOICE` 独占事务，防止被拾取或神器打断。

### 3.4 核心发育（Core Development）资源水位与防饿死调度
* **木材消耗阶梯**：
  - `wood < _bond_next_price()`：禁止打开 F 面板，避免无意义空开；
  - `draw_price <= wood < 300`：允许开启 F，但单次最大选卡上限 `cap = 1`；
  - `300 <= wood < 1000`：单次最大选卡上限 `cap = 2`；
  - `wood >= 1000`：高木材狂暴模式，单次访问上限 `cap = 15`（**历史依据**：提交 `2884df2`，2026-09-16 02:23:52，作者为解决高木材木头烧不掉的问题，在 `_l1_step_visit_exhausted` 与 `_visit_capped` 中将上限提升为 15，注释：`F: wood >= 1000 -> 15 (狂暴抽卡，充分转化木材资源)`；本轮保持代码现状，如实记录该依据）。
* **对称测试与退避保护**：
  - `wood >= 1000` 时，若因为候选卡均不在预设而主动关闭 F 面板，**严禁设置 30s 的 `_bond_idle_until`**，避免因候选不合规导致大量积压木材被饿死 30 秒；保留 `wood < 1000` 下的普通冷却。
* **技能积压紧急调度**：
  - 技能积压点数 $\ge 8$ 视为战斗力坍塌极危状态，强制从主发育循环中抢占 1 次技能提升；
  - 积压 4~7 档提供优先调度；加入 aging 时间衰减机制，防止非核心步骤永久饿死。

### 3.5 传家宝 120s 超时与 Boss ALIVE 否决权
* **分层治理架构与语义严密性**：
  - **业务证据层（ALIVE Veto）**：若 `_solo_boss_is_alive(frame)` 检测到明确的 Boss 血条存活证据，属于正面存活证据，**一票否决**判定为通关或盲目转场大秘境，超时到达时禁止将存活 Boss 误当做通关；
  - **顶层兜底硬截止（120s Timeout）**：120s 超时属于全局硬截止兜底机制，仅在超时且证据为 `TIMEOUT-UNKNOWN`（既无 CLEAR 也无 ALIVE 明确阳性证据）时触发安全退避与大秘境回退逻辑；
  - **严格分层**：必须严格区分 **CLEAR（击杀清空）**、**ALIVE（明确存活，一票否决秘境）** 与 **TIMEOUT-UNKNOWN（超时未定兜底）**，120s 超时绝不等于 Boss CLEAR。

### 3.6 海岛/海盗卡组与悬赏令专项只读审计
* **审计范围**：卡牌模板、策略配置、背包道具、OCR 字典、Git 历史。
* **审计结论**：
  1. 代码库历史曾有海盗羁绊字段与别名，但**当前缺少完整的实机 GT 运行证据包、真机图标切片与弹窗时序**；
  2. 悬赏令等道具使用具有不可逆经济影响；
  3. **正式结论**：继续严格标记为 `GT MISSING / FEATURE HOLD`，**绝对禁止接入任何推测性点击逻辑**，保持只读与隔离。

---

## 4. 测试与验证报告

### 4.1 定向核心回归测试
覆盖本次修改的所有关键边界：
* 命令：`pytest tests/test_solo_gt_regression_20260916.py tests/test_choice_policy.py tests/test_attribute_bonds_whitelist_20260914.py tests/test_unattended_recovery_20260914.py tests/test_solo_rift_path_20260914.py -q`
* 结果：**180 passed, 18 subtests passed in 18.25s（100% 通过）**。
* 重点包含：`test_owned_off_whitelist_debt_lifecycle_and_release` 中 **15 组细粒度场景**（未持有、1/4~3/4 持续还债、4/4 释放、同系异名前缀强隔离等）。

### 4.2 云端审计 P1 阻断项复现与修复测试
针对审计报告确认的三大阻断项：
* 复现用例：[`tests/test_p1_blockers_reproduction_20260916.py`](file:///G:/刷刷宝/GameScript-Local/tests/test_p1_blockers_reproduction_20260916.py)
  - P1-01（4 项）：RuntimeMediator 继承 Core 调度，成功清零与时间刷新验证通过，高木材 F ↔ G 保持通过，低木材 10 步大环通过，蹭车大环不受影响；
  - P1-02（4 项）：停滞恢复拦截同系异名卡（`智力` 拦截 `智力祝福(2/3)`），未完成债务正常放行，已完成态 4/4 正常释放，既有战斗预设正常保留；
  - P1-03（4 项）：蹭车宝物全负面卡安全关闭，全未识别卡安全关闭，正向卡正常选走，共享道具（英雄卡）优先选走。
* 结果：**12 passed in 0.55s（100% 通过）**。
* 综合定向回归：82 用例全绿（含 `test_hitch_treasure_v_gate_20260913.py`、`test_solo_core_development_20260916.py` 等）。

### 4.3 全量测试套件（Full Pytest Suite）
* 命令：`python -m pytest tests/ --ignore=tests/test_live_harness_refresh.py -q`
* 结论：除已知未 rebaseline 的 harness 测试外，全工程测试套件无任何失败。

### 4.4 Live Harness 独立验证与说明
* 命令：`pytest tests/test_live_harness_refresh.py -v`
* 结果：15 passed, 3 failed（`production_code_diff == NOT_CLEAN`、`status == NOT_CLEAN`、`production_diff_status == NOT_CLEAN`）；
* 原因说明：当前分支工作区包含本轮三个 P1 阻断项的生产代码修复，尚未进行 Rebaseline（Harness 基线冻结在 `7a6c36b`），因此 Harness 的防篡改门禁准确报出 NOT_CLEAN，这是预期的守护行为，严禁私自 Rebaseline 或篡改 Harness 基准。

---

## 5. 红线与合规声明

1. **基准未篡改（No Rebaseline）**：
   - 保持 `LIVE_HARNESS_REFRESH_BASELINE = "7a6c36b"`；未手改 `GATE_BASELINE.json`；未手改 harness baseline。
2. **实机零侵入（No Real GT Run）**：
   - 本次会话严格遵守指令，零硬件物理输入，未启动任何实机 GT 脚本。
3. **极简主义（Karpathy Principles）**：
   - 零新增沉重第三方依赖；零新增抽象框架；所有修复均在既有 FSM 与 Mediator 内做紧致最小收口。
4. **远端同步状态**：
   - 本地与远端 `origin/fix/solo-live-regression-20260915` 处于完全一致的提交点 `c977ab6`。
