# Scenario Replay 测试 Harness 设计

> 状态：设计稿；只定义目录、数据契约、测试替身和伪代码，不实现生产代码或测试代码。
>
> 输出目标：将 `Mediator.tick()` 的多帧状态机行为变成可审计的、确定性的回放测试。每一帧都验证“看到了什么、决定了什么、是否输入、输入结果是什么、阶段是否推进”，而不是只验证最终阶段。

## 1. 设计依据与边界

### 1.1 当前代码行为

- `Mediator.tick()` 的顺序是：检查 `StopSignal` → `see("tick")` → frame health → 断线/失败恢复优先级 → 按 `Phase` 分派到 `_tick_l0`、`_tick_main_line` 或 `_tick_l1_tail`。
- `Mediator.see()` 负责按阶段选择 L0/L1 窗口、调用 `_capture_best()`、更新 `_prev_frame`/`_last_frame`，并通过 `_detect_context()` 计算页面上下文。
- `Phase` 至少包括 `BOOT`、`ROOM_WAITING`、`ROOM_STARTING`、`STAGE_SELECT`、`STAGE_STARTING`、`HERO_SETUP`、`MAIN_LINE`、`QUIT`、`NEXT`、`ERROR`。
- 现有状态机约束是“一帧最多一个改变 UI 的动作”。失败/断线恢复本身也是三步状态机：`fail -> ok -> close`，每步结束后必须等下一帧，禁止用旧帧连点。
- `ActionResult` 的关键字段为 `success: bool`、`status: str`、`message: str`。真实输入路径使用 `SUCCESS`、`CANCELLED_WINDOW_OBSCURED`、`CANCELLED_NOT_ELEVATED`、`CANCELLED_SENDINPUT_FAILED` 等状态。
- `tests/test_hero_mode_temporal.py` 已采用固定时间、固定截图、patch `time.time` 和断言每一步点击次数/语义的模式。
- `tests/test_p1a2_challenge_controls.py` 已采用 `fixtures/replay` 截图、注入 `ActionResult`、断言严格顺序、失败重试和零输入安全性的模式。
- `fixtures/reborn_wow/manifest.json` 是按状态和动作组织的证据目录；`fixtures/reborn_wow/README.md` 明确截图是不可变证据，模板/识别不确定时应保持零输入。`fixtures/replay` 目前是扁平的可复用截图库。

### 1.2 不在本设计范围

- 不改变 `Mediator` 的生产接口、Phase 枚举、输入策略或识别算法。
- 不把 Scenario Replay 变成端到端桌面驱动；不得调用真实窗口枚举、真实截图、真实 `SendInput` 或真实睡眠。
- 不用 `sleep` 解决竞态；所有超时和时序由 `FakeClock` 控制。
- 不将最终 `final_phase` 当成唯一断言；每 tick 的硬断言是必须项。

## 2. 推荐方案：声明式 case + 真实 Mediator + 测试替身

### 2.1 方案比较

**方案 A：每个场景手写 Python 测试。**

- 优点：接入现有 unittest 最直接。
- 缺点：多帧时序、动作结果和重复的 phase 断言很快复制粘贴；难以审阅一整条状态轨迹。

**方案 B：只调用私有 `_tick_*`，绕过 `tick()/see()`。**

- 优点：测试快、容易定点构造。
- 缺点：不会覆盖全局 fail/disconnect 优先级、frame health、StopSignal 短路和 capture/context 链；与真实主循环偏离。

**方案 C：推荐。`case.json` 声明轨迹，真实 `Mediator.tick()` 执行，FakeClock/FakeCapture/FakeInputExecutor 提供确定性边界。**

- 优点：保留真实调度顺序；case 是可审阅证据；每 tick 可统一做硬断言；支持同一截图跨多个时刻重放。
- 成本：需要一个测试专用的 capture adapter 和动作探针；不需要生产代码改动。

采用方案 C。Harness 的唯一职责是给 `Mediator` 提供帧、时间和输入结果，并记录观察/动作；不重写状态机。

### 2.2 组件关系

```text
case.json
   │
   ├── ReplayCaseLoader ── 校验字段、解析 Phase/Settings、解析时间轴
   ├── ReplayFrameSource ── 根据 at_s 返回 Frame；替换 _capture_best 的外部采集边界
   ├── FakeClock ── 替换 gamescript.mediator.time.time / sleep
   ├── FakeInputExecutor ── 替换 med.executor；记录 action_ledger；返回注入的 ActionResult
   ├── ActionProbe / ContextProbe ── 记录 Mediator 语义动作和 see() 上下文
   └── ScenarioRunner ── 每帧调用 med.tick()，执行六项硬断言，最后断言 final_phase
```

`Mediator.see()` 保持真实执行。只在 `_capture_best(title, role)` 边界注入回放帧，避免绕过 `see()` 的角色选择、静态帧复用、`_last_frame` 更新和 context cache 行为。`BOOT` 可能按 L0/L1 请求两次采集，因此 `ReplayFrameSource` 必须按 `(tick_index, role)` 返回同一逻辑帧，而不是简单全局 pop 一次。

## 3. Fixture 目录结构

每个场景一个目录；图片可以复用仓库现有证据，也可以放在场景目录中保存场景专用裁剪/变体。所有 `file` 使用仓库根目录相对路径，避免测试工作目录不同导致解析歧义。

```text
fixtures/
├── replay/                         # 现有扁平可复用证据库，不改名、不移动
├── reborn_wow/                     # 现有按状态分类的证据库，不改名、不移动
│   ├── room/
│   ├── stage/
│   ├── main_line/
│   ├── choices/
│   └── endgame/
└── scenarios/
    ├── fail_recovery_three_frames/
    │   ├── case.json
    │   └── frames/
    │       ├── fail_visible.png
    │       ├── ok_visible.png
    │       └── close_visible.png
    ├── stop_start_race/
    │   ├── case.json
    │   └── frames/
    │       └── room_start_visible.png
    ├── skill_panel_one_missing/
    │   ├── case.json
    │   └── frames/
    │       └── skill_panel_three_of_four.png
    ├── stage_starting_env_hud/
    │   ├── case.json
    │   └── frames/
    │       └── env_hud_visible.png
    └── ticket_zero_archaeology/
        ├── case.json
        └── frames/
            ├── ticket_zero_1.png
            ├── ticket_zero_2.png
            └── ticket_zero_3.png
```

`case.json` 是发现入口：测试从 `fixtures/scenarios/*/case.json` glob 加载，不需要再维护一个会与目录漂移的总清单。场景图片必须是完整窗口证据，除非已有识别函数明确接受 ROI；禁止在 harness 中用固定坐标绘制“假按钮”。

现有可直接复用的候选证据：

- 普通房间：`fixtures/reborn_wow/room/room_waiting_host.png`。
- 选关页：`fixtures/reborn_wow/stage/stage_select_old_world_1.png` 或 `stage_select_molten_core_2.png`。
- 局内 HUD：`fixtures/live_postgame_20260808/live_hero_challenge.png`，需确认其包含当前版本 `HeroChallenge`/`env_anchor` 可识别证据。
- 技能面板基线：`fixtures/reborn_wow/choices/skill_choice_3.png`、`skill_choice_4.jpg` 或 `fixtures/replay/skill_choice_3.png`。

失败/断线三帧、券为 0 的当前版本全屏证据在现有目录中没有完整明确的三帧集合；实现时必须补齐真实截图，不能用黑图或合成按钮代替。设计中的路径先作为资产契约。

## 4. `case.json` 数据契约

### 4.1 顶层字段

```json
{
  "schema_version": 1,
  "case": "fail_recovery_three_frames",
  "description": "失败弹窗按 fail -> ok -> close 三帧恢复",
  "phase": "MAIN_LINE",
  "settings_overrides": {
    "dry_run": false,
    "query_timeout": 30
  },
  "frames": [],
  "expect_actions": [],
  "final_phase": "QUIT"
}
```

| 字段 | 类型 | 必填 | 定义 |
|---|---|---:|---|
| `schema_version` | integer | 是 | 当前固定为 `1`；未知版本直接失败，不静默降级。 |
| `case` | string | 是 | 与目录名一致；用于失败信息和报告定位。 |
| `description` | string | 否 | 人类可读的场景意图。 |
| `phase` | string | 是 | 第一帧前的初始 `Phase` 名称，例如 `MAIN_LINE`、`ROOM_WAITING`、`STAGE_STARTING`。大小写必须匹配枚举。 |
| `settings_overrides` | object | 否 | 覆盖 `Settings` 的已有属性；只允许已存在的设置字段，未知字段报错。不得在这里放 harness 控制字段。 |
| `frames` | array | 是 | 按 tick 顺序排列的帧描述；至少一帧。 |
| `expect_actions` | array | 是 | 与 `frames` 一一对应，长度必须完全相等；每个元素描述该 tick 的观察、动作和结果。 |
| `final_phase` | string | 是 | 所有帧执行后 `med.phase.name` 的精确值。 |

`settings_overrides` 的典型字段包括 `dry_run`、`query_timeout`、`stage_targets`、`auto_reputation`、`reputation_type`、`reputation_level`、`skills`、`auto_archaeology`、`auto_bond`、`auto_treasure`。不允许为测试方便新增生产配置字段。

### 4.2 `frames[]` 字段

```json
{
  "id": "fail",
  "at_s": 100.0,
  "file": "fixtures/scenarios/fail_recovery_three_frames/frames/fail_visible.png",
  "window_title": "英雄三国KK",
  "hwnd": 10001,
  "left": 0,
  "top": 0,
  "capture_role": "l1",
  "control": {
    "stop_signal": "unchanged",
    "before_action": null
  }
}
```

| 字段 | 类型 | 必填 | 定义 |
|---|---|---:|---|
| `id` | string | 是 | 帧标识；在失败消息中显示。 |
| `at_s` | number | 是 | 相对场景起点的单调时间，单位秒；runner 在该 tick 前 `clock.set(at_s)`。必须非递减；允许相邻帧同一时间。 |
| `file` | string | 是 | 仓库根目录相对图片路径；必须可解码为 BGR 图像。 |
| `window_title` | string | 否 | 默认按 `capture_role` 选择 `KK` 或 `英雄三国KK`；需与现有 `Frame` 约定一致。 |
| `hwnd` | integer/null | 否 | 默认 `10001`；可设为 `null` 验证无目标窗口输入保护。 |
| `left` / `top` | integer | 否 | 默认 `0, 0`；参与静态帧复用和屏幕坐标计算。 |
| `capture_role` | `l0`/`l1` | 否 | 证据所属窗口角色；默认由初始 phase 推导。只用于 fake capture 选择，不改 phase。 |
| `control` | object | 否 | 测试控制事件，不代表生产输入。用于 StopSignal 竞态和按调用注入结果。 |

`control.stop_signal` 取 `clear`、`set`、`unchanged`。`control.before_action` 可取 `trigger_stop_signal`，含义是帧已被 `see()` 观察后、FakeInputExecutor 解析结果前触发急停，用于复现“看到开始按钮但动作执行窗口被急停抢先”的竞态。该控制事件不是第五种输入结果。

### 4.3 `expect_actions[]` 字段

```json
{
  "phase_before": "MAIN_LINE",
  "context": "QUIT",
  "action_count": 1,
  "action": {
    "kind": "click",
    "reason": "recover",
    "target": "fail",
    "input_kind": "left_click"
  },
  "action_result": {
    "success": true,
    "status": "SUCCESS"
  },
  "phase_after": "QUIT",
  "loop_action": "Continue",
  "input_injection": {
    "outcome": "SUCCESS"
  }
}
```

| 字段 | 类型 | 必填 | 定义 |
|---|---|---:|---|
| `phase_before` | string | 是 | 调用 `tick()` 前的 `med.phase.name`。同时作为防止上一个 tick 隐式推进的断言。 |
| `context` | string | 是 | 本 tick `see()` 观察到的上下文，例如 `QUIT`、`MAIN_LINE`、`ROOM_WAITING`、`STAGE_SELECT`、`UNKNOWN`。若 tick 在 `StopSignal` 入口短路且没有 `see()`，使用约定 sentinel `STOP_SIGNAL`。`HERO_SETUP` 是 `see()` 的特判上下文。 |
| `action_count` | integer | 是 | 本 tick 新增的底层 executor ledger 条数，必须为 `0` 或 `1`；即使输入被取消/失败，也计为一次尝试。 |
| `action` | object/null | 是 | `null` 表示零输入；非空时描述语义动作。 |
| `action_result` | object/null | 是 | 有动作时必须有 `success`、`status`；零输入时必须为 `null`。 |
| `phase_after` | string | 是 | `tick()` 返回后 `med.phase.name`。 |
| `loop_action` | `Continue`/`Break` | 否 | 精确断言 `LoopAction.name`；建议所有场景填写。 |
| `input_injection` | object | 否 | 驱动 FakeInputExecutor 的结果，不是额外断言。若缺省，默认 `SUCCESS`。 |

`action.kind` 取 `click`、`right_click`、`press_key`、`hotkey`、`paste_text`、`scroll`、`type_text`；`reason` 是 `Mediator.act_*` 传入的语义标签，如 `RoomStart`、`StageStart-retry`、`SwitchToArchaeology`、`recover`；`target` 是 `MatchResult.name`，无法从直接 executor 调用得到时可省略。`input_kind` 是 `left_click`、`right_click`、`key`、`hotkey`、`scroll` 等底层类型。

### 4.4 ActionResult 状态映射

Fake executor 对外始终返回真实 `ActionResult` 形状，场景只注入以下四个可控结果：

| 注入名 | `success` | 返回 `status` | 用途 |
|---|---:|---|---|
| `SUCCESS` | `true` | `SUCCESS` | 模拟实际 SendInput 成功；不使用 `DRY_RUN`，以便验证真实成功分支。 |
| `OBSCURED` | `false` | `CANCELLED_WINDOW_OBSCURED` | 点击点被其他窗口遮挡。 |
| `NOT_ELEVATED` | `false` | `CANCELLED_NOT_ELEVATED` | 非管理员进程被 UIPI 拒绝。 |
| `SENDINPUT_FAILED` | `false` | `CANCELLED_SENDINPUT_FAILED` | Windows 注入没有真正发生。 |

`CANCELLED_EMERGENCY_STOP` 是 FakeInputExecutor 检测到 `StopSignal` 后的安全短路结果，不作为普通 outcome 轮次注入；它专门用于 stop/start 竞态。`message` 默认不做全量字符串相等断言，必要时可增加 `message_contains`，避免把文案改动误报成状态机回归。

## 5. FakeClock 接口

FakeClock 必须是单调、无睡眠、可显式推进的时钟。所有 mediator 内部经过 `gamescript.mediator.time.time()` 的 deadline/timeout 都读到同一时钟。

```text
class FakeClock:
    def __init__(self, start: float = 0.0) -> None: ...

    def now(self) -> float: ...
    def set(self, value: float) -> None: ...
    def advance(self, seconds: float) -> float: ...
    def sleep(self, seconds: float) -> None: ...

    def install(self, module: ModuleType = gamescript.mediator)
        -> ContextManager[FakeClock]: ...
```

契约：

1. `set(value)` 只允许 `value >= now()`；回拨时间应立即失败，防止测试隐藏 look-back/timeout bug。
2. `sleep(seconds)` 不等待真实时间，只调用 `advance(seconds)`；Scenario Replay 默认不调用它，但保留接口以阻止未来代码引入真实 sleep。
3. `install()` patch `gamescript.mediator.time.time` 和 `gamescript.mediator.time.sleep`，退出上下文后恢复原对象。
4. `Mediator` 构造和 `set_phase()` 必须在 clock 安装后执行，否则初始化 deadline 会混入墙上时间。

## 6. FakeInputExecutor 接口

FakeInputExecutor 替换 `med.executor`，实现 Mediator 当前实际使用的全部方法，且每次方法调用都先写 ledger，再返回 `ActionResult`。它不调用 Win32、pyautogui、窗口激活或真实延时。

```text
Outcome = Literal[
    "SUCCESS",
    "OBSCURED",
    "NOT_ELEVATED",
    "SENDINPUT_FAILED",
]

class ActionRecord:
    call_index: int
    at_s: float
    method: str
    args: tuple[object, ...]
    kwargs: dict[str, object]
    result: ActionResult

class FakeInputExecutor:
    def __init__(
        self,
        stop_signal: StopSignal,
        clock: FakeClock,
        outcomes: Sequence[Outcome] = (),
        default_outcome: Outcome = "SUCCESS",
        before_result: Callable[[str, ActionRecord], None] | None = None,
    ) -> None: ...

    @property
    def action_ledger(self) -> list[ActionRecord]: ...

    def clear(self) -> None: ...
    def inject_next(self, outcome: Outcome) -> None: ...
    def inject_for_call(self, call_index: int, outcome: Outcome) -> None: ...

    def click(
        self, x: int, y: int, target_hwnd: int | None = None,
        dry_run: bool = True, delay_ms: int = 120,
    ) -> ActionResult: ...
    def right_click(
        self, x: int, y: int, target_hwnd: int | None = None,
        dry_run: bool = True, delay_ms: int = 120,
    ) -> ActionResult: ...
    def press_key(
        self, key: str, target_hwnd: int | None = None,
        dry_run: bool = True,
    ) -> ActionResult: ...
    def hotkey(
        self, *keys: str, target_hwnd: int | None = None,
        dry_run: bool = True,
    ) -> ActionResult: ...
    def paste_text(
        self, text: str, target_hwnd: int | None = None,
        dry_run: bool = True,
    ) -> ActionResult: ...
    def scroll(
        self, x: int, y: int, clicks: int, target_hwnd: int | None = None,
        dry_run: bool = True,
    ) -> ActionResult: ...
    def type_text(
        self, text: str, target_hwnd: int | None = None,
        dry_run: bool = True,
    ) -> ActionResult: ...
```

结果解析顺序：

1. 记录方法名、坐标/按键、`target_hwnd`、`dry_run` 和当前 `clock.now()`。
2. 如果 `stop_signal.is_set()`，返回 `ActionResult(False, "CANCELLED_EMERGENCY_STOP", ...)`，不消费普通 outcome。
3. 若有 `before_result`，先调用它；`trigger_stop_signal` 在此处设置 StopSignal，可复现观察与执行之间的竞态。
4. 按 `inject_for_call`/`inject_next`/队列/default 选择 outcome。
5. 将四种 outcome 映射为上表 ActionResult，并把结果写回同一 `ActionRecord`。

`action_ledger` 是底层事实源：失败输入也算一条记录，直接 `self.executor.scroll/press_key` 的路径也不会漏记。语义 `reason` 和 `target` 由 test-only `ActionProbe` 包裹 `Mediator.act_click`、`act_right_click`、`act_key`；两者按本 tick 的 ledger 调用顺序关联。若生产代码直接调用 executor，语义标签为空，但底层 `method`、参数和结果仍必须断言。

## 7. Replay Runner 伪代码

以下是行为契约，不是实现代码：

```text
run_case(case_path):
    case = load_and_validate_case(case_path)
    clock = FakeClock(start=case.frames[0].at_s)
    stop_signal = StopSignal()

    with clock.install(gamescript.mediator):
        settings = Settings()
        apply_existing_settings_only(settings, case.settings_overrides)
        med = Mediator(settings, ROOT, stop_signal=stop_signal)
        med.set_phase(Phase[case.phase], "scenario initial phase")
        fake_input = FakeInputExecutor(stop_signal, clock)
        med.executor = fake_input
        install_replay_capture(med, case.frames)
        install_action_probe(med)
        install_see_context_probe(med)

        for index, (frame_spec, expected) in enumerate(zip(case.frames, case.expect_actions)):
            clock.set(frame_spec.at_s)
            apply_control(frame_spec.control, stop_signal, fake_input)
            fake_input.begin_tick(index)
            probe.begin_tick(index)

            phase_before = med.phase.name
            assert phase_before == expected.phase_before

            inject_expected_input_result(expected.input_injection)
            loop_action = med.tick()

            context = probe.context_or_STOP_SIGNAL()
            actual_records = fake_input.records_since_tick_start()
            assert len(actual_records) == expected.action_count
            assert len(actual_records) <= 1                 # 永久硬断言
            assert context == expected.context
            assert semantic_action(actual_records, probe) == expected.action
            assert action_result(actual_records) == expected.action_result
            assert med.phase.name == expected.phase_after
            assert loop_action.name == expected.loop_action

        assert med.phase.name == case.final_phase
```

`semantic_action` 必须同时检查动作种类和语义标签；不能只比较 ledger 长度。零动作时要求 `action is null` 且 `action_result is null`。`phase_before` 必须在调用 `tick()` 前取，`phase_after` 必须在 `tick()` 返回后取。对 `StopSignal` 入口短路的 tick，context 记录为 `STOP_SIGNAL`，确保“没有调用 see”也是可审计行为，而不是缺失断言。

## 8. 每 tick 的六项硬断言

每个 `expect_actions[i]` 必须执行以下断言，任何一项失败立即报告 `case/frame/at_s`：

1. **`phase_before`**：调用前 phase 精确匹配 JSON；阻止上一帧的隐式推进或错误初始 phase。
2. **`context`**：`see()` 的第一份有效上下文精确匹配；`StopSignal` 入口使用 `STOP_SIGNAL` sentinel；不允许用期望 phase 代替 context。
3. **`action_count <= 1`**：无论动作成功、遮挡、未提权、SendInput 失败还是急停取消，都按 ledger 计数；大于一直接失败。
4. **`action`**：零输入必须为 `null`；有输入必须匹配 kind、reason/target（若提供）和底层 input kind。
5. **`ActionResult`**：有输入必须匹配 `success` 和精确 `status`；不能只断言 mediator 返回的 bool，因为失败类型决定后续策略。
6. **`phase_after`**：`tick()` 返回后精确匹配；同时建议断言 `loop_action`，确认 `Break/Continue` 与 phase 一致。

额外的 runner 不变量：`frames` 与 `expect_actions` 长度相等；时间非递减；每个 case 只创建一个 Mediator；每帧 ledger 起点使用上帧终点，不清空全局 ledger，从而仍可生成完整 action trace。

## 9. 首批五个场景

### 9.1 `fail_recovery_three_frames`：fail 恢复三帧

**目的**：锁住全局 fail/disconnect 优先级和“每个恢复动作必须等待下一帧”的行为。

| tick | 输入帧 | phase_before | context | 期望动作 | 结果 | phase_after |
|---:|---|---|---|---|---|---|
| 0 | `fail_visible.png` | `MAIN_LINE` | `QUIT` | `click`, reason=`recover`, target=`fail` | `SUCCESS` | `QUIT` |
| 1 | `ok_visible.png` | `QUIT` | `QUIT` | `click`, reason=`ok`, target=`ok` | `SUCCESS` | `QUIT` |
| 2 | `close_visible.png` | `QUIT` | `QUIT` | `click`, reason=`close`, target=`close` | `SUCCESS` | `QUIT` |

每帧 `action_count` 均为 1，`loop_action` 均为 `Continue`。三帧都必须保留足以进入全局恢复分支的 `fail` 或 `disconnect` 父锚点，只把当前可点击控件从 fail 换成 ok、再换成 close；否则 `tick()` 会离开恢复分支，不能验证 WAIT_OK/WAIT_CLOSE。禁止同一帧同时点击 fail 和 ok，禁止第三步使用第二帧的旧图。`final_phase` 为 `QUIT`；不要求本场景自动回到房间。

### 9.2 `stop_start_race`：停止与开始动作竞态

**目的**：验证已观察到开始按钮后，急停在执行窗口抢先发生时不推进到 `ROOM_STARTING`；下一 tick 的急停入口也不能消费旧帧重新点击。

| tick | 控制/输入帧 | phase_before | context | 期望动作 | 结果 | phase_after |
|---:|---|---|---|---|---|---|
| 0 | `room_start_visible.png`；`before_action=trigger_stop_signal` | `ROOM_WAITING` | `ROOM_WAITING` | `click`, reason=`RoomStart` | `CANCELLED_EMERGENCY_STOP` | `ROOM_WAITING` |
| 1 | 同一帧；StopSignal 保持 active | `ROOM_WAITING` | `STOP_SIGNAL` | `null` | `null` | `ROOM_WAITING` |

tick 0 的底层 `action_count` 是 1，因为曾尝试执行输入；tick 1 是 0，因为 `tick()` 在 `see()` 前短路。`final_phase` 为 `ROOM_WAITING`。该场景额外验证：StopSignal 触发不会被普通 `SUCCESS` outcome 覆盖，且失败的 `RoomStart` 不得写入 `ROOM_STARTING` 的 deadline/phase。

### 9.3 `skill_panel_one_missing`：技能面板少识别一张

**目的**：验证技能面板可见卡牌数量与可靠识别结果不完整时，不能盲点一个“看起来像”的位置，也不能把未识别卡当成偏好命中。

**证据**：以 `fixtures/reborn_wow/choices/skill_choice_4.jpg` 或当前版本同源全屏截图为基线，准备一个真实的“三张可见、仅两张有可靠模板命中”的 `three_of_four` 证据；不在测试中绘制假卡或修改像素。

| tick | 输入帧 | phase_before | context | 期望动作 | 结果 | phase_after |
|---:|---|---|---|---|---|---|
| 0 | `skill_panel_three_of_four.png` | `MAIN_LINE` | `MAIN_LINE` | `null` | `null` | `MAIN_LINE` |
| 1 | 同一未改变面板 | `MAIN_LINE` | `MAIN_LINE` | `null` | `null` | `MAIN_LINE` |

`settings_overrides.skills` 指定四张候选的偏好顺序。两帧都必须零输入；不能因为 `_selection_anchor` 命中就按刷新、放弃或任意已识别卡。`final_phase` 为 `MAIN_LINE`。该 case 是安全回归契约：如果产品策略未来改为“有可靠 preferred hit 即可选择”，应先修改 case 的明确策略，而不是让 harness 默默放宽。

### 9.4 `stage_starting_env_hud`：STAGE_STARTING 通过环境 HUD 进局

**目的**：验证进入 `STAGE_STARTING` 后，环境 HUD 是可信的进局证据；识别到 HUD 时只推进 phase，不再次点击 `StageStart`。

建议使用 `fixtures/live_postgame_20260808/live_hero_challenge.png` 或当前版本明确包含 `env_anchor`/`HeroChallenge` 的全屏截图。

| tick | 输入帧 | phase_before | context | 期望动作 | 结果 | phase_after |
|---:|---|---|---|---|---|---|
| 0 | `env_hud_visible.png` | `STAGE_STARTING` | `MAIN_LINE` | `null` | `null` | `MAIN_LINE` |

首批最小契约只包含上述一个 tick，`final_phase=MAIN_LINE`；不要把后续主线自动任务或挑战动作混入此 case。核心硬断言是 action_count=0，防止环境 HUD 被误判为仍需点开始。

**目的**：验证挑战券为 0 需要连续三帧确认，第三帧点击 `SwitchToArchaeology` 并进入停止路径，避免一帧闪烁就切模式。

使用当前版本选关页的真实“挑战券=0”证据；现有 stage 截图只能作为版式参考，不能假定其包含 ticket-zero 数字。

| tick | 输入帧 | phase_before | context | 期望动作 | 结果 | phase_after |
|---:|---|---|---|---|---|---|
| 0 | `ticket_zero_1.png` | `STAGE_SELECT` | `STAGE_SELECT` | `null` | `null` | `STAGE_SELECT` |
| 1 | `ticket_zero_2.png` | `STAGE_SELECT` | `STAGE_SELECT` | `null` | `null` | `STAGE_SELECT` |
| 2 | `ticket_zero_3.png` | `STAGE_SELECT` | `STAGE_SELECT` | `click`, reason=`SwitchToArchaeology`, target=`archaeology_switch` | `SUCCESS` | `QUIT` |

tick 2 的 `loop_action` 为 `Break`，`final_phase=QUIT`。前三帧之间可有时间间隔，但不能用时间替代连续帧确认；每一帧仍必须有自己的上下文和 action_count 断言。

## 10. `tests/test_scenario_replay.py` 接入方式

### 10.1 测试文件职责

新增独立测试模块 `tests/test_scenario_replay.py`，不修改现有 temporal/challenge 测试的断言方式。建议结构：

```text
class ScenarioReplayTests(unittest.TestCase):
    def test_all_scenario_cases(self):
        for case_path in discover("fixtures/scenarios/*/case.json"):
            with self.subTest(case=case_path.parent.name):
                run_case(case_path)
```

实现时还应提供按 case 名称筛选的单场景入口，便于截图/模板回归时只跑一个 case；筛选应由测试参数或独立 helper 完成，不要改变 `case.json` 契约。

### 10.2 注入边界

- `Mediator` 仍从真实构造函数创建，使用仓库 `ROOT` 和真实 `Settings`。
- 在 clock 安装后设置初始 phase。
- `med.executor = FakeInputExecutor(...)`；不得 patch `InputExecutor` 的静态函数后让真实 executor 继续存在。
- 在 `_capture_best` 边界注入 `ReplayFrameSource`，保留 `Mediator.see()`。
- 用 test-only probe 包装 `act_click`/`act_right_click`/`act_key`，只记录语义标签并委托原方法；不要替换 `_tick_*`。
- 用 context probe 暴露 `see()` 的观察上下文；对 `StopSignal` 入口短路显式记录 `STOP_SIGNAL`。
- 每 tick 只允许 runner 推进 clock 和应用 case control；不允许测试内部调用 `set_phase()` 修正实际结果。

### 10.3 失败报告

失败消息至少包含：

```text
case=<case> frame=<id> index=<i> at_s=<time>
phase_before expected=<...> actual=<...>
context expected=<...> actual=<...>
ledger_delta=<...>
action expected=<...> actual=<...>
action_result expected=<...> actual=<...>
phase_after expected=<...> actual=<...>
```

如果 `action_count > 1`，必须打印该 tick 的全部 ledger 记录，包括 method、坐标/按键、reason、status；这是定位“一帧连点”所需的最小证据。

### 10.4 执行命令

在仓库根目录执行：

```text
python -m unittest -v tests.test_scenario_replay
```

若本地使用 pytest 运行现有测试，也支持：

```text
python -m pytest -q tests/test_scenario_replay.py
```

单场景调试命令由实现时的筛选 helper 决定；建议最终提供：

```text
python -m pytest -q tests/test_scenario_replay.py -k fail_recovery_three_frames
```

首批接入完成后的通过标准不是“文件能加载”，而是五个 case 的每帧六项硬断言全部通过，且没有真实窗口、真实输入或真实睡眠副作用。

## 11. 实施顺序与风险控制（供后续实现使用）

1. 先落地 loader/schema 校验和 `FakeClock`，用不涉及识别的 STOP_SIGNAL case 验证时间/短路。
2. 再落地 capture adapter，确认 `see()` 的 `_last_frame`、静态帧和 role 行为仍被执行。
3. 再落地 FakeInputExecutor/action ledger；先用现有 `main_line_auto_off/on` 和挑战测试的 ActionResult 语义核对状态映射。
4. 最后逐个加入五个 scenario；缺失真实证据时标记为资产缺失并阻止误报，不用占位图片通过。
5. 任何 case 若需要调用私有 `_tick_*` 才能通过，应视为 harness 边界设计错误；Scenario Replay 的价值正是覆盖真实 `tick()` 总调度。

### 自检结论

- 目录、字段、时间轴和最终 phase 已定义。
- FakeClock 不依赖墙上时间；FakeInputExecutor 不触碰真实输入，并保留 `ActionResult` 原形状。
- 每 tick 明确断言 phase_before/context/action_count/action/ActionResult/phase_after。
- 五个场景均有逐帧期望和最终 phase；缺失截图被明确列为证据前置条件，不伪造完成。
- 接入为独立 `tests/test_scenario_replay.py`，并给出 unittest/pytest 执行命令。
