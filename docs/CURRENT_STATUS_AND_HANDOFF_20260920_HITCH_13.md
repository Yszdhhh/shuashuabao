# 13 号蹭车完整链路交接（2026-09-20）

## 本轮结论

当前 13 号默认试跑为：`1 局真实蹭车 → 离房 → 自建单人房 → 选关页点击考古 → fresh kaogu/kaoguMode 锚点确认 → 退出脚本`。

13 号启动时会只读加载正式看板，再生成临时设置副本，强制写入：

- `hitch_cycle_num` / `cycle_num` 默认是 `1`（兼容 production runtime 的通用局数字段）
- `hitch_after_goal=arch`
- `auto_archaeology=true`

这是为了先验证“退出切入考古”链路；正式 `C:\Users\10639\AppData\Local\ShuaBao\user_settings.json` 不会被测试启动器改写。需要长链时，在启动器进程环境设置 `SHUABAO_HITCH_E2E_ROUNDS=5`，不设置则保持快速 1 局试跑。

## 生产收尾链路

`Mediator._finish_hitch_round()` 在目标局完成后设置离房与考古 handoff 标记；先完成旧房真实退出和回厅，再复用已有单人选关路由。考古按钮点击后必须拿到新一代 `kaogu`/`kaoguMode` 页面锚点，确认成功才 `COMPLETE` 并停止脚本。没有 fresh 锚点时只等待，不算 PASS。

## 今天已确认的蹭车问题与修复

1. 13 号之前实际读取的是看板局数；本轮用隔离副本默认 1 局 + 考古收尾，专门验证退出切入链路。长线程通过 `SHUABAO_HITCH_E2E_ROUNDS` 切换，不再改代码。
2. 蹭车链仍由 production `Mediator.tick()` 驱动，capture harness 只观察 trace/状态并汇总，不复制搜房、进房、Ready、压力、结算或回厅 FSM。
3. 单人考古直达曾在 `BOOT` 阶段过早设置 handoff，导致房间页安全零输入；已在 `7ab6e27` 延后到 production 进入 `STAGE_SELECT` 后再 arm。
4. 选关页的考古模板曾误用 `1-23` 关卡行残片，导致“考古模式”假命中；已在 `173dd8a` 替换为真实按钮模板，并更新运行时资源清单。该模板在实机 bundle 上命中 `1.000`，独立截图复核 `0.970`。

## 13 号验收标准

必须同时满足：

- `rounds_started == 1` 且有真实 `ROOM_LIST → JOIN → READY → PRESSURE → OUTCOME → REAL_EXIT → LOBBY_RETURN` 证据；
- 至少一次 blocking modal recovery，且无 UNKNOWN 输入、静默停止、永久零输入 stall 或盲点回家；
- 第 1 局后出现 `ARCHAEOLOGY_HANDOFF_CONFIRMED`，并能在 manifest 中看到 fresh `kaogu`/`kaoguMode` 锚点；
- capture summary 的 `natural_e2e` 为 `PASS`。仅点击成功、单帧变化或人工点房间/准备/退出均不算通过。

## 操作

1. 通过桌面快捷方式打开 `刷刷宝 Live 实机测试.lnk`。
2. 先点“1 启动前检查”，确认 `READY FOR GT: YES`。
3. 点击“13 PRIMARY HITCH_FULL_NATURAL_E2E”。启动器会显示临时设置副本路径，随后进入一局退出切考古试跑。
4. 测试期间不要手动点房间、刷新、准备、开始、压力、背包或退出；紧急停止使用 `Shift+F12`。
5. 交接时提供生成 bundle 目录，重点查看 `manifest.json`、`trace` 和 `failures`；若未到 `ARCHAEOLOGY_HANDOFF_CONFIRMED`，只能记为未完成/阻塞，不能记 PASS。

## 当前待真机确认

本次代码和离线契约已完成；当前先用 13 号按钮跑一条新的 1 局实机 bundle，确认退出切入考古。通过后设置 `SHUABAO_HITCH_E2E_ROUNDS=5` 验证密钥挑战、传家宝、时光之穴等可选路线。此前的单人 14 号问题不能代替 13 号真机 PASS。

## 2026-09-22 长线程异常收尾补充

昨晚长线程在第 11 个房间遇到“等待 1 号位选择难度”超时。该页面是已识别的客号预开局页，但没有常规局内左上退出按钮；旧 QUIT 分支将其降为 UNKNOWN，15 秒后以 `exit button timeout` 停止。

已补齐：该已知页面找不到专用退出按钮时，只发送一次语义 `Esc` 并进入既有确认/回房观察链；取得 fresh 房间证据后拉黑该房并**继续搜房**（Owner 2026-09-22 裁定：单个房主磨蹭不得提前结束长线程；考古只由 cycle_num 达标 / 挑战券预算触发）。该异常不增加 `game_count`，不扣挑战券。

已知限制：客号全程看不到选关页，`_ticket_balance` 恒为 None（fail-open），蹭车模式下"门票耗尽转考古"不会触发，长线程终点只能由 cycle_num 决定。

搁置：同批次的「诅咒之力/提高上限 默认不拿」改动未提交——违反 `test_treasure_negative_fixtures_contract`（每张负面卡须 ≥1 真机面板帧），待补实机帧后单独提交。

离线验证：`python -m pytest tests/test_hitch_guest_stage_select_recovery_20260921.py tests/test_s0_hitch_failure_exit.py tests/test_ticket_budget_20260921.py tests/contract -q` → `86 passed, 111 subtests passed`（Owner 裁定后重跑）。

仍需真机：在房主选难度页超过阈值后，确认 `Esc → 退出确认/平台房间 → 拉黑并继续搜房` 的实际 UI 变更；若 `Esc` 未产生可观察变化，保持零输入并记录为 BLOCKED，不把点击发送当作成功。

## Owner 待裁决（本任务只记录，不改代码）

1. `hitch_after_goal="solo"` 的看板标签是“去单人刷票”（`main_window.py:2810`），但 `_finish_hitch_round()` 当前实现为 `COMPLETE + stop + Break`，实际直接结束脚本，没有进入单人刷票。预期应有“考古 / 单刷 / 结束脚本”三个分支，目前只有两个且其中一个名不副实。
2. `auto_create_room=True` 当前只写在 `arch` 分支内。按“目标局数到达后即解禁”的语义，应移到达标判断之后、分支判断之前；本轮 arch 不暴露问题，因为其他分支直接停止。

## 2026-09-20 20:45 bundle 复盘

`C:\tmp\shuabao-captures\hitch_lobby_chain_20260920_204522_885047` 已确认 `game_count=5`、`victory_count=5`。第 5 局退出确认点击成功，但随后旧房页面持续被识别为 `ROOM_WAITING`，最终因 UNKNOWN 输入保护而 FAIL。

根因有两层：

1. 旧房退出兜底直接取全屏最高分的 `room_exit_btn`，在这轮命中了房间内容区（约 `(731,261)` / `(768,344)`），没有命中右下角真实“退出”按钮，所以没有产生 fresh 房间列表；
2. 13 号蹭车阶段为禁止自建房会把 `auto_create_room=false` 投影到内存设置。即便离房成功，收尾只切到 `normal_farm` 也不足以进入自建房考古路由。

已修复：旧房收尾改用 `_find_hitch_exit_button()` 的右侧房间几何约束；`hitch_after_goal=arch` 收尾显式恢复 `auto_create_room=true`。下轮应看到“真实退出 → fresh 房间列表 → 自建房 → 选关考古”，而不是停在旧房。

## 2026-09-22 Boss 后置语义最小收口（恢复与战后层）

视觉验收（`_facts_20260922/mechanics_solo/BOSS_VISUAL_ACCEPTANCE_20260922.md`）撤回旧「掉落弹窗/击杀BOSS=受理」结论。双帧未识别到卡 **只支持停止重复定位/空滚**，不证明受理或成功。

改动（`src/shuabao/mediator.py` 两条调用路径 + 测试 + `docs/BOSS_CHALLENGE_20260922.md`）：
- 双帧无卡时：`_time_cave_boss_done=True`、`_time_cave_boss_result_confirmed=False`、`_time_cave_boss_confirm_unconfirmed=True`、`_time_cave_boss_clicked_at=None`
- 不新增 list_closed / 掉落 OCR / 战果识别；保留有界滚动、无锚点零输入、卡片重现重置、超时 incident

仍需实机：业务受理/成功锚（掉落条或战果 HUD）；tick4081 拒点窗；game_count 映射；六次兜底时 17 解锁状态。验收目标是「收敛不虚报受理」，不是 Boss 实机成功。
