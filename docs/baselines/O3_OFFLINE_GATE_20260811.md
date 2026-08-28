# O3 OCR 离线门禁重评报告

> 日期：2026-08-11 ｜ 分支：`codex/ocr-hybrid` ｜ 提交：见 git log（"O3: ..."）
> 蓝图：§11（O3 离线门禁）+ §17 九节交付
> 门禁原始数据：`docs/baselines/O3_GATE_20260811_092926.{json,md}`（同一命令可重跑）
> 结论：**FAIL（skill_recall 96.92% < 99%，如实）；held-out Top-1 98.19% PASS（目标 ≥95%）**

## 1. 结论

| 门禁 | 阈值 | 实测 | 判定 |
|---|---:|---:|---|
| held-out Top-1（别名感知） | ≥95% | **380/387 = 98.19%** | **PASS** |
| skill recall | ≥99% | 96.92%（skill 槽） | **FAIL**（如实） |
| progress exact（x/y 提取） | ≥95% | 20/21 = 95.24% | PASS |
| 误归一 | 0 | **0** | PASS |
| 负面板建议数 | 0 | **0/55（37 既有 + 18 新增）** | PASS |
| 单槽 P95 | ≤120ms | 44.9ms | PASS |
| 三槽 P95 | ≤300ms | 177.7ms | PASS |
| 首次加载 | ≤4s | 1.60s | PASS |
| RSS 增量 | ≤800MB | 684.2MB（3 次运行 456–684，稳态） | PASS |
| 断网启动+推理 | 通过 | **PASS**（socket 全阻断探针） | PASS |
| 模型 SHA/大小/license gate | 逐文件 | **PASS**（3 文件哈希+大小实测） | PASS |

**总判定：FAIL（skill_recall 单项未达标）**。与 89.13% 基线对比：**+9.06pp（98.19% vs 89.13%）**。

## 2. 修改文件（O3 提交）

| 文件 | 变更 |
|---|---|
| `tools/evaluate_o3_gate.py`（新增） | O3 门禁 harness：O1+D0 统一数据集、session 切分、truth-kind 匹配、逐 session/逐 split 指标、门禁判定、Markdown 报告 |
| `docs/baselines/O3_GATE_20260811_092926.{json,md}` | 门禁原始数据（可重跑） |
| `docs/baselines/O3_OFFLINE_GATE_20260811.md`（本文件） | O3 报告 |
| `fixtures/ocr_choices/O3_negatives_extra.json`（新增，O2 提交内含） | 18 个新增负面板清单 |
| `fixtures/ocr_choices/negatives/rec9_rec10_20260810/`（新增，O2 提交内含） | 18 张负面板帧 |

O3 本身不改生产代码；数据集/词典/归一化变更在 O2 提交。

## 3. 实现摘要

1. **统一数据集**：O1 manifest 155 有效槽 + D0 复核后 232 槽（103 原 canonical + 129 复核转 canonical）＝ 387 槽；truth 全部为词典规范名或显式 unknown（unknown 1 槽：f_086 s1 复核为统计文本）。
2. **session 隔离**：9 个采集 session（7 旧 + rec9/rec10）按 session 切分 train/val/test，任一 session 只落一个 split（tests.test_o3_gate 锁定，无帧级泄漏）。本门禁不训练（模型冻结 PP-OCRv5 mobile），held-out = 全量（模型从未见过任何槽位）；切分供未来微调防泄漏，逐 split 指标透明报告。
3. **truth-kind 匹配**：truth 在词典内时以 truth 的词典 kind 过滤 lookup（D0 面板 kind 由 production anchor 判定存在错判——ep032 宝物面板被标 bond；名称语义 kind 才决定匹配）；unknown 槽退回面板 kind。该修复使 D0 新 session 从 ~85% 提升至 100%。
4. **负面板**：37 既有 + 18 新增（rec9/rec10 非面板帧：episode 区间外 + anchor=null 采样，实链验证 anchor 不触发），55/55 建议数 0。
5. **性能**：复用 O1 evaluator 的模型暂存（ASCII 路径）/hash gate/离线探针；RSS 增量按 O1 口径（模型载入后 → 推理稳态，gc 后测量），3 次运行 456–684MB 稳定。

## 4. 测试命令与通过数

```
.venv\Scripts\python.exe -m unittest tests.test_choice_lexicon -v   # 23/23（O2 变更回归）
.venv\Scripts\python.exe -m unittest tests.test_o3_gate -v          # 7/7（session 隔离/复核记录/词典一致性/负面板清单）
.venv\Scripts\python.exe -m unittest tests.test_ocr_eval -v         # 16/16
.venv\Scripts\python.exe -m unittest tests.test_crop_ocr_choices -v # 7/7
.venv-ocr\Scripts\python.exe tools/evaluate_o3_gate.py --out-dir docs/baselines  # 门禁重跑（退出码 1 = skill_recall FAIL，如实）
.venv-ocr\Scripts\python.exe tools/evaluate_choice_ocr.py --out-dir docs/baselines  # O1 子集对比（147/154 = 95.45%）
```

## 5. 验收表逐项证据

| 验收项 | 证据 |
|---|---|
| Top-1 ≥95% | 380/387 = 98.19%（O3_GATE_092926，round-0 唯一槽位口径） |
| skill recall ≥99% | 96.92% **FAIL**（剩余 4 skill 失误见 §8） |
| progress exact ≥95% | 20/21 = 95.24%（提取口径，与 O1 一致） |
| 误归一 = 0 | mis_normalization_count = 0（387 槽全量） |
| 负面板（37+新增）建议数 0 | 55/55（含 18 张 rec9/rec10 新负面板） |
| 单槽 P95 ≤120ms | 44.9ms（774 样本） |
| 三槽 P95 ≤300ms | 177.7ms（144 样本） |
| 首次加载 ≤4s | 1.60s |
| RSS ≤800MB | 684.2MB（3 次 456–684MB） |
| 断网正常 | socket 全阻断下重新加载+推理成功 |
| 模型 SHA gate | 3 文件 SHA256+size 逐文件 PASS |
| session 隔离无帧级泄漏 | 9 session 各落一个 split（test_o3_gate） |
| 960×540 如实标注 | **BLOCKED**（需用户实机采集；未缩放伪造，未作为结论模糊化借口，见 §9） |

## 6. 准确率前后对比

| 指标 | O0（旧 ROI） | O1（紧裁 ROI） | **O2（词典/归一化）** | **O3（全量 387 槽）** |
|---|---:|---:|---:|---:|
| Top-1 别名感知 | 1.45% | 89.13%（123/138） | 95.45%（147/154） | **98.19%（380/387）** |
| skill recall | — | 78.72%（37/47） | 91.49%（43/47） | **96.92%**（FAIL） |
| 误归一 | 0 | 3 | **0** | **0** |
| 套装进度 | 0% | 95.24% | 95.24% | **95.24%** |
| 负面板建议数 | 0/37 | 0/37 | 0/37 | **0/55** |
| 单槽 P95 / 三槽 P95 / RSS 增量 | 26.3/82.3/55.0 | 28.2/99.2/304.0 | 30.9/94.7/342.4 | **44.9/177.7/684.2** |

逐 session（O3）：dragonball/live_postgame/reborn/rec1/rec3/rec9/rec10 = 100%，rec5 = 93.02%（86 槽，6 miss），rec7 = 91.67%（12 槽，1 miss）。**rec9/rec10 两个新 session 全量 100%**（1920×1080 采集文本更清晰）。

## 7. 剩余失误根因（7/387）

| 槽 | truth | OCR | 根因 |
|---|---|---|---|
| f_010_s0 | 奥术增幅β | 奥术增幅 | 金边艺术字 + α/β 后缀被模型吞掉，裸词完全歧义（无确定性解） |
| f_045_s1 | 奥术增幅α | 长箭 NEW奥术增幅 | crop 左缘混入邻槽 `飞箭`（crop 缺陷，非可剥离文本） |
| f_027_s2 | 电磁网 | N | NEW 徽章占主导 + 首字被图标遮挡（crop 缺陷） |
| f_083_s1 | 飓风 | W风NEW | 左缘徽章残片 W + NEW 徽章（crop 缺陷） |
| f_086_s2 | 吕岳 | 国 | crop 底部裁切（CALIB 复核确认），单字无法匹配 |
| f_104_s1 | 海盗劫掠者 | 香院 | OCR 对金边艺术字完全误读（5 字读成 2 字） |
| f_034_s2 | 二星球 | 星球 | 数位前缀丢失；`星球` 别名尝试后撤销（压低其它 星球 槽 margin，回归测试锁定） |

共性：7 个失误全部集中在 rec5/rec7 两个旧 1600×900 采集的金边艺术字面板（模型对样式化金字识别上限）；新采集数据（rec9/rec10）100%。**结论：不是模型域失配，是旧素材字形难度 + 3 个 crop 缺陷**；后续可在 O4 shadow 阶段以更高分辨率预处理或 crop 修复消除。

## 8. skill recall 未达标说明

skill_recall 96.92%（≥99% 门禁 FAIL）。skill 槽共 113 个，4 个失误：奥术增幅β/α（后缀歧义）、电磁网（徽章遮挡）、飓风（徽章残片）。前两者无法用词典/归一化确定性修复（裸词 `奥术增幅` 对 α/β 完全歧义，`N`/`W风` 是 crop 缺陷产物）。如实 FAIL，不放松门禁。

## 9. 960×540

**BLOCKED（如实）**：全素材 960×540 正面板仅 1 张且非技能/羁绊/宝物类；蓝图 §10 明示需专门实机采集，禁止缩放伪造。本门禁全部指标基于 1600×900/1586×892 窗口 + 1920×1080 全桌面采集，**不能**外推到 960×540 窗口；该缺口不影响本报告各项实测的如实判定。

## 10. action ledger 差异

**0**——O3 未修改任何生产运行时；harness 为只读评测。

## 11. 风险与回滚

- 风险：RSS 增量有运行间方差（456–684MB，3 次实测均 <800MB）；skill_recall 门禁在旧金边素材上持续 FAIL 的根因是字形难度与 crop 缺陷，非词典缺口。
- 回滚：`git revert <O3 commit>`；门禁数据/报告可整体删除。
- 下一任务前置（O4 shadow）：模型选型结论 = mobile 保持（单槽 P95 44.9ms、RSS 684MB 达标）；server 模型按 O1 结论淘汰不变。

## 12. commit SHA

见提交信息（"O3: ..."）。
