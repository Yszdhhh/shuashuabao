# 只读证据矩阵：状态 → 视觉锚点 → 允许动作 → 后置确认 → 超时 → 恢复目标（2026-08-12）

> 阶段：GameScript-Local 深度修复第一阶段（A 阶段）· 只读，不修改生产代码。
> 仓库：`C:\Users\10639\Desktop\🎮 影音游戏\GameScript-Local`，分支 `codex/ocr-hybrid`，HEAD=`8b946fa`（工作树未提交改动属项目所有，本文件仅新增产物，不提交）。
> 权威交接：`docs/CURRENT_STATUS_AND_HANDOFF_20260812.md`；外部审查：`goal-objective.md`（问题 1-12）。
> 验收口径：仅 `1600×900`；禁止通用 `blue_button_color` 创房兜底；每 tick ≤1 输入；不得新增 XFAIL。
> 证据等级（沿用交接文档）：**I**=已实现（代码级）｜**U**=单元测试/合成回放（447 tests，2 XFAIL）｜**R**=真实录像帧离线回放/当前版本截图 fixtures｜**L**=桌面版本真机跑通｜**S**=3/10 局无人干预长稳（当前均未达到）。

## 0. 证据来源口径（重要）

- 当前工作树 `__version__ = "2026.08.12-r7"`。**r7 至今没有任何真机 trace 证明全链跑通**（handoff §4）。
- 本文引用的真机 trace 均属**旧构建**：
  - `trace_20260811_205100.jsonl` / `215307` / `232040` → `build_id=ocr-hybrid-dev`（LIVE 真机，创房走旧版 `blue_button_color` 兜底，属已禁止行为的历史证据）；
  - `trace_20260812_001250.jsonl` → r5 真机（3 次误点“快速加入”缺陷现场）；
  - `trace_20260812_002654.jsonl` → `build_id=v2026.08.12-r6` 真机（创房卡死 57 tick 现场）。
- 胜利/秘境/退出确认链在**全部 20260811/20260812 trace 中 0 命中**（`continueGame`/`damijing`/`mijingOk`/`exit_confirm`/`gameDisconnect`/`failGiftClose` 均无实命中行），其证据只能来自 **R 级**（录屏 `C:\Users\10639\Desktop\录屏素材\20260810_214444.mp4` 离线回放 + `fixtures/reborn_wow/endgame/*.png` 当前版本截图）与 **U 级**单测。
- 基准分辨率模板为绝对尺寸资产：局外 L0 门闩用宽尺度档 `_l0_scales()`（绝对 1.0,1.1,0.9,1.15,1.2 + `ui_scale` 邻域）；局内用 `_hot_scales()`（`|ui_scale-1|<0.05` 时仅 1.0，否则 `(ui_scale, ui_scale*1.06)`）。
- 所有阈值：`settings.match_threshold=0.85` 为默认；各锚点专有阈值见下文“视觉锚点”列。

## 1. 证据矩阵（18 状态）

| # | 状态 | 视觉锚点（模板/ROI/阈值/尺度） | 允许动作（intent 枚举） | 后置确认（锚点/像素/等待） | 超时(s) | 恢复目标 | 证据（trace+tick / 截图 / 录像） | 证据等级 |
|---|---|---|---|---|---|---|---|---|
| 1 | 平台地图页 `PLATFORM_MAP` | 场景 `map_create_room` → 模板 `lobby/create_room`；thr=0.85；尺度 `_l0_scales()`（绝对 1.0 优先）；fallback=`null`。函数 `_find_map_create_room()`；`config/scenes.json`。**blue_button_color/左右位置/按钮数量均无点击权** | `CreateRoom-open`；同帧可转 `SelectStage-target`（stage_page）/ `RoomStart`（room_start）/ 转 `CREATE_ROOM` | 专用 `create_room_confirm` 锚点命中 → `CREATE_ROOM`；或 `room_start` 命中 → `ROOM_WAITING`；弹窗未出现=零输入等待 | 创房总预算 `_CREATE_ROOM_TOTAL_TIMEOUT_S=15`、确认窗 `_CREATE_ROOM_CONFIRM_WINDOW_S=4`、重试 `_CREATE_ROOM_MAX_ATTEMPTS=3`；不健康帧 `l0_timeout=max(30,min(query,60))` | `ERROR`（Fail-Closed；“create room button not found”/“create dialog confirmation timeout”，绝不点快速加入） | r6 卡死：`trace_20260812_002654.jsonl` tick1-57（1328×945，57 tick 全 `ctx=UNKNOWN`、scenes 空、零输入）+ `incidents/20260812/incidents/incident_002658_907`、`incident_002707_833`（unknown_page ≥2s）；r5 误点缺陷：`trace_20260812_001250.jsonl` tick2/5/8（3×`click:blue_button_color @(1120,913)`=快速加入）+ `incident_001308_742`（create dialog confirmation timeout）；r7 修复证据：incident 原帧回放 `create_room 0.974 @ local(719,871)`、真实窗口诊断 `ui_scale=0.83 context=PLATFORM_MAP map_create=True`（handoff §3.3） | I+U+R+(L 仅缺陷行为) |
| 2 | 建房弹窗 `CREATE_ROOM` | 场景 `create_room_confirm` → 模板 `lobby/create_room_confirm`；thr=0.85；尺度 `_l0_scales()`；小窗（≤800×700）fallback `blue_bottom_dialog_roi`+`find_input_boxes≥2`。函数 `_find_create_confirm()` | `CreateRoom-confirm` | `room_start` 命中 → `ROOM_WAITING`（“create confirmed”） | 确认窗 4.0s；总预算 15s | 超时→`PLATFORM_MAP`（“create dialog timeout”，不假报）；预算耗尽→`ERROR` | `trace_20260811_205100.jsonl` tick4（`ctx=CREATE_ROOM` size=[584,488] 独立小窗）、tick6 `CreateRoom-confirm`（旧版 fallback 行为）；215307/232040 同构；r5 弹窗始终未出现 → `incident_001308_742` | I+U+(L 仅旧版/缺陷) |
| 3 | 选关页 `STAGE_SELECT` | `_find_stage_page()`：`visible_stage_rows()`（numpy 字形行解析，memo）优先 + 模板 `stage1/2/3/4` 于 `_STAGE_ROWS_ROI=(0.45,0.05,0.85,0.60)`、hot 尺度、排除 stage/toHero/HeroChallenge、x≥0.55w；目标关卡 `find_stage_labels()`/`find_stage_in_range()`（stage_targets 或 1-12 连续段） | `SelectStage-target`（click:stage_target_1-15 等）；`StageStart`（场景 `stage_start`，thr 0.85）；`OpenHeroModeModal`（`lobby/stage_hero_mode_btn` thr 0.90） | 语义确认 `_stage_target_has_consistent_neighbor()`（同名/相邻连续关卡）；点开始→`STAGE_STARTING` startChallenge 子状态机（WAIT_TRANSITION→VERIFY_INGAME→DONE，局内锚点连续 **2 帧**→`MAIN_LINE`） | 目标未找到：`_action_timed_out`（query_timeout=60）；选关后验证超时→回选关页重选（attempts 2）；重试耗尽/页面异变→ERROR | `ROOM_WAITING`（选关页消失）/ `STAGE_SELECT` 重选 / `ERROR` | `trace_20260811_205100.jsonl` tick153-163（t159 `SelectStage-target` 1-15、t163 `OpenHeroModeModal`）；215307 tick150-176（1-13）；232040 tick146-156；keyframes `t_003s_stage_select_archive_panel.png`、`t_010s_stage_select_hover.png`、`t_027s_STAGESELECT疑似面板.png`；fixtures `live_postgame_20260808/live_stage_select.png` | I+U+L(旧版) |
| 4 | PREPARE-房间等待 `ROOM_WAITING`（含退出后回房验证） | 场景 `room_start` → 模板 `kk_start`/`lobby/room_start`/`lobby/room_start_alt`/`lobby/startGameBtn`/`startGameBtn`；`_ROOM_START_ROI=(0.60,0.55,0.86,0.95)`（排除右部活动/宠物 0.883 误命中）；thr 0.85；`_l0_scales()`；fallback `blue_room_start_roi`（仅 L0 门闩）。函数 `_find_room_start()` | `RoomStart`（click:kk_start）；`RoomStart-retry`（1 次重试）；回房验证期零输入 | 点开始→`ROOM_STARTING`（deadline min(query,15)）；退出确认后 PREPARE 等待 `room_start` 重现 → `ROOM_WAITING`（“same room verified”） | 房间等待超时=query_timeout（60）；退出回房窗 `min(query,30)=30`；L0 cycle `_l0_cycle_limit` | `PLATFORM_MAP`（auto 创房重试，cycle 上限→ERROR）/ `LOBBY_ROOM`（手动）/ `ERROR`（“same room return timeout”） | `trace_20260811_205100.jsonl` tick9-10（ROOM_WAITING 1224×904 → t10 `RoomStart`）；215307/232040 同构；fixtures `replay/room_waiting_host.png`；回房验证 R 级：录屏 `20260810_214444.mp4` 回放含“返回原房间”（handoff §3.6）；旧版 trace 回房段未闭环（205100 tail tick1478-1529 零动作至 trace 结束） | I+U+R+L(旧版) |
| 5 | 开局奖励弹窗（上局神赐奖励 `failGiftClose`） | 模板 `failGiftClose`；thr=0.82；ROI `(0.45,0.15,0.70,0.45)`；hot 尺度（`_tick_main_line` 内 find）。场景 `close` 亦含该模板 | `DismissFailureReward`（专用小叉，唯一授权） | 弹窗消失（main_line_since 刷新；无独立后置锚点，靠次帧不再命中） | 3 次尝试（间隔 ui_action_interval_s=1.5）→ ERROR | `ERROR`（“failure reward popup did not close”） | **缺少真实证据**：全部 trace 扫描 `failGiftClose` 0 命中；仅 U：`tests/test_live_run_205044_regressions.py`（断言 `DismissFailureReward` 被调用） | I+U |
| 6 | `MAIN_LINE` HUD | `_is_in_game_hud()`：env 锚点 `zidong`(ROI 0.05,0.58,0.42,0.82)/`shortKey`(0.70,0.10,1.0,0.55)/`mainIdentifier`(全帧)，thr=0.85，hot 尺度；场景 `skill_panel`/`card_panel`；4 挑战场景（coin/wood/experience/treasure）thr=`min(0.68,0.85)`、ROI `_HUD_CHALLENGE_ROI=(0,0.62,0.60,1.0)`；或 `_selection_anchor()` | `EnableAutoTask`（auto_task_toggle click_if_off，重试 3）；`金币/木材/经验/宝物Challenge-right_click`（4 挑战，间隔≥1.5s，UNKNOWN 3-30s 跳过）；`OpenSkillPanel`/`OpenBondPanel`/`OpenTreasurePanel`（G/F/V，choice_interval=120s）；`ClickEvolve`；`SelectEquipmentAffix`；`UseInventory-swallow_pill/hero-card`；`BlackMerchant-*`；`Pickup-Z`；`Artifact-Q/W/E`；面板 FSM 选择/刷新/放弃 | 面板 FSM `WAIT_MUTATION` 像素基线变化；动作间隔 `ui_action_interval_s=1.5` | round hard deadline `round_timeout_s=900`（不可续期）→ QUIT；idle watchdog `max(game_timeout,5)=15`min → ERROR；不健康帧 60s → ERROR | `QUIT`（deadline 到期）/ `ERROR` | `trace_20260811_205100.jsonl` tick187-192（EnableAutoTask + 4 挑战右键 + OpenSkillPanel）起至 t1407 整局循环；215307 tick200-1011（含 equipment_affix_0@745、hero-card@468、BlackMerchant-swallow_pill@896）；232040 tick181-336；keyframes `t_003s_局内HUD.png`、`t_006s_面板底部按钮.png` | I+U+L(旧版) |
| 7 | 技能面板（G） | `_selection_anchor()`：`_ANCHOR_NAMES`（skill_giveup_btn/skill_refresh_btn/bond_hide_btn/bond_refresh_btn/treasure_hide_btn/treasure_lock_btn/treasure_refresh_btn/skill_hide/card_hide/hide），thr=`min(0.70,0.85)`，ROI `(0.20,0.50,0.80,0.75)`，hot 尺度；分类 `_classify_choice_panel_at()`（无 bond/treasure 专有按钮→skill）；OCR 槽 ROI `(0.286,0.178,0.421,0.255)/(0.433,0.178,0.568,0.255)/(0.579,0.178,0.714,0.255)`；HUD 按钮比 `(0.9025,0.867)` | `技能选择`（仅配置技能：click:asj/asjg/assx/jq 等）；`技能刷新选择`；`技能放弃选择`（giveUp，需面板锚点存在）；`CloseSkillPanel`（无配置命中时点按钮关闭） | 面板 FSM WAIT_MUTATION（ROI 像素变化） | unknown 面板超时（`_selection_unknown_attempts` 上限）→ ERROR | `ERROR`（“unknown selection panel timeout”，不盲点隐藏）/ FSM 继续 | `trace_20260811_215307.jsonl` tick269-290（OpenSkillPanel→asjg→jq→刷新→giveUp）；232040 tick232-242、300-312（持久技能面板刷新/放弃）；keyframes `t_015s_技能面板_giveUp证据.png`、`t_063s_技能面板.png`、`t_234s_技能面板.png`；fixtures `replay/skill_choice_3.png`；U：test_s0_safety_state_machine（AMBIGUOUS_GIVEUP） | I+U+L(旧版) |
| 8 | 羁绊面板（F） | 分类锚点 `bond_hide_btn`/`bond_refresh_btn`（thr=`min(0.70,0.85)`，ROI `_PANEL_BUTTONS_ROI`）；OCR 槽 `(0.254,0.180,0.410,0.265)/(0.425,0.180,0.581,0.265)/(0.596,0.180,0.752,0.265)`；HUD 按钮比 `(0.864,0.867)` | `OpenBondPanel`；`bond选择`（OCR 名或 rarity：ocr_bond:祝福/成长/法术/藏宝图(三)/体术…）；`CloseBondPanel` | 面板 FSM WAIT_MUTATION；episode 上限 `panel_episode_limit_per_kind=5` | unknown 面板超时→ERROR | `ERROR` / FSM 继续 | `trace_20260811_215307.jsonl` tick305-323（ocr_bond:祝福/成长/法术）；232040 tick244-260、314-336（持久羁绊面板未识别→t336 ERROR “unknown selection panel timeout”）；keyframe `t_036s_羁绊面板.png`；fixtures `replay/bond_choice_3.png` | I+U+L(旧版) |
| 9 | 宝物面板（V） | 分类锚点 `treasure_lock_btn`+`hide`(0.95)；OCR 槽 `(0.286,0.190,0.418,0.265)/(0.433,0.190,0.565,0.265)/(0.582,0.190,0.714,0.265)`；HUD 按钮比 `(0.861,0.811)` | `OpenTreasurePanel`；`treasure选择`（OCR 名/品质回退 `fallback_first`）；`CloseTreasurePanel` | 面板 FSM WAIT_MUTATION | unknown 面板超时→ERROR | `ERROR` / FSM 继续 | `trace_20260811_215307.jsonl` tick326-332（ocr_treasure:力之极/属性神符）、tick675-681（rarity_orange→fallback_first）、724、937-945；232040 tick230、267-273；fixtures `replay/treasure_choice_3.png` | I+U+L(旧版) |
| 10 | 装备属性选择（十级词缀弹窗） | `_find_equipment_affix_choice()`：**仅 1600×900**；HSV/灰度形态门禁（body `gray[210:445,560:1040]` 暗像素占比≥0.85、金色条带 `gold[195:245,560:1040]≥2000` 与 `[405:455]≥900`、4 行 `(240,285,330,375)` 亮像素各≥450）；行优先级 红>橙>紫>蓝；点击 `(800, row+20)` | `SelectEquipmentAffix`（equipment_affix_0..3）；前置 `UpgradeEquipmentSlot1-max`（右键装备槽） | 命中即处理：`_equipment_pending_until=0` + `_advance_l1_cycle("equipment")`；main_line_since 刷新 | 无独立超时（每次命中即处理；不健康由 idle watchdog 兜底） | `MAIN_LINE` 循环继续 | `trace_20260811_215307.jsonl` tick677（UpgradeEquipmentSlot1-max）、tick745（equipment_affix_0）；232040 tick290、294 | I+U+L(旧版) |
| 11 | 胜利结算 `POST_VICTORY` | `_post_game_state()`：模板 `continueGame` thr=0.80、ROI `(0.40,0.50,0.65,0.75)`（endgame fixtures 实测 0.874 @(800,587)）；后置存档面板关闭 `lobby/archive_panel_close` thr=0.85 ROI `(0.55,0.15,0.70,0.35)`（实测 close 1.000 @(996,239)、archiveChallenge 0.945 @(798,45)）；胜利链前先查 PAUSED（pauseGame 0.80 居中） | `ContinueGame`（≤3）；`CloseArchivePanel`（≤3）；随后自动秘境链（`OpenGreatRift`/`ConfirmGreatRift`）或直接 `QuitGame-open-confirm` | 胜利页消失→`ARCHIVE_PANEL`→`NPC_HUB`（damijing+quit+HeroChallenge 多锚点）→ `_record_round_outcome(VICTORY)` → `QUIT` | 胜利页关闭 `min(query,30)=30`；ContinueGame 3 次；post-game transition 30s | `QUIT`（NPC 广场验证后）/ `ERROR` | **无 L**；R：fixtures `reborn_wow/endgame/victory_continue.png`、`replay/victory_continue.png`、录屏 `20260810_214444.mp4` 回放（handoff §3.6）、keyframe `t_001s_victory.png`、`fixtures/live_postgame_20260808/live_archive_*.png`；U：`tests/test_p1b0_post_game.py`（7 tests） | I+U+R |
| 12 | 普通失败（强失败弹窗） | 场景 `fail` → 模板 `fail`/`gameFail`（强失败优先级最高，thr 0.85；`giveUp` 已独立无恢复权）；2 帧连续证据抢占；`_find_failure_exit_button()`：强 fail 锚点 + 红/绿兄弟按钮 HSV（ROI `(0.30-0.70w, 0.55-0.74h)`，尺寸 70-180×22-65） | `Recovery-FAIL-FAIL_CONFIRM`（`ok` 场景或 `failure_exit`）；`Recovery-FAIL-FAIL_CLOSE`（`close`）；`Recovery-FAIL-FAIL_EXIT_CONFIRM`（exit_confirm） | 每步门闩 `anchor∧input_ok∧(mutation∨post_anchor)`（`_recovery_post_confirmed`）；失败页消失 ∨ `close` 出现 | 总预算 `recovery_timeout_s=60`（不可续期）、每步 `recovery_action_limit=3`、间隔 `recovery_retry_interval_s=1.5` | 恢复完成→`QUIT`；direct exit→`PREPARE`（回原房间）；预算耗尽→`ERROR` | 旧版抢占：`trace_20260811_205100.jsonl` tick1420-1478（gameFail 0.97 连续 ~58 帧→t1478 进 RECOVER_FAILURE，旧版恢复零动作无兜底）；R：录屏 `20260810_214444.mp4` 回放 `failure_open_exit (76,58) → exit_confirm_btn (740,554) → PREPARE`（handoff §3.6）；U：test_s0_safety_state_machine；XFAIL `fail_recovery_three_frames`（缺当前版本全屏失败弹窗素材） | I+U+R |
| 13 | 大秘境 NPC 页（挑战广场） | `_post_game_state()`→`NPC_HUB`：`quit`（x≤0.10w,y≤0.15h, thr 0.75）+ `damijing`（x≥0.60w, y 0.15-0.55h, thr 0.80）+ `HeroChallenge`(0.85)；`_find_secret_realm_npc()`：damijing thr=0.80 ROI `(0.60,0.15,0.85,0.55)`、位置 (0.60-0.85w, 0.15-0.55h)（fixtures 实测 0.930 @(1132,307)） | `OpenGreatRift`（右键 NPC，≤3 次，间隔 1.5s）；不自动秘境时 `QuitGame-open-confirm`（左上 quit） | `GREAT_RIFT_CONFIRM` 出现（mijingOk/ok 中央） | 3 次或 `min(query,15)=15` → ERROR；确认后过渡帧 15s（防二次右键） | `QUIT`（不挑战）/ `ERROR` | **无 L**；R：fixtures `reborn_wow/endgame/challenge_npc_hub.png`（damijing 0.930@(1132,307)、HeroChallenge 0.944@(351,116)、quit 0.878@(75,52)）、录屏回放 `damijing (1262,247)`（handoff §3.6）；U：test_p1b0_post_game | I+U+R |
| 14 | 大秘境确认页 | `GREAT_RIFT_CONFIRM`：`mijingOk`(0.75)/`ok`(0.85) 中央 ROI `(0.30-0.60w, 0.40-0.65h)`（fixtures 实测 mijingOk 0.910@(714,478)+ok 0.932@(715,478)）；`_find_great_rift_accept` thr=0.80 ROI `(0.30,0.40,0.60,0.65)`；`_find_great_rift_cancel` 同锚点反推“否”(+0.104w) | `ConfirmGreatRift`（是，≤3）；`CancelGreatRift`（否，≤3） | 确认框消失→过渡帧零输入→`_is_in_game_hud` 确认（置 `_secret_realm_active`、重启 round deadline 900s） | 3 次或 15s → ERROR（“great rift confirm/dialog verification/entry verification timeout”） | `MAIN_LINE`（HUD 确认后）/ `ERROR` | **无 L**；R：fixtures `reborn_wow/endgame/great_rift_confirm.png`、录屏回放 `mijingOk (713,481)`（handoff §3.6）；U：test_p1b0_post_game | I+U+R |
| 15 | 大秘境 HUD（秘境局内） | `_is_in_game_hud()`（同 MAIN_LINE env 锚点）+ `_secret_realm_active` 状态位 | 局内循环全部动作（G/F/V/挑战/进化/装备/Z/黑商/神器）+ 失败抢占（2 帧） | 失败→`failure_open_exit`→`exit_confirm`→`PREPARE`；胜利链同普通局 | round deadline 重启 900s；HUD 确认窗 15s | `MAIN_LINE` 循环 / `PREPARE`（失败退出后） | **无 L**；R：录屏 `20260810_214444.mp4` 回放（进入：damijing→mijingOk→过渡帧零输入→HUD；handoff §3.6） | I+U+R |
| 16 | 大秘境失败（自然结束） | 强失败 2 帧抢占（`fail` 场景）；`_find_game_exit()`：`quit` thr=0.78 ROI `(0,0,0.12,0.15)`、位置 x≤0.12w,y≤0.15h（录屏实测 (76,58)）→ `failure_open_exit` | `Recovery-FAIL-FAIL_CONFIRM`（failure_open_exit 专用左上退出）；`Recovery-FAIL-FAIL_EXIT_CONFIRM`（exit_confirm_btn，录屏实测 (740,554)） | exit_confirm 出现→`_finish_direct_failure_exit`→`PREPARE` 验证同房间；outcome=`VICTORY`（主图已胜，不计入失败三连熔断） | `recovery_timeout_s=60` | `PREPARE`（同房间）→ `ROOM_WAITING` | **无 L**；R：录屏 `20260810_214444.mp4` 回放 `failure_open_exit (76,58) → exit_confirm_btn (740,554) → PREPARE`（handoff §3.6）；U：test_s0_safety_state_machine | I+U+R |
| 17 | 标准退出确认 `QUIT`→`NEXT` | `_find_game_exit()`：`quit` thr=0.78 ROI `(0,0,0.12,0.15)`、x≤0.12w/y≤0.15h；`_find_exit_confirm()`：`lobby/exit_confirm_btn` thr=0.78 ROI `(0.38,0.50,0.50,0.68)`、位置 (0.38-0.50w, 0.50-0.68h)（录屏实测 (740,554)） | `QuitGame-open-confirm`（≤3）；`QuitGame-confirm`（≤3） | 确认点击→`PREPARE`（“exit confirmed; verify same room”）窗 `min(query,30)=30` → `ROOM_WAITING` | 退出窗 `timeout=max(3,min(query,15))=15`（自 `_exit_since`） | `NEXT`（点退出后）→`PREPARE`→`ROOM_WAITING`；超时→`ERROR` | **无 L**（205100 tail 的 QUIT ctx 仅旧版零动作，无确认点击）；R：keyframe `t_039s_exit_confirm.png`、fixtures `live_postgame_20260808/live_exit_button.png`+`live_exit_confirm.png`、录屏回放 exit_confirm_btn (740,554)；U：test_p1b0_post_game / test_s0_safety_state_machine | I+U+R |
| 18 | 断线重连 | 场景 `disconnect` → 模板 `gameDisconnect`/`retryConnect`（thr 0.85，priority 高于 fail）；2 帧抢占→RECOVER_FAILURE(DISCONNECT) | `Recovery-DISCONNECT-DISCONNECT_RETRY`（**仅模板名为 `retryConnect` 才点击**；`gameDisconnect` 文字模板→零输入等待；绝不点 fail 的 ok/close） | disconnect 消失 ∨ `_selection_anchor` ∨ `_is_in_game_hud` → 恢复完成→`QUIT` | `recovery_timeout_s=60`、动作上限 3 | `QUIT`（恢复完成）→`PREPARE`；超时→`ERROR` | **缺少真实证据**（素材缺失：6333 帧录屏扫描 gameDisconnect/retryConnect 0 命中，`fixtures/manifest.json` `missing_disconnect_modal`；XFAIL `fail_recovery_three_frames`）；仅 U：test_s0_safety_state_machine `test_disconnect_uses_disconnect_path`（合成 matcher） | I+U |

## 2. 代码依据（函数级）

| # | 状态 | 关键函数（`src/gamescript/mediator.py` 除注明外） |
|---|---|---|
| 1 | 平台地图页 | `_tick_l0()`（PLATFORM_MAP 分支）、`_find_map_create_room()`、`_find_create_confirm()`、`_l0_scales()`、`find_scene()`/`_L0_GATE_SCENES`、`config/scenes.json: map_create_room(fallback:null)` |
| 2 | 建房弹窗 | `_find_create_confirm()`、`_tick_l0()`（CREATE_ROOM 分支）、`_CREATE_ROOM_CONFIRM_WINDOW_S/_TOTAL_TIMEOUT_S/_MAX_ATTEMPTS`、`find_blue_buttons`/`find_input_boxes`（`vision/matcher.py`） |
| 3 | 选关页 | `_find_stage_page()`、`_find_stage_target()`、`_stage_target_has_consistent_neighbor()`、`_visible_stage_rows()`、`_find_hero_entry()`、`_tick_l0()` STAGE_SELECT/STAGE_STARTING（startChallenge 子状态机）、`vision/stage_selector.py` |
| 4 | 房间等待/回房 | `_find_room_start()`、`_tick_l0()` ROOM_WAITING/ROOM_STARTING、`_tick_l1_tail()` NEXT→PREPARE 尾部、`_room_action_deadline`、`_l0_cycle_count` |
| 5 | 开局奖励弹窗 | `_tick_main_line()` failGiftClose 分支、`DismissFailureReward` |
| 6 | MAIN_LINE HUD | `_is_in_game_hud()`、`_compute_context()`、`_ensure_auto_task_enabled()`、`_ensure_challenge_buttons()`、`_maybe_open_choice_panel()`、`_maybe_fire_artifacts()`、`_maybe_black_merchant()`、round deadline/idle watchdog |
| 7 | 技能面板 | `_selection_anchor()`、`_classify_choice_panel_at()`、`_find_reward_choice()`、`_tick_panel_fsm()`、OCR `_OCR_SLOT_ROIS["skill"]`、`_handle_self_opened_compact_panel()` |
| 8 | 羁绊面板 | 同上（bond 分类/OCR 槽/`OpenBondPanel`）、`_maybe_open_choice_panel()` |
| 9 | 宝物面板 | 同上（treasure 分类/OCR 槽/`OpenTreasurePanel`）、`_find_reward_choice()` 品质回退 |
| 10 | 装备属性 | `_find_equipment_affix_choice()`、`_maybe_upgrade_equipment()`、`_advance_l1_cycle()` |
| 11 | 胜利 | `_post_game_state()`、`_tick_main_line()` POST_VICTORY/ARCHIVE_PANEL/NPC_HUB 分支、`_find_archive_panel_close()`、`_record_round_outcome()` |
| 12 | 普通失败 | `_tick_impl()` 强失败 2 帧抢占、`_begin_recovery()`、`_tick_recovery()`、`_recovery_anchor/_action/_post_confirmed()`、`_find_failure_exit_button()` |
| 13 | 大秘境 NPC | `_post_game_state()` NPC_HUB、`_find_secret_realm_npc()`、`act_right_click(OpenGreatRift)` |
| 14 | 大秘境确认 | `_post_game_state()` GREAT_RIFT_CONFIRM、`_find_great_rift_accept()/_find_great_rift_cancel()`、`ConfirmGreatRift/CancelGreatRift` |
| 15 | 大秘境 HUD | `_is_in_game_hud()` 入口验证、`_secret_realm_active`、`_tick_main_line()` 秘境段 |
| 16 | 秘境失败 | `_tick_recovery()` FAIL 路径、`_find_game_exit()`→`failure_open_exit`、`_finish_direct_failure_exit()` |
| 17 | 标准退出 | `_tick_l1_tail()` QUIT/NEXT、`_find_game_exit()`、`_find_exit_confirm()` |
| 18 | 断线重连 | `_tick_impl()` disconnect 抢占、`_recovery_anchor/_action()`（DISCONNECT_RETRY 仅 retryConnect）、`_finish_recovery()` |

## 3. 证据等级汇总（I/U/R/L/S）

| # | 状态 | I | U | R | L | 说明 |
|---|---|---|---|---|---|---|
| 1 | 平台地图页 | ✓ | ✓ | ✓ | △ | r7 修复有 incident 原帧回放（R）+ 旧版缺陷真机（L 非 r7）；**r7 正确行为无 L** |
| 2 | 建房弹窗 | ✓ | ✓ | — | △ | 弹窗小窗 584×488 真机见过（旧版）；r5 缺陷现场（弹窗未出）；r7 专用锚点链无 L |
| 3 | 选关页 | ✓ | ✓ | — | ✓ | 旧版真机完整（1-13/1-15 选择+开始+英雄模式）；r7 无 L |
| 4 | 房间等待/回房 | ✓ | ✓ | ✓ | △ | 房间页旧版真机 ✓；回房验证 R 级（录屏回放含返回原房间）；**回房验证无任何版本 L**（旧版 tail 零动作） |
| 5 | 开局奖励弹窗 | ✓ | ✓ | — | — | **仅 U**；trace 0 命中，缺真实证据 |
| 6 | MAIN_LINE HUD | ✓ | ✓ | — | ✓ | 旧版真机整局循环 ✓；r7 无全链 L |
| 7 | 技能面板 | ✓ | ✓ | ✓ | ✓ | 旧版真机完整（选择/刷新/放弃/unknown 超时 ERROR）；fixtures skill_choice_3 |
| 8 | 羁绊面板 | ✓ | ✓ | ✓ | ✓ | 旧版真机完整（含持久面板→ERROR 现场）；fixtures bond_choice_3 |
| 9 | 宝物面板 | ✓ | ✓ | ✓ | ✓ | 旧版真机完整（OCR/品质回退）；fixtures treasure_choice_3 |
| 10 | 装备属性选择 | ✓ | ✓ | — | ✓ | 旧版真机 2 trace（affix_0 两次） |
| 11 | 胜利 | ✓ | ✓ | ✓ | — | R（endgame fixtures + 录屏回放）；**r7 无 L** |
| 12 | 普通失败 | ✓ | ✓ | ✓ | △ | 旧版抢占真机（但恢复零动作=旧版缺陷）；当前版恢复链仅 R/U；XFAIL 缺素材 |
| 13 | 大秘境 NPC | ✓ | ✓ | ✓ | — | R（endgame fixtures + 录屏回放）；**r7 无 L** |
| 14 | 大秘境确认 | ✓ | ✓ | ✓ | — | R（endgame fixtures + 录屏回放）；**r7 无 L** |
| 15 | 大秘境 HUD | ✓ | ✓ | ✓ | — | R（录屏回放）；**r7 无 L** |
| 16 | 秘境失败 | ✓ | ✓ | ✓ | — | R（录屏回放）；**r7 无 L** |
| 17 | 标准退出确认 | ✓ | ✓ | ✓ | — | R（keyframe t_039s + live_postgame fixtures + 录屏回放）；**r7 无 L** |
| 18 | 断线重连 | ✓ | ✓ | — | — | **仅 U**；素材缺失（6333 帧 0 命中），XFAIL |

图例：✓=有该级证据；—=无；△=有真机记录但属旧版/缺陷行为，不算当前版 L。
**S 级（3/10 局无人值守）：18 行全部未达到。**

## 4. 特别标注

1. **只有单测（U）无真机（L）证据的状态（r7 口径）**：
   - **开局奖励弹窗（#5）**：仅 `test_live_run_205044_regressions.py`；全部 trace 0 命中，连 R 级都没有；
   - **断线重连（#18）**：仅 `test_s0_safety_state_machine.py`（合成 matcher）；6333 帧录屏扫描 0 命中，`missing_disconnect_modal` 持续 XFAIL；
   - **胜利链（#11）、大秘境全部 4 状态（#13-16）、标准退出确认（#17）**：有 R 级（当前版本截图 fixtures + `20260810_214444.mp4` 真实录像帧回放）但**无 r7 真机 L**；handoff §5 第 3/4 条明确列为待验证。
2. **回房验证（#4 PREPARE 尾部）**：所有 trace 均未出现“退出确认→回到原 KK 房间→再开始下一局”闭环；旧版 205100 tail 在 RECOVER_FAILURE 零动作直到 trace 结束。该后置确认链当前只有 U 级。
3. **创房正确链（#1/#2，r7 修复后）**：专用模板回放命中 `create_room 0.974 @ local(719,871)`（R 级，来自 r6 incident 原帧）+ `ui_scale=0.83 context=PLATFORM_MAP map_create=True`（真实窗口只读诊断），但**尚未有 r7 真机点击+弹窗后置确认的 L 级证据**（handoff §5 第 1 条）。
4. **旧版真机 trace 中的已禁止行为**：`trace_20260812_001250.jsonl`（r5，3×`click:blue_button_color` 误点“快速加入”）与 `trace_20260811_*.jsonl`（`ocr-hybrid-dev`，创房走 blue 兜底）是**反面证据**，正是 `goal-objective.md` 问题 1-12 中创房问题（Q 系列）的现场，仅作修复前后对照，不得作为当前行为依据。
5. 全部 18 状态的**允许动作均为确定性规则**：每 tick ≤1 输入、输入间隔 ≥`ui_action_interval_s=1.5`、OCR 只提供名称不提供坐标、unknown 一律零输入/超时 Fail-Closed；`blue_button_color` 无任何创房/快速加入点击权限。

---

*生成：EVIDENCE-MATRIX（只读），2026-08-12。证据源：代码 `src/gamescript/mediator.py`(r7 worktree)、`config/scenes.json`、`%LocalAppData%\GameScript-Local\20260811|20260812\trace_*.jsonl`、`%LocalAppData%\GameScript-Local\incidents\`、`C:\tmp\recordings\keyframes\`（27 张）、`C:\Users\10639\Desktop\录屏素材\20260810_214444.mp4`（R 级回放源）、`fixtures/reborn_wow/endgame/*`、`fixtures/replay/*`、`fixtures/live_postgame_20260808/*`、`docs/P1B0_POST_GAME_STATE_MODEL.md`、`docs/CURRENT_STATUS_AND_HANDOFF_20260812.md`。*
