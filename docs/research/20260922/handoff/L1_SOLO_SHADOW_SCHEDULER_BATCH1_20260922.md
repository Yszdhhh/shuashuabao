【刷刷宝 · 单人动态调度 L1 第一批：影子决策器（只记录，不改线上动作）· 2026-09-22】用中文。

## 0. 身份与边界
- 你是唯一的 L1 实施 agent。不是唯一在仓库工作的人：不覆盖、不还原他人文件。
- 工作目录已由主架构建好（不要自己 worktree add，也不要在主目录改文件）：
  G:\刷刷宝\Worktrees\solo-shadow-scheduler-20260922
  分支 feat/solo-shadow-scheduler-20260922，起点 da566dd8d2320d55df0211a4b6f43d0e671789e5。开工前核对。
- 先读：
  1. G:\刷刷宝\GameScript-Local\AGENTS.md
  2. G:\刷刷宝\_facts_20260922\solo_strategy\DYNAMIC_SOLO_ARCHITECTURE_V1.md —— §11 是本任务的唯一语义来源
  3. G:\刷刷宝\_facts_20260922\solo_strategy\DYNAMIC_SIGNAL_EVIDENCE.md —— 各信号是否可用、file:line
  4. src/shuabao/observe_log.py 与 mediator.py 的 _observe_log/_observe_tick（约 16660–16700 行）—— 照这个模式接线
- 禁止：改任何现有决策/执行路径、改 choice_policy 行为、改阈值、加 OCR/模板匹配/输入、改 config 默认值、改 ui-v2、跑全量门禁（release_gate.py 由主架构跑）、打包、启动游戏、动桌面快捷方式。
- 语义不清时不要自选权重补齐，写 REVIEW_REQUIRED 并在交付里列问题。

## 1. 目标
实现 §11 的纯函数决策器，并以影子模式挂到单人 MAIN_LINE tick：每个事务边界算一次“动态调度会推荐什么”，与旧逻辑实际选了什么一起落盘。**线上动作 100% 不变。**
用途：今晚/明天的单人基线跑完后，用同一批局对比“旧逻辑实际选择”与“影子推荐”，测量分歧率与不可比率。

## 2. 交付物

### 2.1 src/shuabao/solo_scheduler.py（纯函数，只依赖标准库）
- 数据结构：
  - Fact：value + state ∈ {observed, unknown, missing, invalid} + source（file:line 或 trace 字段）+ observed_at（快照时间，从入参来）。未知永远不填 0。
  - ActionRecord：state ∈ {observed, requested, confirmed}；只有 confirmed 能推进持有/已购/已进化账目（§11.1）。
  - Snapshot：本局观测（木材、G/V 角标、已确认持有卡、当前事务、面板状态、主线 X-Y、失败事件、黑商余额/价格等，按 EVIDENCE 矩阵的可用性取值）、Owner 配置约束、now。
  - Candidate：action_id、目标/页面、legal + reject_reason、fact 引用、各币种成本（UNKNOWN_PRICE 与 model-derived 标注）、kind ∈ {READ_EXISTING_PANEL, PAID_DRAW, PAID_REFRESH, ...}、预期兑现、解决的瓶颈、执行器名、确认条件引用。
  - Decision：kind ∈ {CONTINUE_TRANSACTION, RECOMMEND, WAIT_OR_OBSERVE}；RECOMMEND 带 chosen + 未选替代项与原因；另有 review_required 标记与不可比集合。
- decide(snapshot) -> Decision：严格按 §11.3 A–F 的顺序：事务优先 → 合法性（消费类余额/价格不可信不授权该消费）→ 紧迫阻塞 → 支配比较（未知维度不算更好；不同币种不换算）→ 不可比时防饿死（§11.5）→ 缺信息且有安全读取入口才 OBSERVE，否则 WAIT / REVIEW_REQUIRED。
- 纯函数约束：不读磁盘/网络、不调 OCR、不读隐式时间、不发输入；相同快照结果相同。

### 2.2 src/shuabao/solo_shadow.py（适配器 + 记录器）
- build_snapshot(mediator) -> Snapshot：只用 getattr 读 Mediator 已有字段，不写回、不新增识别。读不到记 unknown/missing。字段来源以 EVIDENCE 矩阵为准：
  - 可用：木材余额、G/V 角标（带新鲜度，角标 sticky 语义照实标注）、已确认持有卡、进化事务锁、吞噬丹守卫（恒 False → 排除消费）、宝物禁拿名单。
  - 不可授权动作：主线 X-Y、失败归因、TAB mid_run、神器就绪、黑商余额不可读（→ 该消费 legal=False，reason=BALANCE_UNKNOWN）。
- 记录：jsonl，一行一个事务边界，含 snapshot 摘要、decision、旧逻辑本 tick 的实际选择（_observe_plan / 实际 act 名），round_id 与 observe_log 相同键。输出到 observe 目录下 solo_shadow_*.jsonl。
- 开关：SHUABAO_SOLO_SHADOW=1 才开，默认关；关时 Mediator 侧连模块都不导入（照 observe_log）。任何异常自己吞掉计数，连续 5 次永久关闭，绝不向主线抛。
- 只在 **单人** MAIN_LINE 且“事务边界”（无进行中事务，或事务刚结束）记录，不逐 tick 刷。蹭车模式不记录。

### 2.3 Mediator 接线（唯一允许改的生产文件，最小改动）
- 仿照 _observe_log/_observe_tick 加 _solo_shadow_log/_solo_shadow_tick，在 _tick_main_line 里紧跟 self._observe_tick() 调用。
- diff 里 mediator.py 除这两个方法和一行调用外不得有其他改动。

### 2.4 tools/summarize_solo_shadow.py
- 输入 observe 目录；输出每局：边界数、三类 decision 占比、RECOMMEND 与旧逻辑实际选择一致/分歧数、REVIEW_REQUIRED 数与原因 top、不可比率、各 reject_reason 计数。只统计，不下结论。

## 3. 测试（worktree 内跑，主目录 .venv 解释器）
1. tests/test_solo_scheduler_contract.py：§11.6 全部 11 个场景各一个用例，预期与“禁止结果”都要断言：
   进化待确认+技能角标大→CONTINUE_TRANSACTION；只积压增加→不产生紧迫标签/不恢复 >=8 抢占；挑战失败且短板未知→OBSERVE 或不可比；关键合法卡可支付+木材<300→仍是合法候选；A 支配 B→选 A；金币 vs 杀敌不可比→保留不可比不换算；刷新可付但目标买不起→不推荐刷新链；等价宝物长期未服务且事务结束→给宝物一次；选卡 ok 但未确认→持有不增加；TAB mid_run≠entry→只更新本局快照；丹可见但守卫关→排除消费。
   另加：相同快照两次 decide 结果完全相等；unknown 值不会被当 0 参与比较。
2. tests/test_solo_shadow_adapter.py：开关关闭时不导入模块；开启时用假 Mediator 生成快照，缺字段记 unknown；记录器异常 5 次后永久关闭且不抛；蹭车模式不写记录。
3. **行为不变证明**：同一组现有单人 L1 测试在 SHUABAO_SOLO_SHADOW=0 和 =1 下各跑一次，动作序列/结果一致（写成参数化测试或对比脚本，贴结果）。至少覆盖 tests/test_choice_policy.py、tests/test_p1_choice_fsm_contracts.py、tests/contract、以及 mediator 单人主线相关测试。
命令示例：
  G:\刷刷宝\GameScript-Local\.venv\Scripts\python.exe -m pytest tests/test_solo_scheduler_contract.py tests/test_solo_shadow_adapter.py tests/contract tests/test_choice_policy.py tests/test_p1_choice_fsm_contracts.py -q
不许 skip/xfail/改 GATE_BASELINE/删断言放行。git diff --check 无输出。

## 4. 已知裁决（主架构，照做）
- G8 黑商余额不可读：线上行为本批不改（单人仍按现有代码继续购买）；影子决策器按契约 §11.3B 判该消费 legal=False(BALANCE_UNKNOWN)。两者差异正是要测量的分歧，记录即可。
- 宝物负面：以 da566dd 的 negative_names + negative_patterns + treasure_allow_negative 为准（EVIDENCE 里“仓内仅 6 卡夹具”已过时，现为 20 卡）。
- 技能积压 >=8 抢占：影子里不复刻该硬阈值（§11.6 第 2 行）；旧逻辑照旧。
- 不引入任何新数值阈值。确需数值时写 REVIEW_REQUIRED 并列出。

## 5. 交付（回传主架构）
- 分支、commit SHA（可多个，不 amend）、diff stat；mediator.py 的 diff 全文。
- 各测试命令与数字、exit code；行为不变对比结果。
- 快照字段清单：字段 | 来源 file:line | 状态（observed/unknown 何时）| EVIDENCE 对应行。
- REVIEW_REQUIRED 清单与需主架构裁决的问题。
- 不 push、不合并；合并、identity、全量门禁由主架构做。完成即收工。
