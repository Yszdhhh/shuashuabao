# 云端 Production 整合审查交接（2026-09-09）

> 给云端 Agent：这是当前大厅蹭车、局内长跑、胜负结算与 Live Harness 的唯一最新整合入口。
> 请以实际代码和测试为准，不要只依据 commit message。当前结论是 `SAFE_TO_GT: NO`。

## 1. 当前版本与远端状态

| 对象 | 分支 | 当前 HEAD | 状态 |
|---|---|---|---|
| Production | `refactor/stability-s0-20260908` | `d4aa92cbdd9207f25cea6b8e99c6692afafa5588` | 已推送，工作区 clean |
| Live Harness | `test/live-harness-current-20260908` | `d9ab54af1f7558ff07343785453835a25a2458fd` | 已推送，工作区 clean |
| Harness 冻结 production baseline | — | `332cc75e36ecb21ead31120021d1c4d1bfbfff1b` | 落后当前 production 一提交 |

因此当前状态是：

```text
Production HEAD             d4aa92c
Harness production baseline 332cc75
Production Code Diff        NOT_CLEAN
READY FOR GT                NO
```

不要把 Harness identity 直接推进到 `d4aa92c` 后就宣称可测。`d4aa92c` 的蹭车宝物无匹配回退行为仍违反产品诉求，且 Claude 审查发现的 P0/P1 均未在该提交中修复。

## 2. 用户要求的真实完整逻辑

1. 脚本需要长期连续运行多局，不能因一次识别失败、加载、窗口变化、结算或退出重试而自行结束。
2. 从 KK 地图详情、评论、社区攻略、排行榜等任意地图页签启动时，第一步先通过可信控件切到「房间列表」。
3. 搜房后遇到房间已满、密码、等级限制或普通大厅提示，点取消、关闭或叉，并继续找房；不得卡在独立子窗口。
4. 加入房间后 Ready，等待房主开局；进入游戏后依次处理压力转移、自动主线任务、金币/木材/经验/宝物四个挑战。
5. 然后打开黑商，只拿「吞噬丹」。不得购买木头、折扣商品或其他物品。
6. 然后打开宝物，只拿同时满足以下两个条件的宝物：
   - 品质为绿色；
   - OCR 名称包含「神符」。
7. 没有绿色 `xx神符` 时可以有界刷新；刷新耗尽后关闭/跳过。绝不能按品质拿红、橙、紫或其他宝物。
8. 上述任一步缺锚点、OCR UNKNOWN 或后置确认失败时，应有界跳过并继续等待本局胜负，不能退出整个脚本，也不能无限卡住。
9. 胜利后点「继续游戏」，进入存档挑战，处理四个存档挑战以及配置的时光之穴/传家宝步骤，再退出回大厅继续找房。
10. 失败后走失败确认与退出链，确认离局后回大厅继续找房。
11. 只有「已验证离局」才能增加 `game_count`；达到 `hitch_cycle_num -> cycle_num` 才正常结束。
12. Shift+F12、用户主动停止、UIPI/非管理员权限失败仍是允许保留的安全终止。
13. Live Harness 的 `hitch_lobby_chain` 必须观察完整一局和多局循环，不能首次识别 HUD 就结束。

## 3. 实机测试已发现的问题

### 3.1 大厅链

- 在评论页启动时，脚本没有自动切到房间列表；社区攻略、排行榜等其他页签尚未逐一实测。
- 「房间已满」是一个约 `440x260` 的独立 KK 子窗口。旧测试程序多次停在该弹窗，不点取消/叉，也不继续找房。
- 用户担心窗口化、全屏、DPI 或不同大小子窗口会使定位失效。当前实现不是 UIA 枚举真实 Button，而是先选 HWND，再在截图中按模板、ROI、颜色和几何证据找按钮。
- `capture.py::rank()` 虽然计算了 `area`，但没有把面积加入分数；多个 KK 窗口仍可能因 foreground 加分导致子窗口排在主窗口前面。已知 pending-join 子窗有专项处理，但不能据此证明所有弹窗和所有页面的 surface ownership 都正确。

### 3.2 局内链

- 实机已经正常进入游戏，但脚本在一局中途结束；没有等到胜负，也没有完成后续多局。
- 实机没有完成黑商吞噬丹与宝物绿色神符步骤。
- 即使黑商/宝物没有拿到，脚本也应继续等待胜利或失败，而不是直接结束或失去动作。
- 胜利截图已经出现「继续游戏」和「存档挑战」，但测试程序没有继续点击和完成战后链。

### 3.3 测试/发布链

- 旧 Live GUI 曾因 Harness 与 production identity 不一致显示全红，无法开始测试。
- Harness 后来同步到 `332cc75` 并通过 source identity，但没有新的 EXE：构建被仓外真实 Ed25519 manifest 签名材料缺失正确阻断。
- 桌面快捷方式已确认指向 `live-harness-current-20260908/live_scenario_launcher.ps1`；不得用旧 EXE 或伪造签名材料绕过构建门禁。

## 4. 已经提交的修改

以下是「代码已经修改」的事实，不等于全部经过新一轮实机验证。

### 4.1 Production：`6719046..332cc75`

- `6719046 fix(lobby)`: 为评论/社区等非房间列表页面补充可信的房间列表切换路径。
- `83ab3a7 fix(l1)`: 加载过场的自动任务 UNKNOWN 不再提前终止；增强战后继续运行。
- `fab5770 fix(lobby)`: Ready 180 秒退房重试耗尽后保持长跑；清理跨 episode Ready 超时状态。
- `3ac2dc0 fix(l1)`: 压力转移按本局计时；自动任务和四挑战在蹭车模式有界跳过；黑商无吞噬丹/无刷新时转宝物；存档挑战 UNKNOWN/缺卡面有界跳过。
- `5b5c87f fix(recovery)`: 只有验证离局才计数；达到局数转 COMPLETE；清理跨局 deadline/outcome。
- `c446122 test(l1)`: 增加蹭车自动任务有界跳过测试。
- `332cc75 fix(recovery)`: 胜利继续、战后转场、存档/传家宝关闭、退出确认等若干重试耗尽改为蹭车重新武装或零输入等待，不再直接终止。

`332cc75` 对应的已记录验证：

- Production release gate：`1681 passed, 13 skipped, 2 xfailed`；frozen replay、148 个 scene、56 个 contract PASS。
- Harness 全量：`1700 passed, 13 skipped, 2 xfailed, 211 subtests passed`；仅两条已知 OCR stderr reader 关闭竞态 warning。
- Harness 已删除首次 HUD/observer PASS 就中断一小时循环的终止条件。

这些测试证明离线门禁通过，不证明用户截图中的大厅弹窗、评论页、全屏/DPI、黑商和完整胜负链已经实机通过。

### 4.2 Production：`d4aa92c`

该提交做了普通模式宝物品质优先和 `PolicySettings.mode_id` 隔离，并为 `lobby_hitch` 增加绿色名称含「神符」的优先规则。

但当前实现仍有明确缺陷：

```text
有绿色 xx神符  -> 选绿色 xx神符
没有绿色 xx神符 -> 回落普通品质链，选择其他高品质宝物
```

测试 `test_hitch_mode_without_green_talisman_falls_back_to_quality` 还把这个错误行为固定成了通过条件。产品要求恰好相反：没有绿色 `xx神符` 就刷新或关闭，绝不拿其他宝物。

此外，蹭车宝物的实际入口在 `mediator._ocr_reward_choice()`；`ocr_mode != "live"` 时仍会走 `_rarity_choice()`。因此只改 `choice_policy` 不能堵住非 live OCR 的品质兜底旁路。

结论：保留该提交中普通模式品质裁决的独立价值，但云端整合时必须修正蹭车分支和对应测试，不能直接同步到 Harness 进行正式 GT。

本次交接前已在 `d4aa92c` 上重新执行完整 `python tools/release_gate.py`：

- pytest：`1692 passed, 13 skipped, 2 xfailed`；
- frozen replay：PASS；
- scene templates：`148 passed, 0 missing`；
- contracts：`56 passed`；
- release gate：`PASS（4/4）`。

第一次沙箱内执行曾因无法写入 `%LocalAppData%\ShuaBao\logs\ShuaBao.log` 出现两个 pytest collection `PermissionError`；在正常本机权限下重跑即得到以上 4/4 PASS。该环境错误不是产品断言失败。即便离线 gate 通过，前述严格神符规则、实机窗口 ownership 以及 Claude 找出的可达挂起/提前结束路径仍未解决，所以 `SAFE_TO_GT` 继续为 `NO`。

### 4.3 Live Harness

- `226cf92`: 删除 `hitch_lobby_chain && observer.is_pass -> break`；首次 HUD PASS 只记录 checkpoint，不结束完整测试。
- `55c4512`: identity baseline 更新到 production `332cc75`。
- `115088a/125f79d/d9ab54a`: 写入长跑审查交接、最终 gate/build blocker 和并发改动说明。

## 5. Claude 只读审查发现、尚未修复的问题

Claude 审查基线为 production `332cc75` + Harness `d9ab54a`。它没有修改文件。以下问题经再次对照代码后大部分成立。

### P0：阻断无人值守多局

#### P0-1 游戏窗口丢失/最小化/持续不健康帧会永久挂起

- 路径：`src/shuabao/mediator.py::_tick_impl()` 健康门禁。
- hitch 分支在健康失败后无界 `Continue`，局内 hard deadline 和业务状态机均无法运行。
- 后果：房主解散、游戏崩溃、窗口被关或最小化后，既不回大厅也不停机，只能人工停止。
- 不应简单在 60 秒后盲目切大厅。应先尝试恢复同一 HWND/重新捕获；只有确认游戏窗口消失且新鲜证据证明 KK 大厅存在，才清局状态并转 `LOBBY_ROOM`。

#### P0-2 `_recovery_failed()` 在蹭车模式仍直接停机

- 路径：`src/shuabao/mediator.py::_recovery_failed()`。
- 失败页面按钮、锚点或退出后置确认识别不到时，会 `Phase.ERROR + stop() + Break`。
- 后果：第一局失败就可能结束整个长跑。
- 修复不能只清状态后盲目回大厅；需进入有界的「等待验证离局/重新取证」路径，只有确认 L0 或确认游戏窗口消失后才 handoff。

### P1：高概率卡住或提前结束

#### P1-1 大厅未知通用弹窗永久零输入

- 路径：`_tick_lobby_hitch()` 的 `UNKNOWN_GENERIC_MODAL`。
- `Esc` 被输入层判成功但弹窗实际未关闭时，`pending_join` 已被清掉；下一 tick 进入未知弹窗分支并永久等待。
- 需要在正确子 HWND 上有界尝试 Esc、受锚定的取消或 X，并验证弹窗消失；之后重新取得 KK 主窗口并继续找房。

#### P1-2 暂停恢复五次耗尽会停机

- 路径：`_maybe_resume_paused()`。
- 点击被拒也会增加 attempts，五次后直接 `ERROR + stop + Break`。
- hitch 中应有界重新武装/跳过，不能结束整个 run。

#### P1-3 两处 unverified archive entry 会停机

- 路径：`_tick_main_line()` 的两处局尾 archive 门禁。
- 局尾 HUD 误匹配 archive 时立即终止。
- hitch 应保持零输入观察或进入受证据约束的战后分类，不能直接 stop。

#### P1-4 最小化窗口恢复只写标志，没有执行恢复

- 路径：capture 后的 minimized 检查。
- 当前只执行 `frame.is_minimized = True`，没有调用恢复窗口；该字段也没有后续消费者。
- 需真正恢复目标窗口，或由 P0-1 的有界 surface 恢复路径负责，不得保留「注释承诺恢复、实现没有动作」的状态。

#### P1-5 配置 `sgzx_boss` 时存档面板可能永久卡住

- `_maybe_challenge_configured_boss()` 的各分支都返回 `LoopAction.Continue`。
- Boss 卡始终不可见时，调用方后续关闭存档面板的路径到不了；只能等一小时 round timeout。
- 需增加有界观察/尝试预算；耗尽后标记本步骤跳过并继续关闭存档面板，不能把该局记成 TIMEOUT。

### P2：长跑退化和业务正确性缺口

1. `auto_secret_realm` 未在 `lobby_hitch.hidden_defaults` 固定为 `false`，可能继承其他模式设置并进入六条仍会停机的大秘境路径。
2. `_hitch_blacklisted_room_keys` 全 run 只增不减；长跑后可加入房间单调枯竭。应按 TTL 或 episode 老化。
3. 面板 episode 达上限后把 cooldown 写成 `float("inf")`；可能让本局压力转移、自动任务、四挑战、黑商和宝物永久被中心面板 FSM 阻挡。
4. `ocr_mode != "live"` 时蹭车 treasure 仍按品质兜底，违反「只拿绿色 xx神符」。此项对当前业务应提升为正式版阻断项。
5. 存档挑战点击被拒时不增加预算、不更新冷却，可能每 tick 重复点击。
6. `STAGE_SELECT` 和 `ROOM_WAITING + game window` 对不可分类页面缺少最终收口。
7. KK 子窗口枚举要求 `width > 200 && height > 200`；已知 `440x260` 可通过，但更矮的提示窗会被过滤。此项需真实样本或保守的子窗口 ownership 规则后再改门槛，不能简单放宽并盲点。
8. `lobby_popup_title` 未在 `config/scenes.json` 定义，相关探测恒为空；当前通用弹窗识别面比代码表面上窄。

Claude 报告最后写了 `SAFE_TO_GT: YES（带条件）`，但同时列出默认配置仍可达的五条提前结束和多条无界挂起。这两个结论自相矛盾。针对用户要求的无人值守多局，正确裁决是：

```text
SAFE_TO_GT: NO
UNINTENDED_REVERT at 332cc75: 0
REMAINING_EARLY_EXIT_PATHS: 至少 5 条默认可达 + 6 条配置继承相关
REMAINING_HANG_PATHS: 至少 7 条
```

## 6. 云端整合的必修范围

请从 production `d4aa92c` 开始整合，保留 `6719046..332cc75` 已有行为，并按项目规则分层提交，避免为修一个问题回退上一提交。

### 6.1 Recovery / 长跑收口

- 为 hitch 不健康帧增加有界 surface 恢复；先恢复/取证，确认 L0 后才能回大厅。
- 为 hitch `_recovery_failed()` 增加不终止 run 的验证离局路径。
- 保留 Shift+F12、用户停止、UIPI/权限失败的真正终止语义。

### 6.2 L0 大厅

- 对地图详情、评论、社区、排行榜等页面验证房间列表切换锚点和点击后置条件。
- 对 pending-join 子窗口、房满/密码/等级/普通提示实现有界取消/关闭，并验证 modal 消失。
- 收口主窗口/业务子窗口 ownership；不要把 `area` 变量或注释当成已实现的排序规则。
- 最小化/恢复和全屏/DPI 必须使用当前 HWND/client 坐标重新取证，禁止固定绝对屏幕坐标兜底。
- 给黑名单增加合理老化，避免多小时运行后房源耗尽。

### 6.3 L1 局内与战后

- 暂停恢复耗尽、archive 未验证命中、中心面板 episode 上限都不能终止或永久阻塞 hitch run。
- `sgzx_boss` 不可见时有界跳过，继续存档关闭、NPC/传家宝、退出和计数。
- 存档挑战点击拒绝必须有冷却和尝试预算。
- 所有开局可选步骤失败后仍要进入 hitch idle，继续观察 victory/failure 抢占。

### 6.4 黑商与宝物业务不变量

- 黑商：只允许 `devour_pill / 吞噬丹`；没有就刷新，预算耗尽后跳过。
- 宝物：只允许 `rarity == green && "神符" in OCR name`。
- 无绿色神符：刷新；刷新耗尽后关闭/跳过，禁止品质兜底。
- 该不变量必须在实际执行入口 `mediator` 处生效；`choice_policy` 可以作为第二道隔离，但不能代替入口门禁。
- 删除或反转 `test_hitch_mode_without_green_talisman_falls_back_to_quality`，新增「无绿色神符绝不 SELECT_SLOT」以及 `ocr_mode=off/shadow` 的防旁路测试。
- `lobby_hitch.hidden_defaults` 明确固定 `auto_secret_realm=false`；如产品未要求，不要让其他模式配置串入。

## 7. 合并与验证纪律

1. 每个修复提交对 parent 做删除行审查，报告 `NEW_FIX` 和 `UNINTENDED_REVERT=0`。
2. 不要直接改 Harness production 代码；先得到唯一 production candidate SHA。
3. Production 依次通过：

```powershell
python tools/release_gate.py
python -m pytest tests -q
python -m pytest tests/contract -q
python tools/run_frozen_replay.py --check
python tools/validate_scenes.py
```

4. 至少新增以下确定性回归：
   - hitch MAIN_LINE 持续不健康帧最终恢复到已验证 L0，不 stop；
   - hitch recovery 超预算不 stop、不误计局数；
   - 未知大厅 modal 有界关闭/回退，不永久等待；
   - 暂停恢复耗尽不 stop；
   - 两处 unverified archive 在 hitch 下不 stop；
   - `sgzx_boss` 不可见时能继续关闭存档面板；
   - 存档挑战点击拒绝有预算和冷却；
   - `ocr_mode=live/off/shadow` 下，hitch 都不会选择非绿色或名称不含神符的宝物；
   - 黑商永远不产生木头、折扣或其他购买动作；
   - 评论/社区/排行榜到房间列表的后置确认；
   - 满房子窗关闭后继续扫描下一行；
   - 胜利、失败各一局后 game_count 正确、跨局状态清空。

5. Production 最终 SHA 固定后，才更新 Harness identity，要求 `src/ + config/` diff clean，再跑 Harness 全量。
6. 只有具备真实签名材料时重建 EXE；不得伪造密钥、篡改 manifest 或手改 identity 变绿。
7. 最终实机 GT 至少覆盖：从评论页启动、一次满房弹窗、一次窗口最小化/恢复、开局完整步骤、一次胜利、一次失败、回大厅再进第二局。

## 8. 云端最终应回传的内容

- 最终 production candidate 完整 SHA 和远端分支。
- 按层列出的提交及 `UNINTENDED_REVERT=0` 证据。
- 所有新增/保留测试结果与完整 release gate 结果。
- `REMAINING_EARLY_EXIT_PATHS` 与 `REMAINING_HANG_PATHS` 的重新审查结果。
- Harness 是否已同步到最终 SHA、source identity 是否 CLEAN、EXE 是否真实重建并通过签名验证。
- 明确裁决 `SAFE_TO_GT: YES/NO`。如果仍有默认可达提前退出或无界挂起，必须是 `NO`。
