# 13 号蹭车完整链路交接（2026-09-20）

## 本轮结论

13 号现在固定验收：`5 局真实蹭车 → 离开第 5 局房间 → 自建单人房 → 选关页点击考古 → fresh kaogu/kaoguMode 锚点确认 → 退出脚本`。

13 号启动时会只读加载正式看板，再生成临时设置副本，强制写入：

- `hitch_cycle_num=5`
- `cycle_num=5`（兼容 production runtime 的通用局数字段）
- `hitch_after_goal=arch`
- `auto_archaeology=true`

因此不会再因正式看板残留 `hitch_cycle_num=1` 而只跑一局，也不会把“跑到第 5 局”误报成完整通过。正式 `C:\Users\10639\AppData\Local\ShuaBao\user_settings.json` 不会被测试启动器改写。

## 生产收尾链路

`Mediator._finish_hitch_round()` 在第 5 局完成后设置离房与考古 handoff 标记；先完成旧房真实退出和回厅，再复用已有单人选关路由。考古按钮点击后必须拿到新一代 `kaogu`/`kaoguMode` 页面锚点，确认成功才 `COMPLETE` 并停止脚本。没有 fresh 锚点时只等待，不算 PASS。

## 今天已确认的蹭车问题与修复

1. 13 号之前实际读取的是看板局数，当前看板为 1 局；本次改为测试副本固定 5 局 + 考古收尾。
2. 蹭车链仍由 production `Mediator.tick()` 驱动，capture harness 只观察 trace/状态并汇总，不复制搜房、进房、Ready、压力、结算或回厅 FSM。
3. 单人考古直达曾在 `BOOT` 阶段过早设置 handoff，导致房间页安全零输入；已在 `7ab6e27` 延后到 production 进入 `STAGE_SELECT` 后再 arm。
4. 选关页的考古模板曾误用 `1-23` 关卡行残片，导致“考古模式”假命中；已在 `173dd8a` 替换为真实按钮模板，并更新运行时资源清单。该模板在实机 bundle 上命中 `1.000`，独立截图复核 `0.970`。

## 13 号验收标准

必须同时满足：

- `rounds_started == 5` 且每轮有真实 `ROOM_LIST → JOIN → READY → PRESSURE → OUTCOME → REAL_EXIT → LOBBY_RETURN` 证据；
- 至少一次 blocking modal recovery，且无 UNKNOWN 输入、静默停止、永久零输入 stall 或盲点回家；
- 第 5 局后出现 `ARCHAEOLOGY_HANDOFF_CONFIRMED`，并能在 manifest 中看到 fresh `kaogu`/`kaoguMode` 锚点；
- capture summary 的 `natural_e2e` 为 `PASS`。仅点击成功、单帧变化或人工点房间/准备/退出均不算通过。

## 操作

1. 通过桌面快捷方式打开 `刷刷宝 Live 实机测试.lnk`。
2. 先点“1 启动前检查”，确认 `READY FOR GT: YES`。
3. 点击“13 PRIMARY HITCH_FULL_NATURAL_E2E”。启动器会显示临时设置副本路径，随后进入完整长链。
4. 测试期间不要手动点房间、刷新、准备、开始、压力、背包或退出；紧急停止使用 `Shift+F12`。
5. 交接时提供生成 bundle 目录，重点查看 `manifest.json`、`trace` 和 `failures`；若未到 `ARCHAEOLOGY_HANDOFF_CONFIRMED`，只能记为未完成/阻塞，不能记 PASS。

## 当前待真机确认

本次代码和离线契约已完成；仍需用 13 号按钮跑一条新的 5 局实机 bundle，确认蹭车中途的密钥挑战、传家宝、时光之穴等可选路线以及第 5 局后的考古 handoff 在同一条 production 链中完整出现。此前的单人 14 号问题不能代替 13 号真机 PASS。

## 2026-09-20 20:45 bundle 复盘

`C:\tmp\shuabao-captures\hitch_lobby_chain_20260920_204522_885047` 已确认 `game_count=5`、`victory_count=5`。第 5 局退出确认点击成功，但随后旧房页面持续被识别为 `ROOM_WAITING`，最终因 UNKNOWN 输入保护而 FAIL。

根因有两层：

1. 旧房退出兜底直接取全屏最高分的 `room_exit_btn`，在这轮命中了房间内容区（约 `(731,261)` / `(768,344)`），没有命中右下角真实“退出”按钮，所以没有产生 fresh 房间列表；
2. 13 号蹭车阶段为禁止自建房会把 `auto_create_room=false` 投影到内存设置。即便离房成功，收尾只切到 `normal_farm` 也不足以进入自建房考古路由。

已修复：旧房收尾改用 `_find_hitch_exit_button()` 的右侧房间几何约束；`hitch_after_goal=arch` 收尾显式恢复 `auto_create_room=true`。下轮应看到“真实退出 → fresh 房间列表 → 自建房 → 选关考古”，而不是停在旧房。
