# 刷刷宝 Live Harness — Opus 审查交接

## 目的与边界

这是 `test/solo-live-harness-20260907` 的 Harness 审查材料，不是 production 功能交付。

- 冻结 production 基线：`b15da05f4fd7313b02b2cc466e319d9683aa979c`
- production 分支 `trial-merge`：审查时必须保持在上述 SHA；禁止 merge/rebase/push
- Harness 分支：`test/solo-live-harness-20260907`
- 允许改动：`tools/live_scenario_capture.py`、`live_scenario_launcher.ps1`、Harness tests、Harness docs
- 明确没有改动：`src/` production mediator/runtime/settings/choice policy、正式 EXE、正式用户设置、release approval
- Runtime 模式：`SOURCE_RUNTIME`；本轮不 build、不使用正式安装包制造结论

本材料中的“通过”只表示 Harness acceptance 语义和自身测试通过；不表示最近一次 Natural E2E 已通过。

## 用户报告的现场问题

1. 第一次点击 12 时 OCR 环境不存在：`ShuaBao OCR runtime missing; create .venv-ocr or set SHUABAO_OCR_PYTHON`，工具退出码 3。
2. 旧版临时设置窗口曾报 PowerShell `Point` 构造重载错误；当前脚本已改成显式 `[System.Drawing.Point]::new(x, y)`，并有 offscreen smoke test。
3. 早期脚本会把 KK/房间窗口置前，遮挡游戏选关；当前 12 从游戏内 Stage Select 接管，preflight 只确认目标窗口，后续 capture 不再激活 KK 房间窗口。
4. `5-5` 后到时间没有真实生效地点击“提前挑战”；日志中有 `ClickTQTZ`，但点击后业务面仍未改变。Harness 不把 click success 算成业务成功。
5. `auto_close_main_line=true` 时曾先 `DisableAutoTask`，之后 production 又多次 `EnableAutoTask`；这是 production runtime 行为，不是 Harness 修复。
6. 羁绊/技能/装备/宝物/进化等动作有 click 记录，但 click 不等于业务后置确认；随机黑商未启用时不能算失败。
7. 存档挑战面板缺少战利品挑战；生产 `_archive_hitch_card_unavailable` 对红色 `7/8` 的 OCR/颜色判断把它当成 unavailable，导致未点战利品挑战。
8. 结算后生产没有把 NPC Hub / 存档 / 传家宝 / 秘境 route 分类为可继续业务基线，因此旧 run 在 post-game transition timeout。
9. 外部 Chrome 窗口抢焦点/遮挡造成 `CANCELLED_WINDOW_CHANGED`、`CANCELLED_WINDOW_OBSCURED` 和后续 `CANCELLED_SENDINPUT_FAILED`；这应标为测试环境 `BLOCKED`，不能伪造 production FAIL。
10. 封神面板出现 `肉身成圣(0/3)`，但最近 run 的 OCR 多次把卡名识别成 `祝福`，未证明正确拿卡。

## Harness 已交付的行为

### 启动与身份

- GUI 真实入口：`live_scenario_launcher.ps1`；核心捕获器：`tools/live_scenario_capture.py`。
- 桌面快捷方式 `C:\Users\10639\Desktop\刷刷宝 Live 实机测试.lnk` 的 target/working directory 都指向该隔离 worktree。
- 点击 12 的入口使用真实 `RuntimeMediator.tick()`/`Mediator.tick()`，启动 ground truth 为游戏内 Stage Select；Harness 不实现创房、选关、MAIN_LINE、卡牌、Boss、结算 FSM。
- 12 默认只读 `C:\Users\10639\AppData\Local\ShuaBao\user_settings.json`，再复制到本次 Temp bundle；临时面板是覆盖，不写回正式看板。
- GUI 身份拆分为 Harness SHA、Production baseline SHA、Runtime source SHA、Runtime type=`SOURCE_RUNTIME`。

### Acceptance 收紧

- 房间、Stage、Hero/HUD、Victory、Return baseline、Next round 均要求后续 fresh frame 和 production classifier/business surface。
- `ROOM_CREATE_CONFIRMED` 不接受内部 phase + valid frame；`RETURN_BASE_CONFIRMED` 不接受仅 `LOBBY_ROOM`；`NEXT_ROUND_CONFIRMED` 必须在 request 后的新 frame 上由现有 Stage/Hero/HUD classifier 证明。
- 可选 route（提前挑战、战利品、传家宝、秘境）使用 request/confirmation ledger：没有真实 classifier 只记录 `NOT_OBSERVED` 或 `BLOCKED`，不新增固定坐标 detector。
- 外部窗口 ownership guard 的取消、遮挡和焦点变化进入 `BLOCKED`，并请求 production safe stop；不杀 KK/游戏进程，不自动 ESC/F1/切窗口纠错。
- Replay 仍是 event-driven capture；不复制 production FSM。

### 当前改动文件

相对冻结基线只应看到以下 4 个 Harness 文件（本交接文档本身是 Harness docs）：

- `tools/live_scenario_capture.py`
- `live_scenario_launcher.ps1`
- `tests/test_live_scenario_capture.py`
- `docs/live_scenario_capture.md`

## 最近一次真实 run（历史证据，不是最新 acceptance 版本）

完整 bundle：

`C:\Users\10639\AppData\Local\Temp\shuabao-captures\solo_ingame_chain_20260907_220109_971377`

- 运行时 Harness SHA：`b50a7203e76f0587c5c6c9b503a1619570249601`（早于当前 acceptance 收紧 commit）
- Runtime：`SOURCE_RUNTIME`
- `mode_id=normal_farm`
- config snapshot hash：`5e0dfea0ace1bebcb9f923f9206082253caf55ea0d4314f972800a182f793def`
- 813 ticks、623 screens、399 timeline events；`failures/`、`incidents/`、`cases/`、`trace/` 均保留
- 结果：`PENDING_OR_FAILED`；不是 Natural E2E PASS

重点证据索引：

- 提前挑战：timeline `e0348`，`f0525_action_before` / `f0526_action_after`；action `ClickTQTZ` 成功，但按钮/业务 surface 没有发生可确认变化。
- 自动任务：timeline `e0350` `DisableAutoTask`，随后 `e0360`、`e0372` 等又 `EnableAutoTask`。
- 存档/战利品：`f0599_action_after`、`f0618_action_before`；战利品挑战显示约 `7/8`，没有对应 `ArchiveChallenge-loot` action。
- 结算路由：`f0620_action_before`、`f0621_action_after`、`f0622_state_change`；生产未给出可继续 Hub classifier，最终 `post-game transition timeout`。
- 外部窗口：timeline `e0182`/`e0183`，分别为 `CANCELLED_WINDOW_CHANGED` / `CANCELLED_WINDOW_OBSCURED`；cover HWND `33490400`（Chrome_WidgetWin_0），target game HWND `25366644`。
- 羁绊/封神：`f0282_action_before`、`f0283_action_after` 等面板帧；截图中有 `肉身成圣(0/3)`，trace/OCR 却多次记录 `ocr_bond:祝福`。

## 生产侧只读结论

### 提前挑战和自动任务

生产 `_maybe_click_tqtz` 在 SendInput 成功后设置内部 clicked 状态，但没有要求 fresh business postcondition；因此最近 run 只能证明“发出了点击”，不能证明“提前挑战已生效”。`_tick_main_line` 仍会按自身逻辑重新确保 auto task，和 `auto_close_main_line` 的用户期望存在冲突。Harness 不改这些 production 行为，只把证据拆成 request/confirmation。

### 存档、传家宝、秘境

生产 route classifier 在这次截图上不能稳定区分 NPC Hub、存档、传家宝、秘境的可继续基线；Harness 不新增假 detector。因此它们在当前 run 只能是 `NOT_OBSERVED`/`BLOCKED`，不能因为 phase 看起来像对就 PASS。

### 封神“肉身成圣”

结论：**没有解决，也没有被 Harness 验证为已解决。**

证据链：

- `config/game_mechanics_kb.json` 记录的攻略链是：姜子牙启动；6 张封神卡成封神榜；`肉身成圣` 为 3 张一组、可直接吞以加速封神榜；该细节仍标为 guide/未上帧。
- `config/choice_lexicon.json` 有 `肉身成圣`，`set_membership=封神`，但 `config/fetter_labels.json` 没有该卡的短码映射。
- `config/choice_policy.json` 的 `advanced_names` 和封神 `advanced_groups` 只有 `封神、封神榜、打神鞭、杏黄旗、斩仙飞刀`，没有 `肉身成圣`。
- `official_strategy_defaults.json` 的封神默认卡组也没有 `肉身成圣`。
- 最近 run 的 dashboard `cards` 快照同样没有 `肉身成圣`；实机截图虽看到了它，但 OCR 将多个该卡面误判为 `祝福`。

因此即便 Harness 继续正确调用 production policy，也无法声称这条卡的选取已修好。Production 后续应由业务 owner 决定：先补充可复核的实机 OCR/template evidence，再把它加入封神组的显式策略、进度/吞噬语义和回归测试；不能仅为让 Harness 通过而盲加默认点击。

## KB/拿卡策略审查意见

当前策略已有可复用基础：硬白名单、基础羁绊 80% gate、同名/已持有合成优先、`set_progress` 缺字段时 fail-closed、技能前置/存档解锁排序、宝物负面卡拦截。KB 也明确区分了 live verified、guide-only、未上帧内容。

可优化但应在 production 变更单独完成的方向：

1. 把 KB 的 `status/evidence` 作为策略输入元数据，而不是把 guide-only 卡直接等同 live-confirmed 卡。
2. 封神组拆成“启动钥匙 / 神将素材 / 肉身成圣 3 张加速组 / 法宝跳阶 / 打神鞭硬门槛”，每一步需要真实 owned/progress evidence；未知进度继续不猜。
3. 增加 OCR confusion regression：真实 `肉身成圣`、`祝福`、`封神榜` 同屏时必须保持 card identity，不得仅凭家族名或最高品质降级选择。
4. 让 `owned_bond_cards`、`set_progress` 和卡面 exact name 的来源可审计；没有稳定来源时记录 `NOT_OBSERVED`，不要把错误 OCR 当作已拥有。
5. 用本 bundle 的 action-before/action-after 对每次卡牌点击做业务确认；不能因为选择函数返回 SELECT 就算拿卡成功。

这些是审查建议，不是本 Harness 分支已经做的 production 修复。

## Harness 自测结果

本分支已验证：

- `python -m pytest tests/test_live_scenario_capture.py -q` → `101 passed`
- `python -m py_compile tools/live_scenario_capture.py` → PASS
- `powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Sta -File .\live_scenario_launcher.ps1 -SettingsPanelSmokeTest` → PASS
- `git diff --check` → PASS
- 无 Harness 直接 `pyautogui.click` / `SendInput` / `keyboard.press` 业务调用；输入仍由 production InputExecutor/Mediator authority 发出
- 当前 branch 与 `origin/test/solo-live-harness-20260907` 已同步；`origin/trial-merge` 仍为冻结 baseline

## 请 Opus 最终回答

1. 相对 `b15da05...` 是否有任何 production 文件变更？
2. 12 是否仍把 click success、phase-only 或 stale frame 当 business PASS？
3. route ledger 是否明确区分 request / confirmation / `NOT_OBSERVED` / `BLOCKED`？
4. external window guard 是否 fail-closed 且 safe-stop？
5. `肉身成圣` 是否在当前 production policy 真正有可选路径？如果没有，请把“未解决”保持为结论。
6. 最近 run 的提前挑战、自动任务、战利品、Hub/秘境/传家宝和 OCR 证据是否支持可复现的 production issue？
7. 是否有任何 Harness 代码复制了 production FSM 或使用固定坐标模拟业务？

审查时请把 Harness acceptance PASS 与 Natural E2E PASS 分开报告。
