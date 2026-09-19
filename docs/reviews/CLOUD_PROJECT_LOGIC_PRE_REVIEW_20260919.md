# 海盗机制项目级逻辑与数据预审查包（2026-09-19）

> 目的：把海盗卡组、羁绊拿卡、个人/公共背包、物品栏道具、木材阈值、技能抢占和现有测试证据放到同一个审查面，供云端做项目级预审查。
> 性质：**Draft / review only**。本包不宣称当前候选已通过 GT，不把旧实机日志当作当前 HEAD 的验收证据，也不在没有实机闭环前修改运行策略。

## 1. 审查快照与结论

| 项目 | 当前值 |
|---|---|
| 分支 | `test/pirate-necromancy-gt-20260917` |
| 审查 HEAD | `270caf76487272dcf73381f2d3201b7cf61cd9bc` |
| 生产锚点 | `b52c69e2aa1f74b59506439cceba06535bc6234c` |
| 相对 `origin/main` | 领先 82 commits、129 files、`+17549/-797` |
| 最新有效实机问题日志 | `captures/pirate_necromancy_20260919_140828/run.log`，candidate 为 `e49a4a9` |
| 当前 HEAD 实机结论 | **未验证**；`ac04a74` / `270caf7` 之后没有可归因的 LIVE `run.log` |
| 离线专项门禁 | 合同脚本 PASS，但 readiness BLOCKED；目标回归集 261 passed / 6 failed |
| 建议合并状态 | **禁止直接合并；先完成云端预审查，再拆实现 PR 与实机验收** |

当前最重要的结论：

1. `ac04a74` 修复了“同一轮立刻反复抢占”和面板残留，但没有消除根因。技能点仍在 `>= 8` 时无视木材量强抢占；30 秒退避结束后可再次进入 G 面板。
2. 基础卡漏拿的配置缺口已经补上，但“只推进当前高级卡组”的目标与 `test_open_mode` 行为冲突：`bond_base_completion_ratio=0.0` 会让全部高级预设都合法，包括尚未轮到的宝藏/亡灵。
3. 背包、物品栏和道具链路本身有事务门禁，但它们排在 `_maybe_open_choice_panel()` 之后。只要选卡调度持续抢占，吞噬丹、悬赏令、黄金猿、银月之晶、定期拾取和背包维护都可能延迟。
4. 现有证据混用了旧 candidate 的 LIVE 日志、当前 HEAD 的离线合同、零输入 WhatIf 和过时 READY 文档，不能组成当前候选的闭环证明。

## 2. 当前链路总图

```text
MAIN_LINE tick
  ├─ 已有面板/事务 FSM 收口
  ├─ _maybe_open_choice_panel()                ← G/F/V 先于背包和道具
  │    ├─ skill >= 8 → G（无视 wood）
  │    ├─ 基础未完成或 wood >= 200 → F
  │    └─ 普通 L1 cycle: artifact/skill/bond/treasure/evolve/equipment/pickup/public_bag
  └─ 仅 HUD_ONLY 且无事务时
       ├─ L 吞噬状态检查
       ├─ _maybe_use_inventory_item()
       │    ├─ 银月之晶
       │    ├─ 吞噬丹
       │    ├─ 黄金猿
       │    ├─ 神赐吞噬丹
       │    └─ 悬赏令 / 快捷栏→个人背包暂存
       ├─ 定期 Z 拾取
       ├─ 装备/进化/英雄卡/银月/黑商机会动作
       └─ cycle 到 pickup/public_bag 时处理个人或公共背包
```

这个顺序能避免背包点击与中央选卡面板同时发生，但也把所有维护动作绑定到“选卡调度能够让出 tick”这一前提。当前技能强抢占与高木材羁绊抽卡都可能长期占用这个入口。

## 3. 逻辑冲突矩阵

| ID | 链路 | 当前实现 | 冲突或风险 | 当前证据 | 预审查问题 |
|---|---|---|---|---|---|
| C1 | 技能 vs 木材 | `skill >= 8` 在 `_solo_plan_panel()` 第一优先级，无视 wood；无合法技能退出后退避 30 秒 | 5700+ 木材时仍可周期性回到 G；从“连续活锁”变为“周期抢占”，F/背包/道具仍可能被压制 | 旧 LIVE 日志 45、181 行进入强抢占，96、234、286、338、393 行超时；当前代码 `mediator.py:4621-4629,16552-16556,16736-16767` | 是否用木材饱和状态压制 G，且采用有进入/退出阈值的滞回策略？ |
| C2 | 木材阈值 | `_BOND_HIGH_WOOD=200`，高木材 F 最多 15 次或 60 秒 | 文档/测试仍存在 1000、3000、5000 等语义；200 既像“可抽”又承担“狂暴转战力”，命名与行为不一致 | `mediator.py:4417-4436,4631-4646`；目标回归有 3 个阈值断言失败 | 统一成“可支付价格”“高木材饱和”“退出饱和”三个概念，还是保留单阈值？ |
| C3 | 基础卡 vs 高级组 | 配置包含祝福/成长/经济/挑战；`bond_base_completion_ratio=0.0` | 基础卡已不再漏配，但 0.0 会触发 `test_open_mode`，允许全部 `bond_advanced_presets`，绕过当前高级组 | `dashboard_test_profiles.json:60-69`；`choice_policy.py:1464-1475`；测试 `test_test_open_mode_allows_all_configured_advanced_presets` 明确固化该行为 | 测试放开“基础卡门禁”是否应该同时放开“高级组顺序”？建议拆成两个开关 |
| C4 | 基础卡经济优先级 | `_ECONOMY_BOND_ORDER=(祝福, 成长, 经济, 贪婪, 挑战)` | 需求称“按经济优先级”，但同屏时实际先祝福、再成长、再经济；术语与排序相反 | `choice_policy.py:407,458`；离线决策探针可复现成长优先于经济/挑战 | 明确业务排序，并让配置/测试只保留一个权威来源 |
| C5 | 海盗终局 | 毁灭战舰或累计海盗 `>=12` 才停止拿非合并散卡 | 10 格羁绊栏无法自然容纳 12 张；计数又混合持有/吞噬估算，容易在基础卡和后续宝藏/亡灵前过度占槽 | `choice_policy.py:1494-1511,1636-1647`；相应测试把 12 固化为契约 | 是否改为 8 张或 `free_slots <= 4`，同时保留罗杰斯/毁灭战舰/合并升级例外？ |
| C6 | 悬赏令吞海盗 | 按悬赏令品质吞不高于它的海盗；罗杰斯和毁灭战舰被保护 | 当 owned 未记录具体海盗、但配置含海盗且栏位非空/未知时，会兜底允许吞噬；身份不充分时授权偏宽 | `mediator.py:5456-5511`；单测覆盖品质、核心保护和未跟踪卡 | 未知身份应 fail-closed，还是允许为释放槽位而推定吞噬？需要产品级裁决 |
| C7 | `auto_devour_dan` | Settings 默认 `False`，GT profile 显式 `true`；海盗配置本身也能触发吞噬丹分支 | 旧交接写“必须 False”，配置与运行代码却允许 true；当前权威契约互相矛盾 | `settings.py:197`、profile 69 行、`mediator.py:5578-5618`、`test_p0_devour_failclosed_20260917.py` | 确定“吞噬丹总开关”和“海盗专用吞噬授权”的边界，删除双重授权 |
| C8 | 黄金猿/银月/神赐丹 | 都在 inventory 链路；黄金猿和银月可从 HUD/背包识别，神赐丹要求 EX；均受每次访问点击上限/冷却 | 物品识别和使用顺序存在，但缺少当前 HEAD 的真实后置条件证据（物品消失、弹窗确认、宝藏组真正开启） | 单元测试证明派发动作；无 `270caf7` LIVE 闭环 | 每类道具都应定义“点击成功”之外的可观测后置条件及超时恢复 |
| C9 | 个人背包 vs 公共背包 | 单人维护个人背包；蹭车用 `PublicBagFSM`，公共流转活跃时禁止左键吃丹 | 隔离条件清晰，但主入口仍晚于选卡；个人背包常驻、Boss 强关、拾取打开和道具暂存共享 B 开关与多个 cooldown | `mediator.py:5514-5526,5622-5636,6761-6915,18502-18682` | 是否把“需要清包/关键道具待用”提升为有预算的调度任务，而非机会动作？ |
| C10 | 首帧直击 | 严格 helper 要求预设/严格命中、>=0.95、无重名；其后另有通用 `>=0.95` 分支 | 后一个分支实际绕过了 helper 的唯一性/原因限制；与拟议的 `>=0.90` 白名单首帧直击不是同一安全边界 | `mediator.py:3917-3954,3985-4006` | 先删除重复授权，建立一个首帧授权函数，再讨论是否从 0.95 降到 0.90 |
| C11 | 状态与证据 | 旧 handoff 标记 READY，当前目标回归仍 6 FAIL，readiness 为 BLOCKED | 云端若只读 handoff 会得出错误结论；WhatIf 只是零输入预检，不能替代 LIVE | 本文第 5 节 | 以 manifest candidate SHA 为强关联键，禁止跨 commit 借用 LIVE 结论 |

## 4. 四个架构决策的建议裁决

这些是预审查建议，不在本 PR 中改代码。

### D1. 技能 4 槽未满且未中预设，是否允许通用技能补位

建议：**暂不允许通用技能自动补位**。只有在“可识别当前 4 槽、可安全遗忘/替换、替换结果可验证”三项均有实机证据后，才开放有限补位。否则临时技能会占死槽位，把一次调度饥饿变成整局构筑污染。

可接受的后续实现应是显式白名单、最低品质、最多临时槽数、替换预算和后置验证的组合，而不是按 OCR 最高品质盲拿。

### D2. 5000+ 木材是否动态压制技能抢占

建议：**是，但使用滞回和服务预算**。建议进入饱和阈值 `wood >= 3000`，退出阈值 `wood < 1000`；饱和期间 F 单次最多 15 次或 60 秒，然后强制让出一个服务机会给 V、背包/道具和 G。技能仍可在明确的防溢出上限触发一次，但不能每次 30 秒退避结束就重新占领主入口。

阈值需要以真实抽卡价格曲线和一局木材增长曲线校准；5000 只是现场症状，不应成为唯一魔法数。

### D3. `confidence >= 0.90` 的静态卡是否首帧直击

建议：**条件开放，不做泛化阈值放行**。仅当卡名是 canonical 精确白名单、同屏唯一、槽位坐标有效、非刷新/品质降级/模糊别名、且当前 panel ownership 已确认时允许 `>=0.90` 首帧点击。刷新、重名、近似 OCR、满槽替换继续双帧。

在实施前先合并当前两套首帧授权逻辑；现有通用 `>=0.95` 分支会绕过“同屏唯一”检查。

### D4. 海盗散卡停止阈值是否从 12 提前

建议：**改为 8 张或 `free_slots <= 4`，两者先到先停**。停止后仍允许：罗杰斯上将、毁灭战舰、可验证合并升级、明确 must-take。这样能为四大基础卡以及后续宝藏/亡灵保留空间。最终数字要用 live occupancy 与吞噬计数对账，避免把“历史已吞”误当“当前占槽”。

## 5. 证据账本

### 5.1 已通过但能力有限

| 命令/证据 | 结果 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| `powershell -ExecutionPolicy Bypass -File tools/one_click_test.ps1 -WhatIf` | PASS | 当前候选可完成零输入 prepare；命令没有向游戏派发输入 | 不能证明选卡、背包、道具或一局闭环 |
| `python tools/check_pirate_necromancy_profile.py` | `offline_contract: PASS` | profile schema、必要配置和离线合同可解析 | 同一输出里 `dashboard_readiness: BLOCKED`、`gt_readiness: BLOCKED`；不能当 READY |
| `tests/test_policy_bond_identity_20260916.py` 中道具/海盗测试 | 多数 PASS | 决策函数与 mock 动作派发符合当前断言 | mock 点击不等于游戏接受动作；部分测试固化了待裁决的 12 张/open mode 行为 |

### 5.2 红灯与不一致

目标回归命令：

```powershell
python -m pytest `
  tests/test_solo_planner_20260915.py `
  tests/test_solo_core_development_20260916.py `
  tests/test_choice_policy.py `
  tests/test_panel_liveness_harness.py `
  tests/test_policy_bond_identity_20260916.py `
  tests/test_solo_b2_pickup_speed_20260915.py `
  tests/test_live_run_205044_regressions.py -q
```

结果：`261 passed, 6 failed, 18 subtests passed`。

- 3 个 planner 失败：旧断言与当前 `_BOND_HIGH_WOOD=200` 不一致。
- 1 个 panel liveness 失败：旧断言期待 `COOLDOWN`，当前修复有锚点时转 `CLOSING`。
- 2 个 inventory hero-card 回归失败：与海盗主问题不完全同域，但说明项目级候选不能声称全绿。

### 5.3 LIVE 证据边界

`captures/pirate_necromancy_20260919_140828/manifest.json` 将 candidate 锁定为 `e49a4a9`，早于 `ac04a74` 和当前 `270caf7`。该日志只能证明旧缺陷存在：

- 45 行：技能点 12 触发紧急强抢占。
- 61-96 行：多次刷新后超时；181-393 行重复出现同类 episode。
- 114、137、153 行：木材 6031/5937/5868 时 F 有短暂服务，但之后又回到 G。
- 410-415、431-436、453-458 行：策略识别“挑战”，运行时却点击 `card_hide`，证明旧 candidate 的策略与执行白名单脱节。

`ac04a74` 对这些点做了修正，但当前没有 post-fix LIVE 日志，因此结论只能是“代码路径已改变、离线尚待证明”，不能写“彻底根除”。

## 6. 云端预审查请求

请按以下顺序审查完整 PR diff，而不是只看最后一个文档 commit：

1. **权威数据源**：profile → Settings → `PolicySettings` → runtime mediator 的字段是否存在二次默认、别名扩张或反向覆盖。
2. **全局调度公平性**：G/F/V、inventory、pickup、equipment、evolve、merchant、personal/public bag 是否都有可证明的最大等待时间。
3. **海盗状态模型**：当前持有、历史吞噬、OCR 估算、毁灭战舰终局、卡槽 occupancy 是否被混成同一个计数。
4. **动作事务**：每次点击是否有唯一授权点、可观测后置条件、有限重试和明确回滚/关闭路径。
5. **证据归因**：测试和文档是否锁定同一 candidate SHA、同一配置 hash、同一运行模式。
6. **重复逻辑**：首帧选卡、银月之晶使用、背包开关、海盗配置检测是否有多入口导致门禁不一致。

重点文件：

- `src/shuabao/mediator.py`
- `src/shuabao/choice_policy.py`
- `src/shuabao/policy/public_bag.py`
- `src/shuabao/bond_capacity.py`
- `src/shuabao/runtime_mediator.py`
- `src/shuabao/settings.py`
- `config/dashboard_test_profiles.json`
- `config/choice_lexicon.json`
- `config/game_mechanics_kb.json`
- `tests/test_policy_bond_identity_20260916.py`
- `tests/test_solo_planner_20260915.py`
- `tests/test_panel_liveness_harness.py`
- `tests/test_live_run_205044_regressions.py`

## 7. 后续实现 PR 的验收门槛

云端预审查完成后，建议另开小范围实现 PR，至少满足：

1. 一个权威调度策略能说明在任意资源组合下 G/F/V、背包和关键道具的最大等待时间。
2. 将基础门禁、高级组顺序、海盗终局和吞噬授权拆成独立状态，不再用 `ratio=0.0` 同时表达多个语义。
3. 阈值有单元测试覆盖边界与滞回，不再让旧 1000、当前 200、现场 5000 在注释/测试/实现中并存。
4. 首帧直击只有一个授权函数，并覆盖唯一性、canonical 名称、置信度、panel ownership 与满槽替换例外。
5. 道具测试验证后置条件，而不只验证 `act_click()` 被调用。
6. 目标回归集与 `python tools/release_gate.py` 全绿，或每个非本次失败都有明确、经审查的基线记录。
7. 新 LIVE run 的 manifest 必须指向实现 PR HEAD；至少覆盖高木材+技能积压、挑战卡首帧/双帧、海盗 8~12 张、悬赏令暂存/吞噬、黄金猿、Boss 强关背包。
8. 只有上述证据归档后才能把 CURRENT_STATUS 改回 READY。
