# O0 OCR 评测可信度修复报告

> 日期：2026-08-11 ｜ 分支：`codex/ocr-hybrid` ｜ 提交：`fb8818c`（"O0: ..."）
> 蓝图：§9 O0（评测可信度）+ §19 给 OCR-EVAL 的第一轮任务
> 结论：**PASS（评测可信度）；生产准确率门禁如实 FAIL（1.45%，等待 O1 ROI 修复与 O2 数据）**

## 1. 修改文件（O0 提交 fb8818c）

| 文件 | 变更 |
|---|---|
| `models/ocr/MODEL_MANIFEST.json` | 修复为合法 JSON（原文件两个 model 对象之间缺逗号无法 parse）；schema_version 2，字段含 name / files{sha256,size_bytes} / license / source_url / model_dir / present_in_repo |
| `tools/evaluate_choice_ocr.py` | 重写评测口径（见 §3） |
| `requirements-ocr.txt` / `requirements-ocr.lock` | 新增 OCR 依赖锁（paddlepaddle 3.3.1 / paddleocr 3.7.0 / paddlex 3.7.2，PyPI，74 包 freeze） |
| `tests/test_ocr_eval.py` | 新增 16 个定向测试 |
| `docs/baselines/B2_STATUS_20260810.md` | 追加 §5 O0/O1 状态 |
| `docs/baselines/B2_OCR_EVAL_PP-OCRv5_mobile_rec_20260811_012330.{json,md}` | O0 基线重评报告（旧 ROI、新口径） |

## 2. 实现摘要

### 2.1 MODEL_MANIFEST 合法化（O0-1）
原 `MODEL_MANIFEST.json` 不是合法 JSON（models 数组两对象间缺逗号）。修复为 schema 2：
- mobile 模型：`files` 逐文件记录真实 SHA256 与字节大小（inference.json 217724B /
  inference.pdiparams 16458665B / inference.yml 148345B），license Apache-2.0，
  source_url 官方 bcebos 链接，model_dir，archive 记录 tar SHA256/大小；
- server 模型：`present_in_repo=false`（文件不入库），hash gate 不校验 absent 模型。

### 2.2 evaluator 真实校验（O0-2）
- `verify_model_files()` 逐文件计算 SHA256 + 字节大小，与 manifest 核对；任一文件缺失/大小不符/
  哈希不符 → hash gate FAIL，报告逐文件证据（实际 vs 期望值）。
- 篡改任一模型字节 → gate FAIL 由单测证明（tests/test_ocr_eval.py TestHashGate）。
- 模型源目录与 ASCII 暂存副本都校验（防御复制损坏）。

### 2.3 repo HEAD（O0-3）
`repo_head_info()` 执行 `git rev-parse HEAD` / `branch --show-current` / `status --porcelain`，
写入报告 `repo_head`；非空是门禁之一（`repo_head_recorded`）。

### 2.4 准确率分母 = 独立有效槽位（O0-4）
- 旧版：两轮推理 276 条样本全部进分母（155 槽 × 2 = 310，in-lex 138 × 2 = 276）——分母倍增。
- 新版：round 0 每 (entry_id, slot_index) 唯一一条进准确率；round 1 只进 latency/稳定性
  （round0 vs round1 文本一致率 155/155 = 100%）。
- 单测证明分母不随 rounds 倍增（TestAccuracyDenominator）。

### 2.5 逐 session 指标（O0-5）
round-0 唯一槽位按 `session_id` 分组输出 Top-1 命中/准确率/unknown/unverified/面板数。

### 2.6 词典外 truth 独立计 unknown（O0-6）
- `truth_status()`：in_lexicon / alias_covered（别名纠正后进分母）/ unknown（词典外）。
- unknown 槽独立计数（17 槽），不进准确率分母；误归一（unknown→词典名）单独计 mis_norm 门禁。
- 别名纠正示例：奥术激光 → 奥数激光（lexicon alias），纠正后进分母。

### 2.7 负面板 触发/分类/建议 链（O0-7）
- 复刻 `mediator._selection_anchor`（10 模板、threshold 0.70、scales 0.85-1.2、ROI 0.20-0.45-0.80-0.80、
  位置校验 fx∈[0.2w,0.8w]、fy≥0.5h）与 `_classify_choice_panel`（bond/treasure/skill/card 判定顺序）。
- 37 个真实负面板全部实际推理：**建议数 0/0，37/37 PASS**（锚点均未触发）。
- 逐面板输出：分辨率、原因、anchor 模板/分数、分类、建议数、结论（见报告 §5b）。

### 2.8 OCR 依赖锁（O0-8）
`requirements-ocr.txt`（顶层 pin + 下载源 PyPI）+ `requirements-ocr.lock`（pip freeze 74 包）。

## 3. O0 基线重评结果（旧 ROI，新口径）

| 指标 | 旧报告 | O0 修正 |
|---|---:|---:|
| Top-1（别名感知） | 4/276 = 1.45%（分母倍增） | **2/138 = 1.45%**（独立槽位） |
| 误归一 | 0 | 0 |
| 负面板建议数 | 未评测 | **0（37/37 PASS）** |
| 模型 hash gate | 硬编码 PASS | **真实校验 PASS**（3 文件哈希+大小） |
| repo_head | None | **非空 = 运行时刻 HEAD** |
| 单槽 P95 / 三槽 P95 / RSS | 56.0 / 113.1 / 138.4 | 26.3 / 82.3 / 55.0 |
| 套装进度 | 0% | 0%（ROI 错位，O1 修正） |

**结论：1.45% 是裁剪错位造成的评测假象（O1 实证），不是模型质量结论。生产准确率门禁如实 FAIL。**

## 4. 测试

```
.venv\Scripts\python.exe -m unittest tests.test_ocr_eval -v          # 16/16 PASS
.venv\Scripts\python.exe -m unittest tests.test_crop_ocr_choices -v  # 7/7 PASS（O1 裁剪器）
PYTHONPATH=src .venv\Scripts\python.exe -m unittest discover -s tests  # 236 通过 / 2 预存 expected failures
```

## 5. 验收表

| 验收项 | 证据 |
|---|---|
| manifest 可 parse | tests.test_ocr_eval.TestModelManifest（json.loads + load_model_manifest） |
| 篡改模型字节 → hash gate 失败 | TestHashGate.test_tampered_model_fails_hash_gate（翻转 pdiparams 首字节） |
| 分母 = 独立 valid slots | TestAccuracyDenominator（rounds=2 时 denominator=3 非 6） |
| repo_head 非空 = 当前提交 | TestRepoHead（与 git rev-parse HEAD 一致） |
| 负面板真实推理且建议数=0 | 报告 §5b：37/37，全链实测 |
| 定向测试全绿 | 16/16（O0）+ 7/7（裁剪器） |
| 全量测试 | 236 OK / 2 预存 expected failure |

## 6. 前后对比与门禁

准确率 1.45% →（O1 修复后 89.13%，见 O1 报告）。O0 阶段本身不改 ROI，准确率门禁保持 FAIL（如实）。

## 7. action ledger

未修改任何生产运行时 → **ledger 差异 0**。

## 8. 风险与回滚

- 风险：误归一计数在 O1 修复 bbox 后上升（更宽的 crop 带入更多文本）——如实计入门禁；
- 回滚：`git revert fb8818c`（纯工具/测试/文档，无迁移成本）。

## 9. 前置条件

O1（ROI 修复）→ O2（数据/词典补录，含 金币(中)/恢复神符 等 17 个 unknown truth 的核实入典）。
