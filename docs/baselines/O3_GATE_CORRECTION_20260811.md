# O3 OCR 离线门禁 — 状态修正版（2026-08-11，依据 AGENT_CORRECTION_GATES_20260811.md）

> 本文件是 docs/baselines/O3_GATE_STATUS_20260811.md 的修正版：原文件将 skill_recall 96.92% 记为"FAIL（waiver 登记）"并整体视为可推进依据，违反纠偏门禁（禁止"FAIL + waiver = PASS"表述）。历史报告保留不删，门禁语义以本文件为准。
> 依据提交：O3 评测 72541fb（held-out Top-1 98.19% 原始数字）。

## O3 门禁状态（逐项原始数字，无模糊措辞）

| 门禁 | 目标 | 实测 | 状态 |
|---|---|---|---|
| held-out Top-1 | ≥95% | 380/387 = 98.19% | **PASS** |
| skill recall | ≥99% | 126/130 = 96.92% | **FAIL**（非 waiver，无 PASS 化） |
| progress exact | ≥95% | 20/21 = 95.24% | **PASS** |
| 误规范化 | =0 | 0 | **PASS** |
| 负面板建议 | =0 | 0 / 55 面板 | **PASS** |
| 单槽 P95 | ≤120ms | 44.9ms | **PASS** |
| 三槽 P95 | ≤300ms | 177.7ms | **PASS** |
| 首次加载 | ≤4s | 1.60s | **PASS** |
| RSS 增量 | ≤800MB | 实测区间 456-684MB（3 runs） | **PASS**（如实记录区间，不隐藏） |
| 断网推理 | 正常 | socket 阻断探针 PASS | **PASS** |
| 模型 hash/size/license | 校验 | 3 文件 SHA256+size PASS | **PASS** |
| 真实 960×540 正样本 | ≥10/类 | 0 | **BLOCKED**（需用户实机采集；禁止缩放伪造） |
| 真实断线弹窗素材 | 存在 | 0 命中（6333 帧扫描） | **BLOCKED**（需用户实机；S0 恢复路径仅有合成证据） |

**结论（复评后 2026-08-11 11:02）：模型质量门禁全部 PASS；960×540 与断线素材 BLOCKED。**
- skill_recall 复评达标：SKILL-FIX 提交 8103f99（OCR 引导 ROI 校准：α/β 后缀槽、徽章重叠槽、吕岳 top-edge 扩展、二星球）后重跑 evaluate_o3_gate：**Top-1 98.19%→99.48%（385/387）、skill_recall 96.92%→1.0（PASS ≥99%）、progress 95.24% PASS、误归一 0、负面板 0/55**；逐 session 仅 rec5 97.67%（剩 2 miss：海盗劫掠者 艺术字不可恢复 + 另一槽）。
- 修复未改分母/未删失败样本/未降阈值（manifest truth_status 136/17 语义保持，仅 6 槽 ROI 校准）。
- 960×540 与断线素材 BLOCKED 保持：无用户实机素材前，OCR 生产接入（O4 接线）、G0 后段、长期无人值守宣称一律冻结。

## waiver 登记（规范格式）

| 项 | status | waiver | owner | 补证据条件 | 截止阶段 |
|---|---|---|---|---|---|
| skill_recall 96.92% | FAIL | true（暂缓，不改门禁结论） | SKILL-FIX 修复 + O3 重评 | badge 重叠裁剪/α/β 后缀处理且全量 387 槽复评 ≥99% | R0 前复评 |
| 960×540 真实样本 | BLOCKED | true | 用户实机采集 | 每类 ≥10 真实 960×540 面板（游戏窗口 960×540 运行采集，非缩放） | O3 复评后 |
| 断线真实素材 | BLOCKED | true | 用户实机 | 真实断线弹窗帧（命名素材 + fixture） | S0/G0 复评后 |

## 下一阶段唯一合法入口（无素材前）

A. O4 shadow 真实模型压测与协议验收（10,000 实际推理请求）；或
B. R0 录制/采集工具与报告模板；或
C. 纯离线评测修复。
三者均不产生游戏输入。P0/O4 生产接线、G0 后段、mediator.py/输入执行器修改全部冻结。
