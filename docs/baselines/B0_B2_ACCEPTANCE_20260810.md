# B0-B2 验收指引（对照蓝图 §18 十项验收清单）

> 日期：2026-08-10 | 分支：`codex/ocr-hybrid` | HEAD：见 git log
> 用法：逐项核对证据；命令可复制运行；缺口如实标注。

## 验收清单逐项映射

| # | 蓝图验收项 | 证据位置 | 状态 |
|---|---|---|---|
| 1 | 审查 commit 范围、dirty worktree、用户文件保护 | `git status --short`（clean）；提交链 `d753ab6`→`41ea8f5`；`dist_release2` 哈希 `05055049…50BF` 记录于 `docs/baselines/B0_BASELINE.md` | ✅ |
| 2 | 15 条安全不变量 | B0-B2 全部提交未触碰输入链/决策链；`tests/test_p0_security.py`、`tests/test_scenario_replay.py` 绿；`choice_ocr.py` 纯函数无输入权；incidents 只写盘 | ✅ |
| 3 | 新增依赖必要性与模型来源/许可证 | `.venv-ocr`（隔离）paddlepaddle 3.3.1/paddleocr 3.7.0；模型 `models/ocr/MODEL_MANIFEST.json`（SHA256/许可证/source_url）；`docs/venv_ocr.md` | ✅ |
| 4 | compileall/unittest/scenes/replay | **210 tests OK (2 预期 XFAIL)** 830-940s；scenes ok=130 missing=0；replay Failed=0、**Required Missing=1**（`missing_disconnect_modal` 断线弹窗素材缺口，XFAIL 同源） | ⚠️ 见缺口 |
| 5 | OCR 离线评测 + 抽查错例 | `docs/baselines/B2_OCR_EVAL_*`（3 份：mobile 44 槽/扩充 131 槽/85 面板终版 + server 对比）；错例清单完整；预处理探针 6 变体报告；标注审计 `B2_ANNOTATION_AUDIT_20260810.md`（20 面板 60 槽 0 错 + 10 处按钮字段修正） | ✅ |
| 6 | action ledger 与 B0 等价 | `tools/compare_ledger.py fixtures/baselines/action_ledger_b0.jsonl <候选>` → 实测 `diffs=0 [OK]`（多次运行） | ✅ |
| 7 | 技能白名单/UNKNOWN/低分差/错误页面/错误 HWND 负路径 | 误归一=0（全部评测）；词典 margin 不足返 None（17 单测）；负样本 37 条；`test_p0_security.py` 绿 | ✅ |
| 8 | 每动作前置证据/一 tick 一输入/后置确认/有界恢复 | 本阶段零动作（B0-B2 无运行时改动）；基线动作链由 ledger 证明未变；B1-2 incidents 有界等待+Fail-Closed 前留证 | ✅ |
| 9 | EXE 离线启动/模型加载/日志路径/体积/回滚 | 本轮未构建 EXE（B10 才打包 OCR）；trace/incident 路径 `%LocalAppData%\GameScript-Local\YYYYMMDD\`；回滚 `git revert <hash>` 或 `dist_release2` | ✅（B10 前不适用项） |
| 10 | 门禁全过才派下一阶段 | **B2 门禁 FAIL（准确率 1.46% vs 95%）→ B3 未派发**，符合蓝图"不达标不得进下一阶段" | ⚠️ 决策点 |

## 提交清单（16 个，`d753ab6`→`41ea8f5`）

| 阶段 | 提交 | 内容 |
|---|---|---|
| B0 | `d753ab6` | 固化 16 稳定修复文件 |
| B0 | `3be85e2` | 蓝图文档 + gitignore |
| B0 | `96c8278` | ledger 工具 + B0_BASELINE |
| B0 | `4265a20` | replay argv 隔离修复 |
| B1-1 | `0825f45` | 桌面 trace 扩展（6 测试） |
| B1-2 | `dc02d41` | incident 归档（11 测试） |
| B2-1 | `31cbec8` | 首轮数据集 52 条 |
| B2-3 | `30df2ba` | 词典 + 归一化（17 测试） |
| B2-2 | `40dbea0` | mobile 评测 + 隔离环境 |
| B2 迭代 | `a5aece5` | 词典补录 + 预处理探针 |
| B2 迭代 | `899a999` | server rec 对比（拒绝） |
| B2 迭代 | `e26e0a3` | 数据集扩至 81 条 |
| B2 迭代 | `0ea4943` | 重评报告 131 槽 2.6% |
| B2 迭代 | `670506b`+`7927781` | 词典 90→89 entries + 回归修复 |
| B2 迭代 | `8c254ea` | rec7 扩至 85 条 |
| B2 迭代 | `05e79b2`+`473b568` | 终版评测 1.46% + 状态刷新 |
| B2 审计 | `41ea8f5` | 标注质量审计修正 |

## 你验收时可复制运行的命令

```powershell
cd "C:\Users\10639\Desktop\🎮 影音游戏\GameScript-Local"
git log --oneline main..codex/ocr-hybrid
git status --short
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v      # 预期 210 OK (2 XFAIL)，~14 分钟
.\.venv\Scripts\python.exe tools\validate_scenes.py               # 预期 ok=130 missing=0
.\.venv\Scripts\python.exe tools\run_replay.py --ledger .\tmp_ledger.jsonl
.\.venv\Scripts\python.exe tools\compare_ledger.py fixtures\baselines\action_ledger_b0.jsonl .\tmp_ledger.jsonl   # 预期 [OK] diffs=0
.\.venv-ocr\Scripts\python.exe tools\evaluate_choice_ocr.py --model-subdir PP-OCRv5_mobile_rec_infer --model-name PP-OCRv5_mobile_rec --staging-dir %TEMP%\ocr_stage_verify   # 预期门禁报告（准确率 FAIL、安全/性能 PASS）
```

## 已知缺口（不隐藏）

1. `missing_disconnect_modal`：断线弹窗素材缺失 → replay Required Missing=1（非 FAIL）
2. 960x540 面板样本 0（全部素材 1600x900/1586x892）
3. skill/bond/treasure 面板数 16/14/18 vs 门槛 30
4. **B2 准确率门禁 FAIL**：Top-1 1.46%（85 面板 143 槽，mobile rec；server 同族 4.55% 更慢 47 倍；预处理 6 变体无效——系统性域失配证据链完整）
5. 决策点：数据补齐后仍不达标时，需在"微调（≥1000 样本）"/"降级低置信兜底语义"间裁决
