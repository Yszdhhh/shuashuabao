# 选关截断夹具 2026-09-26

两帧均复制自真机包
`C:\Users\10639\AppData\Local\Temp\shuabao-captures\solo_ingame_chain_20260926_123830_340057`
（`trace.jsonl` + `frames/`，1600x900 客户端实采，**不是合成帧**）。

- `highlight_on_1_18_before_click_client_1600x900.png`
  （源 `f0020_action_before.png`）：tick 48 第一次点 `stage_target_1-23` 之前，
  高亮在 **1-18**（整圈亮边环亮比约 0.45），目标 1-23 在列表底部只露出上半截。
- `selected_1_23_bottom_truncated_client_1600x900.png`
  （源 `f0025_action_after.png`）：tick 54 第三次点击之后，1-18 高亮已消失，
  1-23 带金边（已选中）但仍只露出上半截；底部「开始游戏」按钮可见。
  此帧 `selected_stage_row()` 在修复前返回 None（整圈环亮比仅约 0.04），
  导致 LIVE 的 `_find_stage_start` 覆写反复重置 `_stage_selected`，
  tick 48/51/54 三次重点击 1-23 后 tick 55 因
  `stage attempt budget exhausted: stage select attempts` 进 ERROR。

- 现场：入口 12 单人，`stage_targets=["1-23"]`，
  三次 `click:stage_target_1-23 @ (1237,858)`（屏幕坐标）。
- 用途：钉住 `selected_stage_row()` 必须读出被截断的末行高亮（= `1-23`），
  且点选前帧仍读出 `1-18`（不提前、不错位确认）。
