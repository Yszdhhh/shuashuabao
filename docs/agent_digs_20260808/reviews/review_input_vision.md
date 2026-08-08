# 输入与视觉层审查

审查范围：`src/gamescript/input/keyboard_mouse.py`、`emergency_stop.py`、`vision/capture.py`、`vision/matcher.py`；交叉阅读 `mediator.py` 调用链、`jobs/auto_job.py` 遗留路径、`stop_signal.py`。

已知历史问题（遮挡 WAIT_MODAL、冻结/陈旧帧误杀、选关误判等）不重复开单，仅在有新角度时提及。

---

## P0 致命（卡死/误操作/资源泄漏）

### 1. Legacy AutoJob 绕过全部输入安全链
- **文件:行号**: `jobs/auto_job.py:53-60`, `jobs/auto_job.py:110-112`; `main.py:57-59` (`--legacy`)
- **现象**: `--legacy` / `LongzhuJob` 直接调用模块级 `click()` / `press_key()`，**不经过** `InputExecutor.check_can_execute` / 前台校验 / 遮挡检测 / 急停 / 提权门闩。
- **根因**: 安全封装只挂在 `InputExecutor`；standalone API 默认仅 `dry_run` 布尔门，无 HWND 约束。
- **加固建议**:
  1. `AutoJob._click_hit` 改为持有 `InputExecutor`（共享 `StopSignal`），禁止直接 `from keyboard_mouse import click`。
  2. 或在 standalone `click/press_key` 内强制 `dry_run=True` 除非显式传入已验证 token；`main.py --legacy` 打印 FATAL 并拒绝 `dry_run=False`。
  3. 中长期删除 legacy 路径，只保留 Mediator。

### 2. 滚轮路径无点位遮挡校验 → 误滚其它窗口
- **文件:行号**: `input/keyboard_mouse.py:316-327` (`InputExecutor.scroll`); 对照 `click/right_click` 246-268 有 `_check_point_obscured`
- **现象**: 选关列表滚动（`mediator.py:1689-1690` `executor.scroll(x,y,-5)`）只做 HWND/前台/提权检查，**不做** `WindowFromPoint`。游戏被 VS Code/终端盖住时，滚轮落到编辑器，表现为“关卡列表不动 / 编辑器乱滚”，状态机空转至超时 ERROR。
- **根因**: 遮挡检测只接到 click/right_click；scroll 用 `pyautogui.moveTo + scroll`，同样受命中窗口影响。
- **加固建议**: `InputExecutor.scroll` 在 `not dry_run and target_hwnd` 时复用 `_check_point_obscured(target_hwnd,x,y)`；失败返回 `CANCELLED_WINDOW_OBSCURED`。可选：滚轮也改 SendInput `MOUSEEVENTF_WHEEL`，与 click 同源。

### 3. 建房密码粘贴后剪贴板可能残留（非文本/空剪贴板/Open 失败）
- **文件:行号**: `input/keyboard_mouse.py:384-401` (`paste_text`); 调用方 `mediator.py:1506` 填 `room_password`
- **现象**:
  ```python
  saved_text = get_clipboard_text()  # 非文本或 OpenClipboard 失败 → None
  ...
  finally:
      if saved_text is not None:   # None 时不恢复
          set_clipboard_text(saved_text)
  ```
  原剪贴板是图片/文件/空，或 `get_clipboard_text` 失败时，房间密码留在系统剪贴板。
- **根因**: 只按“曾读到 Unicode 文本”才恢复；把“读失败/非文本”与“本来就是空”混为 `None`。
- **加固建议**:
  1. 引入三态：`_CLIPBOARD_UNAVAILABLE` / `saved:str|bytes` / 明确 empty。
  2. `finally`：**只要成功 `set_clipboard_text(password)` 就必须清理**——恢复旧文本，或 `EmptyClipboard`，绝不留下密码。
  3. 优先走已有 `type_text`（CEF 友好且不碰剪贴板）填房间名/密码；`paste_text` 仅作回退。

### 4. 遮挡检测 API 异常时 fail-open（放行点击）
- **文件:行号**: `input/keyboard_mouse.py:213-228`
- **现象**: `WindowFromPoint` 抛错或返回路径异常时 `return None`，调用方视为“未遮挡”继续 `SendInput`。这与“遮挡导致 WAIT_MODAL 卡死”的历史根因同型，只是从逻辑漏检变成异常漏检。
- **根因**: 安全检查失败默认放行。
- **加固建议**: 非 dry_run 下 ctypes 失败应 **fail-closed**：返回 `CANCELLED_OBSCURE_CHECK_FAILED`；仅 dry_run 可忽略。

---

## P1 严重（稳定性/边界）

### 5. `_post_check` 在动作已发生后标失败 → 双击/重试误操作
- **文件:行号**: `input/keyboard_mouse.py:196-211`, 各 `click/scroll/...` 返回路径
- **现象**: 点击/滚动已执行，若此后前台切换或急停置位，返回 `success=False`。Mediator 多处 `if not self.act_click(...): return Continue` 会在下一 tick **再点一次**（选关、建房确认、选择面板）。
- **根因**: 事后校验与“是否已注入输入”未分离。
- **加固建议**: 拆成 `injected: bool` + `post_status`；已注入则 `success=True, status=SUCCESS_FOREGROUND_LOST` 供日志，**禁止**业务层当“未执行”重试。或 post 失败时进入短冷却，不在同一状态立即重发。

### 6. 动作中段不可取消（急停/长输入）
- **文件:行号**: `keyboard_mouse.py:479-530` (`_send_mouse_click` 固定 sleep 0.20+0.02+0.05+delay); `403-465` (`type_text` 每字符 50ms+); `emergency_stop.py:34-42`
- **现象**: Shift+F12 在 click 的 ~370ms+ 睡眠或 `type_text` 循环中不会中断当前注入；只能挡**下一次** `check_can_execute`。
- **根因**: 底层注入无协作式 cancel；listener 只写 `StopSignal`。
- **加固建议**: `_send_mouse_click` / `type_text` 在 sleep 切片间查 `stop_signal.is_set()`；`InputExecutor` 把 signal 传入 standalone 或改为实例方法注入。

### 7. 非前台截屏：PrintWindow 坐标/内容与 mss 客户区不一致
- **文件:行号**: `vision/capture.py:561-565`, `487-515` (`_capture_print_window`)
- **现象**: `activate=False` 且非前台时走 PIL `ImageGrab.grab(window=hwnd)`；成功则用 `client_left/top` 标 Frame 原点。PIL 抓到的常是**含非客户区**或尺寸≠`GetClientRect`，导致 `MatchResult.screen_x/y = frame.left + x + w//2` 整体偏移，真实点击打偏。
- **根因**: 两套捕获后端像素空间未对齐；失败才回落 mss（mss 在遮挡时抓到的是桌面上层，更糟）。
- **加固建议**:
  1. PrintWindow 后按 `client_width/height` crop（去掉标题栏/边框），再设 left/top=client 原点。
  2. 尺寸与 client 差 >N px 时丢弃 PrintWindow，标记 `is_valid=False` 或强制 `activate_window` 后 mss。
  3. Mediator 真输入前若 frame 来自 offscreen 路径，先 activate 再重抓一帧再点。

### 8. mss 遮挡窗口静默抓到“上层异物”帧
- **文件:行号**: `capture.py:561-589`
- **现象**: 前台==target 但客户区被其它置顶窗部分覆盖时仍 mss 客户区矩形 → 帧内含编辑器像素；健康检查未必黑/低熵；模板误匹配或坐标点到遮挡物。点击侧有 WindowFromPoint，**识别侧没有**。
- **根因**: 捕获路径无“客户区采样点是否属于本 HWND”校验。
- **加固建议**: `capture_target` 末尾对客户区中心/四象限 `WindowFromPoint`；若 PID 不属于 target，打 `FrameHealthIssue`（如 `OBSCURED`）或 `is_valid=False`，让 tick 走不健康等待而非瞎匹配。

### 9. 多窗口排名：每 tick 全量截屏 + 全量上下文识别
- **文件:行号**: `mediator.py:244-259` (`_capture_best`); `capture.py:328-424` (`find_window_targets`)
- **现象**: `targets>1` 时对**每个**窗口 `capture_target`，再 `max(..., key=_frame_signal)`；而 `_frame_signal` → `_detect_context` → 多组 `find_scene` / `_selection_anchor`（多模板×多尺度）。双开 KK/游戏或残留窗口时，单 tick 捕获与匹配成本×N，曾与“一帧 8s”同类。
- **根因**: 用重识别做窗口选择；`find_window_targets` 内每个候选还 `OpenProcess+QueryFullProcessImageNameW+ClientToScreen`。
- **加固建议**:
  1. 排名先用轻量特征（标题分、client 尺寸、上次 hwnd 粘性、可选 64×64 缩略图哈希），只对 top-1 或 top-2 做全量 context。
  2. 缓存 `hwnd → (pid,exe,class)`，枚举期不重复 OpenProcess。
  3. `capture_target` 复用线程内 `mss` 实例，避免每次 `with mss.mss()`。

### 10. 模板无内存缓存 + `resolve_template` 未命中即 `rglob`
- **文件:行号**: `matcher.py:30-38`, `41-61`, `264`, `320`
- **现象**: 每次 `match_one`/`match_all` `np.fromfile + cv2.imdecode`；名字解析失败走 `images_dir.rglob("*.png")`。选择面板/场景轮询每秒多次，磁盘与解码占满热路径（对照原版 IL：启动时 Dictionary 缓存 Bitmap）。
- **根因**: 无 `path → ndarray` 缓存；模糊搜索作主路径回退。
- **加固建议**: 模块级 `lru_cache`/`dict` 按 `mtime` 失效；启动或 `Mediator.__init__` 预热 scenes 用到的模板；`rglob` 仅诊断日志一次，运行期禁止。

### 11. `match_all` 低阈值 + `np.where` 候选爆炸
- **文件:行号**: `matcher.py:335-347`; 调用 `mediator.py:670-677`, `717`（threshold≈0.70，scales 4 档）
- **现象**: 对每个 scale 全图 `matchTemplate` 后 `np.where(result >= threshold)`，低阈值在平坦区可产生数万点，再构造 `MatchResult` 列表，内存与排序尖峰，帧时间抖动。
- **根因**: 多命中扫描未做峰值抑制（非极大值）即物化所有过阈像素。
- **加固建议**: 用 `cv2.minMaxLoc` 迭代掩膜、或 `result` 上高斯+局部峰值；限制每模板每尺度最多 K 个峰值再进 IoU；skills/cards 目录名数量上限。

### 12. `match_any`/`match_one` 无 ROI，场景门闩仍全屏多尺度
- **文件:行号**: `matcher.py:64-102`, `240-266`; `mediator.py:346-358`（L0 门闩 scales 最多 5 档）
- **现象**: ROI 只存在于 `match_all`；`find_scene` 对 lobby/room/stage 等全屏 × 多模板 × (0.9..1.2)。`_detect_context` 一帧内串行多次 `find_scene`，放大开销。
- **根因**: API 能力不对称；context 分类未共享中间结果（仅有 scene_cache 按 scene_key，仍各跑各的 matchTemplate）。
- **加固建议**: `match_one/match_any` 增加与 `match_all` 相同的归一化 ROI；L0 按钮类模板加经验 ROI；context 分类改为“一次特征提取 / 短名单”。

### 13. L1 关键字过宽（`KK`/`single`/`troubl`）误锚定窗口
- **文件:行号**: `capture.py:59-60`, `328-424`
- **现象**: `L1_WINDOW_KEYWORDS` 含泛化子串；`allow_fallback` 或空关键词时 fallback 合并 L0+L1。可能标到无关窗口（标题含 single/KK 的工具），后续输入校验若同进程多窗仍可能放行。
- **根因**: 关键词召回优先，精确 exe/class 约束不足（虽采集了 exe/class 但 rank 几乎不用）。
- **加固建议**: rank 强依赖 `exe` 白名单（平台/游戏进程名）；`single`/`troubl` 仅作二次加分；fallback 必须 `allow_fallback=True` 且打告警。

### 14. SendInput 结构体/`dwExtraInfo` 与返回值未校验
- **文件:行号**: `keyboard_mouse.py:414-420`, `486-519`, `403-465`
- **现象**: `dwExtraInfo` 声明为 `POINTER(c_ulong)` 而非 `ULONG_PTR`/`c_size_t`；`SendInput` 返回值丢弃；失败时（UIPI 已在上层拦，但仍有句柄/桌面切换失败）上层报 SUCCESS。
- **根因**: ctypes 布局习惯性写法 + 无 `GetLastError` 路径。
- **加固建议**: 统一 `ULONG_PTR = ctypes.c_size_t`；检查 `SendInput==1`，失败返回 `CANCELLED_SENDINPUT_FAILED`；`SetCursorPos` 失败同样处理。

### 15. 剪贴板写入失败可清空用户剪贴板
- **文件:行号**: `keyboard_mouse.py:119-137`
- **现象**: `OpenClipboard` 成功后 `EmptyClipboard`，随后 `GlobalAlloc`/`SetClipboardData` 失败则返回 False，用户原内容已空。
- **根因**: 先清空再提交，无事务。
- **加固建议**: 先 Alloc+填好再 Open/Empty/Set；失败尽量写回 `saved`；`paste_text` 失败不要 `pyautogui.write` 默默改通道（行为不一致）。

---

## P2 一般

### 16. 急停仅 Shift+F12 轮询，无 RegisterHotKey，依赖 GetAsyncKeyState
- **文件:行号**: `emergency_stop.py:14-42`
- **现象**: 50ms 轮询；部分全屏/独占输入法/游戏可能吃掉键状态；无线程异常上报。
- **加固建议**: `RegisterHotKey` + 隐藏消息窗；失败再回退轮询；listener 异常记日志。

### 17. `activate_window` TOPMOST 闪烁与 AttachThreadInput 失败静默
- **文件:行号**: `capture.py:427-474`
- **现象**: `HWND_TOPMOST`→`NOTOPMOST` 可能导致 z-order 闪烁；Attach 失败仍 SetForeground，返回值仅比 fg==target。
- **加固建议**: 记录 attach 成败；失败时增加 `AllowSetForegroundWindow` 或短暂重试；避免无条件 TOPMOST。

### 18. `is_window_valid` 不含挂起/不可见客户区
- **文件:行号**: `capture.py:209-219`
- **现象**: 仅 `IsWindow+IsWindowVisible+not IsIconic`；窗口 hung 或 0 尺寸客户区仍“有效”。
- **加固建议**: 附加 `client_width/height>0`、可选 `IsHungAppWindow`。

### 19. dry_run 与真实路径行为不完全同构
- **文件:行号**: `keyboard_mouse.py:157-158` vs 160-194；`mediator.py:363-371` `_focus_last_window`
- **现象**: dry_run 跳过提权/HWND/前台/遮挡；`_focus_last_window` dry_run 直接 True。dry-run 绿的流程在真跑时被 CANCELLED_* 刷屏，调试信号差。
- **加固建议**: dry_run 增加 `check_only` 模式：跑完校验链但跳过 SendInput，日志打印“将点击/将取消”。

### 20. `Frame.timestamp` 在重计算前打点，OLD_FRAME 易在重 tick 误报
- **文件:行号**: `capture.py:24`, `222-243`; `mediator.py:1792-1800`（已放行 frozen/old）
- **现象**: 多窗捕获+context 若 >5s，health 报 old；虽已放行，仍噪声日志。
- **加固建议**: timestamp 在 `see()` 返回前刷新，或 old 阈值与 `loop_sleep + 捕获预算` 挂钩。

### 21. 冻结检测在正常 loop 下几乎永不触发
- **文件:行号**: `capture.py:256-261`（需 `time_diff >= frozen_threshold_sec` 默认 5s）
- **现象**: tick 间隔通常 ≪5s，`prev_frame` 与当前差 <5s 时不判冻结；真冻结窗口只能靠业务超时。
- **加固建议**: 累积“内容相同”的墙钟时间（state 上 last_change_ts），而非单次两帧间隔。

### 22. standalone `scroll` 依赖 pyautogui 隐式依赖
- **文件:行号**: `keyboard_mouse.py:468-476`
- **现象**: click 已用 ctypes，scroll/key 仍 pyautogui，环境缺依赖时运行期 ImportError；行为与 DPI/后端不一致。
- **加固建议**: scroll/key 同样 SendInput；pyautogui 作可选回退。

---

## 性能与流畅度

| 热点 | 位置 | 量级估计 | 建议 |
|------|------|----------|------|
| 无模板缓存反复 imdecode | `matcher._load_template` | 每 hit 次磁盘+解码 | 进程内缓存 |
| `resolve_template` rglob | `matcher.py:58-60` | 未命中时全树 walk | 启动索引 stem→path |
| 多尺度全屏 matchTemplate | `match_one` × scales；L0 5 档、选择 4~6 档 | O(names × scales × W × H × tw × th) | ROI + 尺度少而精 + 早期打分剪枝 |
| `match_all` np.where 物化 | `matcher.py:336-347` | 低阈值尖峰 | 峰值限制 / NMS |
| 每 tick 多窗 mss | `capture_target` + `with mss()` | 每窗一次初始化+全客户区 copy | 单例 mss；只抓 top-k |
| `_capture_best` 对每窗跑 context | `mediator._frame_signal` | 匹配成本 × 窗数 | 轻量 rank |
| `find_window_targets` 每窗 OpenProcess | `capture.py:366-367` | 枚举期 syscall 多 | 缓存 pid/exe |
| 全帧 mean/std/max 健康检查 | `check_frame_health` 245-253 | 每 tick 3 次全图 reduce | 下采样 1/8 或积分图 |
| `np.array_equal` 冻结比较 | `capture.py:260` | 全图 memcmp | 下采样哈希 / 步进采样 |
| click 固定 ≥270ms sleep | `_send_mouse_click` | 每击阻塞 | 可配置，成功焦点后缩短 |
| `type_text` 每键 50ms | `keyboard_mouse.py:437-439` | 长密码明显停顿 | 批量 SendInput 或缩短间隔 |

**选择面板路径（最重业务）**：`_selection_anchor`（最多 10 名 × 6 尺度）+ `_classify_choice_panel`（多组 × 3 尺度）+ `match_all`（skills/cards 全目录 × 4 尺度 × ROI）。即使 ROI 约 0.52×0.5 帧，目录变大时仍可能回到数百 ms~数 s。应：目录上限、缓存、anchor 命中后再 classify、classify 用按钮 ROI 而非全屏。

**捕获默认策略**：`capture()` 默认 `activate=True`，但 Mediator `_capture_best` 不 activate——正确（避免抢焦点）；须保证 offscreen 帧坐标与健康语义，见 P1-7/8。

---

## 提权 / UIPI / dry_run 一致性

| 项 | 状态 | 位置 |
|----|------|------|
| 真输入前 `IsUserAnAdmin` | 有，Mediator.run + check_can_execute 双闸 | `mediator.py:2158-2171`, `keyboard_mouse.py:160-169` |
| 非管理员行为 | 拒绝真实输入，ERROR 停机（非静默点） | 同上 |
| dry_run 默认 True | 有 | `settings.py` |
| dry_run 跳过 UIPI/HWND | 是（预期），但也不做 check_only 预演 | P2-19 |
| Legacy 无提权闸 | **缺口** | P0-1 |
| UIPI 注释与实现一致 | 是 | `is_current_process_elevated` docstring |

---

## 异常与句柄失效兜底

| 路径 | 现状 | 缺口 |
|------|------|------|
| 多数 user32 封装 | 宽 `except: return 默认` | 可接受，但遮挡检查不应 fail-open（P0-4） |
| mss 异常 | 返回 `is_valid=False` Frame | 无重试；可考虑单次 recreate mss |
| PrintWindow 异常 | 返回 None → 可能 mss 脏帧 | P1-7/8 |
| 窗口枚举异常 | `[]` | OK |
| SendInput/SetCursorPos | 不查返回值 | P1-14 |
| OpenClipboard 失败 | get/set 返回 None/False | paste 密码残留 P0-3 |
| 急停线程 | daemon，stop join 0.5s | OK |
| HWND 失效 | `is_window_valid` 在 check 时拦截 | 动作中窗口销毁不中断已开始的 SendInput |

---

## 输入安全链完整性（结论表）

| 动作 | 急停 | 提权 | HWND 有效 | 前台/同进程 | 点位遮挡 | 事后前台 | 剪贴板安全 |
|------|------|------|-----------|-------------|----------|----------|------------|
| Executor.click/right_click | ✓ | ✓ | ✓ | ✓ | ✓ | ✓（语义有坑） | n/a |
| Executor.scroll | ✓ | ✓ | ✓ | ✓ | **✗ P0-2** | ✓ | n/a |
| Executor.press/hotkey | ✓ | ✓ | ✓ | ✓ | n/a | ✓ | n/a |
| Executor.paste_text | ✓ | ✓ | ✓ | ✓ | n/a | ✓ | **✗ P0-3** |
| Executor.type_text | ✓ | ✓ | ✓ | ✓ | n/a | ✓ | n/a（更好） |
| standalone click (AutoJob) | **✗** | **✗** | **✗** | **✗** | **✗** | **✗** | n/a |
| dry_run 任意 | ✓（仍查 stop） | 跳过 | 跳过 | 跳过 | 跳过 | 跳过 | 跳过 |

---

## 建议修复优先级（供主 agent 实施）

1. **P0**: scroll 遮挡检查；paste 密码必清理；遮挡检查 fail-closed；legacy 禁用真输入或接 Executor。
2. **P1**: 模板缓存；`_capture_best` 轻量排名；match_all 峰值限制；PrintWindow 客户区对齐；SendInput 返回值；post_check 与重试语义。
3. **P2/性能**: mss 单例；健康检查下采样；match_any ROI；冻结累计计时；dry_run check_only。

---

## 审查文件清单

- `src/gamescript/input/keyboard_mouse.py`（全文）
- `src/gamescript/input/emergency_stop.py`（全文）
- `src/gamescript/vision/capture.py`（全文）
- `src/gamescript/vision/matcher.py`（全文）
- `src/gamescript/stop_signal.py`
- `src/gamescript/mediator.py`（see/capture_best/act_*/scroll/paste/health/run/选择面板）
- `src/gamescript/jobs/auto_job.py`（遗留点击路径）
- `src/gamescript/main.py`（legacy 入口）
