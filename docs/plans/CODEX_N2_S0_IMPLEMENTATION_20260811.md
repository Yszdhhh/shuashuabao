# CODEX N2/S0 实现细则（2026-08-11）

**目标：** 在 `codex/ocr-hybrid` 上把 N0 已冻结基线转化为两份可施工、可验收的工作包：N2 消除局内视觉热路径的重复和宽搜；S0 让失败、断线、超时、面板与跨局运行全部 Fail-Closed。

**边界：** 本文件是施工细则，不修改任何生产代码。执行顺序严格为 **N2 合并且 N0 对比/ledger 全绿 → S0 独占 `mediator.py`**。不要引入通用工作流框架、OCR 运行时或坐标生成；每 tick 至多一个输入，未知/黑屏/错误窗口零输入。

**基线与判定约定：**

- N0 JSON schema `N0-benchmark-v1` 是 N2 唯一性能基线；保持 `match_calls`、`search_pixels`、每 fixture/mode 的 `capture_ms`、`health_ms`、`context_ms`、`decision_ms`、`action_ms` 字段及 fixture id 不变。
- 基线：changed idle MAIN_LINE P50 **9.49 s / 410 次 / 250.6M px**；exact-static **6.40 s / 273 次**；skill panel decision **4.73 s / 241**；victory **3.31 s / 206**；fail panel **6.60 s / 244**；unknown **10.60 s / 441**；capture P95 **27.1 ms**。原版 panel→input 的可测 143 事件为 P50 **0.8 s**、P95 **2.8 s**。
- 原版 panel→input 已有可靠事件证据，因此 N2 使用更严绝对门槛 **P95 ≤800 ms**；同时保留相对统计作为观察项（P50 ≤0.88 s，P95 ≤3.22 s），绝对门槛冲突时以绝对门槛为 PASS/FAIL 判据。
- N2 结束前执行 `tools/benchmark_hot_path.py` 三次、`tools/compare_ledger.py`（OCR off）及相关 `unittest`；报告每项 P50/P95、调用数、像素数与基线差。不可将 action ledger 归属或基准 fixture 改给 OCR/DATA。

---

## 文件与责任地图

| 工作包 | 修改文件 | 新增/调整测试 | 不可改/契约 |
|---|---|---|---|
| N2 | `src/gamescript/vision/matcher.py`、`src/gamescript/mediator.py`、必要的 `tests/test_multiscale_matcher.py`、`tests/test_ui_scale.py`、`tests/performance/test_benchmark_smoke.py` | matcher 契约、同帧缓存、节奏和 benchmark schema 回归 | `tools/benchmark_hot_path.py` 统计口径；无 OCR 接入 |
| S0-① | `config/scenes.json`、`src/gamescript/scenes.py`（仅场景加载支持新 key 时） | 场景配置/加载单测 | `giveUp` 不得再进入强失败模板集合 |
| S0-②～⑥ | `src/gamescript/mediator.py`、`src/gamescript/settings.py`、对应 mediator/replay 测试 | 新建 `tests/test_s0_safety_state_machine.py`；复用 `FakeClock`/`FakeInputExecutor` | S0 独占 mediator；不得和 N2 并行 |
| S0-⑦ | 生产入口（仓库根 `desktop_app.py`、CLI/API 构造 Mediator 的实际入口）、`src/gamescript/incidents.py`（仅 schema/ROI 支持不足时）、`tests/test_desktop_app.py`、`tests/test_incident_archiver.py` | incident 落图与 metadata 端到端 | 正常每 tick 不落图；敏感设置不得归档 |

现有锚点：`Mediator.see()` 每 tick 清空 `_scene_cache`；`_detect_context()`、`_is_in_game_hud()`、`_tick_main_line()`可在同一帧重复扫描；`match_any_with_margin()`目前扫描全部 names 并排序；`match_one()`扫描全部 scale；`find_blue_buttons()`先全图 HSV 再 mask ROI；`_tick_impl()` 2707–2755 的失败处理会在有 selection anchor 时忽略 fail；`_recovery_step` 当前无成功门闩；`Settings.cycle_num` 存在但运行时零引用。

---

# N2：游戏内视觉热路径优化

## N2.1 Matcher API：优先级早停、主尺度与 ROI

### 设计原则

1. **默认保持兼容。** 现有 `match_any()` 和全局 best-score 的 `match_any_with_margin()` 语义不因未选择新模式而变化。
2. **早停是显式模式。** 只有调用者明确说明 `early_stop=True` 且不要求跨全部候选的 margin 时，才按 names 的配置顺序返回首个达到 threshold 的 hit。
3. **margin 不被伪造。** 提前停止意味着未扫描的候选不能成为 `second_best`；结果必须显示这是局部比较，不得以 `best.score` 冒充全局 margin。
4. **热路径只试主尺度与一个邻域。** 宽尺度只保留给 hwnd/尺寸变化、UNKNOWN 恢复和离线校准，不得成为正常 HUD/面板每 tick 默认。
5. **ROI 是语义前置条件。** 战后、挑战、退出、stage、蓝色按钮均由各页面的已知位置限制搜索，而不是命中后再用坐标过滤。

### 建议 API（函数签名）

```python
@dataclass(frozen=True)
class MatchSearch:
    names: tuple[str, ...]
    threshold: float = 0.85
    primary_scale: float = 1.0
    neighbor_scale: float | None = None
    roi: tuple[float, float, float, float] | None = None
    early_stop: bool = False
    min_margin: float = 0.0

@dataclass
class MatchMarginResult:
    best: MatchResult | None
    second_best: MatchResult | None
    margin: float
    compared_all: bool  # False only when early_stop returned before names exhausted


def preferred_scales(primary_scale: float, neighbor_scale: float | None = None) -> tuple[float, ...]: ...

def match_one(
    frame: Frame, template_path: Path, threshold: float = 0.85,
    name: str | None = None, scales: tuple[float, ...] = (1.0,),
    *, early_stop_scale: bool = False,
) -> MatchResult | None: ...

def match_any_with_margin(
    frame: Frame, images_dir: Path, names: list[str] | tuple[str, ...],
    threshold: float = 0.85, scales: tuple[float, ...] = (1.0,),
    min_margin: float = 0.0, roi: tuple[float, float, float, float] | None = None,
    *, early_stop: bool = False,
) -> MatchMarginResult: ...

def match_any(..., *, early_stop: bool = False) -> MatchResult | None: ...

def match_scenes(
    frame: Frame, images_dir: Path,
    scene_searches: list[tuple[str, MatchSearch]],
) -> tuple[str, MatchResult] | None: ...
```

`MatchSearch` 是一个小值对象，不引入 registry 或 factory。`preferred_scales()` 的输出按 `(primary, neighbor)` 去重、保序、夹在支持区间；通常 `primary=self._ui_scale`，邻域是该比例最近的一个校准档。`match_one(..., early_stop_scale=True)` 按尺度顺序在第一个达到 threshold 的 scale 返回；否则保留当前“全 scales 取最高分”行为。

### 早停与 margin 的精确定义

| 调用模式 | 扫描 | `best` | `second_best`/`margin` | 允许用于动作？ |
|---|---|---|---|---|
| `early_stop=False` | 全 names × scales | 全局最高分 | 当前完整语义，`compared_all=True` | 可，按既有阈值/margin |
| `early_stop=True, min_margin==0` | 按优先级；首个过阈值即返回 | 首个满足阈值的模板 | `None` / `best.score`，`compared_all=False`；此值仅诊断，非全局 margin | 可，前提是场景锚点和后置确认已有 |
| `early_stop=True, min_margin>0` | **禁止早停，自动转全扫描** | 全局最高分 | 完整 margin | 可 |

这样不会使已有依赖 `min_margin` 的判别悄悄失去歧义检测。实现应记录 `early_stop` 和 `compared_all` 至 `_trace_scenes`，让性能和安全诊断能识别搜索模式。

### `find_blue_buttons()` 修订

保留函数签名，改内部顺序：先计算并 clip ROI 坐标；`bgr = frame.bgr[y1:y2, x1:x2]`；仅对这块做 `cvtColor`、`inRange`、形态学和 contour；将 contour 坐标加回 `(x1,y1)`。`roi=None` 才允许全图。空/退化 ROI 直接返回 `[]`。保持 `MatchResult` 的 `x/y/screen_x/screen_y` 都是原 frame 坐标，保持 `find_blue_button()` 调用方无须变更。

### 场景级 `match_scenes()`

替换当前 `list[tuple[str, list[str]]] + 默认全扫描` 的窄接口。每个场景携带自己的 threshold、ROI、主/邻尺度和早停策略，按场景列表优先级搜索；命中场景后停止后续场景。它不是全局场景分类器：只给 `_post_game_state`、退出、挑战、stage 等已经知道候选集合的热路径使用。`disconnect`、`STRONG_FAIL` 的高优先级检测不因主线早停被跳过。

### 调用方适配点

| 位置 | 改法 |
|---|---|
| `Mediator._selection_anchor`、`_find_reward_choice`、`_close_current_panel` | 传固定 selection ROI、`preferred_scales(self._ui_scale, neighbor)`；偏好卡按用户设置顺序 `early_stop=True`，多卡收集仍用 `match_all`，不得错误早停 |
| `_post_game_state` | 用 ordered `match_scenes` 或等价小 ROI searches；每个页面的唯一锚点先查，避免每 tick 全屏 6+ 模板 ×3 scale |
| `_find_game_exit`、`_find_exit_confirm`、挑战、stage 行/按钮 | 页面锚点已知时传其 ROI；仅 UNKNOWN/scale 变更触发广搜 |
| `_detect_context` 与 `_is_in_game_hud` | 不自行宽搜；读取当 tick 的 `FrameEvidence` 结果 |
| 现有无 margin 安全需求的 `find()` | 保持默认，逐处审查后才 opt-in early stop；不可全局改默认 |

### N2 matcher 测试

在 `tests/test_multiscale_matcher.py` 新增：

- `test_early_stop_returns_first_configured_threshold_hit_and_marks_partial_margin`：两个都命中时返回 names 顺序第一个，`compared_all=False`。
- `test_margin_request_disables_early_stop_and_keeps_second_best`：`min_margin>0` 时扫描到第二名并按当前 margin 拒绝/接受。
- `test_primary_scale_hit_skips_neighbor_and_later_scales`、`test_primary_scale_miss_tries_exactly_one_neighbor`。
- `test_find_blue_buttons_converts_only_roi_and_returns_global_coordinates`：patch `cv2.cvtColor` 的输入 shape，验证只处理 ROI 且坐标回映正确。
- `test_match_scenes_respects_scene_priority_and_scene_specific_roi`。

## N2.2 FrameEvidence：同帧证据、失效与动作授权

### 数据模型

在 `mediator.py` 添加最小私有 dataclass，不另起通用缓存模块：

```python
@dataclass
class FrameEvidence:
    frame_ref: Frame                 # 强引用；绝不只依赖 id(frame)
    gen: int                         # 单调递增的感知/动作世代
    ui_scale: float
    hwnd: int | None
    cache: dict[tuple[object, ...], object] = field(default_factory=dict)
    context: str | None = None
```

`cache` key 必须规范化为：

```python
(
    "scene" | "match" | "anchor" | "post_game" | "blue" | "stage_rows" | "auto_task",
    tuple(names), threshold, scales, roi, mode_key,
)
```

其中 `mode_key` 区分 `early_stop`、`min_margin`、`max_results`、颜色/模板模式和场景后置约束；不能把 margin 搜索与早停结果混用。`names` 使用 tuple，ROI 使用原始 ratio tuple，scales 使用最终适配后的 tuple。

### 生命周期与失效规则

1. 新捕获帧像素/位置不等价于 `frame_ref` 时，创建新 `FrameEvidence`、`gen += 1`。
2. exact-static 可以复用同一个 `frame_ref` 和证据，但仅限 `hwnd`、left/top、width/height、`ui_scale` 都相同。
3. 任一 `act_click`、键盘、滚轮、粘贴等输入 **成功** 后，在输入返回的同一控制流立刻 `invalidate_evidence(reason="input")`：`gen += 1`、丢弃 evidence、清空 context/scene 读缓存。输入失败不授予状态推进，也不把旧缓存转换成新动作授权。
4. 捕获 hwnd 改变、UI scale 改变或 frame 尺寸/位置改变时无条件失效；不得让另一窗口或旧比例命中沿用。
5. frame health 不健康时不创建“可动作”证据；静态/old_frame 放行只复用只读检测，仍受本 tick generation 断言。
6. 每个生成动作的函数接收/读取 `evidence.gen`；在实际调用 `act_*` 前断言 `self._evidence is evidence and evidence.gen == action_gen`。不满足则返回零输入并 trace `stale_evidence`。

**核心不变量：缓存命中不得延续旧帧动作授权。** exact-static 的缓存只减少检测，不为一次旧命中重复点击；动作前的 generation 和 frame 强引用必须仍相同。

### 与 `_scene_cache` 的切换策略

不长期并存两套语义。N2 采用一次清洁切换：`FrameEvidence.cache` 取代 `_scene_cache`、`_context_cache_frame`、`_context_cache_value` 的缓存职责；可保留同名只读兼容属性一小次提交，但最终删除 `see()` 的 `_scene_cache.clear()` 与 `id(frame)` 键缓存。所有 `find_scene()`、`find()`、`_selection_anchor()`、`_post_game_state()`、`_auto_task_state()`、stage rows 都经 evidence 的一个 memoization helper。

迁移期禁止让 `_scene_cache` 命中绕过 evidence generation；若必须短暂保留，`_scene_cache` 只能是 `evidence.cache` 的别名而非独立 dict。性能 benchmark 的 exact-static 行为因此从“每 tick clear 后重扫”转为“同 frame、无输入时复用只读证据”，其动作路径仍由 generation 闸门保护。

### mediator 重复扫描消除清单

| 当前重复点 | N2 后单一证据来源 | 禁止行为 |
|---|---|---|
| `_detect_context` → `_selection_anchor`，接着 `_is_in_game_hud` → `_selection_anchor`，随后 `_tick_main_line` 再查 | `evidence.cache[("anchor", …)]`，一次算出；context 和 handler 复用 | 在同一 evidence 下二次调用底层 matcher |
| `_detect_context` 先 fail/disconnect，`_tick_impl` 再扫，`_post_game_state` 又全屏扫 | 先作全局安全候选，再把结果缓存；page-specific post-game 用 ROI | 面板/主线分支覆盖安全检测 |
| `_post_game_state` 每 MAIN_LINE tick 多模板×多尺度全屏 miss | `("post_game", ui_scale, …)` memo；场景级 ROI/早停 | 正常 HUD 每 tick扫全战后库 |
| `see()` 每 tick 清 `_scene_cache` | evidence 根据 frame/gen 管理 | 静态 frame 因 clear 丢失证据 |
| `_find_reward_choice`、`_close_current_panel`、selection 逻辑各扫 anchor | one anchor cache；派生 panel kind/cache | 重算相同 anchor 或把不同 ROI/key 混用 |
| `_capture_best()` 多窗口逐个 `_frame_signal()` 全分类 | 上次健康 hwnd 先抓；仅连续 `N=2` 不健康/失配后枚举候选；候选先用廉价固定 anchor，再只对最高分做完整 context | 对每个 title-match 窗口执行完整 MAIN_LINE 分类 |

### N2 evidence 测试

新建或扩展 `tests/test_s0_safety_state_machine.py` 的无输入部分（也可先置于 `tests/test_p1a1_main_line_controls.py`）：

- 同一 `Frame` 两次 context/anchor 查询只有一次 matcher 调用。
- exact-static 同 tick/跨 tick可复用检测，但成功 `act_click` 后相同对象再次进入时必须重新计算且动作因 stale generation 被拒绝。
- hwnd 或 scale 改变即使像素相同也清空 evidence。
- 配置差异（threshold/ROI/scales/mode）不命中同一 key。
- 多窗口策略连续一帧失配不触发全量候选分类；第二帧才重选。

## N2.3 Capture 与主循环 cadence

### 运行循环

将固定 `time.sleep(loop_sleep_ms / 1000.0)` 改为按本次 tick 开始计时：

```python
while self._running and not self.stop_signal.is_set():
    started = time.monotonic()
    action = self.tick()
    elapsed = time.monotonic() - started
    if action is LoopAction.Break or stop/max_steps:
        break
    cadence = self._cadence_for_current_state()
    time.sleep(max(0.0, cadence - elapsed))
```

必须用 `time.monotonic()`，不使用 wall clock；deadline 仍可保持 `time.time()` 或统一迁移，但同一次改动不得混用其差值。`_cadence_for_current_state()` 返回有限常量，不读取动态网络或新增设置层：

| 情形 | cadence | 判断来源 |
|---|---:|---|
| 成功输入后、panel `WAIT_VISIBLE/WAIT_MUTATION`、恢复后置确认 | 80–120 ms（默认 100 ms） | 短观察窗；不能成为连续输入许可 |
| 稳定健康 HUD、无待确认动作 | 250–400 ms（默认 300 ms） | 无安全/面板高优先级候选 |
| loading、窗口转场、非静态不健康等待 | 500 ms | 无可动作证据；失败检测的单独高优先级路径仍执行 |
| UNKNOWN、FAIL/DISCONNECT 候选、deadline 临界 | 不放慢到 loading；300 ms 或更快 | 安全检测优先 |

`loop_sleep_ms` 仅作为兼容默认/上限，N2 完成后记录其实际替代语义或删除，避免两个竞争 cadence 配置。

### 点击等待可靠性实验（不先减等待）

鼠标点击当前约含 390 ms 内部等待；在没有实验数据前不得缩短。实验在隔离实机/录屏回放环境进行，分 3 组，每组至少 30 个独立 panel episode，skill/bond/treasure 均有样本：

1. **对照**：现有 InputExecutor 等待 + N2 detection/cadence；记录 input 发送、首个 mutation/close、正确目标、重复输入、Fail-Closed。
2. **候选 A**：仅把动作后主循环 cadence 设 100 ms，不改 executor 内部等待。
3. **候选 B（仅 A 通过才做）**：逐档减少一个固定等待（一次最多 50 ms），其他值不变。

每组采集 `panel_visible_at`、`input_at`、`mutation_at/closed_at`、click target、输入成功结果、frame generation、尝试数。候选只有在以下全部成立时才可上线：零错卡/错按钮、零同一 generation 重复输入、每 episode ≤1 F1、成功率不低于对照、P95 panel→input ≤800 ms、P95 post-input mutation 不劣于对照 10%、无新增 `unknown/health` Fail-Closed。任何失败立刻恢复对照等待；报告保留原始事件 JSON。

## N2 验收映射

| 门禁 | 实现支点 | 验证方法 |
|---|---|---|
| cold preload P95 ≤250 ms | 不改模板预加载模型；避免新增解码/扩尺度 | N0 工具 cold ×3，读 JSON `total_ms.p95`/preload 字段 |
| exact-static 非动作 P95 ≤75 ms | FrameEvidence 跨 tick 只读复用；无动作授权复用 | `exact_static` ×3；断言 action=0、P95≤75 |
| changed idle MAIN_LINE P95 ≤400 ms | ROI + early-stop + 主/邻尺度 + 消除 anchor/post-game 重扫 | `idle_hud/warm_changed` ×3；阶段耗时合计及 P95 |
| 选择 decision tick P95 ≤500 ms | anchor/panel kind复用；偏好顺序早停；card 多命中仅在必需时做 | skill/bond/treasure fixture，记录 `decision_ms` |
| post-victory P95 ≤250 ms | scene-specific ROI + `match_scenes` | victory fixture；额外断言正确 `POST_VICTORY` |
| 单窗口 capture P95 ≤80 ms | 复用 MSS/上次健康 hwnd；N=2 才候选重排 | live capture + 单窗口 replay；报告 `capture_ms` |
| 非 OCR 识别 P95 ≤500 ms | 上述综合；OCR 不在生产路径 | all supported fixtures，排除 capture/action 后计算识别段 |
| 选择 tick matchTemplate P95 ≤20 | matcher 明确早停与单/双尺度；不能仅靠 mediator cache | benchmark counter，按 fixture/tick 分位统计 |
| 搜索像素下降 ≥80% | ROI 裁剪、scale 限制、避免重复扫描 | 同 fixture 比 N0 `search_pixels`，`new ≤ 0.20 × N0` |
| panel→input P95 ≤800 ms | cadence 100 ms + 可靠性实验后才改点击等待 | 录屏/实机 episode JSON；独立于 dry-run benchmark |
| replay ledger 一致、每 tick≤1输入 | generation gate，不改变业务选择策略 | `compare_ledger.py`；FakeInputExecutor 计数 |
| unknown/black/wrong-window 零输入 | health/context gates 在 action 前 | replay tests + action ledger |

### “无法解释 tick >1 s = 0”的可判定白名单

以 tick trace 的 `elapsed_ms` 自动统计；超过 1000 ms 的 tick 必须恰好属于以下之一，并有结构化 reason：

1. `capture_wait`：`capture_ms ≥800`，且 trace 标明候选窗口数量/role；
2. `input_executor_wait`：本 tick 成功执行实际输入，`action_ms ≥800`；
3. `incident_write`：incident 被触发，metadata 写入耗时有字段，且每 episode/采样频率符合 S0.5；
4. `debug_trace_io`：仅显式 debug trace mode，生产默认关闭；
5. `external_pause`：系统睡眠/调试器暂停，有 monotonic gap 标记，不能计为正常性能。

除此之外（matcher、HSV、OCR、排序、缓存 miss、普通 JSON/日志、全窗枚举）均是 **unexplained**。N2 验收脚本计算 `unexplained_tick_over_1s == 0`；任何白名单项需输出数量、最大值、fixture/episode，不允许文字豁免。

## N2 实施顺序与风险

1. 冻结 N0 schema/ledger，先补 matcher unit tests；实现 `MatchSearch`、early-stop、primary+neighbor scale、ROI-first blue HSV、scene API。
2. 在 mediator 引入 `FrameEvidence` 和 generation invalidation，删除而非叠加旧 `_scene_cache` 语义；先改 detect/hud/anchor/post-game，再改多窗口策略。
3. 改 cadence，先做不减少 InputExecutor 等待的可靠性实验；通过才逐档研究等待。
4. 逐次跑 matcher/mediator 定向测试、N0 benchmark、ledger 比较；仅在 N2.1–N2.3 全部完成但门禁仍 FAIL 时评估 N2.4 灰度候选。N2.4 必须离线重标所有 fixture 阈值，色相检测仍留彩色，不得提前实施。

**Top 风险：** (a) early-stop 被错误用于 margin 判别导致歧义动作；以 `min_margin>0` 自动全扫描避免；(b) static evidence 导致重复点击；以 generation 前置断言避免；(c) 缩 ROI 漏掉窗口/比例变化；只在 UNKNOWN/scale/hwnd 改变时允许宽搜恢复；(d) cadence 提速掩盖输入可靠性；以分组实验和零误触门槛避免。

---

# S0：长期运行安全状态机

## S0 全局模型与约束

S0 保持 `Mediator` 单写者，只增加最小状态/计数器。新增 `Phase.RECOVER_FAILURE`，用一个内部 `RecoveryKind`（`FAIL`、`DISCONNECT`）和明确 `RecoveryStep` 表示脚本进度；不要字符串散落地推进。新增 `RoundOutcome`：`VICTORY`、`FAILURE`、`TIMEOUT`、`DISCONNECT`。所有阶段转换记录 `reason`、outcome、deadline，失败/断线/期限拥有面板和主线的全局抢占权。

建议 Settings 的新增安全默认（名称可保持，值必须写入加载的范围校验）：`round_timeout_s`（从进入 MAIN_LINE 起不可续期；默认以现有 game timeout 语义明确换算，不能继续把 `game_timeout=15` 静默当分钟/秒）、`recovery_timeout_s=60`、`recovery_action_limit=3`、`recovery_retry_interval_s=1.5`、`failure_streak_limit=3`、`panel_visible_timeout_s=2.0`、`ui_action_interval_s=1.5`、`panel_action_limit_per_fingerprint=3`、`panel_episode_limit_per_kind`、`incident_sample_rate`。对 `round_timeout_s` 必须在实施前写出 Settings 文档和迁移决定；不得猜测旧 `game_timeout` 单位。

## ① Scenes 拆分：STRONG_FAIL、GIVEUP、DISCONNECT

**修改文件：** `config/scenes.json`；必要时 `src/gamescript/scenes.py`；`tests/test_s0_safety_state_machine.py`/场景加载测试。

**变更：**

- 把现有 `fail.templates = ["fail", "gameFail", "giveUp"]` 改为 `strong_fail`（或保留 key `fail` 但文档/代码常量称 `STRONG_FAIL`）仅 `["fail", "gameFail"]`，使用高阈值、位置受限 ROI。
- 新增独立 `giveup` 场景，仅 `["giveUp"]`，标记为 `AMBIGUOUS_GIVEUP`，没有恢复动作权。
- 保留/明确 `disconnect = ["gameDisconnect", "retryConnect"]` 为独立场景和独立恢复脚本入口；不得与 fail 共用 `click_scene("fail")`。
- 调整 priority：`disconnect`、`strong_fail` 在所有 panel/context 场景前；`giveup` 不进入强失败优先级。
- `scene_templates()`/加载逻辑如假设 `fail` key，改为读取明确强失败 key；不做给旧 key 的隐式别名。

**具名测试与验收：**

- `strong_fail_with_panel_preempts_selection` 的 fixture/patch 证明 fail+panel 同时存在时强失败候选仍被记录。
- `giveup_only_panel_is_not_failure` 证明 giveUp+有效 panel anchor 不进恢复、不变 QUIT、选卡仍遵守 panel FSM。
- 场景配置测试断言 `giveUp not in scene_templates(..., "strong_fail")`，但仍能作为独立 giveup 证据加载。

**风险：** template 名/资产可能与旧场景引用耦合；以加载器单测和全库 `scene_templates` 调用审查消除残留，而非兼容双 key。断线真实 fixture 仍缺失，测试可用合成 matcher 证据验证路径，但 S0 完成前必须补真实断线素材，不能 XFAIL。

## ② 全局抢占：两帧 STRONG_FAIL 优先于 selection/panel

**修改文件：** `src/gamescript/mediator.py`；`tests/test_s0_safety_state_machine.py`；调整 `tests/test_external_review_regressions.py` 的旧恢复期望。

**变更：**

1. `_tick_impl()` 在 health 放行后、context/panel/main-line dispatch 前评估 `disconnect` 与 `STRONG_FAIL`，写入当前 `FrameEvidence`。
2. 每类强证据单独连续帧计数；同 hwnd/scale/evidence generation 下连续两帧才授权抢占。两帧中断即归零；不要把 `giveup` 计入。
3. 到第二帧，先 `invalidate_evidence("failure-preempt")`，再 `set_phase(RECOVER_FAILURE, ...)`；同 tick 不执行 selection、panel、artifact、challenge 或主动开面板输入。
4. 删除/翻转现有 L2732–2738 的“selection anchor 存在就忽略 fail”语义。仅当 **没有 STRONG_FAIL**、只有独立 `giveup` 且 panel anchor 成立时，记录 ambiguous evidence 并继续 panel FSM；giveup 单独出现且无 panel anchor 也只进入未知/安全等待，不得自动判为失败。
5. disconnect 与 strong fail 都能在所有 panel state、MAIN_LINE 和 tail phase 抢占；抢占后清 panel 许可和待输入 token。

**具名测试与验收：**

- `strong_fail_with_panel_preempts_selection`：连续两帧 `strong_fail`+anchor，第二 tick 后 `Phase.RECOVER_FAILURE`，FakeInput action ledger 中 selection 输入=0。
- `giveup_only_panel_is_not_failure`：连续给 giveUp+anchor，recovery state 为 None，`RoundOutcome` 不变。
- 验收 `fail+panel` 连续两帧选卡输入为 0；未知/缓存陈旧状态零输入。

**风险：**把单帧误命中升级为强失败会错退局；故必须是高阈值+ROI+连续两帧，且“连续”不能靠同一输入前 static frame 的旧 generation 重复计数。

## ③ RECOVER_FAILURE：有门闩、分脚本、有限预算

**修改文件：** `src/gamescript/mediator.py`、`src/gamescript/settings.py`、`tests/test_s0_safety_state_machine.py`。

**状态数据：**

```python
@dataclass
class RecoveryState:
    kind: RecoveryKind                 # FAIL or DISCONNECT
    step: RecoveryStep
    started_at: float
    deadline: float                    # started_at + 60 s
    attempts: dict[RecoveryStep, int]
    next_allowed_at: float
    anchor_before: MatchResult | None
    input_ok: bool = False
    mutation_seen: bool = False
    post_anchor_seen: bool = False
```

**门闩：** 一步只能从 `READY` 进入 `WAIT_CONFIRM`，随后只有

```text
anchor_before exists
∧ input result.success
∧ (frame mutation beyond documented threshold ∨ required post_anchor appears)
```

才进入下一步。缺 anchor、input rejected、无 mutation/后置锚点都保留在本步并消耗/等待其有界重试；不可像当前 `FAIL_VISIBLE → WAIT_OK → WAIT_CLOSE` 那样无论 click 成功与否推进。每动作最多 3 次，尝试间隔至少 1.5 s，总恢复 deadline 是开始时固定的 60 s，任何 periodic 行为不得续期。

**两个脚本：**

- `FAIL`：只包含由失败 modal 实际锚点定义的 confirm/close 步；每一步写明 anchor、action、expected mutation 或下一 post-anchor。不要沿用 `click_scene("fail")` 的泛化点击。
- `DISCONNECT`：只操作 disconnect/retry/reconnect 的独立 anchors；不得点击 fail 的 `ok/close`，没有断线 anchor 时零输入等待或超时 ERROR。

恢复确认完毕后，将 outcome 设为 `FAILURE` 或 `DISCONNECT`，再进入 `QUIT`；**此刻**初始化 `_exit_since`/退出 deadline 和退出尝试数。恢复期间的 60s 不侵蚀退出窗口。恢复超时/重试耗尽直接 `ERROR`、停止、写 incident，不能盲目 QUIT。

**具名测试与验收：**

- `recovery_does_not_advance_without_anchor_or_success`：anchor 缺失、`act_click=False`、无 mutation 三个子例均停在同 step、无后续动作。
- `disconnect_uses_disconnect_path`：仅 disconnect anchors 可调用；mock fail action 被断言未调用。
- `recovery_exit_timeout_starts_after_recovery`：FakeClock 让恢复耗时 46.9s，确认 `exit_deadline == recovery_completed_at + exit_window`，不是 `recovery_started_at + …`。
- 验收：每动作≤3、≥1.5s；总恢复60s；恢复完成前 QUIT 输入为0；所有失败路径有 incident。

**风险：**“画面 mutation”阈值过低会把动画噪声当确认，过高会假失败。先以 template 消失/下一 anchor 作为主要证明；全局像素 mutation 仅作并列证据，并用 replay fixture 定标。

## ④ Round hard deadline：进入 MAIN_LINE 即固定

**修改文件：** `src/gamescript/mediator.py`、`src/gamescript/settings.py`、`tests/test_s0_safety_state_machine.py`。

**变更：**

- 首次经连续局内锚点进入 `MAIN_LINE` 时设置 `_round_started_at` 与 `_round_deadline = started + round_timeout_s`；同一局重复 set_phase 不得覆盖。
- `_main_line_since` 继续作为 idle watchdog，可由受确认的正常进展刷新；它不等于 hard deadline。
- 在 MAIN_LINE（包括技能/面板/神器/挑战/进化分支）最早检查 hard deadline；到期先记录 `TIMEOUT`，清 input/evidence token，转 `QUIT`，再由正常退出链处理。退出打开/确认失败才 ERROR。
- 仅在完整胜利链确认、成功回房且开启下一局时清 round 字段；panel 打开、刷新、关闭、artifact、challenge 都不得重置/延期。

**具名测试与验收：**

- `periodic_panel_actions_do_not_extend_round_deadline`：FakeClock 执行多个合法 panel actions 后 deadline object/value 不变；到期走 QUIT，动作不再产生。
- 验收：deadline 到期先 QUIT 后 ERROR；outcome 精确为 VICTORY/FAILURE/TIMEOUT/DISCONNECT；idle watchdog 单独可触发但不能延长 deadline。

**风险：**旧 `game_timeout` 单位不明是 P2 实机风险。实施提交必须先写“旧字段映射决定”和 default，增加 settings load 范围测试；没有决定不允许将其直接接成 hard deadline。

## ⑤ Panel FSM：可见性、间隔、指纹上限与 F1 灰度

**修改文件：** `src/gamescript/mediator.py`、`src/gamescript/settings.py`、`tests/test_s0_safety_state_machine.py`。

**状态：**

```text
CLOSED → OPEN_REQUESTED → WAIT_VISIBLE → ACTIVE → WAIT_MUTATION → CLOSING → COOLDOWN
```

- `CLOSED`：无 active episode；只有稳定 HUD、无强失败/断线/round deadline、且全局输入 token 空闲时可请求打开。
- `OPEN_REQUESTED`：成功按 G/F/V 后立即失效 evidence，记录 kind/attempt/time；不能把“请求”当“可见”。
- `WAIT_VISIBLE`：在固定 2.0 s visible deadline 内仅观察 anchor；锚点出现才进入 `ACTIVE`，未出现则到期进入 `COOLDOWN`（零盲点/盲关闭）。
- `ACTIVE`：从同帧 evidence 得 kind、fingerprint、候选；动作必须有 anchor、generation、且距上次 UI-changing input ≥1.5s。
- `WAIT_MUTATION`：已输入后只观察 mutation/post-anchor；确认后进入 `CLOSED` 或下一明确 state；未确认不得再次选择。
- `CLOSING`：仅对“本 episode 由我们打开且明确 close anchor”的安全关闭；同样需后置 mutation。
- `COOLDOWN`：冻结本 kind 到固定 deadline，清本 episode token；不因为轮询、panel存在或 retry 延长。

`fingerprint` 至少含 panel kind、anchor template/近似位置、关键 ROI 的稳定 hash；相同 fingerprint+同 action 最多 3 次，之后必进 cooldown/Fail-Closed（取决于面板是否阻塞）。同时维护每局每类 `panel_episode_count[kind]`，达到配置上限不再开该类面板。

强失败/断线在所有上述 state 抢占；round deadline 在所有非恢复 state 抢占。F1 兜底不直接 LIVE：记录 shadow candidates（would_trigger、anchor、fingerprint、误触 predicate）；连续累计 **20 正确、0 误触** 才写一个可审计 enable 标志允许 LIVE，且每 episode 最多一次。任何误触将 shadow 计数清零并保持关闭；F1 不得用于 UNKNOWN/无 anchor。

**具名测试与验收：**

- `panel_waits_for_visibility_before_close`：open 成功后首 tick anchor 未见，不点击关闭；2s 内可见才 ACTIVE；2s 到期是 cooldown/zero input。
- `panel_same_fingerprint_has_bounded_retries_and_cooldown`：同 fingerprint/action 第四次被拒、进入 cooldown，FakeInput 次数=3。
- 在上述及 `strong_fail_with_panel_preempts_selection` 覆盖全状态抢占；另加 F1 shadow 20/0 -> live、任一误触 reset、episode only once 三个小测试。
- 验收：所有 UI-changing 输入间隔≥1.5s；每 tick≤1 输入；每局类上限生效；无锚点/未知零输入。

**风险：**与 N2 evidence 互相污染；Panel FSM 只能读取本 generation evidence，输入后必须失效。不要将「面板看起来仍可见」解释为可再点击。

## ⑥ cycle_num、outcome 与 failure_streak

**修改文件：** `src/gamescript/mediator.py`、`src/gamescript/settings.py`、`tests/test_s0_safety_state_machine.py`；必要时现有 temporal replay tests。

**变更：**

- `game_count` 定义为“已完成一局并回到已验证原 KK 房间”的总数；不要继续只作为回房打印计数。
- 分别维护 `success_count`、`failure_count`、`disconnect_count`、`timeout_count`、`failure_streak`、`last_outcome`。只有确认完整 victory chain 才 `success_count +=1` 且 `failure_streak=0`。
- FAILURE、TIMEOUT、DISCONNECT 都按项目安全定义决定是否递增 failure streak；本方案默认都属于不成功局而递增，以防断线/超时绕开熔断。原因必须写入 trace/incident。
- streak 达 3 后，已完成当前安全退出/回房验证时转 ERROR/停止；不得尝试下一局。
- `cycle_num > 0` 时，当 `game_count == cycle_num`（或已达到）先转 `COMPLETE`（新增 Phase），停止 run，不调用 room start；`cycle_num==0` 表示不按局数限制。达到后再看到 room_start 也必须零输入。

**具名测试与验收：**

- `three_failed_rounds_fail_closed_and_victory_resets_streak`：三次 outcome 后 ERROR/no start；victory 在中间将 streak 清零。
- `cycle_num_two_stops_before_third_room_start`：完成/回房两局后，第三次 room start 可见，`act_click` 未调用、phase COMPLETE。
- 验收：`game_count` 与成功/失败计数可独立解释；连续3局失败安全停止；第三局开始 input=0。

**风险：**outcome 在恢复/退出未确认时过早计数会把一局计两次。使用 `round_id` 或 `outcome_recorded` guard，一局只能落一个终局 outcome。

## ⑦ S0.5 生产 incident：入口传递与证据最小化

**修改文件：** 根 `desktop_app.py`、实际 CLI/API 建 Mediator 的模块（由构造调用搜索确定）、`src/gamescript/incidents.py`（如缺字段/ROI）、`tests/test_desktop_app.py`、`tests/test_incident_archiver.py`。

**变更：**

- Desktop、API、CLI 都从一个明确 `incident_dir` 配置/路径构造 `Mediator(..., incident_dir=...)`；默认建议 `%LocalAppData%/GameScript-Local/incidents`，测试传 tempdir。不得只有 desktop 接线。
- 对异常、round/recovery/exit timeout、恢复、UNKNOWN 面板、Fail-Closed 和按采样率的 panel episode 调 `IncidentArchiver`；正常 HUD 每 tick不得写图。
- 一个 incident 组保存动作前 `frame_before`、动作发生时 `frame_now`、下一帧 `frame_after`。metadata 最少包含：`phase`、`context`、`evidence`（scene/template/score/ROI/generation/hwnd/ui_scale）、`action`、`attempt`、`deadline`（round/recovery/exit）、`outcome`、reason、health。保存关键 ROI crop 和模板分数，ROI 必须来自已裁检测区域。
- 继续使用既有敏感字段 scrub；不归档房间密码、粘贴文本或原始 settings 全量。保留/容量清理仅可删除自身 `incident_*`。
- 将 S0 新字段作为 metadata 的附加字段；N0 action ledger 比较保持单独的动作语义，比较工具只能显式忽略 trace/incident 新字段，不能修改基线动作行。

**具名测试与验收：**

- `desktop_worker_writes_fail_closed_incident`：从 desktop worker 的 Mediator 构造路径传 temp `incident_dir`，触发 Fail-Closed，断言 `incident_*` 含 3 帧（或事件结束前可补齐机制）、metadata 含 phase/context/evidence/action/attempt/deadline/outcome、关键 ROI/score；不得泄露 password。
- 扩展现有 `test_incident_archiver.py`：timeout/recovery/unknown/sample 各一组，正常 10 tick 不落图，frame_after 仅补一次，retention 不删非 incident。
- 验收：ERROR/超时/恢复均产生完整 incident；桌面/API/CLI 三入口都有端到端单测或构造路径测试。

**风险：**高频截图拖慢 hot path/泄露数据；用事件去重、per-episode pending frame-after、sampling 和 S0 metadata allow-list 控制。incident 写入时间若 >1s 必须在 N2 白名单统计中标明。

---

## S0 强制实施顺序、测试矩阵与完成定义

严格按 **① scenes → ②抢占 → ③恢复门闩 → ④round deadline → ⑤Panel FSM → ⑥跨局语义 → ⑦incident 入口** 提交和验证。不得先做 panel FSM 再补强失败抢占；不得在 recovery 尚可无锚推进时宣布稳定；不得因断线 fixture 缺失 XFAIL。

| 具名测试 | 责任步骤 | 核心断言 |
|---|---|---|
| `strong_fail_with_panel_preempts_selection` | ①② | 两帧 STRONG_FAIL 抢占，selection input=0 |
| `giveup_only_panel_is_not_failure` | ①② | giveUp+anchor 不触发 failure/recovery |
| `recovery_does_not_advance_without_anchor_or_success` | ③ | anchor/input/mutation 任一缺失不推进 |
| `disconnect_uses_disconnect_path` | ③ | disconnect 不调用 fail 脚本 |
| `recovery_exit_timeout_starts_after_recovery` | ③ | 46.9s恢复后仍有完整 exit window |
| `periodic_panel_actions_do_not_extend_round_deadline` | ④ | deadline 恒定，超时先 QUIT |
| `three_failed_rounds_fail_closed_and_victory_resets_streak` | ⑥ | 三失败停机，胜利归零 |
| `cycle_num_two_stops_before_third_room_start` | ⑥ | cycle=2，第三局 start 输入=0 |
| `panel_waits_for_visibility_before_close` | ⑤ | 2s visible window，无盲关闭 |
| `panel_same_fingerprint_has_bounded_retries_and_cooldown` | ⑤ | 同指纹≤3、后 cooldown |
| `desktop_worker_writes_fail_closed_incident` | ⑦ | desktop 构造路径完整落 incident |

**S0 最终验收：** 上表全绿、零 XFAIL；fail+panel 两帧零选卡；缺锚/输入失败零状态推进；恢复后才启动退出时钟；周期面板不能延长 round deadline；连续三失败安全停止；cycle=2 绝不点第三局；ERROR/timeout/recovery incident 完整；未识别和 stale evidence 零输入；断线路径至少有真实 fixture 验证后才可宣告 S0 完成。

## 交接与回滚

S0 开始条件：N2 合并；N0 三轮性能报告；`compare_ledger.py` OCR off 零 diff；FrameEvidence 的输入后失效和 generation test 已通过。N2 回滚为恢复 matcher/memo/cadence 上一提交；S0 回滚不得保留 `giveUp` 重新绑进 fail，若需临时停用自动面板，保持 Fail-Closed/zero input 而非退回旧“panel 否决 fail”行为。任何硬门禁 FAIL 均停止下一阶段，报告原始 JSON/trace/incident，而非用文档措辞降级。

## 施工前检查清单

- [ ] N0 schema 和 fixture/template hash 已冻结，连续三次可重跑。
- [ ] S0 执行者已阅读本文件、N0 报告、蓝图 §7/§8/§17/§18、审查 §7/P0。
- [ ] 未与 N2 并行写 `mediator.py`。
- [ ] 新 action 都有：anchor、generation guard、input success、post-confirm、max attempts、deadline、incident。
- [ ] 断线真实素材缺口已作为完成阻塞项登记，未以 mock/XFAIL 替代。
