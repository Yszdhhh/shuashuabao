# 统一版本交接（2026-09-24）

## 组成

`claude/project-thread-fqyf7h` 分支上的统一版本，由三部分组成：

1. PR #37（`fix/desktop-sync-20260923`，头 `1b0a1a8`）。它已经包含 PR #36 的前 125 个提交（两者分叉点是 `94f5023`）。
2. PR #36 在 `94f5023` 之后的独有提交：
   - 直接叠上：`985d350` `d5d7107` `5fcb253` `661773a` `c3f42f5` `e5838f5` `6b9bf9e`。
   - 已在 #37 里，跳过：`7f847c2` `3ecd095` `6717cad`。
   - `3f4f9af`：取 #37 这一侧解冲突后没有剩余改动，说明它的内容已被 #37 的 `8a0f02e` 和 `f082f0a` 覆盖，因此跳过。
   - `533e7b5`（UI-24 看板）：在 `ui-v2/index.html` 上有 3 处冲突。日志条保留 #37 的高度过渡动画；龙珠图标和负面宝物手风琴采用 UI-24 的写法。
3. `fix/launch-summary-escape-20260913` 的两个 XSS 转义提交：`9f60c97` 和 `4519970`。

所有原始提交都保留，合并时用 merge commit，可以二分定位。

## 未完成，需要在本机做

- `python tools/release_gate.py`：云端 Linux 缺 Qt 和 OCR venv，只能跑部分 pytest，不能算门禁 PASS。确认 failed=0 后，再用 `--update-baseline --reason` 更新 pytest 计数。
- 身份锚点：`config/runtime_identity_manifest.json` 仍指向 `94f5023` 一系的候选。合入 main 后，需要补一个锚点提交，指向合入后的 HEAD。
- `build_release.ps1` + `release_harness.py`，并核对桌面 `build_identity.json` 的 `source_sha`（AGENTS.md §6）。
- 需要重新真机验证：蹭车→考古交接和局数计数（`f082f0a`）、Boss 点击后确认、宝物负面默认不拿、#37 的满槽顶替和 F1 兜底、银月之晶、UI-24 看板（含上面 3 处冲突的取舍）、启动摘要转义。

## 分支收敛

远端分支清单和删除建议见项目文件 `branch_convergence/分支收敛方案_20260924.md`。统一版本合入后，#36、#37 关闭，被吸收的分支按清单删除。
