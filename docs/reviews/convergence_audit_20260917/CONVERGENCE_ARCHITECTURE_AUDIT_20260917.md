# ShuaBao 收敛架构审计（2026-09-17）

> 目的：解释并收敛「为什么每经历一次中长开发任务，就容易引入一批新的回归和边界 bug」。
> 性质：**只读审查**。没有修改任何生产代码、测试代码、夹具、baseline、配置、快捷方式或 KK/游戏窗口；没有发送任何游戏输入。
> 机制事实以 `docs/mechanics-contract-20260917` 分支的 `MECHANICS_CONTRACT_RESEARCH_20260917.md` 为基础，本报告只做 delta / gap closure，**不因攻略、截图或现有代码升级证据等级**。

---

## 0. 基准与核验

### 0.1 Refs（2026-09-17 15:09 +0800 实际 `git fetch` + `git ls-remote` 核验）

| 项 | 值 | 核验结果 |
|---|---|---|
| Production `fix/solo-live-regression-20260915` | `bbf2de0e749095ee8dcef656a57b1eef3371e4fa` | 本地 == 远端，G 根工作树 clean |
| Test/GT `test/pirate-necromancy-gt-20260917` | `f4e56bc4c3636d683d5a82520d73d6aa0549a1b0` | 本地 == 远端；工作树只有未跟踪的截图/captures |
| merge-base(prod, test) | `bbf2de0` | test 已包含 production（`f3f4afc` 合流） |
| test 相对 prod 改动的 `src/shuabao` 文件 | `choice_policy.py`、`settings.py`、`shell/main_window.py`、`shell/test_profiles.py` | **test 分支跑的不是 production 代码** |
| `main` | `7ebf4b2` | 未动 |
| Harness 冻结基线 `FROZEN_PRODUCTION_CODE_BASELINE` | `7a6c36b` | 落后 prod 25 个提交，`src/shuabao` 差 4 文件 +787/-287 |
| 本报告所在分支 | `docs/convergence-architecture-audit-20260917`，从 `bbf2de0` 切出，只加本文件 | 未设上游跟踪，未开 PR |

### 0.2 本轮实际运行过的东西（全部离线、零输入）

| 动作 | 结果 |
|---|---|
| `release_gate.py --only frozen_replay --only scene_templates --only contract --json`（G 根，bbf2de0） | FAIL：`giveup_panel_not_fail` 快照 PASS→实际 FAIL；`asset_files/allowlisted` 399→401；contract 56 PASS |
| `pytest tests -q -p no:faulthandler`（G 根，bbf2de0，游戏未运行，约 10GB 空闲内存） | **3 failed, 2377 passed, 1 skipped, 2 xfailed**，868s；3 个失败全在 `tests/test_live_harness_refresh.py` |
| 离线探针 `probe_round_reset`（附录 A） | 复现：正常选关开局路径不重置局级状态 |
| 离线探针 `probe_challenge_return`（附录 A） | 复现：core 与 runtime 对同一 `set_phase` 的重置语义不同 |
| `tools/check_pirate_necromancy_profile.py`（test 工作树） | offline_contract PASS，gt_readiness BLOCKED |
| AST / grep 度量（附录 B） | 见各节 |
| 桌面 `.lnk`、`%LOCALAPPDATA%\ShuaBao\current.json` 读取 | 见 §4.7 |

运行后 G 根 `git status` 仍为 clean。

### 0.3 证据标签

沿用机制研究报告的标签（`REAL_LIVE_GT` / `LIVE_BUNDLE` / `USER_CONFIRMED` / `USER_SCREENSHOT` / `LOCAL_FIXTURE` / `GUIDE_ONLY` / `CURRENT_CODE` / `INFERENCE` / `CONFLICTED` / `UNKNOWN`），本报告另加：

| 标签 | 含义 |
|---|---|
| `OFFLINE_REPRO` | 本轮用离线脚本在 bbf2de0 上实际复现 |
| `CODE_VERIFIED` | 本轮读代码确认的控制流/数据流，未运行 |
| `METRIC` | 本轮 AST/grep 统计 |

---

## 1. 一句话结论

**ShuaBao 不是「bug 多」，而是「同一件事有多个 authority，而且 authority 之间靠字符串、代码顺序和 getattr 默认值隐式耦合」。**
每次中长任务只修其中一个 authority，其余 authority 保持旧语义；测试又主要替身（stub）掉 authority 本身，只验证分发逻辑，于是「测试全绿」和「实机行为」之间永远存在一条没人拥有的缝。

四个最核心的证据：

1. **局级状态的重置由 `set_phase` 的 note 自由文本决定**（`mediator.py:9965-9979`），正常的「选关→开始游戏」开局 note 恰好命中「重入」白名单，约 80 个局级字段不重置（`OFFLINE_REPRO`）。
2. **LIVE 用 `RuntimeMediator`，release gate 的 frozen_replay 和 tests/contract 用 core `Mediator`**，两者有 24 个方法语义不同（`CODE_VERIFIED`）。
3. **测试替身掉的恰好是「正向画面证据」本身**：`_post_game_state` 被 patch 128 次、`_selection_anchor` 54 次、`_is_in_game_hud` 50 次（`METRIC`）。
4. **同一台机器上有 5 个「身份」**：安装版 `6a90670`、Live 快捷方式 `8e8a908`、production `bbf2de0`、test 看板 `f4e56bc`（带 4 个 src 改动）、Harness 冻结基线 `7a6c36b`（`CODE_VERIFIED`）。

---

## 2. P0 / P1 / P2

判定口径：
- **P0**：会导致不可逆业务破坏、错误输入，或让计划中的 GT 产出不可归因/误导性证据，必须在正式 GT 前处理（处理 = 修复 **或** 明确禁用/隔离）。
- **P1**：系统性结构风险，已在代码中确认，会持续制造回归；Release 前必须闭环。
- **P2**：局部风险或债务，可排期。

### P0

#### P0-1 局级状态重置依赖 note 字符串；正常选关开局路径（非声望模式）不重置约 80 个局级字段 — `OFFLINE_REPRO`

- 位置：`src/shuabao/mediator.py:9965-9979`（`is_reentry_or_attach` 白名单含 `"challenge start verified"`），`:14545`（正常开局 `set_phase(Phase.MAIN_LINE, "challenge start verified")`），`:9847`（声望路径 note 为 `"hero mode in-game HUD verified"`，不在白名单）。
- 分叉点：`:14488` `if self.settings.auto_reputation: return self._begin_hero_setup(frame)`。
  - `auto_reputation=True` → HERO_SETUP → 重置正常。**所有已知实机 bundle（09-15/09-16 的 `live_harness_settings_*.json`）都是 `auto_reputation=True`**，所以这条缺陷从未在实机暴露。
  - `auto_reputation=False` → STAGE_STARTING → note 命中白名单 → `entering_main_line=False` → 整个局级重置块（`:10017-10210`）不执行。
- 离线复现（附录 A.1）：第 1 局结束状态经 `QUIT→NEXT→STAGE_SELECT→STAGE_STARTING→MAIN_LINE("challenge start verified")` 后：
  `_auto_task_done=True`、`_main_line_closed_done=True`、`_close_main_line_triggered=True`、`_challenge_done` 保留、`_main_line_started_at` 仍是 1500s 前、`_skill_cards_owned` 保留、`_post_game_route="archive"`、`_secret_realm_active=True`、`_time_cave_boss_done=True`、`_merchant_next_at` 保留、`_round_deadline=None`。
- 业务后果（`CODE_VERIFIED`）：
  - `_main_line_closed_done=True` → `_ensure_auto_task_enabled` 在 `:2778` 直接 return → **第 2 局永远不开自动任务**。操作员当前设置 `auto_close_main_line=True`，此条可达。
  - `_secret_realm_active=True` → `_finish_direct_failure_exit`（`:10447`）把第 2 局真实失败记成 VICTORY → 连败熔断/降级统计失真。
  - 第 1 局本身：`_main_line_started_at` 只在重置块里赋值（`:10019`），走此路径时始终为 None → 神器 Q/W/E 在 `:4189` 被永久跳过；`_round_started_at` 只能靠 liveness 监督器在 `:12258` 补设，dry_run 下监督器直接 return，**离线回放与实机的计时语义不同**。
- **与 GT 的直接关系**：test 分支 `海盗+亡灵机制GT` 方案显式设 `auto_reputation: false`。这是第一次在实机走这条开局路径，GT 的「60s 高级组解锁」依赖 `_round_elapsed_s()`，神器释放完全失效，GT 结论会被这条缺陷污染而非反映海盗/亡灵机制。
- 最小处理：正式 GT 前二选一 —— (a) GT 方案改回 `auto_reputation=true`；或 (b) 修复重置语义（用显式的 round token / 枚举原因代替 note 子串），并补一个 `RuntimeMediator.tick()` 级两局离线测试。**不建议**在同一补丁里顺带改别的重置字段。

#### P0-2 生产默认 `auto_devour_dan=True`，门槛只有「羁绊栏 >3 张」，与 Owner 已确认的吞丹禁令冲突 — `USER_CONFIRMED` + `CODE_VERIFIED`

- Owner 规则（`OWNER_CONFIRMED_RULES.md`，`USER_CONFIRMED`）：普通丹随机吞；栏里有海盗启动卡、高级组关键卡、接近凑满的叠卡或 Owner 保护卡时**禁止自动用丹**；**身份未知不能证明安全**。
- 代码：`settings.py:187 auto_devour_dan: bool = True`；`mediator.py:5261 _can_consume_inventory_swallow_pill` 只判 `occupancy > 3`；`runtime_mediator.py:487-523` 在该条件下点击 `danGif`（阈值 0.55）。操作员当前设置 `auto_devour_dan=True`。
- 观测层现状（`LIVE_BUNDLE`，机制研究 §2.6）：卡名 OCR 命中 0/1796，羁绊栏无逐格身份 → 任何时刻都**无法证明栏里没有受保护卡** → 按 Owner 规则，自动用丹在当前观测能力下永远不满足前置条件。
- 验证器过弱：`runtime_mediator.py:505-522` 的 `WAIT_DEVOUR_DAN` 验证器把「`danGif` 找不到」也算成功（tooltip 遮挡、叠数变化都会命中），属于「点击成功≈业务成功」。
- 为什么是 P0：吞卡不可逆，吞掉 藏宝图/开进码头/近满叠卡会直接毁掉整局构筑；one-click GT 脚本已单独强制 False，但 Dashboard 正常运行、Live 快捷方式运行仍为 True。
- 最小处理：生产默认改为 False 或加硬门「身份未知 → 零输入」；验证器要求「丹数量减少 **且** 栏占用减少」。这是一个配置/门控改动，不需要等 GT。

#### P0-3 源码身份不可归因：GT 证据无法对应到 production candidate — `CODE_VERIFIED`

- Live 快捷方式 `刷刷宝 Live 实机测试.lnk` 的 `-ProductionSourceSha 8e8a908…`，落后 `bbf2de0` 24 个提交（身份规则要求 == HEAD）。
- one-click 路径 `--production-source-root = 测试工作树`、`--production-source-sha = 测试 HEAD`、`--allow-dev-source`：身份检查是**自指的**（证明「我跑的是我自己」），而测试 HEAD 在 `src/shuabao` 有 4 个文件与 production 不同。
- `tools/live_scenario_capture.py:3900-3907 _scenario_identity` 用**字符串前缀**过滤掉基础身份报告中的 `"imported shuabao is"` 与 `"production code diff is NOT_CLEAN"`：Harness 冻结基线（`7a6c36b`）的漂移信号在实机入口被静默吞掉，只在 pytest 里以 3 个失败出现（§5）。
- 清洁度只检查 `src/shuabao`：`config/choice_policy.json`、`mode_specs.json`、`dashboard_test_profiles.json` 等决定运行行为的配置**不在身份里**。
- 为什么是 P0：本轮目标之一是「把 GT 结果变成可进 production 的事实」。现在任何 GT 结果都无法回答「这是 bbf2de0 的行为吗」。
- 最小处理：GT 前定一个 identity manifest（production SHA、test SHA、`git diff --stat prod..test -- src config`、venv 路径与 `pip freeze` hash、OCR 模型 hash、settings sha256、operator settings 来源 hash），**写进每个 bundle**；test 分支对 `src/shuabao` 的改动要么回到 production，要么在 manifest 中显式列为 `TEST_ONLY_DELTA`。

### P1

| # | 问题 | 证据 | 位置 |
|---|---|---|---|
| P1-1 | **LIVE 与门禁跑两套 Mediator**。`run_frozen_replay.py:50`、`tests/contract/*` 用 core `Mediator`；LIVE（`live_execute.py:343`、harness `_new_live_mediator`）用 `RuntimeMediator`，有 24 个覆盖方法。差异举例：`_canonical_bond_name`（core `:3671` 子串归 5 类 / runtime 查 `fetter_labels`）、`_hide_fallback_hit`（core `:6580` 固定坐标盲点 `(0.30,0.613)`，紧邻「放弃」`(0.36,0.61)` / runtime 返回 None）、`set_phase` 重置语义（见 P1-2）。测试里 core 构造 ≥60 处、runtime 60 处。 | `CODE_VERIFIED` + `METRIC` | `runtime_mediator.py` 全文 |
| P1-2 | **core 与 runtime 对同一次 `set_phase(MAIN_LINE)` 的重置不同**。runtime `set_phase`（`runtime_mediator.py:683-698`）只要 `previous != MAIN_LINE` 就清空 `_bond_cards_owned`、`_l1_cycle_index`，**不看** core 的重入白名单。离线复现：`EARLY_CHALLENGE→MAIN_LINE("challenge return")` 后 core 保留 `['经济','经济','藏宝图(三)']`，runtime 变成 `[]`，步骤重置为 bond。可能的实际入口：liveness 监督器 `_hitch_reconcile_to`（`:12370-12387`，note 含 `reconcile`；监督器对 normal_farm 的 MAIN_LINE/RECOVER_FAILURE/QUIT/NEXT 也生效）、`startup reconcile`/`startup found existing game` → 局中拥有记账丢失 → 80% 基础卡锁与近满合并判断重新计算。单人路径是否真的会从恢复阶段 reconcile 回 MAIN_LINE 本轮未回放确认（`INFERENCE`）。 | 语义分叉 `OFFLINE_REPRO`；触发路径 `INFERENCE` | 附录 A.2 |
| P1-3 | **输入 authority 分散**。`act_*` 调用点 94 个，分布在 46 个方法；`_tick_main_line` 1419 行、161 个 return；`InteractionSurface` 仲裁在 `:17065`，比函数入口晚约 890 行，其前已有失败礼包点击（`:16404`）、蹭车压力转移、聊天条关闭、传家宝/战后链等输入。**优先级 = 代码顺序**：`4f57f1e` 的修复就是把「正向 HUD 门」代码块整体下移。`_has_active_transaction`（`:2333`）不含面板会话、TQTZ、秘境请求、退出链、建房表单、恢复状态。 | `METRIC` + `CODE_VERIFIED` | `mediator.py:16178-17597` |
| P1-4 | **安全门按自由文本 reason 匹配，异常时 fail-open**。`_action_forbidden`（`:2185-2198`）捕获 `get_spec` 的任何异常后 `return False`；`action_is_forbidden` 按 reason 字符串前缀匹配（`mode_catalog.py:129`，其 docstring 写「unknown keys stay closed」，与实现矛盾）。`lobby_hitch`/`follow_team` 禁止 `RoomStart`/`CreateRoom-*` 全靠这个。reason 改名或 `mode_specs.json` 加载失败 = 禁令消失。 | `CODE_VERIFIED` | 同左 |
| P1-5 | **单 tick 一输入只在 tick 内生效**。`_action_gate_ok`（`:1979-1988`）在 `_evidence is None or _tick_gen is None` 时直接放行；测试里 680 处直接调用 `_tick_*`/`_maybe_*` 私有处理器，只有 130 处走 `tick()` → 大多数测试**不受**一输入约束。 | `CODE_VERIFIED` + `METRIC` | — |
| P1-6 | **测试替身掉 authority 本身**。`patch.object(<Mediator>, "_…")` 共 1151 处；前几名：`_post_game_state` 128、`_selection_anchor` 54、`_is_in_game_hud` 50、`_lobby_room_list_evidence` 36、`_find_stage_page` 29、`_ocr_panel_slots` 27；直接写私有状态 `med._x = …` 1344 处。测试证明的是「若分类完美，分发正确」，而不是正向画面合同。 | `METRIC` | 附录 B |
| P1-7 | **Win32 ctypes 原型是进程级全局可变状态**。`capture._typed_user32()`（`capture.py:128`）改写 `ctypes.windll.user32` 共享函数对象的 argtypes/restype；`keyboard_mouse.get_foreground_window/_window_pid/_window_class_and_title`（`:91-156`）直接用未声明原型的 `ctypes.windll.user32`，行为取决于 `_typed_user32` 是否已在本进程执行过；`_window_root` 每次调用都改写 `GetAncestor` 原型；`tools/manual_gt_capture.py` 另声明一套 `c_void_p` 原型（`GetForegroundWindow` 返回 None 而非 0）。`bbf2de0` 的提交说明本身承认「ctypes shares the function prototype across windll.user32 callers」，修法是把 `EnumWindows` 放宽为 `c_void_p`。 | `CODE_VERIFIED` | 同左 |
| P1-8 | **窗口枚举失败被当成「没有窗口」**。`find_window_targets` / `list_active_window_titles` 外层 `except Exception: return []`；回调内异常被 ctypes 以 `Exception ignored on calling ctypes callback` 吞掉。09-17 实例：`entry_failure/entry_retry.stderr.log` 连续 OverflowError，`diagnose_lobby` exit 0，最终报「无游戏窗口」。 | `LIVE_BUNDLE`（test 分支证据）+ `CODE_VERIFIED` | `capture.py:582-583` |
| P1-9 | **`tools/test_dashboard.py` 是第三套 preflight，且 READY 语义错误**（详见 §4.6）。 | `CODE_VERIFIED` | test 分支 |
| P1-10 | **测试看板会写生产操作员设置**。`on_open_native_dashboard` 用 `MainWindow(app_data=APP_DATA)`（默认 `%LOCALAPPDATA%\ShuaBao`），应用测试方案后 `_schedule_auto_save()` → 测试方案（`bonds=[经济]`、`bond_must_take=[藏宝图(三)]`、`auto_secret_realm`）持久化进操作员 `user_settings.json`，之后 Dashboard/Live 正常运行继承。one-click 反向也以操作员 `user_settings.json` 为底（`check_pirate_necromancy_profile` 显示 skills `jq,pg` 继承自操作员）→ GT 输入不可复现。 | `CODE_VERIFIED` | test 分支 `tools/test_dashboard.py:323-327`、`tools/one_click_test.ps1` |
| P1-11 | **调度器没有等待时长/容量概念，阈值在两个方法里重复实现**。`_l1_step_visit_exhausted`（`:4302`）与 `_visit_capped`（`:4407`）各自实现木材 1000/300 → 15/2/1 张分档；`_solo_plan_panel` 另有 8/4 技能积压、`treasure is None` 视为有待拿、30s/60s/10s 冷却；`_should_hold_core_development`（`:4468`）仍在；F 价格按「我们自己拿了几张」推算（`:4391`），与 Owner「重开免费/刷新收费」无关。任何一次修复只改其中一处就会分叉（`7d034de`→`25092cb`→`187931e` 的往返即此）。 | `CODE_VERIFIED` | 同左 |
| P1-12 | **秘境「进入成功」后置条件不针对秘境**。`_observe_secret_realm_entry`（`:16095`）只要求两帧 `post_game is None and _is_in_game_hud`，帧区分用 `id(frame)`（Python 对象地址可复用）；战后广场本身也有局内 HUD。已知有可靠的场景标签（顶栏模式：存档=广场 / 团本 / 第N/5波，`LIVE_BUNDLE`，09-12）但未用于该判断。实机秘境确认 0 次，无秘境真实帧。 | `CODE_VERIFIED` + `LIVE_BUNDLE` | 同左 |

### P2

| # | 问题 | 证据 |
|---|---|---|
| P2-1 | `release_gate` 两个非 pytest 失败都是**快照陈旧**，其中 `giveup_panel_not_fail` 的旧期望点在「放弃」按钮上沿（§5），说明快照机制曾把危险点位焊成 PASS。 | `LOCAL_FIXTURE` + `OFFLINE_REPRO` |
| P2-2 | `release_gate._run` 未捕获 `subprocess.TimeoutExpired`；本机全量 gate 多次 exit 255（test 分支记录 1191.81s）→ 门禁在开发机上实际不可用，于是被绕过。 | `CODE_VERIFIED` + test 分支记录 |
| P2-3 | `RuntimeMediator.__init__` 临时改写传入的 `settings.ocr_mode/ocr_enabled`（`runtime_mediator.py:60-71`），settings 对象被多方共享。 | `CODE_VERIFIED` |
| P2-4 | LIVE 看门狗把「输入发出」当进展（`act_click` 成功即 `_mark_runtime_progress`），无效点击循环不会被判停滞；HUD 确认闩用 `id(frame)` 判不同帧。 | `CODE_VERIFIED` |
| P2-5 | `_exit_rearm_attempts` 在任何非 QUIT/NEXT 边界清零（`bdb30ef`）；若出现 `QUIT→RECOVER_FAILURE/MAIN_LINE→QUIT` 往返，预算可反复恢复。 | `INFERENCE`，需回放验证 |
| P2-6 | 声望「今日声望耗尽时自动降级常规模式」在 UI 上承诺（`main_window.py:1854`），实现是 `pass`（`mediator.py:9687-9691`）。 | `CODE_VERIFIED` |
| P2-7 | Mediator：449 个方法、461 个实例属性、64 个只在 `__init__` 之外懒创建、`getattr(self, "_…", default)` 362 处 → 状态所有权不可枚举，重置清单无法机械核对。 | `METRIC` |
| P2-8 | `_new_live_mediator` 在 RuntimeMediator 加载失败时回退 core Mediator，靠「OCR 健康检查置为不健康」间接阻断输入（`live_scenario_capture.py:4349-4363, 4475`），安全依赖间接耦合。 | `CODE_VERIFIED` |
| P2-9 | G 根 `tools/` 172 项中 107 项未版本化（经 `.git/info/exclude` 忽略），含 `do_click.py`、`temp_click.py`、`sendinput_click.py`、`uia_click.py` 等可发真实输入的脚本。 | `METRIC` |
| P2-10 | 工作树注册异常：`pirate-necromancy-gt-20260917` 与 `night-ablation`/`stability-s0` 一样以 `…\.git` 路径注册；test 工作树没有自己的 `.venv`，one-click/看板回落到 G 根 `.venv` 与 `.venv-ocr`；`Start-Process -Verb RunAs` 提权后不继承父进程环境变量。 | `CODE_VERIFIED` |
| P2-11 | `RuntimeMediator._bond_presets_complete()` = 「没有配置任何羁绊预设」→ `bonds=[]` 时整局跳过 F（`runtime_mediator.py:615, 704-713`），语义像「已完成」实为「未配置」。 | `CODE_VERIFIED` |
| P2-12 | `InteractionSurface` 枚举 docstring 的优先级顺序（EQUIPMENT_AFFIX=2、HERO=3）与声明顺序（HERO 在前）不一致。 | `CODE_VERIFIED` |
| P2-13 | pytest 会拉起真实 OCR worker 子进程（本轮观察到 3 个），并有 `_read_stderr` 线程在已关闭流上抛 `ValueError` 的警告；进程内存峰值约 2.6GB。 | 本轮观察 |

---

## 3. 最容易制造新 bug 的 10 个结构原因

按「每次中长任务后回归概率」排序。

1. **控制面藏在自由文本里。** `set_phase` 的 note 子串决定是否重置局级状态；`act_*` 的 reason 字符串决定是否被模式禁令拦截；harness 身份用失败原因的字符串前缀过滤。改一条日志文案 = 改行为，且没有任何测试会报警。（P0-1、P1-4、P0-3）
2. **优先级 = 代码顺序。** `_tick_main_line` 1419 行、161 个 early return，仲裁器在中段。每个修复都是「插一个 if 块到合适位置」或「把块往下挪」，下一次任务再插一个块就可能越过门禁（TQTZ P0、正向 HUD 门的两次移动都是这个模式）。（P1-3）
3. **同一语义有两个实现（core vs runtime），门禁验证的是 LIVE 不用的那个。** 修 runtime 不会让 frozen_replay/contract 变红，修 core 也不会改变实机。（P1-1、P1-2）
4. **状态所有权不可枚举。** 461 个实例属性、64 个懒创建、362 个 `getattr` 默认值；「局级/面板级/会话级」没有类型边界，重置清单靠人工维护在 `set_phase` 的 360 行里。新增一个字段时，没有任何机制提醒「它属于哪个生命周期」。（P0-1、P2-7）
5. **测试替身掉的是 authority 而不是 I/O 边界。** 最常被 patch 的正是正向画面分类器；1344 处直接写私有状态造就「任意起点」，绕过了真实转移路径——P0-1 这种「只有真实转移才会暴露」的缺陷因此天然不可见。（P1-5、P1-6）
6. **阈值即策略，策略写死在测试里。** 调度器阈值散落两处，测试断言当前阈值（`ff0d7ca` 把测试改回断言「严格 F↔G」），于是「修回去」和「退回去」都能让测试变绿；测试不表达「V 等待有上限」这类合同。（P1-11）
7. **点击成功被当作业务成功。** 吞丹验证器接受「图标不见了」；LIVE 看门狗以「输入发出」为进展；秘境以通用 HUD 两帧为进入。每个 postcondition 都比业务合同弱一点，弱的部分就是下一次实机事故的位置。（P0-2、P1-12、P2-4）
8. **失败被静默成「不存在」。** 79 处 `except …: pass/return None|False|[]`；枚举异常 = 无窗口；模式表加载异常 = 无禁令；ctypes 回调异常只打 `Exception ignored`。上层据此做出「零输入/BLOCKED」或「放行」判断，却不知道自己在对一个异常下结论。（P1-4、P1-8）
9. **身份/入口/环境有多份真相。** 5 个 SHA、4 套 preflight（harness 目标表、one-click PS1、Live launcher PS1、测试看板）、2 个 venv 回落、操作员设置双向污染。一次任务只更新其中一两处，其余自动过期。（P0-3、P1-9、P1-10）
10. **production 与 test 分支互相修改同一文件，门禁快照靠手工刷新。** HWND FFI 先在 test 提交、cherry-pick 到 production 仍标 `TEST_ONLY`、再在 production 改、再合回 test 并解冲突；gate 快照本机跑不完就手改数字（09-14 记录）。每一次同步都在制造新的「哪个是权威」问题。（P0-3、P2-1、P2-2）

---

## 4. 分主题审查

### 4.1 RuntimeMediator / Mediator / Scheduler / 事务 FSM 的职责边界

| 组件 | 名义职责 | 实际职责 | 隐藏耦合 |
|---|---|---|---|
| core `Mediator`（17897 行） | 通用状态机 | 截屏、分类、策略、调度、事务、恢复、身份、trace 全部 | 被 frozen_replay、contract、多数测试当作「生产」 |
| `RuntimeMediator`（794 行） | 「生产专用活性与安全不变量」 | 另有羁绊拥有记账、hard whitelist 否决、OCR 客户端替换、进化兜底限制、选关高亮复核、阶段重置 | 依赖 core 未初始化的 `_l1_cycle_index`（core 只用 `getattr` 读）；改写共享 settings |
| Scheduler（`_solo_plan_panel` + `_advance_l1_cycle` + `_l1_step_visit_exhausted` + `_visit_capped` + `_bond_step_blocked`） | 决定下一个面板 | 同时承担木材读数刷新、访问计数、优先级挂起、退避 | 状态字段由 `_reset_solo_plan_state` 仅在 `entering_main_line` 时清（受 P0-1 影响） |
| 事务 FSM（PendingAction / MerchantFSM / EquipmentFSM / PublicBagFSM / 面板 FSM / 退出链 / 秘境请求 / TQTZ） | 每个事务一个持有者 | `_has_active_transaction` 只汇总其中 6 类 | 抢占由代码顺序决定，不由持有者声明 |

结论：**没有一个对象拥有「这一 tick 谁可以输入」的决定权**；InteractionSurface 是其中一个中段检查，不是入口。

### 4.2 跨阶段 stale state

| 边界 | 问题 | 等级 |
|---|---|---|
| 第 N 局 → 第 N+1 局（非声望） | 约 80 个字段不重置（P0-1） | `OFFLINE_REPRO` |
| 局中 MAIN_LINE 重入（reconcile / 恢复） | runtime 清空拥有记账，core 保留（P1-2） | `OFFLINE_REPRO` |
| STAGE_SELECT 进入 | 清面板、pending、TQTZ、round deadline（`:9915-9964`），不清主线/挑战/战后字段——与 MAIN_LINE 重置块职责重叠又不完整 | `CODE_VERIFIED` |
| 秘境 → 失败 → 下一局 | `_secret_realm_active` 只在 `entering_main_line` 清 | `CODE_VERIFIED` |
| 进程级 | Win32 原型、`mode_catalog._CACHE`、OCR worker 子进程 | `CODE_VERIFIED` |
| 操作员设置 | 测试方案持久化进 `user_settings.json`（P1-10） | `CODE_VERIFIED` |

### 4.3 Scheduler 饥饿 / 等待上限 / 抢占 / reset

- `bbf2de0` 相比 `5b0f243`：`187931e` 恢复「V 在 treasure 步有一次显式服务机会」与 F 抽卡指纹退避（`_F_DRAW_REOPEN_LIMIT=2`、`_F_DRAW_BACKOFF_S=30`）。这是方向正确的收敛，**应保持**。
- 仍然没有：每类需求的等待时长、上限、容量应急；V 的服务仍依赖「轮换恰好停在 treasure 步」，不是「等待超过上限必须服务」。
- 读数未知时的语义不一致：`treasure is None` → 视为有待拿；`wood is None` → F 优先（`bond_priority_affordable = wood is None or …`）；技能 `None` → 不抢占。
- 重置风险：调度状态随 P0-1 在非声望第 2 局泄漏（`_bond_picks_round` 价格推算、挂起标记）。
- **需 GT 才能定的**：V/G 等待上限值、木材预留、F 刷新预算（机制研究 §4.5，`NEEDS_OWNER_CALIBRATION`）。**可以先做的**：把等待时长作为 trace 字段（纯观测，零行为变化）。

### 4.4 input ownership / positive surface / business postcondition 是否单一 authority

| 维度 | 现状 | 单一？ |
|---|---|---|
| 输入发出 | 46 个方法 94 个调用点，统一经过 `_action_forbidden` + `_action_gate_ok` + executor 前台检查 | 闸门统一，**决策不统一** |
| 正向画面 | `_is_in_game_hud`、`_post_game_state`、`_selection_anchor`、`_classify_choice_panel`、`_top_bar_mode`、`_find_stage_page`、`InteractionSurface`、harness `_start_surface_preflight`、看板窗口标题 | 否 |
| 业务后置条件 | PendingAction verifier（各写各的 lambda）、面板 mutation、秘境两帧、退出链 surface 重分类 | 否，且强弱不一（P0-2、P1-12） |

### 4.5 Test Dashboard / one_click_test / live_scenario_capture / desktop launcher 的重复

| 能力 | live_scenario_capture | one_click_test.ps1 | live_scenario_launcher.ps1 | test_dashboard.py |
|---|---|---|---|---|
| 源码身份 | `_scenario_identity`（带前缀过滤） | HEAD + `src/shuabao` clean | lnk 参数 SHA | `git rev-parse` + merge-base 显示 |
| 提权 | `is_current_process_elevated` | `-Verb RunAs` 自提权 | 自提权 | 无 |
| 窗口发现 | Mediator 分类器 | 无 | — | `find_window_targets` 标题子串 |
| OCR 就绪 | worker start/ping/warmup | 路径存在 | — | 硬编码 G 根路径存在 |
| 设置来源 | `--settings` | 操作员 `user_settings.json` + 方案 | 操作员 AppData | 原生看板写操作员 AppData |

`live_scenario_capture.py` 本身 6164 行、165 个函数，含逐目标 preflight 决策表——它已经是第二个「编排器」。

### 4.6 `tools/test_dashboard.py` 应仅作为 UI，不是安全 Gate

结论：**应降级为纯 UI（展示 + 调起），不得承担任何「READY」判定**。理由（全部 `CODE_VERIFIED`）：

1. KK 检测错误：`find_window_targets("KK", allow_minimized=True)` 无 role，标题子串 `kk` 也匹配游戏窗口「英雄三国KK」；排序时游戏窗口 +1000，所以有游戏时 `kk_targets[0]` 就是游戏窗口，「KK 最小化」读的是游戏窗口坐标。
2. 身份未参与 READY：`package_valid` 只显示，不进 `reasons`；production base 用 `merge-base origin/fix/…`（未 fetch 时陈旧，且永远是祖先，看不出 production 已前进）；分支名硬编码在 UI 文案。
3. OCR 就绪只检查 `ROOT.parent.parent / "GameScript-Local"` 下路径存在，与 test 工作树无关。
4. 未检查提权、16:9 客户区、前台可激活、operator 设置来源、GT 方案实际 sha。
5. 模块导入时与每次预检时 `OpenDesktopW("Default")` + `SetThreadDesktop`：未声明原型、未 `CloseDesktop`（句柄泄漏）、结果不检查、`except: pass`；在已创建 Qt 窗口的 GUI 线程上 `SetThreadDesktop` 必然失败但被吞。
6. 以 `pythonw.exe` 启动：未捕获异常无控制台，失败不可见。
7. 「READY」后调起 `one_click_test.cmd`，真正的门禁在 harness 里——看板的 READY 与 harness 的 READY 语义不同，却用同一个词。
8. 「打开完整配置看板」写操作员真实设置（P1-10）。
9. 桌面「刷刷宝 看板预览.lnk」（09-13 已归档的名字）被重新创建并指向测试看板——名字暗示生产看板。

### 4.7 源码身份漂移

| 入口 | 指向 | 与 production `bbf2de0` 关系 |
|---|---|---|
| `刷刷宝.lnk`（安装版） | `app-0.3-internal-pilot-6a90670` | 旧 |
| `刷刷宝 Live 实机测试.lnk` | G 根 + SHA `8e8a908` | 落后 24 提交 → 按规则 READY=NO |
| `刷刷宝 测试看板.lnk` / `看板预览.lnk` | test 工作树 `tools/test_dashboard.py`，解释器 G 根 `.venv\pythonw.exe` | test HEAD `f4e56bc`，含 4 个 src 差异 |
| Harness 冻结基线 | `7a6c36b` | 落后 25 提交；pytest 3 个失败即此 |
| venv | test 工作树无 `.venv`，回落 G 根；无 editable install，导入靠 `sys.path` 插入 | G 根 requirements 变动会静默影响 test |

未来漂移风险：任何 docs 提交都会让「lnk SHA == HEAD」失效（09-12 已知规则）；本报告分支不在 G 根上，不触发。

### 4.8 Win32 ctypes 全局副作用

见 P1-7、P1-8、§4.6 第 5 点。补充：
- `AttachThreadInput` 在 `activate_window`（`capture.py:590-630`）中成对 attach/detach，写法正确；但异常路径下 detach 是否一定执行需要单独审（本轮未展开）。
- `SetProcessDpiAwarenessContext(-4)` 只在 `manual_gt_capture.py` 设置，生产进程未设置 → **手工 GT 帧与生产帧的坐标系可能不同**（高 DPI 屏上尤其），手工 GT 帧上标注的坐标不能直接当生产坐标。`INFERENCE`，需在 GT 时记录双方 DPI 与客户区尺寸。

### 4.9 broad except / silent fallback / retry / recovery

- 统计：`src/shuabao` 宽泛 except 最多的文件为 `ui/uia/backend.py` 20、`mediator.py` 19、`main_window.py` 17、`keyboard_mouse.py` 16、`capture.py` 13；紧跟 `pass/return None|False|[]` 的 79 处。
- 危险方向不一致：`is_window_minimized` 异常 → False（当作未最小化，fail-open）；`is_window_valid` 异常 → False（fail-closed）；`_action_forbidden` 异常 → 不禁止（fail-open）；`_runtime_watchdog_hud_confirmed` 异常 → 不授权（fail-closed，正确）。
- 恢复链：`bdb30ef` 把「无限重新武装」改为有界 `_EXIT_REARM_LIMIT=2`，**应保持**；预算清零边界见 P2-5。
- 建议规则：安全相关判定（窗口存在、模式禁令、画面分类）异常时返回显式 `UNKNOWN` 三态并写 incident，而不是布尔默认值。

### 4.10 release_gate 失败项：真实风险还是陈旧 baseline

见 §5。

### 4.11 测试覆盖的是代码路径还是系统合同

见 §6。

### 4.12 测试代码 / GT tooling / 生产代码的重复

| 重复 | 保留哪个 |
|---|---|
| core vs runtime 的羁绊身份、隐藏兜底、背包使用、重置 | runtime 语义为准，core 版本移入 runtime 或删除 |
| 调度分档在 `_l1_step_visit_exhausted` 与 `_visit_capped` | 合并为一个纯函数 |
| Win32 原型：`capture.py`、`keyboard_mouse.py`、`manual_gt_capture.py`、`test_dashboard.py` | 单一 `win32_api` 模块，私有 `WinDLL` 实例（不用共享 `ctypes.windll`） |
| preflight × 4（§4.5） | harness 一个；PS1/看板只调起并展示 |
| 身份检查 × 3 | 单一 identity manifest 生成器 |
| test 分支对 `settings.py`/`choice_policy.py`/`test_profiles.py`/`main_window.py` 的改动 | 要么走 production 提交，要么留在 test 并在 manifest 中列为 delta；不要长期双轨 |
| `_bag_page_swallow_pill`（core，取第一个有东西的格，无身份） | 未接线，建议隔离/删除，防止未来接线即成盲点 |

---

## 5. release_gate 当前失败项判定（bbf2de0）

| 阶段 | 结果 | 判定 | 依据 |
|---|---|---|---|
| pytest | 3 failed / 2377 passed / 1 skipped / 2 xfailed | **陈旧 baseline，但信号真实** | 3 个失败均断言 `production_code_diff == "CLEAN"`，对比对象是冻结基线 `7a6c36b`；production 已前进 25 提交。这不是产品缺陷，但它正是 P0-3 中被 `_scenario_identity` 前缀过滤掉的那个漂移信号。**不要**只为让它变绿而重定基线；先定 identity manifest，再决定基线。 |
| frozen_replay `giveup_panel_not_fail` | 快照 PASS → 实际 FAIL | **陈旧期望，且旧期望是危险点位** | 期望 `skill_refresh_btn @ (1020,654)`，实际 `refresh @ (1171,677)`。本轮在夹具 `tests/performance/fixtures/giveup_panel.jpg` 上标出两点：(1020,654) 落在「技能免费刷新次数+1」文字右下、「放弃」按钮上沿附近；(1171,677) 落在「刷新(3)」按钮中央。现行为正确（`LOCAL_FIXTURE`）。旧快照曾把近「放弃」的点位记为 PASS。 |
| frozen_replay `disconnect_modal_missing` | BLOCKED（与快照一致） | 真实素材缺口 | 无真实断线弹窗素材，不得合成 |
| scene_templates | asset 399 → 401 | **陈旧快照** | 新增 `env/great_rift_title.png`、`env/tqtz_confirm_title.png`（`447c2f4`），manifest 已登记，hash 全对 |
| contract | 56 passed | PASS | 但验证的是 core Mediator（P1-1） |

结论：当前 gate 红色**没有一项直接代表新的产品缺陷**；真正的风险在于 gate 绿色时也不覆盖 P0-1、P0-2、P1-1、P1-2、P1-12。

---

## 6. 「测试全绿但实机会炸」最危险区域

按危险度排序：

1. **非声望模式的开局与第 2 局**（P0-1）：所有实机 bundle 都走声望路径；测试直接写私有状态造起点。
2. **正向画面分类器本身**（P1-6）：`_post_game_state`/`_is_in_game_hud`/`_selection_anchor` 在数百个测试中被替身；真实误分类（如 09-12 胜利横幅垫在存档面板上、09-11 黑窗 HWND）只能靠 bundle 回放发现。
3. **秘境进入/退出**（P1-12）：离线 12 个 `secret_realm` 测试通过，实机确认 0 次、无秘境真实帧，HUD 判据不特指秘境。
4. **窗口发现与 Win32 FFI**（P1-7、P1-8）：测试用 mock user32；实机 OverflowError 被吞成「无窗口」。
5. **LIVE 专属语义**（P1-1、P1-2）：frozen_replay/contract 用 core；runtime 的拥有记账重置、hard whitelist 否决、隐藏兜底禁用都不在门禁里。
6. **调度饥饿**（P1-11）：测试断言当前阈值，不断言等待上限；四个实机包三种失败方式（机制研究 §4.1）没有一个成为回归测试的合同。
7. **吞丹/消耗品**（P0-2）：验证器接受「图标消失」。
8. **身份与入口**（P0-3、§4.6）：`test_live_harness_refresh` 失败被视为噪音；看板 READY 无测试。

---

## 7. 保持 / 收敛 / 删除

### 应保持（不要再动）

- 原两个输入 P0 的关闭：TQTZ 排在交互面仲裁之后、2–6 号格不盲点、单人不周期性 F4。
- `187931e` 的 F 抽卡指纹 + 有界退避；V 在 treasure 步的显式服务机会。
- `bdb30ef` 的退出链 surface 重分类 + 有界 rearm。
- `922ed1a` 的分 tick 建房表单事务。
- `4f57f1e` 的「无正向 HUD 证据 → 零输入」门（位置可再议，语义保持）。
- `runtime_mediator` 中：禁用固定坐标隐藏兜底、选关高亮复核、进化兜底不在已分类面板上触发、看门狗零输入化。
- `bbf2de0` 的 pointer-sized HWND 原型（作为过渡，见下）。
- PublicBagFSM / MerchantFSM / EquipmentFSM / PendingAction / BagLayout 双锚点（机制研究 §1.3 READY_TO_WIRE）。
- `live_scenario_capture` 作为**唯一**实机采集与 preflight 入口。

### 应收敛

| 从 | 到 |
|---|---|
| note 子串决定重置 | 显式 `RoundBoundary` 原因枚举；局级字段集中到一个 `RoundState` 对象，整体替换而非逐字段清 |
| core/runtime 双语义 | frozen_replay 与 contract 改用 RuntimeMediator（或 core 吸收 runtime 语义后删除 runtime 覆盖） |
| reason 字符串禁令 + fail-open | 动作类型枚举 + 加载失败 fail-closed |
| 两处调度分档 | 一个纯函数 `visit_cap(kind, wood, elapsed)`，外加等待时长观测 |
| 4 套 preflight / 3 套身份 | harness 一套 + identity manifest；PS1/看板只调起与展示 |
| Win32 原型散落 | 单一模块，私有 `ctypes.WinDLL("user32", use_last_error=True)`；枚举返回 `(targets, error)` |
| PendingAction verifier lambda | 每类事务的后置条件函数，要求业务量变化（数量/占用/场景标签） |

### 应删除或隔离

- core `_hide_fallback_hit` 固定坐标盲点（LIVE 已禁用，只剩测试和回放在用）。
- core `_bag_page_swallow_pill`「第一个有东西的格」逻辑（未接线的盲点）。
- core `_canonical_bond_name` 子串归类（与 runtime 冲突）。
- `_should_hold_core_development` 硬锁（若 Owner 确认有界优先级方向）。
- `test_dashboard.py` 的 READY 判定与 `SetThreadDesktop` 代码；看板保留为只读展示。
- 桌面「刷刷宝 看板预览.lnk」恢复归档状态或改名为明确的「测试看板」。
- G 根 `tools/` 下未版本化且可发输入的临时脚本移出仓库目录。

---

## 8. 机制 GT 最小合同（delta / gap closure）

通用规则（所有条目适用）：
- 模式标签只用 `AUTO` / `USER_ASSISTED` / `MANUAL_GT`；人工动作一律记 `USER_ACTION`，永不记 AUTO PASS。
- 每个 before/after 必须是**两张 sha256 不同的帧**，并记录 HWND、客户区尺寸、DPI、identity manifest。
- 「点击成功」「模板存在」「OCR READY」「-WhatIf 成功」都不是 postcondition。
- 未自然出现 → `NOT_OBSERVED`，不得诱导或合成。
- GT 前必须先处理 P0-1（方案改回 `auto_reputation=true` 或修复）与 P0-3（manifest）。

### 8.1 海盗启动 / 开进码头 / 卡池

| 项 | 内容 |
|---|---|
| 当前已知事实 | 卡头 `藏宝图(x/3)`，卡名 `藏宝图(一/二/三)`，N 品（`LIVE_BUNDLE`）；卡面「集齐后将一张N开进码头置入卡牌栏，开启海盗卡组」（`LIVE_BUNDLE`）；单人面板出现 71 次、拿 0 次（`LIVE_BUNDLE`）；生产高级包不含启动卡（`CURRENT_CODE`）；OCR 只读卡头（`LIVE_BUNDLE`）；合成后释放组件格位（`USER_CONFIRMED`）；F 重开免费、刷新收费（`USER_CONFIRMED`）；test 方案把 `藏宝图(三)` 作为 base + must_take（test 分支 `CURRENT_CODE`，offline_contract PASS） |
| 当前未知 | 是否必须三张不同卡名；3/3 瞬间栏位变化；开进码头是否占栏、占哪格；卡池变化的可观测信号；开组后的海盗卡头；hard whitelist 是否会否决开组后的新卡头 |
| 必须看到的 before state | 局内 HUD 正证据；F 面板卡头 `藏宝图(k/3)` 原始 OCR 与裁图；羁绊栏逐格占用（人工标注身份）；木材读数 |
| 允许动作 | 生产策略在 F 面板上选择藏宝图卡（每 tick 一输入）；隐藏/关闭面板；**禁止**刷新预算外刷新、禁止用丹、禁止点栏位 |
| 必须看到的 business postcondition | k<3：下一次 F 卡头变为 `藏宝图(k+1/3)` **或** 栏占用 +1 且新增图标；k→3：组件格位释放（占用净变化记录）**且**栏中出现「开进码头」（人工标注）**且**此后 F 面板首次出现此前从未出现的海盗系卡头（记录原始 OCR） |
| UNKNOWN 时行为 | 卡头读不出或栏占用读不出 → 不计进度、不改策略、零额外输入；打书签 `m` |
| 能否进入 production | **否**。GT 后仅允许把启动卡加入包定义（配置）；开进码头保护、卡池判断需要卡名/逐格身份观测，另立任务 |

### 8.2 悬赏令（bounty）

| 项 | 内容 |
|---|---|
| 当前已知事实 | 5 色各叠一格带数量（`USER_SCREENSHOT`）；红≤UR/橙≤SSR/紫≤SR/蓝≤R/绿=N，用最低够用档（`USER_CONFIRMED`）；「只能吞海盗卡」（`GUIDE_ONLY`，`CONFLICTED`）；生产无悬赏令使用代码（`CURRENT_CODE`） |
| 当前未知 | 左键后是立即吞 / 目标光标 / 确认框；谁被吞；数量是否 −1；无合法目标时是否消耗；是否推进开进码头计数；背包内是否可用 |
| 必须看到的 before state | 物品栏该格颜色与数量裁图；羁绊栏逐格身份与稀有度（人工标注）；栏占用计数；无其他弹窗 |
| 允许动作 | `MANUAL_GT`：操作员单次左键该悬赏令格；之后 5 秒零输入。**不主动**测试高档替代（Owner 限制） |
| 必须看到的 business postcondition | 悬赏令数量 −1 或格变空 **且** 一张稀有度 ≤ 该档的海盗卡从栏中消失 **且** 无非海盗卡消失；若出现目标选择 UI，记录 UI 与取消路径 |
| UNKNOWN 时行为 | 生产不实现；保持 `NOT_IMPLEMENTED` |
| 能否进入 production | **否**。需物品身份+数量识别、逐格稀有度、受保护卡清单三项观测能力 |

### 8.3 满栏替换（full bond replacement）

| 项 | 内容 |
|---|---|
| 当前已知事实 | 合成释放格位（A 路径，`USER_CONFIRMED`，不重测）；新卡无法先释放时满栏需要替换（`USER_CONFIRMED`）；该自动化从未闭环（`USER_CONFIRMED`）；机制研究规则「任何时候都不能点进替换卡牌窗口」 |
| 当前未知 | 替换窗口外观；格位选择方式；取消入口；二次确认；超时；凑满卡在满栏时是否也弹窗 |
| 必须看到的 before state | 羁绊栏逐格确认 10/10；F 面板上一张**不能**凑满的卡；无其他弹窗 |
| 允许动作 | `MANUAL_GT`：操作员点该卡；先走**取消**路径，再（如 Owner 同意）走一次确认路径 |
| 必须看到的 business postcondition | 替换窗口模板裁图；取消后栏仍为 10/10 且各格身份不变；确认路径下恰好一格被换 |
| UNKNOWN 时行为 | 生产把替换窗口视为 CONFLICT：零输入，仅在已验证取消按钮时点击取消 |
| 能否进入 production | 只允许**否定规则**（识别窗口 → 零输入/取消）在拿到模板后进入；选择格位的自动化 **否** |

### 8.4 背包消耗品（bag consumable）

| 项 | 内容 |
|---|---|
| 当前已知事实 | HUD 物品格左键丹 = 消耗并吞一张（`REAL_LIVE_GT`，n=2）；背包页左键个人物品 = 使用（`USER_CONFIRMED`，规格文件，无帧）；单人 LIVE 从不开背包（`CURRENT_CODE`）；core `_bag_page_swallow_pill` 取第一个有东西的格、无身份（`CURRENT_CODE`，未接线） |
| 当前未知 | 背包内左键丹/悬赏令是否需要确认；数量变化；是否与 HUD 左键等价 |
| 必须看到的 before state | 背包页双锚点确认；源格身份（人工标注）与数量裁图；羁绊栏占用 |
| 允许动作 | `MANUAL_GT`：操作员单次左键该格 |
| 必须看到的 business postcondition | 源格数量 −1 **且**（丹）栏占用 −1；关闭背包后回到局内 HUD 正证据 |
| UNKNOWN 时行为 | 不使用；经已验证关闭按钮关闭背包 |
| 能否进入 production | **否**；`_bag_page_swallow_pill` 应隔离 |

### 8.5 随机吞噬丹（random pill）

| 项 | 内容 |
|---|---|
| 当前已知事实 | HUD 左键消耗并吞卡（`REAL_LIVE_GT`，n=2，第 1 次受封神榜倒计时干扰）；吞哪张由游戏决定（`USER_CONFIRMED`）；有受保护卡时禁止自动用（`USER_CONFIRMED`）；EX 神级吞噬丹吞 EX（`USER_CONFIRMED`，截图 `MISSING_ATTACHMENT`）；生产默认自动用、门槛仅 >3 张（P0-2） |
| 当前未知 | 目标分布（稀有度/位置）；与受保护卡的关系；EX 丹外观 |
| 必须看到的 before state | 羁绊栏逐格身份/边框颜色（人工标注）；丹数量；栏中无倒计时类卡（封神榜等） |
| 允许动作 | `MANUAL_GT` 或 `USER_ASSISTED`：栏中无受保护卡时单次左键；每次间隔 ≥ 5 秒；目标 5 次 |
| 必须看到的 business postcondition | 丹数量 −1 **且** 栏占用 −1 **且** 记录消失的是哪一格（前后逐格比对） |
| UNKNOWN 时行为 | 不用丹 |
| 能否进入 production | 自动用丹：**否**（且应立刻关闭默认，P0-2）；GT 只产出分布事实 |

### 8.6 亡灵（Necromancy）

| 项 | 内容 |
|---|---|
| 当前已知事实 | 卡头 `亡灵`（无进度）、卡名 `亡灵天灾`；每 50 杀一份残骸，累计 100 份吞全部亡灵卡 → UR 巫妖王；三种符文均 >10 → EX 兵主（`LIVE_BUNDLE`，卡面文字）；单人出现 35 次、拿 0 次；生产组成员 `亡灵/亡灵天灾/白骨复生/魂火收割/巫妖之躯`（`CURRENT_CODE`，后 3 个无帧）；词典「需要 3 张」（`CONFLICTED`） |
| 当前未知 | 开组后出现的卡头；残骸计数是否可见；符文卡卡头；巫妖王置入时的栏位变化 |
| 必须看到的 before state | F 面板卡头 `亡灵` 原始 OCR；栏占用 |
| 允许动作 | 生产策略按组优先级选择；不用丹；不加任何亡灵专属逻辑 |
| 必须看到的 business postcondition | 栏占用 +1 且新增图标；之后 F 面板出现的亡灵系卡头逐一记录原始 OCR；巫妖王/兵主仅在实际出现时记录 |
| UNKNOWN 时行为 | 按 hard whitelist 现有判定处理；不推断成员 |
| 能否进入 production | 仅在记录到真实卡头后修正**组成员配置**；机制代码 **否** |

### 8.7 秘境（Secret Realm）

| 项 | 内容 |
|---|---|
| 当前已知事实 | 大秘境 NPC 在战后广场，确认框只弹给点击者；灰色「是」≥0.85；大秘境框与提前挑战确认框靠标题模板区分（`447c2f4`，`LOCAL_FIXTURE`）；单人传家宝无胜利页（`REAL_LIVE_GT`，09-14）；11 个单人包秘境确认 0 次；无秘境真实帧；生产判据为两帧通用 HUD（P1-12）；秘境失败记 VICTORY（`CURRENT_CODE`） |
| 当前未知 | 秘境局内与广场的区分标记；载入时长；广场帧能否满足「无战后状态 + HUD」；秘境结束页；返回路径 |
| 必须看到的 before state | `post_game=NPC_HUB`；顶栏模式 = 广场；`_post_game_route=secret` |
| 允许动作 | `AUTO`（生产现有链）：右键 NPC 本体一次、点灰色「是」一次，之后零输入观察 |
| 必须看到的 business postcondition | 两张 sha 不同的帧：顶栏模式 ≠ 广场、非战后页、局内 HUD，并**额外记录一个秘境特有标记**；随后局内输入恢复；秘境结束后失败页 → 退出链 → 回房间 |
| UNKNOWN 时行为 | 现有行为：零输入、有界等待、放弃秘境 → QUIT；保持 |
| 能否进入 production | 现有代码可在 GT 中运行；「秘境 PASS」必须满足上表的秘境特有后置条件；判据改为秘境特有标记需 GT 后单独提交 |

---

## 9. 必须 GT 后才能处理的问题

| 问题 | 需要的 GT |
|---|---|
| 调度等待上限、木材预留、F 刷新预算的数值 | 单人一局完整资源时间序列（机制研究 GT-9） |
| 秘境判据改为秘境特有标记 | §8.7 |
| 海盗启动卡加入包定义 | §8.1 |
| 亡灵组成员修正 | §8.6 |
| 满栏替换窗口的否定规则 | §8.3 模板 |
| 悬赏令/背包消耗品任何自动化 | §8.2、§8.4 + 观测能力 |
| 吞丹目标分布 | §8.5 |
| Win32 DPI 与坐标系一致性 | GT 时记录双方 DPI/客户区 |
| `_exit_rearm_attempts` 边界是否可循环 | 退出链 bundle 回放 |

**不需要等 GT、应先做的**：P0-1 规避或修复、P0-2 默认关闭、P0-3 manifest、P1-4 fail-closed、P1-10 设置隔离、§4.6 看板降级。

---

## 10. Release 前必须完成的最小闭环

按顺序，每步都有可检验的出口：

1. **P0-2**：生产 `auto_devour_dan` 默认关闭或加「身份未知 → 零输入」硬门；验证器要求数量与占用同时变化。出口：RuntimeMediator 级测试，替身只限 I/O。
2. **P0-1**：重置语义改为显式原因；新增 `RuntimeMediator.tick()` 两局离线测试，分别走声望与非声望路径，断言 §2 列出的字段在第 2 局首帧为初值。出口：该测试在 `bbf2de0` 上失败、修复后通过。
3. **P1-2**：统一 core/runtime 的 MAIN_LINE 重入语义。出口：附录 A.2 探针两个类输出一致。
4. **P0-3**：identity manifest 写入每个 bundle；Live lnk 更新到候选 SHA；test 分支 src 改动归位或列为 delta。出口：`READY FOR GT: YES` 且 manifest 中 `test_only_delta` 明确。
5. **P1-4**：模式禁令加载失败 fail-closed。出口：单测「mode_specs 缺失 → RoomStart 被拒」。
6. **P1-1**：frozen_replay 与 contract 至少增加 RuntimeMediator 一轮。出口：gate 输出两列。
7. **gate 快照**：在 1–6 完成后，一次性刷新 `giveup_panel_not_fail` 期望（附夹具点位说明）与 asset 计数；冻结基线是否重定由 Owner 决定。
8. **GT-0 安全烟测**（handoff §4）+ §8.7 秘境一次 + §8.1 海盗启动一次。
9. 以上全部在同一 production SHA 上完成，bundle manifest 可追溯。

---

## 11. 建议的下一阶段架构（只建议，不重构）

目标不是重写，而是把「authority」一个一个从 if 链里提出来，每一步都可单独回退。

```text
Frame ──► Observation (纯函数，三态：值 / UNKNOWN / ERROR)
             │  surface, hud, post_game, top_bar_mode, bars, counters
             ▼
        RoundState / SessionState  (显式生命周期对象，整体替换)
             │
             ▼
        Arbiter (唯一输入 authority)
             │  1. 活动事务持有者  2. 强制模态  3. 容量应急
             │  4. 等待超上限      5. 计划服务  6. 可延后
             ▼
        Transaction (每类一个：开始条件 / 单输入 / 业务后置条件 / 超时 / 恢复)
             │
             ▼
        InputExecutor (动作类型枚举 + fail-closed 禁令 + 一 tick 一输入)
```

渐进步骤（每步都是独立 PR，行为不变先行）：

1. **RoundState 提取**：把 `set_phase` 重置块里的字段移入 `RoundState` dataclass，`entering_main_line` 时整体新建。先只移动，不改语义（P0-1 修复作为前一个独立提交）。
2. **Observation 三态化**：`_is_in_game_hud`、`_post_game_state`、`find_window_targets` 返回三态；旧布尔接口作为适配器保留。
3. **测试替身边界下移**：新测试只替身 `capture` 与 `executor`，以 bundle 帧驱动 `RuntimeMediator.tick()`；旧测试不删，逐步迁移。
4. **Arbiter 影子模式**：在 `_tick_main_line` 入口计算「Arbiter 会选谁」，只写 trace，与实际输入比较（与机制研究 §16 的影子调度一致）。
5. **Transaction 后置条件表**：先为吞丹、秘境进入、F 选择三类写强后置条件并接入 trace 评分，再替换 verifier。
6. **core/runtime 合并**：runtime 覆盖逐个下沉到 core，每下沉一个就删掉对应覆盖，frozen_replay 同步切到合并后的类。
7. **身份与入口单一化**：identity manifest 生成器 → harness 唯一 preflight → PS1/看板只调起。

不建议：在上述第 1–4 步完成前实现海盗/亡灵/悬赏令自动化，或调整调度阈值。

---

## 附录 A：离线复现脚本

在 G 根（`bbf2de0`）用 `.venv\Scripts\python.exe` 运行，零输入、不连窗口。

### A.1 `probe_round_reset.py`

```python
import sys, time
from pathlib import Path
sys.path.insert(0, "src")
from shuabao.settings import Settings
from shuabao.runtime_mediator import Mediator as RM
from shuabao.mediator import Phase, ChallengeState

med = RM(Settings(), Path("."))
med.phase = Phase.MAIN_LINE
med._auto_task_done = True
med._main_line_closed_done = True
med._close_main_line_triggered = True
med._challenge_done = {"coin_challenge", "wood_challenge"}
med._challenge_states = {k: ChallengeState.ON for k in med._challenge_states}
med._main_line_started_at = time.time() - 1500
med._main_line_since = med._main_line_started_at
med._skill_cards_owned.append("asj")
med._post_game_route = "archive"
med._secret_realm_active = True
med._time_cave_boss_done = True
med._merchant_next_at = 9e12
med._evolve_ok_this_cycle = True
med._round_deadline = None
med._bond_cards_owned.append("经济")
for ph, note in [(Phase.QUIT, "round over"), (Phase.NEXT, "x"),
                 (Phase.STAGE_SELECT, "back"), (Phase.STAGE_STARTING, "stage start clicked")]:
    med.set_phase(ph, note)
med.set_phase(Phase.MAIN_LINE, "challenge start verified")
for f in ["_auto_task_done", "_main_line_closed_done", "_close_main_line_triggered",
          "_challenge_done", "_main_line_started_at", "_skill_cards_owned", "_post_game_route",
          "_secret_realm_active", "_time_cave_boss_done", "_merchant_next_at",
          "_round_deadline", "_bond_cards_owned", "_l1_cycle_step"]:
    print(f, getattr(med, f))
```

本轮输出（摘要）：`_auto_task_done=True`、`_main_line_closed_done=True`、`_close_main_line_triggered=True`、`_challenge_done={'wood_challenge','coin_challenge'}`、`_main_line_started_at=1500s ago`、`_skill_cards_owned=['asj']`、`_post_game_route=archive`、`_secret_realm_active=True`、`_time_cave_boss_done=True`、`_merchant_next_at=9e12`、`_round_deadline=None`、`_bond_cards_owned=[]`（runtime 覆盖清空）、`_l1_cycle_step=bond`。

### A.2 `probe_challenge_return.py`

```python
import sys
from pathlib import Path
sys.path.insert(0, "src")
from shuabao.settings import Settings
from shuabao.runtime_mediator import Mediator as RM
from shuabao.mediator import Mediator as CM, Phase
for cls in (CM, RM):
    med = cls(Settings(), Path("."))
    med.phase = Phase.MAIN_LINE
    med._bond_cards_owned.extend(["经济", "经济", "藏宝图(三)"])
    med._l1_cycle_step = "treasure"
    med.set_phase(Phase.EARLY_CHALLENGE, "tqtz confirmed")
    med.set_phase(Phase.MAIN_LINE, "challenge return")
    print(cls.__module__, med._bond_cards_owned, med._l1_cycle_step)
```

本轮输出：`shuabao.mediator ['经济','经济','藏宝图(三)'] treasure`；`shuabao.runtime_mediator [] bond`。

### A.3 `giveup_panel_not_fail` 点位核对

在 `tests/performance/fixtures/giveup_panel.jpg`（1920×1080）上以 (1020,654) 与 (1171,677) 画圈裁出 x∈[880,1300]、y∈[560,760]：前者位于「技能免费刷新次数+1」文字右下、「放弃」按钮上沿；后者位于「刷新(3)」按钮中央。裁图未提交（本分支只提交报告），可用同参数复现。

---

## 附录 B：度量方法

| 度量 | 值 | 方法 |
|---|---|---|
| `mediator.py` 行数 | 17897 | `wc -l` |
| Mediator 方法 / 实例属性 / 懒创建属性 | 449 / 461 / 64 | `ast` 遍历 `self.<attr>` 赋值目标，对比 `__init__` |
| 被 ≥5 个方法写入的属性 | 65 | 同上 |
| `getattr(self, "_…"` | 362 | grep |
| `_tick_main_line` 行数 / return | 1419 / 161 | ast |
| `act_*` 调用点 / 所在方法 | 94 / 46 | ast |
| RuntimeMediator 覆盖 core 的方法 | 24 | 方法名比对 |
| 测试 `patch.object(…, "_…")` | 1151 | grep |
| 测试直接调用 `_tick_*`/`_maybe_*` | 680 | grep |
| 测试 `.tick()` 调用 | 130 | grep |
| 测试直接写 `med._x = ` | 1344 | grep |
| `src/shuabao` 宽泛 except 后紧跟静默返回 | 79 | grep -A1 |
| G 根 `tools/` 条目 / 已跟踪 | 172 / 65 | `ls` / `git ls-files` |

---

## 附录 C：本轮未做的事

- 未跑正式 GT，未连接游戏窗口，未发送输入。
- 未修改 production、test、main、快捷方式、baseline、夹具、配置。
- 未开 PR，未 merge。
- 未审：`ui-v2`、订阅/签名服务、`AttachThreadInput` 异常路径、`_tick_lobby_hitch` 内部细节（蹭车线本轮不在范围）。
