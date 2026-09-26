# 机制抽帧 / KB 整理进度（接手用）

更新：2026-09-26 15:10（机制线程 Claude）
总目标：把录屏抽帧里的卡面、宝物、黑商、道具、图纸、合成链路全部转录，校对名字，合进 KB。
口径：G:\刷刷宝\素材\系列标签\README_Owner口径.md（Owner 口径最高优先）。归属拿不准的不要分类，列进待确认清单等 Owner。
staff-hub 状态：G:\刷刷宝\GameScript-Local\.staff-hub\jobs\<id>.*；收结果：node "C:/Users/10639/.claude/staff-hub/companion/agy-companion.mjs" wait <id> --timeout 60m
内存紧（32GB 常剩 1~3GB），omp 同时最多 2 路。omp 必须显式带 --model gemini-3.8-flash；任何任务都不许写默认工作树 G:\刷刷宝\GameScript-Local。

## 已完成
| 步骤 | 产出 | 说明 |
|---|---|---|
| KB 落库 10EX/11EX + Owner 口径 | 分支 docs/kb-ex-breakdown-20260926（worktree G:\刷刷宝\Worktrees\kb-ex-20260926），HEAD d5da8aec | muse，已验收；含海贼王 EX 卡面 |
| 系列标签第一批 | G:\刷刷宝\素材\系列标签\整理后\ | muse 22 张 + 实测线程 codex 补充2，分类符合 Owner 确认 |
| codex 第一轮看图转录 | catalog.jsonl（95 条）、keyframes\、template_candidates.csv、SUMMARY.md | 已抽查；注意 catalog 里「推锋」是错的，实机为「挫锋」 |
| OCR 预筛 | ocr_prepass\（ocr_raw\ 1915 帧、drafts.jsonl 1605 条、name_suspects.csv 339 对、stats.md） | OCR 错字很多，只当提示；重跑：python ocr_prepass\scripts\build_drafts.py |
| 待看图帧清单 | ocr_prepass\frames_for_visual_check.txt（777 帧）拆成 visual_part_A/B1/B2/B3.txt | A=宝物/黑商/道具/图纸/提示/未知 92 帧；B1-B3=卡面各约 228 帧 |

## 进行中 / 待派
| 路 | job id | 输出 | 状态 | 下一步 |
|---|---|---|---|---|
| A | implement-mui17azq-b237f3b6（omp gemini） | catalog_omp_A.jsonl | 运行中 | 完成后验收；超时就用同一 brief 续做未处理的帧 |
| B1 | implement-mui17bg6-9e7a6e2c（omp gemini） | catalog_omp_B1.jsonl | 运行中，已抽查（挫锋正确） | 同上 |
| B2 | 已取消（内存不足） | catalog_omp_B2.jsonl | 未开始 | A 或 B1 结束后派：brief = ocr_prepass\visual_brief.md 把 {PART} 换成 B2 |
| B3 | 已取消（内存不足） | catalog_omp_B3.jsonl | 未开始 | 同上换成 B3 |

派发命令模板（在 G:\刷刷宝\GameScript-Local 下执行）：
node "C:/Users/10639/.claude/staff-hub/companion/agy-companion.mjs" implement --backend omp --model gemini-3.8-flash --timeout 90m --prompt-file <把 visual_brief.md 的 {PART} 替换后的文件>

## 之后还没做的
1. 合并 catalog.jsonl + catalog_omp_*.jsonl，去重（同名同文只留最清楚的一条），修正 catalog 里的错字（推锋→挫锋）。
2. 名字对照表 name_mismatch.csv：旧写法、实机写法、出处帧、出处文件+键（来源：各条 note 里的 NAME_MISMATCH + 人工核对 name_suspects.csv 里真正的错字，OCR 误识不算）。涉及 choice_lexicon / 白名单的改名交实测线程改代码。
3. 宝物：把转录到的宝物效果对上 choice_lexicon 里 61 个 treasure 词条（目前只有名字）；dashboard_mechanics.treasures 已有 13 个带描述。
4. 黑商：新建黑商商品库（名字、价格、效果、出处帧）。
5. 把以上合进 KB（在 KB worktree，提交到 docs/kb-ex-breakdown-20260926，不改 wired_to_decision、不改代码），跑 pytest tests/test_choice_lexicon.py tests/contract -q。
6. 待确认清单 PENDING_OWNER.md：归属拿不准的卡/物品、看不清的字。
7. 在线程里交汇总，并把 KB 分支新 HEAD 转实测线程。
