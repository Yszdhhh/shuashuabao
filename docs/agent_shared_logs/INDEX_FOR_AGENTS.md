# INDEX · 外部 Agent 快速入口

## 一句话问题

用户开着脚本站在**游戏房间/大厅**，脚本**不点「开始游戏」**，一直空转；  
联网官方曾能建房/设密/开局。根因是 **L0 大厅层缺失/未触发**，不是 L1 选卡识别坏了。

## 必读文件（相对 GameScript-Local）

| 优先级 | 路径 |
|--------|------|
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

- **要做**：L0 房间识别、点开始、文档/UI 提示；补 `assets/Images/lobby/`  
- **先不做**：完整带队建房若无模板；证书破解；QMacro  
- **技能中文**：官方只有短码，见 `config/skill_labels.json`  

## 成功判据

日志出现 **`开始主线！`** 才算进 L1；仅有 **`等待进入游戏UI`** 仍在门槛外。

---

## 进度更新（2026-08-04）

- **P0 已完成**：`LOBBY_ROOM` 自动点击、`assets/Images/lobby/room_start.png` 与 `[L0]/[L1]` 日志已补齐；2026-08-04 另修复 1936×1066 与 1600×900 模板缩放不一致导致的开始/选关漏检，并保留窗口范围、移除全屏误点兜底。

