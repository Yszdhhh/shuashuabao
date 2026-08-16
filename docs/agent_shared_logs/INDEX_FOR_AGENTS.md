# INDEX · 外部 Agent 快速入口

> **先读规矩：** [`AGENTS.md`](../../AGENTS.md)（仓库根）——硬规矩、两条红线、发版门禁命令。
> **再读当前状态：** [`docs/CURRENT_STATUS_AND_HANDOFF_20260812.md`](../CURRENT_STATUS_AND_HANDOFF_20260812.md)。本索引下方内容以早期 L0 日志研究为主，若与当前状态冲突，以新交接文档和最新 trace 为准。
>
> **提交前必过：** `python tools/release_gate.py`（退出码 0）。细则见 [`docs/CONTRIBUTING_GATE.md`](../CONTRIBUTING_GATE.md)。

## 当前进度（2026-08-14）

- **板块 3 逻辑库：** 总索引 [`docs/research/GAME_LOGIC_LIBRARY_INDEX_20260814.md`](../research/GAME_LOGIC_LIBRARY_INDEX_20260814.md)。**刷新必须分账**：羁绊=木头，黑商=杀敌（180s 免费 1 次），宝物/技能/英雄卡=词条或局外卡次数。F1/F2 已入库。F4 / 压力转移分情况解禁。`-zs` 仍禁。均未接线。
- **板块 4 画像绑定（只读）：** 不选不抓。`--bind` 才写 `first_login`。人点顶栏存档：装备战力/强化 + 技能 16 系。TAB 只认刚入局默认盘（装备堆叠），打一半不当画像。夹具 `fixtures/player_profile_20260814/`。`11-画像绑定.bat`。不代点、不写 config。P2 看板未做。

## 一句话问题

原始投诉是用户开着脚本站在**游戏房间/大厅**，脚本**不点「开始游戏」**，一直空转；
联网官方曾能建房/设密/开局；修复重点是 **L0 大厅层与 L1 选关的状态边界**，不是单纯重写选卡算法。

## 必读文件（相对 GameScript-Local）

| 优先级 | 路径 |
|--------|------|
| P0 | `docs/CURRENT_STATUS_AND_HANDOFF_20260812.md` |
| P0 | `docs/agent_shared_logs/README.md` |
| P0 | `docs/agent_shared_logs/exports/LOG_LOBBY_AND_ENTRY_EXTRACT.md` |
| P0 | `docs/LOBBY_ROOM_GAP.md` |
| P0 | `docs/LOGIC_ROOM_STAGE_REP_SKILL.md` |
| P0 | `docs/PROMPT_LOBBY_AND_AGENT.txt` |
| P1 | `docs/agent_shared_logs/official_raw/log_20260803.log` |
| P1 | `docs/SUCCESS_FLOW.md` |
| P1 | `src/gamescript/mediator.py`（搜 WAIT_UI / PREPARE） |
| P1 | `config/scenes.json`（`"start"` 仅 3 模板） |
| P1 | `assets/Images/startGameBtn.png` 等 |
| P2 | `docs/HANDOFF_FRONTEND_CONTROL_PANEL.md` |
| P2 | `config/default_settings.json` / `config/skill_labels.json` |

## 原始日志位置（实时）

```
%LocalAppData%\GameScript\YYYYMMDD\log.log
%LocalAppData%\GameScript\YYYYMMDD\Capture*.png
%LocalAppData%\GameScript\YYYYMMDD\QuitGame*.png
%AppData%\Roaming\GameScript\Settings\Settings.json
```

同步到本仓库：`tools/export_agent_logs.ps1`

## 执行提示词（复制给干活的 Agent）

- **优先大厅进不去**：`docs/PROMPT_EXEC_LOBBY_FIRST.md`（整份复制）
- 大厅缺口说明：`docs/LOBBY_ROOM_GAP.md`
- 日志本目录：`README.md` + `exports/LOG_LOBBY_AND_ENTRY_EXTRACT.md`

## 任务边界

- **已接入**：L0 地图→建房弹窗→房间开始→选关状态链；仍建议补真实建房弹窗/创建按钮模板做回放回归
- **剩余边界**：每局退房重建需要真实退出按钮模板；证书破解；QMacro
- **技能中文**：官方只有短码，见 `config/skill_labels.json`

## 成功判据

日志出现 **`开始主线！`** 才算进 L1；仅有 **`等待进入游戏UI`** 仍在门槛外。

---

## 进度更新（2026-08-04）

- **P0 已完成**：`LOBBY_ROOM` 自动点击、`assets/Images/lobby/room_start.png` 与 `[L0]/[L1]` 日志已补齐；2026-08-04 另修复 1936×1066 与 1600×900 模板缩放不一致导致的开始/选关漏检，并保留窗口范围、移除全屏误点兜底。

## 进度更新：2026-08-05

- **P0 增强**：L0 现在先做上下文判定；同名 KK 大厅/房间窗口全部枚举并按场景锚点选择，不再固定拿主窗口。真实建房弹窗确认按钮改用底部 ROI，并继续要求两个输入框。
- **输入边界**：截图不主动抢前台；真实点击前激活已验证 HWND，激活失败则跳过输入。Dry-run 仍只打印坐标。

