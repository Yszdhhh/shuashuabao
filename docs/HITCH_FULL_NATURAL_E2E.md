# HITCH_FULL_NATURAL_E2E

这是 Tier-0 Lobby 的主 Live 流程。Harness 只负责启动、采集、记录和
判断 production postcondition；Lobby/L1 决策仍全部来自注入的
`Mediator.tick()`，不在 Harness 中复制 FSM 或业务逻辑。

## 固定运行身份

- Harness branch：`test/live-scenarios-tier0-lobby-20260909`
- Production Test Candidate：通过 `--production-source-sha` 显式指定（禁止静默硬编码默认值）
- Candidate worktree：`G:\刷刷宝\Worktrees\lobby-hitch-surface-test`
- Harness worktree：`G:\刷刷宝\Worktrees\live-harness-current-20260908`
- 运行时通过 `--production-source-root` / `--production-source-sha` 注入
  candidate 的 `src/shuabao`。bundle 会同时保存 Harness 和 production
  source identity；source identity 未指定或不匹配时零输入阻塞。

运行前先做身份检查：

```powershell
$candidateSha = (git -C "G:\刷刷宝\Worktrees\lobby-hitch-surface-test" rev-parse HEAD).Trim()
python tools/live_scenario_capture.py identity `
  --repo-root . `
  --production-source-root "G:\刷刷宝\Worktrees\lobby-hitch-surface-test" `
  --production-source-sha $candidateSha `
  --json
```

证据输出应放在 worktree 之外，例如
`C:\Users\10639\AppData\Local\Temp\shuabao-tier0-lobby-20260909`，不要
写入 candidate 的 `live-captures/` 或提交其它运行时产物。

## 主链

入口 target 是 `hitch_lobby_chain`，其显示名称是
`HITCH_FULL_NATURAL_E2E`。启动时把真实 KK 停在 `ROOM_LIST`，随后让
production 自然运行：

```text
ROOM_LIST
  → search confirmed → join → neutral modal dismiss/reclassify
  → ROOM fresh-confirm → Ready → CancelReady fresh-confirm
  → GAME/HUD → Pressure fresh-confirm → normal round
  → Black Merchant / Hitch Treasure / Public Backpack
  → Victory or Failure → real exit
  → PLATFORM/ROOM_LIST fresh-confirm → next round
```

主链至少需要 3 个完整 round，至少 3 次真实回厅，并且覆盖一次 blocking
modal recovery、一次 Pressure fresh-confirm 以及一次 Victory 或 Failure。
点击 API success、单次 frame mutation、`pending_join` 或 phase 变化都不能
单独形成 PASS。

主 ledger 会记录：

```text
rounds_started, rooms_joined, ready_confirmed, pressure_confirmed,
pressure_core_failure, modals_dismissed, merchant_devour_acquired,
talisman_acquired, public_bag_deposit_attempts,
public_bag_deposit_confirmed, public_bag_deposit_failed, victory_count,
failure_count, lobby_returns, longest_stall_s, silent_stop_count,
manual_intervention_count
```

`S01`–`S06` 仍可作为整链失败后的窄复现入口，但不再是主流程，也不能用
六个窄入口的结果替代 `HITCH_FULL_NATURAL_E2E`。

## Public Backpack GT protocol

在 `lobby_hitch` 下，吞噬丹和 OCR 名称命中“神符”的绿色神符都属于保留给
公共背包的资源；未取得真实 GT 前，candidate 不得把它们交给个人使用逻辑
或猜测转移动作。

第一次真实目标物品出现时，唯一允许的自动步骤是由 production 完成：

```text
GAME/HUD fresh-confirm
  → target item slot fresh-confirm
  → right-click target slot
  → press B
  → fresh-confirm 公共背包 / 个人背包 surface
  → 暂停 deposit 输入
```

此时保存截图、HWND、frame dimensions、item bbox、公共/个人背包 bbox 和
trace；用户人工完成一次目标物品到公共背包的转移。该次记录必须标记为
`GT_CAPTURE / MANUAL_INTERVENTION`，不能算 `HITCH_FULL_NATURAL_E2E`
PASS。

窄 target `public_backpack_deposit` 只调用 production operation 并读取
postcondition，不实现右键、`B`、拖拽或背包 FSM。当前 frozen candidate 没有
`_maybe_public_backpack_deposit` entrypoint，因此状态是
`BLOCKED_UNTIL_GT`；没有真实证据前不添加 production operation。

后续 operation 的有效 PASS 至少要 fresh-confirm：公共背包可见、目标原槽位
有可信变化、目标已出现在公共背包或存在等价明确的 transfer postcondition。
UNKNOWN 只允许零输入和有界 reobserve；deposit 失败记录
`PUBLIC_BAG_DEPOSIT_FAILURE`，不得让整条 hitch 长线程直接 stop。Victory /
Failure / active transaction 始终抢占 deposit。

## 失败与状态

每个失败 bundle 至少保留 candidate SHA、Harness SHA、frame、trace、HWND、
surface classification、input、postcondition 和 failure reason，并分类为
`HARNESS_BUG`、`PRODUCTION_BUG`、`ENVIRONMENT` 或 `BLOCKED`。如果出现
production bug，停止该 Scenario，保留 bundle，不能在 Harness 中塞补偿逻辑。

没有可用 KK 窗口时，期望结果是：

```text
SCENARIO_FRAMEWORK_READY = YES
LIVE_GT = BLOCKED_NO_KK_WINDOW
```

这不是 Live PASS，也不允许把离线 replay 或 Harness readiness 提升为
Production PASS。
