# GameScript 下一阶段执行蓝图（速度、识别、稳定性、OCR/ML）

日期：2026-08-11  
适用分支：`codex/ocr-hybrid`  
基线提交：`7bd32b2`  
录屏来源：`C:\Users\10639\Desktop\录屏素材`

## 1. 本轮目标与结论

目标不是只把某一个识别 bug 修掉，而是建立一条可重复验收的工程链路，使系统逐步达到：

1. 游戏内识别和动作流畅度接近原版 1.4.1；
2. 技能、羁绊、宝物等弹窗在模板不充分时可由 OCR 安全兜底；
3. 失败、断线、卡死、面板冲突都能有界恢复或安全停止；
4. 建房、进局、局内、退出、回房、下一局形成可观测闭环；
5. 经过多局实机门禁后，才宣称支持长期无人值守。

当前不能宣称已经达到长期稳定无人值守。主要 P0 缺口是：

- 单次 MAIN_LINE 判断实测约 3.3–8.1 秒，存在 102–314 次 `cv2.matchTemplate` 调用；
- 失败与选择面板并存时，选择面板会否决失败，可能在失败画面继续点卡；
- 失败恢复是无后置确认的三 tick 脚本，且断线走错恢复路径；
- 没有不可续期的单局硬期限，周期性面板动作可能让卡死局永久续命；
- `cycle_num`、跨局连续失败上限、胜负结果没有完整运行时语义；
- 龙珠/秘境等后段主链仍是 Fail-Closed 或未实现；
- OCR 当前 1.45% 准确率主要由错误 ROI 裁剪造成，评测结论暂不可信；
- incident 归档能力虽已实现，但桌面/API/CLI 生产入口没有启用。

## 2. 对原版 1.4.1 的纠偏结论

### 2.1 不应照搬的错误归因

“原版局内选卡快，是因为 UIA InvokePattern 直接点击游戏 CEF 控件”这一结论不成立。

- 大厅、房间名、密码、复选框等局外控件确实适合 UIA；
- 游戏内选卡仍是固定区域截图、OpenCV 模板匹配、坐标鼠标点击；
- 原版也创建了 `InputSimulator`，不能根据某次 Procmon 未见 DLL 加载就断言它从未使用。

### 2.2 原版局内快的可借鉴原因

原版的核心路径更窄：

1. 模板启动时一次载入内存；
2. 只截固定选卡区域；
3. 按配置优先级搜索；
4. 通常只查目标组的第一个模板；
5. 单尺度、固定阈值；
6. 首次命中立即点击并等待模板消失，不继续扫全库。

我们的主要性能问题不是磁盘读取，而是同一帧反复进行彩色、多模板、多尺度、大面积扫描。优化方向应是“缩小搜索空间、复用同帧证据、优先级早停”，不是尝试从 CEF 背后读取游戏代码。

### 2.3 原版不应借鉴的行为

- 局内主线失败仍可反复操作几十次；
- 龙珠搜索可持续约 9.5 分钟；
- 没有可靠的局内总预算；
- 失败画面仍可能继续切换卡片。

我们的目标是达到原版速度，但保留更强的 Fail-Closed、重试上限、证据链和 OCR 兜底。

## 3. 当前量化基线

这些数字来自不同审计 harness，只能用于确认数量级。N0 阶段必须用统一基准工具重新生成正式基线，之后不得混用。

| 项目 | 当前观测 |
|---|---:|
| 316 张原图模板解码 | 约 60–146 ms |
| 8 个缩放比例全部生成 | 约 52 ms，约 25.4 MiB |
| MAIN_LINE 变动空闲帧 | 中位约 8.08 s / 314 次匹配 |
| MAIN_LINE 相同静态帧 | 中位约 4.98 s / 173 次匹配 |
| MAIN_LINE 变动技能帧 | 中位约 6.20 s / 249 次匹配 |
| `_post_game_state` 正常 HUD miss | 约 1.67 s / 30 次全屏匹配 |
| `_selection_anchor` | 约 0.985 s / 60 次 ROI 匹配 |
| anchor 后奖励选择 | 约 1.478 s / 26 次匹配 |
| 匹配耗时占总识别耗时 | 约 98% |
| 当前主循环固定 sleep | 400 ms |
| 鼠标点击内部固定等待 | 约 390 ms |

已知重复计算包括：

- `_detect_context`、`_is_in_game_hud`、`_tick_main_line` 可在同一帧重复查选择锚点；
- `_post_game_state` 每个 MAIN_LINE tick 都做多模板、多尺度全屏 miss；
- 自动主线状态、蓝色按钮、stage fallback 也有重复或全帧预处理；
- `see()` 每 tick 清空 scene cache，直接 `find()`、选择锚点、战后状态没有统一同帧缓存；
- 多窗口捕获时可对每个候选窗口执行完整分类。

## 4. 总体架构原则

### 4.1 感知分层

```text
窗口/阶段锚点
    ↓
固定 ROI + 单主尺度快速检测
    ↓ 命中
模板优先级早停 → 确定性策略 → 后置状态确认
    ↓ 低置信或未知，且强面板锚点成立
OCR/闭集识别 shadow 或 fallback
    ↓ 仍未知
刷新、放弃、关闭或 Fail-Closed（按面板类型）
```

OCR 不得参与全屏轮询，不得直接输出坐标，不得绕过阶段锚点。技能未知时绝不选非预设技能；羁绊和宝物才允许在确定性品质规则下选择兜底项。

### 4.2 决策分层

- 识别层只输出：页面类型、候选槽位、规范名称、置信度、证据；
- `choice_policy.py` 只接受结构化候选并返回有限动作枚举；
- 执行层只接受槽位编号或已验证锚点，不接受模型生成的像素坐标；
- 失败、断线、超时拥有全局抢占权；
- 任一 tick 最多一次输入；每次 UI-changing 输入必须等待画面变化或后置锚点。

### 4.3 Agent 协作规则

- `src/gamescript/mediator.py` 每一波只能有一个 Agent 拥有写权限；
- OCR 评测 Agent 在离线门禁通过前不得修改生产运行时；
- 数据 Agent 不得把相邻视频帧当独立样本；
- 性能 Agent 先交基线，再允许实现 Agent 优化；
- 每个任务独立提交，提交信息包含阶段号；
- 不允许顺手大重构，不增加通用工作流框架；只增加任务需要的最小状态与缓存。

## 5. 执行波次与依赖

```text
Wave 0: N0 正式基线与证据映射
          ├── N1 性能基准/录屏延迟
          ├── O0 OCR 评测可信度修复
          └── D0 录屏会话与素材治理
                         ↓
Wave 1: N2 视觉热路径优化（唯一 mediator/matcher 集成者）
                         ↓
Wave 2: S0 失败/断线/硬期限/Panel FSM（唯一 mediator 所有者）
          └── L0 局外建房 UIA 研究可并行（不同文件）
                         ↓
Wave 3: O1 正确 ROI 重评 → O2 补数据 → O3 OCR 离线门禁
                         ↓
Wave 4: O4 OCR shadow → P0 确定性选择策略 → 分面板 LIVE
                         ↓
Wave 5: G0 龙珠/秘境/黑商等后段状态机（逐功能启用）
                         ↓
Wave 6: R0 多局实机、长稳与发布门禁
```

禁止跳过 O0/O1，直接根据当前 1.45% 报告微调模型；禁止在 N2/S0 未完成时用 OCR 掩盖基础状态机问题。

## 6. 任务包 N0：正式性能与行为基线

### 所有权

- 新增：`tools/benchmark_hot_path.py`
- 新增：`tests/performance/` 下固定基准 fixtures/说明
- 新增：`docs/baselines/N0_*`
- 只读 `mediator.py` 与 matcher，不修改生产行为。

### 实施要求

1. 固定 Python、OpenCV、CPU、分辨率、commit、模板哈希；
2. 对每一帧记录 capture/context/health/decision/action 耗时；
3. 统计 `matchTemplate` 次数与搜索像素总量；
4. 区分 cold、warm-changed、exact-static；
5. fixture 至少包含：空闲 HUD、技能、羁绊、宝物、胜利、失败+面板、giveUp+面板、断线、stage、房间、unknown、黑屏；
6. 用两段录屏建立原版 panel 首次完整可见帧 → 输入发生的 P50/P95，至少 20 个事件；若不能可靠看见输入，标记 `insufficient_evidence`，不伪造结论；
7. 基准输出 JSON 和 Markdown，同一命令可重跑。

### 录屏处理约束

两段 MP4 合计约 89 分钟、4.09 GB。必须顺序处理：

- 先按 1 fps 生成事件索引；
- 只在面板/失败/进退局时间窗按 5 fps 抽帧；
- ffmpeg `-threads 2`，禁止两段视频并行全量抽帧；
- 记录视频 SHA256、时间戳、窗口分辨率、与既有 rec/session 的对应关系；
- 感知哈希去重，相邻静态帧不进入独立样本计数。

### 验收门禁 N0

- 一条命令完成基准并退出码为 0；
- 连续运行 3 次，中位耗时偏差不超过 10%；
- 所有 fixture 都有 expected phase/context；
- 报告含 commit、环境、样本 SHA、P50/P95、匹配次数、搜索像素；
- 原版延迟数字有逐事件证据，或明确判为证据不足；
- 不改变 action ledger，现有测试全绿。

## 7. 任务包 N2：游戏内视觉热路径优化

### 所有权

- 独占：`src/gamescript/mediator.py`
- 独占：`src/gamescript/vision/matcher.py`
- 对应单测/性能测试。

该任务在一个 Agent 内集成，避免 matcher API 与 mediator 使用方式同时漂移。

### N2.1 同帧证据缓存与重复扫描消除

实现最小 `FrameEvidence`：

- 保存 Frame 强引用，不能只用 `id(frame)`；
- 缓存键至少含 names、threshold、适配后 scale、ROI、检测模式；
- 缓存选择锚点、post-game、auto-task、stage rows、通用 `find()`；
- context 只计算一次，传入 phase handler；
- 新 Frame、输入动作、窗口句柄变化、UI scale 变化时失效；
- exact-static 帧可跨 tick 复用只读证据，但任何输入后立即失效；
- 缓存命中不得延续旧帧动作授权。

### N2.2 缩小搜索空间

- 战后、挑战、退出、stage 等模板全部先按已知位置裁 ROI；
- `find_blue_buttons` 在进入 HSV/形态学前先裁 ROI；
- 热路径只用 session 校准的主尺度；
- 主尺度 miss 后最多尝试一个相邻尺度；
- 5–8 尺度宽搜仅允许在窗口/分辨率变化、UNKNOWN 恢复或离线标定中使用；
- 按配置优先级查模板，首个满足后置约束的结果立即早停；
- 正常 HUD 不得每 tick 全屏扫描所有战后模板。

### N2.3 捕获与节奏

- 优先捕获上次健康窗口；连续 N 帧不健康才全量重排候选窗口；
- 复用 MSS 实例与窗口元数据；
- health 统计允许降采样，但不能降低失败检测安全性；
- 主循环改成固定 cadence：`sleep=max(0, cadence-elapsed)`；
- 固定点击前后等待只能在输入可靠性实验通过后减少；
- 建议状态节奏：动作/面板后 80–120ms，稳定 HUD 250–400ms，loading 500ms；最终以实测为准。

### 可选 N2.4 灰度候选

仅当 N2.1–N2.3 仍未达标才做：

- 灰度模板与 Frame 灰度结果缓存；
- 先灰度候选，再在候选局部用彩色复核；
- hue 相关检测继续使用彩色；
- 所有旧 fixture 重新标定阈值，不能直接沿用彩色阈值。

### 验收门禁 N2

- cold preload P95 ≤250ms；
- exact-static 非动作 tick P95 ≤75ms；
- changed idle MAIN_LINE P95 ≤400ms；
- 选择面板 decision tick P95 ≤500ms；
- post-victory 识别 P95 ≤250ms；
- 单窗口 capture P95 ≤80ms；
- 生产非 OCR 识别 P95 ≤500ms，无法解释的 tick >1s 为 0；
- 选择 tick `matchTemplate` 调用 P95 ≤20，且搜索像素较 N0 下降至少 80%；
- panel→input P50 不高于原版 1.10 倍，P95 不高于 1.15 倍；如果原版证据不足，则绝对 P95 ≤800ms；
- 每 tick 最多一个输入；所有 replay action ledger 与 N0 预期一致；
- unknown/黑屏/错误窗口零输入；全测试通过。

## 8. 任务包 S0：长期运行安全状态机

### 所有权

- 独占：`src/gamescript/mediator.py`
- 可改：`src/gamescript/settings.py`、默认配置、场景配置与相关测试
- 必须在 N2 合并后开始，不能与 N2 并行改 mediator。

### S0.1 失败与断线恢复

新增最小阶段 `RECOVER_FAILURE`，不要实现通用调度框架。

- `STRONG_FAIL` 只含位置受限、高阈值的 fail/gameFail；
- `AMBIGUOUS_GIVEUP` 单独建证据；
- 强失败连续两帧后必须抢占选择面板；
- giveUp 单独出现且有面板锚点时，不判失败；
- FAIL 与 DISCONNECT 使用不同恢复脚本；
- 每一步只有“锚点出现 + 输入成功 + 画面变化/后置锚点”后才能推进；
- 每动作最多 3 次、间隔至少 1.5 秒、总恢复期限 60 秒；
- 恢复完成后才进入 QUIT，并从那时开始退出期限。

### S0.2 不可续期的预算

- 进入 MAIN_LINE 时设置 `round_deadline`；
- 技能、面板、神器、挑战、进化等动作不得延期 hard deadline；
- 保留 idle watchdog，但与 hard deadline 分离；
- 到期先 QUIT，退出失败再 ERROR；
- 记录 outcome：VICTORY / FAILURE / TIMEOUT / DISCONNECT。

### S0.3 跨局语义

- failure streak 只在确认完整胜利链后清零；
- 默认连续 3 局失败后 ERROR/安全停止；
- `cycle_num > 0` 时，完成指定局数后进入 COMPLETE；
- 达到 cycle_num 后绝不点击下一局开始；
- `game_count` 与 success_count/failure_count 分开记录。

### S0.4 面板会话

只实现内部有限状态：

`CLOSED → OPEN_REQUESTED → WAIT_VISIBLE → ACTIVE → WAIT_MUTATION → CLOSING → COOLDOWN`

- 打开后给 2 秒可见窗口，不得下一 tick 立即反点关闭；
- UI-changing 输入间隔至少 1.5 秒；
- 相同 fingerprint 同动作最多 3 次；
- 每局每类面板会话有上限；
- 强失败/断线在所有 panel state 中均可抢占；
- F1 兜底先只做 shadow，累计 20 次正确触发、0 次误触后才允许 LIVE；每个 panel episode 最多一次。

### S0.5 生产 incident

桌面、API、CLI 创建 Mediator 时都传入 incident 目录。至少保存：

- 动作前帧、动作帧、动作后帧；
- phase/context/evidence/action/attempt/deadline/outcome；
- 关键 ROI 与模板分数；
- 仅在异常、超时、恢复、未知面板或抽样时落图，避免每 tick 写磁盘。

### 必须新增的测试

- `strong_fail_with_panel_preempts_selection`
- `giveup_only_panel_is_not_failure`
- `recovery_does_not_advance_without_anchor_or_success`
- `disconnect_uses_disconnect_path`
- `recovery_exit_timeout_starts_after_recovery`
- `periodic_panel_actions_do_not_extend_round_deadline`
- `three_failed_rounds_fail_closed_and_victory_resets_streak`
- `cycle_num_two_stops_before_third_room_start`
- `panel_waits_for_visibility_before_close`
- `panel_same_fingerprint_has_bounded_retries_and_cooldown`
- `desktop_worker_writes_fail_closed_incident`

### 验收门禁 S0

- 上述测试全部通过，不得 XFAIL；
- fail+panel 连续两帧时选卡输入为 0；
- 缺锚点或点击失败不推进恢复状态；
- 模拟 46.9 秒恢复后仍拥有完整退出窗口；
- 周期面板动作不能延长 round deadline；
- 连续 3 个失败 outcome 后安全停止；
- cycle_num=2 时第三局开始输入为 0；
- ERROR/超时/恢复均产生完整 incident；
- 未识别状态和缓存陈旧状态零输入。

## 9. 任务包 O0/O1：修复 OCR 评测可信度

### 已确认问题

当前不能把 B2 的 1.45% 当成模型质量结论：

- 52 个正面板中 45 个使用了错误的全局 fallback ROI；
- 许多所谓 name crop 实际是 HUD、卡图或整行说明；
- 正确紧裁的样本中，“光法”“潮汐猎人”已经能识别；
- 两轮推理把同一 155 个槽重复计入准确率分母；
- `MODEL_MANIFEST.json` 当前不是合法 JSON；
- evaluator 没有真实校验 manifest/SHA，直接硬编码 PASS；
- 负面板没有真正进入“不得产生建议”的模型评测；
- 没有裁剪器、评测器、manifest 的自动测试和 OCR 依赖锁。

### 所有权

- `tools/crop_ocr_choices.py`
- `tools/evaluate_choice_ocr.py`
- `models/ocr/MODEL_MANIFEST.json`
- OCR requirements/lock
- OCR fixtures manifest、评测 tests、B2 状态文档
- 不得修改生产 Mediator。

### O0 评测修复

1. 修复 manifest JSON，并在测试中 parse；
2. evaluator 真实计算模型大小、SHA256、license 字段；
3. 报告必须记录 repo HEAD；
4. 每个独立槽位只计一次准确率；重复轮次只统计 latency/稳定性；
5. 按采集 session 留出，输出逐 session 指标；
6. 词典外 truth 单独计 unknown，不得被错误规范化；
7. 真实负面板必须运行触发/分类/建议链，期望建议数为 0；
8. 固定可重建的 OCR 依赖锁。

### O1 ROI 修复

- 每种已验证布局使用显式 panel/slot/name/progress bbox；
- name 与 progress 必须分别紧裁；
- 未知布局禁止静默使用全局 fallback，进入 `unverified_layout`；
- manifest 保存每个槽最终生效 bbox、来源帧、分辨率、session；
- 对当前全部 52 个正面板做 100% crop contact sheet 人工审核；
- 人工审核不是只看文字标签，而是确认 crop 中确实包含目标名称/计数器且不过多包含卡图/HUD。

### 验收门禁 O0/O1

- manifest 可解析，篡改任一模型字节后 hash gate 必须失败；
- accuracy 分母等于独立 valid slots，不因 rounds 倍增；
- repo_head 非空且等于当前提交；
- 所有负面板实际经过推理并且建议数为 0；
- 52/52 面板 crop 审核通过或明确移出有效集；
- 每个有效槽有显式 bbox；`unverified_layout` 不进入准确率分母；
- evaluator/cropper/manifest 定向测试全绿；
- 重评完成前不写“模型域失配”结论。

## 10. 任务包 D0/O2：素材治理与补数

### 当前数据事实

- skill 16、bond 18、treasure 18、negative 37 个面板；
- 52 个正面板、155 个 valid 槽、7 个正样本 session；
- rec5 单 session 占 29/52，分布偏斜；
- 正样本 960×540 为 0；
- 距当前最低门槛还差 skill 14、bond 12、treasure 12；
- 每类还需要至少 10 个 960×540 正面板；
- 19 个槽位 truth 尚不是词典规范名，需要纠正或标 unknown。

### 实施要求

- 先映射两段新录屏与既有 session，禁止重复导入；
- 以 panel episode 而非帧为采样单位；
- 同一面板静止持续期间只保留一份主样本，可另留 jitter 但不得当独立训练/验证事件；
- train/validation/test 按视频/session 切分；
- 每个样本记录 phase、panel_type、resolution、bbox、truth、来源时间戳、标注人/规则、SHA；
- 先从现有 1920×1080 桌面录屏中补真实游戏窗口素材；
- 960×540 正面板缺口需后续一次专门实机采集，不能通过缩放伪造为“真实 960×540”。

### 验收门禁 O2

- 每类 ≥30 个正面板；
- 每类至少 2 个采集 session；
- 每类真实 960×540 ≥10 个；
- 实际进入推理的真实负面板 ≥20；
- session 之间无近重复泄漏；
- 任一 session 不占正样本总量的 40% 以上；
- 所有 truth 是规范词典项或显式 unknown。

## 11. 任务包 O3/O4：OCR 离线门禁与 shadow

### O3 模型选型顺序

1. 先用修复后的紧裁 ROI 重新评估 mobile OCR；
2. mobile 仍失败时，先比较有限词典模板/特征检索基线；
3. 只有 ≥1000 个独立、紧裁、session 隔离的文字行后，才允许微调 mobile recognizer；
4. 当前 server 模型因单槽 P95 约 2.0 秒、三槽约 5.6 秒、RSS +615 MB，默认淘汰；
5. 不引入本地 LLM/VLM/端到端视觉代理。

### O3 离线门禁

- held-out Top-1 ≥95%；
- skill recall ≥99%；
- progress exact match ≥95%；
- 错误规范化为 0；
- 负面板产生建议为 0；
- 单槽 P95 ≤120ms；三槽 P95 ≤300ms；
- 首次加载 ≤4s；RSS 增量 ≤800MB；
- 断网环境启动、推理正常；模型 SHA/大小/license gate 全通过。

### O4 shadow 实施

- 只在强面板锚点成立、模板低置信或 unknown 时 lazy 调用；
- 使用持久进程或真正的 JSONL sidecar，不能每槽启动一个 Python 进程；
- request 含 frame/session/panel/slot/bbox/id，response 仅含规范候选、置信度、耗时；
- 超时、崩溃、坏 JSON、模型缺失都返回 unavailable，不阻塞核心 FSM；
- 缓存只绑定当前 panel fingerprint；画面变化立即失效；
- shadow 只写 trace，不影响任何动作。

### 验收门禁 O4

- `ocr_mode=off` 与 B0/N2 action ledger 完全一致；
- `ocr_mode=shadow` 与 off action ledger 完全一致；
- shadow 三槽端到端 P95 ≤400ms，超时不会把主 tick 拉到 >1s；
- sidecar 连续 10,000 请求无泄漏、无僵尸进程、无协议错位；
- 模型不存在/损坏/断网/进程崩溃时核心模板路径正常运行；
- PyInstaller 主 EXE 不强行打包 Paddle；sidecar 独立版本、哈希与回滚。

## 12. 任务包 P0：确定性选择策略与分面板上线

新增纯函数 `choice_policy.py`，禁止读取屏幕、点击或维护隐式全局状态。

### 技能

- 仅选择用户预设技能；
- 预设不存在时刷新；
- 刷新耗尽仍无预设时放弃/关闭；
- 永不选择非预设技能，因为只有 4 个技能槽；
- 技能学习优先于羁绊、宝物等常规循环。

### 羁绊

- 用户预设优先；
- 接近合成者优先；
- 没有预设/合成候选时才按品质和确定性规则降级；
- unknown 不得冒充词典内羁绊。

### 宝物

- 用户预设和套装进度优先；
- 无匹配时按配置品质序降级；
- 龙珠等套装进度必须来自可验证字段；
- 无安全候选时允许刷新/放弃，禁止无限等待。

### 分阶段 LIVE

1. 技能 fallback；
2. 羁绊；
3. 宝物；

三类不得同时首发。每类先 shadow ≥100 个 panel episode，再 supervised LIVE ≥30 个 episode，错误点击为 0 才进入下一类。

### 验收门禁 P0

- policy 单测覆盖预设、unknown、刷新耗尽、品质降级、套装进度、并列优先级；
- 同一输入始终返回同一结果；
- 返回值只能是有限动作枚举和 slot index；
- 技能非预设点击数为 0；
- unknown 直接点击数为 0；
- 每个 panel episode 有尝试上限和总期限；
- 所有 LIVE 选择都能由 trace 还原“候选→规则→动作→后置确认”。

## 13. 任务包 L0：局外建房与多局闭环

局外可继续采用 UIA 语义控件，这是与局内视觉识别分开的链路。

### 研究顺序

1. 对战平台主窗口、房间窗口、地图页建立稳定窗口身份；
2. 导出 UIA tree：控件名、AutomationId、ControlType、Invoke/Value/Toggle pattern；
3. 映射创建房间、房间名、密码、地图、关卡、开始游戏、退出回房；
4. UIA 不可用时才使用固定 ROI 视觉 fallback；
5. 每一步都要求后置页面/字段值确认；
6. room name、password、stage 以“读取回值/页面证据”为准，不能以点击完成为准。

### 验收门禁 L0

- 20 次只建房不进局 dry-run：房名/密码/地图/关卡正确率 100%；
- 关卡配置 1-15 时，读回和进入画面均不得为 1-16；
- UIA selector 在窗口移动、DPI 变化后仍有效；
- 找不到控件时 30 秒内 Fail-Closed，零盲点连击；
- 完成指定 cycle_num 后不再创建新房；
- 每次建房都有 UIA selector、值、截图和耗时 trace。

## 14. 任务包 G0：龙珠、秘境、黑商与后段链路

这部分必须逐项开发、逐项启用，不能一次性打开。

建议顺序：锚点 Boss → 龙珠 → 退出/回房 → 秘境 → 传家宝 → 黑商/装备使用。

### 龙珠最低状态机

- 只从已验证锚点 Boss 后进入 LONGZHU；
- 不可刷新总期限默认 300 秒；
- 扫描节奏约 9 秒，不得每 tick 高频点；
- 失败/断线立即抢占；
- 到期无条件 QUIT；
- 面板动作不得延期 LONGZHU deadline；
- legacy `LongzhuJob` 在修复不存在的 `find/click_match` 调用前不得启用。

### 每个新后段模块的通用门禁

- 至少 10 个真实正 episode、20 个 hard negative；
- replay 召回 100%，误动作 0；
- supervised LIVE 连续 5 次成功；
- 有独立 deadline、attempt budget、退出路径、incident；
- 关闭功能开关时 ledger 与上一个稳定版本等价。

## 15. 任务包 R0：实机长稳与发布门禁

### R0.1 回放

- 所有历史 bug fixture 必须进入回归集；
- fail+panel、giveUp+panel、存档挑战、主线 HUD、stage、退出确认必须有独立场景；
- 960×540 与 1600×900 游戏窗口都覆盖；
- off/shadow 功能开关组合进行 ledger diff。

### R0.2 实机分级

1. S1：监督运行 3 局，错误输入 0，闭环 3/3；
2. S2：无人值守 10 局或 ≥2 小时，不卡死、无人工救场；
3. S3：至少两个独立 session，累计 30 局或 ≥6 小时；
4. S4：人为制造失败/断线/unknown，验证恢复或安全停止。

### 最终发布门禁

- 正常局建房→进局→主线→后段→退出→回房闭环成功率 ≥95%；
- 任何错误点击、失败画面继续选卡、关卡串位均为 0；
- 无状态停滞超过 60 秒；超过期限必须有明确 recovery/QUIT/ERROR；
- 连续 3 局失败自动停止；cycle_num 精确停止；
- 单局 hard deadline 和每个面板 deadline 均不可被动作续期；
- 核心进程无崩溃，内存增长斜率 ≤50MB/小时；
- CPU/IO 报告无持续异常峰值，录屏抽帧不得与实机压测并行；
- EXE、sidecar、模型、配置均有 SHA 和一键回滚版本；
- README 明确列出已支持和默认关闭模块；
- 只有通过 S3/S4 后，才能对用户表述“支持长期多局无人值守”。

## 16. 后续 ML 路线（不进入当前主链）

### OCR/闭集识别

若正确 ROI 下通用 OCR 仍不够：

1. 先做规范化模板/特征检索；
2. 再评估轻量 ONNX 闭集分类或 embedding 检索；
3. ≥1000 个独立文字行后再微调 mobile OCR recognizer；
4. 模型必须支持 unknown rejection；
5. 模型永不拥有直接点击权。

### 偏好学习

用户习惯学习至少等待：

- ≥1000 个独立选择事件；
- ≥100 局；
- session 留出命中率 ≥80%；
- 相对确定性基线提升 ≥5 个百分点。

即使达到门槛，也只能做候选排序，不得决定失败恢复、退出、技能非预设选择或点击坐标。用户偏好配置必须可查看、可编辑、可关闭、可一键清空。

## 17. 给执行 Agent 的总指令（可直接复制）

```text
你在 GameScript-Local 的 codex/ocr-hybrid 分支执行任务。

必须先完整阅读：
1. docs/NEXT_STAGE_EXECUTION_BLUEPRINT_20260811.md
2. docs/ORIGINAL_1_4_1_LIVE_ANALYSIS_20260810.md
3. docs/OCR_HYBRID_AUTOMATION_BLUEPRINT_20260810.md
4. 当前任务涉及的源码与测试。

工作规则：
- 只执行我分配的一个任务包，不顺手重构其它模块。
- 你不是独自在代码库中工作，不得回退或覆盖他人的修改；发现交叉改动立即适配或报告。
- 严格遵守任务包的文件所有权。mediator.py 同一波只有一个 Agent 可写。
- 先输出 baseline/失败测试，再实现；不得删除、放宽或 XFAIL 测试来过门禁。
- 所有识别结论必须有 fixture、trace 或量化报告；不得以“感觉更快/更准”验收。
- 任一 tick 最多一个输入；unknown、错误窗口、黑屏、陈旧缓存不得获得动作权。
- OCR 在 O3 前不得进入生产运行时，在 O4 只允许 shadow；模型不得输出点击坐标。
- 新动作必须有锚点、后置确认、最大尝试次数、总期限和 incident。
- 保持默认 Fail-Closed；实验功能默认关闭并可回滚。
- 运行相关定向测试和完整测试；报告命令、通过数、性能 P50/P95、ledger diff、未解决风险。
- 单独提交本任务，提交信息以任务包编号开头，例如“N2: cache per-frame evidence”。

交付格式：
1. 结论：PASS / FAIL / BLOCKED；
2. 修改文件；
3. 实现摘要；
4. 测试与原始命令；
5. 验收表逐项证据；
6. 性能或准确率前后对比；
7. action ledger 差异；
8. 风险、回滚方式、下一任务的前置条件；
9. commit SHA。

如果任一硬门禁失败，停止进入下一阶段并保留证据，不得用文档措辞把 FAIL 改写成 PASS。
```

## 18. 推荐任务分配表

| 顺序 | Agent 代号 | 任务 | 独占文件/责任 | 可否并行 |
|---:|---|---|---|---|
| 1 | PERF-BASE | N0 基准与原版录屏延迟 | benchmark、baseline docs | 可与 OCR-EVAL、DATA 并行 |
| 1 | OCR-EVAL | O0/O1 评测与 ROI 可信度 | OCR tools/manifest/tests | 可与 PERF-BASE 并行 |
| 1 | DATA | D0 素材映射、去重、session 切分 | fixtures manifest/标注 | 可与前两者并行，禁止同时重抽两视频 |
| 2 | RUNTIME | N2 热路径 | mediator + matcher，唯一所有者 | 不与其它 mediator 任务并行 |
| 3 | STABILITY | S0 安全状态机 | mediator/settings/scenes | N2 合并后独占 |
| 3 | LOBBY | L0 UIA 局外链路研究 | desktop/lobby adapter/tests | 可与 STABILITY 并行，但不得改 mediator |
| 4 | OCR-MODEL | O2/O3 补数与离线模型 | OCR dataset/model/eval | O1 后 |
| 5 | OCR-RUNTIME | O4 shadow | OCR adapter/sidecar + 最小接线 | S0 与 O3 后 |
| 6 | POLICY | P0 纯规则与分面板 LIVE | choice_policy/tests + 接线 | O4 shadow 达标后 |
| 7 | POSTGAME | G0 后段状态机 | 每次只启用一个模块 | 必须有对应真实 fixture |
| 8 | RELEASE | R0 回放、实机、长稳、发布 | reports/release config | 所有目标模块完成后 |

## 19. 第一轮应立即下发的三条任务

### 给 PERF-BASE

执行 N0。不要优化生产代码。统一复现当前 3.3–8.1 秒数量级，建立可重复 benchmark，并顺序分析 `C:\Users\10639\Desktop\录屏素材` 两段视频中的至少 20 个 panel→input 事件。交付 JSON/Markdown 基线与后续 N2 可自动判定的性能门禁。

### 给 OCR-EVAL

执行 O0/O1。第一目标不是提升准确率，而是证明每个评测 crop 和分母可信。修复 manifest/hash/repo_head/重复分母/负面板推理；为每个已验证布局做紧裁 ROI；生成 52 个面板 contact sheet 并逐一审核。完成前不得把 1.45% 解释为模型失败。

### 给 DATA

执行 D0。对两段录屏建立 SHA、session 和既有素材映射，按事件窗口顺序抽帧并感知去重；不重复导入已存在 rec；输出数据缺口表。不要把桌面 1920×1080 视频缩放成“真实 960×540”正样本。

第一轮三项全部 PASS 后，才下发 N2 给 RUNTIME。这样能避免一边修改算法、一边改变基准和样本定义，最终无法证明到底提升了什么。
