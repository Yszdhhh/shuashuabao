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
| **Main 基线** | `3c4c594` | 生产主线基线（Merge PR #25） |
| **当前代码 HEAD** | `c977ab6` (`c977ab6bc559fd630f022f1569b8ed1923a1daa7`) | 核心代码冻结点，工作区干净（Clean） |
| **Harness 基线** | `7a6c36b` | 严格保持冻结，**未 Rebaseline** |
| **验证总状态** | **CODE GO / READY FOR AUDIT** | 单元测试全绿（2312 通过，0 失败），实机 GT 处于 HOLD |

---

## 2. 变更范围与 Diff 概况

相较于 `origin/main`，本分支共包含 16 个增量提交，总计代码变更统计：
```text
18 files changed, 2590 insertions(+), 174 deletions(-)
```

### 核心生产代码文件分布：
1. [`src/shuabao/mediator.py`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/mediator.py) (+817, -120):
   - HUD Opportunistic 微操互斥门禁与单 Tick 输入保证；
   - 核心发育（Core Development）资源水位阶梯调度（木材 1/2/5 档）、高木材防饿死退避契约；
   - 英雄卡使用业务门禁（`_evolve_ok_this_cycle=True` 强防守）；
   - 装备 FSM 独占推进（`equipment_fsm.pending_slot is None`）与词缀弹窗互斥；
   - 传家宝 120s 超时 ALIVE 证据否决权（Veto）。
2. [`src/shuabao/choice_policy.py`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/choice_policy.py) (+88, -2):
   - 引入严格的规范卡名同一性判定 [`canonical_bond_identity()`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/choice_policy.py#L328) 与 [`same_bond_identity()`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/choice_policy.py#L341)；
   - 彻底剥离卡牌同一性与预设模糊子串匹配（[`matches_bond_preset()`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/choice_policy.py#L350)）；
   - 已持有/白名单外羁绊债务 1/4 ~ 4/4 完整生命周期闭环与完成态自动释放；
   - 容量过滤候选人（`_bond_capacity_candidates`）精准豁免真正同卡合成，拦截异名族系卡。
3. [`src/shuabao/policy/equipment_fsm.py`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/policy/equipment_fsm.py) (+6, -1):
   - 修复装备右键升级时序与 pending 解锁状态判定。
4. [`src/shuabao/runtime_mediator.py`](file:///G:/刷刷宝/GameScript-Local/src/shuabao/runtime_mediator.py) (+2, -2):
   - 状态重置与周期生命周期保持。

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

### 3.3 英雄卡（Hero Card）强业务门禁
* **历史隐患**：代码曾试图以“当前画面没识别到 evolve 按钮”作为依据去使用英雄卡，可能在过渡帧或遮挡时误点。
* **硬门禁收敛**：
  - 强制复用 `_evolve_ok_this_cycle == True` 作为唯一业务前置条件；
  - 若未确认进化成功，即使背包里存在英雄卡，也**绝对产生 0 次点击**；
  - 进化确认成功后，才允许向背包英雄卡槽位发送右键动作，并立刻建立 `WAIT_HERO_CHOICE` 独占事务，防止被拾取或神器打断。

### 3.4 核心发育（Core Development）资源水位与防饿死调度
* **木材消耗阶梯**：
  - `wood < _bond_next_price()`：禁止打开 F 面板，避免无意义空开；
  - `draw_price <= wood < 300`：允许开启 F，但单次最大选卡上限 `cap = 1`；
  - `300 <= wood < 1000`：单次最大选卡上限 `cap = 2`；
  - `wood >= 1000`：高木材狂暴模式，单次访问上限 `cap = 5`。
* **对称测试与退避保护**：
  - `wood >= 1000` 时，若因为候选卡均不在预设而主动关闭 F 面板，**严禁设置 30s 的 `_bond_idle_until`**，避免因候选不合规导致大量积压木材被饿死 30 秒；保留 `wood < 1000` 下的普通冷却。
* **技能积压紧急调度**：
  - 技能积压点数 $\ge 8$ 视为战斗力坍塌极危状态，强制从主发育循环中抢占 1 次技能提升；
  - 积压 4~7 档提供优先调度；加入 aging 时间衰减机制，防止非核心步骤永久饿死。

### 3.5 传家宝 120s 超时与 Boss ALIVE 否决权
* **语义收紧**：传家宝 120s 超时不得被标记或视为“Boss CLEAR”；
* **正面存活否决**：若检测器识别到明确的 Boss 血条（`_solo_boss_is_alive` 返回 True），超时到达时一票否决转场与秘境输入，记录告警并安全挂起，绝不将存活 Boss 误当做通关。

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

### 4.2 全量测试套件（Full Pytest Suite）
* 命令：`python -m pytest tests/ --ignore=tests/test_live_harness_refresh.py -q`
* 运行耗时：**909.40 秒（约 15 分 09 秒）**
* 最终结果：
  ```text
  2312 passed, 3 skipped, 2 xfailed, 1 warning, 250 subtests passed in 909.40s
  0 FAILED
  ```
* 结论：除已知且符合预期的测试外，全工程 2312 个用例无任何失败与破损。

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
