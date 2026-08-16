# bond_daodao_20260814 — 「刀刀」已吞噬面板

## 来源

- 用户 2026-08-14 实机截图：`source_yishitun_panel.png`（标题「已吞噬」）
- 证据等级：**R**（静帧截图，非局内选择面板 OCR）

## 2026-08-14 17:42 F 三选（user 截图）

- `f_panel_daodao_ghost_belt.png`：左敏捷祝福 / 中力量祝福 / 右 **刀刀(0/3) 幽灵系带**。脚本当时在点刷新。
- `f_panel_qitian_dasheng.png`：左敏捷祝福 / 中力量祝福 / 右 **齐天大圣(0/3) 天命人**。脚本当时在点刷新。

根因：白名单只有「祝福/大圣」，OCR 规范名是「敏捷祝福/幽灵系带/齐天大圣」。已补 set_membership 与 probe 卡序。

## 已确认事实

1. **「刀刀」是套装/羁绊规范名**，不是某件装备的专名。本屏前三行及第四行多格的角标均为「刀刀」，图标为各类武器/饰品/护甲/法器。
2. 同屏其它套装角标旁证：异火、封神、法宝、法术、急速、魔术、魔能（后四者本库多数已有）。
3. 每格右下角数量均为 `1`；本屏**看不到**单卡基础词条文本，也看不到力量/敏/智等数值公式。

## 2026-08-14 19:10 词条补全（174547）

F 已见 `刀刀(0/3)` → **need=3**，已从 `unknown` 挪进 `bond_stack_catalog.needs`。
散件/进阶/UR 与基础词条见 `docs/cards_breakdown_20260814_174547.md` + `fixtures/cards_174547_evidence/`（幽灵系带 / 护腕 / 空灵挂坠 / 刀刀萌新 / 刀刀大成）。

本目录仍只证明「刀刀是套装角标」。基础链 tooltip 以 174547 为准（KB `daodao_chain`）。已吞噬里其余刀刀件的高阶词条未采。

## 词库动作（已做）

- `choice_lexicon.json`：`刀刀`、散件、萌新、大成（`set_membership=刀刀`）。
- 未改 mediator / choice_policy 判定；未加 fetter 短码（无 `cards/*.png`）。

## 下一测临时入口

- `测试夹\lab_dasheng_probe.json` 已可叠 `"刀刀"` 中文进 `cards`（无短码）。
- 正式 `--route` 仍只有三属性；刀刀只能走 `--config` 采证，不设 `lab_exit_on_bond`。
