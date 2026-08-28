# L0 局外建房 UIA 链路设计（LOBBY / Wave2 预启动）

> 日期：2026-08-11
> 分支：codex/ocr-hybrid
> 关联：`docs/NEXT_STAGE_EXECUTION_BLUEPRINT_20260811.md` §13（L0）、§17、§18
> 状态：**研究 PASS + 框架实现 PASS + 实机门禁 BLOCKED-待用户实机窗口**

---

## 1. 结论

| 项 | 结论 |
|---|---|
| UIA 技术可行性 | **PASS**：UIAutomationCore 通过 COM 可稳定驱动；纯 ctypes 覆盖读取/遍历子集，**pattern 写路径（Invoke/SetValue/Toggle）建议经 comtypes**（见 §4 依赖申请） |
| 零新库骨架 | **PASS**：`src/gamescript/ui/uia/` 六模块 + `tools/dump_uia_tree.py` + 40 个单测全绿 |
| 控件映射表设计 | **PASS**（模板完备；KK 候选 selector 待实机 UIA tree 回填，表结构已含备选链） |
| Fail-Closed 30s | **PASS**（单测覆盖：控件缺失/读回不符/锚点缺失/pattern 不可用，全部超时停机、零动作） |
| 实机门禁（UIA tree 导出、20 次 dry-run 100%、DPI 移动后有效） | **BLOCKED-待用户实机窗口**（本机为无交互桌面的虚拟显示会话，见 §7 操作指引） |

---

## 2. 现有窗口基础设施盘点（研究任务 1）

### 2.1 现状（读码结论）

| 能力 | 位置 | 说明 |
|---|---|---|
| 窗口发现 | `src/gamescript/vision/capture.py:find_window_targets()` | `EnumWindows` 按标题关键字 + role（l0/l1）排序，返回 `WindowTarget`（hwnd/title/pid/exe/class_name/窗口+客户区几何）；l0 关键字 = KK官方/KK对战/KK竞技/对战平台/竞技平台/KK |
| 前台/激活 | `capture.activate_window()` | AttachThreadInput + SetForegroundWindow + 置顶/取消置顶，仅在真实输入前调用 |
| DPI/坐标 | 逻辑坐标（屏幕物理像素）经 `client_to_screen/screen_to_client` 转换；`mediator._ui_scale` 每帧按 `min(w/1600, h/900)` 校准（960×540=0.6），模板匹配 scales 邻域自适应 |
| 输入安全 | `input/keyboard_mouse.py:InputExecutor` | 前台校验（同进程窗口也算命中）、`WindowFromPoint` 遮挡校验、未提权拒绝 SendInput、dry_run 全拒；**L0 建房链已走此通道**（`_fill_room_dialog` 用 ctrl+a + paste_text） |
| 现有 L0 建房链 | `mediator.py` Phase.PLATFORM_MAP→CREATE_ROOM→ROOM_WAITING→ROOM_STARTING→STAGE_SELECT | 纯视觉：`_find_map_create_room`（模板+底部蓝按钮 ROI）、`_find_create_confirm`（584×488 弹窗 ROI+双输入框）、`_fill_room_dialog`；有 `_l0_cycle_limit=5` 循环上限 |

### 2.2 L0 adapter 接入点

`mediator.py` 本波**不可改**（RUNTIME 独占）。接入点（后续波次接线，接口已就绪）：

1. **替换视觉动作点**：`PLATFORM_MAP` 的 `_find_map_create_room`+`act_click` → `LobbyUiaAdapter.act("create_room_button")`；
2. **弹窗填表**：`CREATE_ROOM` 的 `_fill_room_dialog` → `act("room_name_input", settings.room_name)` / `act("room_password_input", settings.room_password)` / `act("create_confirm_button")`；
3. **房间开始**：`ROOM_WAITING/ROOM_STARTING` → `act("room_start_button")`；**选关**：`STAGE_SELECT` → `act("stage_item")`+`act("stage_start_button")`；**退出回房**：局末 → `act("exit_room_button")`；
4. **窗口身份**：复用 `find_window_targets(title, role="l0")` 的输出作为 `UiaWindowSpec` 的解析器（`LobbyUiaAdapter._default_resolve_window` 已惰性接线）；
5. **开关策略**：`settings` 增加 `lobby_uia_mode`（off/uia/visual-fallback）由后续波次在 `settings.py` 加（本波不动 settings，仅预留 `AdapterOptions.use_visual_fallback`）；
6. **dry_run**：`settings.dry_run` 直通 `AdapterOptions.dry_run`（dry-run 只解析+读回，零真实输入）。

### 2.3 UIA 树与现有链的关系

- 局内（L1）**继续纯视觉**，不引入 UIA（CEF 游戏局内无可用控件树，且与 RUNTIME 热路径隔离）；
- 局外（L0）UIA 是**与视觉并行的独立链路**：UIA 可用时优先生效；UIA 失效/控件缺失 → 30s Fail-Closed，**不自动回退盲点**；显式开启 visual-fallback 时才走固定 ROI 视觉（§6.3 接口已预留）。

---

## 3. UIA 访问途径评估（研究任务 2，实证）

本机实证环境：Windows 10 19045，Python 3.11.15，**无交互桌面的虚拟显示会话**（GameViewer Virtual Display），进程非提权。实测脚本见研究过程（ctypes 探针 vs comtypes 探针，2026-08-11 本机跑通）。

| 途径 | 可行性 | 实测证据 | 依赖 |
|---|---|---|---|
| **A. ctypes 直调 UIAutomationCore COM** | **部分可行** | ✅ CoCreateInstance/GetRootElement/ElementFromHandle/GetCurrentPropertyValue（Name/ControlType/ClassName/AutomationId 读回正确，记事本窗口读出“无标题 - 记事本”）；✅ CreateTrueCondition + FindAll(Children) + ElementArray；✅ GetCurrentPattern（Invoke/Value/Toggle 获取接口存在）。❌ **CreatePropertyCondition（VARIANT 按值传参）在本 Python 上触发 access violation 写 0x7533（propertyId 值），ctypes x64 按值结构体 ABI 缺陷**；❌ 本会话中 RawViewWalker 返回桌面子树（不可信）、FindAll 对个别元素 E_FAIL（按叶子处理即可）。**对策：不用 CreatePropertyCondition，改“FindAll(TrueCondition) 快照 + Python 侧 selector 过滤”**（本骨架即此设计，全绿）。 | 零 |
| **B. comtypes（typelib 生成绑定）** | **完全可行，推荐生产路径** | ✅ 同一窗口经 comtypes 看到全部 5 个控件子级（raw ctypes 同场景 0 个——oleacc/MSAA 代理经 comtypes 加载正常）；✅ ValuePattern 可用（Edit）、InvokePattern 可用（Button“创建房间”）、TogglePattern 可用（CheckBox“自动准备”）——三个 pattern 全部实证可获取；✅ CreatePropertyCondition 由 typelib 正确处理 VARIANT。 | `comtypes`（纯 Python，无编译） |
| **C. PowerShell + System.Windows.Automation** | 可行但**不推荐** | .NET UIAutomationClient 全系统自带；但每调用一个子进程（~200-500ms 启动），元素代理无法跨进程保活，状态/缓存语义弱，trace 困难。 | 零 |
| **D. uiautomation / pywinauto 库** | 可行（B 的上层封装） | `uiautomation` 包本质就是 comtypes 包装（源码实证：`comtypes.client.GetModule("UIAutomationCore.dll")`）；pywinauto 更重（还带 win32 后端）。 | `uiautomation` 或 `pywinauto` |

**结论**：骨架期（本波）走 A 的已验证子集（零依赖）；**生产期申请 B（comtypes）**——它修复 A 的两个致命点（VARIANT 条件、MSAA 代理子级），且是 uiautomation 库的底层，后续若要换 D 只是换后端实现（`ElementSource` 协议不变）。

**UIPI/提权**：UIA 的 Invoke/SetValue 跨完整性级别受 UIPI 限制（与 SendInput 同理）。KK 平台通常提权运行，**自动化进程必须“以管理员身份运行”**才能写 pattern；读取（GetCurrentPropertyValue）不受限。dry-run 只读验证即使不提权也可跑。

---

## 4. 依赖申请清单（需用户批准）

| # | 包 | 用途 | 理由（为什么不用零依赖方案） | 是否阻塞本波 |
|---|---|---|---|---|
| 1 | `comtypes`（纯 Python，pip） | UIA COM typelib 绑定 | 唯一实证能同时解决：VARIANT 按值传参（CreatePropertyCondition AV）+ MSAA 代理子级枚举（标准控件 Edit/Button/CheckBox 的 UIA 树）。本机实证：comtypes 看到 5 子级+3 pattern，raw ctypes 同场景 0 子级。 | 否（骨架已零依赖交付；生产接线前需要） |
| 2 | `uiautomation`（可选，依赖 1） | 高层封装（控件查找/等待） | 减少自研量；其 `AutomationElement` 已覆盖我们需要的 Name/AutomationId/ControlType/Invoke/Value/Toggle。**可拒绝**：我们的 ElementSource 协议已把接口面锁小，comtypes 直连足够。 | 否 |
| 3 | `pywinauto`（备选） | 替代 1+2 | 更重（双后端），仅当团队已有 pywinauto 经验时选用。 | 否 |

**不新增**：本波全部实现零第三方依赖（backend 为 ctypes 子集 + 客户端过滤）。

---

## 5. 接口签名（研究任务 2/交付 3）

### 5.1 模块布局（已实现）

```text
src/gamescript/ui/uia/
  __init__.py    导出
  model.py       UiaNode / UiaSelector / ControlMapping / ReadbackSpec /
                 PostAnchorSpec / UiaActionTrace / FailClosedError / 常量
  selector.py    find_matching_nodes / resolve_node / describe_node（纯函数）
  source.py      ElementSource 协议 / build_snapshot / SnapshotCache /
                 collect_nodes（有界遍历：节点预算 2000 + 深度 32 + 路径环检测）
  backend.py     CtypesUiaBackend（零依赖子集实现）
  adapter.py     LobbyUiaAdapter / AdapterOptions / VisualFallback
  mappings.py    KK_LOBBY_MAPPINGS / WINDOW_PLATFORM_MAP / WINDOW_ROOM
tools/dump_uia_tree.py   实机工具：dump / probe / loop（20 次 dry-run）
tests/test_uia_selector.py / test_uia_tree.py / test_uia_adapter.py（40 用例）
```

### 5.2 ElementSource（后端抽象，mockable）

```python
class ElementSource(Protocol):
    def is_available(self) -> bool
    def element_from_handle(self, hwnd: int) -> Any | None      # None=失败
    def get_property(self, element, prop_id: int) -> Any | None  # Name/AutomationId/ControlType/ClassName/FrameworkId/ProcessId
    def children(self, element) -> list[Any]                    # [] = 叶子（含 FindAll E_FAIL）
    def get_pattern(self, element, pattern_id: int) -> Any | None  # Invoke=10000/Value=10002/Toggle=10016
    def invoke(self, pattern) -> None
    def set_value(self, pattern, text: str) -> None
    def toggle(self, pattern) -> None
    def value(self, pattern) -> str
    def toggle_state(self, pattern) -> int
    def describe(self) -> str
    def close(self) -> None
```

### 5.3 UiaSelector（多属性 AND + 备选链）

```python
@dataclass(frozen=True)
class UiaSelector:
    name: str | None = None        # Name 精确
    name_re: str | None = None     # Name 正则（二选一）
    automation_id: str | None = None
    control_type: int | ControlType | None = None
    class_name: str | None = None
    index: int | None = None       # 第 n 个命中（0-based）；None=第一个
    scope: str = "children"        # children | descendants
```

### 5.4 ControlMapping（控件映射条目）

```python
@dataclass(frozen=True)
class ControlMapping:
    key: str
    selector: UiaSelector          # 主选择器
    variants: tuple[UiaSelector, ...] = ()   # 备选链（版本/皮肤变体）
    action: PatternKind = NONE     # INVOKE | VALUE_SET | TOGGLE | NONE(读)
    value: str | None = None       # VALUE_SET 写入值（运行时可覆盖）
    readback: ReadbackSpec = ...   # 值读回（stability_frames 连续一致）
    post_anchor: PostAnchorSpec | None = None  # 后置页面证据
    fail_timeout_s: float = 30.0   # Fail-Closed 总期限
    max_attempts: int = 3
```

### 5.5 LobbyUiaAdapter（动作 + Fail-Closed）

```python
class LobbyUiaAdapter:
    def __init__(self, source, mappings, window_spec=None, options=None,
                 clock=None, resolve_window=None, visual_fallback=None, sleep=None)
    def act(self, mapping_key: str, expected_value: str | None = None) -> UiaActionTrace
        # 成功→trace；任何不满足→FailClosedError（携带证据），绝无盲点动作
    def probe_mapping(self, mapping_key: str) -> dict      # 只读探针（dry-run 基础）
    def dump_tree(self, hwnd=None, window_key=None) -> dict  # 树导出（incident 留证）
    def resolve_window(self) -> WindowResolved | None      # (hwnd, (pid, class, title))
```

### 5.6 Fail-Closed 时序（act 内部）

```text
[0s]  resolve_window ──失败──▶ 每 0.5s 重试，至 fail_timeout(30s) → FailClosedError("window not found")
[解析] snapshot(cache TTL 5s) + selector/variants 链解析控件
      ──未命中──▶ 每 0.5s 重试（TTL 自动重建快照），至 30s → FailClosedError("control not found")
[动作] pattern 不可用 → 立即 FailClosedError（dry_run 同样要求 pattern 可用）
      dry_run=False 才执行 Invoke/SetValue/Toggle
[读回] ValuePattern/页面证据连续 stability_frames(2) 次一致才算通过
      ──不符──▶ max_attempts(3) 内重试，仍不符 → FailClosedError("readback mismatch")
[锚点] invalidate → 重新快照 → post_anchor 出现/消失/值相等才算动作生效
      ──缺失──▶ 每 0.5s 重试至 30s → FailClosedError("post anchor not confirmed")
[成功] invalidate 缓存；trace 记录 selector/值/耗时/attempts
```

### 5.7 VisualFallback（固定 ROI 视觉 fallback 接口，预留）

```python
class VisualFallback(Protocol):
    def find(self, roi_key: str, frame) -> MatchResult | None   # 现有模板/ROI 链
    def click(self, x: int, y: int) -> ActionResult
    def read_text(self, roi_key: str, frame) -> str | None
```

默认 `AdapterOptions.use_visual_fallback=False`；开启时由后续波次把现有
`_find_map_create_room`/`find_input_boxes` 等包成该实现。**UIA 链路永不自动
触发视觉回退**——回退本身也要经过相同的 selector 解析 + 读回 + 锚点门禁。

---

## 6. 控件映射表（研究任务 2 / 交付 4）

### 6.1 模板（每个控件固定四要素）

| 字段 | 说明 |
|---|---|
| selector | 多属性（Name/AutomationId/ControlType/ClassName）+ 备选链 variants |
| 值读回方式 | VALUE（ValuePattern）/ TOGGLE_STATE / NAME（页面证据） |
| 后置确认锚点 | EXISTS / ABSENT / VALUE_EQ，selector 指向下一个页面特征控件 |
| Fail-Closed 超时 | 默认 30s；读回 stability 2 帧、max_attempts 3 |

### 6.2 KK 候选映射（⚠️ selector 为候选值，实机 UIA tree 导出后回填）

| key | 控件 | selector（候选） | action | 读回 | 后置锚点 |
|---|---|---|---|---|---|
| `create_room_button` | 地图页·创建房间 | name_re=`创建房间\|新建房间` + Button；变体 `创建` | INVOKE | — | 弹窗确认按钮 `^(确定\|创建\|确认)$` EXISTS |
| `room_name_input` | 弹窗·房名 | Edit，index 0（descendants） | VALUE_SET | VALUE == settings.room_name（2 帧） | — |
| `room_password_input` | 弹窗·密码 | Edit，index 1 | VALUE_SET | VALUE == settings.room_password | — |
| `create_confirm_button` | 弹窗·确认 | name_re=`^(确定\|创建\|确认)$` + Button | INVOKE | — | 房间页“开始游戏” EXISTS |
| `room_start_button` | 房间·开始游戏 | name_re=`开始游戏\|开始` + Button；变体 `准备` | INVOKE | — | 选关页关卡行 `^1-(1[0-5]\|[1-9])$` EXISTS |
| `stage_item` | 选关·目标关卡 | name_re=`^1-(1[0-5]\|[1-9])$` | INVOKE | **NAME 正则回读（1-15 合法，1-16 判失败）** | 选关页“开始游戏” EXISTS |
| `stage_start_button` | 选关·开始 | name_re=`开始游戏\|开始` + Button | INVOKE | — | 选关页关卡行 ABSENT（进加载/局内） |
| `exit_room_button` | 局末·退出回房 | name_re=`退出` + Button | INVOKE | — | 关卡行 ABSENT（回到房间页；房间页也有“开始游戏”，不能用它做 ABSENT 锚点） |

**关卡 1-16 门禁**：`STAGE_RE = ^1-(1[0-5]|[1-9])$` 直接嵌入 selector 与读回
（`ReadbackSpec.expected_re`），1-16 永不命中，单测 `test_stage_readback_rejects_1_16` 守护。

**cycle_num 门禁**：`cycle_num` 是 mediator 层循环计数（`_l0_cycle_count`/`_l0_cycle_limit` 已有）；
adapter 单动作无循环语义，接线波次在 LOBBY 层计数，超出不再调 `act("create_room_button")`。

### 6.3 读回/锚点语义与蓝图 §13 对齐

- “房名/密码/地图/关卡以读取回值/页面证据为准，不以点击完成为准” → `readback` 必须通过 + `post_anchor` 必须出现，`test_readback_mismatch_fails_closed` 守护；
- “找不到控件时 30 秒内 Fail-Closed，零盲点连击” → `fail_timeout_s=30.0` + 动作前必须解析成功，`test_control_missing_fails_closed_within_timeout` 守护（断言动作列表为空）；
- “每次建房都有 UIA selector、值、截图和耗时 trace” → `UiaActionTrace`（selector_detail/readback_values/elapsed_s）+ 截图由调用方经 incident 链补（adapter 不直接截图，`dump_tree` 提供留证）。

---

## 7. 实机验证清单（BLOCKED-待用户，附操作指引）

> 前置：用户开启 KK 对战平台，停在对应页面；本脚本以管理员身份运行（UIPI）。

| # | 步骤 | 命令 | 通过标准 |
|---|---|---|---|
| 1 | 开游戏到**平台地图页** | `python tools/dump_uia_tree.py dump` | 导出 JSON + 打印树；能看到“创建房间”类按钮节点（Name/ControlType/Class 落盘） |
| 2 | 打开**建房弹窗**再 dump | 同上 | 树中出现 ≥2 个 Edit + 确认按钮；记录其 Name/AutomationId/Class |
| 3 | 进**房间页**再 dump | 同上 | 出现“开始游戏”按钮节点 |
| 4 | 进**选关页**再 dump | 同上 | 出现 `1-N` 关卡行（ListItem）与开始按钮 |
| 5 | 回填映射 | 用导出的真实属性更新 `mappings.py` selector/variants | — |
| 6 | 只读探针 | `python tools/dump_uia_tree.py probe` | 8 个 mapping 全部 OK（resolved + pattern_available） |
| 7 | **20 次只建房 dry-run** | `python tools/dump_uia_tree.py loop --count 20` | 每 mapping 通过 20/20；报告 `agent_out/lobby_dryrun_report.json` |
| 8 | DPI 移动验证 | 窗口移到副屏/改缩放后重复 6 | selector 仍全命中（UIA 坐标为物理像素，控件属性与屏幕位置无关） |
| 9 | 关卡 1-16 负例 | 选关页出现 1-16 时 probe `stage_item` | 必须 FAIL（正则拒绝） |
| 10 | 首次真人监督建房（dry_run=false） | 接线波次后进行 | 房名/密码读回 == 输入值；进选关页；错误输入 0 |

**本波门禁状态**：步骤 1-5 需要用户实机窗口（本会话为无交互桌面，KK 无法启动可见窗口）；
步骤 6-10 全部标注 **BLOCKED-待用户**。工具已就绪，用户配合一次即可闭环。

---

## 8. 实现摘要（本波交付物）

| 文件 | 内容 |
|---|---|
| `src/gamescript/ui/uia/model.py` | 数据模型 + UIA 常量 + FailClosedError |
| `src/gamescript/ui/uia/selector.py` | selector 匹配引擎（预编译正则、AND 语义、index） |
| `src/gamescript/ui/uia/source.py` | ElementSource 协议 + 有界树快照（预算/深度/路径环检测）+ 缓存失效 |
| `src/gamescript/ui/uia/backend.py` | CtypesUiaBackend：零依赖子集（FindAll(TrueCondition)+属性读+pattern 获取；规避 CreatePropertyCondition） |
| `src/gamescript/ui/uia/adapter.py` | LobbyUiaAdapter：窗口身份→解析→动作→读回→锚点→trace；30s Fail-Closed |
| `src/gamescript/ui/uia/mappings.py` | KK 8 控件候选映射 + 窗口身份 + STAGE_RE 门禁 |
| `tools/dump_uia_tree.py` | dump / probe / loop 三子命令（实机工具） |
| `tests/test_uia_selector.py` | 8 用例 |
| `tests/test_uia_tree.py` | 12 用例（含同属性兄弟节点回归、环检测、预算/深度/缓存） |
| `tests/test_uia_adapter.py` | 20 用例（happy path 7 / fail-closed 8 / dry-run 5，含密码脱敏回归） |

测试命令与通过数：
```text
python -m unittest tests.test_uia_selector tests.test_uia_tree tests.test_uia_adapter
Ran 40 tests — OK
python -m compileall src/gamescript/ui/uia tools/dump_uia_tree.py tests/test_uia_*.py — OK
```
完整套件在 `agent_out/lobby_fullsuite.log`（含本项目全部 test_*.py；耗时 >10 分钟）。

**敏感信息**：`room_password_input` 的读回值在 trace/probe 中一律脱敏为
`<redacted:len=N>`（`AdapterOptions.secret_keys` 可扩展），符合仓库
“密码不出现在日志”策略。

---

## 9. 风险与后续

| 风险 | 缓解 |
|---|---|
| KK Qt/CEF 控件树可能与候选 selector 不符（Name 为空、AutomationId 缺失、CEF 页面元素不可达） | selector 多属性+变体链；实机导出后回填；Qt 无障碍需窗口可见/被 AT 客户端触碰（dump 即触发）；CEF 可访问性通常随 AT 连接激活 |
| ctypes 的 CreatePropertyCondition AV（本 Python 已知） | 骨架不调用它（客户端过滤）；生产切 comtypes |
| UIPI：非提权进程写 pattern 被拒 | 以管理员身份运行；dry-run 只读不受限 |
| 无交互会话（CI/虚拟显示）下 UIA 树异常（桌面空、walker 错乱） | 全部 try/except 兜底；Fail-Closed 由 adapter 层保证；实机门禁必须在用户交互会话执行 |
| 回退路径复杂度 | visual-fallback 默认关闭；开启时同样过 selector/读回/锚点门禁 |
| 下一任务前置 | 依赖批准（comtypes）；实机 UIA tree 导出回填映射；mediator 接线波次（不得本波改 mediator） |

**回滚方式**：本波全部为新文件，不触碰任何现有模块（mediator.py/matcher.py/settings.py 未改）；删除 `src/gamescript/ui/uia/`、`tools/dump_uia_tree.py`、三个测试文件即完全回滚。
