# B2-2 离线 OCR 评测报告（PP-OCRv5 mobile rec-only）

> 生成时间：2026-08-10T13:19:44
> 模型：PP-OCRv5_mobile_rec（本地固定版本，SHA256 见 `models/ocr/MODEL_MANIFEST.json`）
> 数据：131 valid slots / 44 面板 / 57 套装进度槽
> 预处理对比：原图 vs 2x lanczos + contrast 1.5
> 机器：i5-13600KF / Windows 10 / CPU（10 threads，device=cpu）

## 1. 门禁结果（生产候选变体 = raw）

| 门禁 | 阈值 | 实测 | 结论 |
|---|---:|---:|---|
| canonical_top1_accuracy | 0.95 | 0.026 | FAIL |
| lexicon_recall | 0.99 | 0.026 | FAIL |
| mis_normalization | 0 | 0 | PASS |
| set_progress_accuracy | 0.95 | 0.0 | FAIL |
| panel3_cpu_p95 | 300.0 | 107.5 | PASS |
| single_cpu_p95 | 120.0 | 56.0 | PASS |
| rss_delta | 800.0 | 128.4 | PASS |
| offline_inference | 1.0 | 1.0 | PASS |
| model_sha256_recorded | 1.0 | 1.0 | PASS |

**总体：存在 FAIL，见下**

## 2. OCR-raw 报告层（不设门禁，仅报告）

| 变体 | 字符准确率 | 词准确率(对 raw_text) | 词准确率(对规范名) |
|---|---:|---:|---:|
| raw | 1.53% | 1.53% | 1.53% |
| pre | 1.53% | 1.53% | 1.53% |

## 3. lexicon-gated 生产门禁层

### 变体 raw

- 词典内槽位（含别名覆盖）：154，词典外：108
- 规范名 Top-1（严格）：4/150 = 2.67%
- 规范名 Top-1（别名感知）：4/154 = 2.6%
- 词典召回（别名感知）：2.6%（154 槽）
- 技能词典召回（严格）：6.45%（62 槽）
- 误归一（词典外→配置名）：**0**（词典外正确置 None：108）

### 变体 pre

- 词典内槽位（含别名覆盖）：154，词典外：108
- 规范名 Top-1（严格）：4/150 = 2.67%
- 规范名 Top-1（别名感知）：4/154 = 2.6%
- 词典召回（别名感知）：2.6%（154 槽）
- 技能词典召回（严格）：6.45%（62 槽）
- 误归一（词典外→配置名）：**0**（词典外正确置 None：108）

### 套装进度 x/y 完全正确率：0.0%（0/57）

## 4. 性能

| 项 | 值 |
|---|---|
| 模型加载时间 | 3.32s |
| 单槽 P50/P95（raw） | 22.7 / 56.0 ms |
| 单槽 P50/P95（pre） | 23.4 / 55.7 ms |
| 三槽连推 P50/P95（raw） | 68.3 / 107.5 ms |
| 三槽连推 P50/P95（pre） | 72.1 / 108.1 ms |
| RSS（import/加载后/稳态） | 23.0 / 362.7 / 491.1 MB |
| RSS 常驻增量 | 128.4 MB |
| 模型目录（仓库） | C:\Users\10639\Desktop\🎮 影音游戏\GameScript-Local\models\ocr\PP-OCRv5_mobile_rec_infer |
| 模型目录（ASCII 暂存） | C:\tmp\ocr_stage_mobile2\PP-OCRv5_mobile_rec_infer |
| 采样量 | 单槽 262、三槽 88 |

## 5. 断网/离线校验

- 结果：PASS — socket 出站连接全阻断下完成模型加载+推理
- 加载耗时：0.505s；推理耗时：0.053s；识别文本：'福7'

## 6. 错例清单

### 6.1 生产门禁错误（候选变体 raw，词典内 Top-1 错误）

| crop | 真值 | OCR raw | 归一化 | lookup 结果 | 类型 |
|---|---|---|---|---|---|
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_015s_技能面板_giveUp证据_slot0_name.png` | 次级箭 | '福7' | '福7' | None | skill |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_015s_技能面板_giveUp证据_slot1_name.png` | 焦点 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_015s_技能面板_giveUp证据_slot2_name.png` | 箭矢齐射 | '7-' | '7-' | None | skill |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_234s_技能面板_slot0_name.png` | 次级增伤 | '福4' | '福4' | None | skill |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_234s_技能面板_slot1_name.png` | 地震 | '兴' | '兴' | None | skill |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_234s_技能面板_slot2_name.png` | 射线增幅 | 'C' | 'C' | None | skill |
| `fixtures\ocr_choices\skill\live_postgame_20260808\live_skill_choice_slot0_name.png` | 射线增幅 | '福C' | '福C' | None | skill |
| `fixtures\ocr_choices\skill\live_postgame_20260808\live_skill_choice_slot1_name.png` | 奥术激光 | 'X' | 'X' | None | skill |
| `fixtures\ocr_choices\skill\live_postgame_20260808\live_skill_choice_slot2_name.png` | 剑气 | 'C星' | 'C星' | None | skill |
| `fixtures\ocr_choices\skill\reborn_wow_screens_20260806\skill_choice_3_slot0_name.png` | 陨石 | '福' | '福' | None | skill |
| `fixtures\ocr_choices\skill\reborn_wow_screens_20260806\skill_choice_3_slot1_name.png` | 次级箭 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\reborn_wow_screens_20260806\skill_choice_3_slot2_name.png` | 地震 | '' | '' | None | skill |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot0_name.png` | 乱世三国 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot1_name.png` | 体魄 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot2_name.png` | 攻击提升 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot0_name.png` | 修仙 | '」2' | '」2' | None | bond |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot1_name.png` | 魔术 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot2_name.png` | 封神 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot0_name.png` | 智力祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot1_name.png` | 敏捷祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot2_name.png` | 力量祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot0_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot1_name.png` | 六星球 | '?' | '?' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot2_name.png` | 物理伤害 | 'M' | 'M' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot0_name.png` | 攻坚 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot1_name.png` | 四星球 | '?' | '?' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot2_name.png` | 奥术神符 | '-' | '-' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot0_name.png` | 攻坚 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot1_name.png` | 四星球 | '?' | '?' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot2_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot0_name.png` | 攻坚 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot1_name.png` | 四星球 | '?' | '?' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot2_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\reborn_wow_screens_20260806\treasure_choice_3_slot0_name.png` | 贪婪献祭 | '福' | '福' | None | treasure |
| `fixtures\ocr_choices\treasure\reborn_wow_screens_20260806\treasure_choice_3_slot1_name.png` | 卡牌大师 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\reborn_wow_screens_20260806\treasure_choice_3_slot2_name.png` | 双倍神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot0_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot1_name.png` | 六星球 | '-' | '-' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot2_name.png` | 物理伤害 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-ef3f2be8fc5d1103_slot0_name.png` | 攻坚 | '福' | '福' | None | treasure |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-ef3f2be8fc5d1103_slot1_name.png` | 四星球 | '-' | '-' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-ef3f2be8fc5d1103_slot2_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\skill\rec3_260810\f_008_slot1_name.png` | 电磁网 | 'R' | 'R' | None | skill |
| `fixtures\ocr_choices\skill\rec3_260810\f_008_slot2_name.png` | 冰霜新星 | '' | '' | None | skill |
| `fixtures\ocr_choices\bond\rec3_260810\f_015_slot0_name.png` | 敏捷祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec3_260810\f_015_slot1_name.png` | 智力祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec3_260810\f_015_slot2_name.png` | 力量祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\treasure\rec3_260810\f_021_slot0_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec3_260810\f_046_slot0_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\skill\rec5_260808\f_010_slot2_name.png` | 箭矢齐射 | '7' | '7' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_024_slot0_name.png` | 天雷 | '福不' | '福不' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_024_slot1_name.png` | 焦点 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_027_slot0_name.png` | 飓风 | '福' | '福' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_027_slot1_name.png` | 陨石 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_027_slot2_name.png` | 电磁网 | 'R' | 'R' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_042_slot0_name.png` | 射线增幅 | '福C' | '福C' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_042_slot1_name.png` | 奥术激光 | 'X' | 'X' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_042_slot2_name.png` | 剑气 | 'CF' | 'CF' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_043_slot1_name.png` | 天雷 | '五' | '五' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_044_slot0_name.png` | 飓风 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_044_slot1_name.png` | 次级箭 | 'Z' | 'Z' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_045_slot0_name.png` | 爆炎箭 | '福D' | '福D' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_083_slot0_name.png` | 闪电链 | '福国' | '福国' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_083_slot1_name.png` | 飓风 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_083_slot2_name.png` | 地震 | '兴' | '兴' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_174_slot1_name.png` | 射线增幅 | '' | '' | None | skill |
| `fixtures\ocr_choices\bond\rec5_260808\f_030_slot0_name.png` | 力量祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_030_slot1_name.png` | 敏捷祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_030_slot2_name.png` | 乱世三国 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_031_slot0_name.png` | 敏捷祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_033_slot0_name.png` | 敏捷祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_034_slot0_name.png` | 敏捷祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_035_slot0_name.png` | 敏捷祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\treasure\rec5_260808\f_112_slot0_name.png` | 六星球 | '口' | '口' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\rec5_260808\f_130_slot0_name.png` | 物理伤害 | '国' | '国' | None | treasure |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_015s_技能面板_giveUp证据_slot0_name.png` | 次级箭 | '福7' | '福7' | None | skill |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_015s_技能面板_giveUp证据_slot1_name.png` | 焦点 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_015s_技能面板_giveUp证据_slot2_name.png` | 箭矢齐射 | '7-' | '7-' | None | skill |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_234s_技能面板_slot0_name.png` | 次级增伤 | '福4' | '福4' | None | skill |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_234s_技能面板_slot1_name.png` | 地震 | '兴' | '兴' | None | skill |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_234s_技能面板_slot2_name.png` | 射线增幅 | 'C' | 'C' | None | skill |
| `fixtures\ocr_choices\skill\live_postgame_20260808\live_skill_choice_slot0_name.png` | 射线增幅 | '福C' | '福C' | None | skill |
| `fixtures\ocr_choices\skill\live_postgame_20260808\live_skill_choice_slot1_name.png` | 奥术激光 | 'X' | 'X' | None | skill |
| `fixtures\ocr_choices\skill\live_postgame_20260808\live_skill_choice_slot2_name.png` | 剑气 | 'C星' | 'C星' | None | skill |
| `fixtures\ocr_choices\skill\reborn_wow_screens_20260806\skill_choice_3_slot0_name.png` | 陨石 | '福' | '福' | None | skill |
| `fixtures\ocr_choices\skill\reborn_wow_screens_20260806\skill_choice_3_slot1_name.png` | 次级箭 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\reborn_wow_screens_20260806\skill_choice_3_slot2_name.png` | 地震 | '' | '' | None | skill |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot0_name.png` | 乱世三国 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot1_name.png` | 体魄 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot2_name.png` | 攻击提升 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot0_name.png` | 修仙 | '」2' | '」2' | None | bond |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot1_name.png` | 魔术 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot2_name.png` | 封神 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot0_name.png` | 智力祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot1_name.png` | 敏捷祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot2_name.png` | 力量祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot0_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot1_name.png` | 六星球 | '?' | '?' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot2_name.png` | 物理伤害 | 'M' | 'M' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot0_name.png` | 攻坚 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot1_name.png` | 四星球 | '?' | '?' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot2_name.png` | 奥术神符 | '-' | '-' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot0_name.png` | 攻坚 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot1_name.png` | 四星球 | '?' | '?' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot2_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot0_name.png` | 攻坚 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot1_name.png` | 四星球 | '?' | '?' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot2_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\reborn_wow_screens_20260806\treasure_choice_3_slot0_name.png` | 贪婪献祭 | '福' | '福' | None | treasure |
| `fixtures\ocr_choices\treasure\reborn_wow_screens_20260806\treasure_choice_3_slot1_name.png` | 卡牌大师 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\reborn_wow_screens_20260806\treasure_choice_3_slot2_name.png` | 双倍神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot0_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot1_name.png` | 六星球 | '-' | '-' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot2_name.png` | 物理伤害 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-ef3f2be8fc5d1103_slot0_name.png` | 攻坚 | '福' | '福' | None | treasure |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-ef3f2be8fc5d1103_slot1_name.png` | 四星球 | '-' | '-' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-ef3f2be8fc5d1103_slot2_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\skill\rec3_260810\f_008_slot1_name.png` | 电磁网 | 'R' | 'R' | None | skill |
| `fixtures\ocr_choices\skill\rec3_260810\f_008_slot2_name.png` | 冰霜新星 | '' | '' | None | skill |
| `fixtures\ocr_choices\bond\rec3_260810\f_015_slot0_name.png` | 敏捷祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec3_260810\f_015_slot1_name.png` | 智力祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec3_260810\f_015_slot2_name.png` | 力量祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\treasure\rec3_260810\f_021_slot0_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec3_260810\f_046_slot0_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\skill\rec5_260808\f_010_slot2_name.png` | 箭矢齐射 | '7' | '7' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_024_slot0_name.png` | 天雷 | '福不' | '福不' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_024_slot1_name.png` | 焦点 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_027_slot0_name.png` | 飓风 | '福' | '福' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_027_slot1_name.png` | 陨石 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_027_slot2_name.png` | 电磁网 | 'R' | 'R' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_042_slot0_name.png` | 射线增幅 | '福C' | '福C' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_042_slot1_name.png` | 奥术激光 | 'X' | 'X' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_042_slot2_name.png` | 剑气 | 'CF' | 'CF' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_043_slot1_name.png` | 天雷 | '五' | '五' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_044_slot0_name.png` | 飓风 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_044_slot1_name.png` | 次级箭 | 'Z' | 'Z' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_045_slot0_name.png` | 爆炎箭 | '福D' | '福D' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_083_slot0_name.png` | 闪电链 | '福国' | '福国' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_083_slot1_name.png` | 飓风 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_083_slot2_name.png` | 地震 | '兴' | '兴' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_174_slot1_name.png` | 射线增幅 | '' | '' | None | skill |
| `fixtures\ocr_choices\bond\rec5_260808\f_030_slot0_name.png` | 力量祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_030_slot1_name.png` | 敏捷祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_030_slot2_name.png` | 乱世三国 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_031_slot0_name.png` | 敏捷祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_033_slot0_name.png` | 敏捷祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_034_slot0_name.png` | 敏捷祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_035_slot0_name.png` | 敏捷祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\treasure\rec5_260808\f_112_slot0_name.png` | 六星球 | '口' | '口' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\rec5_260808\f_130_slot0_name.png` | 物理伤害 | '国' | '国' | None | treasure |

### 6.2 误归一样本（词典外→配置名，门禁必须为 0；实测 0）

（无）

### 6.3 套装进度错例

| crop | 真值 | OCR raw | 归一化 |
|---|---|---|---|
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot1_progress.png` | 0/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot2_progress.png` | 1/4 | '' | '' |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot1_progress.png` | 0/2 | '' | '' |
| `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot0_progress.png` | 0/3 | '，' | ',' |
| `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot1_progress.png` | 0/3 | '，' | ',' |
| `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot2_progress.png` | 0/3 | '，' | ',' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot1_progress.png` | 0/7 | '每秒木春表[0)' | '每秒木春表[0)' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot2_progress.png` | 0/2 | '' | '' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot0_progress.png` | 0/2 | '，我外上' | ',我外上' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot1_progress.png` | 1/7 | '英雄卡[177)' | '英雄卡[177)' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot0_progress.png` | 0/2 | '' | '' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot1_progress.png` | 1/7 | '英雄卡[117' | '英雄卡[117' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot0_progress.png` | 0/2 | '' | '' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot1_progress.png` | 1/7 | '英维卡套[117' | '英维卡套[117' |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot1_progress.png` | 0/7 | '套装[0' | '套装[0' |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot2_progress.png` | 0/2 | '' | '' |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-ef3f2be8fc5d1103_slot0_progress.png` | 0/2 | '大人' | '大人' |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-ef3f2be8fc5d1103_slot1_progress.png` | 1/7 | '套I[17' | '套I[17' |
| `fixtures\ocr_choices\bond\rec3_260810\f_015_slot0_progress.png` | 0/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec3_260810\f_015_slot1_progress.png` | 0/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec3_260810\f_015_slot2_progress.png` | 0/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_030_slot0_progress.png` | 1/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_030_slot1_progress.png` | 1/3 | '，、' | ',、' |
| `fixtures\ocr_choices\bond\rec5_260808\f_031_slot0_progress.png` | 2/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_031_slot1_progress.png` | 0/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_031_slot2_progress.png` | 0/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_033_slot0_progress.png` | 2/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_033_slot1_progress.png` | 0/3 | '大，开' | '大,开' |
| `fixtures\ocr_choices\bond\rec5_260808\f_033_slot2_progress.png` | 0/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_034_slot0_progress.png` | 2/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_034_slot1_progress.png` | 0/3 | '格游' | '格游' |
| `fixtures\ocr_choices\bond\rec5_260808\f_034_slot2_progress.png` | 0/3 | '大开' | '大开' |
| `fixtures\ocr_choices\bond\rec5_260808\f_035_slot0_progress.png` | 2/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_035_slot1_progress.png` | 1/3 | '的，' | '的,' |
| `fixtures\ocr_choices\bond\rec5_260808\f_035_slot2_progress.png` | 1/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_039_slot0_progress.png` | 1/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_039_slot2_progress.png` | 1/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_041_slot0_progress.png` | 2/4 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_041_slot2_progress.png` | 0/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_050_slot0_progress.png` | 3/4 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_050_slot1_progress.png` | 0/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_050_slot2_progress.png` | 0/2 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_051_slot0_progress.png` | 0/2 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_051_slot2_progress.png` | 0/3 | '，' | ',' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_017_slot1_progress.png` | 0/3 | '' | '' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_018_slot1_progress.png` | 0/3 | '，' | ',' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_018_slot2_progress.png` | 0/4 | '，' | ',' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_020_slot0_progress.png` | 0/2 | '' | '' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_020_slot1_progress.png` | 0/4 | '' | '' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_020_slot2_progress.png` | 0/4 | '，' | ',' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_053_slot1_progress.png` | 0/3 | '请' | '请' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_112_slot0_progress.png` | 0/7 | '不' | '不' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_112_slot1_progress.png` | 0/3 | '，' | ',' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_112_slot2_progress.png` | 1/2 | '四' | '四' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_130_slot0_progress.png` | 0/2 | '' | '' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_130_slot1_progress.png` | 0/7 | '的-10' | '的-10' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_162_slot2_progress.png` | 1/7 | '为' | '为' |

### 6.4 OCR-raw 词级错误（raw 变体，rec_text ≠ raw_text）

共 258 条（全部样本见同名 JSON）
- `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_015s_技能面板_giveUp证据_slot0_name.png`：真值 '次级箭' → OCR '福7'（score=0.2336，lookup=None）
- `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_015s_技能面板_giveUp证据_slot1_name.png`：真值 '焦点' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_015s_技能面板_giveUp证据_slot2_name.png`：真值 '箭矢齐射' → OCR '7-'（score=0.4017，lookup=None）
- `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_234s_技能面板_slot0_name.png`：真值 '次级增伤' → OCR '福4'（score=0.1767，lookup=None）
- `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_234s_技能面板_slot1_name.png`：真值 '地震' → OCR '兴'（score=0.0758，lookup=None）
- `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_234s_技能面板_slot2_name.png`：真值 '射线增幅' → OCR 'C'（score=0.2009，lookup=None）
- `fixtures\ocr_choices\skill\live_postgame_20260808\live_skill_choice_slot0_name.png`：真值 '射线增幅' → OCR '福C'（score=0.1127，lookup=None）
- `fixtures\ocr_choices\skill\live_postgame_20260808\live_skill_choice_slot1_name.png`：真值 '奥术激光' → OCR 'X'（score=0.5957，lookup=None）
- `fixtures\ocr_choices\skill\live_postgame_20260808\live_skill_choice_slot2_name.png`：真值 '剑气' → OCR 'C星'（score=0.37，lookup=None）
- `fixtures\ocr_choices\skill\reborn_wow_screens_20260806\skill_choice_3_slot0_name.png`：真值 '陨石' → OCR '福'（score=0.0586，lookup=None）
- `fixtures\ocr_choices\skill\reborn_wow_screens_20260806\skill_choice_3_slot1_name.png`：真值 '次级箭' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\skill\reborn_wow_screens_20260806\skill_choice_3_slot2_name.png`：真值 '地震' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot0_name.png`：真值 '乱世三国' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot1_name.png`：真值 '体魄' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot2_name.png`：真值 '攻击提升' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot0_name.png`：真值 '修仙' → OCR '」2'（score=0.1764，lookup=None）
- `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot1_name.png`：真值 '魔术' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot2_name.png`：真值 '封神' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot0_name.png`：真值 '智力祝福' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot1_name.png`：真值 '敏捷祝福' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot2_name.png`：真值 '力量祝福' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot0_name.png`：真值 '奥术神符' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot1_name.png`：真值 '六星球' → OCR '?'（score=0.1965，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot2_name.png`：真值 '物理伤害' → OCR 'M'（score=0.3807，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot0_name.png`：真值 '攻坚' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot1_name.png`：真值 '四星球' → OCR '?'（score=0.2331，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot2_name.png`：真值 '奥术神符' → OCR '-'（score=0.5657，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot0_name.png`：真值 '攻坚' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot1_name.png`：真值 '四星球' → OCR '?'（score=0.1545，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot2_name.png`：真值 '奥术神符' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot0_name.png`：真值 '攻坚' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot1_name.png`：真值 '四星球' → OCR '?'（score=0.1925，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot2_name.png`：真值 '奥术神符' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\treasure\reborn_wow_screens_20260806\treasure_choice_3_slot0_name.png`：真值 '贪婪献祭' → OCR '福'（score=0.1218，lookup=None）
- `fixtures\ocr_choices\treasure\reborn_wow_screens_20260806\treasure_choice_3_slot1_name.png`：真值 '卡牌大师' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\treasure\reborn_wow_screens_20260806\treasure_choice_3_slot2_name.png`：真值 '双倍神符' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot0_name.png`：真值 '奥术神符' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot1_name.png`：真值 '六星球' → OCR '-'（score=0.1649，lookup=None）
- `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot2_name.png`：真值 '物理伤害' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-ef3f2be8fc5d1103_slot0_name.png`：真值 '攻坚' → OCR '福'（score=0.0636，lookup=None）

## 7. 词典覆盖缺口（B2-3 跟进项）

- `七星球` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `五星球` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `伯邑考` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `全能神符` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `力之极` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `力量提升` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `压制` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `奥术增幅α` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `奥术增幅β` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `奥术激光` ×4：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `射线延续` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `属性神符` ×8：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `巨龙军团` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `强力箭矢` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `挑战杀手` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `控符大师` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `敏捷提升` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `智力提升` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `暴怒神符` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `杀敌多多` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `极速神符` ×6：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `气势` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `法师奥义` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `法术增幅` ×4：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `法术威力` ×4：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `流星泪` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `激光增幅` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `灵智` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `焦点爆破` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `燃烧的远征` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `爆炸增伤` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `瓦解光线` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `百宝箱` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `箭矢增幅` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `箭矢扩散` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `箭矢连发` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `精英杀手` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `经验(中)` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `经验多多` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `藏宝图(三)` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `蛮舞者` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `调焦` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `赏金神符` ×4：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `透支力量` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `金币猎人` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `魔法权杖` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
- `魔爆能量` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
