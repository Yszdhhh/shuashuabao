# 蹭车架构与逻辑冲突审查（2026-09-12）

审查基线：`f4c847c79b6a1ebf111d48c7c3db9d0bac5e7b97`，工作树 `G:\刷刷宝\Worktrees\prod-source-3904913-20260911`。开始时工作树干净。按交接 §6 的 A–H 顺序检查；不查看截图、不运行实机、不修改实机 harness、不 push、不更改快捷方式。

## 修复落实复核（2026-09-12，工作树未提交）

初始审查确认的生产缺陷 R1–R5 已按最小范围修复，原 11 个严格 xfail 均已转为正常断言，并扩充为 19 个 Core/LIVE 或真实帧回归，全部通过。R6 位于 `GameScript-Local` 实机 harness，受本任务约束没有修改；它仍是唯一明确未落实的代码修复点。秘境/团本没有当前版本真实样本，因此“识别进入后不主动退出”的视觉前提仍不能标为实机验证通过。

| 审查项 | 修复后结论 | 当前证据 |
|---|---|---|
| A 多义状态 | 仍有结构风险；已消除 R5 的跨页预算冲突 | `mediator.py:_tick_main_line` 在读取传家宝预算前按页面重置 `boss_challenge_*`（约 `14202–14220`）；显式战后枚举仍按 H 的渐进方案后续处理 |
| B 每局重置 | 已修复已证实的行为泄漏 | `Mediator.set_phase` 的自然新局块约 `7891–8010` 清空 panel episode、fingerprint、anchor 及 `_pending_action`；C2 状态隔离合同纳入 `_hitch_postgame_started_at` |
| C 早返回 | 已修复 R1/R2；未发现新增无界分支 | round deadline 位于聊天/压力等可重复输入之前（约 `13666`）；乘客战后事务增加固定 300s 总预算（约 `13675–13694`），成功发送 Continue/X/NPC 不续期 |
| D 监督器/计时 | 已修复审查反例；秘境绝对不退出与整局 3600s 的优先级仍需真实样本后定约 | `test_swallowed_victory_clicks_leave_before_whole_round_deadline`、`test_expired_round_deadline_preempts_persistent_pressure_button` 在 Core/LIVE 通过 |
| E LIVE 分叉 | 本轮修复在 LIVE 生效 | `runtime_mediator.Mediator._tick_main_line` 先调用 Core；R1/R2/R3/R5 均参数化 Core/LIVE 通过 |
| F `move` | 生产边界无新增问题；harness 包装缺口仍存在 | 生产 `act_move` 继续经过 gate/finish/trace；`GameScript-Local/tools/live_scenario_capture.py:RecordingInputExecutor` 未包装 `move`，本任务未改外部目录 |
| G 分类矩阵 | 有 2 张 ROOM+HUD 重叠，但完整 LIVE tick 均由游戏上下文持有 | `classifier_matrix.csv` 6036 行、0 分类异常；两条重叠帧回归通过 |
| H 结构 | 仍需渐进拆分，本轮不夹带重构 | 保留本文的分步抽取方案；当前补丁只改状态边界和调度顺序 |

修复后离线验证：蹭车相关集合 `271 passed`；排序后的 `tests/test_*.py` 共 98 个文件，按 49/49 两批顺序执行，第一批 `1104 passed, 8 skipped, 5 known failed, 86 subtests passed`，第二批 `824 passed, 4 skipped, 2 xfailed, 16 subtests passed`。5 个失败与交接列出的基线完全一致，没有新增失败；`test_windows_launcher_smoke` 本次通过。合同 `56 passed`；冻结回放 6 PASS、1 既有 BLOCKED、0 FAIL。scene 模板本体 `ok=148, missing=0`，资产完整性全通过，但 release gate 因既有快照仍为 393、实际为 398 而报告 FAIL，本轮未刷新 baseline。机器可读摘要见 [fix_validation.json](hitch_review_20260912/fix_validation.json)。

> 以下 A–H 正文保留初始候选 `f4c847c` 的审查证据与修复推导。正文中“尚未应用”“严格 xfail”等表述描述修复前快照；当前落实状态以上述复核表为准。

**初始审查结论（修复前）：候选仍有逻辑缺陷，不能据当时的离线通过数宣称蹭车闭环已无冲突。** 初始交付包含审查报告、可复现的离线缺陷用例和机器可读审计数据；当时没有修改生产行为。

| 编号 | 优先级 | 影响 | 证据与复现 |
|---|---|---|---|
| R1 | P1 | 胜利/存档等战后页面反复成功发送点击但不变化，重试可持续到整局截止；180s 监督不起作用 | `mediator.py:13911–13969`、`:14036–14054`、`:10006`、`:10612`；真实胜利帧完整 tick，Core/LIVE 均复现 |
| R2 | P1 | 持续可见的压力转移按钮可以让已过期的整局 deadline 永远得不到执行 | `mediator.py:13646–13651` 在 `:13674` 之前；真实开局帧完整 tick，Core/LIVE 均复现 |
| R3 | P1 | 新局继承上局面板 episode 时间，刚打开 V 就超时进入 COOLDOWN、消耗新局失败预算 | `mediator.py:7795`、`:7980`、`:4043`、`:13237`；真实 HUD 完整 tick，Core/LIVE 均复现 |
| R3a | P2 | 新局保留 `_pending_action` 与未确认计数；旧局后置验证器可被新局调用 | `mediator.py:7784`、`:10143`、`:13656`；生命周期复现。普通蹭车路径很少创建该 token，不能把它夸大为必现事故 |
| R4 | P1 | “连续三帧离开广场”实际可累计不连续候选，错误锁存 instance 后跳过传家宝 60/120s 退出 | `mediator.py:6080–6111`；真实 HUD/胜利帧交错的计数器复现。不是秘境实机验证 |
| R5 | P1 | 时光之穴的 3 次预算在传家宝外层被先读取，换页重置永远进不去；未点 Boss 就关面板并启动“Boss 已点”退出计时 | `mediator.py:14145–14165`、`:6194–6204`、`:14189–14204`；真实传家宝帧完整 tick，Core/LIVE 均复现 |
| R6 | P2 | `move` 绕过实机 harness 的 guard 与输入记录，生产 trace 不能补足其判定覆盖 | `GameScript-Local/tools/live_scenario_capture.py:2952–3013`；只读审查，未修改 |

优先顺序建议：先修 R2、R3、R5，再为战后加入独立的不可续期预算修 R1；R4 必须修正证据连续性，但仍需后续提供真实秘境/团本素材。R6 在 harness 的身份基线流程中独立处理。

## A. 多义状态标志清点——有问题

完整字段索引在 [state_references.csv](hitch_review_20260912/state_references.csv)：每个字段列初始化值、全部静态读写点，覆盖 Core 与 LIVE；`getattr/setattr`、字典赋值和 `clear/add/append` 等可变容器修改也纳入。它是保守超集，包含 L0、配置缓存及非蹭车字段，不能把每个“读”都解释为业务决策。动态别名、第三方外部写入不属于 AST 完备性保证。

局内/战后字段的含义和所有权如下；各组内逐字段位置以 CSV 为准，避免把数百个重复位置粘贴进正文。

| 字段/组 | 实际含义与写入者 | 读取者、边界与问题 |
|---|---|---|
| `_post_game_pending` | 战后链已接管、等待面板/目的地确认；胜利继续成功、直接识别存档/广场均能置 True | `_post_game_state`、`_tick_main_line`、秘境/Boss 分发。不是“点过继续”的同义词；候选已用 `_victory_continue_since` 补门闩，但多义状态仍存在 |
| `_post_game_route` | 业务路线兼过程阶段：`secret/archive/archive_active/heirloom/heirloom_active/boss_active/boss_postgame/npc_hub/team_wait_exit` | 同时控制 NPC 选择、页分类抑制、HUD 转场、退出。`*_active` 有时是“请求已发”，有时是“目的地活动中”；新局设为 `secret` |
| `_victory_continue_attempts`、`_victory_continue_since` | 找到按钮后的尝试数；成功发出 Continue 的时间 | 胜利页重试与尾部检查；attempts 在失败发送时也递增，since 不是页面消失证明。30s 后同时清零导致 R1 |
| `_post_game_close_attempts`、`_aux_dialog_attempts` | 存档关闭与各辅助弹窗的尝试预算 | 点击前增加，乘客达到 3 次又清零；辅助弹窗类别消失也清零。不能作为“已经关掉”证据 |
| `_post_game_hud_confirmations`、`_pending_archive_panel_frames`、`_post_game_archive_pending_only` | 不同帧的目的地确认计数；仅 pending+X 支持的弱存档候选 | `:13813–13851`。最后一个字段由分类器写入，说明分类器不是纯函数 |
| `_post_game_hub_entered_at`、`_post_game_active_wait_since` | 广场等待与请求面板后 3s 观察窗 | `_wait_for_team_post_game_exit`、NPC 路线分发；时间戳不是路线状态，应随所属请求进入/离开清零 |
| `_boss_challenge_attempts/scroll_attempts/next_at/page` | 当前 Boss 页的观察/点击尝试、滚动次数、下一观察时刻、预算所属页 | `_maybe_challenge_configured_boss` 内按页重置；外层先检查 attempts，产生 R5。attempts 包括找不到卡，不等于点击数 |
| `_time_cave_boss_done`、`_time_cave_boss_search_attempts` | 时光之穴步骤已消费、搜索失败数 | `done` 在未配置、预算耗尽跳过和已发点击时都能为 True；它表达“无需再做”，不能在报表中解释为挑战成功 |
| `_archive_challenge_index/observe_attempts/click_attempts/confirm_attempts/next_at` | 八卡游标、各阶段尝试与节流 | `_maybe_click_archive_challenge` / `_tick_main_line`；新局重置游标及计数，next_at 没同块重置，旧的短节流可跨局保留；不是永久锁死 |
| `_heirloom_boss_clicked_at`、`_heirloom_boss_confirm_unconfirmed` | 确实发送传家宝 Boss 点击的时间；业务后置超时标记 | `_heirloom_boss_confirm_expired`；应作为 `HEIRLOOM_SENT` 的唯一请求凭据，不应由“关闭传家宝框”代替 |
| `_hitch_heirloom_exit_since` | 当前实现是成功关闭传家宝框后启动的退出计时 | `:14195` 写入，`:13684` 读取；日志称“Boss 已点”，但 R5 证明两者可不一致 |
| `_hitch_instance_seen/frames/announced/last_frame` | 离开广场判定锁存、候选计数、日志去重、上个计数对象 | `_hitch_left_plaza`；局内初始化/启动传家宝等待清前三项，last_frame 未清；无效候选不归零是 R4，且 Python 帧对象不同并不等于画面内容不同 |
| `_secret_realm_request_pending/since/attempts/next_observe_at` | 自己请求 NPC 的在途操作及预算 | 自动秘境链；正常 hitch 不主动发 NPC 请求（`:14113` 限制 `not _hitch_enabled()`），仍应核对共享状态，不能把跟车路径当蹭车必经路径 |
| `_secret_realm_entering_since/confirm_attempts/confirm_next_observe_at/hud_confirmations/last_hud_frame_id/active` | 确认进入后观察事务、连续 HUD 证明及已进入标记 | `_observe_secret_realm_entry`；成功进入会新建 deadline。与被房主传送使用的 `_hitch_instance_*` 是两种不同证据来源，不宜互相复用 |
| `_passenger_heirloom_for_secret` | 跟车传家宝后待继续秘境的门闩 | 正常 hitch 路径不设置；保留在全字段清单中但不算 hitch 主流程缺陷 |
| `_panel_state/kind/opened_by_us/episode_id/episode_started/first_seen_at/last_progress_at/visible_deadline` | 面板阶段、类型、主动打开来源、episode 身份与各期限 | `_maybe_open_choice_panel`、`_tick_panel_fsm`。`opened_by_us` 为类型字符串或 None，不是纯 bool。R3 的根因是阶段清 CLOSED 但 episode 时间未清 |
| `_panel_episode_count/cooldown_until/executed_actions/confirmed_actions/closing_attempts/closing_started_at/hard_deadline_s` | 每类每局异常预算、重开节流、会话执行/确认统计、关页预算 | `_enter_panel_episode/_finish_panel_episode`、面板 FSM。前两项已修新局重置；其余依赖真正进入/完成 episode |
| `_panel_fingerprint/fingerprint_attempts/mutation_baseline/pending_choice_action/pending_choice_fingerprint/anchor_candidate` | 重复动作防护、后置变更证明、尚未确认的选卡动作、弱锚点跨帧门闩 | 面板选择/后置验证；候选新局只清 state/opened，部分证明残留；首次 ACTIVE 会覆盖大部分，不能笼统声称每项都会误点 |
| `_pending_action`、`_pending_action_unconfirmed_count`、`_surface_conflict_since` | 通用在途后置、累计未确认数、互斥表面冲突开始时间 | 主线与 LIVE inventory wrapper；R3a；冲突出现/消失时自收敛，阶段边界仍宜统一清理 |
| `_public_bag_fsm`、`_public_bag_failed_sources/personal_leftover/empty_since/open_since/next_at` | 搬运事务；每源失败数；个人页残留提示；空页/打开租期/重开时刻 | `_maybe_deposit_public_bag`；新局重建 FSM 与失败记录，但未清 `open_since/next_at`，短局间隔可继承最多 60s 冷却或旧租期 |
| `_l1_cycle_step/index/owned_panel/selected/last_advance_at` | 当前工作步骤、LIVE 位置游标、当前步是否拥有/选过面板、进环初始化时间 | `index` 是 LIVE 独有；`last_advance_at` 在候选只写不读，不是实际活性计时器；真正 15s 步进读取 `_main_line_since` |
| `_auto_task_*`、`_challenge_done/states/attempts/unknown_since/pending_since/next_observe_at/recheck_at` | 自动任务及四挑战的目标状态、待确认与周期复查 | 开局门禁和每轮复查；`done` 是已观察/已处理集合，不取代实时状态；新局相关集合均清理 |
| `_hitch_pressure_*`、`_pressure_next_at` | 压力按钮可见窗口、点击时间/证据代数/计数、确认与旧状态兼容字段 | 压力 transferred 是遥测；按钮可见决定动作。`core_failed/request_attempts` 等旧字段不能被新逻辑当永久门禁；R2 是调度优先级问题 |
| `_hitch_treasure_retry_at`、`_last_treasure_attempt`、`_last_skill_panel/_last_bond_attempt` | V 未出现后的重试时刻与各主动面板节流 | V 30s 再试/达到本局上限跳步已在 Core 与 LIVE 生效 |
| `_merchant_fsm/next_at/discovery_deadline`、`_pickup_next_at` | 黑商事务、黑商节流/发现窗口、拾取节流 | 黑商无目标最多等待 10s 后转步；新局重建，不能把商店输入成功当购买成功 |
| `_round_started_at/deadline/outcome/outcome_recorded`、`_main_line_since/started_at` | 全局截止与结果记录权；局内活性时刻/开局保护起点 | `_hitch_after_exit` 清 round；自然进局设截止；`_main_line_since` 多处更新，不可用作整局截止 |
| `_pause_resume_*`、`_game_chat_frames/close_attempts/close_next_at/last_frame`、`_hero_focus_*`、`_pointer_needs_park` | 暂停、聊天、英雄焦点、自身 tooltip 清理各自的短事务 | 均不是业务推进证明。聊天/鼠标未全量随新局清，但视觉消失/成功移动会收敛；HeroFocusFallback 仍被监督算进展 |
| `_early_challenge_*`、`_tqtz_*`、`_close_main_line_triggered/_main_line_closed_done` | 提前挑战请求与 5-5 主线关闭事实 | 专用 handler；`_reset_tqtz_round_state` 在 STAGE 与自然 MAIN 都调用；非纯蹭车状态不要不加区分搬进新枚举 |
| `_recovery_*`、`_failure_candidate_*`、`_exit_button_attempts/exit_confirm_attempts/exit_since` | 失败抢占证据、恢复事务、退出两阶段的尝试 | 新局清恢复事实；QUIT/NEXT 分别清尝试但监督共用 exit 停留族，详见 D |
| `_liveness_*`、`_runtime_watchdog_*`、`_physical_panel_*` | 总监督、LIVE 遥测、物理面板遥测 | `runtime_watchdog_stall_episodes_total` 故意会话累计；其余局内门闩在 LIVE MAIN 边界重置，详见 E |

嵌套 `PublicBagFSM` 也在边界内：`phase` 为事务阶段；`source_id/kind/slot/cell` 和 `target_slot/kind` 是位置/来源权限；`deadline` 为当前事务不可续期等待；`deposits/aborts` 为成功存入与中止统计；`cooldown_until/abort_reason/opened_by_us` 为恢复节流、原因与页面所有权。定义 `policy/public_bag.py:304–331`；写入由 `request_bag_open/confirm_bag_visible/select_source/request_deposit/confirm_deposit/request_close/confirm_closed/abort/release/observe` 用 frozen dataclass `replace` 完成；读取在这些方法、`active/carrying/can_left_click/can_start/can_adopt_open_page` 及 Mediator 搬运分发。5/6/4/5s 的打开、取源、放置、关闭等待各自独立，不能只看 Mediator 的 self 字段断言重置完整。

**最小修复建议：** 先把 Boss 页预算初始化移到外层分派读取 attempts 之前（R5）；只有确实发出 Boss 请求或明确走“跳过”分支时才能进入对应后续阶段，并区分日志。`_time_cave_boss_done` 暂按“步骤已消费”保留，报告成功状态不要读取它。

建议逐步引入战后子状态，而不是整体重写：① 先为当前布尔组合加状态映射和非法组合断言；② 把 `VICTORY_WAIT_BUTTON/VICTORY_CONTINUE_SENT` 及不可续期 episode 时间迁过去；③ 把 `ARCHIVE/HEIRLOOM_GRID/HEIRLOOM_SENT/PLAZA_WAIT/INSTANCE` 逐段迁移；④ 路线配置仍单独保留，旧字段只作为只读兼容诊断；⑤ 每步用 Core/LIVE 相同真实帧序列比较动作、结果和退出时刻，最后删旧写入点。不要同时维护两个可写真相。

**新增测试：** 本次 `test_heirloom_resets_exhausted_archive_budget_before_dispatch` 复现 R5；后续补 attempts=0/1/2/3、无配置、点击拒绝、第三次才找到卡、传家宝后置未确认等组合。每个动作成功只作为输入证明，独立断言 Boss 请求状态与业务确认。

## B. 每局重置完整性——有问题

全部赋值在 [reset_assignments.csv](hitch_review_20260912/reset_assignments.csv)。比较的是 STAGE_SELECT、自然 `entering_main_line`、`_hitch_after_exit`、`_finish_hitch_round` 与 LIVE 附加重置；不是把整个 `set_phase` 的并集误当每个边界都会执行。

以下逐项列出 STAGE 块清理、而 hitch 自然 MAIN/after_exit 没有等价完整清理的字段：

| 字段 | hitch 下判断 |
|---|---|
| `_stage_scroll_attempts`、`_old_world_switch_attempts` | 选关导航专属；正常 hitch 不选关，未发现局内泄漏影响 |
| `_stage_selected`、`_stage_target_name`、`_stage_target_position` | 回 LOBBY 的另一个 `set_phase` 块已清；不属于真正漏项 |
| `_stage_candidate_name`、`_stage_candidate_position`、`_stage_candidate_frames`、`_stage_select_attempts`、`_stage_scroll_cooldown_until` | L0 选关候选/预算；正常 hitch 不执行该分支，未来改接管策略时才需重新评估 |
| `_room_action_deadline` | L0 房间/选关超时；STAGE 设置的是新 deadline 而非清零；hitch 使用独立 ready/exit 事务，不直接据它退局 |
| `_hero_state`、`_hero_verified_level`、`_hero_level_baseline`、`_hero_level_candidate`、`_hero_card_baseline`、`_hero_step_deadline`、`_hero_modal_missing_frames` | 主动英雄模式状态；正常 hitch 不走 HERO_SETUP。不是蹭车必现缺陷 |
| `_pending_action`、`_pending_action_unconfirmed_count` | R3a，确实跨局残留；当前普通 hitch 不使用主动 inventory 的大部分 token 创建路径，影响须按入口区分 |
| `_panel_kind` | 残留类型；新打开通常会覆盖，不能孤立断言错误。应与 episode 同清 |
| `_panel_episode_id`、`_panel_first_seen_at`、`_panel_last_progress_at` | 上局 episode 身份/诊断残留；下一次 `_enter_panel_episode` 会重写，但主动开窗尚未到 ACTIVE 前已可被读取 |
| `_panel_episode_started` | R3，直接影响行为：新开 V 的 OPEN_REQUESTED 在 `_enter_panel_episode` 前被旧时间判超时 |
| `_panel_visible_deadline` | OPEN_REQUESTED 正常转换时会重写；清理不完整但未单独复现错误 |
| `_panel_mutation_baseline`、`_panel_pending_choice_action`、`_panel_pending_choice_fingerprint` | 旧页后置事实；ACTIVE 入口通常会覆盖，仍应撤销跨局证明，不能继承输入权限 |
| `_panel_fingerprint`、`_panel_fingerprint_attempts` | 正常主线 CLOSED 尾部会清，ACTIVE 入口/finish 也会清；阶段边界本身不完整。不是第二局必然复用旧点击次数 |
| `_panel_anchor_candidate` | 弱锚点双帧门闩可能跨局保留；如果新局首个弱同名面板被优先分派，CLOSED 尾部还没机会清它。需补一帧弱证据不能获权的测试 |

已正确重复清理：`_round_started_at/_round_deadline/_outcome_recorded/_round_outcome` 在 after_exit；面板每类计数/冷却与 `panel_state/opened_by_us` 在自然 MAIN；tqtz 在两条新局入口均重置。`_finish_hitch_round` 只负责计局、25s 关闭宽限与边界调用；达到 cycle_num 时直接 COMPLETE，不需要为了停止后的对象再清新局字段。

其他非 STAGE 专属漏项：背包 `open_since/next_at`、聊天候选/尝试、pointer dirty、`_archive_challenge_next_at`、`_hitch_instance_last_frame`。大部分会自收敛或短暂延迟，报告不把它们统一升级为 P1。特别是手动关背包的 60s 尊重窗口是否应跨局保留，要按“用户意图会话有效”还是“当前局有效”明确语义后再改。

LIVE `runtime_mediator.py:715–730`：任何从非 MAIN 进入 MAIN 都清 bond 所有权、物理面板 guard、游标、当前 stalled 状态，并重新 mark progress；它不检查 Core 的 `is_reentry_or_attach`，所以同一局 reconcile 也会重置这些局内事实。蹭车不消费 bond 卡，当前主要影响游标回环首和遥测；不要把 LIVE 的这段重置当成 Core 面板 episode 已清零。

**最小修复建议：** 在真实新局入口撤销 `_pending_action`，清面板 episode 全部瞬态，尤其 `episode_started/anchor_candidate`。复用 `_finish_panel_episode` 前先确认它会推进循环等副作用；不能为了“复用 reset”意外执行一次环步进。最小安全补丁是把现有纯赋值清理段复用成明确的新局重置函数，不改正常打开/关闭策略。

**新增测试：** 已有 R3/R3a Core/LIVE 用例；R3 测试不是只断言字段为空，而是跨局后通过真实 HUD 完整 tick 打开 V，再证明它错误进入 COOLDOWN。修复后保留该行为断言；补完整 UNKNOWN→准备→自然进局→战后→下一局链，以及同局 reconcile 不重置长期事实。

## C. `_tick_main_line` 早返回——有问题

[main_line_returns.csv](hitch_review_20260912/main_line_returns.csv) 逐个记录 Core/LIVE 共 90 个字面 `return LoopAction.Continue` 的行号、完整 if 路径及前文；这是零输入分支的保守超集，包含有可能发送输入的分支，不能把 90 解释为“90 个必然零输入”。`return helper_result` 的间接返回另见下表。每个字面返回对应的所有者、上限和出口在 [main_line_return_ownership.csv](hitch_review_20260912/main_line_return_ownership.csv)。

| 所有者/分支 | 上限与出口 | 审查结论 |
|---|---|---|
| 已到 round deadline `13680` | 当 tick 能到达此处时转 QUIT | R2：不是所有执行路径都会到达 |
| 传家宝等待 `13712/13718/13722/13728` | hitch 广场 60s、非广场未确认 120s→QUIT；instance 锁存后跳过；follow 分支不属 hitch | R4；当前仍受整局 deadline，存在与“不退秘境”规则的优先级未明确问题 |
| 玩家退出确认 `13738` | 本地零输入；180s 监督软复位，再无进展可转 QUIT；整局 deadline 仍有效 | 本 tick 不取消玩家操作。长时间保留该框会被全局撤离接管，不能声称永久保持不动 |
| 失败奖励关闭 `13746` | 本地无独立累计上限；成功点击可重置监督 | 和 R1 同类，反复点击不消失时缺不可续期业务预算 |
| 等房主难度/误开选关 `13771/13782/14488` | 转 ROOM_WAITING/QUIT；房间 600s、退出族 240s | 有跨阶段上限；正常 hitch 的主动 STAGE_SELECT 不应成为修复目标 |
| 战后背包关闭 `13797/13810` | FSM 关闭 5s，失败后可重试；监督 180s，无战后停留上限 | 成功反复发关闭输入可遮蔽监督；需战后总预算 |
| 存档 pending+X 与 HUD 候选 `13816/13820/13833/13837/13849` | 不同捕获对象 2 帧；静帧等待无本地 deadline，监督 180s | HUD 被监督判为 game_round 时只软复位；不能保证 360s 必定退出 |
| 未验证 archive `13875/14442`、未知战后 `14258`、转场 `14462/14468` | 无输入监督 180s；game_postgame/unknown 可升级离开；game_round 只软复位 | 上限依赖“世界分类”，不只是当前 `_post_game_pending`；无按钮胜利等待 `13940` 同理 |
| 胜利 Continue `13920/13926/13932/13940/13969` | 等待 min(query_timeout,30)s；3 次尝试；乘客重新武装 | R1，局部数字有界、整个 episode 无界；真实 tick 验证重复点击持续 432s 仍 MAIN |
| 存档处理 `13977–14054` | 初次接管/F1 是状态推进；Boss 节流/观察有小预算；关闭 3 次后重新武装 | 缺战后总停留界；找不到按钮零输入可触发监督，反复成功点击则不能 |
| NPC 路线 `14061–14143` | active 请求等待 3s 后回请求路线；秘境请求 3 次或 3–15s ERROR；无路由后 QUIT | archive/heirloom 请求被吞会形成“请求→3s等待→重发”活锁；与 R1 同根 |
| 传家宝框 `14151–14206` | 配置 Boss 后置窗口；关闭 3 次后再武装；成功关框启退出计时 | R5；未成功关框时 60s 计时尚未启动，不能用它证明关框阶段有界 |
| 大秘境框 `14224–14254` | 请求前置时 3 次或 3–15s；非前置取消 3 次后 ERROR | 正常 hitch 不请求秘境；不要靠传家宝 instance 标记取得灰“是”按钮权限 |
| 仲裁冲突 `14346/14352/14400` | 2.5s 已知面板可降级；未知冲突到 panel deadline 后乘客继续等 | 180s 监督依赖 world；同页被认为 HUD 时只有软复位与 round deadline |
| 装备词缀/进化 `14364/14365/14372/14386` | 各自待确认、节流；正常 hitch 不主动进化 | 自然强制弹窗仍可能出现，保持上层后置/失败抢占 |
| 自动任务 `14501` | helper 有 UNKNOWN 复查/熔断；未 done 时阻断后续；F1 可返回 | HeroFocusFallback 不在盲动作排除表，重复 F1 可重置监督 |
| 开局保护 `14541` | 自然进入后 20s，再下行 | 小于 180s；不能因监督软复位而反复刷新 started_at |
| legacy idle、artifact、evolve、equipment `14558–14625` | 多为状态步进，进化 3 次/冷却；正常 hitch 环只包含其子集 | 同一 tick 零输入不等于无进展；详见 CSV 条件区分实际可达性 |
| 背包 `14637/14639` | FSM 打开5s、取源6s、放置4s、关闭5s，租期30s；45/60s重开节流 | 局部事务有界；上层抢占时实际 FSM observe 可能延迟，不能只加总时长 |
| 拾取 `14657/14664` | passenger 推进到公共背包，不执行个人吃丹/英雄卡 | 无业务冲突；零动作步进正常 |
| 黑商 `14668/14674/14676/14679/14687` | 未发现 10s→下步，FSM 自己负责成交后置 | 10s 小于监督；不要让缺店重设 discovery deadline 形成永久等 |
| 底部 15s 步进/idle `14694/14696` | 只更新循环；无物理输入仍受180s监督与round deadline | 不构成“成功输入”，设计上不会清总监督 |
| LIVE `333/346` | 15s 记录一次 stalled，纯遥测 Continue | Core 已先执行；没有补足 R1/R2 |

间接返回的拥有者也已核对：`_maybe_close_game_chat`（每次出现最多2次、每次两帧、2s节流）、压力处理（3s/60s，但 R2）、`_observe_secret_realm_entry`（3–15s）、`_maybe_resume_paused`（5次后乘客等待，监督软复位可再武装）、`_maybe_click_archive_challenge`、`_maybe_challenge_configured_boss`、tqtz/提前挑战、`_tick_panel_fsm`、`_maybe_black_merchant`、`_ensure_auto_task_enabled`、`_ensure_challenge_buttons`、hero focus、主动面板及背包 FSM。它们的 `Continue` 在当前框架下都不自动获得业务进展证明。

退出链的两处重新武装不在本函数：`_tick_l1_tail:14719–14760`。QUIT 与 NEXT 同属 `exit`，240s 族停留上限不因两阶段互跳或成功点击清零，覆盖有效；与没有 postgame family 的 MAIN 不同。

**最小修复建议：** 给战后 episode 一个独立、不可续期的开始时间/总截止，仅在业务页面迁移获得证据后进入新的子阶段；重发 Continue/X/NPC 点击不续期。无输入梯级继续处理未知画面，但不能作为活锁总预算的替代。退出到 QUIT 后继续沿已存在的 240s 事务上限，不另造退出流程。

**新增测试：** R1 已完整 tick 覆盖“输入发送成功但同一胜利页不变”；补存档 X、NPC 打开、背包关闭、传家宝 X 被吞序列，明确验证在独立战后预算前后转 QUIT/ERROR，而非只验证 attempts 被清零。

## D. 监督器与计时器——有问题

监督器 `:9983` 在 `_tick_impl` 返回 Continue 后运行；预算 `:10584` 为大厅90s、房间180s、MAIN180s、恢复90s、QUIT/NEXT60s，其余150s。族停留上限 `:10616` 为 room600s/recover180s/exit240s。监督“进展”来自 `_tick_input_executed` 与 `last_business_action`，没有验证页面推进（`:10006`）。

| 局部等待 | 与监督关系 | 结论 |
|---|---|---|
| 准备70s + 退房截止30s + 宽限60s | 合计160s < 房间180s，room600s总上限另在 | 默认数值无直接冲突；预算锚点是上次输入，不是进入 ROOM 时间，测试应覆盖房间接管而非只做算术 |
| 成员房间保持150s | 小于180s | 不必缩短正常等待；游戏窗口出现仍优先接管 |
| 搜索 SLEEP_RETRY 120s | `_hitch_declared_wait_until` 声明休眠终点 | 避免90s打断休眠；声明只在仍为 SLEEP_RETRY 时可见，不应宣称退出该状态后还保证额外90s |
| 胜利页30s与3次尝试 | 每次重发可重置180s监督 | R1，无 postgame 总上限 |
| 传家宝广场60s/未知120s | 小于MAIN180s，前提是 exit_since 已武装且 instance 未锁存 | R4/R5破坏前提；已经 instance 的局仍可能被原 round deadline退出，与“等失败/胜利才退”需要明确谁优先 |
| 整局默认3600s | 判断在压力处理之后 | R2。稳定 tick ≥3s 时每次都点击并返回；即使<3s，按钮间歇消失又出现会重启60s优先窗。原审计 C12 的“不会绕过”结论失效 |
| LIVE 15s/物理面板30–60s | 只做遥测 | 不会抢输入，也不会解决战后活锁 |
| 退出60s无输入、240s族停留 | 不论按钮是否反复命中，族上限仍执行 | 在阶段族不离开的前提下有效；25s关闭宽限不是退出业务确认，已有重复计局限制继续保留 |

`_LIVENESS_BLIND_REASONS` 现有四项：`HitchStallWatchdogEsc/HitchLeaveMisopenedStage/CloseGameChat/ParkPointer`。这些已正确排除，但清单不足以证明闭环有界：`HeroFocusFallback` 可重复无业务变化；`ContinueGame/CloseArchivePanel/OpenArchiveChallenges/OpenHeirloomChallenges/DismissHeirloomDialog/DismissFailureReward/HitchPressureTransfer` 的发送成功也不能证明推进。最小方案不是把所有合法点击永久列为“盲操作”，而是区分输入已发与业务已确认，再由不可续期 episode 上限覆盖重复尝试。`INPUT_DISPATCHED_UNVERIFIED` 分支增加 `_tick_input_executed` 却没有更新 `last_business_action`（`:2050`），监督还可能读到上一动作名字，应一并校准。

**最小修复建议：** 将 round deadline 的处理放在可重复输入的压力/聊天处理前，同时保留更早的强失败/断线抢占；秘境 entry 自己的有界观察例外显式保留。R1 用战后停留预算修，不靠提高180s。若用户“instance绝不提前退”要求优先于 round hard cap，应把这个合同独立写明并配测试，不能悄悄借本次修复改变它。

**新增测试：** R2 已在真实开局帧、过期deadline、4s tick cadence 下复现；补0.2/1/3/4s cadence、压力短暂消失再出现、输入拒绝及 `INPUT_DISPATCHED_UNVERIFIED`、恢复抢占、instance模式下deadline策略。时间由离线时钟推进，不真实 sleep 3600s。

## E. RuntimeMediator 与核心分叉——有问题，但不是本轮修复全失效

覆盖方法清单及语义如下（行号均为 `runtime_mediator.py`）；新增而非 override 的辅助方法不冒充覆盖方法：

| 覆盖方法 | 差异/影响 |
|---|---|
| `__init__:31` | 暂关Core OCR初始化，改用 ProductionShadowClient；初始化 LIVE 游标与遥测字段 |
| `_advance_l1_cycle:227` | 按位置而非 `order.index` 处理重复项；通过 `_l1_cycle_order` 选 hitch 环。Core 在进入 pickup 时清 inventory统计，LIVE没有同一条件；hitch不个人吃丹，未证实本模式行为损坏 |
| `_tick_main_line:304` | Core先执行，之后记录15s遥测；真实胜利动画、压力与战后缺陷均继承 |
| `_hide_fallback_hit:397` | 始终 None，撤销泛化隐藏兜底 |
| `_tick_panel_fsm:452` | 先做物理面板遥测，再Core FSM；Core宝物上限/重试修复生效，R3也同样存在 |
| `_confirm_panel_choice_action:461` | Core确认后更新物理进展/未知面板/运行时进展 |
| `_find_evolution_choice:471` | 已识别普通面板不当进化；仅明确等待进化时允许受约束候选 |
| `_maybe_use_inventory_item:510` | 在途后置先等待；个人物品使用/升级节流。正常hitch在pickup处提前返回，不执行个人物资消费 |
| `_maybe_black_merchant:590` | 直接super，黑商新修复不存在双实现 |
| `_find_stage_start:596` | 增加关卡高亮正向证明；正常hitch不应发StageStart |
| `_canonical_bond_name:620`、`_stage_bond_card:650`、`_commit_pending_bond_cards:658`、`_confirmed_bond_cards:669` | LIVE名称规范化、暂存/提交/读取bond持有事实，主要为非hitch主动bond服务 |
| `_commit_pending_skill_cards:672`、`_clear_pending_skill_cards:676` | 额外提交/清理bond待确认事实 |
| `act_click:680`、`act_right_click:693`、`act_key:699` | Core成功后标运行时进展；bond选择暂存，等待后置确认才拥有 |
| `_policy_settings:708` | 用剩余bond预设派生配置，复用父类其余设置 |
| `set_phase:715` | 非MAIN→MAIN重置额外LIVE事实，不区分自然新局与attach；见B |
| `_maybe_open_choice_panel:732` | 非hitch、bond预设已完成时跳过；hitch V路径走super |
| `_find_reward_choice:748` | bond完成/白名单与未知面板附加规则，其余走super |
| `panel_episode_diagnostics:800` | 增加物理面板、OCR健康、游标与watchdog遥测 |

AST核对为24个覆盖方法；全部方法及对应Core行号见 [runtime_method_inventory.csv](hitch_review_20260912/runtime_method_inventory.csv)。`_remaining_bond_presets/_bond_presets_complete/_clear_pending_bond_cards/_l1_cycle_order` 等是新增 helper，不是override。

当前 hitch 环为唯一命名的 `merchant/treasure/pickup/public_bag`，位置游标的优点主要服务 solo 重复bond/skill。直接写 `_l1_cycle_step` 时 LIVE 会在下次 advance 重新找相应位置；hitch不存在重复名歧义。Core `_passenger_mode()` 与 LIVE `_hitch_enabled()` 对 follow_team 的差异属于相邻模式风险，不能混为 hitch 缺陷。

**最小修复建议：** 不另修一份 LIVE 战后逻辑。修 Core 后让同一真实帧用例参数化两类；先统一新局边界判定、循环推进的公共副作用，再考虑移除无必要的覆盖。不要把 LIVE 15s遥测恢复成发输入看门狗。

**新增测试：** 本次胜利横幅→继续、鼠标停车→下一真实帧黑商购买的正常链 Core/LIVE均通过；R1/R2/R3/R5均对两类复现。还应把 `test_hitch_ingame_bootstrap_20260911`、宝物上限/第二局、背包租期/英雄卡搬运、失败抢占的现有真实帧测试参数化 LIVE，并用完整 tick 替代只patch act_click的假输入证明。

## F. `move` 边界——生产前置检查无差异；harness 与停车调度有问题

`input/keyboard_mouse.py:423–451` 与 click `:394–421` 一样先 `check_can_execute`（急停、提权、HWND有效、前台获取）、检查目标点遮挡、再次检查急停、SendInput、post-check。`move_cursor:732` 使用不按键的移动路径；不是伪装点击。`Mediator.act_move:2174` 正确走 `_action_forbidden/_action_gate_ok/_finish_input`，加 frame origin，记录 `intent:move`，同tick输入序列门闩生效；ParkPointer不算总监督进展。

`RecordingInputExecutor:2952` 的 `_call` 才执行 input_guard/委派/on_result。没有 `move` override，继承 InputExecutor后会直接移动：底层急停/前台检查还在，但缺少harness自己的上下文限制和记录。**建议必须补包装**，最小内容与现有click同形：

```python
def move(self, x, y, target_hwnd=None, dry_run=True):
    return self._call("move", x, y, target_hwnd=target_hwnd, dry_run=dry_run)
```

这是待走身份基线流程的建议，不是本次已应用的补丁。还要核对 harness action schema/允许方法枚举，不可只加wrapper便声称 guard全面支持move。

停车标记 `:2136` 是归一化后的 `y>=0.55H or x>=0.85W`，能够覆盖现有底部按钮/右缘；`_maybe_park_pointer:2153` 在背包非IDLE、面板非CLOSED、有pending时跳过，避免携带物品时移动破坏后续位置。它会在COOLDOWN也跳过，这是状态而非实际页面可见判断；过期pending或R3能拖延停车。点击失败也会调用 `_note_pointer_on_hud`（`:2090/:2115`附近），可能产生一次多余停车；拒绝移动会直接清dirty并继续旧识别，原tooltip仍可存在。当前没有证据证明这几种情况导致错误点击，按P2改进项保留。

此外，`_black_merchant_present` 仲裁（`:14301`附近）与 MERCHANT handler（`:14395`）位于停车（`:14405`）之前；“所有HUD读取之前都停车”这个注释强于实际实现。应区分只读检测与发输入，给黑商购买前也提供同样的去遮挡入口，保持背包携带/后置门闩；不要无条件把停车搬到战后/退出弹窗之前。

**新增测试：** 补输入层表驱动拒绝检查（急停、前台、遮挡、postcheck失败都不漏发第二次输入）；frame偏移、同tick第二输入拒绝；真实tooltip→move→新帧→黑商完整tick；COOLDOWN、pending、携带源格时不移动；harness fake delegate证明move经过guard/on_result且被拒时delegate未调用。harness测试要在其身份流程内新增，本次没有修改该目录。

## G. 分类矩阵——有视觉重叠，当前路由优先级挡住已发现的两例

脚本 [tools/audit_hitch_review.py](../../tools/audit_hitch_review.py) 仅读磁盘图片，不截屏、不显示图片、不控制窗口、不注入输入。遍历 `tests/fixtures/**` 与 `fixtures/**` 下全部支持的图片，记录SHA256、尺寸、来源路径、解码/分类错误；相同bytes去重计算但保留每个路径行。每张图分别在fresh、archive_pending、boss_active上下文分类，以免把依赖pending/route的函数误当纯图片函数。

分类器：`_post_game_state/_is_in_game_hud/_host_choosing_difficulty/_top_bar_mode/_find_exit_confirm/_game_chat_input_visible/_hitch_room_surface_evidence`。尺度沿 `see()` 的1600×900缩放规则，使用真实Core证据缓存；实例为LIVE。为避免缺失历史窗口元数据导致game-specific函数恒False，图片给固定游戏窗口元数据，房间视觉分类仍独立执行。因此矩阵是视觉交叉压力检查，不是所有历史图片都在生产中的可达窗口路由。

小图/模板/crop仍列出并分类，标记 `crop_or_small`，不能当完整实机画面。目录中没有全量可靠的真实/合成来源清单，所以脚本不把全部图片冒充真实采集；hitch_live及有录制来源的fixture可独立筛选。

互斥候选规则为 `host_wait+hud`、`room+game`、`exit+GREAT_RIFT_CONFIRM`。`HUD+POST_VICTORY`、`HUD+ARCHIVE_PANEL`、`plaza+HEIRLOOM_DIALOG`、`chat+HUD`是前景弹窗/底层HUD可共存，不能直接算分类错误；正确优先级必须再由完整tick验证。

最终结果：[classifier_matrix.csv](hitch_review_20260912/classifier_matrix.csv)、[classifier_summary.json](hitch_review_20260912/classifier_summary.json)。2012个路径、1779个唯一文件内容、3种上下文共6036行；781张达到完整帧尺寸，1231张为crop/small；0解码/分类异常。全尺寸只说明尺寸足够，不证明全部是实机采集。

发现2个路径共6行 `room+game` 重叠：

- `fixtures/ocr_choices/frames/rec9_mijing_20260810/d0_a_000224.png`
- `fixtures/ocr_choices/frames/rec9_mijing_20260810/d0_a_000442.png`

两张均为1920×1080，`hud=True/room=True`，各pending/route上下文一致。`fixtures/ocr_choices/D0_vision_review.json` 有该录制帧的技能卡文本复核记录，因此存在游戏画面语义；本次没有目视检查桌面是否同时包含平台窗口，不能仅凭组合把ROOM分数宣称为生产误点。`_compute_context:1278` 先判断选择面板/HUD，再看ROOM，当前选择MAIN_LINE；新增 `test_matrix_room_hud_overlap_is_owned_by_game_tick` 用LIVE完整tick锁定这个优先级，不允许发HitchJoin/Ready/SelectTab。

`host_wait+hud` 和 `exit+rift` 未发现同时为真的行。另有32行 `post_game+hud` 共存，属于需前景优先的重叠，不能按32个bug计数；正常胜利动画/按钮完整tick测试验证其中的前景优先。

**最小修复建议：** 目前先保持已验证的game优先路由，并把房间视觉识别结果与最终窗口所有权分开命名；若要让ROOM分类器本身排除游戏，应在有真实窗口role/ROI的入口约束，先覆盖实际房间金/蓝皮肤与全桌面复合画面，避免互相调用HUD/ROOM造成递归。此次没有足够证据要求调整模板阈值。

**新增测试：** 已把两张重叠帧写成LIVE完整tick路由测试。仍需当前版本、明确捕获游戏client rect的秘境/团本样本：历史 `rec9_mijing` 名称与技能面板帧不能验证2026-09-12传家宝后传送规则，R4计数器测试也不能填补这个空白。

## H. 结构方案——存在耦合问题，本次不重构行为

Core近1.5万行、LIVE额外覆盖，使“阶段名→新局判定→共享字段→继承覆盖”串成隐式合同。当前最危险的是reset归属和输入/业务成功混用，不是行数本身。

建议按现有职责渐进分割：①蹭车搜索/房间事务（已有 `lobby_hitch.py` 纯搜索SM，保留）；②乘客主线循环；③战后状态与请求；④公共背包协调（几何与FSM已经独立在policy，避免重复抽象）；⑤无进展/停留监督；⑥感知分类。每次只抽一层，不同时改阈值、阶段顺序与返回值。

**第一步可独立落地：** 把 `_hitch_left_plaza` 中“给定mode、quit/fail/postgame证据以及候选连续性，更新instance观察状态”的纯状态推进抽成小函数，先保持当前行为逐字等价；Mediator继续负责取得证据与储存字段。用现有序列对旧函数/新函数做差分，再单独一个行为修复提交解决R4。这比一次搬整个战后块、引入多继承mixin更容易审查。

如果要求第一步严格只移动代码、连函数参数整理也不要做，可先把 `_TOP_BAR_LABEL_ROI` 和 `_top_bar_mode` 的纯匹配逻辑移动为 `post_game_vision.py` 函数，并保留原方法为单行委派、显式传入当前 `find` 回调。保持相同参数、调用顺序和MatchResult坐标，原API/缓存归属不变；用完整分类矩阵逐行比较，与Core/LIVE帧链一起验证。不引入服务容器、泛化状态框架或第二份截图缓存。

**新增测试：** 抽取前后CSV完全一致、Core/LIVE动作序列一致，C2大厅状态污染隔离合同通过。已知既有失败保持明确列出，不能宣称当前全套全绿或刷新基线消除它们。

## 验证与交付记录

测试按原始 `tests/test_*.py` 字典序固定文件清单分48/49两批，顺序执行，每批2400s超时，超时只终止该批PID树。新增审查测试在两批清单冻结后创建，因此单独执行，600s/300s超时。原始命令清单、日志和结果保留在 [hitch_review_20260912](hitch_review_20260912/)。

两批结果：第一批 `1085 passed、8 skipped、5 failed、86 subtests passed`（pytest 519.46s）；第二批 `824 passed、4 skipped、2 xfailed、16 subtests passed`（83.79s）。合计1909通过、12跳过、5既有失败、2既有xfail。第一批5个失败准确对应：

- `test_live_harness_refresh.py::test_identity_uses_current_worktree_not_old_runtime`
- `test_live_harness_refresh.py::test_production_code_diff_gate_is_clean_on_this_worktree`
- `test_live_harness_refresh.py::test_fail_bundle_schema_includes_identity_and_window`
- `test_live_scenario_capture.py::test_lobby_hitch_uses_default_and_custom_search_text`
- `test_mode_catalog.py::ApplyModeOverlayTests::test_hitch_dashboard_contract_exposes_bosses_and_search_terms`

`test_windows_launcher_smoke` 本次没有失败，无需重复跑。新增审查用例最终 `6 passed、11 xfailed`（37.89s），其中R1/R2/R3a/R4/R5的9项已用 `--runxfail` 得到预期断言失败，R3面板行为另2项同样用 `--runxfail` 证明。详见 [review_tests_runxfail.log](hitch_review_20260912/review_tests_runxfail.log)、[panel_reset_runxfail.log](hitch_review_20260912/panel_reset_runxfail.log)、[review_tests_final.log](hitch_review_20260912/review_tests_final.log)。xfail只隔离明确未修缺陷，修复后应删除标记；不得据returncode=0说这些缺陷已解决。

层间合同 `56 passed、111 subtests passed`；冻结回放 `6 PASS、1 BLOCKED、0 FAIL`，BLOCKED仍是缺少真实断线弹窗素材。冻结检查退出码0仅表示当前冻结预期匹配，不能称断线链已通过。

进程检查：任务开始前已有Hermes Python PID `19092/17132/24008/24592`。测试及矩阵结束后，本次pytest/runner/矩阵Python全部退出；最后又观察到由 `explorer.exe(12636)` 启动的 `pythonw.exe(2888)→python.exe(38268)`，不在本次进程树中、命令行不可读，未终止。故结论是“无本次测试残留”，不是“整机没有Python”。记录见 [process_check.json](hitch_review_20260912/process_check.json)。

未修改任何生产代码、GameScript-Local文件、桌面入口或baseline；HEAD与本地候选分支仍为f4c847c。没有生成/更换EXE或产物hash。报告反证了旧活性审计C12及“战后所有重试由监督覆盖”的过强结论，已在当前交接文档追加索引。没有运行一条全量 `pytest tests/`，没有更新GATE_BASELINE，没有commit，因此不声称 release gate 已通过。

最终复核：上述Explorer启动的2888/38268也已自行退出；整机仅剩任务开始前的4个Hermes Python进程。本次任务无Python/pytest残留。报告链接、Python AST、406/90/6036行数检查及git diff --check均通过。
