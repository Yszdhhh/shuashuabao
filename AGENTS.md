# AGENTS.md — 接手本仓库前必读

游戏自动化项目（英雄三国 / KK 对战平台）：截图 → OpenCV 模板匹配 → SendInput 真实点击。
**误点会造成真实游戏后果**（乱点大厅可能进错房、局内乱点会浪费一局），所以本仓库的
规矩比一般项目严。

## 硬规矩（不要绕）

### 0. 分支纪律：main 只经 PR 的 merge commit 前进

- 任何改动开始前：`git fetch origin && git switch -c <topic> origin/main`（或新 worktree）。
  **禁止在 main 上写代码或提交**，也禁止直接 `git push origin main`。
- 合并只用 PR 的 merge commit（仓库已关闭 squash / rebase）。本地 main 只做 `git merge --ff-only origin/main`。
- 克隆后执行一次 `git config core.hooksPath .githooks`：`pre-commit` 拒绝在 main 提交，
  `pre-push` 拒绝推送 main。钩子能被绕过，只是第二道门；绕过即流程事故。
- 发现本地 main 有未推送的提交：先把它们挪到 topic 分支（`git branch <topic> main`），
  再把 main 对齐 `origin/main`，然后才能继续。2026-09-14 的 4ed44d4/45c3520/b66f1ce 就是这样补的 PR #21。

### 1. 提交前必须过门禁

```powershell
python tools/release_gate.py
```

退出码必须为 0。四个阶段：`pytest tests/`、冻结回放、模板完整性、`tests/contract/` 层间契约。

**门禁红了不要去改快照让它变绿。** 快照 `docs/baselines/GATE_BASELINE.json` 是行为基线，
`--update-baseline` 需要 `--reason`。正当顺序永远是：先判断哪边才对 → 修代码或修夹具期望 →
再更新快照。把 FAIL 写进快照当 PASS 是本项目明令禁止的（见 `docs/AGENT_CORRECTION_GATES_20260811.md`）。

### 2. 一个 commit 只动一层

层的划分：**L0 大厅**（地图/建房/房间/选关/英雄弹窗）、**L1 局内**（主线循环/面板 FSM/挑战开关）、
**恢复与战后**、**感知**（vision/模板/scenes.json）、**外壳**（desktop_app/api_server/打包）。

理由不是洁癖：`src/gamescript/mediator.py` 约 5900 行、159 个方法、约 161 个共享可变状态。
2026-08-12 有人把局内修复和大厅改动塞进同一个 1300 行的 commit（`e997b39`），第二天上午
被迫连发两个紧急版本修大厅（`de77a19`、`42f3e95`）。跨层混提交会让二分定位失效。

### 3. 改局内前先看 C2 契约

`tests/contract/test_l0_lobby_chain_contract.py` 的 `C2InGameStateIsolation` 断言：
把全部局内状态污染后，大厅决策序列必须逐字节一致。这是本仓库最容易踩的回归。
若你新增或重命名局内状态字段，同步 `INGAME_POLLUTION` 清单。

### 4. 两条红线，永远不要碰

- **进房/建房禁止颜色兜底**：`room_start` / `map_create_room` 及其别名的 `fallback` 恒为 `null`。
  历史上颜色兜底会误点"快速加入/快速匹配"，把用户拉进陌生房间。契约 C4 守着这条。
  （局内失败恢复的红/绿按钮判定是另一回事——它受强失败锚点门控，不适用本条。）
- **不得用合成帧冒充真机证据**：断线场景至今 BLOCKED 就是因为没有真实素材。
  合成图可以用于单测逻辑，但不得据此声称"实机断线已通过"。

### 5. 不确定就 fail-closed

看不到锚点时零输入等待，不要"猜着点"。`UNKNOWN` 屏态下的强行操作是实跑卡死的主要来源。

## 定位当前状态

- **唯一权威现状**：`docs/CURRENT_STATUS_AND_HANDOFF_*.md`（取日期最新的一份）
- 整体评审与已知结构性风险：`docs/reviews/PROJECT_REVIEW_20260812.md`
- 改动纪律细则：`docs/CONTRIBUTING_GATE.md`
- 外部 agent 入口索引：`docs/agent_shared_logs/INDEX_FOR_AGENTS.md`
- 发布/桌面同步事故 harness：`docs/agent_shared_logs/RELEASE_HARNESS_LESSONS.md`

`docs/` 下有大量按波次堆叠的历史文档（B0–B10 / N/S/O/P/G/R 两套阶段命名并存），
**互相矛盾且多数已过期**。遇到冲突以最新交接文档 + 最新 trace 为准，不要照着旧蓝图施工。

## 会话结束前

若你改了行为或让某条链路的证据失效，回写 `docs/CURRENT_STATUS_AND_HANDOFF_*.md`：
改了什么、哪些链路需要重新真机验证。否则下一个 agent 会从过期状态出发继续跑偏。

## 常用命令

```powershell
python tools/release_gate.py                  # 发版门禁（离线，零输入）
python -m pytest tests -q                     # 全量测试
python tools/run_frozen_replay.py --check     # 只跑冻结回放
python -m pytest tests/contract -q            # 只跑层间契约
python tools/diagnose_lobby.py                # 实机只读快照（需要游戏在运行）
python tools/video_breakdown.py               # 录屏抽帧，把事故固化成夹具
```

真机跑完若出现 TIMEOUT / CANCELLED / 循环点击，请抽帧固化成夹具再修——让事故变成永久回归资产，而不是下次从录屏重新考古。

## 6. 工作树、构建与桌面落地

- 默认唯一工作根是 `G:\刷刷宝\GameScript-Local`；先用 `git rev-parse --show-toplevel` 验证当前目录，不要在 sibling worktree 或桌面副本直接交付。
- 子 agent 隔离目录的改动必须回写父工作树；仅有 agent 返回结果、临时 patch 或 `git push` 都不算落地。
- 父会话在继续前必须于本根检查 `git status --short`、`git diff`、`git rev-parse HEAD`，确认改动路径确实属于本仓库。
- 工作树已有未提交改动时先记录基线，禁止覆盖/回滚用户改动；自动回写冲突必须停止并逐文件处理。
- 修改 `ui-v2/`、`desktop_app.py`、`build_release.ps1`、`ShuaBao.spec` 或发布配置时，必须在本根运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

- 构建后必须核对 `C:\Users\10639\Desktop\ShuaBao\build_identity.json` 的 `source_sha` 等于本根 `git rev-parse HEAD`，并确认 `刷刷宝.lnk` 指向该目录。源码、`ui-v2/dist`、EXE、快捷方式四者不一致时停止交付。
- 桌面 EXE 需要 UAC 或真实游戏交互而无法启动时，状态只能写 `BLOCKED`，不能用 pytest、源码日志或旧截图替代 Level 3 证据。
- 交接文档必须记录本次源码 commit、产物 hash、正式入口和仍需真机验证的项目，避免下个 agent 回到旧版本。

### 6.1 发布事故 harness（强制）

开始处理订阅、桌面 UI、`ui-v2/`、`build_release.ps1` 或 `ShuaBao.spec` 前，先读
[`docs/agent_shared_logs/RELEASE_HARNESS_LESSONS.md`](docs/agent_shared_logs/RELEASE_HARNESS_LESSONS.md)。
它记录了本项目已经付过代价的故障模式：源码 Python 通过但冻结 EXE 失败、同名
OpenSSL DLL 错配、Cloudflare 冷启动超时、桌面快捷方式仍指向旧包，以及把 click
success 误当业务成功。

构建脚本会自动执行两次冻结包 harness；若需手工检查最终桌面目录，必须使用：

```powershell
python tools/release_harness.py `
  --source-root "G:\刷刷宝\GameScript-Local" `
  --bundle "C:\Users\10639\Desktop\ShuaBao" `
  --python-root "<build Python sys.base_prefix>" `
  --manifest-public-keys "<仓外 operator manifest public-key registry>" `
  --require-clean
```

该命令只读 Git/文件，不启动 KK、不发送输入、不读取或打印卡密。任一检查失败时
只能报告 `FAIL/BLOCKED` 并停止交付；不得用源码 CLI、旧桌面日志、单次点击成功或
手工替换 DLL 代替最终冻结 EXE 验证。
