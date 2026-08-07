# Live post-game capture 2026-08-08 (vision-annotated)

Source: game window 英雄三国KK hwnd=1968096 1616x939, captured 00:42 local time.

## Current screen = 局内安全区 (in-match safe zone, NO modal)
Vision (Gemini) annotation of live_archive_panel.png:

- Hero Linus in base/safe zone after finishing a match (no victory modal visible
  at capture time — either auto-dismissed or player closed it).
- NPCs (clickable, center coords in window pixels):
  - 存档挑战 (597, 245)
  - 大秘境 (809, 260)
  - 传家宝挑战 / 英雄挑战 (nearby, left side)
- Bottom buttons: 抽奖(234,802) 存档(284,802) 百科(234,877) 设置(284,877) 查看属性(552,885) 更多设置(1548,863) 屏蔽特效(1554,892) 屏蔽跳字(1549,918)
- Top: 退出游戏(72,50) 设置(139,52) 关闭按键提示(62,89) 玩家列表(1564,137)
- Right-top: 小地图 (archiveChallenge template matched 0.946 @845,94 — likely minimap marker)

## Template findings
- `archiveChallenge` 0.946 @ (845,94): NOT the archive panel modal — it is the
  minimap/marker area. ARCHIVE panel template needs a live modal sample.
- `challenge_npc_hub` fixture vs live: 0.731 (partial overlap, not conclusive)
- Missing: live victory/archive modal screenshots (player was past them when
  capture happened). Awaiting user's screen recording for frame breakdown.

## Next
- Video breakdown (tools/video_breakdown.py) on user's recording to extract
  victory modal + archive panel frames with timestamps.
