# 给外部 Agent

请从本目录开始，不要只依赖聊天记录。

## 2026-09-09 最新入口

大厅蹭车、局内长跑、胜负结算、绿色神符规则、Claude 只读审查和 Live Harness 版本关系，请先读：

`CLOUD_PRODUCTION_INTEGRATION_REVIEW_20260909.md`

当前 production 为 `d4aa92c`，Harness 仍冻结在 `332cc75`；正式裁决为 `SAFE_TO_GT: NO`。旧索引主要是 2026-08 的历史材料，若有冲突，以这份 2026-09-09 整合交接为准。

1. 先读：`README.md` → `INDEX_FOR_AGENTS.md`
2. 大厅/房间不点开始：`../LOBBY_ROOM_GAP.md`
3. 日志摘录：`exports/LOG_LOBBY_AND_ENTRY_EXTRACT.md`
4. 全量日志：`official_raw/*log*.log`
5. 截图：`official_raw/*Capture*` / `*QuitGame*` 与 `exports/*.png`

刷新命令（用户跑完官方脚本后执行）：

```
powershell -File tools/export_agent_logs.ps1
```

（在 GameScript-Local 根目录执行）
