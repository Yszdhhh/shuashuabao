# treasure_negative — 负面宝物取证包（真机抽帧，无合成 / 无 mp4）

供 **D 组**描述取证、**A 组**描述 ROI 标定。2026-08-12 从本机已入库抽帧 + `fixtures/reborn_wow` 整理；
2026-09-22 追加 14 张真机原帧（13 卡来自 `_facts_20260922/treasure_debuff_frames`，诅咒之力来自 Lark 真机图）。

## 已确认 20 张

### 2026-08-12（6）
透支力量 · 贪婪献祭 · 金转木 · 杀敌梭哈 · 伐木契约 · 等级优势

### 2026-09-22（14，仅夹具入库；默认不拿仅诅咒之力/提高上限，其余待 Owner 逐卡裁决）
力之极 · 命运骰子 · 恶魔契约 · 提高上限 · 敏之极 · 智之极 · 木材梭哈 · 混乱转换 · 玻璃大炮 · 登神长阶 · 经验压制 · 贪婪契约 · 金币梭哈 · 诅咒之力

## 目录

| 路径 | 含义 |
|---|---|
| `<卡名>/panel_*.png` | 含该卡的完整选卡面板（原帧无损转码 PNG，不裁剪不缩放不增强） |
| `<卡名>/name_*.png` | 卡名 ROI（`Mediator._OCR_SLOT_ROIS["treasure"]`） |
| `<卡名>/desc_*.png` | 描述区初裁（固定比例，可能偏） |
| `<卡名>/desc2_*.png` | 按 name ROI 下方生产描述带重裁（优先用这个；`Mediator._OCR_DESC_ROIS["treasure"]`） |
| `_panels/treasure_panel.png` | 性能夹具面板，ROI 参考 |
| `INDEX.json` | 机器索引（含 panel_slots 标注共享帧槽位） |
| `DESCRIPTIONS.json` | 读图得到的描述原文 + pattern 缺口建议 |
| `SOURCES.json` | 每张入库图的 SHA-256 与原始来源路径（可追溯 `_facts` / Lark 原件） |

## 覆盖

六张旧卡均有至少 1 张真机面板帧 + 描述裁剪。2026-09-22 十四张均有 ≥1 张真机 panel；
除共享帧按槽位各卡目录各放一份外，name/desc2/desc 按 1600×900 生产 ROI 裁剪。
细节与缺口见 `DESCRIPTIONS.json`。

共享原帧（INDEX `panel_slots.shared_with` 标注）：
- `panel_030308_666_6e5a9909`：力之极 slot0 / 混乱转换 slot1
- `panel_185040_112_8b9790d7`：提高上限 slot1 / 经验压制 slot0

## 红线

- 无合成帧
- 名单外不得仅凭名字可疑拉黑
- 原始录像 mp4 未入库（体积过大）；需要时再从 `Desktop/录屏素材` 抽帧补
- 2026-09-22 批次：仅诅咒之力 / 提高上限默认不拿（Owner 已批准）；其余 12 张只入夹具，不改默认拿/不拿
- negative_patterns 本轮不改（见 `DESCRIPTIONS.json` 的 `suggested_pattern_appends_for_owner`）
