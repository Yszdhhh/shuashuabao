# 素材缺口与抽帧计划（2026-08-12）

## 1. 本地已有（优先吃干净）

### 录屏（`C:\Users\10639\Desktop\录屏素材\`）

| 文件 | 用途建议 |
|---|---|
| 20260810_214444.mp4 | 早期全流程；战后/秘境线索 |
| 20260810_224848.mp4 | 同日补充 |
| 20260811_144337.mp4 | 面板/大厅 |
| 20260811_164929.mp4 | 已有 forensics 引用 |
| 20260811_205044.mp4 | 同上 |
| 20260811_215302.mp4 | 同上 |
| 20260812_110511.mp4 | 创房/大厅当日 |
| 20260812_180003.mp4 | 阵营/英雄相关 |
| 20260812_180825.mp4 | 与 `fixtures/hero_modal_20260812_180825` 对齐 |

### 已抽关键帧

- `C:\tmp\recordings\keyframes\`（技能 giveUp、羁绊、传家宝、选关等）
- `fixtures/ocr_choices/`（技能/羁绊/宝物/negatives；**`o3_blind_manifest.json` entries=0**）
- `fixtures/reborn_wow/{room,stage,main_line,choices,endgame}`
- `fixtures/treasure_negative/`
- `fixtures/card_template_assertions/`（36 卡双向断言）

## 2. 硬缺口（BLOCKED / 不可伪造）

| 缺口 | 影响 | 采集方式 | 优先 |
|---|---|---|---|
| 当前版全屏断线/重连弹窗 | `fail_recovery` XFAIL；frozen disconnect BLOCKED | `tools/net_block.py` 或实机断网 | P0 |
| ticket-zero 连续三帧 | 考古 XFAIL | 实机挑战券=0 | P1 |
| OCR 盲测 1600×900 冻结 ROI 独立 episode | O3 blind 空；99% 离线分不可当盲测 | 新局录屏→冻结裁剪→独立真值 | P0 |
| 黑市全屏（非 card_strip 裁切） | 黑市自动化 | 局内进黑市全屏截图 | P1 |
| 4 选 / 5 选技能面板 | 布局未验收 | 账号出现时立刻截 | P1 |
| 黑锋阵营「未选中」模板 | V0.2 黑锋 Fail-Closed | 实机未选中态截图 | P0（外壳/L0） |
| 可选：海盗/修仙卡面 PNG | 卡库扩展 | 用户提供，禁止伪造 | P2 |

## 3. OCR / 学习素材是否还要补

| 系统 | 结论 |
|---|---|
| OCR | **要补盲测与难例**，不是盲目加卡图。重点：艺术字「海盗」类、负面描述句原文、新面板布局。词典别名已覆盖奥术/奥数。 |
| 模板卡面 | 36 短码已对齐；缺图再补，勿合成。 |
| 本地习惯学习 | **不需要联网素材**；需要运行时日志字段：面板类型、槽位名、用户是否手动改点、最终动作。Schema 见 `config/habit_preference.schema.json`。 |
| 官方权重 | 随包；用录屏回归官方预设，不靠抖音短视频数值。 |

## 4. 抽帧作业单（执行顺序）

1. **本机录屏**用 `python tools/video_breakdown.py` 对 `20260812_*.mp4` 抽「技能/羁绊/宝物/刷新/放弃」帧，候选进 `C:\tmp\frame_candidates_20260812\`（先不入 fixtures）。  
   - **已做**：`20260811_164929.mp4` → `C:\tmp\frame_candidates_20260812\20260811_164929\`（34 scene + contact_sheet；待人工挑面板进 OCR blind）。  
2. 人工过目后，合格的 1600×900 面板进 `fixtures/ocr_choices/`，并开始填 `o3_blind_manifest.json`（每类目标 ≥30 episode，可分期）。  
3. 断线素材单独目录，**禁止**用合成图关 GATE。  
4. B 站 S8/S9：仅当本地仍缺某面板形态时再下载抽帧。  
5. 抖音：目录与截图级词典线索；不做批量下载依赖。

## 5. 合规

- 只使用用户自有录屏与公开可访问页面。  
- 社区攻略文本不直接当模型训练集。  
- 进 `fixtures/` 前必须可追溯来源路径与分辨率。
