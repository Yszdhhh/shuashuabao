# Vision Corpus Coverage（Stage 2 Coverage）

> 基线状态：`FROZEN_2026-08-29`。本报告只做本地素材蒸馏与评测盘点，不接生产；不引入 fallback/watchdog/thread/recovery manager/FSM。后续不再扫描/整理 27GB 原始截图，Coverage 只接受已索引子集或新的真实 Live Capture 回填。

## 结论先行

当前可见原始图片文件为 `161,337` 个、`27.108 GiB`；这是按明确目录的文件计数，不是去重后的样本数。已有选择类评测 `155` 个样本、`7` 个 capture session；treasure description 的 `12,276` 次 unavailable 调用做过 decision-equivalence replay，mismatch 为 `0`。

Coverage 阶段的生产边界是 `NOT_APPLIED`：本次产物只落在 `tools/`、`tests/`、`docs/distillation/`，不改 `src/`、不改 `config/`，也不把 Gray_2x、cards template、HSV、vision_profiles 接入生产。

## Coverage matrix

`units` 是评测/事件/语义单元；`unique_images` 是能定位到的去重文件数。两者可能不同：同一张截图可承担多个 slot/pair，事件也可能没有一一对应的图片。

| 场景 | 正向 | 负向 | Hard-negative | 实机 session | ROI/参数 | 算法 | KPI | 结论 |
|---|---:|---:|---:|---:|---|---|---|---|
| `skill_choice` | 47 / 47图 | 55 / 55图 | 0 / 0图 | 7 | PRESENT | PRESENT | PRESENT | `COMPRESSED` |
| `bond_choice` | 54 / 54图 | 55 / 55图 | 423 / 6图 | 7 | PRESENT | PRESENT | PRESENT | `COMPRESSED` |
| `treasure_choice` | 54 / 54图 | 55 / 55图 | 10 / 10图 | 7 | PRESENT | PRESENT | PRESENT | `COMPRESSED` |
| `l0_platform_room_create` | 2 / 2图 | 2 / 2图 | 2 / 2图 | 1 | PRESENT | PARTIAL | PARTIAL | `PARTIAL` |
| `l0_room_list_join_ready` | 5 / 5图 | 3 / 0图 | 5 / 3图 | 2 | PARTIAL | PARTIAL | MISSING | `PARTIAL` |
| `l0_room_waiting_ready_start` | 1 / 1图 | 0 / 0图 | 2 / 2图 | 2 | PARTIAL | PARTIAL | MISSING | `PARTIAL` |
| `l0_stage_select_start` | 1 / 1图 | 2 / 4图 | 0 / 0图 | 1 | PARTIAL | PARTIAL | PARTIAL | `PARTIAL` |
| `l0_hero_setup` | 1 / 1图 | 0 / 0图 | 0 / 0图 | 1 | PARTIAL | MISSING | MISSING | `RESEARCH_ONLY` |
| `l1_main_hud_challenges` | 2 / 2图 | 1 / 1图 | 2 / 6图 | 2 | PARTIAL | PARTIAL | PARTIAL | `PARTIAL` |
| `l1_long_run_session` | 2 / 47图 | 0 / 0图 | 96 / 47图 | 2 | PRESENT | PARTIAL | PRESENT | `PARTIAL` |
| `l1_dragonball` | 2 / 2图 | 0 / 0图 | 0 / 0图 | 1 | PARTIAL | MISSING | MISSING | `RESEARCH_ONLY` |
| `l1_wood_secret_merchant` | 2 / 2图 | 0 / 0图 | 0 / 0图 | 1 | PARTIAL | MISSING | MISSING | `RESEARCH_ONLY` |
| `l1_post_victory_archive_boss` | 5 / 5图 | 0 / 0图 | 1 / 10图 | 2 | PARTIAL | PARTIAL | PARTIAL | `PARTIAL` |
| `recovery_fail_giveup` | 3 / 3图 | 0 / 0图 | 1 / 3图 | 1 | PRESENT | PRESENT | PRESENT | `COMPRESSED` |
| `recovery_pause_overlay` | 0 / 0图 | 0 / 0图 | 0 / 0图 | 0 | MISSING | MISSING | MISSING | `MISSING` |
| `recovery_disconnect` | 0 / 0图 | 0 / 0图 | 0 / 0图 | 0 | MISSING | MISSING | BLOCKED | `MISSING` |
| `treasure_business_semantics` | 4 / 4图 | 6 / 10图 | 10 / 10图 | 0 | PARTIAL | PRESENT | PRESENT | `PARTIAL` |
| `ur_attr_route_semantics` | 9 / 9图 | 0 / 0图 | 0 / 0图 | 0 | RESEARCH_ONLY | MISSING | MISSING | `RESEARCH_ONLY` |

## 逐项 gap / 原始素材处置

### `skill_choice` — 技能选择

- 处置：`COMPRESSED`；当前 KPI 不是全业务闭环证明；需继续补齐场景级 no-action/hard-negative 和多分辨率样本。
- 正向来源：docs/distillation/VISION_EVAL_MANIFEST.jsonl; fixtures/ocr_choices；负向来源：fixtures/ocr_choices/negatives；hard-negative 来源：未建立 scene-specific hard-negative set。
- ROI/参数：`PRESENT` — VISION_EVAL_MANIFEST.json: source_crop + roi + hash；current six-variant OCR evaluation。
- 算法：`PRESENT` — docs/distillation/VISION_OCR_BENCHMARK.json；existing choice OCR implementation (reference only)。KPI：`PRESENT` — VISION_OCR_BENCHMARK.json；CARD_TEMPLATE_BENCHMARK.json (bond/template scope)。

### `bond_choice` — 羁绊选择

- 处置：`COMPRESSED`；当前 KPI 不是全业务闭环证明；需继续补齐场景级 no-action/hard-negative 和多分辨率样本。
- 正向来源：docs/distillation/VISION_EVAL_MANIFEST.jsonl; fixtures/ocr_choices；负向来源：fixtures/ocr_choices/negatives；hard-negative 来源：docs/distillation/CARD_TEMPLATE_BENCHMARK.json。
- ROI/参数：`PRESENT` — VISION_EVAL_MANIFEST.json: source_crop + roi + hash；current six-variant OCR evaluation。
- 算法：`PRESENT` — docs/distillation/VISION_OCR_BENCHMARK.json；existing choice OCR implementation (reference only)；docs/distillation/CARD_TEMPLATE_BENCHMARK.json。KPI：`PRESENT` — VISION_OCR_BENCHMARK.json；CARD_TEMPLATE_BENCHMARK.json (bond/template scope)。

### `treasure_choice` — 宝物选择

- 处置：`COMPRESSED`；当前 KPI 不是全业务闭环证明；需继续补齐场景级 no-action/hard-negative 和多分辨率样本。
- 正向来源：docs/distillation/VISION_EVAL_MANIFEST.jsonl; fixtures/ocr_choices；负向来源：fixtures/ocr_choices/negatives；hard-negative 来源：fixtures/treasure_negative。
- ROI/参数：`PRESENT` — VISION_EVAL_MANIFEST.json: source_crop + roi + hash；current six-variant OCR evaluation。
- 算法：`PRESENT` — docs/distillation/VISION_OCR_BENCHMARK.json；existing choice OCR implementation (reference only)。KPI：`PRESENT` — VISION_OCR_BENCHMARK.json；CARD_TEMPLATE_BENCHMARK.json (bond/template scope)。

### `l0_platform_room_create` — 地图页→创建房间→确认

- 处置：`COMPRESSED`；创建/确认证据可定位；大厅真实点击成功率、取消/密码/等级弹窗的动作等价性仍未形成稳定 KPI。
- 正向来源：fixtures/manifest.json；负向来源：fixtures/manifest.json；hard-negative 来源：fixtures/lobby_hitch_20260814/INDEX.json。
- ROI/参数：`PRESENT` — fixtures/manifest.json；config/scenes.json existing room/create ROIs。
- 算法：`PARTIAL` — existing template probes in Stage 2A evidence。KPI：`PARTIAL` — release gate scene/template checks；no reliable end-to-end join KPI。

### `l0_room_list_join_ready` — 房间列表筛选→识别可加入房→准备/等待

- 处置：`RESEARCH_ONLY`；有真实录像代表帧，但无法证明蹭车加入成功；列表行、房间满、密码/锁标和准备态仍需成对标注。
- 正向来源：fixtures/lobby_hitch_20260814/INDEX.json; fixtures/lobby_hitch_detail_20260814/README.md；负向来源：fixtures/lobby_hitch_20260814/README.md；hard-negative 来源：fixtures/lobby_hitch_20260814/INDEX.json; fixtures/lobby_hitch_detail_20260814/README.md。
- ROI/参数：`PARTIAL` — client crop 203,84 / 1600x900；existing room/list template probes。
- 算法：`PARTIAL` — template matching evidence only; no join-success action replay。KPI：`MISSING` — no reliable join→ready→start KPI。

### `l0_room_waiting_ready_start` — 房间等待/准备态→开始倒计时

- 处置：`RESEARCH_ONLY`；等待、客人准备和房主开始三态尚未形成可安全放行的完整正负样本闭环。
- 正向来源：fixtures/replay/room_waiting_host.png；负向来源：未建立独立 negative；hard-negative 来源：fixtures/lobby_hitch_20260814/INDEX.json。
- ROI/参数：`PARTIAL` — room_waiting_host replay asset；room_start template threshold evidence。
- 算法：`PARTIAL` — no full state/action sequence benchmark。KPI：`MISSING` — no stable false-start/ready-state KPI。

### `l0_stage_select_start` — 选关/难度/挑战→开始主线

- 处置：`RESEARCH_ONLY`；目标关卡样本存在；ticket 0/120 与挑战票据仍是 XFAIL/CAVEAT，不能当作真实修复证据。
- 正向来源：fixtures/manifest.json；负向来源：fixtures/scenarios/; fixtures/manifest.json；hard-negative 来源：未建立独立 hard-negative。
- ROI/参数：`PARTIAL` — stage target coordinates/scene templates；stage_select_20260814/ representative frame。
- 算法：`PARTIAL` — frozen stage-select scroll replay PASS。KPI：`PARTIAL` — no reliable ticket-zero / wrong-stage action KPI。

### `l0_hero_setup` — 英雄选择/属性/等级/开始

- 处置：`RESEARCH_ONLY`；有素材蒸馏价值，但视频没有完整目标等级与 Start 闭环；不能压缩成生产参数。
- 正向来源：fixtures/hero_modal_20260812_180825；负向来源：未建立独立 negative；hard-negative 来源：54 ROI/level/card/strip crops are state variations, not validated hard negatives。
- ROI/参数：`PARTIAL` — client_1600x900 + 54 ROI/state crops。
- 算法：`MISSING` — no action-level detector/selector benchmark。KPI：`MISSING` — no complete target-level→Start KPI。

### `l1_main_hud_challenges` — 主 HUD/自动任务/四挑战可见与切换

- 处置：`RESEARCH_ONLY`；主线与挑战的正面代表帧有；需要自动开/关、四挑战、不可见/遮挡和误点击对照的动作级 KPI。
- 正向来源：fixtures/replay/; fixtures/lobby_hitch_detail_20260814/README.md；负向来源：fixtures/replay/main_line_auto_on.png；hard-negative 来源：fixtures/ocr_choices/negatives。
- ROI/参数：`PARTIAL` — main_line_auto_on/off and challenge scene assets；existing challenge ROIs。
- 算法：`PARTIAL` — existing scene/template probes; no coverage-wide benchmark。KPI：`PARTIAL` — long-run event counts; no per-action precision/recall。

### `l1_long_run_session` — 长线程主循环、选择、刷新、羁绊与异常事件

- 处置：`COMPRESSED`；长跑已压缩为 session/KPI，但不能把 incident/focus 图直接当作覆盖完成或生产 detector KPI。
- 正向来源：fixtures/longtest_20260814/trace_aligned.json; fixtures/longtest_20260814/focus；负向来源：未定义 session-level negative；hard-negative 来源：fixtures/longtest_20260814/trace_aligned.json。
- ROI/参数：`PRESENT` — trace_aligned.json: 2 runs / 2996.4s / 6525 ticks；choice_decisions.json。
- 算法：`PARTIAL` — event/decision telemetry; no new algorithm is introduced here。KPI：`PRESENT` — n_decisions=110；n_refreshes=57；n_window_loss_ticks=0；room_stuck_candidate=6; incident=90。

### `l1_dragonball` — 龙珠/进度型宝物识别与语义

- 处置：`RESEARCH_ONLY`；只有研究素材和语义线索；缺少不同进度、非龙珠相似卡、跨 session 的可靠样本。
- 正向来源：fixtures/ocr_choices/frames/dragonball_webp_20260807；负向来源：未建立龙珠 negative；hard-negative 来源：未建立龙珠 hard-negative。
- ROI/参数：`PARTIAL` — 2 full-frame WebP + name/progress crops。
- 算法：`MISSING` — no progress-state algorithm benchmark。KPI：`MISSING` — no false-positive / progression KPI。

### `l1_wood_secret_merchant` — 木材挑战/秘境/黑市与掉落链

- 处置：`RESEARCH_ONLY`；原始帧能说明业务存在，但缺少完整出现/不出现/遮挡/点击后状态转移样本。
- 正向来源：fixtures/lobby_hitch_detail_20260814/README.md；负向来源：未建立独立 negative；hard-negative 来源：未建立独立 hard-negative。
- ROI/参数：`PARTIAL` — existing wood/challenge/merchant scene assets；two representative full frames。
- 算法：`MISSING` — no coverage-stage algorithm benchmark。KPI：`MISSING` — no merchant/secret/wood action KPI。

### `l1_post_victory_archive_boss` — 胜利→归档/挑战 NPC/传家宝/大裂隙

- 处置：`RESEARCH_ONLY`；单帧目录与部分 frozen replay 已有；真正胜利后链路、误识别安全区、连续 session 仍不够。
- 正向来源：fixtures/replay/; fixtures/reborn_wow/manifest.json；负向来源：未建立 endgame no-action pool；hard-negative 来源：fixtures/live_postgame_20260808/README.md。
- ROI/参数：`PARTIAL` — frozen replay/endgame catalog assets。
- 算法：`PARTIAL` — archive/exit replay guards; current-version chain is incomplete。KPI：`PARTIAL` — frozen archive/exit checks, but no full chain KPI。

### `recovery_fail_giveup` — 失败/放弃面板的区分与收口

- 处置：`COMPRESSED`；已压缩为场景 guard/replay KPI；仍不等于真实断线弹窗覆盖。
- 正向来源：fixtures/scenarios/fail_recovery_three_frames/；负向来源：未建立独立 recovery negative；hard-negative 来源：fixtures/scenarios/fail_recovery_three_frames/case.json。
- ROI/参数：`PRESENT` — fail/giveup scene anchors and three-frame harness。
- 算法：`PRESENT` — fail/giveup replay guard。KPI：`PRESENT` — giveup_panel_not_fail PASS；fail_panel_preempt PASS。

### `recovery_pause_overlay` — 暂停覆盖层与恢复动作

- 处置：`MISSING`；暂停 overlay 的现有测试回归与素材边界未完成，不能以配置条目替代实机证据。
- 正向来源：没有可审计的 current-version positive；负向来源：没有可审计的 current-version negative；hard-negative 来源：没有可审计的 current-version hard-negative。
- ROI/参数：`MISSING` — 仅有场景配置/历史测试入口。
- 算法：`MISSING` — full current-version pause overlay 未建立。KPI：`MISSING` — pause action KPI 未建立。

### `recovery_disconnect` — 断线/退出确认弹窗 fail-closed

- 处置：`MISSING`；保持 BLOCKED；不得用合成帧或相邻退出弹窗替代。
- 正向来源：fixtures/missing_disconnect.png (missing)；负向来源：未建立 disconnect negative；hard-negative 来源：未建立 disconnect hard-negative。
- ROI/参数：`MISSING` — disconnect modal positive fixture missing。
- 算法：`MISSING` — no current-version visual algorithm evaluation。KPI：`BLOCKED` — release gate: disconnect_modal_missing BLOCKED baseline-consistent。

### `treasure_business_semantics` — 必拿/负向宝物/描述负模式/刷新策略

- 处置：`COMPRESSED`；业务语义已保留并可评测；仍需把必拿/负向卡放回真实多布局 panel/session 做识别 KPI。
- 正向来源：fixtures/treasure_must_take/README.md；负向来源：fixtures/treasure_negative/INDEX.json；hard-negative 来源：fixtures/treasure_negative/INDEX.json。
- ROI/参数：`PARTIAL` — name/description crops and business lists；description/negative_patterns retained。
- 算法：`PRESENT` — choice_policy semantic lists；treasure description decision-equivalence replay。KPI：`PRESENT` — 12276 unavailable desc calls; paired replay mismatch_count=0。

### `ur_attr_route_semantics` — UR 属性路线：智力/力量/敏捷

- 处置：`RESEARCH_ONLY`；当前只能支持业务知识蒸馏，不能支持视觉生产接入或路线成功率结论。
- 正向来源：fixtures/ur_attr_routes/INDEX.json；负向来源：未建立路线 negative；hard-negative 来源：未建立路线 hard-negative。
- ROI/参数：`RESEARCH_ONLY` — source.png semantic cards; no click-template ROI。
- 算法：`MISSING` — no route recognition benchmark。KPI：`MISSING` — no route precision/recall or outcome KPI。

## 已成功压缩为 ROI / 算法参数 / KPI

- 选择类：155 个 title-crop 样本已按 session、ROI、hash 和 train/tune/blind split 建索引；skill/bond/treasure 的 OCR KPI 已落盘。bond 的 template 评测另有 operating threshold `0.82`、6 positive、423 hard-negative pair、blank/idle 各 156 pair。
- treasure description：12,276 次历史 unavailable 调用已被审计；关闭调用的 paired replay 对 SELECT/CLOSE/REFRESH/slot 决策 `mismatch_count=0`，但运行时调用仍保留，业务 `description`、`negative_patterns`、`negative_names` 仍保留。
- fail/giveup：三帧 replay/harness 已压缩为场景 guard 与 KPI；`giveup_panel_not_fail` 和 `fail_panel_preempt` 已通过。
- 长跑：两个真实 session 已压缩为 2,996.4 秒、6,525 ticks、选择/刷新/incident/stuck 计数；这属于 session telemetry，不是所有 detector 已验证。

## 仍只有研发价值的截图

- `G:/测试视频+抽帧` 的顺序帧、`%LOCALAPPDATA%/ShuaBao/incidents` 的 incident/panel 图、`测试夹` 与 `_codex_skill_video_evidence`：可用于追问题和选候选帧，未统一标注，不能当 gold corpus。
- hero setup 的全屏/level/card/strip/plus ROI、dragonball 进度图、木材/秘境/黑市代表帧、treasure must-take、UR 属性路线 source.png：已保留业务语义或候选 ROI，但缺少 paired negative/hard-negative 与动作 KPI。
- live postgame 的 `archive_panel` 已由 README 明确为 safe-zone/minimap marker，不是实际 archive modal；只能作为 hard-negative/研发证据。

## 仍缺可靠素材的业务场景

- current-version disconnect modal positive
- current-version pause overlay positive/negative pair
- full lobby join→ready→start→return action sequence KPI
- ticket-zero challenge evidence
- complete hero setup target-level→Start loop
- scene-specific negative/hard-negative/session KPI for dragonball, wood, secret, merchant and endgame chain

## 原始目录观察

| 目录 | 分类 | 图片文件 | 大小 | 说明 |
|---|---|---:|---:|---|
| `fixtures` | `TEST_ONLY / DEV_ONLY` | 1,952 | 0.866 GiB | Indexed fixtures and replay assets; not all are gold samples. |
| `G:\刷刷宝\测试夹` | `DEV_ONLY` | 5,333 | 2.283 GiB | Incident/test images outside the authoritative repository. |
| `G:\刷刷宝\video_frames` | `DEV_ONLY` | 70 | 0.193 GiB | Locally extracted video frames when present. |
| `G:\刷刷宝\_codex_skill_video_evidence` | `DEV_ONLY` | 266 | 0.239 GiB | Codex evidence images, not a production asset source. |
| `G:\测试视频+抽帧` | `DEV_ONLY` | 142,075 | 19.486 GiB | Raw sequential video frames; no deduplication claim. |
| `C:\Users\10639\AppData\Local\ShuaBao` | `DEV_ONLY` | 11,348 | 4.038 GiB | Runtime incidents/traces; incident evidence only. |
| `G:\下载\1.5.1.zip\Images` | `DEV_REF` | 293 | 0.002 GiB | Legacy reference images; not current-version approval. |

## 边界与下一步

- `disconnect_modal_missing` 继续 `BLOCKED`；没有实机素材就不以合成帧更新 baseline。
- 本阶段不把任何 coverage 结论接入生产，不扩展 fallback/watchdog/FSM，不调整运行时路径。
- 下一步应优先补齐每个缺口的真实 session paired positive/negative/hard-negative，再把算法评测写成可重复 replay；不是先增加 detector 层。
