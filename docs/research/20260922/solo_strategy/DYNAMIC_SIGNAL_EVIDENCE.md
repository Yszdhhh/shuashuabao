# 动态信号证据矩阵 V1（第一轮：只交矩阵+缺口）

- 日期：2026-09-22。角色：证据核验（非主架构，不做硬阈值方案、不选策略）。
- 只读基线：`G:\刷刷宝\GameScript-Local @ 9ed8b52`（已验 `git rev-parse HEAD` 一致，`git status` 干净，未改源码/配置，未跑门禁，未新开实机，未批量 OCR）。
- 契约依据：`DYNAMIC_SOLO_ARCHITECTURE_V1.md` §11（observed / requested / confirmed 三分；unknown/missing/invalid/observed 四态；未知不填 0）。
- 输入资料：`mechanics_solo/SOLO_MECHANICS_FACTS.md`、`treasure_debuff_frames/report.md + treasure_catalog.md`、`TASK_H_OBSERVATION_RUN_20260920.md`、`SOLO_DECISION_SPEC_DRAFT.md`。
- 本轮禁令遵守：点击 ok≠获得；挑战失败≠缺技能；攻击力≠DPS；余额差≠收入；缺失记 unknown/NOT_FOUND，不填 0。
- 行号均为本 SHA 下实测 `git grep` / `Read` 行号。

## 总判（一句话）

- 可直接支持动态比较的已接线信号：木材余额、G/V 角标（带新鲜度条件）、已确认持有→合成优先、进化事务锁、吞噬丹恒 False 守卫、宝物 19+2 禁拿名单（帧级）。
- 不可直接授权动作的：主线 X-Y 同帧对齐、失败→战力归因、TAB mid_run 实时属性、吞噬丹可用、神器效果就绪、杀敌单价/刷新后购买预算闭环、DPS/收入率。
- TASK_H shadow/choice 基线在本基线不存在（探针文件不在本树），记 NOT_FOUND。

---

## 组1：主线 / 失败 / HUD 资源 / 角标同时间对齐 + TASK_H 基线

| 信号 | 生产 producer / 消费 consumer file:line @9ed8b52 | 实际原帧 / trace | n 及单位 | 新鲜度 / 缺失行为 | 可支持什么判断 | 缺口 |  verdict |
|---|---|---|---|---|---|---|---|
| 主线 X-Y | prod `mediator.py:9029 _read_main_line_stage`（ROI `9003`，RE `9004`，10s 节流 `9034-9036`，OCR worker `shadow_predict`）；cons `mediator.py:9006 _record_main_line_stage`，`9076`（close-after-5-5），`17906`（每 tick 扫描） | hitch trace `phase_after=MAIN_LINE` 连续段；`extract_ocr_panels stage_*` 全空（`SOLO_MECHANICS_FACTS §1.3`） | n=45 局内段（主包 10），中位 589s；X-Y token **0 命中** | 10s 缓存，无帧绑定；`now < _main_line_ocr_next_at` 直接回 None（missing，非 0）；换局不重置的引用不可沿用 | 仅支持“读到即 observed (X,Y,frame,now)”；读不到=unknown，不支持停滞归因 | 主线 ROI 实机时间戳缺失（P0）；KB G1/G2/G3 仅 n=1~3（5-5@11:00、5-6@5:01→6-1@7:01、4-5 停滞 8:52–16:24） | **FAIL** |
| 主线失败文字 | prod 同上 `9029` → `9022 _record_main_line_failure`（子串 `主线挑战失败/提升实力后再来挑战`）；cons `4437 _MAIN_LINE_STALL_SECONDS=90.0`，`4497 _main_line_stalled`，`4500 _skill_backlog_force`（stalled→1，否则 4） | 主包 `s0.round_outcome` VICTORY 3 / TIMEOUT 3（outcome_changes n=6），manifest `victory=6/failure=4`；**失败文字同帧原帧在给定资料内 NOT_FOUND** | n=6 次 outcome 变化；单位：局/次 | 失败一旦写入 `_main_line_stall_reason=challenge_failure` 即锁存，无自动过期；同关 90s 判 `same_stage`（`9014-9020`），不区分战斗/面板/不可见时间 | 仅支持“真实失败事件 observed”；**不支持“失败=缺技能/缺输出/缺生存”**（契约 §11.3C） | 失败帧→战力短板映射无证据；同关 90s 需拆有效战斗时间 | **HOLD** |
| 木材余额 | prod `mediator.py:4401 _hud_wood_balance`（ROI `4384`）经 `6174 _hud_counter`（指纹缓存+OCR `shadow_predict`，多值/低分→None）；cons `4419 _refresh_solo_signals`，`4628 _bond_step_blocked`，`4543 _solo_plan_panel` | `20260918_210044` 13 次采样 5 次下降（总降 332 / 总涨 968，单位：木材个数）；KB 反推总入 ~4.5–5.5/s（含脉冲） | n=13 采样；单位：木材个数，3.0s 周期 | `_WOOD_READ_INTERVAL_S=3.0`（`4385`）；`_refresh` 内木材**无条件覆盖**（旧值可被 None 覆盖，`4424`），与角标 sticky 语义不对称 | 支持“当前可支付比较”（`wood >= price`）；**余额差≠收入**（领取/买卖/多事件单列要求，V1 §8） | 无每 3s HUD 快照入 trace；F/刷新点击前后各 1 帧缺失（P0） | **HOLD** |
| G 技能 / V 宝物角标 | prod `6269 _hud_skill_points`（ROI `6234`）、`6273 _hud_treasure_pending`（ROI `6235`）经 `6254 _hud_badge`（黄字预检+`_hud_counter`，`_BADGE_MIN_SCORE=0.6`，`max_value=99`）；cons 同木材行 + `4574-4608` 抢占分支 | live 000229：G 积压 32 未丢（无上限佐证）；hitch 主包 `skill_refresh_btn panel 221`，`OpenTreasurePanel 104` / 实拿 44+18，`giveUp 275` | n 如左；单位：角标个数 | 角标**沿用旧值**（按钮遮挡时不更新，`4425-4432`；None 仅到首次可见）；`skill==0/treasure==0` 才跳过，未读从不跳过（`4618-4623`） | 支持“有/无待处理机会”（`>0`），支持 V 一次服务机会（`4589`）；**不支持“积压数=战力欠账”**（V1 验收：仅积压增加不得产生紧迫标签） | 角标→可学习/可领取合法性无链（需面板 FSM 确认）；`>=8` 硬抢占（`4575-4582`）与 Owner 零机会成本冲突待 TASK_H 裁决 | **HOLD** |
| 同时间对齐 | 上述三生产者周期不同（木/G/V 3s，X-Y 10s），同一 tick 内**非原子快照**；`17962-17966` 神器与 `17969-17977` 吞噬丹在 `HUD_ONLY` 下先于面板，`17998` 面板后于机会动作 | 无同帧四信号联合 trace（hitch 主证据 bond OCR=0，treasure kind=122 仅宝物） | — | 任一不可信即该维度 unknown；消费类余额/价格不可信不得授权该消费（契约 §11.3B） | 仅支持“分信号独立 observed + 事件失效”（花费后余额重读，换页坐标失效，换局全失效） | 缺 `value/source/frame/observed_at/round_id` 五元组快照结构 | **FAIL**（对齐维度） |
| TASK_H shadow/choice 基线 | 任务要求探针：`runtime_core_shadow.py` + mediator 三处接线（`_tick_main_line` 顶、`choose_action` 后含 `downgraded_from/downgrade_reason`）+ `tools/summarize_runtime_core_shadow.py` + `tests/runtime_core_adapter/`（`TASK_H §移植`） | **NOT_FOUND**：本基线 `tools/summarize_runtime_core_shadow.py` 无文件，`src/shuabao/runtime_core*` 无文件；`ls-files` 仅旧 `docs/baselines/O4/R0 shadow.jsonl`（20260811，非本任务基线臂） | n=0；单位：tick/choice 行 | 探针从未在本树实机跑过（TASK_H 明示）；`choice_*.jsonl` 与 `run.log [L1] 选卡策略/羁绊确认获得` 逐条对账无数据 | **仅支持“基线缺失”判断**；不支持任何“影子分歧/转化率/开 F 产出”结论 | 需按 TASK_H 在 GT 新分支新工作树跑 3–5 局后补：木材净囤积/峰值/高位时长、花费÷进账、F/G/其他占比、每次开 F 产出（本轮不跑） | **FAIL** |
| Boss 点击反例 | trace 字段 `mediator.py:14029-14047 click_ok/post_confirm`，`15197`，`15317-15337 _trace_post_confirm`，`15783 True / 15829 False` | V1 §11.1 引用的 `click:17年兽 ok=true 但 post_confirm 为空`为架构侧反例；**本轮未在给定 hitch 包内复现到该事件行**，不独立断言 | — | requested（ok=true）≠ confirmed（后置确认）；动态调度不得以 requested 更新战力/消耗/目标 | 支持“点击被接受≠获得”纪律检查 | Boss 路径真实 `post_confirm` 映射与原帧回归另验（V1 §11.6） | **HOLD** |

---

## 组2：TAB（entry / mid_run、英雄与时间上下文、字段覆盖、负值/上限异常）

| 信号 | 生产 producer / 消费 consumer file:line @9ed8b52 | 实际原帧 / trace | n 及单位 | 新鲜度 / 缺失行为 | 可支持什么判断 | 缺口 |
|---|---|---|---|---|---|---|
| 解析器 | prod `player_profile.py:288 parse_attr_panel`（数字-only；`317-320` 超 cap→`rejected_over_cap`，`321-324` 负值→`rejected_bad_range`，`331` 缺失→`missing`）；schema `136 attr_schema`（KB attributes+special+硬顶，`146-155` 别名）；`23 MIN_CONF=0.60` | 给定三资料内 **TAB 原帧 0**（`mechanics_solo/out` 51 个文件为 aggregate/summary/ocrpanels，无 TAB；treasure 688 面板为宝物三选；`SOLO_MECHANICS_FACTS` 全文无 TAB 命中） | n=0 帧；单位：帧 | parser 为纯函数，无时间/局绑定；`conf<min_conf→unverified`，超顶/负值→value=None + reason（**不是 0**） | 支持“离线审计解析契约”（负值与超顶被丢弃的语义）；**不支持直接当调度信号**（V1 §1 TAB 行） | 需补：entry 与 mid_run 原帧各 ≥1（含英雄形态+波次/时钟/杀敌同帧） |
| 窗口分类 | prod `player_profile.py:262 classify_tab_window`（`_MID_RUN_HINTS`/`wave>=2`/`kills>=20`/`clock>=60s`→mid_run；`_ENTRY_MAX_CLOCK_S=20`/`_ENTRY_MAX_KILLS=5`，两条件中 ≥2→entry；否则 unknown）；消费 `398 build_poster` | 同上 NOT_FOUND | 阈值单位：s / 杀敌数 / 波次 | unknown 不进画像（`262-285` fail-closed） | 支持“entry vs mid_run vs unknown”三分法 | 分类阈值（20s/5杀/20杀/60s）本身无实机标定引用 |
| 画像 vs 本局 | prod `398 build_poster`：`413 use_tab = (window==entry)`，mid_run/unknown 时 `tab_highlights` 全 None；`438 verified_skill_levels` 仅 verified 整级 | 同上 NOT_FOUND | — | mid_run 不覆盖 entry（设计已保证）；进化后英雄属性失效语义在 V1 §11.4，代码侧无自动失效 | 支持“entry=开局底子，run_attributes=本局快照（另存）”结构；**TAB 缺失/旧读数/跨局不得授权依赖该属性的操作**（V1 验收 #8） | `entry_profile / run_attributes` 双存储与进化失效事件在代码侧无对应字段（属 L1 实施范围，本轮仅记缺口） |
| 字段覆盖/异常 | `cap` 来自 KB `caps`（`139-144`）；`136-184` 跳过 `save_attr_colors`；`136` 注释“TAB 面板字段：KB attributes + special” | 同上 NOT_FOUND | — | 超顶/负值保存原文+reason（契约要求“先保存原文与 rejected 原因，再由字段机制判断”——parser 已产出 reason，调用方未见落盘引用） | 支持“异常≠0、需字段机制二次判断”（debuff/上限变化场景下 parser 当前会丢弃合法极端值） | debuff 下合法负值、上限变化后合法大值的字段级真值表缺失；**不得全局放宽解析边界**（V1 §7） |

组2总判：**HOLD**（解析契约已钉死、可离线复用；但 entry/mid_run 原帧、英雄+时间上下文、字段覆盖cross-check 在给定资料内全部 NOT_FOUND，不启动新实机）。

---

## 组3：持有 / 吞噬 / 合成 / 英雄技能属性关系（卡头 vs 卡名；伤害公式不补）

| 信号 | 生产 producer / 消费 consumer file:line @9ed8b52 | 实际原帧 / trace | n 及单位 | 新鲜度 / 缺失行为 | 可支持什么判断 | 缺口 | verdict |
|---|---|---|---|---|---|---|---|
| 已确认持有 | prod `mediator.py:3403 _commit_pending_bond_cards`（WAIT_MUTATION 见变化/面板消失→确认）→ `3411 _confirmed_bond_cards`（tuple 含重复）；cons `choice_policy` owned（`1185/1192` 计数）、`4506-4511 _stall_combat_bond_slots`、`3415 _bond_base_progress_pending`（80% 口径） | hitch 主包 bond OCR=0（蹭车不做羁绊三选，`SOLO_MECHANICS_FACTS §3.4`）；持有链证据靠 09-17 合同 + lab（门 4→中环 4→次环 3→UR 3，chain confirmed，lab 152022/152437） | lab n=2 链；单位：张（重复计数） | 只有 confirmed 才进账；`requested`（点击 ok）不进账（V1 §11.1）；`_bond_cards_pending` 未提交前不计持有 | 支持“持有账目推进合成/差1张秒选”（`choice_policy.py:1706 _match_synthesis`，`1370/1489` 调用） | hitch 基线内无 solo 羁绊确认事件可供对账（待 TASK_H choice 基线） | **HOLD** |
| 卡头 (x/y) vs 卡名 | prod 卡头进度 `_BOND_PROGRESS_RE`（`choice_policy.py:135`，`1114/1219` 使用）；prod 卡名 `mediator.py:3183 _fill_bond_slots_by_title_template`（标题层主导）、`3053` 调用；cons `1150 same_bond_identity`、`1200 _is_uncompleted_merge_upgrade` | 09-17：1796 次羁绊读数**卡名命中 0**；视频双信号 need 提案 n=9（藏宝图 3、身法 3 等）+ catalog 77 needs；海盗启动卡=藏宝图(三) need=3 三源一致 | n=1796 读数 / 9 need 提案 / 77 catalog；单位：槽位/套装 | 卡名不可读→fail-closed 不得点（SPEC 拟议，代码侧标题层仍主导） | 支持“卡头=进度/分类元数据（差1张加权），卡名=点击真值”分工判断；**不支持用卡头 OCR 直接授权点击** | 生产卡名识别缺口（待补采，非本轮改码）；生命 need 4 vs 3、修仙启动卡分歧仍并存 | **HOLD** |
| 吞噬关系 | 机制：门卡散件带经济（如力量之源木材+50 并开池，SPEC §1.2）；部分卡条件吞噬（击杀 200 / 时间 60s，示例非穷尽，V1 §8 由 Owner 口述）；代码：吞噬目标由游戏决定（`5126-5161` 只定何时用丹） | 09-17 n=2（均吞中间紫框）；984fd04 局买 11 颗一颗没用上 | n=2；单位：次 | 吞噬确认以后置 `WAIT_SWALLOW_PILL_CONFIRM`（`5154-5162`，以 bond 栏 occupancy 下降为 verifier，2s 截止）为准 | 支持“何时用丹”时机判断；**不支持“吞哪张带来什么收益”预估** | “吞哪张”扩大 n 缺失（P1）；持有→吞噬→战力链无归因 | **HOLD** |
| 英雄技能属性关系 | prod 画像技能 `101 skill_families`（16 系，archive unlocks+catalog 别名）；属性 schema（上组）；cons `build_poster top_skills`（verified 整级前 5） | G2/G3 对照（G2 点技能后过关 / G3 角标 24 且 4-5 卡死）为 n=1 级对照，非因果 | — | 技能配置是偏好与边界，画面是观测；冲突不静默改流派（V1 §4） | 支持“作用方向匹配/避免无效增益”；**攻击力≠DPS；敏捷/智力递减公式 unknown，不补写**（V1 §7） | 伤害公式、攻速/暴击/急速联合判断所需字段真值缺失 | **FAIL**（公式维度；其余 HOLD） |

---

## 组4：进化 / 神器 / 英雄卡 / 武器 / 吞噬丹（目标识别 + 业务后置；守卫恒 False）

| 信号 | 生产 producer / 消费 consumer file:line @9ed8b52 | 实际原帧 / trace | n 及单位 | 新鲜度 / 缺失行为 | 可支持什么判断 | 缺口 | verdict |
|---|---|---|---|---|---|---|---|
| 进化 | 目标 `4979 _has_evolve_button` / `4949 _evolve_button_hit`（金色条优先，模板 `click_evolve/click_evolve_v2` 0.75）；事务 `5020 _tick_evolve_feedback_pending`（2s 窗，≥3 次无反馈放弃本轮进化，`5039-5043`）、`5047 _maybe_opportunistic_evolve`（5s 冷却）；锁 `17942-17953`（feedback/awaiting 时独占，hero pick 15s 超时释放） | 进化点击后置确认语义（P0-2 164929/215302 注记，`18054-18058`）；同按钮持续出现≠新机会（V1 验收 #5 语义，代码侧以 feedback/awaiting 区分） | 冷却单位：s（5/15/2）；重试单位：次（≤3） | 事务中禁切走（`17942`）；确认后（`5024-5031` →awaiting_hero_pick）重新评价 | 支持“真实入口+未处理新机会+可确认效果”三件套才可列候选；支持 CONTINUE_TRANSACTION | 新机会去重（同按钮持续出现）判据需帧级定义 | **PASS**（事务语义）/ **HOLD**（新机会定义） |
| 神器 | 目标 `4211 _slot_has_artifact`（图标存在性）；执行 `4231 _maybe_fire_artifacts`（`auto_artifact` 门，首火推迟 30s，CD `max(30,artifact_cd=120)`，槽位 `artifact_slots=2`→Q/W）；消费 `17963`（HUD 机会）+ `18043`（artifact 轮换步） | 无神器效果/就绪/释放成功三元对齐帧（给定资料内 NOT_FOUND） | CD 单位：s；槽位单位：个（1–3） | 图标存在+配置 CD 到期**只是可检查条件**；`act_click` 被拒不推进 CD（`4267-4270`）；**无战斗收益后置** | 仅支持“可检查”；**不支持“已识别效果/真实就绪/释放成功/战斗收益”**（V1 §1 神器行） | 效果识别、就绪真值、释放→伤害归因全部缺失 | **FAIL**（效果维度） |
| 英雄卡 | 目标 `5171/6548 find hero_card_item`（0.65，ROI 物品栏）；门禁 `6535 _maybe_opportunistic_hero_card`：`_evolve_ok_this_cycle=True` + 无 evolve button + 无 feedback/awaiting + 4s CD；后置 `6559-6566 WAIT_HERO_CHOICE`（3s，verifier=进化三选出现） | 门禁语义完整；实机使用→三选对齐帧在给定资料内 NOT_FOUND | CD/截止单位：s（4/3） | 未确认进化完成前绝对零输入（`6541`）；不能用“没识别到按钮”代替“已成功” | 支持“进化完成后才可用”排序约束 | 使用成功率/三选确认事件缺失 |
| 武器（1 号格） | 目标 `_equipment_slot_one_occupied` + 授权 `5064 _slot1_upgrade_authorized`（8s cadence + 占位 + `equipment_fsm.can_use(1)`）；执行 `5081 _maybe_opportunistic_upgrade_slot1`（core-development 门 `5083`，merchant VERIFYING 互斥，右键最大升级，走 `equipment_fsm.begin` 租约）+ `18011` 机会路径 | 词缀弹窗异步互斥教训（trace 203910 tick259-260，evolve 先于 equipment 注释 `4278-4281`）；租约观察 `_tick_equipment_pending`（`17940`） | CD 单位：s（8）；租约单位：s（`ui_action_interval_s`） | 保留进化/词缀先后约束（evolve 先 equipment 后）；`equipment_fsm` 未授权零输入 | 支持“升级确能补短板且已授权”才列候选 | 升级→短板解除归因缺失（需战斗反馈） |
| 吞噬丹（普通随机吞噬） | 守卫 `5325 _can_consume_inventory_swallow_pill` **恒 `False`**（注释：无可靠分槽身份，occupancy+opt-in 不能证无保护卡）；消费 `5115 _maybe_use_inventory_item`（`5130` 与门，`5142` 同点 ≤5、`5166` 每 visit ≤2，`5125` 公共背包互斥）+ 购买侧 `6361 danGif 0.90` 识别（购买≠消费，`6437-6439` 注释）；机会路径 `17969-17977`（因守卫恒 False 实际不可达） | 09-17 买 11 颗用 0 颗；hitch swallow_pill 点击 n=44（购买/使用链路点击，manifest `merchant_devour_acquired=44`） | n=44 点击；单位：次（**点击≠获得≠使用成功**） | 守卫恒 False→消费路径零输入（fail-closed）；满仓不得绕过守卫（V1 验收 #11） | 支持“普通吞噬丹**当前不可用**，排除消费候选” | “保护卡身份不明”消除条件无定义（需分槽身份识别，P1 别册） |

组4总判：守卫语义 **PASS**（恒 False 已钉死，不得判可用）；进化事务 **PASS**（锁与后置完整）；神器效果/英雄卡确认/武器归因 **HOLD～FAIL**（见各行）。

---

## 组5：币种价格 / 黑商刷新后购买预算 / 宝物原帧→仓内夹具差距

| 信号 | 生产 producer / 消费 consumer file:line @9ed8b52 | 实际原帧 / trace | n 及单位 | 新鲜度 / 缺失行为 | 可支持什么判断 | 缺口 | verdict |
|---|---|---|---|---|---|---|---|
| F 抽价格 | 模型 `4454 _bond_next_price`（`picks>=4→100，否则 20*(picks+1)`）；刷新 `4458 _bond_refresh_price`（`4452 (40,60,80,100)` 档）；cons `4631 wood<price→blocked`，`4463 _bond_refresh_affordable`（wood 不可读不授权刷新） | 实机：F 20→80→100 封顶（约 1min 后，G3 提示框多点）；羁绊刷新 **40 OCR 实证**（多局面板）；60/80/100 递增仅推断 | 单位：木材个数/次；n：多局面板（未逐事件计数） | `_bond_picks_round` 为本局计数，换局重置（`4407`）；`UNKNOWN_PRICE 不填 0`（V1 §11.4） | 支持“已展示价格+当前可读余额”比较；60/80/100 档**不支持当确定价** | F/刷新点击前后余额帧未逐事件绑定（P0） | **HOLD** |
| 杀敌价（黑商） | 代码价 `4295 吞噬丹 400` / `4296 木材 300` / `4297 刷新 350` / `4300-4302 刷新+丹预留 750`；余额 prod `6277 _merchant_kill_balance`（ROI `4293`，`_MIN_SCORE 0.95`，`6316`）；门 `6328 _merchant_kill_budget_allows` | 实机：5 槽货架（slot 点击 12/8/6/11/7，n=44）；`BlackMerchant-refresh` 主包 87（15 包 ~360）；价签 50–500 杀敌不等 + 5折/8折标签（09-17 `merchant_prices` 零散帧）；免费刷新 180s | n=87 刷新 / 44 吞丹点击；单位：杀敌数/次 | 余额指纹缓存（`6291-6297` 同指纹沿用）；余额 None+单人→**按已验证控件继续（授权购买）**（`6336-6341`），hitch 才 fail-closed；`_BUDGET_RECHECK 15s`（`4303`） | 支持“余额可信且 ≥required 才授权”；**余额不可读时的单人继续≠已验证支付能力**（契约 §11.3B 下应视为 unknown，当前代码行为已记录为偏差） | 单价逐事件 HUD 对齐缺失（F 抽与刷新夹击杀收入，`SOLO_MECHANICS_FACTS §2.4`）；折扣率未量化；刷新后购买预算闭环（刷新可支付但买不起目标→不刷，V1 验收 #6）仅在 `6486-6493` 实现刷新侧，购买侧仍依赖代码价 | **HOLD**（偏 FAIL：预算门在单人非 fail-closed） |
| 金币 / 杀敌收入 | 无金币余额 prod（`grep gold_balance` 本树 0 命中）；杀敌仅余额 prod（上行），无收入流 prod | 木材会降（5/13 下降）；金币被动 74→104/s、杀敌被动 2.5→3.5/s 均为 KB 引用非本批对齐 | — | 缺失=unknown；**余额差≠收入** | 不支持任何收入率/效率比（V1 §8：支出÷收入仅账目完整时报告；开局存量不得叫效率） | 每 3s 三币种快照 + 购买/领取事件绑定全部缺失（P0） | **FAIL** |
| 宝物原帧→仓内夹具 | prod 帧侧：report 25 帧/13 卡（全 1600x900，槽位+描述逐字，红字规则 T=40，`H≤10\|H≥170 & S>120 & V>120`，正样本 10/10，负样本 0/34）；cons 仓侧：`choice_policy.json:47-73 negative_patterns/names` + `choice_policy.py:1650 is_negative_treasure` | 去重 96 卡（负面 19 / 存疑 2 / 正面 42 / 套装 33；亲眼 21 卡）；report §4：fixtures 仅 `treasure_negative 6 卡 + double_rune_3card（提高上限仅卡名级）`；本次补 `提高上限/命运骰子` 等 | 688 面板（主包 134 + C-tmp 554）；单位：面板/卡名/帧 | 红筛精确率低为设计内取舍（候选 335 经 OCR+人眼终审）；`allow_negative` 逐卡放行最高优（`choice_policy.json:74-75`） | 支持“19+2 默认禁拿”名单判断（描述原文+帧路径已齐）；已命中：贪婪契约（将恒定）、提高上限（攻击间隔）、杀敌梭哈等；**缺口 8 类**：恶魔契约`无法再升级`≠`无法升级`、命运骰子`增幅-15%`、登神长阶`全属性-35%`、玻璃大炮`受到的所有伤害提高`、三极`扣除`、木/金梭哈`XX清0`、经验压制`经验-70%`、诅咒之力`恢复效果-/护甲-` | patterns 只增不删落地须夹具+`release_gate`（本轮不改）；诅咒之力维持不交付但策略须拦；经验压制 2 星尾行被卡框遮挡；混乱转换/洗牌存疑待裁 | **FAIL**（夹具差距维度；名单维度 PASS） |

---

## 缺口清单（按主架构 L1 排期用，不含新阈值建议）

| ID | 缺口 | 阻塞的判断 | 补采（只读/离线，不新开实机、不批量 OCR） |
|---|---|---|---|
| G1 | 主线 X-Y 时间戳（45 段 0 OCR） | 停滞/失败→战力归因、有效战斗时间 | 局内 HUD 任务栏 ROI 周期 OCR + trace `main_stage` 字段（P0，既有帧重提，不新录） |
| G2 | 三币种+G/V 角标时序快照（每 3s）+ F/刷新/购买前后各 1 帧 | 收入率、单价对齐、刷新后购买预算闭环 | 既有包重提 HUD 快照；单商品独占购买事件（如有） |
| G3 | 羁绊面板 OCR 进 trace（卡头+卡名）+ Shadow `choice_*.jsonl` | 持有/差1张/启动卡优先、开 F 产出 | TASK_H 3–5 局（Owner 在场 UAC 后）；本基线记 NOT_FOUND |
| G4 | 宝物 8 类语义夹具（§5）+ 25 帧入库对照 | 负面拦截完整性 | 25 帧→夹具映射表（离线列，不改仓） |
| G5 | TAB entry/mid_run 原帧（含英雄形态+波次/时钟/杀敌同帧） | 实时属性快照、debuff/上限字段真值 | 既有语料检索；无则记 NOT_FOUND 待 Owner 供帧 |
| G6 | 吞噬“吞哪张”扩大 n + 保护卡分槽身份定义 | 守卫解除条件 | 有意识排布栏位后用丹的前后帧（新实机需另批，本轮不跑） |
| G7 | 神器效果/就绪/释放→战斗归因 | 神器候选合法性 | 效果文本帧 + CD 就绪帧 + 释放前后战斗帧 |
| G8 | 单人黑商余额不可读时继续购买的语义裁决 | 预算门 fail-closed 一致性 | 主架构裁决（代码 `6336-6341` vs 契约 §11.3B），无需新数据 |

## 交付声明

- 本文件仅为证据矩阵；未提出任何新阈值/权重/调度器，未改源码/配置/夹具，未跑门禁，未新开实机。
- 未动他人文件；本目录另一文件 `SOLO_DECISION_SPEC_DRAFT.md` 保持原样。
- 下一步由主架构据本矩阵给唯一 L1 实施 agent 精确任务；L1 接入前须先满足 V1 §10C（影子记录与真实帧/动作逐条对齐）。
