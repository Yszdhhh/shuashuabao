# Handoff — 蹭车升房主立即退出（2026-09-11）

本次真实事故包：
`C:\Users\10639\AppData\Local\Temp\shuabao-captures\hitch_lobby_chain_20260911_200350_246552`。

- 房间 `730795` 中，Linus 已准备后被提升为首行红色“房主”。
- KK 在该状态显示绿色“等待准备”，没有“开始游戏”；旧 ROOM 识别与升房主判断都错误依赖 Start，随后错误尝试 `HitchSelectTab`。
- 生产修复：准备过的蹭车角色一旦首行显示红色“房主”，且 ROOM 有可见退出按钮，即走既有的退出、确认、回大厅后拉黑事务；不再等待 Start，也不再使用未能反映状态文字变化的像素差阈值。
- 进房后若落入未知子窗口，搜索、刷新和房间列表页签均无输入权限；仅已识别弹窗、可信房间或可信大厅可推进。超时拒绝进房时只尝试重新获取原大厅窗口，不对未知子窗口发送点击或按键。

## 2026-09-11 晚间审计修复（黑窗口死锁 / 座位规则 / 退房链路 / 导航兜底）

根因（均有真实证据）：

1. **Join 后卡死 275s / 11min**：5177602 不是 Join 新开的子窗口，而是 20:03 误点头像后变纯黑、仍 visible 的旧房间 HWND，连续污染 20:17、20:44、20:55 三次运行（每次真实进房都是新 HWND）。`hitch_join_probe` 把它当 join child 钉住；纯黑帧在 `_tick_impl` 健康门禁（black_frame+low_entropy）处被拦，`_tick_lobby_hitch` 从未执行，`pending_join` 永不清除 → 死锁。watchdog/join-timeout/UNKNOWN 分支都没被求值。
2. **升房主后点自己头像**：房主视角（灰「等待准备」+绿「邀请」）旧 ROOM 识别失败 → UNKNOWN → 大厅 Tab 固定槽位检测落在第 1 行头像 (672,308)。
3. **f02f27c 回归**：`_hitch_host_marker_visible` 只说明「第 1 行是房主」，房主是别人坐一楼的正常房间准备后也会被判 `reject_host_takeover`。
4. **退房确认从未能点**：1c45d8e 起确认点击要求确认框与房间同 HWND，而 KK「是否确认退出房间?」是独立 440x260 HWND。
5. **已准备 vs 未准备退房**：未准备走「退出→确认」历史上多次成功；已准备旧版只按 Esc（13:38、18:56 各 3 次均无效）。b3f331f 改为点退出后从未被真机验证。

修复：

- `_capture_best`：同标题纯黑窗口不与有像素的窗口竞争；join probe 只接受 Join 后新出现、非黑的 HWND；unhealthy 分支也释放超时 pending join；L0 阶段 120s 无可用画面 → BLOCKED。
- 座位规则（用户 2026-09-11）：无论是否准备，① 我方成为房主（房主视角的座位下拉框）② 我方在一楼（准备前唯一未准备行 / 准备前后「空白→已准备」差分）③ 一楼玩家离开（第 1 行变空位或名字变化）→ 退房并拉黑；两张 fresh 帧复核。
- 退房事务统一：退出按钮 → 独立确认 HWND 上的确定 → fresh 大厅；退出/确定被吞各自有界重试，60s 硬上限 BLOCKED；70s 超时退房截止后 60s 仍未离房 BLOCKED。
- 房间页永不获得大厅 Tab 点击权（`_hitch_room_like`）。
- KK 主窗口导航终极兜底：主窗口不在房间列表且不像房间时，先点顶部「游戏」，再点侧栏「重生魔兽刷刷刷/英雄三国」；fresh 帧复核、6 次/60s 上限后 BLOCKED。导航已正确时 UNKNOWN 地图子页（如「任务」）也交回 Tab 流程。
- trace 新增 `health`、`capture{candidates,selected_by,black_hwnds}`、`hitch{pending_join,join_age_s,exit_*,self_row,seat_streak,...}`。

验证：`tests/test_hitch_live_chain_20260911.py` 用 `tests/fixtures/hitch_live_20260911/` 真实帧驱动完整 `Mediator.tick()`（多 HWND 假 KK 世界）。仍需真机验证：已准备状态点退出后 KK 是否同样弹出独立确认框。

---

离线验证（上一轮）：真实事故帧识别为 `reject_host_takeover`；蹭车安全、平台提示、历史进房回归和 host 接管场景共 44 项定向测试通过。全量 release gate 的 pytest 会占用约 2.25 GB，已按实机测试环境要求停止；此变更尚需由桌面快捷方式加载本候选 HEAD 后重新真机验证。
