# B 组卡牌模板 / 词典交付说明（2026-08-12）

## 模板库存

- 目录：`assets/Images/cards/`（36 张，与 `config/fetter_labels.json` 短码 1:1）
- 断言夹具：`fixtures/card_template_assertions/`（`templates_index.json` + positives/negatives）
- **未伪造新卡图**。用户尚未提供的短码（如独立「海盗」「修仙」卡面若需入库）仍等待实机素材。

## 双向断言（`tools/validate_scenes.py`）

强制项：

| 检查 | 阈值 | 说明 |
|------|------|------|
| 模板自匹配（正样本源） | ≥ 0.9 | 每个短码 PNG 可读且可匹配 |
| 空白负样本 `black_frame` | ≤ 0.4 | 真空白，对应进化模板教训 |
| 无关帧 `idle_hud` | < 0.9 | 不得达到点击阈值（防误点）；idle 含同色描边 UI 字，≤0.4 对旧文字裁切不可达，记 WARN |
| 面板正样本锁 | ≥ 0.9 | `zhufu` 在 `bond_choice_3` / `bond_panel` |

## 词典

- 六张负面宝物名已在 `config/choice_lexicon.json`（treasure）
- 补录 D0 夹具证实的 OCR 别名：`箭失*` / 全角括号资源名等

## 提醒 C 组

`ui/src/components/FettersCard.tsx` 的 `FETTER_NAMES` 是手抄副本，需与 `config/fetter_labels.json` 同步（或改为 API 拉取）。
