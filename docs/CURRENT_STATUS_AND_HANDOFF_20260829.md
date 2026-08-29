# 刷刷宝交接 2026-08-29

权威以本文件为准。上一份看板交接 `CURRENT_STATUS_AND_HANDOFF_20260821.md` 仍描述 UI 交互，不覆盖局内选卡。

## 23:38 实机（未修版本）

`C:\Users\10639\AppData\Local\ShuaBao\20260828\trace_20260828_233828.jsonl`

- 开局连续 `OpenSkillPanel`（G），到 tick 63 才第一次 F。
- 只确认拿到「经济」后就点了两次「封神」。
- tick 75 面板上出现「箭术」，当次选的是「经济」，不是箭术羁绊。奥术箭技能（箭矢连发/齐射等）来自已勾选的 `asj`。
- tick 159 `ClickEvolve` 后，英雄二选一被 `treasure_lock_btn` 判成宝物，tick 161/163 点了隐藏。
- 设置文件没有被部署清空；`cards` 与 `_shell.bond_scheme` 双写，scheme 里残留「箭术」。

桌面快捷方式 `刷刷宝.lnk` → `C:\Users\10639\Desktop\ShuaBao\ShuaBao.exe`（2026-08-29 09:55，含标题模板 `ffb3cfd`）。不是 MSI 安装包。用户设置仍在 `%LOCALAPPDATA%\ShuaBao\user_settings.json`，部署不会清空。

## 本轮已接线

- 局内循环起步改为 F；基础卡未到 80% 时继续锁 F。
- 高级卡组按白名单出现顺序一次只推进一套，当前套未到 80% 不拿下一套。
- 进化点击后 / 等英雄选择时，不再把英雄二选一判成宝物并隐藏。
- 看板加载用 `cards + bonds` 还原勾选；保存不再把 stale `bond_scheme`（箭术）写回白名单。
- 木材数值 HUD 仍未接线。界面「赌木 · 木材阈值 · 待接线」保持原样。开局和基础卡未满时只开 F，是当前能落地的替代，不是读到木头 > 300。

## 识别优先级（2026-08-29 续）

长期稳定性 > 准确度 > 速度：自己打开的面板 OCR 读名/选卡/刷新都要第二帧确认；没读到不刷新、idle 时不 Fail-Forward；live OCR 超时下限 2500ms；4 张布局先读 4 槽。

## 标题模板（2026-08-29 根源）

`G:\下载\1.5.1.zip\Images\cards` 不是 OCR 训练集，是 ~44×24 的 `matchTemplate` 标题字形。live F 以前读完 OCR 就返回，**从未**用这些图填空槽。另外短码标签和像素对不上：`jj`=经济、`tz`=挑战、`fs`=法神、`gushou`=固守、`yihuo`=异火、`mfs`=秘法师；`法术/急速/魔能` 在包根目录 `fashu/jisu/moneng`。卡住的 4 选（三国/刀刀/挑战2/3/暴击）上官方 `tz`/`baoji` 标题分 0.90/0.96，OCR 空白也能点挑战。这些字形原样打进主程序做 matchTemplate，不要拿去训 OCR。

## Stage 2A/B0 / Pre-Push Audit（2026-08-29）

- [Pre-Push Audit](distillation/PRE_PUSH_AUDIT_20260829.md) 为本轮 Stage 2A/B0 的收口证据；curated release gate 为 `4/4 PASS`，但 repo-wide pytest 当前冻结为 30 个既存失败 nodeid（含 Atlas/UI detector/历史 L0-L1 fixture/desktop/replay），所以不能写成全仓全绿。
- Panel timeout→cooldown→reopen 已用最小 harness 收口：复用 panel episode/cooldown/count，预算只计异常重开，正常 skill/bond/treasure 成功 episode 不消耗；三类 counter 独立，达到上限后永久 cooldown；仍遮挡 UI 的面板不会被忽略来伪造推进。`giveup_panel_not_fail` 已由真实三帧 replay PASS，`main_hud_idle` 已同步确认的 bond-first 真实修复。
- Panel 机制级 P0 已 CLOSED，但端到端长线程仍有最长约 381s 到 panel quarantine、接近 `round_timeout_s=3600s` 才 round fail-closed 的 stall 风险；本轮只记录，不新增 watchdog/recovery/fallback。
- `disconnect_modal_missing` 继续 `BLOCKED`，没有用合成帧更新 baseline。Coverage 阶段只做素材/评测，不接生产。

## 仍未做

- 亡灵 100 残骸 / 亡者大厅 / 邪爆、异火吞噬完再拿帝焱：没有对应计数器，不能假装已接线。
- `test_pause_overlay_clicks_resume_before_game_actions` 仍是全量 pytest 的既有回归；这不等同于 giveup baseline，后者已通过真实三帧 replay。不要为了绿灯修改无关 baseline。
