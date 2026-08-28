# treasure_must_take — EX 宝物必拿取证（用户录像截图）

用户 2026-08-13 确认：三选一面板出现下列卡 **立刻拿**，压过品质降级。

来源是录像静帧（手机播放条可见），不是合成图。PC 1600×900 三槽布局若不同，仍以 OCR 卡名为准。

| 规范名 | 效果（截图原文） |
|---|---|
| ONEPIECE | 恭喜你找到了ONEPIECE!! 金币+100w / 木材+3000 |
| 至高进化 | 等级提升5级，本局进化时变为至高进化（解禁全部进化英雄，极大幅度提升高品级英雄出现概率） |
| 一身神装 | 立即获得神器：王者之冠、燃烧军团之徽、远古王者之刃、高洁七星龙渊剑（不会触发装备成就） |
| 满级大佬 | 立即提升至50级 |

接线：`config/choice_policy.json` → `treasure.must_take_names` → mediator `treasure_presets`。
词典：`config/choice_lexicon.json`。
