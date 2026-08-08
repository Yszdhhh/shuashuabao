# Mediator 审查

审查范围：`src/gamescript/mediator.py`（约 2189 行）及直接依赖的 `settings.py` / `vision/capture.py` / `vision/matcher.py` 交界行为。  
已知历史问题（全屏识别 8.3s、WAIT_MODAL 遮挡、冻结帧误杀、选关/房间误判、滚动方向、未知面板 Fail-Closed）不重复展开，仅在有新角度时提及。

---

## P0 致命（卡死/误操作/资源泄漏）

### 1. 跨局 `_stage_selected` 残留 → 次局可能跳过选关或点错关
- **文件:行号**: `mediator.py:1327-1344`, `1516-1537`, `1679-1747`, `2130-2138`
- **现象**: 第一局在 `STAGE_SELECT` 把 `_stage_selected=True` 后进入英雄/主线；退出确认后 `NEXT → PREPARE`（`_awaiting_room_return`）→ 验房 `ROOM_WAITING` → 再进 `STAGE_SELECT` 时，**不会**清掉上一局的选关标志与目标名。
- **根因**: `set_phase` 只在切入 `LOBBY_ROOM` / `PLATFORM_MAP` 时重置 `_stage_selected` / `_stage_target_*`；多局热路径是 `PREPARE → ROOM_WAITING → STAGE_SELECT`，两条都不清标志。`STAGE_SELECT` 分支仅重置 scroll/hero 状态：
  ```python
  if phase == Phase.STAGE_SELECT:
      self._stage_scroll_attempts = 0
      # 未重置 _stage_selected / _stage_target_name / _stage_target_position
  ```
- **影响**: 次局直接走「已选关」确认链；若 `verify_stage_selection` 假阳性或列表仍显示同名行，可能**不点关卡直接点开始**；否则空等至 `_room_action_deadline`（默认 `query_timeout=60s`）才回落重选。
- **加固建议**:
  - 在 `set_phase(Phase.STAGE_SELECT)` 与 `set_phase(Phase.ROOM_WAITING)`（从局内返回时）强制：
    `_stage_selected=False; _stage_target_name=None; _stage_target_position=None`
  - 或在 `set_phase(Phase.MAIN_LINE)` / 退出确认成功时统一 `_reset_l0_stage_flags()`。
  - 回归：两局连续 `ROOM→STAGE→MAIN→QUIT→ROOM→STAGE`，断言每局必经一次 `SelectStage-target` 点击日志。

### 2. 挑战按钮缺失被当成 UNKNOWN → 约 30s Fail-Closed 整机停机
- **文件:行号**: `mediator.py:1021-1103`, `2026-2030`; 超时 `max(3, min(query_timeout, 30))` 默认 **30s**
- **现象**: 主线早期 HUD 尚未刷出底部四挑战、或某一挑战未解锁时，`label_hit is None` → `_resolve_challenge_state` 返回 `UNKNOWN` → **当 tick 直接 `Continue` 阻断**自动任务之后的选关/进化/神器；连续 UNKNOWN 满 `unknown_timeout` 后 `Phase.ERROR` + `stop()`。
- **根因**: UNKNOWN 语义把「没找到按钮」和「找到但绿字模糊」混为一谈；且注释写明 *ONLY when all 4 challenges are confirmed ON* 才放行下游，与「挑战是增强项、不应阻塞主线」矛盾。
- **影响**: 正常开局只要底部条晚于 30s 出现，或根本无某挑战，挂机直接停机（误杀，非卡死但致命）。
- **加固建议**:
  - 拆状态：`MISSING`（无 label）vs `AMBIGUOUS`（有 label 但绿字不清）。
  - `MISSING`：不占 fail 计时；可跳过该键继续下一个；四键皆缺失时 **放行下游**（选关/选择面板），仅打 debug。
  - `AMBIGUOUS`：保持零输入等待，超时可降级为 skip 该键并记入 `_challenge_done`（或独立 `_challenge_skipped`），避免 `stop()`。
  - 仅在「明确 OFF 且右键 ≥3 次仍 OFF」时 Fail-Closed。

### 3. `set_phase(ROOM_STARTING|STAGE_STARTING)` 覆盖调用方 deadline/attempts
- **文件:行号**: `mediator.py:1339-1341`, `1624-1628`, `1745-1747`, `1645-1665`, `1751-1770`
- **现象**: 点击开始后调用方写入：
  ```python
  self._room_action_attempts = 1
  self._room_action_deadline = time.time() + min(query_timeout, 15)
  self.set_phase(Phase.ROOM_STARTING, ...)
  ```
  但 `set_phase` 内无条件执行：
  ```python
  if phase in (Phase.ROOM_STARTING, Phase.STAGE_STARTING):
      self._room_action_deadline = time.time() + self.settings.query_timeout  # 默认 60s
      self._room_action_attempts = 0  # 清零
  ```
- **根因**: 相位入口的「默认初始化」无区分「首次进入」与「调用方已设置重试上下文」，后写覆盖先写。
- **影响**:
  - 预期 15s 验页变成 60s，失败检出变慢。
  - attempts 被清零，重试计数与日志「已点击」不一致，可能多点 1 次开始键。
  - 与 ROOM_STARTING 不健康帧永不超时（见 P1）叠加时更难收敛。
- **加固建议**:
  - `set_phase` **不要**无条件改 deadline/attempts；改为 `_enter_room_starting(deadline=..., attempts=1)` 显式 API。
  - 或仅当 `_room_action_deadline is None` 时填充默认值；attempts 用 `max(existing, 0)` 且不归零。

---

## P1 严重（稳定性/边界）

### 4. `ROOM_STARTING` 不健康帧路径永不看 deadline → 可能永久挂起
- **文件:行号**: `mediator.py:1808-1834`
- **现象**:
  ```python
  if self.phase == Phase.ROOM_STARTING:
      pass  # Use normal retry deadline
  elif ...
  return LoopAction.Continue
  ```
  注释声称走「正常重试 deadline」，但 **未调用** `_action_timed_out()`，也不进入 15s/60s 不健康超时分支。
- **根因**: 分支写了 `pass` 后统一 `Continue`，把「跳过决策」和「仍要推进超时」混在一起。
- **影响**: 房间点开始后若长时间黑屏/截屏失败/最小化，主循环只睡 `loop_sleep_ms`，**永不 ERROR、永不回 ROOM_WAITING**。
- **加固建议**: 不健康帧统一：`if self._action_timed_out():` 走与健康帧相同的 ROOM_STARTING 回退；或对 ROOM_STARTING 使用 `min(query_timeout, 30)` 的 missing-window 时钟。

### 5. `HERO_SETUP` 不健康帧 15s 误杀 vs 步骤观察窗最高 60s
- **文件:行号**: `mediator.py:1180-1189`, `1218-1225`, `1808-1833`
- **现象**: `_hero_observation_timeout()` = `max(20, min(query_timeout, 60))`（默认 60s）；但不健康帧对非 BOOT/非局内相位置 `elapsed >= min(query_timeout, 15)` → **15s** 停机。`HERO_SETUP` 不在 `in_game_phases`。
- **根因**: 全局不健康超时表未纳入英雄弹窗的慢捕获/过场黑帧。
- **影响**: 点入口后加载/模态动画导致短暂黑帧或 capture 失败连续 15s → 英雄链 Fail-Closed；与已放宽的 WAIT_MODAL 60s 观察窗互相矛盾（新角度：不是遮挡检测本身，是 health 门闸更严）。
- **加固建议**: `HERO_SETUP`（及 `STAGE_STARTING`）使用 `max(_hero_observation_timeout(), _room_action_deadline 剩余)` 或不低于 60s 的 unhealthy 容忍；黑帧可 Continue 但不重置 `_hero_step_deadline` 的已消耗时间需文档化。

### 6. 跨局未重置：`_panel_opened_by_us` / 神器 CD / 主动面板时间戳
- **文件:行号**: `mediator.py:1362-1381`（MAIN_LINE 重置清单）, `779-846`, `1989-2003`
- **现象**: 进入 `MAIN_LINE` 会清 challenge/auto_task/post_game/selection unknown，但 **不会**清：
  - `_panel_opened_by_us`
  - `_last_skill_panel` / `_last_bond_attempt` / `_last_treasure_attempt`
  - `_artifact_next_q|w|e`
  - `_evolve_click_cooldown_until`
- **根因**: 上述字段用 `getattr` 懒挂载，未纳入「新一局」契约。
- **影响**:
  - 上一局主动开面板后异常退出，次局选择面板可能被当成「我们打开的」而点放弃/隐藏。
  - 神器 CD 跨局继承：可能进局 30s 内就按 Q/W/E，或反过来很久不按。
  - 技能 G 可能因 60s 墙钟在次局前数十秒内不触发。
- **加固建议**: `set_phase(MAIN_LINE)` 增加 `_reset_l1_ephemeral()`：面板标记、三件套时间戳、神器 next、evolve CD 全部归零；`_panel_opened_by_us` 写入 `__init__` 显式 `None`。

### 7. 全局断线处理与相位/窗口角色不一致
- **文件:行号**: `mediator.py:1839-1844`, `2090-2128`, `164-188`
- **现象**: 任意相位匹配到 `disconnect`/`fail` 即 `set_phase(QUIT)` 并盲点 `fail/ok/close`。若仍在 L0（KK 窗口），下一 tick `_tick_l1_tail` 在 **游戏窗口关键字** 上找左上角 `quit`，找不到则 ≤15s ERROR。
- **根因**: 恢复动作未区分 L0/L1 上下文；QUIT 假定已在局内 HUD。
- **影响**: 平台断线确认框可能点不到正确按钮；或误进退出状态机后快速停机，无法回到建房。
- **加固建议**: disconnect 时按 `context`/`role` 分支：L0 → 点平台确认后 `PLATFORM_MAP`/`LOBBY_ROOM`；L1 → 现有 QUIT 链。增加 attempts 上限，禁止无限 `click_scene` 空转。

### 8. `Phase.ERROR` / 未实现相位缺少统一出口
- **文件:行号**: `mediator.py:1871-1875`, `2090-2095`, `58-78`
- **现象**: `ERROR` 不在 `_tick_l0/main/l1_tail` 分派表；若未来某路径只 `set_phase(ERROR)` 忘记 `stop()`，会打印 `unhandled phase ERROR` 并 **Continue 空转**。`EARLY_CHALLENGE`/`ANCHOR_BOSS`/`LONGZHU` 一进入即 Fail-Closed（有意），但 `WAIT_UI`/`WAIT_EXIT` 可进入却几乎无专属逻辑，`wait_ui_timed_out()` **从未被调用**（死 API）。
- **加固建议**: `tick` 顶部 `if self.phase == Phase.ERROR: return Break`；删除或接上 `WAIT_UI` 超时；未实现相位保持 Fail-Closed 但集中在一张表。

### 9. 主线 idle 被「无效 Continue」不断续命
- **文件:行号**: `mediator.py:2022-2030`, `2079-2087`
- **现象**: `_ensure_challenge_buttons` 在 UNKNOWN 时返回 `Continue`，调用方 **无条件** `_main_line_since = now`。挑战模糊等待会刷新「主线空闲」时钟，`game_timeout`（默认 15 **分钟**）形同虚设。
- **根因**: 把「有返回值」当成「有有效进度」。
- **影响**: 卡在挑战 UNKNOWN/缺失逻辑时，既可能 30s 误杀（P0-2），若将来放宽 UNKNOWN 又不刷新策略，会 **无限挂机不触发 idle 超时**。
- **加固建议**: 仅在真实点击/确认 ON/选卡成功时刷新 `_main_line_since`；纯等待分支不续命。

### 10. `_awaiting_room_return` 与 `PREPARE` 无双重保险
- **文件:行号**: `mediator.py:1531-1545`, `2130-2138`
- **现象**: 退出确认后依赖 `_awaiting_room_return` + `_room_action_deadline`。若中途 `set_phase` 到其他 L0 相位且标志未清，可能错误阻止建房或错误加 `game_count`。
- **根因**: 标志只在看到 `room_start` 或超时 ERROR 时清理。
- **加固建议**: 进入 `PLATFORM_MAP`/`CREATE_ROOM` 时若 `_awaiting_room_return` 仍为 True → 直接 ERROR（禁止重建房）或明确策略；超时时间与加载动画匹配（当前 `min(query_timeout, 30)`）。

---

## P2 一般

### 11. `WAIT_UI` / `wait_ui_timed_out` 死路径
- **文件:行号**: `mediator.py:65`, `1360-1361`, `1394-1397`, `1552`
- **现象**: 无任何 `set_phase(WAIT_UI)`；超时函数无引用。
- **建议**: 删除或在 `STAGE_STARTING`/`ROOM_STARTING` 复用，避免双轨超时概念。

### 12. `Phase.ERROR` 与 `stop()` 调用约定靠纪律
- **文件:行号**: 多处 `set_phase(ERROR); self.stop()`
- **建议**: 封装 `_fail_closed(reason) -> LoopAction.Break`（英雄模式已有 `_hero_fail`，可提升为通用）。

### 13. 技能候选数非 3/4 时点关闭，可能关掉合法面板
- **文件:行号**: `mediator.py:724-733`
- **现象**: `match_all` 去重后 count∉{3,4} 即点 close；模板不全/遮挡时会误关。
- **建议**: 与未知面板一样先零输入 N 秒，再关；仅 `_panel_opened_by_us` 时立即关。

### 14. `_find_reward_choice` 在 kind 未知时 fallback `"skill"`
- **文件:行号**: `mediator.py:648-656`
- **现象**: 锚点在但分类失败时当技能面板扫 `skills/`，可能选错或空等 10s Fail-Closed（`_tick_main_line` 1994-2015）。
- **建议**: 分类失败 → 直接走 `_close_current_panel` 或 unknown 计时，不要假装 skill。

### 15. `game_timeout` 语义仅出现在主线 idle
- **文件:行号**: `settings.py:66-67`, `mediator.py:2080-2085`
- **现象**: 默认 15（按分钟用）；局内有持续选卡时永远不触发，整局时长无上限。
- **建议**: 区分 `idle_timeout_min` 与 `max_game_duration_min`；后者用独立 `_game_started_at`。

### 16. L0 `BOOT` 在无信号时盲目切 `PLATFORM_MAP`
- **文件:行号**: `mediator.py:1552-1567`
- **现象**: `auto_create_room` 默认 True 时，context=UNKNOWN 也会 `PLATFORM_MAP`，靠地图页 60s 超时兜底。
- **建议**: BOOT 连续 N 帧 UNKNOWN 再进地图；结合 window title 信号。

---

## 性能与流畅度

### 17. 单 tick 模板匹配次数仍然偏多（主热点）
- **文件:行号**: `see` 261-305；`_detect_context` 200-230；`_is_in_game_hud` 190-197；`_tick_main_line` 1877-1990；`_post_game_state` 873-927；`_selection_anchor` 422-455
- **调用链（MAIN_LINE 典型一帧）**:
  1. `see()` → `_scene_cache.clear()` → `_capture_best`：多窗口时 **每个** 候选调用 `_frame_signal` → `_detect_context`（stage 行解析 + 多 scene find）。
  2. `see()` 再 `_detect_context` 一次（缓存命中还好）。
  3. `tick` 全局 `disconnect`/`fail`。
  4. `_tick_main_line`：`_post_game_state` 串行 `continueGame/cjbtiaozhan/mijingOk/ok/archiveChallenge/close/damijing/quit/HeroChallenge`（多尺度）。
  5. 再扫 `archive` / `boss_entry` / `longzhu`。
  6. `_selection_anchor` 最多 10 个模板 × 5 尺度。
  7. 无面板时：auto_task ROI 匹配 + **最多 4 个 challenge** 多尺度 `find_scene` + 像素绿字。
  8. 局内选关 `find_stage_*`；`click_evolve`；神器 HSV；可能 `match_all` 整个 `skills/` 或 `cards/`。
- **缓存**: `_scene_cache` 按 `id(frame)`，`see()` 每 tick `clear()`，**生命周期正确、无跨 tick 泄漏**；同 tick 内 `find_scene` 复用有效。但 `find()`/`match_all`/`_post_game_state` 局部 `find` **不走** scene_cache。
- **加固建议**:
  - `_post_game_state` 结果纳入 per-frame cache；MAIN_LINE 非 `_post_game_pending` 时降频（每 N tick 或每 1s）。
  - challenge 在 `_challenge_done` 已满时跳过整个 `_ensure_challenge_buttons`。
  - `_capture_best` 多窗口：先 title/score 粗排，仅 top-2 跑全量 `_detect_context`。
  - 选择面板：先 ROI 缩图再 `match_all`；技能目录做 stem 索引避免每 tick `glob`。
  - 日志：可选 `settings.debug_match_timing` 打印 see/context/phase 分段耗时。

### 18. `_scene_cache` 内存
- **文件:行号**: `mediator.py:121`, `266`, `333-360`
- **现象**: value 持有 `Frame` 引用；`see()` 开头 clear，正常无泄漏。`_capture_best` 临时 list 中落选 frame 在函数返回后可释放。
- **风险点**: 若未来去掉 per-tick clear 而只靠 id，id 复用可能导致脏缓存（当前无此问题）。
- **建议**: 保持 clear；或改为弱键并只存 results 不存 Frame（已用 `cached[0] is not frame` 防 id 复用，可保留）。

### 19. 英雄模式已避开 context 全屏扫 — 正面肯定
- **文件:行号**: `mediator.py:292-295`, `1519-1522`
- **现象**: `HERO_SETUP` 跳过 `_detect_context` 与 L0 分类，降低 WAIT_LEVEL_* 期间负载。保持即可。

### 20. `loop_sleep_ms=400` 与重匹配叠加
- **文件:行号**: `settings.py:106`, `mediator.py:2183`
- **现象**: 一帧识别若 200–500ms+，有效 tick 周期 0.6–1s+；英雄 60s 窗内样本更少。
- **建议**: 相位自适应 sleep（WAIT_LEVEL_CHANGE 可 100–200ms；MAIN_LINE idle 可 500–800ms）；识别快路径缩短 sleep。

---

## 异常兜底（find_scene / 空帧 / None）

### 21. 空帧/无效帧
- **文件:行号**: `capture.py` `check_frame_health`；`mediator.py:1794-1834`
- **行为**: `bgr is None` / size 0 / `is_valid=False` → `CAPTURE_FAILED` → 跳过决策；BOOT/局内/其它有分层超时（但 ROOM_STARTING 除外，见 P1-4）。
- **matcher**: `match_one` 直接 `frame.bgr.shape`，**假定 health 已拦**；若将来有旁路调用空帧会 `AttributeError`。
- **建议**: `match_one` 入口 `if frame is None or frame.bgr is None or frame.bgr.size==0: return None` 防御。

### 22. `find_scene` 自身
- **文件:行号**: `mediator.py:333-360`
- **行为**: 无 try/except；模板缺失时 `match_any` 返回 None；不抛错。异常只可能来自 OpenCV/坏图。
- **建议**: 在 `tick` 最外层对 `_tick_*` 包一层 `except Exception` → 记日志 + 连续失败计数 + Fail-Closed，避免线程直接崩掉留下半套输入钩子。

### 23. `see()` 无窗口
- **文件:行号**: `mediator.py:244-305`, `capture.capture` 无 target → invalid frame
- **行为**: 健康检查失败走 missing window；非局内 15s、局内 60s。合理。

---

## 超时策略一览（取值与交互）

| 机制 | 默认取值 | 作用相位 | 误杀风险 |
|------|----------|----------|----------|
| `query_timeout` | 60s | L0 deadline、多处 min(...,30/15) | 地图/建房/选关等待上限；偏大则收敛慢 |
| `game_timeout` | 15（**分钟**） | MAIN_LINE idle | 被 challenge Continue 续命时失效（P1-9） |
| `_room_action_deadline` | 常被 set_phase 写成 60s | ROOM/STAGE 开始验页 | 与调用方 15s 意图冲突（P0-3） |
| `_hero_observation_timeout` | max(20, min(q,60))→60s | HERO_SETUP 每步 | 不健康帧 15s 更先杀（P1-5） |
| challenge UNKNOWN | min(q,30)→30s | MAIN_LINE | **缺失按钮误杀（P0-2）** |
| 未知选择面板 | 10s | MAIN_LINE | 主动面板可先关；被动仍停机 |
| 战后 transition | min(q,30)→30s | post_game_pending | 合理 Fail-Closed |
| 退出 QUIT/NEXT | min(q,15)→15s | L1 tail | 加载慢可能紧 |
| 不健康帧 | 局内 60s / 其它 15s / BOOT 特殊 / **ROOM_STARTING ∞** | tick | P1-4 |
| L0 cycle | 5 次 | MAP↔ROOM | 合理 |
| `wait_ui_timed_out` | query_timeout | （未使用） | 无 |
| longzhu deadline | max(archive, boss, 180) | LONGZHU（未实现即杀） | 无实际路径 |

---

## 标志重置完整性矩阵

| 标志 | 初始 | MAIN_LINE 进入 | STAGE_SELECT 进入 | 回房 PREPARE/ROOM_WAITING | 缺口 |
|------|------|----------------|-------------------|---------------------------|------|
| `_stage_selected` | F | 不变 | **不重置** | **不重置** | **P0-1** |
| `_stage_target_*` | None | 不变 | **不重置** | **不重置** | **P0-1** |
| `_challenge_done` 等 | 空 | 清空 | — | — | OK |
| `_auto_task_done` | F | F | — | — | OK |
| `_post_game_pending` | F | F | — | — | OK（QUIT 前已清） |
| `_panel_opened_by_us` | 无 | **不重置** | — | — | **P1-6** |
| `_awaiting_room_return` | F | 不变 | 不变 | 仅成功/超时清 | P1-10 |
| `_main_line_since` | None | now | — | — | 被无效 Continue 刷新 |
| 神器/G/F/V 时间戳 | 懒 | **不重置** | — | — | **P1-6** |
| `_l0_cycle_count` | 0 | 0（STAGE/MAIN） | 0 | 回 MAP +1 | OK |
| `_hero_*` | IDLE | 不变 | 重置 | — | OK |
| `_room_dialog_filled` | F | — | — | 仅进 LOBBY/MAP 清 | 尚可 |

---

## 分支可达性与 Fail-Closed 一致性（摘要）

- **`_tick_l0`**: BOOT/MAP/CREATE/ROOM/STAGE 链完整，多数超时 Fail-Closed 或回退；英雄子状态机完备；`WAIT_UI`/`WAIT_EXIT` 无独立超时。  
- **`_tick_main_line`**: 战后优先 → pending 零输入 → 未实现入口直接停 → 选择 → 自动任务 → **挑战门闸过严** → 选关/进化/神器/主动面板 → idle。Fail-Closed 偏多且粒度不一（有的 skip、有的 stop）。  
- **`_tick_l1_tail`**: 三未实现相位立即停；QUIT/NEXT 有 attempts+时间双条件，较好。  
- **一致性问题**: 「未知」有时 stop（挑战、选择、战后），有时 skip（自动任务找不到 toggle），有时死等（ROOM_STARTING 坏帧）。

---

## 优先修复顺序（给主 agent）

1. **P0-1** 跨局选关标志重置（多局正确性）。  
2. **P0-2** 挑战 MISSING/UNKNOWN 拆分，禁止缺失即停机。  
3. **P0-3** `set_phase` 勿覆盖 ROOM/STAGE_STARTING 的 deadline/attempts。  
4. **P1-4/5** 不健康帧超时表（ROOM_STARTING、HERO_SETUP）。  
5. **P1-6/9** MAIN_LINE 瞬态字段重置 + idle 续命条件。  
6. 性能：post_game/challenge/context 降频与 cache 扩展。

---

## 审查结论

状态机整体方向正确：L0 显式页面链、英雄 Fail-Closed、战后零输入、scene 缓存 per-tick 清空都到位。当前最影响「稳定性/可连续挂机」的是 **跨局 L0 标志残留**、**挑战缺失误杀**、**set_phase 重写重试上下文** 与 **ROOM_STARTING 坏帧无超时**。建议按上表顺序改完后再跑两局以上实机回归。
