# card_template_assertions — B 组双向断言夹具

- 模板本体：`assets/Images/cards/<短码>.png`（仓库已有 36 张，勿重复造假图）
- `positives/`：应能命中部分羁绊/宝物面板的真机帧
- `negatives/`：空白/HUD，模板得分应 ≤0.4
- 阈值：正 ≥0.9，负 ≤0.4（见 `templates_index.json`）
- `FettersCard.tsx` 手抄副本属 C 组，B 组只维护 `config/fetter_labels.json`
