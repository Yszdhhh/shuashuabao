# NEXT_STAGE 执行蓝图只读审查报告

- 审查对象：`docs/NEXT_STAGE_EXECUTION_BLUEPRINT_20260811.md`（N0→R0）
- 对照：`docs/OCR_HYBRID_AUTOMATION_BLUEPRINT_20260810.md`、现有代码/数据事实
- 分支：`codex/ocr-hybrid`
- 审查角色：BLUEPRINT-REVIEW（只读，不改仓库）
- 日期：2026-08-11
- 并行 agent 隔离：不评价 PERF-BASE / OCR-EVAL / DATA 的具体 diff，只评蓝图细则与代码现状匹配度

---

## 0. 总结论

**结论：蓝图方向正确，但当前不可直接当作“无歧义施工图”下发 N2/S0/O2。`overall_correctness = incorrect`（存在会致返工或安全事故的阻塞项）。**

正确之处：
1. 先 N0 基线、后 N2 优化；OCR 先修评测可信度，再谈模型/接入。
2. `mediator.py` 单写者、N2→S0 串行，避免双写漂移。
3. 明确 fail 抢占、硬期限、OCR 不输出坐标等安全原则，与旧蓝图不变量一致。
4. 原版纠偏（局内仍是模板+坐标点击，而非 UIA CEF）与代码现状一致。

主要问题不是“写得不够长”，而是：
1. **安全关键路径**（失败 vs 选择面板）现状与 S0 目标相反，且场景模板把 `giveUp` 和 fail 绑在一起。
2. **波次图与任务包/派工表自相矛盾**（O1 落在 Wave0 还是 Wave3；N1 有名无包）。
3. **O2 的 960×540 真实正面板门禁在现有素材+两段 1080p 桌面录屏下不可达**，若不降级或单列采集任务，O3/R0 会被假阻塞或被造假数据污染。
4. 若干门禁**不可自动判定**或依赖可能 `insufficient_evidence` 的原版延迟。
5. matcher API **没有优先级早停**；N2 若只改 mediator 缓存而不改 `match_any` 契约，无法兑现“选择 tick ≤20 次 matchTemplate”。

---

## 1. 门禁可判定性

| 门禁 | 可自动化？ | 证据 | 判定 |
|---|---|---|---|
| N0 单命令基准 exit0 + 3 次中位偏差≤10% | 是（工具尚未存在） | 蓝图 §6；仓库无 `tools/benchmark_hot_path.py` | 可判定，但需先落地工具与固定 fixture |
| N0 fixture 含 expected phase/context | 是 | §6 要求空闲/技能/羁绊/宝物/胜/失败+面板/giveUp+面板/断线等 | 可判定；**失败+面板、真实断线**当前证据缺口见 B0（`missing_disconnect_modal`） |
| N0 原版 panel→input P50/P95（≥20 事件） | **弱/或不可证** | §6.6 允许 `insufficient_evidence`；视频为 1920×1080 桌面录屏（`C:\tmp\recordings\video_index_meta.json`），**光标/输入瞬时未必可见** | 门禁写法正确留了退路；但 N2 相对倍数门禁会退化 |
| N2 各 P95 耗时/match 次数/搜索像素 | 是（依赖 N0 schema） | §7 验收；需 N0 JSON 字段稳定 | **强依赖 N0 字段契约**，蓝图未冻结 schema 字段名 |
| N2 panel→input ≤原版 1.10×，否则绝对 P95≤800ms | 半自动 | §7；原版证据不足时走绝对阈值 | 绝对阈值可判；相对倍数可能永久 N/A |
| N2「无法解释的 tick >1s 为 0」 | **否（主观）** | §7 原文 | **不可判定**：缺“可解释”白名单（capture/OCR shadow/debug 等） |
| N2 ledger 与 N0 一致 | 是 | B0 ledger + `tools/compare_ledger.py`（`docs/baselines/B0_BASELINE.md`） | 可判定；N2 若改节奏/缓存必须 dry-run 对比 |
| S0 单测清单 | 是 | §8 具名测试 | 可判定；但多项 **缺真实 fixture**（断线弹窗 B0 已记 MISSING） |
| S0「模拟 46.9 秒恢复后仍有完整退出窗口」 | **弱** | §8 验收 | 魔法数 46.9 无来源/无场景定义，测试作者会各写各的 |
| O0 hash gate / repo_head / 分母 | 是（当前实现错误） | `evaluate_choice_ocr.py:665` 硬编码 `model_sha256_recorded=PASS`；`repo_head: None`（L435）；`for _round in range(2)` 两轮都进 `raw_samples`（L310–341）→ 报告分母 276≈双计（`B2_OCR_EVAL_...190231.md`） | 门禁方向对，**现状不能证伪篡改** |
| O1 52/52 contact sheet 人工审核 | **半自动** | §9 | 必须人工；应规定审核记录格式与“移出有效集”的机器可读标记 |
| O2 每类≥30、960×540≥10、session≤40% | 计数可自动；**960 来源不可 internally 满足** | 见 §4 | 判定脚本可写，但 **pass 条件外部阻塞** |
| O3 Top-1/recall/P95 | 是（O0/O1 后） | §11；与旧蓝图 B2-2 阈值一致 | 可判定 |
| O4 off/shadow ledger 等价 | 是 | 与旧 B3 不变量 #11/#12 一致 | 可判定 |
| L0 20 次建房 dry-run | 半自动+实机 | §13 | 需稳定 UIA 环境 |
| R0 S1–S4 长稳 | 实机/人工 | §15 | 发布门禁正确偏人工，但不应阻塞前期工程门禁 |

### 1.1 “无法证明”的高风险门禁（摘要）

1. **原版 panel→input 证据链**（§6/§7）：录屏是桌面 1080p，不一定有可观测点击光标；蓝图已允许 `insufficient_evidence`，但 N2 相对倍数门禁应在 N0 报告里 **显式作废**，只保留绝对 P95≤800ms，避免实现 agent 争论。
2. **960×540 正面板**（§10 O2）：现 manifest 正样本 960=0，仅 1 条 negative 960（`neg_live_e2e_...`）。两段新视频均为 1920×1080（meta SHA `2f6e6f50…` / `df68c4fd…`），**不能**当真实 960 游戏窗。
3. **真实断线弹窗**（S0/R0）：B0 明确 `missing_disconnect_modal` / Required Missing=1；S0 要求 `disconnect_uses_disconnect_path` 且不得 XFAIL——**缺素材则门禁无法绿**。
4. **“无法解释的 tick>1s”**：非形式化，必须改写为可计数规则。

---

## 2. 冲突与依赖

### 2.1 波次图 vs 任务包 vs 派工表（P0 文档冲突）

| 来源 | O0/O1 位置 | 证据 |
|---|---|---|
| §5 波次图 | O0 在 Wave0；**O1 在 Wave3**（N2/S0 之后） | L120–140 |
| §9 任务包 | **O0/O1 捆绑同一包** | L333+ |
| §18/§19 | 第一轮 OCR-EVAL 执行 **O0/O1** | L644、L663 |
| §5 禁令 | 禁止跳过 O0/O1 | L144 |

**冲突**：若按 §5，O1（正确 ROI 重评）要等 N2/S0；若按 §9/§19，O1 与 N0 并行且阻塞后续 O2。  
**影响**：OCR-EVAL 与后续 OCR-MODEL 边界不清；若有人按 Wave3 理解推迟 O1，会浪费并行窗口，且 O0 单独“修分母”却仍用错误 crop，报告仍不可信。

**N1**：仅出现在 §5（L126「N1 性能基准/录屏延迟」），**无任务包、无所有权、无验收**。§6 N0 已含录屏延迟。N1 应删除或并入 N0。

### 2.2 文件所有权碰撞

| 资源 | OCR-EVAL（§9） | DATA（§18） | 风险 |
|---|---|---|---|
| `fixtures/ocr_choices/manifest.json` | 「OCR fixtures manifest」 | 「fixtures manifest/标注」 | **并行双写** |
| crop 产物 / contact sheet | O1 要求重裁+审核 | D0 映射抽帧补样本 | 路径与 id 规则未统一 |
| `docs/baselines/B2_*` | O0/O1 重评 | D0 缺口表 | 低，可约定前缀 |

N2 vs S0：`mediator.py` 串行独占 —— **清晰**（§7/§8/§18）。  
L0 与 S0：L0 不得改 mediator —— **清晰**。  
PERF-BASE 只读 mediator —— **清晰**，与 OCR 无代码耦合。

### 2.3 O0/O1 重跑 B2 与 PERF-BASE 的隐式耦合

- **无生产代码耦合**（正确）。
- **有流程耦合**：N2 性能门禁比较的是 N0 baseline；OCR 重评不应改 `fixtures/baselines/action_ledger_b0.jsonl`。蓝图未写死「ledger 基线所有权=PERF-BASE/N0 only」。
- O1 重裁若改 crop 路径但不改 panel id，O3 前后对比仍可；若 DATA 同时改 session 切分规则，O0 分母定义会漂。

### 2.4 N2 → S0 交接条件

已写「必须在 N2 合并后开始」（§8），但 **缺少可机器检查的交接清单**，建议至少：
1. N2 commit 合并；
2. N0 对比报告：P95/matchTemplate/搜索像素门禁 PASS 或明确 waiver；
3. `compare_ledger.py` diff=0（ocr off）；
4. FrameEvidence 失效规则文档化（输入后必须失效）——否则 S0 恢复点击易踩陈旧缓存。

### 2.5 与旧蓝图一致性

| 主题 | 旧 B* | 新 N/S/O | 一致性 |
|---|---|---|---|
| OCR 不进 LIVE 直到离线门禁 | B2→B3 | O3→O4 | 一致 |
| off/shadow ledger 等价 | 不变量 11/12 | O4/P0 | 一致 |
| 技能永不非预设 | B4/B5 | P0 | 一致 |
| 数据每类≥30、双分辨率 | B2-1 | O2 | 一致，且新蓝图 **加严** session≤40% |
| 阶段命名 | B0–B10 | N/S/O/P/G/R | 映射未给对照表，执行 agent 易混 |
| 桌面 trace | B1-1 已部分落地 | 新蓝图仍写 incident 生产入口未启用 | 与代码一致：`desktop_app.py` 有 `set_trace`，**无 incident_dir** |

---

## 3. 遗漏（会影响目标但蓝图未钉死）

1. **`config/scenes.json` 的 fail 模板集**  
   - 现状：`fail.templates = ['fail','gameFail','giveUp']`（`config/scenes.json`）。  
   - 代码：`failure_hit = find_scene(disconnect) or find_scene(fail)`，若 `_selection_anchor` 存在则 **忽略失败**（`mediator.py:2732–2738`）。  
   - S0 要求 STRONG_FAIL 不含 giveUp、且强失败抢占面板——必须改 scenes + 优先级，但 §8 所有权只写 mediator/settings/scenes「可改」，**未把 scenes 模板拆分列为硬前置**。

2. **失败恢复无后置确认**  
   - 现状三步脚本：`FAIL_VISIBLE → WAIT_OK → WAIT_CLOSE`，**无锚点/点击成功/画面变化门闩**即可步进（`mediator.py:2711–2730`）。  
   - disconnect 与 fail 共用入口（L2710/L2748–2750）。  
   - 蓝图 S0.1 有原则，但未规定与现有 `_recovery_step` 的迁移/删除策略。

3. **Panel FSM 与失败抢占的实现顺序**  
   - 若先做面板会话再做抢占，中间态仍可能在失败画面点卡。  
   - 蓝图 S0 章节并列，**未强制**「抢占 → 恢复门闩 → deadline → panel FSM」。

4. **`cycle_num` / outcome / streak**  
   - `settings.cycle_num` 存在（`settings.py:103`），mediator **零引用**；仅有 `game_count` 回房自增（`mediator.py:2079–2080`）。  
   - 无 `round_deadline` / `success_count` / `failure_streak`。  
   - 蓝图有需求，但缺：默认 hard deadline 秒数、与现有 `game_timeout`/`query_timeout` 的关系表。

5. **trace / action ledger schema 扩展**  
   - S0 新增 phase/outcome/deadline/panel state 后，B0 ledger 字段是否扩展、对比工具是否忽略新字段——未定义。  
   - 风险：N2 后 ledger “一致”与 S0 后 ledger “一致”标准漂移。

6. **matcher 早停 API**  
   - `match_any_with_margin` 对 **全部 names** 做 `match_one`，再排序（`matcher.py:297–334`），**无首命中返回**。  
   - `match_one` 遍历全部 scales。  
   - N2.2 要求优先级早停，但未规定：`match_any(..., early_stop=True)` 还是 scene 级 `match_scenes` 扩展，也未规定与 margin 校验的兼容（早停后 second_best 可能缺失）。

7. **`find_blue_buttons` 全图 HSV**  
   - 先全帧 `cvtColor`+`inRange`，再 mask ROI（`matcher.py:166–180`）。  
   - N2 要求先裁 ROI——需改函数语义，蓝图未点名该函数为 N2 必改点。

8. **生产 incident**  
   - §8.5 要求桌面/API/CLI 都传 incident 目录；代码 archiver 可选，desktop 未接。  
   - 与 B1-2 重复，应标为 S0 或独立 B1 残留项，避免 RUNTIME/STABILITY 扯皮。

9. **主循环 cadence**  
   - 现状：`time.sleep(loop_sleep_ms/1000)` 固定 400ms（`mediator.py:3165`，`settings.loop_sleep_ms=400`）。  
   - 点击路径额外约 0.20+0.02+0.05+delay_ms（默认 120）≈390ms 量级（`keyboard_mouse.py:571–577`）——与蓝图 §3 一致。  
   - N2.3 改 cadence 与“点击等待只能在实验后减少”正确，但 **未定义可靠性实验协议**。

10. **同帧缓存与 `see()`**  
    - `see()` 每 tick `self._scene_cache.clear()`（L331），静态帧通过 `np.array_equal` 复用 Frame 对象（L348–358），`find_scene` 用 `id(frame)` 缓存。  
    - 蓝图 FrameEvidence 比现状更大；需明确是否替换 `_scene_cache` 还是并存，避免双重缓存语义。

---

## 4. 数据可行性（O2）

### 4.1 现状（与蓝图 §10 一致，已复核）

来源：`fixtures/ocr_choices/manifest.json`

| 项 | 数值 |
|---|---:|
| skill / bond / treasure / negative | 16 / 18 / 18 / 37 |
| 正面板 / valid slots | 52 / 155 |
| 正样本 session 数 | 7 |
| rec5_260808 占比 | **29/52 = 55.8%**（>40%） |
| 正样本 960×540 | **0** |
| 负样本 960×540 | 1 |
| 主要分辨率 | 1600×900（60）、1586×892（16）等 |
| 非词典 canonical 槽位数 | **19**（12–13 个唯一名，如 二星球/三星球/利刃海盗/吕岳…） |

蓝图缺口：skill−14、bond−12、treasure−12；每类 960−10；与事实一致。  
（注：必读路径 `docs/baselines/B2_STATUS.md` 实际文件名为 `B2_STATUS_20260810.md`。）

### 4.2 两段新录屏能补什么

| 资源 | 事实 |
|---|---|
| `20260810_214444.mp4` | 2778s，1920×1080，SHA `2f6e6f50…`，1fps 索引 `idx_a` 2778 帧 |
| `20260810_224848.mp4` | 2569s，1920×1080，SHA `df68c4fd…`，1fps 索引 `idx_b` 2569 帧 |

- **可达**：按 panel episode 从 1080p 桌面帧中裁出 **游戏客户区**（若实机窗口为 1600×900/相近），增加 skill/bond/treasure 面板数、新增 session、改善 rec5≤40%。  
- **不可达**：把桌面帧缩放成「真实 960×540 正面板」（蓝图 §10/§19 已禁止——正确）。  
- 因此 O2 全门禁在「仅这两段视频、无专门 960 采集」下 = **结构性格局 FAIL**。

### 4.3 缺口量级（保守下界）

| 目标 | 下界新增 |
|---|---:|
| 每类凑满 30 正面板 | **+38** 面板（14+12+12） |
| 每类 10 张真实 960 | **+30** 面板（若与上者重叠，则 +38 中至少 30 必须是 960 采集；若 1080 桌面只贡献 1600 窗，则 960 仍要另采 30） |
| session≤40% | 总正样本建议 ≥73 时 rec5=29 才≤40%；更稳妥是总样本≥90 且新 session 分散 |
| 非词典 19 槽 | 词典补齐或标 `unknown`（O0/D0 可做，不必等 960） |

**结论**：D0 用新视频做映射/去重/补 1600 级面板 **有价值**；但 **O2 不应作为 O3 的单一硬闸** 除非并行排期「960 实机采集」任务包（建议 D1/O2-res）。

### 4.4 OCR 评测可信度相关数据事实（支撑 O0/O1 优先级）

- name crop 尺寸高度偏大：约 **153/155 为 ≥200px 宽**（常见 272×108），仅「光法」样本出现 96×46 紧裁——与 §9「错误 ROI / 紧裁可识别光法」方向一致。  
- 但 cropper **没有名为 global fallback 的分支**（`crop_ocr_choices.py` 默认 `three_slot` 固定 ROI）；表述写成「45 个使用错误全局 fallback ROI」**易误导实现者去找不存在的 fallback 开关**。更准确：默认三槽 ROI 过松、未写 per-slot 紧 bbox、manifest **0 个 slot bbox 字段**。  
- `MODEL_MANIFEST.json` **非法 JSON**（mobile 与 server 对象间缺逗号，L16–17）。  
- 准确率分母被 2 round 放大；负面板未进“建议数=0”链（evaluator 对 negative 基本无门禁）。

---

## 5. 原版借鉴（§2）与 N2 / matcher API 匹配度

| §2 可借鉴点 | 代码现状 | N2 是否覆盖 | 匹配度 |
|---|---|---|---|
| 启动时模板载入内存 | `_TEMPLATE_CACHE` / `_SCALE_CACHE` 有 | 冷 preload P95≤250ms | 高 |
| 固定选卡 ROI | `_selection_anchor` ROI (0.20,0.45,0.80,0.80) | 缩小搜索空间 | 中（仍 6 尺度×多模板） |
| 优先级搜索 + 首次命中早停 | `match_any` **扫全 names** | 要求早停 | **API 缺口，N2 必须改 matcher** |
| 单尺度/主尺度 | 多处 0.85–1.2；`CACHED_SCALES` 8 档 | 主尺度+至多一邻域 | 高（方向对） |
| 命中后等消失、不扫全库 | mediator 选择逻辑分散 | 缓存+早停+后置确认更多在 S0 | 中 |
| 不要 UIA 点 CEF 选卡 | 局内走视觉+`act_click` | 不要求 UIA | 高 |
| 原版无可靠总预算 / 失败仍点卡 | 我们要 Fail-Closed | S0 | 高（原则对） |

**结论**：§2 与 N2 方向一致，但把“早停”只写在 mediator 任务里不够——**`match_any`/`match_one` 契约变更是 N2 的一等公民**，否则「选择 tick matchTemplate P95≤20」很难从 26–60+ 次量级（蓝图 §3）落下。

---

## 6. Top 阻塞项（按「返工 / 安全事故」排序）

| 优先级 | 阻塞项 | 类型 | 证据 | 若不处理的后果 |
|---:|---|---|---|---|
| **P0** | 失败与选择面板优先级 **与目标相反**；fail 场景含 `giveUp` | 安全事故 | `mediator.py:2732–2738`；`scenes.json` fail 含 giveUp；蓝图 §1/§8 | 失败画面继续选卡；S0 测试与生产行为对不上 |
| **P0** | 恢复脚本无后置确认；disconnect/fail 同路径 | 安全事故 | `mediator.py:2710–2730`；B0 断线素材缺失 | 假恢复、错点、卡死；S0 门禁无法真绿 |
| **P0** | O2 强制真实 960×540≥10/类，当前+两段 1080p **不可达** | 进度假闸/造假诱因 | manifest；video_index_meta；§10 | O3 永久阻塞或被缩放样本污染 |
| **P1** | §5 O1 波次 vs §9/§19 O0/O1 并行 **矛盾**；OCR-EVAL↔DATA manifest **双写** | 返工 | §5 L133 vs §9/§18 | 并行冲突、ROI 重评时机错误 |
| **P1** | N2 相对原版延迟门禁依赖可能失败的证据链；「无法解释 tick」不可判 | 验收扯皮 | §6/§7 | N2 PASS/FAIL 争议、反复重跑 |
| **P1** | matcher 无早停；N2 未定义 margin/早停兼容 API | 性能目标落空 | `matcher.py:297–334` | 只做 FrameEvidence 仍远超 20 次 match |
| **P1** | OCR 评测门禁可被绕过（非法 manifest JSON、hash 假 PASS、双 round 分母、负面板未测） | 错误决策 | MODEL_MANIFEST；evaluate L310/L435/L665 | 再次得出错误“模型域失配/可上线”结论 |
| **P2** | `cycle_num`/hard deadline/outcome 无运行时语义 | 长挂机事故 | settings vs mediator | 多局不停、卡死局续命（蓝图已点名） |
| **P2** | ledger/trace schema 在 N2/S0 后的冻结规则缺失 | 返工 | B0 ledger 字段集 | 对比工具误报、影子模式无法证明 |
| **P2** | S0「46.9s」等魔法验收无 fixture | 验收扯皮 | §8 | 测试各写各的 |
| **P3** | N1 有名无包；B*↔新命名无对照表 | 沟通成本 | §5 | agent 找错文档 |

---

## 7. 给后续实现的可执行建议（N2/S0 顺序与最小状态机）

1. **N0 冻结后再 N2**  
   冻结文件：`docs/baselines/N0_*.json` 字段（含 `match_calls`、`search_pixels`、分阶段耗时、fixture_id、commit、模板哈希）。宣布：原版延迟若 `insufficient_evidence`，则 N2 **只启用绝对 panel→input P95≤800ms**。ledger 基线所有权归 N0，OCR/DATA 禁止改 `action_ledger_b0.jsonl`。

2. **N2 最小状态机（只做证据，不改业务策略）**  
   `FrameEvidence{frame_ref, gen, ui_scale, hwnd, cache}`；`see()` 一次 context；输入成功/`gen++`/hwnd/scale 变化即总清空。  
   **先改 matcher**：`match_any` 支持按序早停（命中 threshold 即返回的模式）+ 主尺度优先；`find_blue_buttons` 先裁 ROI 再 HSV。  
   mediator 侧删除重复的 anchor/post_game/auto_task 扫描。灰度候选保持可选 N2.4。

3. **S0 强制顺序（同一 STABILITY agent，禁止颠倒）**  
   ① scenes：STRONG_FAIL=`fail`/`gameFail`（**移除 giveUp**），GIVEUP/disconnect 独立；  
   ② 全局抢占：连续两帧 STRONG_FAIL **优先于** selection/panel FSM（翻转 L2736–2738 语义）；  
   ③ `RECOVER_FAILURE` 最小步进：每步 `anchor∧input_ok∧(mutation∨post_anchor)`，FAIL 与 DISCONNECT 分脚本，总预算 60s；  
   ④ `round_deadline` 进 MAIN_LINE，面板动作不得续期；  
   ⑤ 再做 panel FSM（`CLOSED…COOLDOWN`）与 cycle_num/streak。  
   每步落地对应 §8 具名测试，**不得 XFAIL**；断线缺图则先补采集再标 S0 完成。

4. **并行数据/OCR 建议（不挡 N2）**  
   - OCR-EVAL：只修 O0（JSON/hash/repo_head/单次分母/负面板）+ O1 紧裁与 manifest **bbox 字段**；contact sheet 审核表机器可读。  
   - DATA：**只读/追加** session 映射与新 episode，写入前与 OCR-EVAL 约定 manifest 锁区或单写者。  
   - O2 拆分：`O2a` 数量/session/≤40%/truth 规范化（可用 1600 素材）；`O2b` 真实 960 采集（独立门禁，不阻塞 N2/S0）。

5. **N2/S0 与缓存安全一句规约**  
   “缓存命中不得延续旧帧动作授权”写入代码断言：`evidence.gen == tick.gen` 否则 zero-action。S0 恢复点击前必须 `invalidate()`。这是两边集成时最便宜的防炸点。

---

## 8. 维度覆盖检查（审查任务要求）

| # | 维度 | 本报告位置 |
|---|---|---|
| 1 | 门禁可判定性 | §1 |
| 2 | 冲突与依赖 | §2 |
| 3 | 遗漏 | §3 |
| 4 | 数据可行性 | §4 |
| 5 | 原版借鉴 vs matcher | §5 |
| 6 | 风险排序 Top 阻塞 | §6 |
| 7 | N2/S0 建议 | §7 |

---

## 9. 对主 agent 的直接建议

1. **先修蓝图矛盾再扩派 N2**：合并 O0/O1 到 Wave0；删除或并入 N1；写明 manifest 单写者；O2 拆 960 子门禁。  
2. **N2 可以在 N0+O0 工具链就绪后开工**，不必等 O2/960。  
3. **S0 是安全关键路径，优先级高于 OCR 准确率故事**；与“选择面板否决失败”相关的代码是当前最大实机风险。  
4. 不要把 B2 的 1.45% 当模型结论——与蓝图一致；但把根因写成「global fallback」不精确，应改成「默认三槽 ROI 过松 + 评测分母/负面板缺陷」。

---

## 10. 关键证据索引（路径/行号/蓝图节）

| 事实 | 位置 |
|---|---|
| 蓝图目标与 P0 缺口 | 新蓝图 §1 |
| 原版纠偏 | 新蓝图 §2 |
| 波次图 O1@Wave3 | 新蓝图 §5 L120–140 |
| N0/N2/S0/O*/D0 细则 | 新蓝图 §6–§10 |
| 派工 O0/O1 第一轮 | 新蓝图 §18–§19 |
| 旧蓝图数据门槛/不变量 | 旧蓝图 §3、§8 B2-1 |
| B0 ledger/断线缺失 | `docs/baselines/B0_BASELINE.md` |
| B2 状态与 960 缺口 | `docs/baselines/B2_STATUS_20260810.md` |
| 面板否决失败 | `mediator.py:2732–2738` |
| 恢复三步无门闩 | `mediator.py:2711–2730` |
| 固定 sleep 400ms | `mediator.py:3165`；`settings.py:109` |
| see 清 cache / 静态帧复用 | `mediator.py:331–358` |
| selection 6 尺度 | `mediator.py:533–561` |
| post_game 多模板全图 | `mediator.py:1087–1147` |
| match 无早停 | `matcher.py:297–334` |
| 蓝按钮全图 HSV | `matcher.py:166–180` |
| fail 含 giveUp | `config/scenes.json` |
| 评测双 round / 假 hash / 空 repo_head | `tools/evaluate_choice_ocr.py:310–341,435,665` |
| MODEL_MANIFEST 非法 JSON | `models/ocr/MODEL_MANIFEST.json:16–17` |
| manifest 统计 | `fixtures/ocr_choices/manifest.json` stats/entries |
| 视频索引 | `C:\tmp\recordings\video_index_meta.json` |
| desktop 有 trace 无 incident | `desktop_app.py` set_trace ~L165；无 incident 传参 |
| cycle_num 无运行时 | `settings.py:103` vs mediator 无引用 |

---

*本报告仅针对执行蓝图细则与仓库事实匹配度；不评价并行 agent 未合并 diff。*
