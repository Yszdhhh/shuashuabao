# Claude 本地独立审查交接（2026-09-09）

## 审查方式

请只做独立审查和报告，暂时不要修改文件，避免与正在收尾的 Codex 互相覆盖。所有结论必须引用实际文件、函数和行为路径；不要只看提交说明。

## 本地工作区与基线

- Production worktree: `G:\刷刷宝\Worktrees\stability-s0-20260908`
- Production branch: `refactor/stability-s0-20260908`
- Production HEAD / candidate: `332cc75e36ecb21ead31120021d1c4d1bfbfff1b`
- Live Harness worktree: `G:\刷刷宝\Worktrees\live-harness-current-20260908`
- Live Harness branch: `test/live-harness-current-20260908`
- Live Harness 代码候选提交: `226cf92` + identity 提交 `55c4512`（完整 HEAD 以 `git rev-parse HEAD` 为准）
- Harness identity baseline: `332cc75e36ecb21ead31120021d1c4d1bfbfff1b`
- 桌面入口: `C:\Users\10639\Desktop\刷刷宝 Live 实机测试.lnk`

Production `332cc75` 已推送远端。Harness 全量测试已通过，等待推送；未能重建 EXE，原因是当前环境缺少仓外真实 Ed25519 manifest 签名材料。

## 用户的真实业务诉求

1. 脚本必须能长期运行多局，不得在刚进游戏、加载过场、局内某一步失败、结算转场或退出重试时无故终止。
2. 大厅脚本启动时，无论当前在地图详情、评论、社区攻略、排行榜等页面，第一步都应用可信的「房间列表」控件切到房间列表，然后才找房。
3. 大厅中遇到「房间已满」、普通提示等弹窗，应点取消或关闭，然后继续找房，不能因 440×260 子窗口或窗口化/全屏尺寸不同而卡死。
4. 进房后应等待游戏启动，进局后完成开局步骤：压力转移、自动主线任务、金币/木材/经验/宝物四个挑战。
5. 然后去黑商，只买「吞噬丹」，不买木头、折扣商品或其他物品。
6. 然后打开宝物，只拿绿色级别且名称包含「神符」的任意宝物。
7. 即使自动任务、四挑战、黑商或宝物某步失败，也不能退出脚本；应安全跳过该步并蹭车等待本局胜负。
8. 胜利时必须点「继续游戏」，处理存档挑战、传家宝等战后页面，再安全退出回大厅继续找房。
9. 失败时应走失败确认/退出链，回大厅继续找房。
10. `hitch_cycle_num` 投影到 production `cycle_num`；只有「已验证离局」才计一局，达到设定局数才正常停止。
11. 必须保留 Shift+F12、用户手动停止、无管理员权限/UIPI 这些真正的安全终止。
12. Live Harness 的「完整链路」不能在第一次识别到局内 HUD 时就自动结束；它必须能观察完整一局和多局循环。

## 本轮已完成的修改

### Production

- `6719046`: 评论/社区等非房间列表页面上，可信切换到房间列表。
- `83ab3a7`: 加载过场中自动任务 UNKNOWN 不再终止；战后链保持运行。
- `fab5770`: Ready 180s 退房重试耗尽后保持零输入观察；清理跨 episode Ready 超时状态。
- `3ac2dc0`: 压力转移窗口改用本局开始时间；蹭车自动任务/四挑战重试耗尽后跳过而不停机；黑商等待出现且无吞噬丹/无刷新时转宝物；存档挑战 COMPLETED/UNKNOWN/缺卡面证据改为有界处理。
- `5b5c87f`: 蹭车胜负已验证离局时才增加 `game_count`；达到 `cycle_num` 转 COMPLETE；清上局 deadline/outcome，防次局立即超时退出。
- `c446122`: 补充自动任务蹭车有界跳过回归。
- `332cc75`: 蹭车中不健康帧、胜利继续、战后转场、存档/传家宝关闭、退出/确认重试耗尽时，改为零输入等待或重新武装，不再终止整个 run。

### Live Harness

- `226cf92`: 删除 `hitch_lobby_chain && recorder.solo_observer.is_pass -> break`；首次 HUD PASS 只作为观测证据，不再结束一小时完整链路测试。
- `55c4512`: Harness identity 更新到 production `332cc75`。

## 已知测试结果

- Production L1 定向：`141 passed, 6 subtests passed`。
- Production 结算/跨局/回归定向：`105 passed, 6 subtests passed`。
- Production 跨局核心：`32 passed`。
- Harness 定向：`103 passed`。
- Production release gate：`1681 passed, 13 skipped, 2 xfailed`，frozen replay / 148 个 scene template / 56 个 contract 全部 PASS。
- Harness 全量：`1700 passed, 13 skipped, 2 xfailed, 211 subtests passed`；仅有 2 条已知 OCR stderr reader 关闭竞态 warning。
- 一次沙箱内 Harness 运行出现 20 个 Windows Temp ACL 权限错误；沙箱外重跑为 `103 passed`，不是产品逻辑失败。
- Harness source identity：production code diff `CLEAN`，runtime source verified；因当前 worktree `dist\ShuaBao\ShuaBao.exe` 尚不存在，EXE identity 为 `MISSING`。
- `build_release.ps1 -SkipGate -NoDeploy` 在产生副作用前正确阻止：缺少 `ManifestSigningKeyPath` / `ManifestSigningKeyId` / `ManifestPublicKeysPath`。不得伪造私钥或手改 identity 绕过。
- 桌面快捷方式已验证指向当前 `live-harness-current-20260908\live_scenario_launcher.ps1`。

## 请 Claude 重点独立审查

1. 全量搜索 `LoopAction.Break` / `Phase.ERROR` / `stop()` / timeout / retry-exhaustion，列出蹭车正常运行仍可到达的提前退出路径。
2. 从任意 KK 地图页签出发，证明「切房间列表 → 搜房 → 拒绝满房/弹窗 → 加入 → Ready → 进游戏」是可达链。
3. 核对窗口 ownership：KK 主窗口、440×260 弹窗、游戏窗口、窗口化/全屏/DPI 变化时，capture 和业务分类是否可能拿错 surface。
4. 证明开局顺序可达：压力转移 → 自动主线 → 四挑战 → 黑商只拿吞噬丹 → 宝物只拿绿色 xx神符 → idle 等待胜负。
5. 检查某步缺锨点、OCR UNKNOWN、输入后置确认失败时，是否真的会跳过并继续，而不是活锁或默默 Break。
6. 审查胜利链：POST_VICTORY → Continue → ARCHIVE_PANEL → 存档挑战 → NPC_HUB → 传家宝 → QUIT/NEXT → LOBBY_ROOM。
7. 审查失败链：失败证据 → recovery → 已验证退出 → 计数/清局状态 → LOBBY_ROOM。
8. 验证 `game_count/cycle_num/failure_streak/_round_deadline/_outcome_recorded` 在多局中没有漏计、重计、次局污染或提前停止。
9. 审查 Harness 一小时循环的所有终止条件，确保首次 HUD/observer PASS 不再导致测试提前结束。
10. 对 production parent `83ab3a7cc416a2b11cc815af18db400f6ccd16de..332cc75e36ecb21ead31120021d1c4d1bfbfff1b` 和 Harness 当前差异做回退审查，明确 `UNINTENDED_REVERT` 是否为 0。

## 输出格式

按严重度输出 `P0 / P1 / P2`，每项必须包含：

- 可达条件；
- 实际函数/文件/行为路径；
- 用户可见后果；
- 现有测试为什么没拦住；
- 最小修复建议和应新增的回归用例。

最后单独给出：

- `SAFE_TO_GT: YES/NO`
- `UNINTENDED_REVERT: 0/N`
- `REMAINING_EARLY_EXIT_PATHS: N`
- `REMAINING_HANG_PATHS: N`
- 明早实机验收必测的最短步骤。
