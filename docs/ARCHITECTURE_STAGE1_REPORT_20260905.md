# Architecture Convergence — Stage 1 Completion Report

Date: 2026-09-05
Branch: `refactor/architecture-convergence-20260904`
Upstream sync SHA: `f1d10ba7ebec2fa61f4a6210bd6ff07868b93d0c` (`origin/trial-merge`, Release P0 已合入)
Task 1 rollback anchor: `4aa065554206556746f6ef3a2f938d45a15db0ca`（云端验收 PASS）
Final HEAD: 见本文末尾提交清单。

## Task 1 — Typed expected-value OCR validation（云端验收 PASS）

- **Problem**: 搜房前缀 OCR 文本与期望值比较逻辑散落，containment 语义允许 `444` 匹配期望 `44`；`normalize_prefix` 静默截断超长配置期望。
- **Old behavior**: `has_prefix_evidence` 自带 normalize/compare/fuzzy 分支；期望词 `[:64]` 截断后仍参与 MATCH。
- **New invariant**:
  - 唯一期望值判定入口 `shuabao.vision.ocr_verifier.verify_expected_text`（NFKC、有界、双侧 allowed_chars、精确相等）。
  - `parse_counter` 支持 `/`、`-`、`—` 与全角/空白变体；malformed 一律 fail-closed 返回 None。
  - `has_prefix_evidence` 仅做 observed 清洗（NFKC+whitespace+counter 提取），期望判定全部委托 verifier。
  - `normalize_prefix` 不再截断；超长期望在 verifier 处 fail-closed。
  - INVALID/UNKNOWN expected → 无 prefix confirmation → 无 room scan/join authority。
- **Tests**: `tests/test_ocr_verifier.py`（13 项：精确匹配、444 vs 44、超长、非批准字符、malformed unicode/分隔符、helper 路由 spy）。
- **Rollback commit**: `0f8f5b4` / `c63ab62`（终态）。

## Task 2 — Transient-state lifecycle convergence（内部 review PASS）

- **Problem**: 跨 episode 边界残留瞬态状态：
  1. `_pending_action` / `_pending_action_unconfirmed_count` 在新一局选关页（STAGE_SELECT）仍存活，首帧误判动作在途并阻塞/污染决策；
  2. `_hitch_floor_exit_pending` / `_hitch_floor_exit_confirmed` / `_hitch_floor_exit_attempted_at` 在 `_hitch_after_exit` 后未清，下次 hitch 流程误判仍在退房等待；
  3. runtime watchdog HUD latch（`_runtime_watchdog_hud_confirmations` / `_runtime_watchdog_last_frame_id`）跨 MAIN_LINE 重进未 re-arm，首帧即可能带上一局确认数。
- **Old behavior**: 上述字段仅在各自流程尾部/构造函数初始化，无 episode 边界复位。
- **New invariant**:
  - `set_phase(STAGE_SELECT)` 跨局入口清 `_pending_action=None`、`_pending_action_unconfirmed_count=0`；
  - `_hitch_after_exit()`（所有 hitch 退出路径收敛点）统一清 floor-exit 三字段；
  - `set_phase(MAIN_LINE)` 入口重置 watchdog HUD latch 与 last_frame_id。
  - 未触碰：`_stage_attempt_budget`、`_room_action_deadline`、进行中 recovery step budget；无新 state container/manager/framework。
- **Reviewer 结论（PASS）**: reset 全部位于既有受守卫边界分支，值等于构造初值；watchdog 复位位于 MAIN_LINE 唯一真实转换点，无 starvation；fallback ownership 未变。
- **Tests**: `tests/test_transient_lifecycle_regressions.py`（3 项，先红后绿）。
- **Rollback commit**: `6879abb`。

## Task 3 — Bound one mechanical recovery path: RuntimeWatchdog-EscUnstuck（内部 review PASS）

- **Problem**: LIVE 活性看门狗只要 `act_key("escape")` 返回 True 即重置停滞计时并 `_mark_runtime_progress`，物理按键成功被当作业务成功；若 ESC 实际未改变页面，看门狗将无限重发 ESC（同 target 无上限、无 fail-closed）。
- **Old behavior**: ESC 发送成功 → 计时刷新 → 15s 后再次 ESC，循环无界。
- **New invariant**:
  - `act_key` 成功 ≠ 业务推进：只有 core FSM 真实执行输入（`_tick_input_executed=True`，即 fresh-frame 后置验证）才把 `_runtime_watchdog_esc_attempts` 清零；
  - 未验证 ESC 尝试累加，达 `_RUNTIME_WATCHDOG_MAX_ESC_ATTEMPTS=2` 后走现有 `set_phase(Phase.ERROR)` fail-closed，不再发送；
  - UNKNOWN/异常/非 HUD 帧保持零输入（HUD latch 原逻辑未动）；
  - retry 恒定同 target（"escape"），无第二 retry framework、无 VerifiedAction、无 UNKNOWN→ESC fallback。
- **Reviewer 结论（PASS）**: 5 项焦点（非业务成功、UNKNOWN 零输入、上限+fail-closed、无新机制、无附带改动）全部证据通过；对 `_runtime_watchdog_allowed`、HUD latch、panel watchdog、既有 fallback 均零改动。
- **Tests**: `tests/test_watchdog_recovery_bounded.py`（3 项：预算耗尽 fail-closed 且第 3 次不再发键、未验证进度不重置预算、真实核心输入重置预算）。
- **Rollback commit**: `e682f9e`。

## Full verification（Phase A3）

**提交后复跑（HEAD 3898214）**: `pytest tests -q --tb=short -p no:faulthandler` → **EXIT=0，1474 passed, 13 skipped, 2 xfailed**。
**提交后 flake 修复**: `test_tick_trace_carries_reason_and_evidence_gen` 在整机高负载下偶发 `capture_wait`（FakeClock 不覆盖 `time.perf_counter`，`see()` 捕获计时用真实墙钟）。修复：测试内固定 `perf_counter`；模块 5 连跑稳定 18 passed。该 flake 为既有测试基建问题，非 Task 2/3 引入。
| 项 | 结果 |
|---|---|
| `python -m pytest tests -q --tb=short` | **1474 passed, 13 skipped, 2 xfailed, 211 subtests**（高于合入前主线 1444；新增 Task 2/3 共 6 项回归） |
| `python tools/release_gate.py` | **PASS（阶段 4/4）**；pytest 1474 / frozen_replay PASS（`disconnect_modal_missing=BLOCKED` 为历史已知项，保持未伪造）/ scene_templates 147 ok / contract 56+1 |
| `git diff --check` | 干净 |
| `git status --short` | 干净（提交后） |

### 附带基础设施修复（非业务语义）

`tools/release_gate.py` pytest 阶段增加 `-p no:faulthandler`：Windows 上 PyQt6 事件循环（上游 Release P0 合入的 `tests/test_dashboard_facade_runner.py` 任意 `processEvents`）与 Python faulthandler 致命转储互相冲突，导致 pytest 进程随机 access-violation（exit 5）且被 gate 记为 0 通过。禁用后全量稳定 1474 passed。三组复现/排除实验（deselect 单测、排除整模块、禁用插件）定位为测试基建与环境交互，非 Stage 1 业务代码引入。

## 反向审查清单（A3）

- 无 Behavior Tree / DSL / 第二 OCR service / 第二 Action framework / 第二 incident system。
- 无 matcher 架构改写；无无关 cleanup。
- Stage 0 事实审计结论未被推翻：UNKNOWN 仍零输入；业务 fallback ownership 未变。

## Commits（base `829c56b` = merge of `f1d10ba` upstream sync）

| Commit | 内容 |
|---|---|
| `829c56b` | sync: merge latest trial-merge (upstream `f1d10ba`) |
| `6879abb` | fix: reset transient recovery state at episode boundaries (Task 2) |
| `e682f9e` | fix: bound runtime watchdog EscUnstuck with fresh-frame postcondition (Task 3) |
| `6f01832` | fix(release): disable faulthandler in gate pytest stage + docs: record Stage 1 completion report |
| `3898214` | test: pin perf_counter in tick-trace regression to remove load-sensitive flake（终态 HEAD） |

## Remaining known issues

- P2（既有，非本 Stage 引入）：`disconnect_modal_missing=BLOCKED`（冻结回放历史已知项，保持 BLOCKED 不得伪造）。
- P2（既有，上游测试基建）：PyQt6 processEvents 与 faulthandler 的 Windows 冲突已在 gate 侧规避；本地裸跑 `pytest tests` 建议同样加 `-p no:faulthandler`。
- 无新增 P0/P1。

## Merge recommendation

建议以 `origin/refactor/architecture-convergence-20260904` 终态 HEAD 合入 `trial-merge`：
- 上游 `f1d10ba` 已在本分支祖先内（正常 merge，无冲突面）；
- Task 1/2/3 全部带独立红绿回归 + 双 reviewer PASS（Task 1 另有云端验收）；
- release_gate 4/4 PASS、pytest 1474 全绿；
- 回滚点：Task 1 `4aa0655`、Task 2 `6879abb^`、Task 3 `e682f9e^`。
