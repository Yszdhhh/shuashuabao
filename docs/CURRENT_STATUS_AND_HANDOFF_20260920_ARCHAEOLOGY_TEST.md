# 单人考古直达测试交接（2026-09-20）

## 已定位并修复

- 测试 14 bundle `solo_ingame_chain_20260920_195046_279500` 在创建房间 `794130` 后停在 KK 房间页。`room_start` 连续命中 `0.958`，但 trace 中没有 `RoomStart`；最终为用户手动停止。
- 因而这次没有进入选关页，问题不是考古模板识别或考古点击失败。
- 根因是 `--direct-archaeology` 在 `BOOT` 阶段就设置 `_archaeology_handoff_pending`。生产 L0 的既有安全约束看到该标记后，会在 `ROOM_WAITING` 零输入等待选关页，刻意不点击房主的“开始游戏”。
- 提交 `7ab6e27` 将此 harness 标记延后到生产已进入 `STAGE_SELECT` 的下一 tick。建房和开始游戏继续完全由生产 L0 执行；到选关页后，仍由生产考古 handoff 点击并以 fresh `kaogu`/`kaoguMode` 锚点确认。

## 新一轮 14 的验收顺序

`CreateRoom` → `RoomStart` → `STAGE_SELECT` → manifest `direct_archaeology_arm` → production 考古 request → fresh `kaogu`/`kaoguMode` confirmation。

截至本文写入，尚未获得修复后的新真机 bundle；不能据此宣称 Live PASS。
