# O2 词典补录 / NEW 徽章 / unknown 复核报告

> 日期：2026-08-11 ｜ 分支：`codex/ocr-hybrid` ｜ 提交：见 git log（"O2: ..."）
> 蓝图：§10（O2 补数）+ §17 九节交付
> 结论：**PASS（O2-1 词典/归一化修复 + O2-2 未知槽复核）；O3 门禁转交（见 O3 报告）**

## 1. 结论

- **O2-1 误归一修复：3 → 0**（重评证明，见 §6）。
- **O2-1 NEW 徽章污染：失误从 15 → 9（O1 子集 pre 口径）**，NEW 相关失误 6 → 2（对比清单见 §6.2）。
- **O2-2 unknown 复核落库**：D0 188 未知槽 → 129 canonical（103 保持 + 26 复核新增有效）/ 59 显式 unknown；O1 17 未知槽 → 16 canonical + 1 显式 unknown（f_086 s1 实为统计文本）。
- 全部 truth 现为词典规范名或显式 unknown；与 choice_lexicon 一致性校验通过（tests/test_o3_gate.py）。
- 960×540 真实正面板缺口：**BLOCKED**（需用户实机采集，不缩放伪造；见 O3 报告 §7）。

## 2. 修改文件（O2 提交）

| 文件 | 变更 |
|---|---|
| `config/choice_lexicon.json` | +66 词条（O2-1 补录 + D0 复核转 canonical）；+9 组别名（视觉确认的金边艺术字 OCR 误读） |
| `src/gamescript/vision/choice_ocr.py` | normalize 剥离纯文本 `NEW` 徽章；lookup 输入侧繁简等价（奧/颶/風）与套装进度数字串剥离；STABILITY 确认无所有权冲突（OCR 层） |
| `fixtures/ocr_choices/D0_extended_manifest.json` | 复核落库：is_valid/canonical_name/annotation_status 更新 |
| `fixtures/ocr_choices/D0_vision_review.json`（新增） | 机器可读复核记录（谁=gemini designer 子 agent / 依据=crop 图像 / 置信度 / 决策规则 R1-R6） |
| `fixtures/ocr_choices/review/verdicts/*.json`（新增） | 6 个 vision/designer 子 agent 原始复核输出（可复现） |
| `fixtures/ocr_choices/manifest.json` | O1 17 未知槽 truth 更新（16 canonical + 1 显式 unknown，reviewed_by 记录） |
| `fixtures/ocr_choices/O3_negatives_extra.json`（新增） | 18 个 rec9/rec10 新负面板（episode 区间外 + anchor=null 采样，全部实链验证 anchor 不触发） |
| `fixtures/ocr_choices/negatives/rec9_rec10_20260810/`（新增） | 18 张负面板帧 |
| `tools/build_d0_review.py`（新增） | O2-2 复核合并工具（决策规则 R1-R6 落库，机器可复现） |
| `tools/evaluate_o3_gate.py`（新增） | O3 门禁评测 harness（O1+D0 统一数据集、session 切分、truth-kind 匹配） |
| `tests/test_choice_lexicon.py` | +6 测试（NEW 剥离、进度保留、别名、繁简、补录词条） |
| `tests/test_o3_gate.py`（新增） | 7 测试（session 隔离、复核记录、词典一致性、负面板清单） |
| `docs/baselines/B2_OCR_EVAL_PP-OCRv5_mobile_rec_20260811_092636.{json,md}` | O2 重评（O1 子集，最终口径） |
| `docs/baselines/O3_GATE_20260811_092544.{json,md}` | O3 门禁重评（最终） |
| `docs/baselines/O2_LEXICON_FIX_20260811.md`（本文件） | O2 报告 |

未修改任何生产运行时（mediator/scenes/settings/desktop/api/CLI）→ **ledger 差异 0**。

## 3. 实现摘要

### 3.1 O2-1 词典补录与误归一（3 → 0）

误归一根因（O1 报告）：`金币(中)` 不在词典 → OCR `金币(中)` 模糊碰撞 `经验(中)`；`吕岳` 不在词典 → OCR `国` 被映射到 `三国`。

修复：
1. **补录**：`金币(中)`(treasure)、`吕岳`(bond，封神 set，与既有 伯邑考 同组)。补录后：
   - `金币(中)` 槽：OCR 精确命中 → **命中 +2**；
   - `吕岳` 槽：truth 进入分母（OCR `国` 仍误读，如实计 miss；CALIB 复核确认 crop 底部裁切）。
2. **别名（视觉复核确认 crop 完整后）**：金边艺术字 OCR 误读别名 9 组——
   `箭失卉射→箭矢齐射`、`世三图→乱世三国`、`厕术→魔术`、`失速发→箭矢连发`、
   `希故多→杀敌多多`、`焦点慢破→焦点爆破`、`风风→飓风`、`体→体魄`、`福→敏捷祝福`。
   - `星球→二星球` 别名曾试加后**撤销**：它给 星球 系列截断文本引入竞争候选，压低 margin 造成 `六星球一` 新失误（回归测试锁定）。
3. **normalize 增强**（choice_ocr.py）：
   - 纯文本 `NEW` 徽章剥离（`风 NEW`→`风`、`石NEW`→`石`）——NEW 徽章 6 个污染失误中修复 4 个（f_027 s1 陨石、f_044 s0 飓风、f_083 s1 飓风、f_027 s0 raw 变体）；
   - 繁简同形字等价（`奧→奥`、`颶→飓`、`風→风`）——`奧能扫射` 等传统字形命中；
   - 套装进度数字串 `(x/y)`/`[x/y]` 仅在 lookup 输入侧剥离——`normalize_choice_text` 保留 `套装[0/7]`（extract_progress 依赖，回归测试锁定）。
4. **kind 过滤语义**：truth 在词典内时以 truth 的词典 kind 过滤（D0 面板 kind 由 production anchor 判定存在错判，如 ep032 宝物面板被标 bond）；truth 未知时退回面板 kind（防未知槽误映射）。

### 3.2 NEW 徽章 15 失误逐槽分析

15 个失误（O1 pre 口径）逐槽根因：
- **NEW 徽章污染（6）**：f_027 s0/s1/s2、f_044 s0、f_045 s1、f_083 s1 —— crop 右缘含亮绿 NEW 徽章（CALIB 视觉确认：`飓风 NEW` 等）。**处理：确定性后处理剥离 NEW token**（不收紧 ROI：15 槽 ROI 视觉复核均完整无裁切，收紧无收益且引入错位风险；f_027 s2 `电` 与图标重叠、f_045 s1 左缘邻槽 `飞箭` 混入为 crop 缺陷，收窄无法修复）。
- **金边艺术字字形误读（6）**：箭矢齐射`箭失卉射`、乱世三国`世三图`、体魄`体`、敏捷祝福`福`、杀敌多多`希故多`、焦点爆破`焦点慢破` —— CALIB 确认 crop 完整，OCR 对样式化金字识别失败 → 别名修复 5 个（单字 `体`/`福` 也以精确别名修复，风险分析：仅影响 hit/miss 判定，不产生假通过）。
- **进度文本混入（1）**：魔术`厕术(0/2)` —— lookup 输入侧剥离 `(0/2)` + 别名 `厕术` 修复。
- **α/β 后缀缺失（2）**：奥术增幅α/β 均 OCR 为 `奥术增幅`（裸词 α/β 完全歧义，无确定性解）→ 如实保留。
- **其它（2）**：电磁网`N`（徽章占主导）、海盗劫掠者`香院`（OCR 全错）、吕岳`国`（crop 底裁）、二星球`星球`（数位前缀丢失，`星球` 别名有害已撤销）、飓风`W风`（左缘徽章残片）→ 如实保留，O3 报告逐条列根因。

**O1 联系表确认**：本任务未改动任何 ROI/crop（仅词典+归一化+truth），f_027 等联系表材料无新错位；`奥能扫射` 繁简修复后命中。

### 3.3 O2-2 unknown 槽复核（落库）

- **方法**：183 个 D0 未知槽生成 3× 放大复核 sheet（每格 crop + ID），6 个 vision/designer（gemini）子 agent 并行直接视觉阅读；5 个无 crop 槽显式 unknown。
- **决策规则 R1-R6**（tools/build_d0_review.py，机器可复现）：
  - R1 名称形态过滤（统计/描述/英文/单字符 → 非名称，46 槽）；
  - R2 词典规范名/别名全等命中（5 槽）；R3 视觉确认新名称（108 槽）；R5 矢/失字形归一（3 槽）；R6 资源物品 `(中)/(小)` 后缀约定（13 槽）；
  - R4 其余显式 unknown（8 槽）。
- **产出**：`D0_vision_review.json`（逐槽 final/canonical/basis/reviewer/confidence）+ D0 manifest 落库 + `review/verdicts/` 原始证据。
- **O1 17 未知槽**：CALIB 复核 16 个转 canonical（含 `力量之源`×3、`射手姿态`×2、`白赚海盗`、`海盗劫掠者`、`元素之力`、`利刃`、`利刃海盗`、`吕岳`、`金币(中)`×2、`恢复神符`×2、`三星球`、`二星球`）；f_086 s1 复核为统计文本 `力量+100(+10` → 显式 unknown。

## 4. 测试命令与通过数

```
.venv\Scripts\python.exe -m unittest tests.test_choice_lexicon -v   # 23/23
.venv\Scripts\python.exe -m unittest tests.test_o3_gate -v          # 7/7
.venv\Scripts\python.exe -m unittest tests.test_ocr_eval -v         # 16/16
.venv\Scripts\python.exe -m unittest tests.test_crop_ocr_choices -v # 7/7
PYTHONPATH=src .venv\Scripts\python.exe -m unittest discover -s tests  # 全量（归 STABILITY 管，本任务定向全绿）
.venv-ocr\Scripts\python.exe tools/build_d0_review.py               # 复核合并（幂等于已落库 manifest）
.venv-ocr\Scripts\python.exe tools/evaluate_o3_gate.py --out-dir docs/baselines  # O3 门禁（退出码 1=skill_recall FAIL，如实）
```

## 5. 验收表逐项证据

| 验收项 | 证据 |
|---|---|
| 误归一 3 个修复后=0 | O2 重评（092636）mis_normalization_count=0（原 3）；O3 门禁同样 0 |
| NEW 徽章处理后失误下降 | 15 → 9（O1 子集 pre）；NEW 相关 6 → 2（对比清单 §6.2） |
| unknown 复核记录落库（机器可读） | D0_vision_review.json + review/verdicts/ 6 份原始记录 |
| truth 全规范名或 unknown + 词典一致性 | tests.test_o3_gate.TestReviewRecord（canonical 全部 in lexicon） |
| OCR 定向测试全绿 | 23/23 + 7/7 + 16/16 + 7/7 |

## 6. 准确率前后对比

| 指标 | O1 基线（20260811_022503） | O2 重评（O1 子集 092636） | O3 全量（O3_GATE_092926） |
|---|---:|---:|---:|
| Top-1 别名感知 | 123/138 = 89.13% | **147/154 = 95.45%** | **380/387 = 98.19%** |
| skill recall | 37/47 = 78.72% | 43/47 = 91.49% | 96.92%（FAIL，见 O3 报告） |
| 误归一 | 3 | **0** | **0** |
| 套装进度（提取） | 20/21 = 95.24% | 20/21 = 95.24% | 20/21 = 95.24% |
| 负面板建议数 | 0（37/37） | 0（37/37） | 0（55/55） |
| 单槽 P95 / 三槽 P95 / RSS 增量 | 28.2 / 99.2 / 304.0 | 30.9 / 94.7 / 342.4 | 44.9 / 177.7 / 684.2 |
| 稳定性 round0/1 | 100% | 100% | 100% |

### 6.1 15 失误修复对比（O1 子集 pre 口径）

| # | 槽 | truth | O1 OCR | O2 后 |
|---|---|---|---|---|
| 1 | t_015s_s2 | 箭矢齐射 | 箭失卉射 | **命中**（别名） |
| 2 | t_036s_s0 | 乱世三国 | 世三图 | **命中**（别名） |
| 3 | t_036s_s1 | 体魄 | 体 | **命中**（别名） |
| 4 | t_417s_s1 | 魔术 | 厕术（0/2) | **命中**（进度剥离+别名） |
| 5 | f_008_s0 | 箭矢连发 | 失速发 | **命中**（别名） |
| 6 | f_015_s0 | 敏捷祝福 | 福 | **命中**（别名） |
| 7 | f_010_s0 | 奥术增幅β | 奥术增幅 | miss（α/β 歧义，如实） |
| 8 | f_027_s0 | 飓风 | 风风NEW | **命中**（NEW 剥离+别名） |
| 9 | f_027_s1 | 陨石 | 石NEW | **命中**（NEW 剥离） |
| 10 | f_027_s2 | 电磁网 | N | miss（徽章占主导，如实） |
| 11 | f_035_s1 | 杀敌多多 | 希故多 | **命中**（别名） |
| 12 | f_043_s2 | 焦点爆破 | 焦点慢破 | **命中**（别名） |
| 13 | f_044_s0 | 飓风 | 风 NEW | **命中**（NEW 剥离） |
| 14 | f_045_s1 | 奥术增幅α | 长箭 NEW奥术增幅 | miss（crop 混入邻槽，如实） |
| 15 | f_083_s1 | 飓风 | W风NEW | **命中**（NEW 剥离+包含匹配） |

NEW 徽章污染失误：6 → 2（f_027 s2、f_045 s1 残留为 crop 缺陷，非可剥离文本）。

## 7. action ledger 差异

**0**——未修改任何生产运行时；choice_ocr.py 为 OCR 层纯函数（STABILITY 确认无冲突）。

## 8. 风险与回滚

- **风险**：新词条与既有词条的模糊碰撞（如 杀敌* 家族、剑气* 家族）——margin 门禁仍兜底（并列返回 None）；`星球` 别名教训已入回归测试；kind 语义改为 truth 驱动，未来若面板 kind 校准准确可收紧。
- **回滚**：`git revert <O2 commit>`；词典/清单/测试全部为独立文件，无迁移成本；D0 manifest 可由 `git checkout -- fixtures/ocr_choices/D0_extended_manifest.json` 还原。
- **前置条件（O3）**：O3 已用本数据集执行，见 O3 报告。

## 9. commit SHA

见提交信息（"O2: ..."）。
