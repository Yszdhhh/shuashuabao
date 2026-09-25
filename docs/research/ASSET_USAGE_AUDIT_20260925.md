# 模板资产用途梳理（2026-09-25）

来源：`assets/Images/` 共 418 张（`boss/`、`chuanjiaobao/` 按目录整体扫描，不逐张引用）。
按"src / config / tools 里有没有以文件名引用"统计；`config/runtime_asset_manifest.json` 的登记不算引用。

## 背包清理要用的现成模板（Owner 09-25 需求）

| 模板 | 画面 | 现状 |
|---|---|---|
| `cundangInfo.png` | 局内 HUD 底栏「存档」字样 | 已被广场识别引用（`_TOP_BAR_LABEL_ROI`），可复用为入口 |
| `decompose.png` | 存档装备页「一键分解」按钮 | 只在 `scenes.json` 的 `clean` 场景（竞品 `AutoClean`）里登记，代码未接 |
| `yes.png` | 品质弹窗「是」按钮 | 同上，代码未接 |
| `zhuangbei.png` / `baoshi.png` / `cibao.png` | 存档页左栏「装备」、「宝石」、以及「磁暴」 | `clean` 场景登记，未接 |
| `cundang.png` | 「我要存档」按钮（另一处存档入口） | 仅 `tools/analyze_post_game.py` 使用 |

这些是竞品 1.4.9 的切图，接线前要在当前版本实机帧上核对分数（只读截屏已在 `G:\刷刷宝\captures\backpack_clean_gt_20260925`）。

## 完全没被引用的 44 张

**局内挑战开关旧切图（11 张，根目录）**
`coin/exp/treasure/wood_challenge_auto|btn`（8 张）、`click_evolve`、`click_evolve_v2`、`dashboard_core03_icon`。
挑战开关现在走 `_HUD_CHALLENGE_ROI` 下的另一套模板；这批是早期切图，其中 `treasure_challenge_btn.png` 实际切到的是 HUD「存档 设置」一带，`click_evolve*` 切到的是地面，均不可直接使用。`dashboard_core03_icon` 是看板图标，不是游戏模板。

**海盗卡组（16 张，`haidao/`）**
悬赏卡各稀有度（N 绿 / R 蓝 / SR 紫 / SSR 橙 / UR 红）、号角 Lv1、背包格与格内物品的各稀有度底色。原计划给海盗卡组识别背包里的藏宝图/宝藏用，接线未做。

**大厅与局内其它（17 张，`lobby/`）**
- 英雄选择高亮：`hero_heifeng/kenrito/shouhu/tanxian/yinse/yuansu_bright`（6 张），英雄三选一的备用高亮态；现行选英雄走 `select_hero.png`。
- 大厅楼层与标签：`lobby_1_4`、`lobby_2_4`、`lobby_4_4`、`lobby_in_game`、`lobby_popup_title`、`lobby_refresh_chars`（大部分是空白或半截文字，切图质量差）。
- `stage_sweep_btn`（选关页扫荡按钮）、`archive_cancel_btn`、`artifact_slot_q/w`（神器 Q/W 格）、`test_patch`（测试用）。

## scenes.json 里登记了但代码从不查询的场景（13 个）

`archive_start`、`archive_challenges`、`choice_panel`、`hero_challenge`、`f4_challenge`、`stage_begin`、`lobby_quick_join`、`lobby_join`、`lobby_popup_dialog`、`lobby_popup_leave`、`lobby_room_lock`、`room_cancel_ready`、`fetter_choice`（空）。
其中 `lobby_quick_join` / `lobby_join` 与红线"进房禁止颜色兜底、禁止误点快速加入"相关，保持不接。

## 建议

1. 背包清理直接复用 `cundangInfo` → `decompose` → `yes`，先用实机帧核对分数，再补品质勾选框的判定（传说不得勾选）。
2. 损坏或空白的切图（`treasure_challenge_btn`、`click_evolve*`、多数 `lobby_*`）不要接，后续可在资产清单里标 deprecated。
3. 海盗 16 张等海盗卡组接线时再核对。
