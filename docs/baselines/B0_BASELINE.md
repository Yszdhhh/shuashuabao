# B0 基线记录（OCR 混合识别蓝图 §6）

> 日期：2026-08-10
> 分支：`codex/ocr-hybrid`
> 稳定修复固化提交：`d753ab6`（chore(baseline): solidify current stable fixes）
> 蓝图文档提交：`3be85e2`
> 机器：i5-13600KF / RTX 3070 8GB / Windows 10 / Python 3.11.15（.venv）

## 回滚基线（dist_release2）

| 项 | 值 |
|---|---|
| 文件 | `dist_release2/GameScript/GameScript.exe` |
| SHA256 | `0505504932A249342D7879DBF4E37684C35C442E079EF55261521AAF186500BF` |
| 大小 | 5,891,759 字节 |
| 构建时间 | 2026-08-10 01:48（本地） |
| 状态 | 未覆盖、未移动、未重打；后续构建输出到新目录 |

## B0-2 可复现测试基线（原始命令输出摘要）

```powershell
.\.venv\Scripts\python.exe -m compileall src tests tools desktop_app.py
$env:PYTHONPATH="src"; .\.venv\Scripts\python.exe -m unittest discover -s tests -v
$env:PYTHONPATH="src"; .\.venv\Scripts\python.exe tools\validate_scenes.py
$env:PYTHONPATH="src"; .\.venv\Scripts\python.exe tools\run_replay.py
git diff --check
```

| 命令 | 退出码 | 摘要 |
|---|---|---|
| compileall | 0 | 通过 |
| unittest | 0 | **178 tests OK（expected failures=2）**，830.6s |
| validate_scenes | 0 | ok=130 missing=0（UNREF 警告为既有正常输出） |
| run_replay | 1 | **Total=32, Passed=31, Failed=0, Required Missing=1**, Optional Missing=0 |
| git diff --check | 0 | 无空白错误 |

### Required Missing=1 单列（不能偷渡）

- `missing_disconnect_modal`：断线弹窗素材缺失（`MISSING_RESOURCE`）。
- 与 `fail_recovery_three_frames`（XFAIL）同源：真实失败/断线弹窗画面至今无实机证据。
- 处理：列为已知证据缺口，不视为通过；`B2-1` 负样本已含 black/frozen/unknown 帧，真实断线弹窗仍需实机录制。

## 基线 action ledger（grok 审查阻塞项 #1 落地）

- 生成：`tools/run_replay.py --ledger fixtures/baselines/action_ledger_b0.jsonl`
- 产物：`fixtures/baselines/action_ledger_b0.jsonl`（32 行，每 fixture 一行 tick 级 ledger）
- 行结构：`fixture_id / phase / context / action_name / action_kind / click_point / hwnd / score / margin / status / required / dry_run`
- 等价比较：`tools/compare_ledger.py <baseline> <candidate>`（忽略 hwnd、score 漂移>0.05 仅 WARN；比较 fixture_id/phase/context/action_name/action_kind/click_point/required；diff>0 则 exit 1）
- 自验：baseline vs 自身 → diffs=0，`[OK]`（EXIT=0）
- 后续 B3 shadow 模式必须与本 ledger 逐 tick 等价（不变量 #11/#12）。

## 后续阶段基线参照

- B1-1（桌面 trace 扩展）：`0825f45`
- B1-2（incident 归档）：`dc02d41`
- B2-1（OCR 数据集）：`31cbec8`（52 条目：15 正面板 + 37 负样本，86 crops，960x540 缺口已记录）
- B2-3（词典归一化）：`30df2ba`（17 测试绿）
- 下一阶段：B2-2（.venv-ocr + PP-OCRv5 mobile 离线评测，不接运行时）
