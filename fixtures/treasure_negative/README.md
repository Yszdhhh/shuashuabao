# treasure_negative — 负面宝物取证包（真机抽帧，无合成 / 无 mp4）

供 **D 组**描述取证、**A 组**描述 ROI 标定。2026-08-12 从本机已入库抽帧 + `fixtures/reborn_wow` 整理。

## 已确认 6 张

透支力量 · 贪婪献祭 · 金转木 · 杀敌梭哈 · 伐木契约 · 等级优势

## 目录

| 路径 | 含义 |
|---|---|
| `<卡名>/panel_*.png` | 含该卡的完整选卡面板 |
| `<卡名>/name_*.png` | 卡名 ROI |
| `<卡名>/desc_*.png` | 描述区初裁（固定比例，可能偏） |
| `<卡名>/desc2_*.png` | 按 manifest name ROI 下方重裁（优先用这个） |
| `_panels/treasure_panel.png` | 性能夹具面板，ROI 参考 |
| `INDEX.json` | 机器索引 |
| `DESCRIPTIONS.json` | 读图得到的描述原文 + pattern 缺口建议 |

## 覆盖

六张均有至少 1 张真机面板帧 + 描述裁剪。细节与缺口见 `DESCRIPTIONS.json`。

## 红线

- 无合成帧
- 名单外不得仅凭名字可疑拉黑
- 原始录像 mp4 未入库（体积过大）；需要时再从 `Desktop/录屏素材` 抽帧补
