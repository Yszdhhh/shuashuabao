# 刷刷宝交接 2026-08-29

权威以本文件为准。上一份看板交接 `CURRENT_STATUS_AND_HANDOFF_20260821.md` 仍描述 UI 交互，不覆盖局内选卡。

## 23:38 实机（未修版本）

`C:\Users\10639\AppData\Local\ShuaBao\20260828\trace_20260828_233828.jsonl`

- 开局连续 `OpenSkillPanel`（G），到 tick 63 才第一次 F。
- 只确认拿到「经济」后就点了两次「封神」。
- tick 75 面板上出现「箭术」，当次选的是「经济」，不是箭术羁绊。奥术箭技能（箭矢连发/齐射等）来自已勾选的 `asj`。
- tick 159 `ClickEvolve` 后，英雄二选一被 `treasure_lock_btn` 判成宝物，tick 161/163 点了隐藏。
- 设置文件没有被部署清空；`cards` 与 `_shell.bond_scheme` 双写，scheme 里残留「箭术」。

桌面 `C:\Users\10639\Desktop\ShuaBao\ShuaBao.exe` 仍是 2026-08-29 00:12 的 Codex 包，**不含**本轮补丁。要实机验证必须重新打包。

## 本轮已接线

- 局内循环起步改为 F；基础卡未到 80% 时继续锁 F。
- 高级卡组按白名单出现顺序一次只推进一套，当前套未到 80% 不拿下一套。
- 进化点击后 / 等英雄选择时，不再把英雄二选一判成宝物并隐藏。
- 看板加载用 `cards + bonds` 还原勾选；保存不再把 stale `bond_scheme`（箭术）写回白名单。
- 木材数值 HUD 仍未接线。界面「赌木 · 木材阈值 · 待接线」保持原样。开局和基础卡未满时只开 F，是当前能落地的替代，不是读到木头 > 300。

## 识别优先级（2026-08-29 续）

长期稳定性 > 准确度 > 速度：自己打开的面板 OCR 读名/选卡/刷新都要第二帧确认；没读到不刷新、idle 时不 Fail-Forward；live OCR 超时下限 2500ms；4 张布局先读 4 槽。

## 仍未做

- 亡灵 100 残骸 / 亡者大厅 / 邪爆、异火吞噬完再拿帝焱：没有对应计数器，不能假装已接线。
- `test_pause_overlay_clicks_resume_before_game_actions` 与 `GATE_BASELINE` 的 giveup 预期，仍是既有红灯。不要为了绿灯改基线。
