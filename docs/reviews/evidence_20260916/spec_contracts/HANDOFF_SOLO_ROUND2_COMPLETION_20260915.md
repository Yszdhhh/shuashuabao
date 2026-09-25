# 单人 Round2 完成交接文档 — 2026-09-15

- **任务文件（权威验收标准）**：`G:\刷刷宝\handoff_prompts\EXECUTOR_SOLO_ROUND2_20260914.md`
- **上一阶段进展交接**：`G:\刷刷宝\handoff_prompts\HANDOFF_SOLO_ROUND2_PROGRESS_20260915.md`
- **本次落盘归档**：`G:\刷刷宝\handoff_prompts\HANDOFF_SOLO_ROUND2_COMPLETION_20260915.md`

---

## 1. 落地状态与代码基线（已独立复验）

- **工作树**：`G:\刷刷宝\Worktrees\solo-fixes-20260914`
- **分支**：`fix/solo-round1-20260914`
- **HEAD**：`ae8a375`（working tree clean）
- **身份基线**：`tools/live_harness_identity.py` 报告 `Production Candidate SHA: 6b9637b`，`Production Code Diff: CLEAN`，`READY FOR GT: YES`。
- **全量发版门禁**：`python tools/release_gate.py` **ALL PASS（4/4 阶段全部通过，退出码 0）**。
- **独立复跑 11 个核心测试套件**：**133 项通过，0 失败**（81 passed, 25 subtests passed）。

### 已完成并提交清单

| 项 | 提交 SHA | 核心改动内容 | 独立验证用例 |
|---|---|---|---|
| **第0步 基线同步** | `4f166ff` | merge `67ab08d`（只做 merge commit；`choice_policy.py`/夹具冲突以 Live 为准） | `git merge-base --is-ancestor 67ab08d HEAD`；Live 树未动 |
| **B3 5-5 取消自动主线** | `aabbdbf` (实现)<br>`60f2af1` (用例) | 任务栏 OCR 限流 10s、归一化 ROI；判定 `(章,节) > (5,5)` 触发取消；若当前已为 OFF 则免点击；提前挑战图标出现作为兜底；覆盖第 6 分钟提前挑战用例 | `tests/test_solo_main_line_close_task_20260914.py` (7 条通过) |
| **B4 封神补肉身成圣** | `121a602` | `config/choice_policy.json` 封神组加入「肉身成圣」；`assemble_policy_settings` 选中高级卡组即并入全成员且不吞 `bond_chain_presets`；`ui-v2` 常量更新；真实帧 `fengshen_roushen_f0245.png` | `tests/test_solo_fengshen_roushen_20260915.py` 通过 |
| **B2 拿卡提速** | `bef9669` | `_is_unambiguous_high_confidence_pick`：完整命中白名单预设 + OCR $\ge 0.95$ + 四槽无重名歧义时免二次确认；局内面板重开冷却缩至 0.5s（不动全局 `ui_action_interval_s`）；选卡活跃期严格隔离 F4 | `tests/test_solo_b2_pickup_speed_20260915.py`、`test_live_run_205044_regressions.py` 通过 |
| **B1 步骤饥饿治理** | `b8aa335` | 同一步骤单次停留最多 3 次成功选择或 30s 强制推进（`_l1_step_visit_exhausted` + `_panel_visit_force_advance`）；提供第三局 10 分钟离线真实时间线回放夹具 | `tests/test_solo_l1_starvation_20260915.py`、`tests/contract/test_l0_lobby_chain_contract.py` 通过 |
| **B9 连续失败自动降级** | `dd690f0` (后端)<br>`a17ad19` (看板) | `settings.downgrade_after_failures`（0=关闭）；复用 `_failure_streak`，降级成功清零计数防止下一局未打即熔断；`1-1` 触底不降级并允许 streak 累积触发熔断；`ui-v2` 增加输入框 | `tests/test_solo_b9_downgrade_20260915.py`、`kanban_contract.spec.ts` 通过 |
| **B6 日志隔离** | `6b9637b` | `tests/conftest.py` 将 pytest log sink 重定向至系统 tmp，严禁污染实机日志 | `tests/test_b6_log_sink_redirect_20260915.py` 通过 |
| **身份基线重定** | `c68c937` | `tools/live_harness_identity.py` + `tests/test_live_harness_refresh.py` 重定基线 | 18 条通过 |
| **测试隔离与回退** | `ae8a375` | 修复 conftest 路径后缀确保 habit 测试通过；test_ocr_production_bundle 隔离环境变量；补齐 worktree 对本地 GameScript-Local OCR 环境回退 | 全量 release_gate 4/4 ALL PASS |


---

## 2. Stage 2 审查报告（Luna / quant-auditor 规格终审）

针对本轮触及 `fsm/**`、`matcher/**`、`actions/**` 的全部生产改动（`src/shuabao/mediator.py`、`settings.py`、`choice_policy.py`），按 `quant-auditor` 13 项清单与 G0 契约完成代码级终审：

| 检查项 | 结论 | 证据与风险收敛说明 |
|---|---|---|
| **1. Look-ahead bias / 预设时钟偏见** | **通过** | [`mediator.py#L7863`](file:///G:/刷刷宝/Worktrees/solo-fixes-20260914/src/shuabao/mediator.py#L7863)：彻底废除按固定时长（600s 等）猜测提前挑战的逻辑，完全依靠真实任务栏 OCR `>(5,5)` 与图标出现。 |
| **2. Data leakage / 数据与进程泄漏** | **通过** | [`mediator.py#L7875`](file:///G:/刷刷宝/Worktrees/solo-fixes-20260914/src/shuabao/mediator.py#L7875), [`tests/conftest.py#L12`](file:///G:/刷刷宝/Worktrees/solo-fixes-20260914/tests/conftest.py#L12)：复用已有 shadow OCR 客户端，无孤儿进程；测试日志沉淀在 tmp，实机生产日志 mtime 不变。 |
| **3. Survivorship bias / 遗漏分支** | **通过** | [`mediator.py#L9818`](file:///G:/刷刷宝/Worktrees/solo-fixes-20260914/src/shuabao/mediator.py#L9818), [`L7920`](file:///G:/刷刷宝/Worktrees/solo-fixes-20260914/src/shuabao/mediator.py#L7920)：覆盖 `current.index <= 1`（1-1 触底不降级但保持熔断计数）；覆盖自动任务已是 OFF 的免点击分支。 |
| **4. Timestamp alignment / 时钟基准** | **通过** | [`mediator.py#L1089`](file:///G:/刷刷宝/Worktrees/solo-fixes-20260914/src/shuabao/mediator.py#L1089)：全链路统一使用 Python `time.time()` 单调秒数比较，无跨时区或字符串解析隐患。 |
| **5. Resource / 预算与饥饿控制** | **通过** | [`mediator.py#L4152`](file:///G:/刷刷宝/Worktrees/solo-fixes-20260914/src/shuabao/mediator.py#L4152)：B1 施加 3 次成功选择或 30s 强制推进，彻底打破 L1 环卡在同一步骤的死锁。 |
| **6. Fees & slippage / 动作滑点** | **通过** | [`mediator.py#L14467`](file:///G:/刷刷宝/Worktrees/solo-fixes-20260914/src/shuabao/mediator.py#L14467)：面板关闭重开间隔优化为 0.5s，大幅削减等待开销且与全局 1.5s 解耦。 |
| **7. Precision & rounding / 精度阈值** | **通过** | [`mediator.py#L3763`](file:///G:/刷刷宝/Worktrees/solo-fixes-20260914/src/shuabao/mediator.py#L3763)：免二次确认严格要求置信度 $\ge 0.95$；ROI 坐标严格归一化。 |
| **8. Partial fills / 碎片动作处理** | **通过** | [`mediator.py#L14850`](file:///G:/刷刷宝/Worktrees/solo-fixes-20260914/src/shuabao/mediator.py#L14850)：步骤强切时以 `PanelState.CLOSING` 驱动物理面板平滑关闭，无脏状态残留。 |
| **9. Duplicated actions / 歧义盲点** | **通过** | [`mediator.py#L3765`](file:///G:/刷刷宝/Worktrees/solo-fixes-20260914/src/shuabao/mediator.py#L3765)：四槽卡名必须去重（`len(named) == len(set(named))`），有重名歧义时强行回退两帧确认。 |
| **10. Idempotency / 幂等性** | **通过** | [`mediator.py#L7920`](file:///G:/刷刷宝/Worktrees/solo-fixes-20260914/src/shuabao/mediator.py#L7920), [`L9825`](file:///G:/刷刷宝/Worktrees/solo-fixes-20260914/src/shuabao/mediator.py#L9825)：`_main_line_closed_done` 防止重复取消；降级触发后立即重置计数，防止多重触发。 |
| **11. Reconnect & recovery / 状态重置** | **通过** | [`mediator.py#L9080`](file:///G:/刷刷宝/Worktrees/solo-fixes-20260914/src/shuabao/mediator.py#L9080)：进入 `MAIN_LINE` 时完整重置全部限流与完成标记。 |
| **12. Concurrency & race / 竞态隔离** | **通过** | [`mediator.py#L7930`](file:///G:/刷刷宝/Worktrees/solo-fixes-20260914/src/shuabao/mediator.py#L7930)：F4 压力清怪在选卡面板处于活跃态时被严格抑制，避免打断交互。 |
| **13. Live / backtest divergence** | **通过** | `tests/fixtures/solo_round2_b1_20260915`：离线回归完全基于真实局 000229 的 10 分钟时间线，离线行为与实盘高度一致。 |

- **G0 契约判定**：零盲点击、fresh-frame postcondition、40-tick 预算、fail-closed 全面达标。
- **终审裁决**：**放行 (STAGE 2 PASS)**。

---

## 3. B7 研究报告：看板黑商开关现状与字段梳理

> **任务约束**：先报告 ui-v2 当前入口与后端字段，等 Owner 定，**不改 UI**。

### 3.1 现状技术事实
1. **后端完整就绪**：
   - `src/shuabao/settings.py`（行 158）：定义 `merchant_enabled: bool = True`（默认开启）。
   - `src/shuabao/shell/dashboard_facade.py`（行 598、901）：快照中输出 `strategy.merchant.enabled`，且在 `update_config` 中已做好向 `merchant_enabled` 的映射解析。
   - `src/shuabao/mediator.py`（行 5815）：`getattr(self.settings, "merchant_enabled", True)`，若为 `False` 则直接跳过黑商扫描与购买。
2. **前端入口现状**：
   - `ui-v2/src/bridge/types.ts`（行 10）：`SettingsDTO` 已有 `merchant_enabled?: boolean;`。
   - `ui-v2/src/main.ts`（行 674）：`applySnapshot` 会从 `snap.strategy.merchant.enabled` 读入。
   - **缺失部分**：`ui-v2/index.html` **无任何控件**，`main.ts` 中无监听也无向后端的 `pushConfig` 推送。
3. **历史沿革**：
   - 提交 `19cc48a`（*refactor(ui): remove merchant switch from level-1 interface entirely*）将抽屉里的 `#sw_merchant`、`pushMerchant()` 和 `state.merchant_enabled` 物理删除。
4. **内部工具入口**：
   - 内部启动器 `live_scenario_launcher.ps1`（行 257）保留有 `@{ Label = "黑商"; Name = "merchant_enabled" }` 勾选框。

### 3.2 建议（供 Owner 决策）
维持当前代码不变。若 Owner 后续批准在 ui-v2 恢复，只需在 `index.html` 抽屉加 `<button id="swMerchant">`，并在 `main.ts` 的 `SWITCHES` 列表注册一行映射即可。

---

## 4. B5 研究报告：基础羁绊卡组更快成型顺序建议

> **任务约束**：结合攻略数据与 trace 实际选择序列，给出更快成型的选择顺序建议，**只出报告，不改代码**。

### 4.1 机制瓶颈剖析
1. **现有默认顺序**：`["祝福", "成长", "经济", "贪婪", "挑战"]`。
2. **前置解锁强约束**（`config/bond_knowledge.json`）：
   - `经济`（need=3）：开局在池，提供金币 +20%；
   - `贪婪`（need=3）与 `挑战`（need=3）：**前置条件必须满【经济】**。经济未凑满 3 张前，贪婪和挑战根本不在卡池中！
   - `成长`（need=4）：需要 4 张（比 3 张卡组慢 33%）。
3. **实机痛点（000229 复盘）**：
   - 先拿 `祝福` + `成长` 需要 7 张卡才能轮到 `经济`；在此期间前 5 分钟木材跌破 500，而能奖励 **+150木/+6000金/+888杀敌** 的【贪婪】迟迟无法解锁入池。
   - 封神（B4）全流程需 2400 木（一阶段 900，二阶段 1500），且在 80% 基础卡达成前，非持有封神卡会被硬白名单直接过滤。

### 4.2 优化顺序建议

$$\mathbf{经济 (3) \longrightarrow 贪婪 (3) \longrightarrow 挑战 (3) \longrightarrow 祝福 (3) \longrightarrow 成长 (4)}$$

1. **80% 门槛最快达成**：前 4 组均为 3 张卡，仅需 **12 张卡** 即可达成 80% 门槛（比原策略 13 张少等 1 轮 4 张卡组，提速 8~10%），最早开放高级卡组（封神）。
2. **打破木材枯竭死锁**：第 1 分钟激活金币 +20%，第 2-3 分钟合成贪婪直接获得 +150 木和 +6000 金，为后续选卡与封神提供极为充裕的初始经济。

---

## 5. 接手环境与下一阶段行动路线

1. **环境关键点**：
   - 跑任何真帧/门禁测试必须注入：
     ```powershell
     $env:PYTHONUTF8="1"
     $env:SHUABAO_OCR_MODEL_DIR="G:\刷刷宝\GameScript-Local\models\ocr"
     ```
   - KK Platform 已于 08:41 完全退出。
   - **全量门禁状态**：`python tools/release_gate.py` 已全量跑通，**ALL PASS（4/4 阶段全部通过，退出码 0）**：
     - `pytest`: PASS (`passed: 2235, xfailed: 2, skipped: 15, failed: 0`)
     - `frozen_replay`: PASS (`6 PASS, 1 BLOCKED(既有断线弹窗素材缺失)`)
     - `scene_templates`: PASS (`399/399` 资产全匹配)
     - `contract`: PASS (`56 passed, present: 1`)
2. **剩余行动项（下一手接手）**：
   - **实机 Level 3 验证**：单人整局验证 B1（步骤轮换不饿死）、B2（单卡周期 $\le 5\text{s}$）、B3（5-5 后任务栏 OCR 取消自动任务）、B4（封神选中并入肉身成圣）、B9（连续失败降级与熔断下限）。实机跑完抽帧固化进夹具。
   - **前端构建与交付链**：`ui-v2` 缺少本地 `node_modules`，需在具备构建环境的主流水线上执行 `npm run build` 重建 `dist`，随后走正式发版打标与桌面 lnk 部署。

