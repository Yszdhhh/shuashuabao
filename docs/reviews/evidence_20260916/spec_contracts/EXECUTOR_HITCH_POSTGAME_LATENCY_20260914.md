# 执行 Agent 提示词：蹭车 09-14 晚实机复盘 + 传家宝慢 / 战后识别延迟修复

> 由本地架构会话编写。把分隔线以下全部内容交给执行 Agent。完成后把汇总报告交回 Claude 验收。

---

## 0. 背景

Owner 在 09-14 晚跑了一轮蹭车实机测试，**没有全程盯着**。反馈了两个问题：**传家宝点击慢**、**结束后识别延迟高**。另外请顺带逐帧排查局内其它潜在问题。

- 被测代码：`feat/unattended-recovery-20260914` @ `cc179626aa51e7e42d1c2d810cb8eb3d57de0eb9`（PR #23）。
- 主证据包：`C:\tmp\shuabao-captures\hitch_lobby_chain_20260914_175241_393670\`（约 70 分钟，1792 帧，1182 个事件）。
- 半截包：`C:\tmp\shuabao-captures\hitch_lobby_chain_20260914_174228_304699\`（76 帧，未正常结束，确认是不是被手动中止的）。
- 包内结构：`manifest.json`（汇总、`events[]`、`hitch_lobby_chain.metrics`）、`trace.jsonl`（逐 tick）、`frames\fNNNN_*.png`（截图）、`failures\`、`incidents\`。

## 1. 已从时间线看出的线索（at_s 为包内相对秒；需要你用帧来证实或推翻）

| 局 | 继续游戏 | 存档 8 卡 + 时光之穴 | 关存档 → 开传家宝 → 选 Boss → 关弹窗 | 退出 |
|---|---|---|---|---|
| R1 | 626.2 | 630–679（BossNotUnlockedLast） | 681.4 → 684.6 → 692.0 → 697.6（开到选 **7s**） | 757.1（关弹窗后约 60s） |
| R2 | 1617.9 | 1621–1666 | 1668.8 → 1671.5 → 1682.6 BossLastVisibleFallback → 1688.2（**11s**） | 1749.8 |
| R3 | 2647.1 | 2651–2709（时光之穴滚动 20s 后 LastVisibleFallback） | 2712.0 → 2715.2 → 2722.3 → 2727.9 | 2787.8 |
| R4 | 3949.5 | 3956–4019（同上约 24s） | 4021.5 → 4024.6 → **BossConfigured-scroll 4027.8 … DismissHeirloomDialog 4106.1（开到关 81s）** | 4167.1 |

疑点：
1. **传家宝慢**：R4 从打开传家宝到关弹窗用了 81 秒，R1 只要 7 秒。查清 R4 是在反复滚动找 `18乌索克`，还是在等"已挑战"的后置确认，还是在走 `_heirloom_boss_confirm_expired`；时光之穴在 R3、R4 各滚了 20 秒以上才兜底，也一起查。滚动步长、复核间隔（`_post_game_action_recheck`）、每张卡的 OCR/模板耗时，都要给出实测时间分解。
2. **结束后识别延迟**：
   - R3 的最后一个局内动作是 2493.2（OpenTreasurePanel），而 ContinueGame 在 2647.1 才点，**中间约 154 秒**。找出胜利页/胜利横幅第一次出现在哪一帧，从出现到点击之间代码在做什么（`_post_game_state` 的分类结果、`_victory_continue_since`、是否被面板/背包/聊天条挡住）。
   - 4 局关弹窗之后都是约 **60 秒**才退出，`metrics.victory_count=0`：说明传家宝后规则 1（右侧"已获取"装备弹窗 → 立即退出）**一次都没触发**，全部走了 60 秒超时。逐局看关弹窗后 60 秒内的帧，里面有没有"已获取"装备弹窗：如果有，就是 `_heirloom_loot_popup_visible` 漏识别（这正是"结束后识别延迟高"最可能的来源）；如果没有，就在报告里写清楚。
3. **其它局内疑点**（逐帧核实，判断是生产缺陷、harness 误判还是环境问题）：
   - R3 局内有 3 次 `treasure关闭`（2310.1、2390.0、2465.0）：按当前代码，蹭车宝物只有 OCR 没读出名字、并且还能刷新时才会关，核实每次的原因和面板内容。
   - 1960.6 进局、约 2004 就回到大厅：这一局为什么这么短（房主退出？失败？被踢？）。
   - 2156.2 进局后 2160.2 点了 `DismissFailureReward`：刚进局就出现失败奖励弹窗，是不是残留的上一局页面。
   - `metrics.longest_stall_s=113.9`：定位是在哪个阶段、什么画面。
   - `final_status=FAIL`，`final_reason="production input on UNKNOWN lobby/game surface"`：上次已知是 harness 把退出确认框分类成 UNKNOWN，确认这次是不是同一个原因。
   - 黑商在 R2 有连续多次 `BlackMerchant-refresh`（1206–1243），确认刷新次数是否符合预期、有没有浪费杀敌数。

## 2. 修复规则

- 从 `feat/unattended-recovery-20260914` 拉分支 `fix/hitch-postgame-latency-20260914`，**禁止在 main 上提交**（仓库有 `.githooks`，执行 `git config core.hooksPath .githooks`）。
- 一个 commit 只动一层（L1 局内 / 恢复与战后 / 感知）。
- 每个修复都要有**真实帧回归测试**：从证据包里取帧，按 PNG 无损保存到 `tests/fixtures/hitch_postgame_20260914b/`。**出问题的那一环不许 mock**（反例：b66f1ce 的测试 mock 掉了入口识别，结果是假绿）。新测试必须在修复前的代码上失败。
- 新增模板素材要登记到 `config/runtime_asset_manifest.json`，`GATE_BASELINE.json` 只能按工具流程带 `--reason` 更新，并在报告里说明为什么变。
- 调滚动/复核节奏时，不能削弱"找不到目标就点能点到的最后一张卡；一张都认不出就跳过；任何 Boss 失败都不停机"这条用户规则。
- 验证：先跑相关测试；再在**游戏关闭的状态下**跑 `python tools/release_gate.py`（本机内存紧，游戏开着时整套 pytest 会出现 0xC0000142 假失败）。改了 `src/shuabao/` 就要重定 `tools/live_harness_identity.py` 和 `tests/test_live_harness_refresh.py` 的基线，把 Live lnk 的 `-ProductionSourceSha` 改成新的 HEAD，再用 `python tools/live_scenario_capture.py identity` 确认 READY。
- 不打正式包，不碰开发机 staging 订阅服务（18010/18011、cloudflared），不改 `%LOCALAPPDATA%\ShuaBao` 的安装。

## 3. 分析技巧（避坑）

- `trace.jsonl` 里混着 harness 行（相对时间戳、没有 `hwnd` 键）和 mediator 行（绝对时间戳、有 `hwnd`），分析时只看 mediator 行。
- `frames\fNNNN` 的编号**不是** tick，要用 `manifest.events[]` 的 `action.reason` 找 `frame_before` / `frame_after`；两边 fingerprint 格式不同，对不上。
- 离线重放要设置实机的 `med._ui_scale`（这批帧是 1600×900，就是 1.0）；走完整 tick 要 patch `reacquire_target_window`、`capture_reacquire_target_window`、`activate_window`、`is_window_minimized`。
- 广场 NPC 标签**鼠标悬停时是粗体**，否则是细体；两种都有模板，还有 OCR 兜底（日志关键字 `OCR 兜底`）。

## 4. 交付（交回 Claude 验收）

1. 每局一行的表：进局、胜负、战后各步的耗时（继续游戏、存档 8 卡、时光之穴、传家宝、退出），以及每一步的等待原因。
2. 每个疑点：结论（生产缺陷 / harness 误判 / 环境问题 / 正常）、证据帧文件名、代码位置（函数名 + 行号）。
3. 修复：commit 列表；每个修复对应的回归测试名，以及"修复前失败、修复后通过"的输出；门禁结果。
4. 修复前后各项耗时的对比（离线能测的就测，测不了的写"需要实机验证"）。
5. 还需要 Owner 在实机上验证的清单。
