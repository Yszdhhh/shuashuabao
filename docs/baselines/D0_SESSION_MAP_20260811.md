# D0 录屏 Session 映射与去重明细（2026-08-11）

## 1. 全部 10 段录屏元数据

| 文件 | 时长 | 分辨率/fps | 大小 | SHA256（前 16） | 文件时间 | session 归属 | 与 fixtures 关系 |
|---|---|---|---|---|---|---|---|
### 既有 rec1-rec8（C:\\tmp\\recordings）
| rec1_ingame_boss.mp4 | 00:10:32 | 1600x900/30 | 118.4MB | ad486cc02b958ae5… | 2026-08-09T14:41 | rec1_ingame_boss_20260809 | 正样本 9 面板（skill3/bond2/treasure4）+ 负样本 |
| rec2_postgame_exit.mp4 | 00:00:42 | 1586x892/30 | 10.7MB | cfaa726d70c07b33… | 2026-08-09T14:42 | rec2_postgame_exit_20260809 | 负样本 17（无三选一面板） |
| rec3_260810.mp4 | 00:05:09 | 1600x900/30 | 53.9MB | 0af9f88af2bf3eb6… | 2026-08-10T00:29 | rec3_260810 | 正样本 4（skill1/bond1/treasure2） |
| rec4_260809.mp4 | 00:02:40 | 1600x900/30 | 41.3MB | 605aafa3f94e2205… | 2026-08-09T22:34 | （无面板，跳过） | 未导入 |
| rec5_260808.mp4 | 00:14:12 | 1600x900/30 | 214.7MB | f2b7ce9a520d9690… | 2026-08-08T00:44 | rec5_260808 | 正样本 29（skill9/bond13/treasure7）——占比 55.8% 超 40% 门禁 |
| rec6_short1.mp4 | 00:00:06 | 1600x900/30 | 1.4MB | 62ccfb01e955fcf6… | 2026-08-08T00:55 | rec6_short1 | 未导入 |
| rec7_short2.mp4 | 00:00:30 | 1600x900/30 | 7.7MB | 93543a1c418a4857… | 2026-08-08T18:37 | rec7_short2_20260808 | 正样本 4（skill1/bond1/treasure2） |
| rec8_short3.mp4 | 00:00:04 | 1600x900/30 | 1.0MB | 12993999d880aa85… | 2026-08-08T18:46 | rec8_short3 | 未导入 |

### 本轮新增两段（C:\\Users\\10639\\Desktop\\录屏素材）
| 20260810_214444.mp4 | 00:46:18 | 1920x1080/30 | 2.08GB | 2f6e6f5098834f3c… | 2026-08-10T21:44 | **rec9_mijing_20260810** | 新 session（秘境局） |
| 20260810_224848.mp4 | 00:42:48 | 1920x1080/30 | 2.02GB | df68c4fd3405d6a5… | 2026-08-10T22:48 | **rec10_3normal_20260810** | 新 session（三普通局） |

## 2. session 对应关系结论

两段新录屏与既有 rec1-rec8、fixtures 7 正样本 session **均无对应/无重复导入**，证据：

1. **SHA256 全异**：新视频与全部 8 段既有 rec 的 SHA256 无一相同（见上表）；
2. **时间不重叠**：既有 rec 最晚 2026-08-10T00:29（rec3），新视频为 2026-08-10T21:44/22:48——晚 21 小时以上；
3. **采集形态不同**：既有 rec 为窗口采集（1600x900/1586x892，h264 Main），新视频为全桌面采集（1920x1080，h264 Constrained Baseline，另一录制器）；
4. **内容感知哈希无近重复**（见 §3）。

## 3. 感知哈希去重报告

### 3.1 全帧粗查（phash 64bit，全帧拉伸 32x32）

- 参与比较：既有 fixtures 89 张原始帧（52 正面板 + 37 负样本） × 新索引帧 5347 张；
- 结果：最近距离分布 min=2；hd≤10 的配对共 13 对，下表列出最近 8 对——均为布局级相似（HUD/全屏游戏画面结构），非内容重复（见 §3.2 面板区复检）；

| 既有帧 | 新帧 | hd | 判定 |
|---|---|---|---|
| fixtures/ocr_choices/negatives/live_postgame_20260808/live_fullscreen.png | a_000236 | 2 | 布局相似（中心区 hd 更高，内容不同） |
| fixtures/ocr_choices/frames/dragonball_webp_20260807/image-c875a13d94b45218.webp | a_000982 | 4 | 布局相似（中心区 hd 更高，内容不同） |
| fixtures/ocr_choices/frames/reborn_wow_screens_20260806/treasure_choice_3.png | a_001148 | 5 | 布局相似（中心区 hd 更高，内容不同） |
| fixtures/ocr_choices/negatives/live_postgame_20260808/live_archive_panel.png | a_000236 | 6 | 布局相似（中心区 hd 更高，内容不同） |
| fixtures/ocr_choices/frames/reborn_wow_screens_20260806/skill_choice_3.png | a_000982 | 7 | 布局相似（中心区 hd 更高，内容不同） |
| fixtures/ocr_choices/negatives/reborn_wow_screens_20260806/heirloom_challenge_bosses.png | a_001686 | 7 | 布局相似（中心区 hd 更高，内容不同） |
| fixtures/ocr_choices/frames/reborn_wow_screens_20260806/bond_choice_3.png | a_001673 | 8 | 布局相似（中心区 hd 更高，内容不同） |
| fixtures/ocr_choices/frames/dragonball_webp_20260807/image-ef3f2be8fc5d1103.webp | a_001092 | 8 | 布局相似（中心区 hd 更高，内容不同） |

### 3.2 面板区复检（中心区 phash）

对 hd≤10 的强候选逐对复检中心区（x0.2-0.8, y0.15-0.75）：
- `a_000236` ↔ live_fullscreen(neg)：全帧 hd=2，中心区 hd=13；OCR 内容不同（挑战选择页 vs 局外页）→ **非重复**；
- `a_000982` ↔ dragonball webp 帧：全帧 hd=4，中心区 hd=22 → **非重复**（不同面板内容）；
- `a_001148` ↔ reborn_wow treasure_choice_3：全帧 hd=5，中心区 hd=24 → **非重复**；

### 3.3 面板级去重（episode 主样本 vs 既有 52 正面板 name 带）

每个新 episode 主样本的 name 带 OCR 文本指纹与既有面板逐帧比对（见 episodes.json annotations），无同名/同布局重复导入；
既有 fixture 帧与新 episode 主样本的帧级 SHA 无任何相同。

## 4. 视频索引

- `idx_a`（rec9 秘境局）：2778 帧 @1fps，帧名 000001-002778（第 N 帧 ≈ 第 N-1 秒）；
- `idx_b`（rec10 三普通局）：2569 帧 @1fps，帧名 000001-002569；
- 元数据：`C:/tmp/recordings/video_index_meta.json`（含 probe/sha256/frames 数）。

## 5. 失败/断线/胜利帧（production 确认）

> 待 stage-2 production 复核完成后补齐（当前仅有 stage-1 低阈候选）。

