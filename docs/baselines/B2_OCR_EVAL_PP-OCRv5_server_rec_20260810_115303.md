# B2-2 离线 OCR 评测报告（PP-OCRv5 mobile rec-only）

> 生成时间：2026-08-10T11:53:03
> 模型：PP-OCRv5_server_rec（本地固定版本，SHA256 见 `models/ocr/MODEL_MANIFEST.json`）
> 数据：44 valid slots / 15 面板 / 18 套装进度槽
> 预处理对比：原图 vs 2x lanczos + contrast 1.5
> 机器：i5-13600KF / Windows 10 / CPU（10 threads，device=cpu）

## 1. 门禁结果（生产候选变体 = raw）

| 门禁 | 阈值 | 实测 | 结论 |
|---|---:|---:|---|
| canonical_top1_accuracy | 0.95 | 0.0455 | FAIL |
| lexicon_recall | 0.99 | 0.0455 | FAIL |
| mis_normalization | 0 | 0 | PASS |
| set_progress_accuracy | 0.95 | 0.0 | FAIL |
| panel3_cpu_p95 | 300.0 | 5620.3 | FAIL |
| single_cpu_p95 | 120.0 | 2020.7 | FAIL |
| rss_delta | 800.0 | 615.0 | PASS |
| offline_inference | 1.0 | 1.0 | PASS |
| model_sha256_recorded | 1.0 | 1.0 | PASS |

**总体：存在 FAIL，见下**

## 2. OCR-raw 报告层（不设门禁，仅报告）

| 变体 | 字符准确率 | 词准确率(对 raw_text) | 词准确率(对规范名) |
|---|---:|---:|---:|
| raw | 4.55% | 4.55% | 4.55% |
| pre | 4.55% | 4.55% | 4.55% |

## 3. lexicon-gated 生产门禁层

### 变体 raw

- 词典内槽位（含别名覆盖）：88，词典外：0
- 规范名 Top-1（严格）：4/86 = 4.65%
- 规范名 Top-1（别名感知）：4/88 = 4.55%
- 词典召回（别名感知）：4.55%（88 槽）
- 技能词典召回（严格）：15.38%（26 槽）
- 误归一（词典外→配置名）：**0**（词典外正确置 None：0）

### 变体 pre

- 词典内槽位（含别名覆盖）：88，词典外：0
- 规范名 Top-1（严格）：4/86 = 4.65%
- 规范名 Top-1（别名感知）：4/88 = 4.55%
- 词典召回（别名感知）：4.55%（88 槽）
- 技能词典召回（严格）：15.38%（26 槽）
- 误归一（词典外→配置名）：**0**（词典外正确置 None：0）

### 套装进度 x/y 完全正确率：0.0%（0/18）

## 4. 性能

| 项 | 值 |
|---|---|
| 模型加载时间 | 3.444s |
| 单槽 P50/P95（raw） | 1897.8 / 2020.7 ms |
| 单槽 P50/P95（pre） | 1860.6 / 1908.4 ms |
| 三槽连推 P50/P95（raw） | 5485.8 / 5620.3 ms |
| 三槽连推 P50/P95（pre） | 5465.6 / 5613.1 ms |
| RSS（import/加载后/稳态） | 21.0 / 392.8 / 1007.8 MB |
| RSS 常驻增量 | 615.0 MB |
| 模型目录（仓库） | C:\tmp\ocr_models\PP-OCRv5_server_rec_infer |
| 模型目录（ASCII 暂存） | C:\tmp\ocr_stage_server\PP-OCRv5_server_rec_infer |
| 采样量 | 单槽 88、三槽 30 |

## 5. 断网/离线校验

- 结果：PASS — socket 出站连接全阻断下完成模型加载+推理
- 加载耗时：1.39s；推理耗时：1.714s；识别文本：''

## 6. 错例清单

### 6.1 生产门禁错误（候选变体 raw，词典内 Top-1 错误）

| crop | 真值 | OCR raw | 归一化 | lookup 结果 | 类型 |
|---|---|---|---|---|---|
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_015s_技能面板_giveUp证据_slot0_name.png` | 次级箭 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_015s_技能面板_giveUp证据_slot1_name.png` | 焦点 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_015s_技能面板_giveUp证据_slot2_name.png` | 箭矢齐射 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_234s_技能面板_slot0_name.png` | 次级增伤 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_234s_技能面板_slot1_name.png` | 地震 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_234s_技能面板_slot2_name.png` | 射线增幅 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\live_postgame_20260808\live_skill_choice_slot0_name.png` | 射线增幅 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\live_postgame_20260808\live_skill_choice_slot1_name.png` | 奥术激光 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\live_postgame_20260808\live_skill_choice_slot2_name.png` | 剑气 | '-' | '-' | None | skill |
| `fixtures\ocr_choices\skill\reborn_wow_screens_20260806\skill_choice_3_slot0_name.png` | 陨石 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\reborn_wow_screens_20260806\skill_choice_3_slot1_name.png` | 次级箭 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\reborn_wow_screens_20260806\skill_choice_3_slot2_name.png` | 地震 | '' | '' | None | skill |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot0_name.png` | 乱世三国 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot1_name.png` | 体魄 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot2_name.png` | 攻击提升 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot0_name.png` | 修仙 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot1_name.png` | 魔术 | '國' | '國' | None | bond |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot2_name.png` | 封神 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot0_name.png` | 智力祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot1_name.png` | 敏捷祝福 | '回' | '回' | None | bond |
| `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot2_name.png` | 力量祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot0_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot1_name.png` | 六星球 | '0' | '0' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot2_name.png` | 物理伤害 | '国' | '国' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot0_name.png` | 攻坚 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot1_name.png` | 四星球 | '0' | '0' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot2_name.png` | 奥术神符 | '日' | '日' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot0_name.png` | 攻坚 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot1_name.png` | 四星球 | '国' | '国' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot2_name.png` | 奥术神符 | '日' | '日' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot0_name.png` | 攻坚 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot1_name.png` | 四星球 | '国' | '国' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot2_name.png` | 奥术神符 | '日' | '日' | None | treasure |
| `fixtures\ocr_choices\treasure\reborn_wow_screens_20260806\treasure_choice_3_slot0_name.png` | 贪婪献祭 | '日' | '日' | None | treasure |
| `fixtures\ocr_choices\treasure\reborn_wow_screens_20260806\treasure_choice_3_slot1_name.png` | 卡牌大师 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\reborn_wow_screens_20260806\treasure_choice_3_slot2_name.png` | 双倍神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot0_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot1_name.png` | 六星球 | 'a' | 'a' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot2_name.png` | 物理伤害 | 'N' | 'N' | None | treasure |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-ef3f2be8fc5d1103_slot0_name.png` | 攻坚 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-ef3f2be8fc5d1103_slot1_name.png` | 四星球 | 'a' | 'a' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-ef3f2be8fc5d1103_slot2_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_015s_技能面板_giveUp证据_slot0_name.png` | 次级箭 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_015s_技能面板_giveUp证据_slot1_name.png` | 焦点 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_015s_技能面板_giveUp证据_slot2_name.png` | 箭矢齐射 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_234s_技能面板_slot0_name.png` | 次级增伤 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_234s_技能面板_slot1_name.png` | 地震 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_234s_技能面板_slot2_name.png` | 射线增幅 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\live_postgame_20260808\live_skill_choice_slot0_name.png` | 射线增幅 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\live_postgame_20260808\live_skill_choice_slot1_name.png` | 奥术激光 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\live_postgame_20260808\live_skill_choice_slot2_name.png` | 剑气 | '-' | '-' | None | skill |
| `fixtures\ocr_choices\skill\reborn_wow_screens_20260806\skill_choice_3_slot0_name.png` | 陨石 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\reborn_wow_screens_20260806\skill_choice_3_slot1_name.png` | 次级箭 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\reborn_wow_screens_20260806\skill_choice_3_slot2_name.png` | 地震 | '' | '' | None | skill |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot0_name.png` | 乱世三国 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot1_name.png` | 体魄 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot2_name.png` | 攻击提升 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot0_name.png` | 修仙 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot1_name.png` | 魔术 | '國' | '國' | None | bond |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot2_name.png` | 封神 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot0_name.png` | 智力祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot1_name.png` | 敏捷祝福 | '回' | '回' | None | bond |
| `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot2_name.png` | 力量祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot0_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot1_name.png` | 六星球 | '0' | '0' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot2_name.png` | 物理伤害 | '国' | '国' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot0_name.png` | 攻坚 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot1_name.png` | 四星球 | '0' | '0' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot2_name.png` | 奥术神符 | '日' | '日' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot0_name.png` | 攻坚 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot1_name.png` | 四星球 | '国' | '国' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot2_name.png` | 奥术神符 | '日' | '日' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot0_name.png` | 攻坚 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot1_name.png` | 四星球 | '国' | '国' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot2_name.png` | 奥术神符 | '日' | '日' | None | treasure |
| `fixtures\ocr_choices\treasure\reborn_wow_screens_20260806\treasure_choice_3_slot0_name.png` | 贪婪献祭 | '日' | '日' | None | treasure |
| `fixtures\ocr_choices\treasure\reborn_wow_screens_20260806\treasure_choice_3_slot1_name.png` | 卡牌大师 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\reborn_wow_screens_20260806\treasure_choice_3_slot2_name.png` | 双倍神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot0_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot1_name.png` | 六星球 | 'a' | 'a' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot2_name.png` | 物理伤害 | 'N' | 'N' | None | treasure |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-ef3f2be8fc5d1103_slot0_name.png` | 攻坚 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-ef3f2be8fc5d1103_slot1_name.png` | 四星球 | 'a' | 'a' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-ef3f2be8fc5d1103_slot2_name.png` | 奥术神符 | '' | '' | None | treasure |

### 6.2 误归一样本（词典外→配置名，门禁必须为 0；实测 0）

（无）

### 6.3 套装进度错例

| crop | 真值 | OCR raw | 归一化 |
|---|---|---|---|
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot1_progress.png` | 0/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot2_progress.png` | 1/4 | '' | '' |
| `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot1_progress.png` | 0/2 | '' | '' |
| `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot0_progress.png` | 0/3 | '' | '' |
| `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot1_progress.png` | 0/3 | '' | '' |
| `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot2_progress.png` | 0/3 | '' | '' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot1_progress.png` | 0/7 | '每秒木材17' | '每秒木材17' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot2_progress.png` | 0/2 | '份+1' | '份+1' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot0_progress.png` | 0/2 | '都外获取1分' | '都外获取1分' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot1_progress.png` | 1/7 | '英雄卡*装[17' | '英雄卡*装[17' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot0_progress.png` | 0/2 | '获70' | '获70' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot1_progress.png` | 1/7 | '英卡*套装[17' | '英卡*套装[17' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot0_progress.png` | 0/2 | '获得对量7' | '获得对量7' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot1_progress.png` | 1/7 | '英雄卡套装[117' | '英雄卡套装[117' |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot1_progress.png` | 0/7 | '装[017)' | '装[017)' |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot2_progress.png` | 0/2 | '(0' | '(0' |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-ef3f2be8fc5d1103_slot0_progress.png` | 0/2 | '对' | '对' |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-ef3f2be8fc5d1103_slot1_progress.png` | 1/7 | '套装 [17' | '套装[17' |

### 6.4 OCR-raw 词级错误（raw 变体，rec_text ≠ raw_text）

共 84 条（全部样本见同名 JSON）
- `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_015s_技能面板_giveUp证据_slot0_name.png`：真值 '次级箭' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_015s_技能面板_giveUp证据_slot1_name.png`：真值 '焦点' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_015s_技能面板_giveUp证据_slot2_name.png`：真值 '箭矢齐射' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_234s_技能面板_slot0_name.png`：真值 '次级增伤' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_234s_技能面板_slot1_name.png`：真值 '地震' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_234s_技能面板_slot2_name.png`：真值 '射线增幅' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\skill\live_postgame_20260808\live_skill_choice_slot0_name.png`：真值 '射线增幅' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\skill\live_postgame_20260808\live_skill_choice_slot1_name.png`：真值 '奥术激光' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\skill\live_postgame_20260808\live_skill_choice_slot2_name.png`：真值 '剑气' → OCR '-'（score=0.1442，lookup=None）
- `fixtures\ocr_choices\skill\reborn_wow_screens_20260806\skill_choice_3_slot0_name.png`：真值 '陨石' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\skill\reborn_wow_screens_20260806\skill_choice_3_slot1_name.png`：真值 '次级箭' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\skill\reborn_wow_screens_20260806\skill_choice_3_slot2_name.png`：真值 '地震' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot0_name.png`：真值 '乱世三国' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot1_name.png`：真值 '体魄' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot2_name.png`：真值 '攻击提升' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot0_name.png`：真值 '修仙' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot1_name.png`：真值 '魔术' → OCR '國'（score=0.1463，lookup=None）
- `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot2_name.png`：真值 '封神' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot0_name.png`：真值 '智力祝福' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot1_name.png`：真值 '敏捷祝福' → OCR '回'（score=0.2241，lookup=None）
- `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot2_name.png`：真值 '力量祝福' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot0_name.png`：真值 '奥术神符' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot1_name.png`：真值 '六星球' → OCR '0'（score=0.1391，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot2_name.png`：真值 '物理伤害' → OCR '国'（score=0.132，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot0_name.png`：真值 '攻坚' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot1_name.png`：真值 '四星球' → OCR '0'（score=0.115，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot2_name.png`：真值 '奥术神符' → OCR '日'（score=0.1005，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot0_name.png`：真值 '攻坚' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot1_name.png`：真值 '四星球' → OCR '国'（score=0.1908，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot2_name.png`：真值 '奥术神符' → OCR '日'（score=0.109，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot0_name.png`：真值 '攻坚' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot1_name.png`：真值 '四星球' → OCR '国'（score=0.1401，lookup=None）
- `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot2_name.png`：真值 '奥术神符' → OCR '日'（score=0.0827，lookup=None）
- `fixtures\ocr_choices\treasure\reborn_wow_screens_20260806\treasure_choice_3_slot0_name.png`：真值 '贪婪献祭' → OCR '日'（score=0.2347，lookup=None）
- `fixtures\ocr_choices\treasure\reborn_wow_screens_20260806\treasure_choice_3_slot1_name.png`：真值 '卡牌大师' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\treasure\reborn_wow_screens_20260806\treasure_choice_3_slot2_name.png`：真值 '双倍神符' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot0_name.png`：真值 '奥术神符' → OCR ''（score=0.0，lookup=None）
- `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot1_name.png`：真值 '六星球' → OCR 'a'（score=0.2286，lookup=None）
- `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot2_name.png`：真值 '物理伤害' → OCR 'N'（score=0.0498，lookup=None）
- `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-ef3f2be8fc5d1103_slot0_name.png`：真值 '攻坚' → OCR ''（score=0.0，lookup=None）

## 7. 词典覆盖缺口（B2-3 跟进项）

- `奥术激光` ×2：不在 config/choice_lexicon.json，该槽生产 Top-1 必然失败（词典补录后可恢复）。
