# Live E2E capture 2026-08-07 (elevated SendInput)

Proven path (admin process required — UIPI):
1. Map page → click 创建房间
2. Create dialog (separate Qt HWND) → type password → 创建
3. Room host UI (开始游戏/邀请/退出) → click 开始游戏
4. Game window `英雄三国KK` 1600x900 loading → in-match

Key files:
- 03_dialog.png / 04_after_pwd.png — create room dialog
- 10_room.png — room host before start
- 20_t*_1968096.png / watch_* — game client frames

Not yet captured: full post-game victory/archive flow (match still running / not finished in session).
