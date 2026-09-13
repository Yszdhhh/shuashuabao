# 蹭车战后链路审计交接（2026-09-14）

## 交接结论

本次只做两处小逻辑修复，没有重构主状态机：

1. 宝物三选一在整局刷新预算用尽、或连续无可共享道具达到保护阈值时，不再关闭面板并反复重新打开/隐藏；改为优先选择可识别的非负面卡，若 OCR 名称不可用则选择第一张可定位卡，保证本次 V 面板落地并让后续奖励继续处理。
2. 存档面板关闭后的短暂过渡帧不再被误判为选关页而提前退出。只要战后路由已经确定为 `archive`/`heirloom`，并且仍有广场/存档证据，就保持零输入等待入口，入口出现后继续点击 `OpenHeirloomChallenges`（或存档入口）。

## 真实证据

证据包：`C:\tmp\shuabao-captures\hitch_lobby_chain_20260914_000312_456716`

- 第一局密钥挑战并非漏点：`frames/f0336_action_before.png` 中密钥卡显示绿色 `8/8`，完成检查按设计跳过；同局其余七张卡均有 `ArchiveChallenge-*` 点击记录。
- 第二局密钥未完成时正常点过，trace tick 636 为 `ArchiveChallenge-key`。
- 第二局宝物末段 tick 599 打开 V，tick 602 刷新，之后 tick 607/613/615/621/623 反复 `treasure关闭`/重新打开；这是刷新预算耗尽后旧分支关闭面板造成的循环。本次修复将该分支改为兜底选卡。
- 第一局传家宝链路正常：tick 316 `OpenHeirloomChallenges`，tick 318 选择 Boss。
- 第二局 tick 645 关闭存档面板后，tick 646-650 仍处于 `cundangInfo` 过渡证据，旧逻辑在 tick 651 将页面误判为选关并进入 QUIT，因此没有机会点击传家宝。本次修复在选关判断前保留已确定的战后路由，入口出现后继续传家宝点击。

该证据包最终 `final_status=FAIL` 的原因是 harness 在后续未知前台上报告 `production input on UNKNOWN lobby/game surface`；不是本次两条修复的断言失败。生产源在该包中为基线提交 `45c35202393186afd324bf9e00fd3fcc6b89fa62`。

## 代码与验证

- 核心改动：`src/shuabao/mediator.py`
- 宝物回归：`tests/test_hitch_treasure_v_gate_20260913.py`
- 战后过渡回归：`tests/test_b15da05_real_regressions.py`
- 已通过：
  - `python -m pytest tests/test_hitch_treasure_v_gate_20260913.py -q`（14 passed）
  - `python -m pytest tests/test_b15da05_real_regressions.py -q`（48 passed）
  - `python -m pytest tests/unit/test_s0_hitch_policy_bounds.py -q`（7 passed）
  - 联合策略/Boss/宝物回归（206 passed，18 subtests passed）
  - `python tools/release_gate.py`：frozen replay、scene templates、contract 通过；pytest 观测为 2124 passed / 7 failed。失败集中在既有 live harness identity 基线（测试仍固定旧的 `4ed44d4`/旧生产 SHA）及同一轮门禁启动时尚未更新的旧宝物边界断言；本次新增/修改的针对性回归均已单独复跑通过。不得改基线掩盖，应保留原始失败原因。

## 审计接入要求

- 先审查本提交的两条行为约束和新增回归，再合入正式版看板。
- 不要把“格子未满”当作时光之穴最后 Boss 的唯一判断；本交接仅涉及传家宝入口过渡保护和宝物末段兜底选卡。
- 审计通过后再执行桌面正式看板同步；本工作区当前不宣称已注入生产桌面快捷方式。
