"""KK 对战平台局外建房控件映射表（L0）。

⚠️ 重要：本表是**待实机验证的候选映射**。KK 是 Qt 窗口内嵌 CEF 的游戏，
控件 Name/AutomationId/ClassName 的真实取值必须由用户按
docs/plans/LOBBY_UIA_DESIGN_20260811.md 第 7 节操作导出 UIA tree 后回填。
selector 命中策略已按“多属性 + 备选链”设计，命中不足时 Fail-Closed，
不会因候选值错误而乱点。

每个映射条目字段：
- selector：主选择器（AND 语义，None 字段不参与）
- variants：备选链（主选择器未命中时按序尝试）
- action：INVOKE / VALUE_SET / TOGGLE
- value：VALUE_SET 写入值（运行时可用 expected_value 覆盖）
- readback：动作后值读回（ValuePattern/页面证据）
- post_anchor：后置页面确认锚点
- fail_timeout_s：Fail-Closed 总期限（蓝图门禁默认 30s）
"""

from __future__ import annotations

from .model import (
    AnchorCondition,
    ControlMapping,
    PatternKind,
    PostAnchorSpec,
    ReadbackKind,
    ReadbackSpec,
    UiaSelector,
    UiaWindowSpec,
)

# 窗口身份（候选值，实机验证后回填精确 class_name）
WINDOW_PLATFORM_MAP = UiaWindowSpec(
    title_contains=("KK",),
    class_name=None,  # 候选：Qt5QWindowIcon / Qt5QWindowOwnDC / Chrome_WidgetWin_1
    role="l0",
)
# 房间/弹窗与平台同进程：同一 pid，不同顶层窗口
WINDOW_ROOM = UiaWindowSpec(
    title_contains=("KK",),
    class_name=None,
    role="l0",
)

# 关卡编号读回约束：1-15 合法，1-16 必须判失败（蓝图门禁）
STAGE_RE = r"^1-(1[0-5]|[1-9])$"

# 房名/密码输入框：弹窗内两个 Edit，按出现顺序 index 0/1
_ROOM_NAME_INPUT = UiaSelector(
    control_type=50004,  # Edit
    index=0,
    scope="descendants",
)
_ROOM_PASSWORD_INPUT = UiaSelector(
    control_type=50004,  # Edit
    index=1,
    scope="descendants",
)

KK_LOBBY_MAPPINGS: dict[str, ControlMapping] = {
    # 地图页 → 创建房间
    "create_room_button": ControlMapping(
        key="create_room_button",
        selector=UiaSelector(name_re=r"创建房间|新建房间", control_type=50000, scope="descendants"),
        variants=(
            UiaSelector(name_re=r"创建", control_type=50000, scope="descendants"),
        ),
        action=PatternKind.INVOKE,
        post_anchor=PostAnchorSpec(
            # 精确匹配：锚点是弹窗内的确认按钮，不能误中刚点过的“创建房间”
            selector=UiaSelector(name_re=r"^(确定|创建|确认)$", control_type=50000, scope="descendants"),
            condition=AnchorCondition.EXISTS,
        ),
        fail_timeout_s=30.0,
    ),
    # 建房弹窗 → 房间名
    "room_name_input": ControlMapping(
        key="room_name_input",
        selector=_ROOM_NAME_INPUT,
        action=PatternKind.VALUE_SET,
        value="",  # 运行时以 settings.room_name 覆盖
        readback=ReadbackSpec(kind=ReadbackKind.VALUE, expected="", stability_frames=2),
        fail_timeout_s=30.0,
    ),
    # 建房弹窗 → 密码
    "room_password_input": ControlMapping(
        key="room_password_input",
        selector=_ROOM_PASSWORD_INPUT,
        action=PatternKind.VALUE_SET,
        value="",  # 运行时以 settings.room_password 覆盖
        readback=ReadbackSpec(kind=ReadbackKind.VALUE, expected="", stability_frames=2),
        fail_timeout_s=30.0,
    ),
    # 建房弹窗 → 确认
    "create_confirm_button": ControlMapping(
        key="create_confirm_button",
        selector=UiaSelector(name_re=r"确定|创建|确认", control_type=50000, scope="descendants"),
        action=PatternKind.INVOKE,
        post_anchor=PostAnchorSpec(
            selector=UiaSelector(name_re=r"开始游戏|开始", control_type=50000, scope="descendants"),
            condition=AnchorCondition.EXISTS,
        ),
        fail_timeout_s=30.0,
    ),
    # 房间页 → 开始游戏
    "room_start_button": ControlMapping(
        key="room_start_button",
        selector=UiaSelector(name_re=r"开始游戏|开始", control_type=50000, scope="descendants"),
        variants=(
            UiaSelector(name_re=r"准备", control_type=50000, scope="descendants"),
        ),
        action=PatternKind.INVOKE,
        post_anchor=PostAnchorSpec(
            selector=UiaSelector(name_re=STAGE_RE, scope="descendants"),
            condition=AnchorCondition.EXISTS,
        ),
        fail_timeout_s=30.0,
    ),
    # 选关页 → 目标关卡（读回必须落在 1-15，1-16 判失败）
    "stage_item": ControlMapping(
        key="stage_item",
        selector=UiaSelector(name_re=STAGE_RE, scope="descendants"),
        action=PatternKind.INVOKE,
        readback=ReadbackSpec(
            kind=ReadbackKind.NAME,
            expected_re=STAGE_RE,
            stability_frames=2,
        ),
        post_anchor=PostAnchorSpec(
            selector=UiaSelector(name_re=r"开始游戏|开始", control_type=50000, scope="descendants"),
            condition=AnchorCondition.EXISTS,
        ),
        fail_timeout_s=30.0,
    ),
    # 选关页 → 开始游戏（进局）
    "stage_start_button": ControlMapping(
        key="stage_start_button",
        selector=UiaSelector(name_re=r"开始游戏|开始", control_type=50000, scope="descendants"),
        action=PatternKind.INVOKE,
        post_anchor=PostAnchorSpec(
            selector=UiaSelector(name_re=r"开始游戏|开始", control_type=50000, scope="descendants"),
            condition=AnchorCondition.ABSENT,  # 选关页消失 = 进入加载/局内
        ),
        fail_timeout_s=30.0,
    ),
    # 局末 → 退出回房（回到房间页）
    "exit_room_button": ControlMapping(
        key="exit_room_button",
        selector=UiaSelector(name_re=r"退出", control_type=50000, scope="descendants"),
        action=PatternKind.INVOKE,
        post_anchor=PostAnchorSpec(
            # 回到房间页：选关页的关卡行消失（房间页本身也有“开始游戏”，
            # 不能用它作 ABSENT 锚点）
            selector=UiaSelector(name_re=STAGE_RE, scope="descendants"),
            condition=AnchorCondition.ABSENT,
        ),
        fail_timeout_s=30.0,
    ),
}
