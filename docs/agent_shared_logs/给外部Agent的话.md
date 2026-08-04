# 给外部 Agent

请从本目录开始，不要只依赖聊天记录。

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
