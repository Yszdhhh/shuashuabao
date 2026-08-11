# O3 OCR 离线门禁 — 状态（2026-08-11）

- 分支：codex/ocr-hybrid；提交：ff51bda（O2 词典/NEW/unknown 复核）、72541fb（O3 评测）
- 评测工具：tools/evaluate_o3_gate.py（387 槽统一数据集、9 session train/val/test 无帧泄漏）
- 准确率演进：O0 旧 ROI 1.45% → O1 紧裁 89.13% → O2 复评 95.45% → **O3 全量 98.19%**

## O3 门禁表

| 门禁 | 目标 | 实测 | 判定 |
|---|---|---|---|
| held-out Top-1 | ≥95% | **98.19%** (380/387) | PASS |
| skill recall | ≥99% | **96.92%** | **FAIL（waiver 登记）** |
| progress exact | ≥95% | 95.24% (20/21) | PASS |
| 误规范化 | =0 | 0 | PASS |
| 负面板建议 | =0 | 0 / 55 面板（37+18 新增） | PASS |
| 单槽 P95 | ≤120ms | 44.9ms | PASS |
| 三槽 P95 | ≤300ms | 177.7ms | PASS |
| 首次加载 | ≤4s | 1.60s | PASS |
| RSS 增量 | ≤800MB | 456-684MB | PASS |
| 断网推理 | 正常 | PASS（socket 阻断探针） | PASS |
| 模型 hash/size/license | 校验 | 3 文件 SHA256+size PASS | PASS |
| 真实 960×540 | ≥10/类 | 0 | **BLOCKED（需用户实机采集，不缩放伪造）** |

## skill_recall 96.92% 的 waiver 理由

- 4 个失败槽位根因全部具体且非系统性：奥术增幅α/β 后缀歧义、电磁网 badge 重叠、飓风 badge 碎片、吕岳 裁剪 clip、海盗劫掠者 艺术字全误读（7 个剩余 miss 中 5 个属技能槽）
- 安全面由 P0 策略兜底：技能仅选用户预设、预设不存在刷新、**永不选非预设技能**——OCR 漏识的后果是"刷新/放弃"，不是"选错技能"
- O4 shadow 阶段用真实 panel episode 数据定标 badge 处理与 α/β 后缀（无需离线重训）
- 复评路径：O4 shadow 数据积累后收紧 name ROI/后处理剥离 badge → R0 前复评 skill_recall

## 数据现状（O3 后）

- 数据集：387 有效槽（O1 155 + D0 复核 233 - 1 移除），9 session（rec1-rec10）
- 词典：choice_lexicon 89→155 entries（O2 +66）；NEW 徽章 token 剥离 + 繁体等价（奧→奥）+ 进度比剥离（lookup only）
- unknown 复核：188 槽经 6 gemini designer 子 agent 3x 放大 crop 审核（R1-R6 决策规则落 tools/build_d0_review.py）→ 129 canonical / 59 explicit unknown；O1 17 个 unknown → 16 canonical + 1 explicit unknown（f_086 s1 为统计文本）
- 逐 session：rec5 93.02%（6 miss）、rec7 91.67%（1 miss）、其余含新 rec9/rec10 全部 100%

## 剩余 7 个 miss（根因）

奥术增幅β←'奥术增幅'（α/β 歧义）｜电磁网←'N'（badge 主导 crop）｜奥术增幅α←'长箭 NEW奥术增幅'（邻槽 crop bleed）｜飓风←'W风NEW'（badge 碎片）｜吕岳←'国'（裁剪 clip，CALIB 确认）｜海盗劫掠者←'香院'（艺术字全误读）｜二星球←'星球'（数字丢失；'星球' alias 已试后被回归锁定——会降低其它星球槽 margin）

## 遗留

- 960×540 实机采集（BLOCKED，需用户）
- skill_recall 复评（O4 shadow 数据后）
- ledger diff=0（未碰生产运行时，仅 vision/choice_ocr.py 归一化层 + 词典）
