# 面板与外围 审查（desktop_app.py / monitor_game_over.py / settings.py / tests）

审查基准：HEAD `13a4d1a`（工作区干净）。已实测运行 `tests/test_desktop_app.py`、`tests/test_monitor_game_over.py`（10 passed）、`tests/test_temporal_same_room_loop.py`（1 failed，见 P0-2）。

## P0 致命（卡死/误操作/资源泄漏）

### P0-1 运行中直接关闭窗口 → QThread 销毁崩溃
- **位置**：desktop_app.py:539-583（toggle_run 启动线程），MainWindow 无 `closeEvent` 重写（235-457 全类无）。
- **现象**：运行中用户点窗口 × → `app.exec()` 返回 → 解释器销毁 `MediatorWorker`（C++ QThread）时线程仍在 `mediator.run()` 循环里 → Qt `QThread: Destroyed while thread is still running` → qFatal abort。此时任务也没停（stop 无人调用），紧急停止仅靠 Shift+F12（且需 mediator 已启动 EmergencyStopListener）。
- **根因**：线程生命周期与窗口生命周期无关联；`toggle_run` 只在按钮路径处理停止，窗口关闭路径完全裸奔。
- **加固**：`MainWindow.closeEvent` → 若 `worker_thread and worker_thread.isRunning()`：先 `worker_thread.stop()`，再 `worker_thread.wait(5000)`，超时则 `QMessageBox.warning` 提示"任务未完全退出，请稍候"并 `event.ignore()`；或 `worker_thread.finished.connect(self.close)` 异步收尾。这是最直接的崩溃路径，建议优先修。

### P0-2 过期测试红灯：test_unknown_choice_panel_is_bounded… 断言旧行为（实测失败）
- **位置**：tests/test_temporal_same_room_loop.py:102-121（断言 `["HideUnknownSelection"]*3`）。
- **现象**：实测运行该测试 FAILED——源码已无 `HideUnknownSelection` 动作（mediator.py:2007-2011 是"零输入等待 → 10s 超时 Fail-Closed 停机"），测试却断言点击了 3 次隐藏按钮。实测 stdout 显示新行为正确：3×Continue 零动作 → `已等 10s` → Break → `Phase.ERROR`。
- **根因**：P0 修复"未知选择面板 Fail-Closed 停机（零输入+主动面板关闭）"落地后，测试未同步改写，把旧实现（盲点隐藏 ×3）固化成断言。
- **加固**：该测试改为断言：4 次 tick 中前 3 次 `LoopAction.Continue`、第 4 次（`_selection_unknown_since` 前置到 10s 前，或 patch `time.time`）`LoopAction.Break` + `Phase.ERROR`；`self.actions` 保持空（零输入）且 patch `act_click` 断言 `assert_not_called()`。注意现有测试对 `elapsed>=10` 分支未做时间控制（靠真实匹配耗时 4s/tick 凑出 10s），应显式 patch 时间，否则是脆弱测试。

### P0-3 停止竞态：startup 窗口期 stop() 被吞，任务继续跑
- **位置**：desktop_app.py:143-145（MediatorWorker.stop 仅转发）；mediator.py:2144-2146（run() 开头 `self._running=True; self.stop_signal.reset()`）。
- **现象**：用户在"点开始"后极短时间内点停止：(a) `self.mediator` 尚未被 worker 线程赋值 → stop() 空转，任务照常启动；(b) 更糟：`mediator.stop()`（1779-1781 置 `_running=False` + 触发信号）先执行，随后 `run()` 的 `stop_signal.reset()` 把停止信号清掉、`_running=True` 恢复 → 用户明确要求停止，真机链路却继续点击。
- **根因**：停止意图没有在 worker 层持久化；`run()` 无条件 reset 信号，与外部 stop 存在 TOCTOU。
- **加固**：`MediatorWorker` 增加 `self._stop_requested = False`，`stop()` 置位并（若 mediator 存在）转发；`run()` 进入循环前 `if self._stop_requested: return`。或 `Mediator.run()` 改为仅在 `not self._running` 时 reset（`if self.stop_signal.is_set() and not self._running: return`）。后者最小改动。

## P1 严重（稳定性/边界）

### P1-1 Settings._from_dict 无类型/范围校验，坏配置直接炸或误开真机输入
- **位置**：settings.py:146-158（`_from_dict` 只过滤未知键 + None→默认，其中 None 分支仅覆盖字符串/列表字段）。
- **现象**：
  - `"query_timeout": null`（官方配置常见 null）→ 数值字段 None 不被处理 → `Settings(query_timeout=None)` → mediator `time.time()+None`（如 mediator.py:1336）TypeError 崩溃。
  - `"stage2": "abc"` → `apply_settings_to_ui`（desktop_app.py:497 `int(settings.stage2)`）ValueError → **整份配置加载失败**（load_local_settings 兜底，但用户所有 UI 预设丢失且无明细）。
  - `"loop_sleep_ms": "400"` → `time.sleep("400"/1000.0)`（mediator.py:2183）TypeError。
  - `"dry_run": 0`（int）→ falsy → **真机输入被静默打开**；`"auto_create_room": "false"`（字符串）→ truthy → 自动建房。布尔/数值类型混淆是误操作源头。
  - `"match_threshold": "0.85"` → 匹配器 float 比较 TypeError 或静默阈值错误。
- **根因**：dataclass 无 `__post_init__`，`_from_dict` 只做键过滤与局部 None 处理，不做 per-field 类型转换与边界钳制。
- **加固**：`__post_init__` 或 `_from_dict` 末尾统一：数值字段 `int()/float()` 转换 + 钳制（stage1/2 ∈ [1,99]、query_timeout ∈ [3,300]、game_timeout ≥ 3、match_threshold ∈ [0,1]、click_delay_ms/loop_sleep_ms ≥ 0、artifact_slots ∈ [1,3]、window_size 校验 len==2 且 >0）；布尔字段严格 `bool(v) if isinstance(v, bool) else 默认值`（字符串 "false" 不得为 True）；skills/cards/stage_targets 强制 `list` 且元素 `str`。**dry_run 必须 fail-safe：任何非 bool 值一律按 True（安全测试）处理。**

### P1-2 load_official 字符串技能被逐字符拆解
- **位置**：settings.py:124-125（`if lk in ("skills","cards") and not isinstance(v, list): v = list(v) if v else []`）。
- **现象**：官方 `"Skills": "jq"`（字符串）→ `['j','q']` → 模板名 "j"、"skills/j" 全部 miss → 技能选卡永远为空（挂机只识别不选卡）。`list("jq")` 应得 `["jq"]`。
- **根因**：`list(v)` 对字符串按字符拆解；字符串技能应包成单元素列表。
- **加固**：`v = [v] if isinstance(v, str) else list(v)`；同时对 skills/cards 元素做 `str` 清洗与去空。

### P1-3 monitor_game_over 是死代码，且阈值不随 ROI 尺寸缩放
- **位置**：src/gamescript/monitor_game_over.py:36-82；全仓库仅 test_monitor_game_over.py 引用（grep 证实无任何业务 import）。
- **现象**：
  - 静止候选从未被主循环消费：mediator 的战后分类（`_post_game_state`）与 frozen/old 帧处理（mediator.py:1794-1800）都不使用本模块。模块 docstring 明言"Callers must combine…"，但无 caller。
  - 阈值语义与 capture.py:256-261 的 FROZEN 检测（`np.array_equal` 全等 + 5s）不一致：同一画面，FROZEN 要求逐像素全等，GameActivityMonitor 允许 ≤500 像素差（15/255 阈值 + 高斯模糊）——两条检测线对"静止"的定义不同，若未来接入会互相矛盾。
  - `changed_pixels <= 500`（64 行）是绝对像素数：1600x900 ROI 下容差仅 0.035%，任何 HUD 动画/技能特效/光标闪烁都超限 → 永远 not still；小 ROI（200x200）则容差 1.25% 过宽。尺度依赖。
  - 任何无效帧（None ROI / NaN 时间戳 / 时间回拨 / shape 变化）→ 整机 reset（47/53/57-59 行）→ 瞬态截屏坏帧会打断 2s 计时，需重新累积。
- **根因**：模块独立开发后未接线；阈值是固定像素而非比例。
- **加固**：(a) 接入点建议在 `_tick_main_line` 的 `_post_game_state` 判定前：`stillness_candidate and (victory|fail|post-game 锚点)` 组合才判 game-over；(b) 阈值改比例 `changed_pixels <= 0.0005 * roi.size`（或按 ROI 面积归一化）并参数化；(c) `_prepare` 失败时保留 `_still_since`（瞬态坏帧不打断），仅对明确无效输入（None/NaN）reset；(d) 接入后补"静止候选 + 锚点 → 判定"的集成测试。

### P1-4 输入拒绝链关键路径无测试：遮挡检测与动作后校验
- **位置**：src/gamescript/input/keyboard_mouse.py:117-136（`_check_point_obscured`）、140-143（`_post_check`）；tests/test_p0_security.py 覆盖了 emergency/elevation/hwnd/foreground 五条拒绝（194-249 行），**但 `_check_point_obscured`（WindowFromPoint 遮挡拒绝，修复"窗口被 VS Code 遮挡"卡死的核心）与 `_post_check`（动作后前台丢失）零测试**。
- **现象/风险**：这两条是防止"点错窗口"误操作的最后两道闸，无回归网；若后续改动破坏（如 foreground_matches_target 同进程放宽逻辑误伤），静默漏点击或误点击都测不出。
- **加固**：补测试：patch `ctypes.windll.user32.WindowFromPoint` 返回异进程 hwnd → 断言 `CANCELLED_WINDOW_OBSCURED` 且底层 click 未被调用；patch `get_foreground_window` 动作后返回他窗口 → 断言 `CANCELLED_WINDOW_CHANGED`；同进程不同 hwnd 应放行（foreground_matches_target 同 PID 逻辑）。

### P1-5 状态机超时分支大量无测试（详见 §测试覆盖缺口）
- **位置**：mediator.py:1886（victory page did not close）、1951（post-game transition timeout）、2007（unknown selection panel timeout，现有测试断言旧行为）、2083（main_line idle timeout）、1539（same room return timeout）、2104（exit button timeout）、2120（exit confirmation timeout）、1657（L0 cycle limit）、1698（configured stage not found）、1813-1833（unhealthy frame timeout）。
- **现象**：这些 Fail-Closed 停机分支是"卡死"的最后防线，但除 challenge UNKNOWN 超时（test_p1a2:286）与 missing-window（test_lobby_detectors:47）外全部未测。test_p0c1_fixes:37 只测 QUIT/NEXT 的零输入锚点，不测 `attempts>=3 or elapsed>=timeout` 分支；test_p1b0:97 只测 victory 3 次重试上限，不测 `elapsed>=timeout` 的"等待超时"分支。
- **根因**：超时分支需 patch `time.time()`，测试编写成本略高，历史未补。
- **加固**：按超时类型各补 1 条：patch `gamescript.mediator.time.time`（monkeypatch 单调递增）把 `_victory_continue_since`/`_exit_since`/`_main_line_since` 置为过去 → 断言 `LoopAction.Break` + `Phase.ERROR` + `stop_signal.is_set()` + 零输入。

## P2 一般

- **desktop_app.py:113-127 hook_print 阶段解析显示"上一阶段"**：`parts[1].split()[0]` 取到 "phase OLD → NEW" 的 OLD（如 "BOOT"），`"BOOT".split("→")[-1]` 仍是 "BOOT" → 面板"运行中 · 阶段"永远滞后一个阶段（进入 MAIN_LINE 后持续显示 STAGE_STARTING）。应改为 `parts[1].split("→")[-1].strip().split()[0]`。
- **desktop_app.py:516-520 collect_settings_from_ui 丢弃章节号**：`_, stage_index = ...`，随后 `stage1=stage2=stage_index`（test_desktop_app:63-64 固化了 2-7 → 7/7）。面板始终写 stage_targets 故暂无害，但若 stage_targets 为空走 `find_stage_in_range(stage1, stage2)`（mediator.py:1483-1487）会找"编号 7 的行"而非"第 2 章第 7 关"，语义错误。建议 `stage1=章节, stage2=关卡`。
- **desktop_app.py:514 关卡输入无上限**："999-9999" 通过 `([1-9]\d*)-([1-9]\d*)` → 选关永远 miss → 8 次滚动 + `configured stage not found` 停机（fail-closed 安全，但应 UI 层直接拒绝）。建议章节 ≤ 9、关卡 ≤ 60 之类与游戏一致的边界。
- **desktop_app.py:494-510 apply_settings_to_ui 阵营钳制与 UI 不一致**：`rep_type = max(1, min(6,...))` 但下拉只有"肯瑞托(3)"，配置为 6 时 UI 显示肯瑞托、settings 里仍 6 → mediator `_begin_hero_setup` 遇未知阵营 Fail-Closed 停机，用户困惑。
- **desktop_app.py:580-583 线程收尾无 finished 连接**：旧 worker 靠 `isRunning()` 门控 + GC 回收；stop 后线程实际退出时机不可见（若 mediator 阻塞在截屏，面板一直显示"停止运行"）。建议 `worker.finished.connect(lambda: self.log("[结束] 线程已退出"))` 并复位按钮。
- **desktop_app.py:133-135 任务异常只打一行 `{e}`，无 traceback**：崩溃根因（哪个阶段/哪个调用）不可见，只能猜。建议 `LOGGER.error(..., exc_info=True)` 或 `traceback.format_exc()`。
- **desktop_app.py:458-466 面板 txt_log 无时间戳**：文件日志有 `asctime`（49-52），面板内裸文本，卡住时无法对照时刻。建议 `log()` 内加 `[HH:MM:SS]` 前缀。
- **desktop_app.py:88-146 无启动环境快照**：Python/OpenCV 版本、是否管理员、目标窗口是否可见均不落盘，排"为什么没点击"全靠猜。建议 run() 开头打印 `sys.version`、`cv2.__version__`、`is_current_process_elevated()`、`find_window_targets` 结果数。
- **desktop_app.py:602-605 `sys.excepthook` 只覆盖主线程**：Python ≥3.8 线程异常走 `threading.excepthook`；worker 已全 try/except 兜底，风险低，但建议一并注册（防未来新增线程裸奔）。
- **desktop_app.py:78-79 LogSignal 无 parent**：QObject 纯 Python 持有，依赖 `self.worker_thread` 引用保活；`isRunning()` 门控避免了重建碰撞，但建议 `self.signals.setParent(self)` 或随 worker 显式管理。
- **settings.py:168-179 `skill_template_names` 未校验技能短码**：`s` 可含路径分隔符 → 模板路径拼接越界（本地配置，非安全边界，但建议白名单/去分隔符）。
- **settings.py:161-166 `save()` 原样回写**：损坏值（None/str）会 round-trip 永久化；建议 save 前经同一套校验/钳制。
- **mediator.py:794 `artifact_slots` 有使用层钳制（好）**，`artifact_cd` 有 `max(30,...)`（793）——settings 层宽松被部分弥补，但 stage/query_timeout/dry_run 无使用层防线。

## 性能与流畅度

- **monitor_game_over 若接入的代价**：GaussianBlur(5,5) + absdiff + threshold + countNonZero 全 ROI 每帧；1600x900 灰度约数 ms，可接受；但建议与 hero 全帧匹配（已知 0.223s/帧）不同——只对"战后锚点候选帧"或降采样 ROI 计算，避免每帧都跑。
- **面板 txt_log 无行数上限**：`appendPlainText`（desktop_app.py:466）长跑后 QPlainTextEdit 内存线性增长；建议 ≥1000 行裁剪（`document().setMaximumBlockCount(1000)`）。
- **hook_print 每行 print 都做关键字分类 + 两路转发**：频率受 `loop_sleep_ms=400` 限制，每 tick 至多几行，无压力；但 `status_changed` 的 phase 正则解析在每行 print 上跑（低效且逻辑错误，见 P2），顺带修复。
- **缓存现状（良好）**：`_context_cache_frame`（mediator.py:204-206）、`_scene_cache`、`_stage_click_cooldown_until`/`_selection_click_cooldown_until` 冷却避免同帧重复点击；`SKILL_STEMS`/`SKILL_LABELS` 模块级一次性加载。无可优化热点。
- **stop 响应延迟**：stop 只在每 tick 之间生效（`time.sleep(loop_sleep_ms/1000)`）；若某 tick 内发生阻塞截屏/匹配，停止最长延迟一个 tick + 阻塞时间。可接受，但 EmergencyStopListener 轮询 50ms 与主循环解耦，Shift+F12 是即时路径（好）。
- **启动即全量 glob assets**（desktop_app.py:29-34 `_stems`）：一次性，毫秒级，无问题。

## 测试覆盖缺口汇总（核心路径无测试）

| 路径 | 位置 | 现状 |
|---|---|---|
| settings 加载兜底（缺失/None/类型/越界/技能空） | settings.py:112-158 | **整个 settings.py 无测试文件**；只有 test_p0c1:30 读 default_settings.json 断言 auto_secret_realm=False |
| MediatorWorker 线程生命周期（stop 幂等、启动竞态、异常清理、关窗） | desktop_app.py:80-146 | 无测试（UI 集合/收集逻辑除外） |
| `_check_point_obscured` / `_post_check`（输入拒绝链尾部） | keyboard_mouse.py:117-143 | 无测试（前段 5 条拒绝已覆盖） |
| 超时分支：victory page did not close / post-game transition / main_line idle / same room return / exit button / exit confirmation / L0 cycle / configured stage not found / hero step deadline 过期 / unhealthy frame | mediator.py:1886,1951,2083,1539,2104,2120,1657,1698,1813 | 未测（challenge UNKNOWN 超时、victory 重试上限、missing-window 已测） |
| unknown selection panel timeout（elapsed≥10） | mediator.py:2007 | 测试存在但断言旧行为，**红灯**（P0-2） |
| 面板异常路径：load_local_settings 失败、collect 边界（章节丢弃/无上限） | desktop_app.py:482-537 | 未测（test_desktop_app 只测正则拒绝 + 技能空） |

## 实测证据

- `python -m pytest tests/test_desktop_app.py tests/test_monitor_game_over.py -q` → **10 passed**（面板 UI 集合、monitor 静止检测行为均绿）。
- `python -m pytest tests/test_temporal_same_room_loop.py -q` → **1 failed**（P0-2，断言旧 `HideUnknownSelection` 行为）。
- 全量 `pytest tests/ -q` 在 49% 处出现 `F`（即上述失败），900s 超时未跑完（replay 模板匹配慢，属已知成本，非本次问题）。
