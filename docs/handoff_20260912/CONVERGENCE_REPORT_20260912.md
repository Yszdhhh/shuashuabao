# 刷刷宝版本收敛整合报告（2026-09-12）

> 编写：架构/收敛会话。后续执行工作见同目录 `EXECUTOR_PROMPT_KANBAN_HITCH_SETTINGS.md`。

## 1. 结论

- 此前并行的四条线（实机测试框架、蹭车生产逻辑、新看板、桌面旧副本）已收敛为 **一条主线：`integration/converge-20260912`**。
- **唯一工作根**：`G:\刷刷宝\GameScript-Local`（checkout 这条主线）。
- 桌面「刷刷宝 Live 实机测试.lnk」的 harness 根和生产根都指向这个目录。
- 发版门禁在 c991aea 上全绿：pytest 2069 passed / 2 xfailed / 13 skipped；frozen_replay、scene_templates（398/398）、contract（56）均 PASS；退出码 0。
- 实机身份检查：`READY FOR GT: YES`。

## 2. 收敛前的状态

| 线 | 位置 | 头部 | 说明 |
|---|---|---|---|
| 实机测试框架 | G 根，`fix/live-hitch-follow-closure-20260911` | 20d9444 | 相对分叉点 3904913 只改 launcher / live_scenario_capture / 身份文件 / 测试（src/shuabao 净变化为 0） |
| 蹭车生产逻辑 | `Worktrees\prod-source-3904913-20260911`，`fix/hitch-live-closure-20260912` | 7a55fa3 | 29 个提交，当时 Live 快捷方式指向这里 |
| 新看板移植 | `Worktrees\ui-kanban-port-20260912` | 未提交 | 执行 agent 的移植成果 |
| 桌面旧副本 | `Desktop\影音游戏\GameScript-Local`，`trial-merge` | b9208db（08-14） | FastAPI / pywebview 路线，**冻结**，只作为设计参考 |

两条正式线在 3904913 分叉，互不包含对方提交；三条正式线都没有推送到远端。

## 3. 收敛提交（按顺序）

| 提交 | 内容 |
|---|---|
| fc49237 | feat(ui-v2)：新看板（液态银）移植到 DashboardFacade v2；Esc 不再停止运行 |
| 9095471 | merge：实机测试框架线 0e18a44（冲突只在身份基线，取生产侧） |
| cc73dcb | merge：新看板 |
| 155185e | feat(shell,ui-v2)：蹭车/跟车 360 宽二级小窗；修深色主题竞态；日志收进抽屉；状态条显示中文阶段；去掉无效的最大化按钮 |
| b1e3e40 | chore(harness)：身份基线重定 |
| ad18a5b | merge：生产线 7a55fa3（战后 Boss 兜底收口） |
| 9cc3eae | merge：测试框架线 20d9444（采集器减少写盘） |
| c991aea | chore(harness)：身份基线重定到 9cc3eae（门禁在此提交上全绿） |

## 4. 架构要点（本次定下的规则）

1. **只有一条线**：以后所有 agent 都在 G 根的 `integration/converge-20260912` 上工作。不再新建 `Worktrees\*` 候选树，也不再用「候选注入」模式；需要隔离时用分支，完成后合回。
2. **实机身份规则**：
   - Live 快捷方式里的 `-ProductionSourceSha` 必须等于 G 根的 HEAD，任何提交后都要同步。
   - 改了 `src/shuabao` 时，还要重定 `tools/live_harness_identity.py` 的冻结基线。
   - 验证命令：`python tools/live_scenario_capture.py identity`，要求输出 `READY FOR GT: YES`。
3. **看板 ↔ 后端**：只走 QWebChannel `facade`（`BRIDGE_SCHEMA_VERSION=2`）。页面不发 `game_mode`，模式由 `mode_id` 加 `mode_specs.json` 决定。桌面旧副本的 `/api/*` 路线作废。
4. **二级小窗**：`set_window_layout({"layout":"compact","height":N})`，宽 360，高度由页面在 360 宽下实测。运行中仍然最小化，由原生 OverlayHud 负责显示和急停。小窗**故意不置顶**，置顶窗口会盖住游戏、挡住脚本点击。
5. **急停**：F12、看板停止按钮、原生 HUD 停止按钮。Esc 只关闭弹窗和抽屉。

## 5. 工作树清理

- **已移除**（没有改动，提交都已在主线或远端；只删目录，分支保留）：architecture-convergence、ci-speed-and-stability-harness、cloud-sync-audit、concurrent-lobby-overlay、fix-formal-g0-live-review、formal-g0-d9148c-live、formal-integration-20260910、hitch-owner-left-popup、live-g0-publicbag-treasure-20260910、live-harness-current、prod-source-52edff3、release-p0、shuabao-release-closure、shuashuabao-entitlement-test、shubao-build-7816a15-clean、solo-live-harness、`G:\tmp\shuabao-rc-build`。其中两个构建树里的 OCR 模型 tar 与 G 根里的哈希一致。
- **切换后移除**：prod-source-3904913-20260911、ui-kanban-port-20260912、converge-20260912（均已并入主线）。
- **保留，待用户决定**（有未提交的生产改动或独有提交）：

| 工作树 | 情况 |
|---|---|
| live-harness-refresh-20260908 | ae52f56 未推送 + 7 个未提交文件（mediator / choice_policy / merchant_scanner 等） |
| live-test-boss-05ed271 | 26 个未提交文件（mediator / lobby_hitch / launcher / scenes.json 等） |
| live-g0-publicbag-v2 | 2 个未提交文件（mode_specs / mediator） |
| lobby-hitch-surface-test | 未跟踪的 live-captures/（实机证据） |
| subscription-lobby-pilot-20260831 | edccc21 未推送 |
| night-ablation-20260907、stability-s0-20260908 | 登记路径直接指向 `.git` 文件，结构异常，未动 |
| build\tls_release_d11ac00 | 两个构建日志 |
| `C:\Users\10639\.codex\worktrees\*`（2 个） | Codex 应用自己的工作树，08-15 的 5d6406b，不属于本仓库管理 |

建议：以上各项先导出 patch 或证据到归档目录再移除，因为它们的改动都早于今天的收敛，内容大概率已过时。

## 6. 桌面入口

| 入口 | 指向 | 状态 |
|---|---|---|
| 刷刷宝.lnk | 已安装正式版 app-0.3-dev-b15da05（09-07） | 旧 UI；执行 agent 任务 C 会用主线重新打包 |
| 刷刷宝 Live 实机测试.lnk | G 根 + HEAD SHA | 实机蹭车测试的唯一入口 |
| 刷刷宝 看板预览.lnk | 桌面旧副本 preview_app.pyw | 旧设计稿，已冻结；新看板在主线 ui-v2 |

事故记录：09-12 21:45，有人在桌面旧副本里执行了 `build_release.ps1`，生成了没有图标的旧引擎 `ShuaBao-V0.3`，并把「刷刷宝.lnk」挪进了归档。快捷方式已恢复；V0.3 已归档到 `刷刷宝-旧版归档\20260912-误建旧引擎V0.3`。

## 7. 未验证 / 需要用户做的

- 收敛后的实机蹭车链：BLOCKED（待用户实机，通过 Live 快捷方式）。
- 正式版打包和安装：执行 agent 任务 C。
- 云端审查：推送后，用户在 Claude Code 里运行 `/code-review ultra`（审当前分支）。
