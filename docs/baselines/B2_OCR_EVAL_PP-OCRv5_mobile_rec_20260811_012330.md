# B2-2 离线 OCR 评测报告（PP-OCRv5 mobile rec-only，O0/O1 可信度口径）

> 生成时间：2026-08-11T01:23:30
> repo HEAD：897661088b10f154887f4157ddf37ba837c4ca28（branch=codex/ocr-hybrid，dirty=True）
> 模型：PP-OCRv5_mobile_rec（MODEL_MANIFEST.json，hash gate 实测见 §0）
> 数据：155 独立 valid slots / 52 面板 / 69 套装进度槽 / 17 unknown 槽 / 0 unverified_layout 槽（不进分母）
> 预处理对比：原图 vs 2x lanczos + contrast 1.5
> 机器：i5-13600KF / Windows 10 / CPU（10 threads，device=cpu）

## 0. 模型完整性门禁（真实 SHA256/大小校验）

- manifest 文件：`C:\Users\10639\Desktop\🎮 影音游戏\GameScript-Local\models\ocr\MODEL_MANIFEST.json`（schema 2，entry=PP-OCRv5_mobile_rec_infer）
- 结果：PASS

| 文件 | 大小(字节) | SHA256 | 校验 |
|---|---|---|---|
| inference.json | 217724 | 24587345250C7332… | PASS |
| inference.pdiparams | 16458665 | 2460DA90875937C9… | PASS |
| inference.yml | 148345 | 5DFEB2777F6D0DB8… | PASS |

## 1. 门禁结果（生产候选变体 = raw）

| 门禁 | 阈值 | 实测 | 结论 |
|---|---:|---:|---|
| canonical_top1_accuracy | 0.95 | 0.0145 | FAIL |
| lexicon_recall | 0.99 | 0.0145 | FAIL |
| mis_normalization | 0 | 0 | PASS |
| set_progress_accuracy | 0.95 | 0.0 | FAIL |
| panel3_cpu_p95 | 300.0 | 82.3 | PASS |
| single_cpu_p95 | 120.0 | 26.3 | PASS |
| rss_delta | 800.0 | 55.0 | PASS |
| offline_inference | 1.0 | 1.0 | PASS |
| model_hash_verified | manifest sha256+size per file (repo + staged) | True | PASS |
| repo_head_recorded | non-empty git rev-parse HEAD | 897661088b10f154887f4157ddf37ba837c4ca28 | PASS |
| negative_panels_zero_suggestions | 每负面板 suggestion_count == 0 | 37/37 | PASS |

**总体：存在 FAIL，见下**

## 2. OCR-raw 报告层（round-0 唯一槽位口径，不设门禁）

| 变体 | 槽位数 | 字符准确率 | 词准确率(对 raw_text) | 词准确率(对规范名) |
|---|---:|---:|---:|---:|
| raw | 155 | 1.29% | 1.29% | 8.39% |
| pre | 155 | 1.29% | 1.29% | 9.03% |

稳定性（raw 变体 round0 vs round1 文本一致率）：100.0%（155/155 槽）

## 3. lexicon-gated 生产门禁层

### 变体 raw

- 词典内槽位（含别名覆盖，布局已验证）：138，其中严格词典内 136；词典外(unknown)：17；unverified_layout 剔除：0
- 规范名 Top-1（严格）：2/136 = 1.47%
- 规范名 Top-1（别名感知）：2/138 = 1.45%
- 词典召回（别名感知）：1.45%（138 槽）
- 技能词典召回（严格）：4.44%（45 槽）
- 误归一（词典外→配置名）：**0**（词典外正确置 None：17）

#### 逐 session 指标（round-0 唯一槽位口径）

| session | 词典内槽 | Top-1 命中 | Top-1 | unknown | unverified | 面板数 |
|---|---:|---:|---:|---:|---:|---|
| dragonball_webp_20260807 | 6 | 0 | 0.0% | 0 | 0 | 2 |
| live_postgame_20260808 | 3 | 0 | 0.0% | 0 | 0 | 1 |
| reborn_wow_screens_20260806 | 9 | 0 | 0.0% | 0 | 0 | 3 |
| rec1_ingame_boss_20260809 | 26 | 2 | 7.69% | 0 | 0 | 9 |
| rec3_260810 | 12 | 0 | 0.0% | 0 | 0 | 4 |
| rec5_260808 | 76 | 0 | 0.0% | 11 | 0 | 26 |
| rec7_short2_20260808 | 6 | 0 | 0.0% | 6 | 0 | 2 |

### 变体 pre

- 词典内槽位（含别名覆盖，布局已验证）：138，其中严格词典内 136；词典外(unknown)：17；unverified_layout 剔除：0
- 规范名 Top-1（严格）：2/136 = 1.47%
- 规范名 Top-1（别名感知）：2/138 = 1.45%
- 词典召回（别名感知）：1.45%（138 槽）
- 技能词典召回（严格）：4.44%（45 槽）
- 误归一（词典外→配置名）：**0**（词典外正确置 None：17）

#### 逐 session 指标（round-0 唯一槽位口径）

| session | 词典内槽 | Top-1 命中 | Top-1 | unknown | unverified | 面板数 |
|---|---:|---:|---:|---:|---:|---|
| dragonball_webp_20260807 | 6 | 0 | 0.0% | 0 | 0 | 2 |
| live_postgame_20260808 | 3 | 0 | 0.0% | 0 | 0 | 1 |
| reborn_wow_screens_20260806 | 9 | 0 | 0.0% | 0 | 0 | 3 |
| rec1_ingame_boss_20260809 | 26 | 2 | 7.69% | 0 | 0 | 9 |
| rec3_260810 | 12 | 0 | 0.0% | 0 | 0 | 4 |
| rec5_260808 | 76 | 0 | 0.0% | 11 | 0 | 26 |
| rec7_short2_20260808 | 6 | 0 | 0.0% | 6 | 0 | 2 |

### 套装进度 x/y 完全正确率：0.0%（0/69）

## 4. 性能

| 项 | 值 |
|---|---|
| 模型加载时间 | 1.483s |
| 单槽 P50/P95（raw） | 20.9 / 26.3 ms |
| 单槽 P50/P95（pre） | 21.8 / 26.9 ms |
| 三槽连推 P50/P95（raw） | 64.4 / 82.3 ms |
| 三槽连推 P50/P95（pre） | 68.3 / 90.3 ms |
| RSS（import/加载后/稳态） | 43.7 / 317.8 / 372.9 MB |
| RSS 常驻增量 | 55.0 MB |
| 模型目录（仓库） | C:\Users\10639\Desktop\🎮 影音游戏\GameScript-Local\models\ocr\PP-OCRv5_mobile_rec_infer |
| 模型目录（ASCII 暂存） | C:\Users\10639\AppData\Local\Temp\gamescript_ocr_stage\PP-OCRv5_mobile_rec_infer |
| 采样量 | 单槽 310、三槽 104（2 轮，仅 latency） |

## 5. 断网/离线校验

- 结果：PASS — socket 出站连接全阻断下完成模型加载+推理
- 加载耗时：0.453s；推理耗时：0.042s；识别文本：'福7'

## 5b. 负面板 触发/分类/建议 链（期望建议数 = 0）

- 通过：37/37

| 面板 | 分辨率 | 原因 | 触发 | 锚点模板 | 分类 | 建议数 | 结论 |
|---|---:|---|---|---|---:|---|
| neg_rec2_postgame_exit_20260809_t_000s_loading | 1586x892 | 加载画面 | 否 | - | - | 0 | PASS |
| neg_rec1_ingame_boss_20260809_t_000s_开局 | 1600x900 | 局内 HUD（开局准备） | 否 | - | - | 0 | PASS |
| neg_rec2_postgame_exit_20260809_t_001s_victory | 1586x892 | 胜利结算页 | 否 | - | - | 0 | PASS |
| neg_rec1_ingame_boss_20260809_t_003s_局内HUD | 1600x900 | 局内 HUD（主线任务栏） | 否 | - | - | 0 | PASS |
| neg_rec2_postgame_exit_20260809_t_003s_stage_select_archive_panel | 1586x892 | 选关页+存档挑战入口 | 否 | - | - | 0 | PASS |
| neg_rec1_ingame_boss_20260809_t_006s_面板底部按钮 | 1600x900 | 局内 HUD（准备阶段） | 否 | - | - | 0 | PASS |
| neg_rec2_postgame_exit_20260809_t_010s_stage_select_hover | 1586x892 | 选关页 | 否 | - | - | 0 | PASS |
| neg_rec2_postgame_exit_20260809_t_020s_ingame_boss_mengmo | 1586x892 | Boss 战（梦魔之王，倒计时悬浮条） | 否 | - | - | 0 | PASS |
| neg_rec2_postgame_exit_20260809_t_022s_chuanjiabao_panel | 1586x892 | 传家宝挑战弹窗（4 Boss 图标） | 否 | - | - | 0 | PASS |
| neg_rec2_postgame_exit_20260809_t_023s_ingame_npc_arrow | 1586x892 | 局内 HUD（NPC 箭头） | 否 | - | - | 0 | PASS |
| neg_rec2_postgame_exit_20260809_t_024s_chuanjiabao_panel_2 | 1586x892 | 传家宝挑战弹窗 2 | 否 | - | - | 0 | PASS |
| neg_rec2_postgame_exit_20260809_t_027s_ingame_boss_click | 1586x892 | Boss 战点击 | 否 | - | - | 0 | PASS |
| neg_rec2_postgame_exit_20260809_t_027s_STAGESELECT疑似面板 | 1600x900 | 局内 HUD（主线任务栏/聊天文本，曾被误判选关页） | 否 | - | - | 0 | PASS |
| neg_rec2_postgame_exit_20260809_t_039s_exit_confirm | 1586x892 | 退出确认弹窗 | 否 | - | - | 0 | PASS |
| neg_rec2_postgame_exit_20260809_t_041s_ingame_after_cancel | 1586x892 | 局内 HUD（取消退出后） | 否 | - | - | 0 | PASS |
| neg_rec1_ingame_boss_20260809_t_120s_STAGESELECT疑似面板 | 1600x900 | 局内 HUD（主线任务栏/聊天文本，曾被误判选关页） | 否 | - | - | 0 | PASS |
| neg_rec1_ingame_boss_20260809_t_303s_STAGESELECT疑似面板 | 1600x900 | 局内 HUD（主线任务栏/聊天文本，曾被误判选关页） | 否 | - | - | 0 | PASS |
| neg_rec1_ingame_boss_20260809_t_414s_最后STAGESELECT | 1600x900 | 局内 HUD（主线任务栏/聊天文本，曾被误判选关页） | 否 | - | - | 0 | PASS |
| neg_rec2_postgame_exit_20260809_t_008 | 1586x892 | 存档挑战弹窗（时光之穴选择） | 否 | - | - | 0 | PASS |
| neg_rec2_postgame_exit_20260809_t_014 | 1586x892 | 存档挑战弹窗+战利品/聊天文本 | 否 | - | - | 0 | PASS |
| neg_rec2_postgame_exit_20260809_t_026 | 1586x892 | 传家宝挑战弹窗（掉落详情） | 否 | - | - | 0 | PASS |
| neg_rec2_postgame_exit_20260809_t_032 | 1586x892 | Boss 战（克雷什之父） | 否 | - | - | 0 | PASS |
| neg_rec2_postgame_exit_20260809_t_038 | 1586x892 | 局内 HUD（安全区地图） | 否 | - | - | 0 | PASS |
| neg_live_e2e_20260807_20_t9_1968096 | 960x540 | 加载画面（960x540） | 否 | - | - | 0 | PASS |
| neg_live_e2e_20260807_watch_78_1968096_1600x900 | 1600x900 | 选关页（大厅） | 否 | - | - | 0 | PASS |
| neg_live_e2e_20260807_03_dialog | 584x488 | 创建房间对话框（584x488） | 否 | - | - | 0 | PASS |
| neg_live_e2e_20260807_10_room | 1224x904 | 房间等待页（1224x904） | 否 | - | - | 0 | PASS |
| neg_live_postgame_20260808_live_exit_confirm | 1600x900 | 退出确认弹窗 | 否 | - | - | 0 | PASS |
| neg_live_postgame_20260808_live_archive_panel | 1616x939 | 局内安全区 HUD | 否 | - | - | 0 | PASS |
| neg_live_postgame_20260808_live_stage_select | 1600x900 | 选关页 | 否 | - | - | 0 | PASS |
| neg_live_postgame_20260808_live_fullscreen | 1920x1080 | 局内全屏（1920x1080） | 否 | - | - | 0 | PASS |
| neg_reborn_wow_screens_20260806_great_rift_confirm | 1602x933 | 大裂隙确认弹窗 | 否 | - | - | 0 | PASS |
| neg_reborn_wow_screens_20260806_heirloom_challenge_bosses | 1597x929 | 传家宝挑战 Boss 选择 | 否 | - | - | 0 | PASS |
| neg_legacy_fixtures_black_frame | 1600x900 | 黑帧 | 否 | - | - | 0 | PASS |
| neg_legacy_fixtures_frozen_frame | 1600x900 | 冻结帧 | 否 | - | - | 0 | PASS |
| neg_legacy_fixtures_unknown_page | 1600x900 | 未知页面 | 否 | - | - | 0 | PASS |
| neg_legacy_fixtures_assistant_window_neg | 800x600 | 助手窗口（非游戏页） | 否 | - | - | 0 | PASS |

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
| `fixtures\ocr_choices\skill\rec3_260810\f_008_slot0_name.png` | 箭矢连发 | '7' | '7' | None | skill |
| `fixtures\ocr_choices\skill\rec3_260810\f_008_slot1_name.png` | 电磁网 | 'R' | 'R' | None | skill |
| `fixtures\ocr_choices\skill\rec3_260810\f_008_slot2_name.png` | 冰霜新星 | '' | '' | None | skill |
| `fixtures\ocr_choices\bond\rec3_260810\f_015_slot0_name.png` | 敏捷祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec3_260810\f_015_slot1_name.png` | 智力祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec3_260810\f_015_slot2_name.png` | 力量祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\treasure\rec3_260810\f_021_slot0_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec3_260810\f_021_slot1_name.png` | 极速神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec3_260810\f_021_slot2_name.png` | 赏金神符 | '8' | '8' | None | treasure |
| `fixtures\ocr_choices\treasure\rec3_260810\f_046_slot0_name.png` | 奥术神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec3_260810\f_046_slot1_name.png` | 极速神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec3_260810\f_046_slot2_name.png` | 赏金神符 | '福' | '福' | None | treasure |
| `fixtures\ocr_choices\skill\rec5_260808\f_010_slot0_name.png` | 奥术增幅β | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_010_slot1_name.png` | 箭矢增幅 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_010_slot2_name.png` | 箭矢齐射 | '7' | '7' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_024_slot0_name.png` | 天雷 | '福不' | '福不' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_024_slot1_name.png` | 焦点 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_024_slot2_name.png` | 强力箭矢 | '7' | '7' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_027_slot0_name.png` | 飓风 | '福' | '福' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_027_slot1_name.png` | 陨石 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_027_slot2_name.png` | 电磁网 | 'R' | 'R' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_042_slot0_name.png` | 射线增幅 | '福C' | '福C' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_042_slot1_name.png` | 奥术激光 | 'X' | 'X' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_042_slot2_name.png` | 剑气 | 'CF' | 'CF' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_043_slot0_name.png` | 爆炸增伤 | '福7' | '福7' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_043_slot1_name.png` | 天雷 | '五' | '五' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_043_slot2_name.png` | 焦点爆破 | 'C' | 'C' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_044_slot0_name.png` | 飓风 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_044_slot1_name.png` | 次级箭 | 'Z' | 'Z' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_044_slot2_name.png` | 调焦 | 'C' | 'C' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_045_slot0_name.png` | 爆炎箭 | '福D' | '福D' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_045_slot1_name.png` | 奥术增幅α | 'X' | 'X' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_045_slot2_name.png` | 射线延续 | 'C' | 'C' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_083_slot0_name.png` | 闪电链 | '福国' | '福国' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_083_slot1_name.png` | 飓风 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_083_slot2_name.png` | 地震 | '兴' | '兴' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_174_slot0_name.png` | 瓦解光线 | '福X' | '福X' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_174_slot1_name.png` | 射线增幅 | '' | '' | None | skill |
| `fixtures\ocr_choices\skill\rec5_260808\f_174_slot2_name.png` | 激光增幅 | 'X星' | 'X星' | None | skill |
| `fixtures\ocr_choices\bond\rec5_260808\f_030_slot0_name.png` | 力量祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_030_slot1_name.png` | 敏捷祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_030_slot2_name.png` | 乱世三国 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_031_slot0_name.png` | 敏捷祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_031_slot1_name.png` | 法师奥义 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_031_slot2_name.png` | 法术威力 | '-' | '-' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_033_slot0_name.png` | 敏捷祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_033_slot1_name.png` | 藏宝图(三) | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_033_slot2_name.png` | 箭矢扩散 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_034_slot0_name.png` | 敏捷祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_034_slot1_name.png` | 经验多多 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_034_slot2_name.png` | 流星泪 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_035_slot0_name.png` | 敏捷祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_035_slot1_name.png` | 杀敌多多 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_035_slot2_name.png` | 法术增幅 | '🔥' | '🔥' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_039_slot0_name.png` | 法术威力 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_039_slot1_name.png` | 巨龙军团 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_039_slot2_name.png` | 法术增幅 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_041_slot0_name.png` | 敏捷提升 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_041_slot1_name.png` | 燃烧的远征 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_041_slot2_name.png` | 气势 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_050_slot0_name.png` | 力量提升 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_050_slot1_name.png` | 金币猎人 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_050_slot2_name.png` | 魔法权杖 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_051_slot0_name.png` | 魔爆能量 | '💯' | '💯' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_051_slot1_name.png` | 伯邑考 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec5_260808\f_051_slot2_name.png` | 灵智 | '' | '' | None | bond |
| `fixtures\ocr_choices\treasure\rec5_260808\f_017_slot0_name.png` | 极速神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec5_260808\f_017_slot1_name.png` | 挑战杀手 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec5_260808\f_017_slot2_name.png` | 属性神符 | '0' | '0' | None | treasure |
| `fixtures\ocr_choices\treasure\rec5_260808\f_018_slot0_name.png` | 百宝箱 | '日' | '日' | None | treasure |
| `fixtures\ocr_choices\treasure\rec5_260808\f_018_slot1_name.png` | 蛮舞者 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec5_260808\f_018_slot2_name.png` | 属性神符 | '0' | '0' | None | treasure |
| `fixtures\ocr_choices\treasure\rec5_260808\f_020_slot0_name.png` | 经验(中) | '吉园' | '吉园' | None | treasure |
| `fixtures\ocr_choices\treasure\rec5_260808\f_020_slot1_name.png` | 全能神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec5_260808\f_020_slot2_name.png` | 属性神符 | '回' | '回' | None | treasure |
| `fixtures\ocr_choices\treasure\rec5_260808\f_053_slot0_name.png` | 力之极 | '日' | '日' | None | treasure |
| `fixtures\ocr_choices\treasure\rec5_260808\f_053_slot1_name.png` | 精英杀手 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec5_260808\f_053_slot2_name.png` | 控符大师 | 'D' | 'D' | None | treasure |
| `fixtures\ocr_choices\treasure\rec5_260808\f_112_slot0_name.png` | 六星球 | '口' | '口' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\rec5_260808\f_112_slot1_name.png` | 智力提升 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec5_260808\f_112_slot2_name.png` | 压制 | '口' | '口' | None | treasure |
| `fixtures\ocr_choices\treasure\rec5_260808\f_130_slot0_name.png` | 物理伤害 | '国' | '国' | None | treasure |
| `fixtures\ocr_choices\treasure\rec5_260808\f_130_slot1_name.png` | 七星球 | '0' | '0' | None | 龙珠 |
| `fixtures\ocr_choices\treasure\rec5_260808\f_130_slot2_name.png` | 透支力量 | '福' | '福' | None | treasure |
| `fixtures\ocr_choices\treasure\rec5_260808\f_162_slot0_name.png` | 属性神符 | 'O' | 'O' | None | treasure |
| `fixtures\ocr_choices\treasure\rec5_260808\f_162_slot1_name.png` | 暴怒神符 | '' | '' | None | treasure |
| `fixtures\ocr_choices\treasure\rec5_260808\f_162_slot2_name.png` | 五星球 | '□' | '□' | None | 龙珠 |
| `fixtures\ocr_choices\bond\rec5_260808\f_232_slot2_name.png` | 燃烧的远征 | '' | '' | None | bond |
| `fixtures\ocr_choices\skill\rec7_short2_20260808\f_022_slot0_name.png` | 天雷 | '不' | '不' | None | skill |
| `fixtures\ocr_choices\skill\rec7_short2_20260808\f_022_slot1_name.png` | 焦点 | 'C' | 'C' | None | skill |
| `fixtures\ocr_choices\skill\rec7_short2_20260808\f_022_slot2_name.png` | 次级增伤 | '7' | '7' | None | skill |
| `fixtures\ocr_choices\bond\rec7_short2_20260808\f_027_slot0_name.png` | 力量祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec7_short2_20260808\f_027_slot1_name.png` | 智力祝福 | '' | '' | None | bond |
| `fixtures\ocr_choices\bond\rec7_short2_20260808\f_027_slot2_name.png` | 敏捷祝福 | '' | '' | None | bond |

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
| `fixtures\ocr_choices\bond\rec5_260808\f_086_slot1_progress.png` | 0/4 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_104_slot0_progress.png` | 0/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_104_slot2_progress.png` | 0/4 | '入相' | '入相' |
| `fixtures\ocr_choices\bond\rec5_260808\f_159_slot0_progress.png` | 0/4 | '中入' | '中入' |
| `fixtures\ocr_choices\bond\rec5_260808\f_159_slot1_progress.png` | 1/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_159_slot2_progress.png` | 0/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec5_260808\f_232_slot0_progress.png` | 0/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec7_short2_20260808\f_027_slot0_progress.png` | 0/3 | '' | '' |
| `fixtures\ocr_choices\bond\rec7_short2_20260808\f_027_slot1_progress.png` | 0/3 | '，分' | ',分' |
| `fixtures\ocr_choices\bond\rec7_short2_20260808\f_027_slot2_progress.png` | 0/3 | '' | '' |
| `fixtures\ocr_choices\treasure\rec7_short2_20260808\f_033_slot2_progress.png` | 0/7 | '，' | ',' |
| `fixtures\ocr_choices\treasure\rec7_short2_20260808\f_034_slot2_progress.png` | 0/7 | '，' | ',' |

### 6.4 OCR-raw 词级错误（raw 变体，rec_text ≠ raw_text）

共 153 条（全部样本见同名 JSON）
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

## 7. 词典覆盖缺口（O1: 已纠正或标 unknown 的槽位）

unknown truth 槽共 17 个，独立计 unknown、不进准确率分母：
- `三星球` ×1
- `二星球` ×1
- `元素之力` ×1
- `利刃` ×1
- `利刃海盗` ×1
- `力量之源` ×3
- `吕岳` ×1
- `射手姿态` ×2
- `恢复神符` ×2
- `海盗劫掠者` ×1
- `白赚海盗` ×1
- `金币(中)` ×2
