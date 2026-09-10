# 刷刷宝 Live Debug 外部 Agent 接手说明（2026-09-10）

> 本文只记录当前事实和可复现证据。**候选代码尚未完成新一轮两局真机验收；不要把单测或 click 日志写成实机 PASS。**

## 1. 给接手 Agent 的任务

用户要完成并实机验证以下行为：

1. 蹭车模式的公共背包：个人物品栏 UI 的 1 号格是固定自有物品，绝不能移动；只允许 2--6 号非空格作为源，其他已识别背包物品/装备也应能转入公共背包。单人模式绝不操作公共背包。
2. 蹭车局内需持续拾取溢出物：优先 HUD 的 Z 拾取按钮，缺失时按 `Z`；不能遗漏地面道具。
3. 战后顺序：`ContinueGame → 存档挑战 1~8 → 时光之穴 Boss → 传家宝 Boss`。配置 Boss 时优先配置；未配置时仅在已分类的 Boss 列表中滚到底，点击最后一个模板可识别的卡。
4. G（存档挑战）和 H（传家宝/Boss）单项测试都应能从战后挑战广场自动找到对应 NPC，不要求用户先手动打开面板。
5. 蹭车“中场接手”必须识别已进行的局，不能因为开局压力转移按钮已经不存在就永久零输入。用户提供的顶部 `存档挑战 / 2-7` 进度条是这类状态的真实视觉证据。
6. 完整蹭车链路（菜单 13）要按正式 `hitch_cycle_num=2` 跑两局；重点真机观察每局退出后在 KK 房间内是继续准备、离房还是重新搜房，以及该选择是否符合既有 production 状态机。

## 2. 权威工作区、版本与桌面入口

| 项目 | 路径 / 值 |
|---|---|
| 当前 production worktree | `G:\刷刷宝\Worktrees\live-g0-publicbag-v2` |
| 当前 production 分支 | `test/live-g0-publicbag-treasure-20260910-v2` |
| 功能行为基线 | `8d57a2a1e0872f9ff799751ec82102bd7cfc3715`（本次生产代码改动；当前 HEAD 仅额外包含本文档） |
| Live Harness worktree | `G:\刷刷宝\Worktrees\live-harness-current-20260908` |
| Harness HEAD | `57dbc0edd04d4403db46c2c952ddbe668fdda691` |
| 桌面入口 | `C:\Users\10639\Desktop\刷刷宝 Live 实机测试.lnk` |
| 快捷方式当前注入 | `-ProductionSourceRoot "G:\刷刷宝\Worktrees\live-g0-publicbag-v2" -ProductionSourceSha "<该 worktree 的当前 HEAD>"`；已与当前 HEAD 同步，勿从历史记录复制旧 SHA |
| 真实抓包根目录 | `C:\Users\10639\AppData\Local\Temp\shuabao-captures` |
| 当前正式设置 | `%LOCALAPPDATA%\ShuaBao\user_settings.json`，最近 manifest 显示 `hitch_cycle_num=2`、`cycle_num=3`、`cjb_boss=18乌索克`、`sgzx_boss=53拉贾克斯将军` |

Harness 的 source injection 已验证：`ready_for_gt=true`、`match=READY`、`production_code_diff=CLEAN`。当前运行的是源码运行时，不依赖 worktree 下不存在的 `dist\ShuaBao\ShuaBao.exe`；launcher 的旧“未找到 EXE”文字已经改为说明源码运行时。

## 3. 最近历史改动（按提交阅读）

| 提交 | 结论 / 入口 |
|---|---|
| `8d57a2a` | 本轮：中场蹭车接手、G/H 探针广场入口、未配置 Boss 的战后 fallback、hitch 两局计数投影。重点读 `src/shuabao/mediator.py`、`tools/live_scenario_capture.py` 和同提交测试。 |
| `2d3424e` | 公共背包永远跳过 UI 1 号固定格；其他 2--6 号物品栏格仍可作为源；补空配置 Boss 的“最后可识别卡”fallback。 |
| `85b25d6` | 公共背包允许在已分类 `NPC_HUB` 战后广场执行；仍由双锚点背包布局授权真实点击。 |
| `161a81e` | 旧候选重钉/Live identity 历史点。 |
| `13b92a0`（Harness 历史） | Harness 接受 NPC_HUB 作为公共背包开始 surface。 |
| `bb2f4c0`（Harness 历史） | Harness/production 允许从挑战广场打开战后挑战面板的前置工作。 |

更早的公共背包设计、几何、资产来源及“不可以声称多人 PASS”的边界，见：

- `docs/CURRENT_STATUS_AND_HANDOFF_20260910_PUBLIC_BAG.md`
- `docs/gt_lab/PUBLIC_BAG_GT_SPEC_20260909.md`
- `docs/P1B0_POST_GAME_STATE_MODEL.md`
- `docs/agent_shared_logs/CLAUDE_HITCH_LONGRUN_AUDIT_HANDOFF_20260909.md`

这些是历史背景，不应覆盖本文所列的当前 worktree/SHA。

## 4. 当前实现与本轮已修复根因

### 4.1 公共背包 / Z 拾取

- 入口：`src/shuabao/mediator.py::_maybe_public_backpack_deposit`。
- 蹭车循环：`_HITCH_L1_CYCLE_ORDER = ("merchant", "treasure", "pickup", "public_bag")`。
- `pickup` 步会优先点 `bag/hud_pickup_button`，缺失时 `act_key("z", "Pickup-Z")`；蹭车随后推进到公共背包，不会消耗吞噬丹或英雄卡。
- `2d3424e` 后，源物品栏循环从 internal slot 1 开始，因此 UI 1 号格不会右键；UI 2--6 号非空格会进入候选。公共背包布局和双锚点安全门没有放宽。
- 尚未以多人蹭车局完成“公共格从空变非空”的真机业务后置确认。不要删除这一限制或宣称通过。

### 4.2 G/H 为什么此前要手动开 NPC，H 为什么有日志却无画面动作

旧 G probe 直接调用 `_maybe_click_archive_challenge`，只会消费已打开的卡位，无法从广场走 NPC 入口；现在 G 改为调用 `_tick_main_line(frame)`，其 production `NPC_HUB` 分支会发 `OpenArchiveChallenges`。

H 的实机 bundle 明确证明旧路由错误：

- `C:\Users\10639\AppData\Local\Temp\shuabao-captures\heirloom_20260910_152512_860879\manifest.json`
- `probe_bootstrap.post_game_route` 当时固定写成 `heirloom`；但起始页面已是 `HEIRLOOM_DIALOG`。
- production 因路由不是 `heirloom_active` 落入 `DismissHeirloomDialog`。
- H 的窄 probe allowlist 不包含这个 reason，`input_status=CANCELLED_PROBE_GUARD`；所以控制台有 click 日志，但 SendInput 没有下发，屏幕当然无反应。

当前修复：`_bootstrap_target_probe(..., frame)` 在 live preflight 后调用 production `_post_game_state(frame)`；若 H 起始页是 `HEIRLOOM_DIALOG`，设置 `heirloom_active`，否则在广场设置 `heirloom`。H allowlist 添加 `OpenHeirloomChallenges`；G 添加 `OpenArchiveChallenges`。不允许通用 `DismissHeirloomDialog` 通过 probe 护栏。

### 4.3 无预设 Boss fallback

`_maybe_challenge_configured_boss` 原先已有“已分类列表 + 无配置 → 滚到底 → 最后可识别卡”的局部能力，但两个上游门禁阻止它被走到：

- ARCHIVE_PANEL 在 `sgzx_boss` 空时跳过整个时光之穴分支；
- HEIRLOOM_DIALOG 在 `cjb_boss` 空时跳过 Boss handler、转而关闭弹窗。

`8d57a2a` 删除这两个配置门禁。存档关闭后总是路由到 `heirloom`。仍然只有 `_post_game_state` 已确认是 `ARCHIVE_PANEL` 或 `HEIRLOOM_DIALOG` 时，才允许滚动和选择；未识别画面保持零输入。

### 4.4 中场接手卡死

实机 `hitch_runtime_20260910_152721_121316` 的首帧已有：

- `context=MAIN_LINE`；
- 顶部 `cundangInfo` template score `0.974`；
- 用户截图显示 `存档挑战 / 111 秒 / 2-7`；
- 没有业务 input。

原因是 `_maybe_click_hitch_pressure_transfer` 要求本进程亲自点击 `yalizhuanyi` 并观察其消失；进程在已经进行的 `2-7` 局里接手时该按钮不存在，于是它永久返回 `Continue`，后续自动任务、四挑战、宝物、拾取、公共背包都没有输入权。

现在 `_adopt_hitch_midgame_takeover(frame)` 仅在同时满足以下条件时将 `_hitch_pressure_transferred=True`：

1. production `_is_in_game_hud(frame)` 为真；
2. `_post_game_state(frame) is None`；
3. 压力转移按钮 `yalizhuanyi` 不可见；
4. 顶部 ROI 内 `cundangInfo` ≥ 0.85。

单独“按钮不存在”绝不授权；正常开局仍保留“点击后按钮消失”的原始后置确认。

### 4.5 两局计数

桌面 runner 正常会把 `hitch_cycle_num` 投影到 generic `cycle_num`，但 live harness 直接构造 `Mediator`，此前漏了这一步。`_prepare_settings` 现为 `lobby_hitch/lobby_search/hitch_runtime/hitch_lobby_chain` 明确执行：

```python
settings.cycle_num = int(settings.hitch_cycle_num or 0)
```

当前正式设置里 `hitch_cycle_num=2`，故菜单 13 的预期为两局后 `COMPLETE`。

## 5. 真机证据索引与应如何解读

| Bundle / 文件 | 已证明事实 | 未证明事实 |
|---|---|---|
| `heirloom_20260910_152512_860879` | H 曾错误走 Dismiss reason，且被 `CANCELLED_PROBE_GUARD` 拦截。frames 有 `f0000_action_before.png` 等。 | 新修复的 `OpenHeirloomChallenges → Boss → HUD` 未实机复验。 |
| `archive_challenge_20260910_150732_292239` | G 在用户已手工打开面板后真实发送过多个 `ArchiveChallenge-*` 点击。 | 从 NPC_HUB 自动打开存档 NPC 还未真机复验。 |
| `hitch_runtime_20260910_152721_121316` | 旧中场接手卡在 MAIN_LINE/pressure gate；顶部 `cundangInfo=0.974`。之后用户点 HUD stop，后续 trace 的 `stop:User clicked HUD stop` 不是 production 成功或失败。 | 新 `cundangInfo` takeover 分支尚未真机复验。 |
| `public_backpack_deposit_20260910_150226_818161` | 公共背包窄 probe 的真实起始截图/布局证据。 | 多人实际转存业务后置未确认。 |
| `hitch_lobby_chain_20260910_152947_269297` | 旧完整链试图启动的目录。 | 没有可用 final manifest，不可作为 PASS 或 FAIL 的证据。 |
| 用户截图 | `C:\Users\10639\AppData\Local\Temp\codex-clipboard-3a66a46e-289f-4723-b629-1f9730647eba.png`（中场顶部状态）；`...b992a868...png`（G/H 菜单）。 | 不是可回放输入证据。 |

## 6. 已运行的离线验证

`8d57a2a` 后已明确得到以下结果：

```text
python -m pytest tests/test_live_scenario_capture.py -q
# 89 passed

python -m pytest tests/test_p1b0_post_game.py -q
# 77 passed, 8 subtests passed

python -m pytest tests/test_s0_l1_hitch_bounds.py tests/test_public_bag_transfer.py -q
# 64 passed
```

新增/更新覆盖包括：H 已打开页面 bootstrap、G/H allowlist、hitch cycle 数投影、无 cjb 配置不再直接关传家宝、无 `cundangInfo` 时仍保持 pressure gate、UI 1 号物品栏格排除。

曾启动 `python tools/release_gate.py`，但调用环境在 pytest 长运行时截断了父进程输出，未采集完整最终 summary；**不要声称本 SHA 的 full release gate 已通过**。如需 release 结论，请在本机前台重跑并保留完整输出。

## 7. 当前真机阻塞与下一步复现

最后一次只读检查时：游戏窗口不存在，`KK官方对战平台` 窗口处于最小化状态（`IsIconic=True`、rect `-32000,-32000,-31840,-31972`）。因此没有启动菜单 13：preflight 会安全 BLOCKED，强行运行无法验证退出后的房间分支。

用户将 KK 恢复并置于房间列表后，按以下顺序操作：

1. 确认普通刷刷宝未同时运行；KK 前台可见且不是最小化；正式设置中 `hitch_cycle_num=2`。
2. 从桌面快捷方式启动，点击菜单 `13 PRIMARY HITCH_FULL_NATURAL_E2E`。
3. 不手动点击房间、准备、压力转移、挑战、战后 NPC、卡或 Boss；需要人工介入时使用 harness bookmark `MANUAL_INTERVENTION`，不要将该 run 标 PASS。
4. 每局退出游戏后，收集 `hitch_lobby_chain_*\manifest.json` 的 `events`、`fsm_state`、`hitch_status`、`hitch_re_search`、`game_count`、`last_outcome`，以及 KK 房间页前后帧。重点确认：
   - 已验证离局是否只计一次 `game_count`；
   - 仍在旧房时 production 是否按现有 `_tick_lobby_hitch` 走准备/离房/重搜，而不是盲点；
   - 第 2 局完成后是否只在 `game_count==2` 时进入 `COMPLETE`。
5. 如需单项复验：G/H 从挑战广场开始，分别点击单项 `G`/`H`，全程不要手工点 NPC。检查 action reason 必须分别是 `OpenArchiveChallenges`/`OpenHeirloomChallenges` 或随后的 Boss/card action；`DismissHeirloomDialog + CANCELLED_PROBE_GUARD` 表示旧问题复现或路由回归。

等价 CLI（desktop launcher 会自动提供同样的 source injection）：

```powershell
$env:SHUABAO_PRODUCTION_SOURCE_ROOT = 'G:\刷刷宝\Worktrees\live-g0-publicbag-v2'
$env:SHUABAO_PRODUCTION_SOURCE_SHA = (git -C $env:SHUABAO_PRODUCTION_SOURCE_ROOT rev-parse HEAD).Trim()
Set-Location 'G:\刷刷宝\Worktrees\live-harness-current-20260908'
python tools\live_scenario_capture.py capture --target hitch_lobby_chain `
  --out "$env:TEMP\shuabao-captures" --repo-root (Get-Location) `
  --duration 3600 --max-ticks 30000 --interval 0.15 --continue-after-failure --generate `
  --live-input --confirm-live-input --allow-dev-source `
  --production-source-root $env:SHUABAO_PRODUCTION_SOURCE_ROOT `
  --production-source-sha $env:SHUABAO_PRODUCTION_SOURCE_SHA
```

## 8. 调试入口与建议阅读顺序

1. `tools/live_scenario_capture.py`
   - `_prepare_settings`：hitch cycle 投影；
   - `_start_surface_preflight`：G 接受 `NPC_HUB` 或 `ARCHIVE_PANEL`；
   - `_bootstrap_target_probe`：按 preflight frame 给 H 设正确 route；
   - `_invoke_target_handler`：G 必须经 `_tick_main_line`；
   - `_probe_allowed_reasons`：窄 probe 输入护栏。
2. `src/shuabao/mediator.py`
   - `_maybe_click_hitch_pressure_transfer` / `_adopt_hitch_midgame_takeover`；
   - `_post_game_state`、`_post_game_hub_entry_click`；
   - `_maybe_challenge_configured_boss`；
   - `_tick_main_line` 的 `ARCHIVE_PANEL`、`NPC_HUB`、`HEIRLOOM_DIALOG` 分支；
   - `_HITCH_L1_CYCLE_ORDER`、`pickup`、`public_bag`。
3. 相关测试：`tests/test_live_scenario_capture.py`、`tests/test_p1b0_post_game.py`、`tests/test_s0_l1_hitch_bounds.py`、`tests/test_public_bag_transfer.py`。

## 9. 接手注意事项

- 不要 `git reset --hard`、不要覆盖其他 worktree，也不要修改 `docs/baselines/GATE_BASELINE.json` 让 gate 变绿。
- Windows 前台、UIPI、最小化和 capture 无效时必须零输入；这些是正确阻塞，不是需要坐标兜底的 bug。
- 不要让 harness 为方便测试复制 NPC/Boss/房间选择策略；应调用 production `Mediator` 入口，并仅做证据/allowlist/身份门禁。
- 外部 agent 可先只读审查；若修改 production，需要增加最小回归、提交 production 后更新快捷方式中的 SHA，并重新确认 identity 为 `READY`。
- 交付报告请清楚分为：离线通过、真实输入已发出、真实业务后置确认、完整两局 Natural E2E；四者不能混用。
