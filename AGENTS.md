# AGENTS.md — 接手本仓库前必读

游戏自动化项目（英雄三国 / KK 对战平台）：截图 → OpenCV 模板匹配 → SendInput 真实点击。
**误点会造成真实游戏后果**（乱点大厅可能进错房、局内乱点会浪费一局），所以本仓库的
规矩比一般项目严。

## 硬规矩（不要绕）

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

真机跑完若出现 TIMEOUT / CANCELLED / 循环点击，请抽帧固化成夹具再修——
让事故变成永久回归资产，而不是下次从录屏重新考古。
