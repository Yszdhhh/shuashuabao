# B2-2 离线 OCR 评测报告（PP-OCRv5 mobile rec-only，O0/O1 可信度口径）

> 生成时间：2026-08-11T02:25:03
> repo HEAD：7bb66a3bd27d322054b94cc71cabe979b4e3ee1c（branch=codex/ocr-hybrid，dirty=True）
> 模型：PP-OCRv5_mobile_rec（MODEL_MANIFEST.json，hash gate 实测见 §0）
> 数据：155 独立 valid slots / 52 面板 / 21 套装进度槽 / 17 unknown 槽 / 0 unverified_layout 槽（不进分母）
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

## 1. 门禁结果（生产候选变体 = pre）

| 门禁 | 阈值 | 实测 | 结论 |
|---|---:|---:|---|
| canonical_top1_accuracy | 0.95 | 0.8913 | FAIL |
| lexicon_recall | 0.99 | 0.8913 | FAIL |
| mis_normalization | 0 | 3 | FAIL |
| set_progress_accuracy | 0.95 | 0.9524 | PASS |
| panel3_cpu_p95 | 300.0 | 99.2 | PASS |
| single_cpu_p95 | 120.0 | 28.2 | PASS |
| rss_delta | 800.0 | 304.0 | PASS |
| offline_inference | 1.0 | 1.0 | PASS |
| model_hash_verified | manifest sha256+size per file (repo + staged) | True | PASS |
| repo_head_recorded | non-empty git rev-parse HEAD | 7bb66a3bd27d322054b94cc71cabe979b4e3ee1c | PASS |
| negative_panels_zero_suggestions | 每负面板 suggestion_count == 0 | 37/37 | PASS |

**总体：存在 FAIL，见下**

## 2. OCR-raw 报告层（round-0 唯一槽位口径，不设门禁）

| 变体 | 槽位数 | 字符准确率 | 词准确率(对 raw_text) | 词准确率(对规范名) |
|---|---:|---:|---:|---:|
| raw | 155 | 80.03% | 56.77% | 50.97% |
| pre | 155 | 81.03% | 60.0% | 53.55% |

稳定性（raw 变体 round0 vs round1 文本一致率）：100.0%（155/155 槽）

## 3. lexicon-gated 生产门禁层

### 变体 raw

- 词典内槽位（含别名覆盖，布局已验证）：138，其中严格词典内 138；词典外(unknown)：17；unverified_layout 剔除：0
- 规范名 Top-1（严格）：121/138 = 87.68%
- 规范名 Top-1（别名感知）：121/138 = 87.68%
- 词典召回（别名感知）：87.68%（138 槽）
- 技能词典召回（严格）：78.72%（47 槽）
- 误归一（词典外→配置名）：**3**（词典外正确置 None：14）

#### 逐 session 指标（round-0 唯一槽位口径）

| session | 词典内槽 | Top-1 命中 | Top-1 | unknown | unverified | 面板数 |
|---|---:|---:|---:|---:|---:|---|
| dragonball_webp_20260807 | 6 | 6 | 100.0% | 0 | 0 | 2 |
| live_postgame_20260808 | 3 | 3 | 100.0% | 0 | 0 | 1 |
| reborn_wow_screens_20260806 | 9 | 9 | 100.0% | 0 | 0 | 3 |
| rec1_ingame_boss_20260809 | 26 | 22 | 84.62% | 0 | 0 | 9 |
| rec3_260810 | 12 | 9 | 75.0% | 0 | 0 | 4 |
| rec5_260808 | 76 | 66 | 86.84% | 11 | 0 | 26 |
| rec7_short2_20260808 | 6 | 6 | 100.0% | 6 | 0 | 2 |

### 变体 pre

- 词典内槽位（含别名覆盖，布局已验证）：138，其中严格词典内 138；词典外(unknown)：17；unverified_layout 剔除：0
- 规范名 Top-1（严格）：123/138 = 89.13%
- 规范名 Top-1（别名感知）：123/138 = 89.13%
- 词典召回（别名感知）：89.13%（138 槽）
- 技能词典召回（严格）：78.72%（47 槽）
- 误归一（词典外→配置名）：**3**（词典外正确置 None：14）

#### 逐 session 指标（round-0 唯一槽位口径）

| session | 词典内槽 | Top-1 命中 | Top-1 | unknown | unverified | 面板数 |
|---|---:|---:|---:|---:|---:|---|
| dragonball_webp_20260807 | 6 | 6 | 100.0% | 0 | 0 | 2 |
| live_postgame_20260808 | 3 | 3 | 100.0% | 0 | 0 | 1 |
| reborn_wow_screens_20260806 | 9 | 9 | 100.0% | 0 | 0 | 3 |
| rec1_ingame_boss_20260809 | 26 | 22 | 84.62% | 0 | 0 | 9 |
| rec3_260810 | 12 | 10 | 83.33% | 0 | 0 | 4 |
| rec5_260808 | 76 | 67 | 88.16% | 11 | 0 | 26 |
| rec7_short2_20260808 | 6 | 6 | 100.0% | 6 | 0 | 2 |

### 套装进度 x/y 正确率：字符串精确 0.0%（0/21）；x/y 提取（'套装[1/7]'→'1/7'）95.24%（20/21）

## 4. 性能

| 项 | 值 |
|---|---|
| 模型加载时间 | 1.541s |
| 单槽 P50/P95（raw） | 20.2 / 37.5 ms |
| 单槽 P50/P95（pre） | 20.6 / 28.2 ms |
| 三槽连推 P50/P95（raw） | 62.3 / 86.1 ms |
| 三槽连推 P50/P95（pre） | 64.2 / 99.2 ms |
| RSS（import/加载后/稳态） | 43.8 / 317.7 / 621.7 MB |
| RSS 常驻增量 | 304.0 MB |
| 模型目录（仓库） | C:\Users\10639\Desktop\🎮 影音游戏\GameScript-Local\models\ocr\PP-OCRv5_mobile_rec_infer |
| 模型目录（ASCII 暂存） | C:\Users\10639\AppData\Local\Temp\gamescript_ocr_stage\PP-OCRv5_mobile_rec_infer |
| 采样量 | 单槽 310、三槽 104（2 轮，仅 latency） |

## 5. 断网/离线校验

- 结果：PASS — socket 出站连接全阻断下完成模型加载+推理
- 加载耗时：0.48s；推理耗时：0.045s；识别文本：'次级箭'

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

### 6.1 生产门禁错误（候选变体 pre，词典内 Top-1 错误）

| crop | 真值 | OCR raw | 归一化 | lookup 结果 | 类型 |
|---|---|---|---|---|---|
| `rec1_ingame_boss_20260809_t_015s_技能面板_giveUp证据_2_name.png (preprocessed)` | 箭矢齐射 | '箭失卉射' | '箭失卉射' | None | skill |
| `rec1_ingame_boss_20260809_t_036s_羁绊面板_0_name.png (preprocessed)` | 乱世三国 | '世三图' | '世三图' | None | bond |
| `rec1_ingame_boss_20260809_t_036s_羁绊面板_1_name.png (preprocessed)` | 体魄 | '体' | '体' | None | bond |
| `rec1_ingame_boss_20260809_t_417s_转折点_1_name.png (preprocessed)` | 魔术 | '厕术（0/2)' | '厕术(0/2)' | None | bond |
| `rec3_260810_f_008_skill_corrected_0_name.png (preprocessed)` | 箭矢连发 | '失速发' | '失速发' | None | skill |
| `rec3_260810_f_015_bond_corrected_0_name.png (preprocessed)` | 敏捷祝福 | '福' | '福' | None | bond |
| `rec5_260808_f_010_skill_corrected_0_name.png (preprocessed)` | 奥术增幅β | '奥术增幅' | '奥术增幅' | None | skill |
| `rec5_260808_f_027_skill_corrected_0_name.png (preprocessed)` | 飓风 | '风风NEW' | '风风NEW' | None | skill |
| `rec5_260808_f_027_skill_corrected_1_name.png (preprocessed)` | 陨石 | '石NEW' | '石NEW' | None | skill |
| `rec5_260808_f_027_skill_corrected_2_name.png (preprocessed)` | 电磁网 | 'N' | 'N' | None | skill |
| `rec5_260808_f_043_skill_corrected_2_name.png (preprocessed)` | 焦点爆破 | '焦点慢破' | '焦点慢破' | None | skill |
| `rec5_260808_f_044_skill_corrected_0_name.png (preprocessed)` | 飓风 | '风 NEW' | '风NEW' | None | skill |
| `rec5_260808_f_045_skill_corrected_1_name.png (preprocessed)` | 奥术增幅α | '长箭 NEW奥术增幅' | '长箭NEW奥术增幅' | None | skill |
| `rec5_260808_f_083_skill_corrected_1_name.png (preprocessed)` | 飓风 | 'W风NEW' | 'W风NEW' | None | skill |
| `rec5_260808_f_035_bond_corrected_1_name.png (preprocessed)` | 杀敌多多 | '希故多' | '希故多' | None | bond |

### 6.2 误归一样本（词典外→配置名，门禁必须为 0；实测 3）

| crop | 真值 | OCR raw | 归一化 | 误映射 |
|---|---|---|---|---|
| `rec5_260808_f_086_bond_corrected_2_name.png (preprocessed)` |  | '国' | '国' | '三国' |
| `rec7_short2_20260808_f_033_treasure_3star_0_name.png (preprocessed)` |  | '金币(中）' | '金币(中)' | '经验(中)' |
| `rec7_short2_20260808_f_034_treasure_2star_0_name.png (preprocessed)` |  | '金币（中）' | '金币(中)' | '经验(中)' |

### 6.3 套装进度错例

| crop | 真值 | OCR raw | 归一化 |
|---|---|---|---|
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot1_progress.png` | 0/7 | '套装[0/7]' | '套装[0/7]' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_393s_技能面板_龙珠首现_slot2_progress.png` | 0/2 | '套装[0/2]' | '套装[0/2]' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot0_progress.png` | 0/2 | '装[0/2]' | '装[0/2]' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_423s_持久面板起点_slot1_progress.png` | 1/7 | '套装[1/7]' | '套装[1/7]' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot0_progress.png` | 0/2 | '套装[0/2]' | '套装[0/2]' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_507s_持久面板中段_slot1_progress.png` | 1/7 | '套装[17]' | '套装[17]' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot0_progress.png` | 0/2 | '套装[0/2]' | '套装[0/2]' |
| `fixtures\ocr_choices\treasure\rec1_ingame_boss_20260809\t_630s_结尾_slot1_progress.png` | 1/7 | '套装[1/7]' | '套装[1/7]' |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot2_progress.png` | 0/2 | '套装[0/2]' | '套装[0/2]' |
| `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-ef3f2be8fc5d1103_slot0_progress.png` | 0/2 | ' 套装[0/2]' | '套装[0/2]' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_017_slot1_progress.png` | 0/3 | ' 套装[0/3] 在接' | '套装[0/3]在接' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_018_slot1_progress.png` | 0/3 | '套装[0/3]' | '套装[0/3]' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_053_slot1_progress.png` | 0/3 | '套装[0/3]' | '套装[0/3]' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_112_slot0_progress.png` | 0/7 | '套装[0/7]' | '套装[0/7]' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_112_slot1_progress.png` | 0/3 | '套装[0/3]' | '套装[0/3]' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_112_slot2_progress.png` | 1/2 | ' 套装[1/2]' | '套装[1/2]' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_130_slot0_progress.png` | 0/2 | '[0/2]' | '[0/2]' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_130_slot1_progress.png` | 0/7 | '套装[0/7]' | '套装[0/7]' |
| `fixtures\ocr_choices\treasure\rec5_260808\f_162_slot2_progress.png` | 1/7 | '套装[1/7]' | '套装[1/7]' |
| `fixtures\ocr_choices\treasure\rec7_short2_20260808\f_033_slot2_progress.png` | 0/7 | '赛装[0/7]' | '赛装[0/7]' |
| `fixtures\ocr_choices\treasure\rec7_short2_20260808\f_034_slot2_progress.png` | 0/7 | '套装[0/7]' | '套装[0/7]' |

### 6.4 OCR-raw 词级错误（raw 变体，rec_text ≠ raw_text）

共 67 条（全部样本见同名 JSON）
- `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_015s_技能面板_giveUp证据_slot2_name.png`：真值 '箭矢齐射' → OCR '失齐射'（score=0.7547，lookup=None）
- `fixtures\ocr_choices\skill\rec1_ingame_boss_20260809\t_234s_技能面板_slot1_name.png`：真值 '地震' → OCR '地震NEW'（score=0.951，lookup='地震'）
- `fixtures\ocr_choices\skill\live_postgame_20260808\live_skill_choice_slot1_name.png`：真值 '奥术激光' → OCR '奥术激光 NEW'（score=0.8813，lookup='奥数激光'）
- `fixtures\ocr_choices\skill\reborn_wow_screens_20260806\skill_choice_3_slot0_name.png`：真值 '陨石' → OCR '陨石N'（score=0.9156，lookup='陨石'）
- `fixtures\ocr_choices\skill\reborn_wow_screens_20260806\skill_choice_3_slot2_name.png`：真值 '地震' → OCR '地震NEW'（score=0.9644，lookup='地震'）
- `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot0_name.png`：真值 '乱世三国' → OCR '世三国'（score=0.6444，lookup=None）
- `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot1_name.png`：真值 '体魄' → OCR '体'（score=0.8898，lookup=None）
- `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_036s_羁绊面板_slot2_name.png`：真值 '攻击提升' → OCR '击提升'（score=0.692，lookup='攻击提升'）
- `fixtures\ocr_choices\bond\rec1_ingame_boss_20260809\t_417s_转折点_slot1_name.png`：真值 '魔术' → OCR '厕术(0/2)'（score=0.6819，lookup=None）
- `fixtures\ocr_choices\bond\reborn_wow_screens_20260806\bond_choice_3_slot1_name.png`：真值 '敏捷祝福' → OCR '收捷祝福'（score=0.7368，lookup='敏捷祝福'）
- `fixtures\ocr_choices\treasure\reborn_wow_screens_20260806\treasure_choice_3_slot2_name.png`：真值 '双倍神符' → OCR '双倍神'（score=0.7682，lookup='双倍神符'）
- `fixtures\ocr_choices\treasure\dragonball_webp_20260807\image-c875a13d94b45218_slot1_name.png`：真值 '六星球' → OCR '六星球一'（score=0.7801，lookup='六星球'）
- `fixtures\ocr_choices\skill\rec3_260810\f_008_slot0_name.png`：真值 '箭矢连发' → OCR '失违发'（score=0.6291，lookup=None）
- `fixtures\ocr_choices\skill\rec3_260810\f_008_slot1_name.png`：真值 '电磁网' → OCR '电网NW'（score=0.5229，lookup=None）
- `fixtures\ocr_choices\skill\rec3_260810\f_008_slot2_name.png`：真值 '冰霜新星' → OCR '冰霜新星NEW'（score=0.951，lookup='冰霜新星'）
- `fixtures\ocr_choices\bond\rec3_260810\f_015_slot0_name.png`：真值 '敏捷祝福' → OCR '祝福'（score=0.7176，lookup=None）
- `fixtures\ocr_choices\skill\rec5_260808\f_010_slot0_name.png`：真值 '奥术增幅β' → OCR '奥术增幅B'（score=0.8381，lookup=None）
- `fixtures\ocr_choices\skill\rec5_260808\f_010_slot1_name.png`：真值 '箭矢增幅' → OCR '箭失增幅'（score=0.9764，lookup='箭矢增幅'）
- `fixtures\ocr_choices\skill\rec5_260808\f_010_slot2_name.png`：真值 '箭矢齐射' → OCR '箭失齐射'（score=0.9623，lookup='箭矢齐射'）
- `fixtures\ocr_choices\skill\rec5_260808\f_024_slot0_name.png`：真值 '天雷' → OCR '天雷 NEW'（score=0.896，lookup='天雷'）
- `fixtures\ocr_choices\skill\rec5_260808\f_024_slot1_name.png`：真值 '焦点' → OCR 'LEW焦点'（score=0.5416，lookup='焦点'）
- `fixtures\ocr_choices\skill\rec5_260808\f_024_slot2_name.png`：真值 '强力箭矢' → OCR ' 强箭矢'（score=0.827，lookup='强力箭矢'）
- `fixtures\ocr_choices\skill\rec5_260808\f_027_slot0_name.png`：真值 '飓风' → OCR '风NEW'（score=0.844，lookup=None）
- `fixtures\ocr_choices\skill\rec5_260808\f_027_slot1_name.png`：真值 '陨石' → OCR ' 石 NEW'（score=0.8034，lookup=None）
- `fixtures\ocr_choices\skill\rec5_260808\f_027_slot2_name.png`：真值 '电磁网' → OCR '电磁网NE'（score=0.4351，lookup='电磁网'）
- `fixtures\ocr_choices\skill\rec5_260808\f_042_slot1_name.png`：真值 '奥术激光' → OCR '奥术激光 NEW'（score=0.7412，lookup='奥数激光'）
- `fixtures\ocr_choices\skill\rec5_260808\f_042_slot2_name.png`：真值 '剑气' → OCR '剑气NEW'（score=0.903，lookup='剑气'）
- `fixtures\ocr_choices\skill\rec5_260808\f_043_slot1_name.png`：真值 '天雷' → OCR '天雷 NEW'（score=0.8367，lookup='天雷'）
- `fixtures\ocr_choices\skill\rec5_260808\f_043_slot2_name.png`：真值 '焦点爆破' → OCR ' 焦点慢础'（score=0.7243，lookup='焦点'）
- `fixtures\ocr_choices\skill\rec5_260808\f_044_slot0_name.png`：真值 '飓风' → OCR ' 颶风 NEW'（score=0.7745，lookup=None）
- `fixtures\ocr_choices\skill\rec5_260808\f_044_slot1_name.png`：真值 '次级箭' → OCR 'NEW 次级箭'（score=0.8992，lookup='次级箭'）
- `fixtures\ocr_choices\skill\rec5_260808\f_044_slot2_name.png`：真值 '调焦' → OCR '一调焦'（score=0.5948，lookup='调焦'）
- `fixtures\ocr_choices\skill\rec5_260808\f_045_slot0_name.png`：真值 '爆炎箭' → OCR '爆炎箭 NEW'（score=0.9346，lookup='爆炎箭'）
- `fixtures\ocr_choices\skill\rec5_260808\f_045_slot1_name.png`：真值 '奥术增幅α' → OCR '长箭 NEW 奥术增幅'（score=0.8792，lookup=None）
- `fixtures\ocr_choices\skill\rec5_260808\f_045_slot2_name.png`：真值 '射线延续' → OCR '射线延'（score=0.671，lookup='射线延续'）
- `fixtures\ocr_choices\skill\rec5_260808\f_083_slot0_name.png`：真值 '闪电链' → OCR 'AT 闪电链 NEW'（score=0.8213，lookup='闪电链'）
- `fixtures\ocr_choices\skill\rec5_260808\f_083_slot1_name.png`：真值 '飓风' → OCR 'W 风 NEW'（score=0.7883，lookup=None）
- `fixtures\ocr_choices\skill\rec5_260808\f_083_slot2_name.png`：真值 '地震' → OCR '地震 NEW'（score=0.9181，lookup='地震'）
- `fixtures\ocr_choices\bond\rec5_260808\f_030_slot0_name.png`：真值 '力量祝福' → OCR '量祝福'（score=0.7452，lookup='力量祝福'）
- `fixtures\ocr_choices\bond\rec5_260808\f_030_slot2_name.png`：真值 '乱世三国' → OCR '乱世三国99'（score=0.9104，lookup='乱世三国'）

## 7. 词典覆盖缺口（O1: 已纠正或标 unknown 的槽位）

unknown truth 槽共 17 个，独立计 unknown、不进准确率分母：
- `` ×17
