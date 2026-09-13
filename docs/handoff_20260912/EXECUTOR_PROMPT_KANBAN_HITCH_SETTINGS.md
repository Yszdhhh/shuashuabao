# 执行 Agent 提示词：蹭车设置进新看板 + 本地正式版打包（2026-09-12）

> 由架构/收敛会话编写。粘贴分隔线以下全部内容给执行 Agent。

---

你负责刷刷宝的**功能落地**。版本收敛已经完成，现在只有一条主线，不要再开新的工作树或分支线。全程用中文汇报。

## 0. 唯一工作根（先核对）

- 工作根：`G:\刷刷宝\GameScript-Local`，分支 `integration/converge-20260912`（已推送 origin）。开工先执行 `git rev-parse --show-toplevel`、`git status --short`、`git log -1`，并在汇报里写明看到的 HEAD。
- 这条线已包含：最新蹭车生产逻辑（7a55fa3 及之前）、实机测试框架（20d9444 及之前）、新看板（液态银，DashboardFacade v2）、蹭车/跟车 360 宽二级小窗。
- 桌面「刷刷宝 Live 实机测试.lnk」的 harness 根和生产根都是这个目录，`-ProductionSourceSha` 等于当前 HEAD。
- **禁止**在 `G:\刷刷宝\Worktrees\*`、桌面副本 `C:\Users\10639\Desktop\影音游戏\GameScript-Local` 里开发或执行构建/同步脚本。
- 先读：`AGENTS.md`、`docs/agent_shared_logs/RELEASE_HARNESS_LESSONS.md`、`docs/handoff_20260912/CONVERGENCE_REPORT_20260912.md`、`ui-v2/docs/KANBAN_PORT_CONTRACT_20260912.md`。

## 1. 任务 A：自定义搜房词（蹭车）

现状：
- 后端 `hitch_stage_prefix`（`src/shuabao/settings.py:119`）是逗号分隔的多词列表，默认 `4,3,速`，按轮换规则使用；中文词走 unicode 直注入（提交 6a8f8c6 / 43ffcaa），「速」就是这样搜的。
- 看板「高级搜房」弹窗只有「主搜/副搜」两个框（`main.ts` 的 `parseHitchSearchTerms` 只取前两个词），**一保存就把第三个词「速」丢了**。
- `index.html` 约 4793 行还挂着一个沙盒提示「高级搜房：沙盒仅展示入口」，和 `main.ts` 的弹窗同时触发。

要做：
1. 弹窗改成可编辑的**完整词列表**：可增删、排序，支持中文或任意文字（例如「速」「刷」「秘境」），规则与后端校验一致（合计 ≤64 字符、不能为空、去重）。已有配置原样回显，不能丢词。
2. 删除 index.html 里的沙盒提示处理器。
3. 蹭车小窗页面上显示当前搜房词摘要。
4. 测试：vitest 覆盖三个及以上的词往返不丢；Python 侧确认 `Settings.validate_patch` 接受中文和多词。

## 2. 任务 B：时光之穴 / 传家宝 Boss 设置、目标局数（蹭车/跟车）

- 核对蹭车/跟车页上的「传家宝」「时光之穴」选择器能否端到端写入 `cjb_boss` / `sgzx_boss`：弹窗选定 → `update_config` → `snapshot_changed` 回显 → 重开窗口仍在。然后查 `mediator.py` 的蹭车战后链确实读取这两个字段（7a55fa3 起，找不到指定 Boss 时有「末卡」兜底：受控探测 + 两帧确认，最多再观察 3 次）。
- 用户希望在看板上能设置这些 Boss 行为。如果后端已有对应字段（例如「选指定 Boss / 末卡兜底」开关），就接到看板；**如果没有，不要自己加后端字段**，写成提案（字段名、默认值、mediator 读取点、测试），停下来问用户。
- 目标局数：`hitch_cycle_num` / `follow_cycle_num` 以及结束后预案（`hitch_after_goal`: solo/arch，`follow_after_room`: solo/arch/hitch），在小窗里改动后要能持久化、正确回显，0 表示不限（`clampCycle` 允许 0）。
- 蹭车/跟车页只显示 `snapshot.modes[].visible_settings` 里列出的设置。

## 3. 任务 C：本地正式版打包（用户已要求整合本地正式版）

前置条件：任务 A、B 已提交，并且 `python tools/release_gate.py` 退出码为 0（门禁非 0 就停下汇报，不许改快照）。

1. 在工作根执行 `powershell -ExecutionPolicy Bypass -File .\build_release.ps1`。它会更新 `C:\Users\10639\Desktop\ShuaBao` 和「刷刷宝.lnk」，这是用户要求的，按 AGENTS.md 第 6 节执行。
2. 核对 `C:\Users\10639\Desktop\ShuaBao\build_identity.json` 的 `source_sha` 等于 `git rev-parse HEAD`，「刷刷宝.lnk」指向该目录，`ui-v2/dist` 的 build_manifest 与源码一致。
3. 运行 AGENTS.md 6.1 节的 `tools/release_harness.py ... --require-clean`，贴出结果。
4. 打包出来的正式版只允许打开看界面（深浅主题、四个场景、蹭车/跟车小窗），**不点开始运行**。实机验证写 `BLOCKED（待用户实机）`。

## 4. 红线

- 不点开始运行，不启动 KK/游戏输入，不跑 Live harness 或提权菜单（这些由用户做）。
- 看界面用源码壳探针 `ui-v2/_verify/probe_real_shell.py`，配合隔离的 `SHUABAO_APP_DATA`（参考脚本头注释），不写真实的 `%LOCALAPPDATA%\ShuaBao`。
- **实机测试身份规则**（启动器 `tools/live_scenario_capture.py::_scenario_identity`）：
  1. **每次提交后**（包括只改文档的提交），都要把桌面「刷刷宝 Live 实机测试.lnk」的 `-ProductionSourceSha` 改成新的 `git rev-parse HEAD`。启动器要求两者严格相等。
  2. **改了 `src/shuabao/**`** 时，还要另开一个提交，把 `tools/live_harness_identity.py` 的 `HARNESS_BASE_SHA` / `FROZEN_PRODUCTION_CODE_BASELINE` 和 `tests/test_live_harness_refresh.py` 的 `FROZEN` / `BASE`，重定到最后一个改动 src/shuabao 的提交（参照 b1e3e40 / c991aea 的做法）。
  3. 验证：`$env:SHUABAO_PRODUCTION_SOURCE_ROOT='G:\刷刷宝\GameScript-Local'; $env:SHUABAO_PRODUCTION_SOURCE_SHA=(git rev-parse HEAD); python tools/live_scenario_capture.py identity`，必须输出 `READY FOR GT: YES`。
  否则用户下次实机测试会被身份门禁拦下。
- 不一次跑全量 `pytest tests`，全量只通过 `release_gate.py` 跑，并加超时保护。
- 提交信息先写进文件，再用 `git commit -F`；`.ps1` 文件存成 UTF-8 BOM。提交留在 `integration/converge-20260912`，推送前先问用户。

## 5. 汇报格式

①改动（文件路径 + 提交）②验收命令输出摘要（失败照实写）③正式版产物：路径、source_sha、hash ④待用户拍板事项 ⑤BLOCKED 项。
