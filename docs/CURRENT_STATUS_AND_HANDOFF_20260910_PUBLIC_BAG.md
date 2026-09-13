# ShuaBao Handoff — 公共背包流转 / 战后 NPC_HUB / 输入后置确认（2026-09-10）

本文覆盖 `TASK_PROMPT_OPUS5.md` 的四项要求。**没有任何一条实机 PASS 被声称**：
本轮全部是离线单测 + 真实素材上的检测复现。

## 当前 Git 状态

- 工作根：`G:\刷刷宝\GameScript-Local`（已用 `git rev-parse --show-toplevel` 确认）
- 分支：`test/gt-lab-public-bag-merchant-refresh-20260909`
- 起始 HEAD：`fddb172`（工作树带上一个 agent 未提交的 `_post_game_state` 改动 + 单测）
- 本轮提交（按层拆分，遵守 AGENTS.md 规矩 2）：

| commit | 层 | 内容 |
|---|---|---|
| `24ac53a` | 感知/资产 | `assets/Images/bag/{public_bag_title,bag_sell_equipment}.png` + 重生成 `config/runtime_asset_manifest.json` |
| `fa8c75f` | 战后 | `_post_game_hub_label_pair` + `_post_game_state` 判定（含上一个 agent 的改动） |
| `0617466` | 输入 + trace | 已注入/未注入区分、`post_confirm` 落地、选择面板不再重复点 |
| `d1025ac` | L1 局内 | `policy/public_bag.py` + mediator PUBLIC_BACKPACK_DEPOSIT 链路 |
| `6a155a8` | harness | 重钉 `live_harness_identity` 到 `d1025ac` |

### 并发提交提醒

本轮进行中，**另一个会话**在同一分支上提交了
`f868d2d feat(runtime): add reliability foundations and architecture audit reports`
（2026-09-10 00:49，新增 `src/shuabao/reliability_foundation.py` + 17 条单测）。
它是自包含新增（"Zero existing files modified"），没有和本轮改动冲突，
但因为动了 `src/shuabao/`，`live_harness_identity` 的 frozen baseline 又变成 NOT_CLEAN。
本轮**没有回滚也没有 amend 别人的提交**，只是在其之上再钉一次（见文末提交表）。
同分支并发提交时，最后一次重钉定义 candidate —— 下一个 agent 提交生产代码后同样要重钉。

## 一、战后挑战广场判定（复核结论）

上一个 agent 的方向是对的，但门禁开得太松，本轮收紧。

**为什么原来判不出来**：实机帧
`_formal_g0_live_evidence_20260909/hitch_lobby_chain_20260909_215849_052314/frames/f0133_action_after.png`
里根本没有大秘境 NPC。`damijing` 最高只有 **0.597**，而且命中位置在 `x=663`
（"存档挑战" 那四个字上），不是右侧 NPC 位。所以 `rift_npc_right` 恒为 False，
页面被判 UNKNOWN → 零输入等待 → `OpenHeirloomChallenges` 永远触发不了。

**上一版改法的风险**：`_find_post_game_hub_entry` 的阈值只有 **0.58**，而
`quit`（退出游戏）在**战斗中也一直可见**（见 f0133 与 GT 帧 t12_0）。
只要求"两个标签都命中"，等于让两个低置信噪声命中就能把战斗帧提升成 NPC_HUB。

**本轮收紧**：新增 `_post_game_hub_label_pair`，要求两个标签具备广场页的几何：

- 同一基线：`|Δy| ≤ 2% 帧高`
- 存档挑战在传家宝挑战**左边**
- 两者**几乎相邻**：水平间隙在 `[-1%, +10%] 帧宽` 内

f0133 实测：archive `(665,146,92,24)`、heirloom `(769,146,116,27)` — 同行、相距 12px。
严格路径（`rift_npc_right and hero_hit`）和 `ARCHIVE_PANEL` 关闭按钮互斥都没动。

回归：`tests/test_p1b0_post_game.py` 新增 4 条（f0133 精确坐标正例 + 错行/过远/左右颠倒三条反例）。

## 二、公共背包流转（PUBLIC_BACKPACK_DEPOSIT）

live harness 从 20260909 起就在调 `_maybe_public_backpack_deposit` /
`_public_backpack_deposit_postcondition`，而 candidate 里一直没有这两个入口
（manual_gt bundle: `production_readiness = BLOCKED_UNTIL_GT`）。本轮补上。

### 几何（`src/shuabao/policy/public_bag.py`）

全部量自 `_public_bag_gt_20260909/keyframes/t12_0.png`。KK 客户端矩形
`1600x900 @ (160,102)` 不是猜的 —— 同一次 run 的日志每 tick 都打
`capture tick 1600x900 @(160,102)`。

| 量 | 值 |
|---|---|
| 面板原点 / 尺寸 | `(670, 82)` / `677 x 491` |
| 个人背包网格原点（面板相对） | `(3.75, 40)` |
| 公共背包网格原点（面板相对） | `(343, 40)` |
| 网格 | 7 列 x 8 行，步距 `46.75 x 43.5` |
| 物品栏（源物品格） | 面板相对 `(20, 433)`，6 格，步距 `51.6`，格 `40x41` |

坐标**不是**硬编码屏幕坐标（GT spec §5 明令禁止）：面板原点由锚点在运行时给出，
所有格位 = `panel_origin + margin + [col*step_x, row*step_y]`，再乘帧自身的 16:9 scale。
验证：模型算出的公共格 `(3,0)` 正是操作者实际存进去的那一格。

### 页面确认（spec 步骤 4/5）

`_bag_layout` 要求 `bag/public_bag_title` 与 `bag/bag_sell_equipment` **同时命中**，
且两者对同一个面板原点吻合（±8px * scale），否则返回 `None` → 整条链零输入。
实测：GT 全部背包帧 ≥0.995；t00/t09/t11（未开背包）、实机广场帧 f0133、
以及 t52_8（录屏软件窗口盖住面板）全部不命中。

### 空格判定（spec 步骤 6）

`_bag_slot_empty` 同时要求"平"和"不饱和"：

| 状态 | 灰度 std | 饱和像素 |
|---|---|---|
| 空格 | 3.2 – 7.7 | 0 |
| 存进去的吞噬丹 | 63 | 313 |
| 仅鼠标指针遮挡 | 24 – 76 | ≤118 |

阈值 `std < 12 且 饱和 < 200*scale²`。**被指针遮挡的格子判为"未知"而不是"空"**，
不会隔着指针点进未知格。

### 状态机

`PublicBagFSM` 是纯 frozen dataclass（与 `merchant_fsm` / `equipment_fsm` 同风格）：

```
IDLE --按B--> BAG_OPEN_REQUESTED --页面确认--> BAG_VISIBLE
     --右键源物品--> SOURCE_SELECTED --左键已验证空格--> DEPOSIT_REQUESTED
     --后置确认--> CLOSE_REQUESTED --> IDLE
任一环节证据缺失/超时 --> ABORTED（带冷却，不重试同一格）
```

**铁律落到结构上**：只有 `SOURCE_SELECTED` 一个相位授权左键，
且左键目标只能由 `BagLayout.public_slot_rect` 产出；
`_public_bag_left_click_allowed` 再做一次"不在个人背包/物品栏内 + 在公共网格内"的双向检查。
个人格与物品栏在构造上就只有右键路径。

### 两处对 spec 的**有意偏离**（已写进模块 docstring）

1. **步骤顺序**。spec 把 `[2] 右键源物品` 排在 `[3] 按 B` 前面；20260909 的手势录像
   顺序相反：t11.5 先开背包页，t13.5 在面板的 **物品栏** 右键源物品，t14 携带物品落到公共网格。
   本实现按录像走，原因是常驻的右下角 HUD 栏标着 **「右击十连」** —— 在那里右键是
   "连用十次"的使用手势，把队伍的吞噬丹用掉正是输入安全铁律要防的损失。
   spec 的步骤 3 本来就是条件式的（"if the public bag view is not visible"），
   所有步骤仍然都执行了。
2. **源物品范围**。本轮只认吞噬丹（`danGif`/`swallow_pill`）。
   绿色神符的判据需要物品名，40x41 的图标上没有文字，读名字要悬停出 tooltip ——
   那是一次输入，在没有真实多人 GT 之前不打算花。未识别的物品一律不碰。
   **这是 TASK_PROMPT 里"装备/神符/英雄卡"未覆盖的部分，需要多人实机素材后补。**

### 吞噬丹与背包页

`_bag_page_swallow_pill`：丹在背包里而不在 HUD 栏时，只要背包页被双锚点确认，
就能在物品栏找到它。这条路径在 `lobby_hitch` 下**关闭**（那里丹是要存进公共背包的队伍资产），
在公共背包流转持有物品期间也整体关闭 `_maybe_use_inventory_item`。

## 三、宝物（神符）后置确认

TASK_PROMPT 说"第 1 个神符点选成功但 `post_confirm=null`，导致后续神符保守拒绝"。
查 trace 后是**两个独立问题**：

1. **`post_confirm=null` 不是失败**：`_trace_post_confirm()` 原本在恢复链之外恒返回
   `None`（它自己的 docstring 写着"B3/B4 的 OCR/选择后置确认在此阶段尚未实现"）。
   现在选择面板 `WAIT_MUTATION` 落定会写 `True`（mutation/面板消失）或 `False`（确认窗超时），
   公共背包存入落定也写。

2. **暴怒神符 `ok=false` 的真正原因**：tick 464 日志里有
   `[input] click (723, 480) dry_run=False` 且没有 CANCELLED 行 ——
   **点击其实注入成功了**。失败来自 `_post_check`：注入后前台窗口被抢走
   （tick 460-468 全是 `context=UNKNOWN` / `capture_wait`）。
   而 `_post_check` 返回的状态和"注入前就被拒"完全相同，于是面板 FSM 认为"没点到"，
   指纹不变继续重点，直到 `panel_action_limit_per_fingerprint` 把宝物面板强制 CLOSING。

   修法：`_post_check` 改返回 `CANCELLED_WINDOW_CHANGED_AFTER_INPUT`（注入前的路径保持原状态，
   `test_p0_security` 钉着）；`_finish_input` 对该状态推进 `_input_seq` 并标记本 tick 已有输入
   （每 tick ≤1 输入的门禁照旧成立，同 tick 不会补第二次）；选择路径把它当作"已发出"，
   进 `WAIT_MUTATION` 走后置确认而不是重点同一张卡；harness 把该状态记为 window guard（BLOCKED/环境），
   不算 production FAIL。

回归：`tests/test_dispatched_unverified_input.py`（10 条）。

## 四、测试与门禁

```
python -m pytest tests -q     →  1804 passed, 1 skipped, 2 xfailed, 248 subtests
python tools/release_gate.py  →  pytest PASS / frozen_replay PASS / contract PASS
                                 scene_templates: 资产 387→389（本轮两张锚点模板，已 --update-baseline --reason）
```

新增/改动的测试：

- `tests/test_public_bag_transfer.py`（40 条）：几何对 GT 实测值、FSM 全部相位与超时、
  左键铁律、指针遮挡不判空、postcondition、hitch_idle 接线。
- `tests/test_dispatched_unverified_input.py`（10 条）
- `tests/test_p1b0_post_game.py`：+4 条广场标签几何
- `tests/contract/test_l0_lobby_chain_contract.py`：`INGAME_POLLUTION` 补
  `_public_bag_fsm` / `_public_bag_next_at` / `_tick_post_confirm`（C2 隔离照旧逐字节一致）

`disconnect_modal_missing` 仍是 BLOCKED（素材缺失），与本轮无关。

## 五、仍需真机验证（不要当成已通过）

1. **公共背包存入的业务后置确认**：GT spec 明确写了 solo 录像**不能**声明
   `PUBLIC_BAG_DEPOSIT_GT = PASS`。t14 帧里物品落到公共格 (3,0)，t25 帧公共背包又空了 ——
   单人局没有队伍同步。`_public_backpack_deposit_postcondition` 的判据
   （目标格存入前空、存入后非空）**只在多人蹭车局才有意义**，必须用真实多人录像验。
2. **按 B 开/关背包在实机的时序**：`request_bag_open` 给了 3s 窗口，
   `CLOSE_REQUESTED` 给了 3s；实机若更慢会 ABORTED（零输入、有冷却，不会乱点），需要按实测调。
3. **战后 NPC_HUB → 传家宝入口**：f0133 现在能判成 NPC_HUB，但从 NPC_HUB 走到
   `OpenHeirloomChallenges` 并拿到结果，本轮没有实机证据。
4. **绿色神符 / 装备 / 英雄卡入公共背包**：未实现，等多人素材。

## 六、下一个 agent 的入口

- 实机跑：`tools/live_scenario_capture.py` 的 `public_backpack_deposit` target
  （worktree `G:\刷刷宝\Worktrees\live-harness-current-20260908`）。
  它期望的动作 reason 已经对上：`PublicBackpackDepositB` /
  `PublicBackpackDepositRightClick` / `PublicBackpackDeposit`。
- 素材：`G:\刷刷宝\_public_bag_gt_20260909\`（keyframes/crops/source_crops）。
  新素材切片用 `tools/gt_lab/extract_bag_gt.py`。
- 本轮**没有**构建桌面包（未动 `ui-v2/`、`desktop_app.py`、`build_release.ps1`、`ShuaBao.spec`），
  所以没有跑 `build_release.ps1`，桌面 EXE 仍是旧版。要交付实机 EXE 必须先构建并核对
  `build_identity.json` 的 `source_sha`。
