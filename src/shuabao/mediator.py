"""
中介层：串起 Settings / 场景表 / 截屏找图 / 键鼠 / 阶段状态机。

对齐实机日志（SUCCESS_FLOW.md）：
  环境 → 准备 → 等进入UI → 主线 → 选卡循环
  → 提前挑战 → 锚点Boss → 龙珠 → 退出 → 下一局

Jobs 不直接碰 OpenCV/输入；只通过本中介 see / act。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from pathlib import Path

import cv2
import numpy as np

from shuabao import __version__
from shuabao.incidents import IncidentArchiver
from shuabao.input.emergency_stop import EmergencyStopListener
from shuabao.input.keyboard_mouse import (
    INPUT_DISPATCHED_UNVERIFIED,
    InputExecutor,
    foreground_matches_target,
    get_foreground_window,
    is_window_valid,
    reacquire_target_window,
)
from shuabao.loop_action import LoopAction
from shuabao.scenes import load_scenes, scene_templates
from shuabao.settings import Settings
from shuabao.stop_signal import StopSignal
from shuabao.layout_transform import LayoutTransform
from shuabao.vision.capture import (
    Frame,
    FrameHealthIssue,
    FrameHealthResult,
    L0_WINDOW_KEYWORDS,
    L1_WINDOW_KEYWORDS,
    WindowRole,
    activate_window,
    classify_window_role,
    reacquire_target_window as capture_reacquire_target_window,
    capture,
    capture_target,
    check_frame_health,
    find_window_targets,
)
from shuabao.vision.matcher import (
    MatchResult,
    _load_template,
    find_blue_buttons,
    find_input_boxes,
    match_all,
    match_any,
    match_any_with_margin,
    match_one,
    resolve_template,
)
from shuabao.vision.stage_selector import (
    StageId,
    configured_stage_id,
    find_stage_in_range,
    find_stage_labels,
    find_unselected_old_world_tab,
    selected_stage_row,
    stage_list_scroll_point,
    visible_stage_rows,
)
from shuabao.policy.boss_order import (
    BossOrderAction,
    BossOrderDecision,
    VisibleCard,
    decide_boss_order_action,
    is_slot_empty,
    predict_card_slot,
    parse_boss_order_number,
    LOCATE_FAILURE_FALLBACK_DEFAULT,
)
from shuabao.vision.ocr_shadow.client import ShadowClient
from shuabao.vision.label_boxes import white_text_word_boxes
from shuabao.log_sink import LOGGER, emit_print as print  # noqa: A001
from shuabao.lobby_hitch import (
    JOIN_ATTEMPTS,
    FollowPhase,
    FollowTeamSM,
    HitchAction,
    HitchPhase,
    HitchSearchSM,
    SearchTransaction,
    classify_hitch_ocr,
    has_prefix_evidence,
    normalize_prefix,
)
from shuabao.choice_policy import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_REFRESHES,
    DEFAULT_MAX_WAITS,
    PanelCandidates,
    PolicyAction,
    PolicyDecision,
    PolicySettings,
    SessionState,
    SlotCandidate,
    _is_uncompleted_merge_upgrade,
    assemble_policy_settings,
    choose_action,
    hitch_treasure_pick,
    is_negative_treasure,
    matches_bond_preset,
    same_bond_identity,
    slot_fingerprint,
)
from shuabao.interaction_surface import (
    ActionLifecycle,
    InteractionSurface,
    PendingAction,
    resolve_interaction_surface,
    verify_inventory_item_consumed,
)
from shuabao.merchant_scanner import (
    DISCOUNT_KEYWORDS,
    MerchantScanner,
    MerchantSlotItem,
    MERCHANT_STRIP_ROI,
)
from shuabao.habit_preference import (
    append_learning_observation,
    habit_scores_for_panel,
    load_habit_preference,
)
from shuabao.skill_catalog import grant_on_learn_card
from shuabao.card_fact import CardFact, card_fact_from_slot
from shuabao.policy.mechanics_view import MechanicsPolicyView
from shuabao.policy.equipment_fsm import EquipmentFSM
from shuabao.policy.merchant_fsm import MerchantFSM, MerchantPhase
from shuabao.policy.public_bag import (
    ANCHOR_ROIS,
    EMPTY_SLOT_MAX_SATURATED,
    EMPTY_SLOT_MAX_STD,
    ITEM_BAR_SLOTS,
    OCCUPIED_SLOT_MIN_SATURATED,
    OCCUPIED_SLOT_MIN_STD,
    SLOT_SATURATION_MIN,
    SLOT_VALUE_MIN,
    BagLayout,
    PublicBagFSM,
    PublicBagPhase,
)

# 构建标识：写入 JSONL tick trace（B1-1），用于区分版本/里程碑来源。
# 每次发布里程碑时更新；配合 git 提交哈希可精确定位产生该日志的代码。
BUILD_ID = f"v{__version__}"


@dataclass
class FrameEvidence:
    """单帧感知证据（N2.2）：强引用帧 + 单调 generation + 规范化缓存。

    - ``frame_ref`` 强引用，绝不只依赖 ``id(frame)``；
    - ``gen`` 单调递增：新帧 / 输入成功 / hwnd·scale 变化时推进；
    - ``cache`` 键已规范化：``(kind, names_tuple, threshold, scales, roi, mode_key)``；
    - ``context`` 每 evidence 只算一次，phase handler 直接复用。
    """

    frame_ref: Frame
    gen: int
    ui_scale: float
    hwnd: int | None
    cache: dict[tuple[object, ...], object] = field(default_factory=dict)
    context: str | None = None


@dataclass(frozen=True)
class PlatformModalShell:
    """KK 平台普通提示的视觉外壳，不承载正文或正向按钮语义。"""

    kind: str
    close: MatchResult


class _SceneCacheCompat:
    """兼容 shim：benchmark/旧调用仍访问 ``_scene_cache.clear()``。

    真实缓存语义已由 :class:`FrameEvidence` 承担（N2 清洁切换）；本对象无任何
    读写路径，clear() 为无操作，禁止让旧语义绕过 evidence generation。
    """

    __slots__ = ()

    def clear(self) -> None:
        pass


def _scrub_sensitive_keys(value):
    """递归剔除密码类键（如 room_password），保证 trace 永不携带凭据。

    设置摘要由显式白名单构建，此函数是第二道防线：未来新增的嵌套
    设置字段即使误入白名单，只要键名含 password 也不会落到 trace。
    """
    if isinstance(value, dict):
        return {
            k: _scrub_sensitive_keys(v)
            for k, v in value.items()
            if "password" not in str(k).lower()
        }
    if isinstance(value, list):
        return [_scrub_sensitive_keys(v) for v in value]
    return value


def _is_blank_capture(frame: Frame | None) -> bool:
    """A captured window whose pixels are (near) pure black.

    Same threshold as the lobby black-frame gate.  Invalid/empty captures are
    not "blank": their owner is the minimized/health path, not ranking.
    """
    if frame is None or frame.bgr is None or not frame.bgr.size:
        return False
    return float(np.mean(frame.bgr)) < 3.0


class Phase(Enum):
    """与官方日志阶段大致对应。"""

    BOOT = auto()  # 验证环境
    WAIT_EXIT = auto()  # 等待所有人退出
    LOBBY_ROOM = auto()  # L0 大厅/房间态
    PREPARE = auto()  # 开始/准备游戏
    WAIT_UI = auto()  # 等待进入游戏UI
    PLATFORM_MAP = auto()  # 地图详情页
    CREATE_ROOM = auto()  # 建房弹窗
    ROOM_WAITING = auto()  # 房间已建立，等待开始
    ROOM_STARTING = auto()  # 已点击房间开始，等待游戏窗口
    STAGE_SELECT = auto()  # 选关页
    STAGE_STARTING = auto()  # 已点击关卡开始，等待局内 UI
    HERO_SETUP = auto()  # 英雄模式弹窗：阵营/难度/开启的后置确认链
    ERROR = auto()  # 目标窗口不可用
    MAIN_LINE = auto()  # 开始主线 / 选卡
    EARLY_CHALLENGE = auto()  # 提前挑战
    ANCHOR_BOSS = auto()  # 锚点 Boss
    LONGZHU = auto()  # 找龙珠
    RECOVER_FAILURE = auto()  # S0 ③ 失败/断线有门闩恢复（完成才进 QUIT）
    QUIT = auto()  # 点击局内专用退出按钮
    NEXT = auto()  # 确认退出并返回原 KK 房间
    COMPLETE = auto()  # S0 ⑥ cycle_num 达成：停止 run，绝不点下一局开始


class ChallengeState(Enum):
    PENDING = auto()
    OFF = auto()
    ON = auto()
    UNKNOWN = auto()


class RecoveryKind(Enum):
    """S0 ③ 恢复脚本种类：FAIL 与 DISCONNECT 使用不同 anchors/动作。"""

    FAIL = auto()
    DISCONNECT = auto()


class RecoveryStep(Enum):
    """恢复脚本步骤（每步带 anchor/动作/后置确认门闩）。"""

    FAIL_CONFIRM = auto()  # 失败弹窗可见 → 点 ok（确定）→ 弹窗消失或 close 出现
    FAIL_EXIT_CONFIRM = auto()  # 失败状态 → 左上退出 → 标准退出确认框 → 点确认
    FAIL_CLOSE = auto()    # 确认后出现 close → 点 close → 全部消失
    DISCONNECT_RETRY = auto()  # 断线弹窗可见 → 点 retryConnect（重连）→ 弹窗消失或回局内
    DONE = auto()


# 仅允许全局断线/强失败抢占的真实局内阶段集合（pre-game/大厅/选关等过渡阶段严禁被全局抢占中断）
IN_GAME_FAILURE_PREEMPT_PHASES = {
    Phase.MAIN_LINE,
    Phase.EARLY_CHALLENGE,
    Phase.ANCHOR_BOSS,
    Phase.LONGZHU,
    Phase.QUIT,
}

class RoundOutcome(Enum):
    """S0 终局 outcome：一局只能记录一个（_outcome_recorded 守卫）。"""

    VICTORY = auto()
    FAILURE = auto()
    TIMEOUT = auto()
    DISCONNECT = auto()


class RunExitReason(str, Enum):
    """G0 P0：mediator 终止的唯一停止归因（run() 退出时写入 exit_reason）。

    复用 StopSignal，不引入第二套停止系统：外部 stop reason（F12/Shift+F12
    或 RunnerService/HeadlessRunner）在退出时归 EMERGENCY_STOP/USER_STOP；
    Mediator.stop() 只在尚无外部 stop 时才写信号，绝不覆盖先到的外部 reason。
    """

    USER_STOP = "USER_STOP"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    CONFIGURED_CYCLE_COMPLETE = "CONFIGURED_CYCLE_COMPLETE"
    ARCHAEOLOGY_HANDOFF_COMPLETE = "ARCHAEOLOGY_HANDOFF_COMPLETE"
    UIPI_PERMISSION_FAILURE = "UIPI_PERMISSION_FAILURE"
    FATAL_ENVIRONMENT_FAILURE = "FATAL_ENVIRONMENT_FAILURE"
    PROCESS_CRASH = "PROCESS_CRASH"
    UNEXPECTED_TERMINATION = "UNEXPECTED_TERMINATION"


Outcome = RoundOutcome

class PanelState(Enum):
    """S0 ⑤ 面板会话 FSM：CLOSED→OPEN_REQUESTED→WAIT_VISIBLE→ACTIVE→WAIT_MUTATION→CLOSING→COOLDOWN。"""

    CLOSED = auto()
    OPEN_REQUESTED = auto()
    WAIT_VISIBLE = auto()
    ACTIVE = auto()
    WAIT_MUTATION = auto()
    CLOSING = auto()
    COOLDOWN = auto()


@dataclass(frozen=True)
class FactionSpec:
    """英雄模式声望阵营的界面几何 + 模板配置（2026-08-12）。

    ``card_roi``/``level_roi``/``plus_xy`` 均以 1600x900 客户区坐标衡量。
    卡片网格来自 ``fixtures/live_postgame_20260808/live_archive_start_panel.png``：
    行1（黑锋/银色/肯瑞托/探险者）y=118..286，行2（元素/守护）y=438..606，
    列宽 153px，列间距 207px。

    ``level_roi`` 在录屏 ``20260812_180825.mp4`` 客户区帧上用 ``hero_level_zero``
    滑动匹配校准（六阵营零级自匹配 ≥0.99）；底行数字 Y 比网格公式 +196 多约 5px，
    不可再统一用 ``y1+196``。``plus_xy`` 仍为卡片相对偏移 ``(+110,+209)``，
    与肯瑞托既有真机点 ``(772,327)`` 一致。

    ``verified`` 表示未选中态卡面模板可用（在 ``fixtures/hero_modal_20260812_180825``
    上自匹配 ≥0.90）。完整「点加号 → 等级确认 → 再点」时序链仍只有肯瑞托有
    既有录屏逐步验证；其余阵营仅有同录屏上等级 ROI 像素突变的离线旁证，
    不宣称已完成真机加号闭环。
    """

    rep_type: int
    name: str
    slug: str  # 用于模板文件名与英文 action 名（HeroXxxPlus-N）
    plus_xy: tuple[int, int]
    card_roi: tuple[int, int, int, int]
    level_roi: tuple[int, int, int, int]
    unselected_template: str | None
    card_match_window: tuple[int, int, int, int]  # (x_min,x_max,y_min,y_max) for find() hit position
    verified: bool

    @property
    def action_label(self) -> str:
        return f"Hero{self.slug.capitalize()}Plus"


def _faction_card_roi(col_x1: int, row_y1: int) -> tuple[int, int, int, int]:
    return (col_x1, row_y1, col_x1 + 153, row_y1 + 168)


def _faction_plus_xy(card_roi: tuple[int, int, int, int]) -> tuple[int, int]:
    x1, y1, _x2, _y2 = card_roi
    return (x1 + 110, y1 + 209)


def _faction_card_match_window(card_roi: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x1, y1, _x2, _y2 = card_roi
    return (x1 - 12, x1 + 13, y1 - 8, y1 + 12)


# 行1 4 列 x1：黑锋 248 / 银色 455 / 肯瑞托 662 / 探险者 869（y1=118）
# 行2 2 列 x1：元素 248 / 守护 455（y1=438）
_HEIFENG_CARD_ROI = _faction_card_roi(248, 118)
_YINSE_CARD_ROI = _faction_card_roi(455, 118)
_KENRITO_CARD_ROI = (662, 118, 815, 286)  # 既有已验证数值，未改动
_TANXIAN_CARD_ROI = _faction_card_roi(869, 118)
_YUANSU_CARD_ROI = _faction_card_roi(248, 438)
_SHOUHU_CARD_ROI = _faction_card_roi(455, 438)

# 20260812_180825 客户区上 hero_level_zero 最佳匹配 TL（28x28）
_HEIFENG_LEVEL_ROI = (307, 314, 335, 342)
_YINSE_LEVEL_ROI = (516, 314, 544, 342)
_TANXIAN_LEVEL_ROI = (932, 314, 960, 342)
_YUANSU_LEVEL_ROI = (307, 639, 335, 667)
_SHOUHU_LEVEL_ROI = (516, 639, 544, 667)

FACTION_SPECS: dict[int, FactionSpec] = {
    1: FactionSpec(
        rep_type=1,
        name="黑锋骑士团",
        slug="heifeng",
        plus_xy=_faction_plus_xy(_HEIFENG_CARD_ROI),
        card_roi=_HEIFENG_CARD_ROI,
        level_roi=_HEIFENG_LEVEL_ROI,
        unselected_template="lobby/hero_heifeng_unselected",
        card_match_window=_faction_card_match_window(_HEIFENG_CARD_ROI),
        verified=True,
    ),
    2: FactionSpec(
        rep_type=2,
        name="银色北伐军",
        slug="yinse",
        plus_xy=_faction_plus_xy(_YINSE_CARD_ROI),
        card_roi=_YINSE_CARD_ROI,
        level_roi=_YINSE_LEVEL_ROI,
        unselected_template="lobby/hero_yinse_unselected",
        card_match_window=_faction_card_match_window(_YINSE_CARD_ROI),
        verified=True,
    ),
    3: FactionSpec(
        rep_type=3,
        name="肯瑞托",
        slug="kenrito",
        plus_xy=(772, 327),  # 既有已验证数值，未改动
        card_roi=_KENRITO_CARD_ROI,
        level_roi=(724, 314, 752, 342),  # 既有已验证数值，未改动
        unselected_template="lobby/hero_kenrito_unselected",
        card_match_window=(650, 675, 110, 130),  # 既有已验证数值，未改动
        verified=True,
    ),
    4: FactionSpec(
        rep_type=4,
        name="探险者协会",
        slug="tanxian",
        plus_xy=_faction_plus_xy(_TANXIAN_CARD_ROI),
        card_roi=_TANXIAN_CARD_ROI,
        level_roi=_TANXIAN_LEVEL_ROI,
        unselected_template="lobby/hero_tanxian_unselected",
        card_match_window=_faction_card_match_window(_TANXIAN_CARD_ROI),
        verified=True,
    ),
    5: FactionSpec(
        rep_type=5,
        name="元素领主",
        slug="yuansu",
        plus_xy=_faction_plus_xy(_YUANSU_CARD_ROI),
        card_roi=_YUANSU_CARD_ROI,
        level_roi=_YUANSU_LEVEL_ROI,
        unselected_template="lobby/hero_yuansu_unselected",
        card_match_window=_faction_card_match_window(_YUANSU_CARD_ROI),
        verified=True,
    ),
    6: FactionSpec(
        rep_type=6,
        name="守护巨龙",
        slug="shouhu",
        plus_xy=_faction_plus_xy(_SHOUHU_CARD_ROI),
        card_roi=_SHOUHU_CARD_ROI,
        level_roi=_SHOUHU_LEVEL_ROI,
        unselected_template="lobby/hero_shouhu_unselected",
        card_match_window=_faction_card_match_window(_SHOUHU_CARD_ROI),
        verified=True,
    ),
}


@dataclass
class RecoveryState:
    """S0 ③ 恢复状态：步骤门闩 + 有限预算。

    - 一步从 READY（等待锚点）进入 WAIT_CONFIRM（已点击，等待 mutation/后置锚点）；
    - 每步尝试上限 recovery_action_limit、间隔 recovery_retry_interval_s、
      总预算 recovery_timeout_s（开始时固定，任何 periodic 行为不得续期）。
    """

    kind: RecoveryKind
    step: RecoveryStep
    started_at: float
    deadline: float
    attempts: dict = field(default_factory=dict)
    next_allowed_at: float = 0.0
    anchor_before: "MatchResult | None" = None
    input_ok: bool = False
    mutation_seen: bool = False
    post_anchor_seen: bool = False
    waiting_confirm: bool = False
    input_at: float = 0.0
    confirm_window: float = 15.0
    direct_exit: bool = False
    opening_exit_confirm: bool = False
    # The modal's red 退出游戏 did nothing (live 2026-09-12: the game chat
    # input lay over the button row).  Further attempts use the top-left
    # 退出游戏 + standard confirmation instead.
    prefer_game_exit: bool = False


@dataclass
class AttemptBudget:
    """Fixed, fail-closed allowance for one stage-selection episode."""

    started_at: float
    hard_deadline: float
    actions_left: int
    retries_left: int

    def exhausted(self, now: float) -> bool:
        return now >= self.hard_deadline or self.actions_left <= 0 or self.retries_left <= 0

    def consume_action(self, now: float) -> bool:
        if now >= self.hard_deadline or self.actions_left <= 0:
            return False
        self.actions_left -= 1
        return True

    def consume_retry(self, now: float) -> bool:
        if now >= self.hard_deadline or self.retries_left <= 0:
            return False
        self.retries_left -= 1
        return True


_REAL_TIME = time.time  # captured at import; immune to test-time patching of time.time


class AgingBlacklist:
    """Session blacklist with TTL aging to prevent room pool starvation in multi-hour runs."""

    def __init__(self, ttl_s: float = 1800.0) -> None:
        self._entries: dict[str, float] = {}
        self.ttl_s = ttl_s

    def add(self, key: str, added_at: float | None = None) -> None:
        if key:
            # Expiry checks compare against time.time(), which tests may patch
            # to a frozen past epoch. Clock-less adds therefore clamp UP to the
            # real wall clock (identical to time.time() in production) so an
            # entry is never born already expired; explicit added_at is honored
            # verbatim.
            self._entries[str(key)] = (
                float(added_at) if added_at is not None else max(time.time(), _REAL_TIME())
            )

    def prune(self, now: float | None = None) -> None:
        t = time.time() if now is None else float(now)
        expired = [k for k, v in self._entries.items() if t - v >= self.ttl_s]
        for k in expired:
            del self._entries[k]

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str) or key not in self._entries:
            return False
        if time.time() - self._entries[key] >= self.ttl_s:
            del self._entries[key]
            return False
        return True

    def __len__(self) -> int:
        self.prune()
        return len(self._entries)

    def __iter__(self):
        self.prune()
        return iter(list(self._entries.keys()))

    def clear(self) -> None:
        self._entries.clear()

    def discard(self, key: str) -> None:
        self._entries.pop(key, None)


class Mediator:
    _CREATE_ROOM_CONFIRM_WINDOW_S = 4.0
    _CREATE_ROOM_TOTAL_TIMEOUT_S = 60.0
    # Compatibility aliases retained for older tests/diagnostics.  They no
    # longer terminate a recoverable alignment loop by click count.
    _CREATE_ROOM_DOWNLOAD_WAIT_S = _CREATE_ROOM_TOTAL_TIMEOUT_S
    _CREATE_ROOM_MAX_ATTEMPTS = 3
    _L0_TRANSITION_TIMEOUT_S = 60.0
    _STAGE_ACTION_LIMIT = 12
    _STAGE_RETRY_LIMIT = 2
    _STAGE_SELECT_LIMIT = 3
    # Title-only bands calibrated against the recorded 1600x900 game frames.
    # The previous bands included a large amount of card background above the
    # title; on red bond glyphs that pushed the recognizer toward progress
    # digits and single-character false matches.  Keep the lower edge wide
    # enough for the inline (x/y) suffix, which is useful for stack decisions.
    _OCR_SLOT_ROIS = {
        "skill": ((0.286, 0.190, 0.421, 0.255), (0.433, 0.190, 0.568, 0.255), (0.579, 0.190, 0.714, 0.255)),
        "bond": ((0.254, 0.190, 0.410, 0.228), (0.425, 0.190, 0.581, 0.228), (0.596, 0.190, 0.752, 0.228)),
        "treasure": ((0.286, 0.205, 0.418, 0.265), (0.433, 0.205, 0.565, 0.265), (0.582, 0.205, 0.714, 0.265)),
    }
    _OCR_SLOT_ROIS_4 = {
        "skill": ((0.210, 0.190, 0.330, 0.255), (0.355, 0.190, 0.475, 0.255), (0.500, 0.190, 0.620, 0.255), (0.645, 0.190, 0.765, 0.255)),
        "bond": ((0.185, 0.190, 0.325, 0.228), (0.340, 0.190, 0.480, 0.228), (0.495, 0.190, 0.635, 0.228), (0.650, 0.190, 0.790, 0.228)),
        "treasure": ((0.210, 0.205, 0.330, 0.265), (0.355, 0.205, 0.475, 0.265), (0.500, 0.205, 0.620, 0.265), (0.645, 0.205, 0.765, 0.265)),
    }
    _CHOICE_SLOT_CENTERS = {
        "skill": ((0.354, 0.42), (0.500, 0.42), (0.646, 0.42)),
        "bond": ((0.331, 0.44), (0.503, 0.44), (0.676, 0.44)),
        "treasure": ((0.352, 0.42), (0.500, 0.42), (0.648, 0.42)),
    }
    _CHOICE_SLOT_CENTERS_4 = {
        "skill": ((0.270, 0.42), (0.415, 0.42), (0.560, 0.42), (0.705, 0.42)),
        "bond": ((0.255, 0.44), (0.410, 0.44), (0.565, 0.44), (0.720, 0.44)),
        "treasure": ((0.270, 0.42), (0.415, 0.42), (0.560, 0.42), (0.705, 0.42)),
    }
    _OCR_DESC_ROIS = {
        "treasure": {
            # Reuse the live 3-card centers.  The previous centers came from
            # an older capture and shifted the middle/right description band
            # several pixels left on the current 1600x900 client frame.
            "centers_x": (0.352, 0.500, 0.648),
            # Match one card's content width.  The old 0.088 band crossed
            # neighboring card edges on the 1600x900 live panel.
            "half_w": 0.066,
            # Description text begins below the icon.  The previous band
            # included most of the icon and made the recognizer return
            # punctuation/digits instead of the first description lines.
            "y0": 0.350,
            "y1": 0.405,
            "scan_y1": 0.550,
        },
    }
    _OCR_DESC_ROIS_4 = {
        "treasure": {
            "centers_x": (0.270, 0.415, 0.560, 0.705),
            "half_w": 0.065,
            "y0": 0.350,
            "y1": 0.405,
            "scan_y1": 0.550,
        },
    }
    _RARITY_LETTER_TO_BAND = {
        "EX": "red",
        "UR": "red",
        "SSR": "orange",
        "SR": "purple",
        "R": "blue",
        "N": "green",
    }
    _RARITY_BADGE_ROIS_4 = {
        "bond": (
            (0.224, 0.150, 0.266, 0.195),
            (0.396, 0.150, 0.438, 0.195),
            (0.568, 0.150, 0.610, 0.195),
            (0.740, 0.150, 0.782, 0.195),
        ),
        "skill": (
            (0.248, 0.150, 0.292, 0.195),
            (0.393, 0.150, 0.437, 0.195),
            (0.538, 0.150, 0.582, 0.195),
            (0.683, 0.150, 0.727, 0.195),
        ),
        "treasure": (
            (0.248, 0.150, 0.292, 0.195),
            (0.393, 0.150, 0.437, 0.195),
            (0.538, 0.150, 0.582, 0.195),
            (0.683, 0.150, 0.727, 0.195),
        ),
        "card": (
            (0.224, 0.150, 0.266, 0.195),
            (0.396, 0.150, 0.438, 0.195),
            (0.568, 0.150, 0.610, 0.195),
            (0.740, 0.150, 0.782, 0.195),
        ),
    }
    _RARITY_BADGE_ROIS = {
        "bond": (
            (0.306, 0.150, 0.356, 0.195),
            (0.478, 0.150, 0.528, 0.195),
            (0.651, 0.150, 0.701, 0.195),
        ),
        "skill": (
            (0.328, 0.150, 0.378, 0.195),
            (0.475, 0.150, 0.525, 0.195),
            (0.622, 0.150, 0.672, 0.195),
        ),
        "treasure": (
            (0.327, 0.150, 0.377, 0.195),
            (0.475, 0.150, 0.525, 0.195),
            (0.623, 0.150, 0.673, 0.195),
        ),
        "card": (
            (0.306, 0.150, 0.356, 0.195),
            (0.478, 0.150, 0.528, 0.195),
            (0.651, 0.150, 0.701, 0.195),
        ),
    }
    # cards/*.png title glyphs: 0.80 < live baoji/tz/jj, > next-best false ~0.54
    _BOND_TITLE_TEMPLATE_MIN = 0.80

    def __init__(
        self,
        settings: Settings,
        project_root: Path,
        stop_signal: StopSignal | None = None,
        incident_dir: str | Path | None = None,
    ):
        self.settings = settings
        self.root = project_root
        self.images = settings.images_path(project_root)
        self.scenes_doc = load_scenes(project_root)
        self.stop_signal = stop_signal or StopSignal()
        self.executor = InputExecutor(stop_signal=self.stop_signal)
        self.emergency_listener: EmergencyStopListener | None = None
        self.phase = Phase.BOOT
        # G0 P0 可观测性：run 终止归因 + 最近业务/恢复动作 + 窗口快照。
        self.exit_reason: RunExitReason | None = None
        self.last_business_action: str | None = None
        self.recent_recovery_actions: list[str] = []
        self.last_window_role: str | None = None
        self.last_window_hwnd: int | None = None
        self.game_platform_window_snapshot: dict[str, bool] = {}
        self._archaeology_handoff_confirmed: bool = False
        self.game_count = 0
        self._running = False
        self._longzhu_deadline: float | None = None
        self._f1_fallback_done = False
        self._boss_clicked = False  # ANCHOR_BOSS 是否已尝试点击
        self._stage_click_cooldown_until = 0.0
        self._stage_scroll_cooldown_until = 0.0
        self._stage_selected = False
        self._stage_target_name: str | None = None
        self._stage_target_position: tuple[int, int] | None = None
        self._stage_candidate_name: str | None = None
        self._stage_candidate_position: tuple[int, int] | None = None
        self._stage_candidate_frames = 0
        self._stage_select_attempts = 0
        self._room_dialog_filled = False
        self._room_form_step = 0
        self._room_action_deadline: float | None = None
        self._room_action_attempts = 0
        # ROOM_STARTING is a transition alignment episode.  The deadline is
        # fixed when RoomStart is first accepted; retries are time-spaced and
        # never extend the macro deadline.
        self._room_start_deadline: float | None = None
        self._room_start_next_retry_at: float = 0.0
        # startChallenge 显式子状态机（STAGE_STARTING 分支内部状态，枚举不变）：
        # WAIT_TRANSITION → VERIFY_INGAME → DONE，带超时/失败分支/有界重试
        self._challenge_start_state: str | None = None   # WAIT_TRANSITION/VERIFY_INGAME/DONE
        self._challenge_start_source: str = "stage"      # stage / hero
        self._challenge_start_attempts: int = 0
        self._challenge_start_deadline: float | None = None
        self._challenge_start_hud_frames: int = 0        # VERIFY_INGAME 连续锚点帧计数
        self._challenge_start_hero_modal_frames: int = 0 # hero 弹窗消失计数
        self._stage_scroll_attempts = 0
        self._stage_attempt_budget: AttemptBudget | None = None
        # 旧世大陆页签切换尝试预算（上限 2 次）：防 UI 刷新延迟/模板残影导致的
        # livelock 连点，超限 Fail-Closed 停机。
        self._old_world_switch_attempts = 0
        self._missing_window_since: float | None = None
        self._last_frame: Frame | None = None
        self._prev_frame: Frame | None = None
        self._last_capture_role: str | None = None
        # 每次 see() 都代表一次新的应用采集观察，即使像素与上一帧完全相同。
        # Lobby modal 的恢复门禁使用这个 generation，不使用 Python Frame identity。
        self._capture_generation = 0
        # N2.2：单帧感知证据（FrameEvidence.cache 取代旧 _scene_cache / 每 tick clear）
        self._evidence: FrameEvidence | None = None
        self._tick_evidence: FrameEvidence | None = None
        self._tick_gen: int | None = None
        # N2-REVIEW #3：独立输入序列号——每次成功输入（含 dry-run 观测）递增，
        # 用于动作授权（本 tick 至多一个输入、缓存命中不延续旧帧授权）；
        # 与 evidence.gen/缓存解耦：dry-run 不丢性能复用（benchmark exact-static）。
        self._input_seq = 0
        self._tick_input_seq: int | None = None
        self._last_input_status = ""
        self._last_input_at: float | None = None
        # 本 tick 落定的后置确认（选择面板 mutation / 公共背包存入）；每 tick 归零。
        self._tick_post_confirm: bool | None = None
        # trace/incident 兼容镜像：_detect_context 每次计算后同步（evidence.context 是权威值）
        self._context_cache_value = "UNKNOWN"
        # 多窗口捕获：上次健康 hwnd 优先；连续 N=2 不健康/失配才枚举候选
        self._capture_miss_streak = 0
        self._capture_candidates = 0
        self._confirmed_room_hwnd: int | None = None
        # N2.3：白名单 reason（无法解释 tick>1s=0 审计）与输入标记
        self._tick_reason: str | None = None
        self._tick_input_executed = False
        self._last_capture_ms = 0.0
        # 会话级 UI 缩放（1600x900 基准）：窗口非基准分辨率（如 960x540=0.6x）
        # 时，模板匹配 scales 需包含 ui_scale 邻域才能命中。
        self._ui_scale: float = 1.0
        # JSONL tick trace：卡死/误操作诊断（set_trace 开启）
        self._trace_path: str | None = None
        self._trace_fh = None
        self._tick_no = 0
        self._trace_actions: list[dict] = []
        self._trace_scenes: list[dict] = []
        self._trace_controls: list[dict] = []
        # 局内观测记录器（默认关闭；SHUABAO_OBSERVE=1 打开）。
        # 只读旁路：不发输入、不改任何 live 状态，只往 JSONL 写观测。
        self._observe = None
        self._observe_ready = False
        self._observe_plan = (None, "")
        # trace 帧指纹缓存：(Frame 强引用, fingerprint)；用 is 判同，避免
        # id 复用导致同址新 Frame 误命中旧指纹。
        self._trace_fingerprint_cache: tuple | None = None
        self._interrupt_reason: str | None = None
        # Safety: L0 cycle counter — prevent infinite PLATFORM_MAP ↔ ROOM_WAITING loops
        self._l0_cycle_count = 0
        self._l0_cycle_limit = 5
        refresh_lo, refresh_hi = 5.0, 5.0
        try:
            from shuabao.shell.mode_catalog import hitch_refresh_window

            refresh_lo, refresh_hi = hitch_refresh_window()
        except Exception:
            pass
        prefixes_raw = getattr(settings, "hitch_stage_prefix", "3")
        prefix_list = [p.strip() for p in str(prefixes_raw).replace("，", ",").split(",") if p.strip()]
        rotate_int = int(getattr(settings, "hitch_rotate_interval", 1) or 1)
        search_budget = max(JOIN_ATTEMPTS, rotate_int * max(1, len(prefix_list)))
        self._hitch_sm = HitchSearchSM(
            prefix=prefix_list[0] if prefix_list else "3",
            prefixes=prefix_list or ["3"],
            rotate_interval=rotate_int,
            join_limit=search_budget,
            refresh_s_min=refresh_lo,
            refresh_s_max=refresh_hi,
        )
        self._hitch_ocr_override: str | None = None
        self._hitch_match_override: bool | None = None
        self._hitch_hit_override = None
        self._hitch_lobby_home_override: bool | None = None
        self._hitch_re_search = False
        self._hitch_status = ""
        self._hitch_join_refresh_count = 0
        # One optional transaction replaces the old
        # ``_hitch_prefix_searched`` / ``_hitch_search_pending`` pair.
        self._hitch_search: SearchTransaction | None = None
        self._hitch_search_ocr_next_at = 0.0
        self._hitch_search_ocr_error_logged_at = 0.0
        self._hitch_rejected_row_ys: set[int] = set()
        self._hitch_pending_row_y: int | None = None
        self._hitch_join_origin_hwnd: int | None = None
        # 平台普通提示默认 Esc；输入成功后必须等 fresh 帧证明 shell 消失。
        self._hitch_popup_esc_attempts = 0
        self._hitch_popup_esc_last_at: float | None = None
        self._hitch_platform_prompt_click_at: float | None = None
        # 无进展看门狗：UNKNOWN 起点；与 _last_input_at 取较晚者计时。
        self._hitch_unknown_since: float | None = None
        self._hitch_room_window_hwnd: int | None = None
        self._hitch_platform_modal_input_frame: Frame | None = None
        self._hitch_platform_modal_input_observation: tuple[int, float] | None = None
        self._hitch_platform_modal_last_action: str | None = None
        self._hitch_platform_modal_reobserve_until: float | None = None
        self._hitch_platform_modal_reacquire_attempts = 0
        # Session-local blacklist keyed by the visible lobby room-number cell.
        self._hitch_blacklisted_room_keys = AgingBlacklist(ttl_s=1800.0)
        self._hitch_pending_room_key: str | None = None
        self._hitch_host_difficulty_since: float | None = None
        self._hitch_floor_exit_pending = False
        self._hitch_floor_exit_confirmed = False
        self._hitch_floor_exit_attempted_at: float | None = None
        self._hitch_floor_exit_deadline: float | None = None
        self._hitch_floor_exit_input_generation: int | None = None
        self._hitch_floor_exit_reobserve_until: float | None = None
        # One room-exit transaction: Exit click -> (separate 440x260 confirm
        # HWND) -> Confirm -> fresh lobby.  Clicks are counted and the whole
        # transaction has a hard cap so a swallowed click cannot park the run.
        self._hitch_floor_exit_started_at: float | None = None
        self._hitch_floor_exit_clicks = 0
        self._hitch_floor_exit_confirm_clicks = 0
        self._hitch_floor_exit_confirm_at: float | None = None
        # Seat rules (user, 2026-09-11): ready or not, leave when we are the
        # host, when we sit on floor one (row 1), or when the floor-one player
        # leaves.  Our own row is learnt from the Ready transaction.
        self._hitch_pre_ready_rows: list[str] | None = None
        self._hitch_member_room_hwnd: int | None = None
        self._hitch_self_row: int | None = None
        self._hitch_floor_one_baseline: np.ndarray | None = None
        self._hitch_floor_one_candidate: np.ndarray | None = None
        # (decision, capture generation, fresh confirmations)
        self._hitch_seat_streak: tuple[str, int, int] | None = None
        self._hitch_seat_generation: int | None = None
        # HWNDs that existed before the join click.  A pre-existing window can
        # never be the child a join just opened (a stale black room window
        # pinned the 2026-09-11 live runs for minutes).
        self._hitch_join_preexisting_hwnds: frozenset[int] = frozenset()
        self._last_l0_target_hwnds: tuple[int, ...] = ()
        self._capture_black_hwnds: tuple[int, ...] = ()
        self._capture_selected_by: str | None = None
        # KK main-window navigation fallback (user, 2026-09-11): when the lobby
        # window is on some other page, first the top "游戏" tab, then the
        # 英雄三国 / 重生魔兽刷刷刷 sidebar entry.  Bounded per off-page episode.
        self._hitch_nav_since: float | None = None
        self._hitch_nav_clicks = 0
        self._hitch_nav_last_click_at: float | None = None
        self._hitch_nav_input_generation: int | None = None
        self._game_chat_frames = 0
        self._game_chat_close_attempts = 0
        self._game_chat_close_next_at = 0.0
        self._game_chat_last_frame: Frame | None = None
        # 秘境/团本 detection during the post-heirloom wait.
        self._hitch_instance_seen = False
        self._hitch_instance_frames = 0
        self._hitch_instance_announced = False
        self._hitch_instance_last_frame: Frame | None = None
        # Hitch liveness ladder (see _hitch_liveness_supervise).
        self._liveness_last_progress_at: float | None = None
        self._liveness_level = 0
        self._liveness_level_at: float | None = None
        self._liveness_family: str | None = None
        self._liveness_family_since: float | None = None
        self._hitch_dwell_room_left = False
        # Our last click left the pointer on a HUD control whose tooltip can
        # cover what the next step reads (see _note_pointer_on_hud).
        self._pointer_needs_park = False
        # Passenger V retry spacing after a "no treasure choices" click.
        self._hitch_treasure_retry_at = 0.0
        # A bag visit that left movable items in the personal grid.
        self._public_bag_personal_leftover = False
        # Verified game exit time: the closing window is not re-adopted.
        self._hitch_game_exit_at: float | None = None
        # P0-6：Ready 70s 超时退房生命周期（确认离房+大厅可见后才拉黑）
        self._hitch_ready_timeout_pending: bool = False
        self._hitch_ready_timeout_leave_at: float | None = None
        self._hitch_ready_confirmed_at: float | None = None
        # Only the natural lobby -> joined room -> Ready -> fresh HUD path may
        # own the opening pressure-transfer gate.  A mid-game attach starts
        # false and therefore never guesses that the opening action is pending.
        self._hitch_opening_pressure_armed = False
        # P0-4：压力转移点击后的后置条件验证锚点（fresh 帧按钮消失才算成功）。
        # 用户规则 2026-09-12：按钮可见即优先点，不可见绝不阻塞局内流程。
        self._hitch_pressure_click_at: float | None = None
        self._hitch_pressure_seen_since: float | None = None
        self._hitch_pressure_request_generation: int | None = None
        self._hitch_pressure_retry_count: int = 0
        self._hitch_refresh_required = False
        self._follow_sm = FollowTeamSM()
        self._hitch_search_actions: list[str] = []
        # L0 建房请求：点击成功不等于弹窗已打开，必须等待专用锚点确认。
        self._create_room_pending_since: float | None = None
        self._create_room_next_observe_at: float | None = None
        self._create_room_flow_deadline: float | None = None
        self._create_room_attempts = 0
        self._create_room_opened_ok = False
        self._create_room_last_candidate: dict | None = None
        # Safety: MAIN_LINE idle deadline — prevent infinite idle on unexpected screens
        self._main_line_since: float | None = None
        self._main_line_started_at: float | None = None
        self._pressure_next_at: float = 0.0
        # L1 reward/challenge actions are one-shot until the next game.
        self._selection_click_cooldown_until = 0.0
        self._challenge_done: set[str] = set()
        self._challenge_attempts: dict[str, int] = {}
        self._challenge_unknown_since: dict[str, float] = {}
        self._challenge_pending_since: dict[str, float] = {}
        self._challenge_next_observe_at: dict[str, float] = {}
        self._challenge_states: dict[str, ChallengeState] = {
            "coin_challenge": ChallengeState.PENDING,
            "wood_challenge": ChallengeState.PENDING,
            "experience_challenge": ChallengeState.PENDING,
            "treasure_challenge": ChallengeState.PENDING,
        }
        self._auto_task_done: bool = False
        self._auto_task_attempts: int = 0
        self._auto_task_pending_since: float | None = None
        self._auto_task_next_observe_at: float | None = None
        self._auto_task_recheck_at: float = 0.0
        self._auto_task_unknown_since: float | None = None
        self._control_recheck_interval_s: float = 120.0
        self._challenge_recheck_at: dict[str, float] = {}
        # P1-B1: victory-continue flow (multi-anchor post-game classification).
        self._victory_continue_attempts: int = 0
        self._victory_continue_since: float | None = None
        # While True, frames that no classifier recognizes must yield ZERO input
        # (no auto-task / challenge / stage actions) until timeout -> ERROR.
        self._post_game_pending: bool = False
        # One immutable budget for the visible post-game UI transaction.
        # Successful SendInput is not proof that Continue/X/NPC changed it.
        self._hitch_postgame_started_at: float | None = None
        self._post_game_close_attempts: int = 0
        self._post_game_hud_confirmations: int = 0
        self._pending_archive_panel_frames: int = 0
        self._post_game_archive_pending_only: bool = False
        # 战后顺序只复用已有页面分类与 handler，不承载新的业务 FSM：
        # Continue 后优先处理存档页；页面被关闭后才从挑战广场进入传家宝，
        # 最后回到既有秘境/退出分支。默认 secret 保持旧的“直接秘境”行为，
        # 只有本轮 Continue 明确打开战后链时才切到 archive。
        self._post_game_route: str = "secret"
        # 战后存档挑战面板的 4x2 卡位只属于已分类的 ARCHIVE_PANEL。
        # 这是一次性访问游标，不是第二套业务 FSM；每个卡位最多发出一次输入，
        # 面板消失后由既有 MAIN_LINE/胜利链继续收敛。
        self._archive_challenge_index: int = 0
        self._archive_challenge_next_at: float = 0.0
        # Sweep bookkeeping (owner 2026-09-14): cards clicked in the 1->8
        # sweep, and those already re-checked by the single verify pass.
        self._archive_challenge_clicked: set[int] = set()
        self._archive_challenge_verified: set[int] = set()
        self._archive_verify_started: bool = False
        self._archive_challenge_observe_attempts: int = 0
        self._archive_challenge_click_attempts: int = 0
        # 同一张卡点了几次却还没出现绿色「已挑战」。
        self._archive_challenge_confirm_attempts: int = 0
        # 传家宝 Boss 点击时刻与后置确认结果（None = 没点过）。
        self._heirloom_boss_clicked_at: float | None = None
        self._heirloom_boss_confirm_unconfirmed: bool = False
        self._hitch_heirloom_exit_since: float | None = None
        self._solo_heirloom_boss_waiting: bool = False
        self._solo_heirloom_boss_waiting_since: float | None = None
        self._heirloom_boss_result_confirmed: bool = False
        self._solo_heirloom_boss_clear_frames: int = 0
        self._solo_heirloom_boss_clear_last_frame: Frame | None = None
        self._post_game_hero_focus_lost_count: int = 0
        self._post_game_hero_focus_last_frame: Frame | None = None
        self._post_game_hero_focus_next_check_at: float = 0.0
        self._opportunistic_merchant_next_at: float = 0.0
        self._opportunistic_hero_card_next_at: float = 0.0
        self._passenger_heirloom_for_secret = False
        # Heirloom label OCR fallback: last (box, frame) sighting + throttle.
        self._hub_label_ocr_last: tuple | None = None
        self._hub_label_ocr_next_at: float = 0.0
        self._time_cave_boss_search_attempts: int = 0
        self._time_cave_boss_done: bool = False
        self._time_cave_boss_clicked_at: float | None = None
        self._hitch_postgame_hero_selected: bool = False
        self._hitch_postgame_returned_to_base: bool = False
        self._post_game_hub_entered_at: float | None = None
        self._post_game_active_wait_since: float | None = None
        self._team_exit_ocr_next_at = 0.0
        self._team_exit_ocr_hits = 0
        self._team_exit_ocr_error_logged_at = 0.0
        # Optional post-victory great-rift chain.  Every input has a dedicated
        # anchor and a bounded post-click observation window.
        self._secret_realm_request_pending: bool = False
        self._secret_realm_request_since: float | None = None
        self._secret_realm_request_attempts: int = 0
        self._secret_realm_next_observe_at: float = 0.0
        self._secret_realm_entering_since: float | None = None
        self._secret_realm_confirm_attempts: int = 0
        self._secret_realm_confirm_next_observe_at: float = 0.0
        self._secret_realm_hud_confirmations: int = 0
        self._secret_realm_last_hud_frame_id: int | None = None
        self._secret_realm_active: bool = False
        # 传家宝/时光之穴 Boss 提前挑战（legacy GetBoss 语义移植）：
        # 有界尝试 + 冷却，防止入口残影连点；每局进入 MAIN_LINE 时重置。
        self._boss_challenge_attempts: int = 0
        # Post-game Boss cards may be below the initially visible rows. This
        # is only list navigation telemetry; the existing BossConfigured
        # handler still owns recognition, click, and postcondition decisions.
        self._boss_challenge_scroll_attempts: int = 0
        # A list must prove that it has stopped moving before its physical last
        # card becomes a fallback target.  A fixed number of scrolls can stop
        # halfway down a long time-cave list.
        self._boss_challenge_scroll_signature: str | None = None
        self._boss_challenge_scroll_stable_frames: int = 0
        self._boss_challenge_unresolved_attempts: int = 0
        self._boss_challenge_locate_attempts: int = 0
        self._boss_challenge_next_at: float = 0.0
        self._exit_button_attempts: int = 0
        self._exit_confirm_attempts: int = 0
        self._exit_since: float | None = None
        self._exit_rearm_attempts: int = 0
        self._awaiting_room_return: bool = False
        # G0 P0 contract #7：同房返回后先离开旧房（语义控件 request→fresh 证据）。
        self._room_leave_pending: bool = False
        self._room_leave_next_at: float = 0.0
        self._room_leave_attempts: int = 0
        # G0 P0 contract #8：cycle 完成 + auto_archaeology 的 handoff 标记。
        # G0 Phase B：考古模板 miss 时的有界 reobserve 计数；超界 FATAL。
        self._archaeology_template_miss_budget = 40
        self._archaeology_handoff_pending: bool = False
        # 交接用的房间是不是我们自己建的。别人的蹭车房里绝不能点开始；
        # 自建房里必须点，否则选关页永远不出现（见 ROOM_WAITING 分支）。
        self._archaeology_handoff_own_room: bool = False
        # 挑战券预算：最近一次可信读数 + 自那以后已完成的局数。
        # 读不出不等于 0 —— balance 为 None 时预算模型直接弃权，不做任何限制。
        self._ticket_balance: int | None = None
        self._ticket_balance_at: float | None = None
        self._ticket_rounds_since_read: int = 0
        self._ticket_next_read_at: float = 0.0
        self._hitch_goal_archaeology_handoff: bool = False
        self._archaeology_click_at: float | None = None
        self._archaeology_click_generation: int | None = None
        self._archaeology_click_attempts: int = 0
        self._selection_unknown_attempts: int = 0
        self._selection_unknown_since: float | None = None
        self._selection_repeat_key: tuple[str, str, int, int] | None = None
        self._selection_repeat_attempts = 0
        self._skill_refresh_attempts = 0
        # L1 选卡策略会话（choice_policy.SessionState）；按 panel episode 重置。
        self._choice_session = SessionState()
        self._choice_fp_before_refresh: str | None = None
        self._choice_policy_idle = False
        self._choice_policy_last_reason = ""
        self._ocr_confirm_key: tuple | None = None
        self._hitch_last_treasure_kill_balance: int | None = None
        self._hitch_treasure_kill_none_skips: int = 0
        self._hitch_treasure_kill_none_first_at: float | None = None
        self._hitch_treasure_total_refreshes: int = 0
        self._hitch_last_treasure_unconfirmed_fp: str | None = None
        self._treasure_consecutive_no_pick: int = 0
        # L1 运行时技能卡归属：pending = 点击后等待 WAIT_MUTATION 确认（episode 级）；
        # owned = 已确认学得（round 级，set_phase(MAIN_LINE) 重置）。未确认点击
        # 超时只清 pending，绝不写入 owned（未知/未验证不记账）。
        # 使用列表保留同卡多次学习；目录里存在明确的 x2 前置。
        self._skill_cards_pending: list[str] = []
        self._skill_cards_owned: list[str] = []
        self._bond_cards_pending: list[str] = []
        self._bond_cards_owned: list[str] = []
        # ---- S0 ② 全局抢占：每类强证据独立连续帧计数（同 evidence generation 才累计）----
        self._failure_candidate_frames: int = 0
        self._failure_candidate_kind: str | None = None
        self._failure_candidate_gen: int | None = None
        # S0 ③ 恢复：结构化 RecoveryState 取代字符串 _recovery_step（后者仅作
        # trace/benchmark 兼容镜像：DONE/None，不承载推进语义）。
        self._recovery_state: RecoveryState | None = None
        self._recovery_step: str | None = None
        # S0 ④ round hard deadline（进入 MAIN_LINE 时固定，不可续期）
        self._round_started_at: float | None = None
        self._round_deadline: float | None = None
        # S0 ⑥ 跨局语义：一局一个 outcome + 独立计数
        self._outcome_recorded: bool = False
        self._round_outcome: RoundOutcome | None = None
        self._last_outcome: RoundOutcome | None = None
        self._success_count = 0
        self._failure_count = 0
        self._disconnect_count = 0
        self._timeout_count = 0
        self._failure_streak = 0
        # S0 ⑤ 面板会话 FSM + F1 shadow 灰度
        self._panel_state = PanelState.CLOSED
        self._panel_kind: str | None = None
        self._panel_episode_id: str | None = None
        self._panel_first_seen_at: float | None = None
        self._panel_last_progress_at: float | None = None
        self._panel_hard_deadline_s: float = 10.0
        self._panel_executed_actions: int = 0
        self._panel_confirmed_actions: int = 0
        self._panel_closing_attempts: int = 0
        self._panel_closing_started_at: float | None = None
        self._panel_episode_started: float | None = None
        self._panel_visible_deadline: float | None = None
        self._panel_mutation_baseline: Frame | None = None
        self._panel_last_input_at: float = 0.0
        self._panel_confirm_window: float = 8.0
        self._panel_episode_count: dict[str, int] = {}
        self._panel_cooldown_until: dict[str, float] = {}
        self._panel_fingerprint: tuple | None = None
        self._panel_fingerprint_attempts = 0
        # F draw liveness must survive generic panel episode resets.
        self._f_draw_fingerprint: str | None = None
        self._f_draw_first_seen_at: float | None = None
        self._f_draw_last_reopen_at: float | None = None
        self._f_draw_reopen_count: int = 0
        self._f_draw_backoff_until: float = 0.0
        # WAIT_MUTATION proves a panel mutation/disappearance.
        self._panel_pending_choice_action: str | None = None  # select/close/refresh
        self._panel_pending_choice_fingerprint: tuple | None = None
        self._panel_f1_used_this_episode = False
        # P0-3（215302）：自然面板进入需同类型锚点连续 2 帧（或单帧 ≥0.85）。
        # 跨 tick 保留上一帧锚点类型；类型漂移/锚点消失即重置，防单帧贴阈值
        # （0.742/0.799）误入面板处理。
        self._panel_anchor_candidate: tuple[str, float] | None = None
        # One explicit L1 cycle owns the proactive G/F/V panels.  Per-panel
        # fingerprint guards remain the anti-loop safety boundary; the
        # per-kind episode count is the terminal guard for repeated unresolved
        # panel episodes in one round.
        self._l1_cycle_step = "merchant" if self._passenger_mode() else "bond"
        self._l1_cycle_owned_panel = False
        self._l1_cycle_selected = False
        # B1 抽干上限：同一步骤单次停留最多 3 次成功选择或 30s（见
        # _l1_step_visit_exhausted）；set_phase(MAIN_LINE) 每局重置。
        self._l1_cycle_last_advance_at: float = time.time()
        self._l1_cycle_step_successes: int = 0
        self._panel_visit_force_advance: bool = False
        # 三面板主动打开时间戳（G/F/V）：0.0 = 本局从未成功打开 → 首次立即允许；
        # 成功打开后按 settings.choice_interval 限制同 kind 重开。set_phase(MAIN_LINE)
        # 每局重置。
        self._last_skill_panel = 0.0
        self._last_bond_attempt = 0.0
        self._last_treasure_attempt = 0.0
        self._merchant_next_at = 0.0
        # Merchant spends are governed by the live kill-resource HUD.  Keep a
        # short retry separate from post-click verification cooldown so a
        # resource-short shop does not park the hitch cycle at the merchant.
        self._merchant_budget_retry_at = 0.0
        self._merchant_kill_balance_fingerprint: str | None = None
        self._merchant_kill_balance_value: int | None = None
        self._merchant_discovery_deadline: float | None = None
        self._equipment_next_at = 0.0
        self._equipment_pending_until = 0.0
        self._equipment_fsm = EquipmentFSM()
        self._merchant_fsm = MerchantFSM()
        # 公共背包流转（lobby_hitch Rank-1）：FSM 只授权步骤，坐标全部由
        # BagLayout 从锚点推导，个人格永远只右键。
        self._public_bag_fsm = PublicBagFSM()
        self._public_bag_next_at = 0.0
        self._public_bag_empty_since: float | None = None
        self._public_bag_open_since: float | None = None
        self._public_bag_deposit_before: tuple[float, int] | None = None
        # 搬不动的格子（装备栏里的在装武器等）：连续失败两次就本局跳过，
        # 否则冷却到期后会一直回来重试同一格。
        self._public_bag_failed_sources: dict[str, int] = {}
        self._pickup_next_at = 0.0
        self._equipment_round_next_at = 0.0
        self._equipment_round_current_slot = 2
        self._fail_gift_attempts = 0
        self._evolution_attempts = 0
        self._evolution_next_at = 0.0
        self._evolution_baseline: np.ndarray | None = None
        # P0-2：click_evolve 后置确认（164929 42 次空点 / 215302 423 次狂点）。
        # 点击必须带来面板/画面反馈才视为成功；无反馈计失败重试，每轮 ≤3 次后
        # 放弃本轮进化。冷却 _evolve_click_cooldown_until（5s）保留。
        self._evolve_click_cooldown_until = 0.0
        self._evolve_feedback_pending = False
        self._evolve_click_at = 0.0
        self._evolve_fail_count = 0
        self._evolve_baseline: np.ndarray | None = None
        self._evolve_feedback_window_s = 3.0
        # r11 live：未点进化就狂点物品栏英雄卡（trace_110618: inventoy 1829 / evolve 0）。
        # 本轮进化成功后才允许 hero_card；单次 equipment 访问最多 2 次且同点粘滞即停。
        self._evolve_ok_this_cycle = False
        self._evolve_awaiting_hero_pick = False
        self._inventory_clicks_this_visit = 0
        self._inventory_last_pt: tuple[int, int] | None = None
        self._inventory_same_pt_hits = 0
        self._inventory_next_at = 0.0
        self._devour_dan_next_at = 0.0
        self._devour_dan_consecutive_clicks = 0
        self._ambiguous_giveup_frames = 0
        self._pending_action: PendingAction | None = None
        self._pending_action_unconfirmed_count = 0
        self._surface_conflict_since: float | None = None
        self._merchant_next_at = 0.0
        self._f1_shadow_correct = 0
        self._f1_shadow_misfire = 0
        self._f1_live = False
        self._aux_dialog_attempts = {"HEIRLOOM_DIALOG": 0, "GREAT_RIFT_CONFIRM": 0}
        # Hero-mode automation is intentionally limited to the one complete
        # recorded path: Kenrito, level 1..5, 1600x900 client capture.
        self._hero_state = "IDLE"
        self._hero_verified_level = 0
        self._hero_level_baseline: np.ndarray | None = None
        self._hero_level_candidate: np.ndarray | None = None
        self._hero_card_baseline: np.ndarray | None = None
        self._hero_step_deadline: float | None = None
        self._hero_modal_missing_frames = 0
        # B1-2：未知页面/未知选择自动归档。incident_dir=None → 不建档（默认关闭，
        # 测试/回放零副作用）；桌面/LIVE 接入时传入 %LocalAppData%\ShuaBao。
        self._incident_dir = incident_dir
        self._archiver: IncidentArchiver | None = IncidentArchiver(root=incident_dir) if incident_dir else None
        self._incident_pending_fp: str | None = None  # 待补齐 frame_after 的 incident 指纹
        self._unknown_since: float | None = None      # context=UNKNOWN 连续计时起点
        self._unknown_recorded_fp: str | None = None  # 本 UNKNOWN episode 已归档的页面指纹
        self._last_health: FrameHealthResult | None = None  # 最近一帧健康结果（Fail-Closed 归档用）
        self._trace_ocr_suggestion: dict | None = None
        self._ocr_client: ShadowClient | None = None
        self._skill_labels: dict[str, str] = {}
        labels_path = project_root / "config" / "skill_labels.json"
        try:
            self._skill_labels = json.loads(labels_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            self._skill_labels = {}
        self._fetter_labels: dict[str, str] = {}
        fetter_path = project_root / "config" / "fetter_labels.json"
        try:
            raw_fetters = json.loads(fetter_path.read_text(encoding="utf-8"))
            self._fetter_labels = {
                str(k): str(v)
                for k, v in raw_fetters.items()
                if not str(k).startswith("_") and isinstance(v, str)
            }
        except (OSError, ValueError, TypeError):
            self._fetter_labels = {}
        # L1 策略文档 + 习惯偏好：Mediator 初始化时各加载一次并快照；
        # _policy_settings() 之后只返回缓存，绝不每 tick 读 choice_policy.json。
        self._choice_policy_doc: dict = {}
        policy_path = project_root / "config" / "choice_policy.json"
        try:
            loaded_policy = json.loads(policy_path.read_text(encoding="utf-8"))
            if isinstance(loaded_policy, dict):
                self._choice_policy_doc = loaded_policy
        except (OSError, ValueError, TypeError):
            self._choice_policy_doc = {}
        # 技能路线 v2 文档：与策略文档同模式，初始化各加载一次并快照。
        self._skill_routes_doc: dict = {}
        skill_routes_path = project_root / "config" / "skill_routes.json"
        try:
            loaded_skill_routes = json.loads(skill_routes_path.read_text(encoding="utf-8"))
            if isinstance(loaded_skill_routes, dict):
                self._skill_routes_doc = loaded_skill_routes
        except (OSError, ValueError, TypeError):
            self._skill_routes_doc = {}
        self._boss_catalog_cache: dict = {}
        boss_catalog_path = project_root / "config" / "challenge_boss_catalog.json"
        try:
            loaded_boss_catalog = json.loads(boss_catalog_path.read_text(encoding="utf-8"))
            if isinstance(loaded_boss_catalog, dict):
                self._boss_catalog_cache = loaded_boss_catalog
        except (OSError, ValueError, TypeError):
            self._boss_catalog_cache = {}
        self._habit_preference: dict = {}
        try:
            loaded_habit = load_habit_preference()
            if isinstance(loaded_habit, dict):
                self._habit_preference = loaded_habit
        except (OSError, ValueError, TypeError):
            self._habit_preference = {}
        self._habit_skill_scores = habit_scores_for_panel(self._habit_preference, "skill")
        self._mechanics_view = MechanicsPolicyView.from_repo(project_root)
        self._cached_policy_settings: PolicySettings | None = None
        ocr_enabled_flag = getattr(settings, "ocr_enabled", False) or getattr(settings, "ocr_mode", "off") in {"shadow", "live"}
        if ocr_enabled_flag:
            # If settings points to a legacy or external repo without shuabao, use active project root
            target_repo = Path(settings.ocr_repo_root) if settings.ocr_repo_root else project_root
            if not (target_repo / "src" / "shuabao" / "__init__.py").is_file():
                target_repo = project_root
            self._ocr_client = ShadowClient(
                repo_root=target_repo,
                timeout_ms=max(2500, int(settings.ocr_timeout_ms or 0)),
                startup_timeout_ms=30000,
                trace_path=(Path(incident_dir) / "ocr_shadow.jsonl") if incident_dir else None,
            )
        self._main_line_ocr_next_at: float = 0.0
        self._main_line_stall_stage: tuple[int, int] | None = None
        self._main_line_stall_since: float | None = None
        self._main_line_stall_reason: str | None = None
        self._close_main_line_triggered: bool = False
        self._main_line_closed_done: bool = False


    # ---------- 感知 / 执行（Jobs 唯一入口）----------

    def _capture_title(self) -> str:
        """根据当前阶段返回截屏目标窗口关键字。
        L0（大厅/建房/房间等待）→ KK 对战平台窗口
        L1（进入游戏后的过渡/选关/局内）→ 英雄三国游戏窗口
        BOOT 默认走 L0，但 see() 会先探测英雄三国游戏窗：存在即改绑 L1
        （20260827 用户规则），只有游戏窗不存在才用本函数的 L0 标题。
        """
        user_title = self.settings.window_title_contains
        if self.phase in (
            Phase.BOOT,
            Phase.WAIT_EXIT,
            Phase.LOBBY_ROOM,
            Phase.PREPARE,
            Phase.PLATFORM_MAP,
            Phase.CREATE_ROOM,
            Phase.ROOM_WAITING,
        ):
            # L0: 优先用户配置，否则 KK 平台关键字
            if user_title:
                # 用户配置 + L0 关键字合并（确保能找到 KK 平台）
                return user_title + "," + ",".join(L0_WINDOW_KEYWORDS)
            return ",".join(L0_WINDOW_KEYWORDS)
        else:
            # L1: 优先用户配置，否则游戏窗口关键字
            if user_title:
                return user_title
            return ",".join(L1_WINDOW_KEYWORDS)

    def _is_in_game_hud(self, frame: Frame) -> bool:
        """局内 HUD 证据（每 evidence 一次；detect/handler 复用）。

        N2.2：结果按证据 memo；环境锚点（HUD 常驻元素）优先命中即止，
        再查技能/卡牌面板场景，最后挑战开关——布尔 OR 语义与旧顺序等价。
        N2.4：env_anchor 按实测位置拆分 ROI（zidong 左下 / shortKey 右上，
        mainIdentifier 位置未知保留全帧），技能/卡牌/挑战场景套场景级 ROI。
        """
        def compute() -> bool:
            if self._selection_anchor(frame):
                return True
            th = self.settings.match_threshold
            if self.find(frame, ["zidong"], threshold=th, scales=self._hot_scales(), roi=self._ENV_ZIDONG_ROI):
                return True
            if self.find(frame, ["shortKey"], threshold=th, scales=self._hot_scales(), roi=self._ENV_SHORTKEY_ROI):
                return True
            # mainIdentifier is the "等待玩家1选择难度" banner of the in-game
            # stage lobby (see _host_choosing_difficulty), never HUD evidence:
            # counting it made a waiting guest "enter" MAIN_LINE before the
            # round started (live 2026-09-11 23:42, pressure/auto-task lost).
            for sc in ("skill_panel", "card_panel"):
                if self.find_scene(frame, sc):
                    return True
            for sc in ("coin_challenge", "wood_challenge", "experience_challenge", "treasure_challenge"):
                # N2.4：与 _ensure_challenge_buttons 统一阈值（min(0.68, …)），
                # 同证据同 key → 面板处理直接复用本扫描，不再每 tick 双扫。
                if self.find_scene(frame, sc, threshold=min(0.68, self.settings.match_threshold)):
                    return True
            return False

        return bool(self._memo(("hud",), frame, compute))

    def _host_choosing_difficulty(self, frame: Frame) -> bool:
        """The in-game stage lobby as a non-host player sees it.

        KK shows "等待玩家1选择难度" above the stage rows while player 1 picks
        the difficulty.  A guest there is waiting for the round, not on a
        misopened stage page, and has no input to give.
        """
        if not self._is_game_client_frame(frame):
            return False
        return self.find(
            frame,
            ["mainIdentifier"],
            threshold=self.settings.match_threshold,
            scales=self._hot_scales(),
            roi=(0.30, 0.0, 0.75, 0.16),
        ) is not None

    def _detect_context(self, frame: Frame, role: str | None = None) -> str:
        """Classify the visible page before taking a state-machine action."""
        # Classification does not depend on role. Reuse it for both L0/L1
        # handlers when they inspect the same frame. N2.2：感知入口建立/复用
        # FrameEvidence；同帧第二次查询不再触发 matcher。
        ev = self._ensure_evidence(frame)
        if ev.context is not None:
            self._context_cache_value = ev.context
            return ev.context
        value = self._compute_context(frame, role)
        ev.context = value
        self._context_cache_value = value
        return value

    def _compute_context(self, frame: Frame, role: str | None = None) -> str:
        if self._selection_anchor(frame):
            value = "MAIN_LINE"
        elif role != "l0" and (self.find_scene(frame, "disconnect") or self.find_scene(frame, "fail")):
            value = "QUIT"
        elif self._post_game_state(frame) in {"POST_VICTORY", "ARCHIVE_PANEL", "HEIRLOOM_DIALOG"}:
            value = "MAIN_LINE"
        elif self._is_in_game_hud(frame):
            # The task bar/Boss timer can parse as a stage row.  Strong HUD
            # anchors revoke STAGE_SELECT classification authority.
            value = "MAIN_LINE"
        elif self._find_stage_page(frame):
            # 选关页特征（关卡编号数字）优先于通用「开始游戏」按钮：
            # 选关页底部也有开始/扫荡/英雄模式按钮，room_start 模板会误匹配
            # （官方 1936x1066 选关截图实测 roomStart 0.84 / kk_start 0.92）。
            value = "STAGE_SELECT"
        elif self._is_confirmed_room_frame(frame):
            value = "ROOM_WAITING"
        elif self._lobby_room_list_evidence(frame):
            value = "ROOM_LIST"
        elif self._find_room_start(frame):
            value = "ROOM_WAITING"
        elif self._find_create_confirm(frame):
            value = "CREATE_ROOM"
        elif self._auto_room_enabled() and self._find_map_create_room(frame):
            value = "PLATFORM_MAP"
        else:
            value = "UNKNOWN"
        return value
    def _frame_signal(self, frame: Frame, role: str) -> int:
        """Give anchor-bearing windows precedence over title-only matches."""
        context = self._detect_context(frame, role)
        return {
            "ROOM_WAITING": 100,
            "ROOM_LIST": 80,
            "STAGE_SELECT": 90,
            "CREATE_ROOM": 80,
            "PLATFORM_MAP": 70,
            "MAIN_LINE": 60,
            "IN_GAME": 60,
        }.get(context, 0)

    def _sticky_frame_signal(self, frame: Frame, role: str) -> bool:
        """上次健康 hwnd 的廉价锚点校验（N2-REVIEW #1）。

        多窗口时「能抓到像素」不足以证明仍是目标局内窗：旧 hwnd 可能被
        最小化/遮挡/切到非目标页，仍返回有效帧。sticky 快路径必须看到
        廉价场景信号（选择锚点 / HUD 元素 / 房间页）才继续；异常时保守
        沿用旧 hwnd（与旧行为一致）。
        """
        try:
            if self._selection_anchor(frame):
                return True
            if role == "l1":
                th = self.settings.match_threshold
                return bool(
                    self.find(frame, ["zidong"], threshold=th, scales=(1.0,), roi=self._ENV_ZIDONG_ROI)
                    or self.find(frame, ["shortKey"], threshold=th, scales=(1.0,), roi=self._ENV_SHORTKEY_ROI)
                    or self.find_scene(frame, "skill_panel")
                )
            return bool(self.find_scene(frame, "room_start") or self.find_scene(frame, "map_create_room"))
        except Exception:
            return True

    def _capture_best(self, title: str, role: str) -> Frame:
        """Capture all matching windows without focusing, then use scene pixels.

        N2.2：上次健康 hwnd 优先抓取；仅连续 N=2 不健康/失配后枚举候选。
        候选枚举先用廉价固定锚点筛出最高分，再对最高分做完整 context 分类。
        N2-REVIEW #1：sticky 快路径在像素有效之外增加廉价锚点校验，
        有效但无信号（非目标局内窗）计入失配，连续 2 帧后候选重排。
        """
        targets = find_window_targets(title, role=role, allow_minimized=True)
        create_dialog_probe = role == "l0" and (
            self._create_room_pending_since is not None
            or self.phase == Phase.CREATE_ROOM
        )
        hitch_join_probe = role == "l0" and self._hitch_sm.pending_join
        room_exit_probe = role == "l0" and (
            getattr(self, "_hitch_floor_exit_pending", False)
            or getattr(self, "_room_leave_pending", False)
        )
        self._capture_candidates = len(targets)
        previous_confirmed_room = self._confirmed_room_hwnd
        self._confirmed_room_hwnd = None
        # One grab per HWND per call.  The room-signature pre-pass below,
        # the probe paths and the sticky/ranking paths all ask for the same
        # candidates; without this memo every l0 tick with 2+ KK windows
        # captured each window twice.
        capture_cache: dict[int, Frame] = {}

        def capture_one(target):
            key = int(getattr(target, "hwnd", 0) or 0)
            if key and key in capture_cache:
                return capture_cache[key]
            frame = capture_target(target)
            if key:
                capture_cache[key] = frame
            return frame
        self._capture_selected_by = None
        if role == "l0":
            self._last_l0_target_hwnds = tuple(
                int(getattr(t, "hwnd", 0) or 0) for t in targets
            )
            self._capture_black_hwnds = ()
        if role == "l0" and len(targets) >= 2:
            # A pure-black same-title KK window carries no page evidence (a
            # stale room window left by an earlier misclick stayed visible and
            # black across runs).  It may never outrank a window with pixels:
            # otherwise sticky, join-probe and ranking paths all pin to it
            # while the frame health gate withholds every decision.
            black = [t for t in targets if _is_blank_capture(capture_one(t))]
            if black and len(black) < len(targets):
                self._capture_black_hwnds = tuple(
                    int(getattr(t, "hwnd", 0) or 0) for t in black
                )
                black_ids = {id(t) for t in black}
                targets = [t for t in targets if id(t) not in black_ids]
        if role == "l0" and len(targets) >= 2:
            for cand_target in targets:
                cand_frame = capture_one(cand_target)
                if cand_frame.hwnd is not None and self._is_confirmed_room_frame(cand_frame):
                    self._confirmed_room_hwnd = cand_frame.hwnd
                    break
        if role == "l0" and len(targets) == 1:
            # 单窗口/全屏 KK 没有第二个候选可供拓扑门禁比较；只要新采集的
            # 页面结构已经证明是 ROOM，当前 HWND 就是唯一可执行 owner。
            candidate = capture_one(targets[0])
            if candidate.hwnd is not None and self._is_confirmed_room_frame(candidate):
                self._confirmed_room_hwnd = candidate.hwnd
        if role == "l0" and self._confirmed_room_hwnd != previous_confirmed_room:
            # Transition only - this runs every tick.  Room identity is the
            # single thing a live hitch run cannot be audited without: it must
            # name the real room HWND and never the pet window.
            candidates = [
                (
                    getattr(t, "hwnd", None),
                    getattr(t, "width", None),
                    getattr(t, "height", None),
                )
                for t in targets
            ]
            print(
                f"[med] confirmed room hwnd {previous_confirmed_room} -> "
                f"{self._confirmed_room_hwnd} candidates={candidates!r}"
            )
        if not targets:
            return capture(title, role=role)
        # KK exposes the create-room form as a second same-title HWND.  The
        # sticky parent window still looks healthy, so the generic fast path
        # would otherwise starve the dialog forever.  Probe every candidate
        # only during this bounded episode and prefer the structurally
        # confirmed form.  No focus change or input is performed here.
        if create_dialog_probe or hitch_join_probe or room_exit_probe:
            frames = [capture_one(target) for target in targets]
            if room_exit_probe:
                # The confirmation prompt may be hosted by its own KK child
                # HWND.  KK's dialog frame template is version-sensitive;
                # while exit is pending, the left-side blue Confirm control is
                # the direct, action-specific proof and cannot be a Ready
                # button (Ready is outside this ROI).
                for candidate in frames:
                    if self._find_hitch_exit_confirm_button(candidate) is not None:
                        self._capture_miss_streak = 0
                        self._capture_selected_by = "probe_exit_confirm"
                        return candidate
            if hitch_join_probe:
                # KK opens the joined room as a separate same-title HWND.
                # While a join is pending, the healthy lobby parent must not
                # starve the child window that owns Ready/Exit controls.
                for candidate in frames:
                    if candidate.hwnd is not None and candidate.hwnd == self._confirmed_room_hwnd:
                        self._capture_miss_streak = 0
                        self._capture_selected_by = "probe_join_room"
                        return candidate
                origin_hwnd = self._hitch_join_origin_hwnd
                preexisting = getattr(self, "_hitch_join_preexisting_hwnds", frozenset())
                for candidate in frames:
                    if (
                        origin_hwnd is not None
                        and candidate.hwnd is not None
                        and candidate.hwnd != origin_hwnd
                        and candidate.hwnd not in preexisting
                        and not _is_blank_capture(candidate)
                        and not self._is_confirmed_room_frame(candidate)
                    ):
                        # Only a window the join itself opened (a prompt such
                        # as room-full, or a room still rendering) is the join
                        # child.  Windows that already existed before the click
                        # have no claim on the pending join.
                        self._capture_miss_streak = 0
                        self._capture_selected_by = "probe_join_child"
                        return candidate
            for candidate in frames:
                if self._find_create_confirm(candidate):
                    self._capture_miss_streak = 0
                    self._capture_selected_by = "probe_create_confirm"
                    return candidate
            # Dialog closed (Create accepted or dismissed). Prefer an already
            # open room over the larger platform map — max(size) would always
            # pick 1328x945 and starve room_start (r10 trace_20260812_102844).
            for candidate in frames:
                if candidate.hwnd is not None and candidate.hwnd == self._confirmed_room_hwnd:
                    self._capture_miss_streak = 0
                    self._capture_selected_by = "probe_confirmed_room"
                    return candidate
            # Otherwise fall through to sticky / signal ranking.
        if len(targets) == 1:
            self._capture_selected_by = "single"
            return capture_one(targets[0])
        prev = self._last_frame if self._last_capture_role == role else None
        if prev is not None and prev.hwnd is not None:
            prev_target = next((t for t in targets if t.hwnd == prev.hwnd), None)
            if prev_target is not None:
                frame = capture_one(prev_target)
                valid = frame.bgr is not None and frame.bgr.size > 0 and frame.is_valid and frame.width > 0
                if valid and self._sticky_frame_signal(frame, role):
                    self._capture_miss_streak = 0
                    self._capture_selected_by = "sticky"
                    return frame
                self._capture_miss_streak += 1
                if self._capture_miss_streak < 2:
                    # 连续第 1 帧失配：仍返回该 hwnd 帧，下一帧才重选
                    self._capture_selected_by = "sticky_miss"
                    return frame
                # 连续 2 帧失配（无效或无信号）→ 候选枚举重排
        self._capture_miss_streak = 0
        frames = [capture_one(target) for target in targets]
        previous_hwnd = prev.hwnd if prev is not None else None
        scored: list[tuple[int, Frame]] = []
        for f in frames:
            cheap = 0
            if f.bgr is not None and f.bgr.size > 0:
                if self._selection_anchor(f):
                    cheap = 60
                elif self.find_scene(f, "env_anchor"):
                    cheap = 50
            scored.append((cheap, f))
        scored.sort(key=lambda pair: (pair[0], int(pair[1].hwnd == previous_hwnd)), reverse=True)
        top = scored[:2]
        self._capture_selected_by = "rank"
        return max(
            top,
            key=lambda pair: (self._frame_signal(pair[1], role), int(pair[1].hwnd == previous_hwnd)),
        )[1]

    def _probe_l1_game_frame(self) -> Frame | None:
        """探游戏窗（含最小化/被遮挡，窗口标题即路由依据）。

        20260827（用户规则）：英雄三国窗口存在就无条件绑定 L1，进入选关/局内
        判定，绝不捕获并置前 KK 平台窗；只有游戏窗不存在才允许回落平台流。
        P0-1：该探测同时服务 BOOT 与 ROOM_WAITING（被动 L1 接管）。
        """
        game_frame = self._capture_best(",".join(L1_WINDOW_KEYWORDS), "l1")
        if (
            game_frame is not None
            and game_frame.hwnd is not None
            and self._is_game_client_frame(game_frame)
        ):
            return game_frame
        return None

    def see(self, reason: str = "") -> Frame:
        # A single tick asks the same scene questions from capture ranking,
        # context classification and the phase handler.  Reuse those results
        # for this frame; template matching is the dominant hot path.
        # Static frames (identical pixels AND same window position) reuse the
        # previous Frame object so the per-frame evidence cache hits instead of
        # re-scanning every template（N2.2：FrameEvidence 取代每 tick clear）。
        t0 = time.perf_counter()
        title = self._capture_title()
        l0_phases = {
            Phase.BOOT,
            Phase.WAIT_EXIT,
            Phase.LOBBY_ROOM,
            Phase.PREPARE,
            Phase.PLATFORM_MAP,
            Phase.CREATE_ROOM,
            Phase.ROOM_WAITING,
        }
        role = "l0" if self.phase in l0_phases else "l1"
        frame = None
        game_probe_phases = {Phase.BOOT, Phase.ROOM_WAITING}
        if self._hitch_enabled():
            # User rule: a running 英雄三国 window owns the view.  Live
            # 2026-09-12 a hitch run knocked back to LOBBY_ROOM kept staring at
            # the minimized KK lobby while its round played with zero input.
            # (WAIT_EXIT is excluded: that is the game window closing.)
            game_probe_phases |= {Phase.LOBBY_ROOM, Phase.PREPARE}
            # ...except the window of the game we just left while it closes:
            # re-adopting it would replay the post-game exit and count the
            # round twice.
            exit_at = getattr(self, "_hitch_game_exit_at", None)
            if exit_at is not None and time.time() - exit_at < self._HITCH_GAME_CLOSE_GRACE_S:
                game_probe_phases -= {Phase.LOBBY_ROOM, Phase.PREPARE}
        if self.phase in game_probe_phases:
            game_frame = self._probe_l1_game_frame()
            if game_frame is not None:
                if self.phase == Phase.BOOT:
                    print(
                        f"[boot] 英雄三国窗口存在 hwnd={game_frame.hwnd}，直接接手游戏内流程"
                    )
                else:
                    print(
                        f"[L0] {self.phase.name} 发现英雄三国窗口 hwnd={game_frame.hwnd}，观察移交 L1 游戏帧"
                    )
                frame = game_frame
                role = "l1"
                title = ",".join(L1_WINDOW_KEYWORDS)
        if frame is None:
            frame = self._capture_best(title, role)
        primary_has_pixels = bool(
            frame is not None
            and frame.bgr is not None
            and frame.bgr.size > 0
        )
        primary_signal = (
            self._frame_signal(frame, "l1") if primary_has_pixels else 0
        )
        if self.phase == Phase.ROOM_STARTING and primary_signal == 0:
            # During process launch the game HWND may not exist yet.  Keep L1
            # as the primary target, but inspect the platform as a fallback so
            # an unchanged room page can be aligned/retried instead of being
            # treated as a missing-window failure.  Invalid frames must never
            # enter template matching: the health gate owns that observation.
            platform_frame = self._capture_best(",".join(L0_WINDOW_KEYWORDS), "l0")
            platform_has_pixels = bool(
                platform_frame is not None
                and platform_frame.bgr is not None
                and platform_frame.bgr.size > 0
            )
            if (
                platform_has_pixels
                and self._frame_signal(platform_frame, "l0") > 0
            ):
                frame = platform_frame
                role = "l0"
        capture_ms = (time.perf_counter() - t0) * 1000.0
        self._last_capture_ms = capture_ms
        # Capture uses PrintWindow and must not change foreground state.  Focus is
        # acquired only by the input guard immediately before a verified action;
        # otherwise a valid L0 frame can repeatedly pull KK above a launching game.
        transition_phases = (Phase.ROOM_STARTING, Phase.STAGE_STARTING, Phase.WAIT_EXIT)
        is_platform_frame = role == "l0" or classify_window_role(getattr(frame, "window_title", None)) == WindowRole.PLATFORM
        suppress_activate = self.phase in transition_phases and is_platform_frame
        if frame.hwnd and not frame.is_valid and not suppress_activate:
            # 20260823（用户规则）：所有目标窗口都可能被最小化。最小化窗口的
            # capture 返回无效帧，上面的前台兜底因 is_valid=False 永远不触发，
            # 健康门禁会一直跳过决策 → 启动卡死。这里对最小化的目标窗口执行
            # SW_RESTORE（activate_window 内含），下一 tick 重新捕获。
            try:
                from shuabao.vision.capture import is_window_minimized
                if is_window_minimized(frame.hwnd):
                    frame.is_minimized = True
            except Exception:
                pass
        # 会话级 UI 缩放校准：取宽高相对 1600x900 的较小缩放比（保守）
        if frame.bgr is not None and frame.width >= 200 and frame.height >= 200:
            scale = min(frame.width / 1600.0, frame.height / 900.0)
            self._ui_scale = round(min(scale, 1.0), 3) if scale < 1.0 else 1.0
        if (
            self._last_frame is not None
            and self._last_frame.bgr is not None
            and frame.bgr is not None
            and self._last_frame.bgr.shape == frame.bgr.shape
            and self._last_frame.left == frame.left
            and self._last_frame.top == frame.top
            and bool(np.array_equal(self._last_frame.bgr, frame.bgr))
        ):
            # 内容+位置相同：复用上一帧对象（场景缓存命中）。
            # 保持原时间戳：OLD_FRAME/FROZEN 静态检测仍会标记该帧为静态帧。
            frame = self._last_frame
        self._capture_generation += 1
        self._prev_frame = self._last_frame
        self._last_frame = frame
        self._last_capture_role = role
        # G0 P0 contract #3：最后窗口 role/HWND 快照。
        self.last_window_role = role
        self.last_window_hwnd = frame.hwnd
        if frame.hwnd is None and not frame.window_title:
            context = "NO_WINDOW"
        elif self.phase == Phase.HERO_SETUP:
            # Hero setup has exact modal/ROI guards; generic context matching
            # is an unnecessary full-screen scan for every slow capture.
            # N2-REVIEW #4：仍建立本帧 evidence——hero 点击链必须受 generation
            # 与输入序列门禁保护（旧路径 _evidence 恒 None → _action_gate_ok 放行）。
            self._ensure_evidence(frame)
            context = "HERO_SETUP"
        else:
            context = self._detect_context(frame, role)
        if capture_ms >= 800.0 and self._tick_reason is None:
            self._tick_reason = "capture_wait"
        print(
            f"[med] capture {reason or '-'} "
            f"{frame.width}x{frame.height} @({frame.left},{frame.top}) "
            f"phase={self.phase.name} target='{title}' "
            f"window='{frame.window_title}' hwnd={frame.hwnd} context={context}"
        )
        return frame

    def templates(self, scene_key: str) -> list[str]:
        names = list(scene_templates(self.scenes_doc, scene_key))
        sc = (self.scenes_doc.get("scenes") or {}).get(scene_key) or {}
        # 技能：优先用用户配置的 Skills 短码
        if scene_key == "skill_panel" or sc.get("prefer_settings_skills"):
            sk = self.settings.skill_template_names()
            names = sk + names
        if scene_key == "boss_entry":
            for b in (self.settings.cjb_boss, self.settings.sgzx_boss):
                if b:
                    names.insert(0, b)
                    names.insert(0, f"boss/{b}")
                    names.insert(0, f"chuanjiaobao/{b}")
        return names

    def _adapt_scales(self, scales: tuple[float, ...]) -> tuple[float, ...]:
        """Merge the session ui_scale neighborhood into the given scales.

        960x540 (=0.6x of 1600x900) needs scales around 0.6; the default
        0.85-1.2 band misses it entirely, which previously made every
        detector report UNKNOWN on non-baseline resolutions.

        P0-1（LOBBY_AUDIT P1）：必须保序追加、不得 sorted()。旧实现的升序排序把
        ``_l0_scales()`` 的"绝对 1.0 优先"顺序反转成升序，非 1.0 KK 窗口上 L0 门闩
        先扫 ui 邻域再扫绝对档（1328×945→0.83 实证：1.0 排在 0.78/0.83/0.88 之后），
        既违背 N2.4 文档序，又扩大 early-stop 假阳性面（r5/r6 误点同族）。
        """
        us = getattr(self, "_ui_scale", 1.0)
        if abs(us - 1.0) < 0.05 or not scales:
            return scales
        out = list(scales)
        for s in (us * 0.94, us, us * 1.06):
            if not any(abs(s - x) < 0.03 for x in out):
                out.append(round(s, 3))
        return tuple(out)

    # ---------- N2.2 FrameEvidence 生命周期 / memo ----------

    @property
    def _scene_cache(self) -> _SceneCacheCompat:
        """兼容 shim（benchmark 只读调用 .clear()）；真实缓存见 FrameEvidence.cache。"""
        return _SceneCacheCompat()

    def _ensure_evidence(self, frame: Frame) -> FrameEvidence:
        """为感知帧建立/复用 FrameEvidence。

        同一帧对象且 hwnd / ui_scale 未变 → 复用（exact-static 关键路径）；
        hwnd 或 scale 变化 → 无条件失效后重建（gen 单调递增）。
        """
        ev = self._evidence
        if ev is not None and ev.frame_ref is frame:
            if ev.hwnd == frame.hwnd and ev.ui_scale == self._ui_scale:
                return ev
            self.invalidate_evidence("window-change")
        prev_gen = ev.gen if ev is not None else None  # invalidate 就地推进后取
        new_ev = FrameEvidence(
            frame_ref=frame,
            gen=(prev_gen + 1) if prev_gen is not None else 0,
            ui_scale=self._ui_scale,
            hwnd=frame.hwnd,
        )
        self._evidence = new_ev
        return new_ev

    def invalidate_evidence(self, reason: str) -> None:
        """输入成功 / hwnd·scale 变化后调用：gen+1、丢弃缓存、清 context。

        保持同一 evidence 对象（``self._evidence is tick_evidence`` 仍成立），
        由 generation 断言识别陈旧动作授权；输入失败不调用（不推进状态）。
        """
        ev = self._evidence
        if ev is not None:
            ev.gen += 1
            ev.cache.clear()
            ev.context = None

    def _memo(self, key: tuple[object, ...], frame: Frame, compute) -> object:
        """evidence 级 memo：仅当 ``frame`` 是当前证据帧时读写缓存。

        候选窗/裁剪辅助帧（非证据帧）直接计算不缓存，避免 gen 污染与错误复用。
        """
        ev = self._evidence
        if ev is not None and ev.frame_ref is frame:
            if key in ev.cache:
                return ev.cache[key]
            result = compute()
            ev.cache[key] = result
            return result
        return compute()

    def _hot_scales(self) -> tuple[float, ...]:
        """热路径尺度：基准分辨率只试主尺度；非基准窗口主尺度 + 一个邻域。

        宽尺度（5-8 档）仅保留给 hwnd/尺寸变化、UNKNOWN 恢复和离线校准
        （N2.1 设计原则 4），不得成为正常 HUD/面板每 tick 默认。
        """
        us = self._ui_scale
        if abs(us - 1.0) < 0.05:
            return (1.0,)
        return (round(us, 3), round(us * 1.06, 3))

    def _wide_scales(self) -> tuple[float, ...]:
        """宽尺度（仅 DPI 放大窗口 miss 回退用）：覆盖 2348x1080≈1.47x 等。

        N2.1 设计原则 4：宽尺度只保留给 hwnd/尺寸变化、UNKNOWN 恢复和离线校准，
        不作为正常 HUD/面板每 tick 默认。
        """
        if abs(self._ui_scale - 1.0) < 0.05:
            return (1.0, 1.06, 1.1, 1.15, 1.2)
        us = round(self._ui_scale, 3)
        return tuple(sorted({us, round(us * 0.94, 3), round(us * 1.06, 3), round(us * 1.1, 3), round(us * 1.15, 3)}))

    # ---------- N2.4：场景级 ROI（比例坐标，命中位置经 fixture/录屏测量）----------
    # 依据 docs/baselines/n2_runs/N2_4_THRESHOLD_RECAL_20260811.md 的位置测量：
    #   挑战开关行        y≈0.71-0.75（idle 1609x932 / fail 1920x1080 均在此带）
    #   中央选择/技能面板  (0.24,0.16,0.76,0.66)（既有 _selection_roi 语义）
    #   卡牌面板          heroRefresh 实测 (0.65,0.68)
    #   选关编号列        x≈0.655（stage_select 实测 x=1048/1600）
    #   KK 房间开始按钮   (0.67,0.70)（room_waiting 1040x719 实测 (694,501)）
    _HUD_CHALLENGE_ROI = (0.0, 0.62, 0.60, 1.0)
    _CARD_PANEL_ROI = (0.24, 0.14, 0.80, 0.74)
    _STAGE_ROWS_ROI = (0.45, 0.05, 0.88, 0.88)
    # Host room start is centered at x=0.738 on the real 1040x719 fixture.
    # The KK activity/pet page false-positive from trace 203937 was x=0.883;
    # keep right-side activity/task buttons outside the action trust boundary.
    _ROOM_START_ROI = (0.60, 0.55, 0.86, 0.95)
    _ENV_ZIDONG_ROI = (0.05, 0.58, 0.42, 0.82)
    _ENV_SHORTKEY_ROI = (0.70, 0.10, 1.0, 0.55)
    # 面板底部按钮行（选择锚点/面板分类/刷新/放弃都在此带，y≈0.59-0.64）
    _PANEL_BUTTONS_ROI = (0.20, 0.50, 0.80, 0.75)
    # 选关页底栏操作带：扫荡/开始游戏都在 y≈0.80-0.95（1600x900 实测
    # 开始游戏 plate (1012,784)-(1168,850)，OCR 置信 1.0），y0.70-0.98 全覆盖。
    _STAGE_ACTION_BAR_ROI = (0.50, 0.70, 0.98, 0.98)
    # CORE02-L0 stage_start 专用阈值：直取模板跨渲染世代（0807/0814/0816
    # 三批实机帧）实测命中带 0.757-1.0，非选关页全帧噪声地板 ≤0.29；0.72
    # 同时覆盖旧世代渲染与本世代，假阳性由 stage_page 门闩 + 底栏 ROI 拦截。
    _STAGE_START_THRESHOLD = 0.72

    _SCENE_ROIS: dict[str, tuple[float, float, float, float]] = {
        # 技能面板场景含技能卡（y≈0.30）与按钮行（y≈0.59-0.64），用全面板 ROI
        "skill_panel": (0.24, 0.16, 0.76, 0.66),
        "card_panel": _CARD_PANEL_ROI,
        "coin_challenge": _HUD_CHALLENGE_ROI,
        "wood_challenge": _HUD_CHALLENGE_ROI,
        "experience_challenge": _HUD_CHALLENGE_ROI,
        "treasure_challenge": _HUD_CHALLENGE_ROI,
        "room_start": _ROOM_START_ROI,
        # CORE02-L0：stage_start 只信底栏操作带——旧全帧扫描在 (1462,426) 等
        # 画面中部产生 0.5x 误中（点错位置的根因），ROI 收紧后模板只可能
        # 命中真实的扫荡/开始游戏按钮行。
        "stage_start": _STAGE_ACTION_BAR_ROI,
        # 存档入口：archiveChallenge 顶部标签实测 (0.47,0.04)（victory 1608x929），
        # tuanben/cundangInfo 实测左上角 (0.02-0.04,0.08)；顶部带覆盖全部已知位置。
        "archive": (0.0, 0.0, 1.0, 0.18),
        # S0 ① STRONG_FAIL / 断线：上部弹窗带（位置受限；实测 quit 对话框标题区
        # fail 0.907 命中于 (0.49,0.063)，故上界放宽到 0.05；下界 0.55 排除面板
        # 按钮带 y≈0.59-0.64 的 giveUp 同源按钮——giveUp 也已从 fail 模板移除）。
        "fail": (0.05, 0.05, 0.95, 0.55),
        "disconnect": (0.05, 0.05, 0.95, 0.55),
        # S0 ① AMBIGUOUS_GIVEUP：giveUp 模板是面板放弃按钮（实测 0.88-0.945 命中
        # y≈0.62 带），只在面板按钮带检测；无恢复动作权。
        "giveup": _PANEL_BUTTONS_ROI,
        # S0 ③ 恢复脚本锚点：确定/关闭按钮（居中；ROI 排除左上角 quit，防止恢复
        # 误点局内退出按钮；无真实素材，测试用合成 matcher 证据驱动）。
        "ok": (0.20, 0.20, 0.80, 0.80),
        "close": (0.20, 0.20, 0.80, 0.80),
        # KK draws the same magnifier glyph in its global top-bar search box,
        # which scores 0.92-0.95 against this template — above the production
        # match_threshold.  The room-list control sits at y≈0.29 of the client
        # in every measured client size, so the band below excludes the top
        # bar by geometry instead of hoping the score margin holds.
        "lobby_search_icon": (0.60, 0.16, 1.00, 0.46),
    }

    def _scene_roi(self, scene_key: str) -> tuple[float, float, float, float] | None:
        return self._SCENE_ROIS.get(scene_key)

    def _scaled_up_frame(self, frame: Frame) -> bool:
        """窗口显著大于 1600x900 基准（如 2348x1080≈1.47x / 1920x1080）时
        才允许宽尺度回退，避免基准分辨率每 tick miss 时全宽扫描。"""
        return frame.width > 1600 * 1.05 or frame.height > 900 * 1.05

    def _action_gate_ok(self, reason: str = "") -> bool:
        """动作授权断言：``self._evidence is tick_evidence`` 且 generation 未变。

        任一成功输入后 generation 推进 → 同控制流后续动作被拒（每 tick≤1 输入；
        缓存命中不得延续旧帧动作授权）。N2-REVIEW #3：dry-run 观测模式经独立
        ``_input_seq`` 走同一授权语义（证据缓存保留以维持 exact-static 复用）。
        未处于 tick 控制流（如 benchmark 直调）或未建立证据时不额外拒绝。
        """
        ev = self._evidence
        if ev is None or self._tick_gen is None:
            return True
        if self._tick_input_seq is not None and self._input_seq != self._tick_input_seq:
            print(f"[med] stale evidence: 动作被拒（{reason}：本 tick 已有成功输入）")
            if len(self._trace_scenes) < 12:
                self._trace_scenes.append({
                    "scene": "stale_evidence",
                    "name": reason,
                    "score": 0.0,
                    "early_stop": False,
                    "compared_all": False,
                })
            return False
        if ev is not self._tick_evidence or ev.gen != self._tick_gen:
            print(f"[med] stale evidence: 动作被拒（{reason}）")
            if len(self._trace_scenes) < 12:
                self._trace_scenes.append({
                    "scene": "stale_evidence",
                    "name": reason,
                    "score": 0.0,
                    "early_stop": False,
                    "compared_all": False,
                })
            return False
        return True

    def find(
        self,
        frame: Frame,
        names: list[str],
        threshold: float | None = None,
        scales: tuple[float, ...] = (1.0,),
        roi: tuple[float, float, float, float] | None = None,
        *,
        early_stop: bool = False,
        min_margin: float = 0.0,
        mode: str = "match",
    ) -> MatchResult | None:
        """通用找图（N2.1 早停可选，默认保持 N0 全扫描语义）。

        缓存键规范化：``(mode, names_tuple, threshold, 适配后 scales, roi, (early_stop, min_margin))``。
        ROI 命中坐标回映为帧内坐标（与 match_all 一致）。
        """
        if not names:
            return None
        th = threshold if threshold is not None else self.settings.match_threshold
        adapted = self._adapt_scales(scales)
        names_t = tuple(names)
        key = (mode, names_t, th, adapted, roi, (early_stop, min_margin))

        def compute():
            res = match_any_with_margin(
                frame,
                self.images,
                list(names_t),
                threshold=th,
                scales=adapted,
                roi=roi,
                min_margin=min_margin,
                early_stop=early_stop,
            )
            hit = res.best
            if hit is not None and roi is not None:
                # ROI 裁剪后 x/y 是 ROI 内坐标；回映到帧内坐标（screen_* 已含偏移）
                rx1, ry1, _rx2, _ry2 = roi
                x1 = max(0, min(frame.width, int(frame.width * rx1)))
                y1 = max(0, min(frame.height, int(frame.height * ry1)))
                hit.x += x1
                hit.y += y1
            return hit

        return self._memo(key, frame, compute)

    # L0 门闩/选关/挑战场景：模板是绝对尺寸资产（如 kk_start/startGameBtn 在
    # 1040x719 平台窗口以 1.0 命中），不受 1600x900 相对 ui_scale 启发式支配。
    # 这些场景用宽尺度档 + 优先级早停一次扫完（不做 hot 双扫）。
    _L0_GATE_SCENES = frozenset({
        "lobby_start", "lobby_room", "map_create_room", "create_room_confirm",
        "room_start", "stage_start", "start",
        "stage", "stage_page", "coin_challenge", "wood_challenge",
        "experience_challenge", "treasure_challenge",
        "lobby_room_list", "lobby_room_list_tab", "lobby_room_list_selected",
        "lobby_refresh", "lobby_search_box", "lobby_search_icon",
    })

    def _l0_scales(self) -> tuple[float, ...]:
        """L0 门闩尺度：绝对 0.9-1.2 档主尺度优先 + 会话 ui_scale 邻域。

        N2.4：按距主尺度（1.0，绝对尺寸资产）的距离排序——实测 kk_start/
        stage_begin_btn/roomStart/stage 全部在 1.0 命中（room_waiting kk_start
        1.0→1.000），旧的升序（0.611 起）会让每次命中都先白扫低档位；ui_scale
        邻域仍保留给真正按窗口缩放渲染的游戏内资产（如小窗口挑战开关），
        但排在绝对档之后。
        """
        absolute = (1.0, 1.1, 0.9, 1.15, 1.2)
        if abs(self._ui_scale - 1.0) < 0.05:
            return absolute
        us = round(self._ui_scale, 3)
        # ui 邻域按距 us 的距离排序（0.94/1.06 等距，0.94 在前）
        nb = sorted({round(us * 0.94, 3), us, round(us * 1.06, 3)}, key=lambda s: abs(s - us))
        return absolute + tuple(nb)

    def find_scene(self, frame: Frame, scene_key: str, threshold: float | None = None) -> MatchResult | None:
        """场景模板找图（evidence 级 memo；热路径只试主/邻尺度）。

        N2.4：命中位置已知的场景（挑战开关行/面板/房间开始按钮）自动套用
        场景级 ROI，全帧宽搜不再是每 tick 默认。
        """
        th = threshold if threshold is not None else self.settings.match_threshold
        names = self.templates(scene_key)
        if not names:
            return None
        key = ("scene", scene_key, th)
        roi = self._scene_roi(scene_key)

        def compute():
            if scene_key in self._L0_GATE_SCENES:
                # L0 门闩：宽尺度档 + early_stop（首个过阈值命中即止，见 _find_room_start 分析）
                hit = self.find(
                    frame, names, threshold=th,
                    scales=self._l0_scales(), early_stop=True, roi=roi,
                    mode=f"scene:{scene_key}:l0",
                )
            else:
                hit = self.find(frame, names, threshold=th, scales=self._hot_scales(), roi=roi, mode=f"scene:{scene_key}")
            if hit is not None and len(self._trace_scenes) < 12:
                self._trace_scenes.append({
                    "scene": scene_key,
                    "name": hit.name,
                    "score": round(hit.score, 3),
                    "early_stop": scene_key in self._L0_GATE_SCENES,
                    "compared_all": scene_key not in self._L0_GATE_SCENES,
                })
            return hit

        return self._memo(key, frame, compute)

    def _reacquire_target_window(self, hwnd: int | None = None, timeout_s: float = 2.0) -> bool:
        """Bring target window to foreground and wait until confirmed foreground.
        Invalidates evidence cache on reacquisition.
        """
        target_hwnd = hwnd if hwnd is not None else (self._last_frame.hwnd if self._last_frame else None)
        if not target_hwnd:
            return False
        ok = reacquire_target_window(target_hwnd, timeout_s=timeout_s)
        if ok:
            self.invalidate_evidence("focus-reacquired")
        return ok

    def _focus_last_window(self) -> bool:
        if self.settings.dry_run or not isinstance(self.executor, InputExecutor):
            return True
        if not self._last_frame or not self._last_frame.hwnd or not is_window_valid(self._last_frame.hwnd):
            return True
        target_hwnd = self._last_frame.hwnd
        fg = get_foreground_window()
        if fg is not None and not foreground_matches_target(target_hwnd, fg):
            self.invalidate_evidence("focus-lost")
            if not self._reacquire_target_window(target_hwnd):
                print(f"[med] real input skipped: cannot focus hwnd={target_hwnd} (fg={fg})")
                return False
        return True
    def _finish_input(self, res, reason: str, action_ms: float = 0.0) -> bool:
        """输入返回后的统一收尾：输入标记、白名单 reason、证据失效。

        N2-REVIEW #2/#3：
        - 仅真实输入（非 dry-run）且 action_ms≥800ms 才标 input_executor_wait
          （dry-run 点击 ~0ms，慢 tick 不得借成功输入假绿）；
        - 每次成功输入（含 dry-run）递增 ``_input_seq``：同 tick 第二次动作
          被 _action_gate_ok 拒绝；LIVE 另有 invalidate_evidence 推进 gen。
        """
        self._last_input_status = str(getattr(res, "status", "") or "")
        if res.success or self._last_input_status == INPUT_DISPATCHED_UNVERIFIED:
            self._last_input_at = time.time()
            if reason == "ParkPointer":
                self._pointer_needs_park = False
        if res.success:
            self._tick_input_executed = True
            self._input_seq += 1
            if action_ms >= 800.0 and not self.settings.dry_run and self._tick_reason is None:
                self._tick_reason = "input_executor_wait"
            if not self.settings.dry_run:
                self.invalidate_evidence("input")
            # G0 P0 contract #3：最近业务动作可读（输入 reason 即动作名）。
            self.last_business_action = reason
        elif self._last_input_status == INPUT_DISPATCHED_UNVERIFIED:
            # 输入已注入、只是后置窗口校验没通过：证据必须失效，重复点击才是危险动作。
            self._input_seq += 1
            self._tick_input_executed = True
            if not self.settings.dry_run:
                self.invalidate_evidence("input-dispatched-unverified")
        return res.success

    def _last_input_dispatched_unverified(self) -> bool:
        """True when the last input reached the game but its outcome is unproven."""
        return getattr(self, "_last_input_status", "") == INPUT_DISPATCHED_UNVERIFIED

    def _action_forbidden(self, reason: str) -> bool:
        mode_id = str(getattr(self.settings, "mode_id", "") or "")
        if not mode_id:
            return False
        try:
            from shuabao.shell.mode_catalog import action_is_forbidden, get_spec

            spec = get_spec(mode_id)
        except Exception:
            return False
        if action_is_forbidden(reason, spec.forbidden_actions):
            print(f"[med] forbidden action denied: {reason} (mode={mode_id})")
            return True
        return False

    def act_click(self, hit: MatchResult, reason: str = "") -> bool:
        if self._action_forbidden(reason):
            return False
        if not self._action_gate_ok(reason):
            return False
        target_hwnd = self._last_frame.hwnd if self._last_frame else None
        print(f"[med] click {hit.name} score={hit.score:.3f} @ {hit.center} ({reason})")
        t0 = time.perf_counter()
        res = self.executor.click(
            hit.screen_x,
            hit.screen_y,
            target_hwnd=target_hwnd,
            dry_run=self.settings.dry_run,
            delay_ms=self.settings.click_delay_ms,
        )
        action_ms = (time.perf_counter() - t0) * 1000.0
        self._trace_actions.append({"intent": f"click:{hit.name}", "at": [hit.screen_x, hit.screen_y], "reason": reason, "ok": res.success, "action_ms": round(action_ms, 1)})
        ok = self._finish_input(res, reason, action_ms)
        self._note_pointer_on_hud(hit)
        return ok

    def act_right_click(self, hit: MatchResult, reason: str = "") -> bool:
        if self._action_forbidden(reason):
            return False
        if not self._action_gate_ok(reason):
            return False
        target_hwnd = self._last_frame.hwnd if self._last_frame else None
        print(f"[med] right_click {hit.name} score={hit.score:.3f} @ {hit.center} ({reason})")
        t0 = time.perf_counter()
        res = self.executor.right_click(
            hit.screen_x,
            hit.screen_y,
            target_hwnd=target_hwnd,
            dry_run=self.settings.dry_run,
            delay_ms=self.settings.click_delay_ms,
        )
        action_ms = (time.perf_counter() - t0) * 1000.0
        self._trace_actions.append({"intent": f"right_click:{hit.name}", "at": [hit.screen_x, hit.screen_y], "reason": reason, "ok": res.success, "action_ms": round(action_ms, 1)})
        ok = self._finish_input(res, reason, action_ms)
        self._note_pointer_on_hud(hit)
        return ok

    def act_key(self, key: str, reason: str = "") -> bool:
        if self._action_forbidden(reason):
            return False
        if not self._action_gate_ok(reason):
            return False
        target_hwnd = self._last_frame.hwnd if self._last_frame else None
        print(f"[med] key {key!r} ({reason})")
        t0 = time.perf_counter()
        res = self.executor.press_key(
            key,
            target_hwnd=target_hwnd,
            dry_run=self.settings.dry_run,
        )
        action_ms = (time.perf_counter() - t0) * 1000.0
        self._trace_actions.append({"intent": f"key:{key}", "reason": reason, "ok": res.success, "action_ms": round(action_ms, 1)})
        return self._finish_input(res, reason, action_ms)

    def act_hotkey(self, *keys: str, reason: str = "") -> bool:
        """Dispatch a hotkey through the same one-input-per-tick transaction."""
        if self._action_forbidden(reason):
            return False
        if not self._action_gate_ok(reason):
            return False
        target_hwnd = self._last_frame.hwnd if self._last_frame else None
        print(f"[med] hotkey {keys!r} ({reason})")
        t0 = time.perf_counter()
        res = self.executor.hotkey(
            *keys,
            target_hwnd=target_hwnd,
            dry_run=self.settings.dry_run,
        )
        action_ms = (time.perf_counter() - t0) * 1000.0
        self._trace_actions.append({"intent": f"hotkey:{keys}", "reason": reason, "ok": res.success, "action_ms": round(action_ms, 1)})
        return self._finish_input(res, reason, action_ms)

    def act_paste_text(self, text: str, reason: str = "") -> bool:
        """Paste text through the same gated input transaction as clicks/keys."""
        if self._action_forbidden(reason):
            return False
        if not self._action_gate_ok(reason):
            return False
        target_hwnd = self._last_frame.hwnd if self._last_frame else None
        print(f"[med] paste_text len={len(text)} ({reason})")
        t0 = time.perf_counter()
        res = self.executor.paste_text(
            text,
            target_hwnd=target_hwnd,
            dry_run=self.settings.dry_run,
        )
        action_ms = (time.perf_counter() - t0) * 1000.0
        self._trace_actions.append({"intent": "paste_text", "reason": reason, "ok": res.success, "action_ms": round(action_ms, 1)})
        return self._finish_input(res, reason, action_ms)

    def _note_pointer_on_hud(self, hit: MatchResult) -> None:
        """After an in-game click the pointer rests on what it clicked.

        Every bottom-HUD / right-edge control shows a tooltip in the right
        panel while hovered (live 2026-09-12: [Z]/[B]/[V] and the challenge
        icons covered the merchant strip; round 2 an item tooltip covered the
        auto-task box).  Remember it so the next HUD read parks the pointer
        first (_maybe_park_pointer).
        """
        frame = self._last_frame
        if frame is None or not self._passenger_mode() or self.phase != Phase.MAIN_LINE:
            return
        x = hit.screen_x - frame.left
        y = hit.screen_y - frame.top
        if y >= frame.height * 0.55 or x >= frame.width * 0.85:
            self._pointer_needs_park = True

    def _maybe_park_pointer(self, frame: Frame) -> LoopAction | None:
        """Clear our own tooltip before reading the HUD: move, don't click."""
        if not getattr(self, "_pointer_needs_park", False):
            return None
        if (
            self._public_bag_fsm.phase is not PublicBagPhase.IDLE
            or self._panel_state != PanelState.CLOSED
            or self._pending_action is not None
        ):
            # Mid-transaction the pointer is where the next click needs it.
            return None
        if self.act_move(
            int(frame.width * self._POINTER_PARK[0]),
            int(frame.height * self._POINTER_PARK[1]),
            "ParkPointer",
        ):
            return LoopAction.Continue
        # No move primitive (or input refused): read as before.
        self._pointer_needs_park = False
        return None

    def _has_active_transaction(self, frame: Frame | None = None) -> bool:
        """Unified arbitration guard: True if any transaction is in progress.

        Opportunistic inputs (artifacts, devour dan, Z pickup) must yield
        whenever another subsystem is mid-transaction.
        """
        # 1. Generic pending action awaiting verification/confirmation
        if self._pending_action is not None:
            return True
        # 2. Equipment FSM pending slot lease/verification
        eq_fsm = getattr(self, "_equipment_fsm", None)
        if eq_fsm is not None and eq_fsm.pending_slot is not None:
            return True
        # 3. Equipment affix choice modal visible on frame
        if frame is not None and self._find_equipment_affix_choice(frame) is not None:
            return True
        # 4. Evolve transaction: feedback pending or awaiting hero pick
        if self._evolve_hero_choice_pending():
            return True
        # 5. Merchant transaction: VERIFYING phase
        merchant_fsm = getattr(self, "_merchant_fsm", None)
        if merchant_fsm is not None and getattr(merchant_fsm, "phase", None) is MerchantPhase.VERIFYING:
            return True
        # 6. Public bag transfer in progress
        bag_fsm = getattr(self, "_public_bag_fsm", None)
        if bag_fsm is not None and getattr(bag_fsm, "active", False):
            return True
        return False

    def act_move(self, x: int, y: int, reason: str = "") -> bool:
        """Move the pointer to frame point (x, y) without pressing a button."""
        mover = getattr(self.executor, "move", None)
        if mover is None or self._last_frame is None:
            return False
        if self._action_forbidden(reason):
            return False
        if not self._action_gate_ok(reason):
            return False
        frame = self._last_frame
        sx, sy = frame.left + int(x), frame.top + int(y)
        print(f"[med] move pointer @ ({sx}, {sy}) ({reason})")
        t0 = time.perf_counter()
        res = mover(sx, sy, target_hwnd=frame.hwnd, dry_run=self.settings.dry_run)
        action_ms = (time.perf_counter() - t0) * 1000.0
        self._trace_actions.append({"intent": "move", "at": [sx, sy], "reason": reason, "ok": res.success, "action_ms": round(action_ms, 1)})
        return self._finish_input(res, reason, action_ms)

    def act_type_text(self, text: str, reason: str = "") -> bool:
        if self._action_forbidden(reason):
            return False
        if not self._action_gate_ok(reason):
            return False
        target_hwnd = self._last_frame.hwnd if self._last_frame else None
        print(f"[med] type {text!r} ({reason})")
        t0 = time.perf_counter()
        res = self.executor.type_text(
            text,
            target_hwnd=target_hwnd,
            dry_run=self.settings.dry_run,
        )
        action_ms = (time.perf_counter() - t0) * 1000.0
        self._trace_actions.append({"intent": f"type:{text}", "reason": reason, "ok": res.success, "action_ms": round(action_ms, 1)})
        return self._finish_input(res, reason, action_ms)

    def act_double_click(self, hit: MatchResult, reason: str = "") -> bool:
        if self._action_forbidden(reason):
            return False
        if not self._action_gate_ok(reason):
            return False
        target_hwnd = self._last_frame.hwnd if self._last_frame else None
        print(f"[med] double_click {hit.name} score={hit.score:.3f} @ {hit.center} ({reason})")
        t0 = time.perf_counter()
        res = self.executor.double_click(hit.screen_x, hit.screen_y, target_hwnd=target_hwnd, dry_run=self.settings.dry_run, delay_ms=50)
        action_ms = (time.perf_counter() - t0) * 1000.0
        self._trace_actions.append({"intent": f"double_click:{hit.name}", "at": [hit.screen_x, hit.screen_y], "reason": reason, "ok": res.success, "action_ms": round(action_ms, 1)})
        return self._finish_input(res, reason, action_ms)

    def act_search_box(self, hit: MatchResult, text: str, reason: str = "") -> bool:
        if self._action_forbidden(reason):
            return False
        if not self._action_gate_ok(reason):
            return False
        target_hwnd = self._last_frame.hwnd if self._last_frame else None
        print(f"[med] search_box text={text!r} @ {hit.center} ({reason})")
        t0 = time.perf_counter()
        res = self.executor.search_text(hit.screen_x, hit.screen_y, text, target_hwnd=target_hwnd, dry_run=self.settings.dry_run)
        action_ms = (time.perf_counter() - t0) * 1000.0
        self._trace_actions.append({"intent": f"search:{text}", "at": [hit.screen_x, hit.screen_y], "reason": reason, "ok": res.success, "action_ms": round(action_ms, 1)})
        return self._finish_input(res, reason, action_ms)

    def act_scroll(self, x: int, y: int, clicks: int, reason: str = "") -> bool:
        """Send one guarded scroll through the existing input executor.

        Scrolling is an input-bearing action just like a click: it consumes
        the current evidence token, is recorded in the action trace, and must
        be followed by a fresh frame before another decision is made.
        """
        if self._action_forbidden(reason):
            return False
        if not self._action_gate_ok(reason):
            return False
        target_hwnd = self._last_frame.hwnd if self._last_frame else None
        print(f"[med] scroll clicks={clicks} @ ({x}, {y}) ({reason})")
        t0 = time.perf_counter()
        res = self.executor.scroll(
            int(x),
            int(y),
            int(clicks),
            target_hwnd=target_hwnd,
            dry_run=self.settings.dry_run,
        )
        action_ms = (time.perf_counter() - t0) * 1000.0
        self._trace_actions.append({
            "intent": "scroll",
            "at": [int(x), int(y)],
            "clicks": int(clicks),
            "reason": reason,
            "ok": res.success,
            "action_ms": round(action_ms, 1),
        })
        return self._finish_input(res, reason, action_ms)

    def click_scene(self, frame: Frame, scene_key: str, reason: str = "", threshold: float | None = None) -> bool:
        hit = self.find_scene(frame, scene_key, threshold=threshold)
        if not hit:
            print(f"[med] miss scene={scene_key} th={threshold or self.settings.match_threshold} ({reason})")
            return False
        return self.act_click(hit, reason or scene_key)

    # ---------- 局内选择 / 挑战 ----------

    # 选择面板底部按钮锚点（配置顺序 = 优先级，N2.1 early_stop 按此返回）
    _ANCHOR_NAMES: list[str] = [
        "skill_giveup_btn",
        "skill_refresh_btn",
        "bond_hide_btn",
        "bond_refresh_btn",
        "treasure_hide_btn",
        "treasure_lock_btn",
        "treasure_refresh_btn",
        "toHero",
        "skill_hide",
        "card_hide",
        "hide",
    ]

    @staticmethod
    def _selection_roi() -> tuple[float, float, float, float]:
        """中央三选一面板 ROI；排除右下角背包和左侧快捷键。"""
        return 0.24, 0.16, 0.76, 0.66

    def _selection_anchor(self, frame: Frame) -> MatchResult | None:
        """Find the bottom anchor of a reward-choice panel.

        Panel types (live ops-video 2026-08-08, 1600x900 window coords):
        - skill:   放弃(580,552) / 刷新(3)(860,552)   [no 暂时隐藏]
        - bond:    暂时隐藏(580,552) / 刷新40(860,552)
        - treasure:暂时隐藏(375,572) / 锁定(580,572) / 刷新(3)(785,572)
        Legacy templates skill_hide/card_hide/hide cover older UIs.
        ROI is pruned to the mid-lower band where these buttons live.

        N2.1：固定 selection ROI + 主/邻尺度 + 优先级早停（首个过阈值命中即止）；
        早停命中位置校验失败时回退完整扫描（保持旧语义）。
        """
        threshold = min(0.70, self.settings.match_threshold)
        scales = self._hot_scales()
        roi = (0.20, 0.50, 0.80, 0.75)  # N2.4：按钮实测 y≈0.59-0.64，收紧竖带
        key = ("anchor", tuple(self._ANCHOR_NAMES), threshold, scales, roi, ("early_stop", 0.0))

        def position_ok(hit: MatchResult) -> bool:
            # hit.x/y 在 ROI 裁剪后是 ROI 内坐标；用屏幕坐标换算回帧坐标做位置校验
            fx = hit.screen_x - frame.left
            fy = hit.screen_y - frame.top
            if fx < frame.width * 0.20 or fx > frame.width * 0.80:
                return False
            if fy < frame.height * 0.50:
                return False
            return True

        def compute():
            hit = self.find(
                frame,
                self._ANCHOR_NAMES,
                threshold=threshold,
                scales=scales,
                roi=roi,
                early_stop=True,
                mode="anchor:es",
            )
            if hit is not None and position_ok(hit):
                if len(self._trace_scenes) < 12:
                    self._trace_scenes.append({
                        "scene": "selection_anchor",
                        "name": hit.name,
                        "score": round(hit.score, 3),
                        "early_stop": True,
                        "compared_all": False,
                    })
                return hit
            if hit is not None:
                # early-stop 命中带外（位置校验失败）：回退完整扫描
                hit = self.find(
                    frame,
                    self._ANCHOR_NAMES,
                    threshold=threshold,
                    scales=scales,
                    roi=roi,
                    early_stop=False,
                    mode="anchor:full",
                )
                if hit is not None and position_ok(hit):
                    return hit
            # 主尺度全 miss → 宽尺度回退（仅 DPI 放大窗口；基准窗口不宽搜）
            if self._scaled_up_frame(frame):
                hit = self.find(
                    frame,
                    self._ANCHOR_NAMES,
                    threshold=threshold,
                    scales=self._wide_scales(),
                    roi=roi,
                    early_stop=True,
                    mode="anchor:es-wide",
                )
                if hit is not None and position_ok(hit):
                    return hit
            return None

        return self._memo(key, frame, compute)

    def _evolve_hero_choice_pending(self) -> bool:
        return bool(
            getattr(self, "_evolve_awaiting_hero_pick", False)
            or getattr(self, "_evolve_feedback_pending", False)
        )

    def _classify_choice_panel(self, frame: Frame) -> str | None:
        """Distinguish skill / bond / treasure choice panels by their unique buttons."""
        if self._evolve_hero_choice_pending() and getattr(self, "_panel_opened_by_us", None) not in (
            "skill", "bond", "treasure",
        ):
            # 进化后的英雄二选一会误中 treasure_lock，先交给英雄排序。
            return None
        opened = getattr(self, "_panel_opened_by_us", None)
        if opened == "treasure":
            # 放弃钮是技能独有；宝物面板绝无放弃按钮。
            skill_giveup = self.find(
                frame, ["giveUp"],
                threshold=min(0.70, self.settings.match_threshold),
                scales=self._hot_scales(),
                roi=self._PANEL_BUTTONS_ROI,
            )
            if skill_giveup is not None:
                return "skill"
            # 锁等专用锚点可强化判定；旧版真 V 面板偶有只在宽尺度命中锁。
            if self._treasure_panel_joint_confirmed(
                frame, min(0.70, self.settings.match_threshold), self._hot_scales()
            ):
                return "treasure"
            return None
        elif opened in ("skill", "bond"):
            return opened
        threshold = min(0.70, self.settings.match_threshold)
        kind = self._classify_choice_panel_at(frame, threshold, self._hot_scales())
        if kind is None and self._scaled_up_frame(frame):
            # 主尺度无法归类 → 宽尺度回退（仅 DPI 放大窗口）
            kind = self._classify_choice_panel_at(frame, threshold, self._wide_scales())
        return kind

    def _classify_choice_panel_at(self, frame: Frame, threshold: float, scales: tuple[float, ...]) -> str | None:
        # N2.4：面板按钮行位置已知（实测 y≈0.59-0.64），全帧扫描不再必要。
        roi = self._PANEL_BUTTONS_ROI
        # P0-3（215302）：bond 定类需要 bond_hide_btn + bond_refresh_btn 联合证据；
        # 单独 bond_refresh_btn（0.70-0.79 贴阈值）不得定类 bond（曾单锚点误入面板）。
        bond_hide = self.find(frame, ["bond_hide_btn"], threshold=threshold, scales=scales, roi=roi)
        bond_refresh = self.find(frame, ["bond_refresh_btn"], threshold=threshold, scales=scales, roi=roi)
        if bond_hide is not None and bond_refresh is not None:
            return "bond"
        # Current treasure and skill panels share refresh/give-up artwork.
        # G 三选也有「暂时隐藏」，treasure_lock 会误匹配遮罩（13号 200601 tick9）。
        # 放弃钮是技能独有；锁模板单独命中不足以为宝物（与 bond 单锚点同纪律）。
        skill_hit = self.find(
            frame, ["skill_giveup_btn", "skill_refresh_btn"],
            threshold=threshold, scales=scales, roi=roi,
        )
        treasure_lock = self.find(frame, ["treasure_lock_btn"], threshold=threshold, scales=scales, roi=roi)
        treasure_hide = self.find(frame, ["treasure_hide_btn"], threshold=threshold, scales=scales, roi=roi)
        treasure_refresh = self.find(frame, ["treasure_refresh_btn"], threshold=threshold, scales=scales, roi=roi)
        if skill_hit is not None and skill_hit.name == "skill_giveup_btn":
            return "skill"
        treasure_joint = (
            (treasure_lock is not None and treasure_hide is not None)
            or (treasure_lock is not None and treasure_refresh is not None)
            or (treasure_hide is not None and treasure_refresh is not None)
        )
        if treasure_joint and skill_hit is None:
            return "treasure"
        if skill_hit is not None:
            return "skill"
        if treasure_joint:
            return "treasure"
        if self.find(frame, ["card_hide"], threshold=threshold, scales=scales, roi=roi):
            return "card"
        return None

    def _treasure_panel_joint_confirmed(
        self, frame: Frame, threshold: float, scales: tuple[float, ...]
    ) -> bool:
        """A V request needs a lock; giveUp preemption above keeps skill panels out."""
        special_hits = tuple(
            self.find(
                frame, [name], threshold=threshold, scales=scales, roi=self._PANEL_BUTTONS_ROI
            )
            for name in ("treasure_lock_btn", "treasure_hide_btn", "treasure_refresh_btn")
        )
        if sum(hit is not None for hit in special_hits) >= 2:
            return True
        has_lock = special_hits[0] is not None
        return has_lock

    @staticmethod
    def _preferred_choice(hits: list[MatchResult], preferred: list[str]) -> MatchResult | None:
        wanted = {Path(value).stem for value in preferred if value}
        return next((hit for hit in hits if hit.name in wanted), None)

    def _auto_task_roi_frame(self, frame: Frame) -> Frame | None:
        if frame.bgr is None or frame.bgr.size == 0 or frame.width < 320 or frame.height < 180:
            return None
        h, w = frame.height, frame.width
        x1, x2 = int(0.85 * w), int(0.95 * w)
        y1, y2 = int(0.50 * h), int(0.65 * h)
        roi_bgr = frame.bgr[y1:y2, x1:x2]
        if roi_bgr.size == 0:
            return None
        return Frame(bgr=roi_bgr, left=frame.left + x1, top=frame.top + y1)

    def _is_auto_task_enabled(self, frame: Frame) -> bool:
        """Check the right task panel using relative ON/OFF template scores."""
        state, _ = self._auto_task_state(frame)
        return state == "ON"

    def _auto_task_state_detail(
        self,
        frame: Frame,
    ) -> tuple[str, MatchResult | None, float, float]:
        """Return state, hit, and the existing ON/OFF scores for diagnostics."""
        key = ("auto_task", round(self._ui_scale, 3))

        def compute() -> tuple[str, MatchResult | None, float, float]:
            roi_frame = self._auto_task_roi_frame(frame)
            if roi_frame is None:
                return "UNKNOWN", None, 0.0, 0.0
            tmpl_on = resolve_template(self.images, "auto_task_on")
            tmpl_off = resolve_template(self.images, "auto_task_off")
            if not tmpl_on or not tmpl_off or not tmpl_on.is_file() or not tmpl_off.is_file():
                return "UNKNOWN", None, 0.0, 0.0
            scales = self._adapt_scales((0.9, 1.0, 1.1))
            on = match_one(roi_frame, tmpl_on, threshold=0.50, name="auto_task_on", scales=scales)
            off = match_one(roi_frame, tmpl_off, threshold=0.50, name="auto_task_toggle", scales=scales)
            on_score = on.score if on else 0.0
            off_score = off.score if off else 0.0
            if max(on_score, off_score) < 0.72 or abs(on_score - off_score) < 0.06:
                return "UNKNOWN", None, on_score, off_score
            return (("ON", on) if on_score > off_score else ("OFF", off)) + (on_score, off_score)

        return self._memo(key, frame, compute)

    def _auto_task_state(self, frame: Frame) -> tuple[str, MatchResult | None]:
        """Return ON/OFF/UNKNOWN while preserving the existing two-value API."""
        state, hit, _on_score, _off_score = self._auto_task_state_detail(frame)
        return state, hit

    def _trace_auto_task_control(
        self,
        state: str,
        on_score: float,
        off_score: float,
        hit: MatchResult | None,
        pending_age: float | None,
    ) -> None:
        self._trace_controls.append({
            "control": "auto_task",
            "state": state,
            "on_score": round(on_score, 3),
            "off_score": round(off_score, 3),
            "label_bbox": [hit.x, hit.y, hit.w, hit.h] if hit else None,
            "click_point": list(hit.center) if hit else None,
            "pending_age": pending_age,
        })

    def _find_auto_task_toggle(self, frame: Frame) -> MatchResult | None:
        """Return a left-click candidate only for explicit OFF evidence."""
        if self._selection_anchor(frame):
            return None
        state, hit = self._auto_task_state(frame)
        return hit if state == "OFF" else None

    def _auto_task_unknown_timeout_s(self) -> float:
        """UNKNOWN fuse budget: default 45s, hard-clamped to 30–60s."""
        raw = getattr(self.settings, "auto_task_unknown_timeout_s", 45.0)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 45.0
        if value != value:
            value = 45.0
        return max(30.0, min(60.0, value))

    def _auto_task_unknown_fuse(self, state: str) -> LoopAction | None:
        """Keep unknown loading surfaces input-free until the game UI returns."""
        normalized = str(state or "").strip().upper()
        if normalized in {"ON", "OFF"}:
            self._auto_task_unknown_since = None
            return None
        if normalized != "UNKNOWN":
            self._auto_task_unknown_since = None
            return None
        now_mono = time.monotonic()
        if self._auto_task_unknown_since is None:
            self._auto_task_unknown_since = now_mono
        elapsed = now_mono - self._auto_task_unknown_since
        timeout = self._auto_task_unknown_timeout_s()
        if elapsed >= timeout:
            print(
                f"[L1] 自动任务 UNKNOWN 已持续 {elapsed:.1f}s "
                f"(阈值 {timeout:.1f}s)，保持零输入等待页面恢复"
            )
            if self._passenger_mode():
                # Stop holding the round, but keep watching: explicit OFF
                # evidence later (the real HUD after a long pre-round page)
                # re-arms the enable click through the recheck path.
                print("[L1] 蹭车自动任务暂无法确认，先放行局内流程，稍后看到未勾选再开启")
                self._auto_task_done = True
                self._auto_task_recheck_at = time.time() + self.settings.ui_action_interval_s
                self._auto_task_unknown_since = None
                return None
        # Loading/interstitial screens have no stable auto-task control.  They
        # are not an unsafe command condition, so do not end the live run.
        return LoopAction.Continue

    def _ensure_auto_task_enabled(self, frame: Frame) -> LoopAction | None:
        """Enable auto-task with a bounded post-click observation window."""
        # B2：auto_close_main_line 触发后期望状态是 OFF——通用启用门禁绝不
        # 得再把勾选打回去；主线关闭完成后亦永不重新启用。
        if getattr(self.settings, "auto_close_main_line", False) and getattr(self, "_close_main_line_triggered", False):
            return None
        if getattr(self, "_main_line_closed_done", False):
            return None
        now = time.time()
        state, hit = self._auto_task_state(frame)
        if getattr(self, "_auto_task_done", False):
            # Once verified ON, a hidden checkbox (bag page, item tooltip,
            # modal) is only "not visible this frame".  It must never freeze
            # the main line: live 2026-09-11 an item tooltip covering it held
            # every in-game action, the public-bag hop included, for minutes.
            self._auto_task_unknown_since = None
            if state == "UNKNOWN" and not self._is_in_game_hud(frame):
                # Neither the checkbox nor any HUD anchor: a loading, black
                # or foreign surface still gets no in-game input.
                return LoopAction.Continue
            if self._auto_task_recheck_at <= 0.0 or now < self._auto_task_recheck_at:
                return None
            if state == "UNKNOWN":
                self._auto_task_recheck_at = now + self.settings.ui_action_interval_s
                return None
        was_done = getattr(self, "_auto_task_done", False)
        fuse = self._auto_task_unknown_fuse(state)
        if fuse is not None:
            return fuse
        if not was_done and getattr(self, "_auto_task_done", False):
            # The passenger fuse just released the round; its own recheck
            # timer decides when to look again.
            return None
        if getattr(self, "_auto_task_done", False):
            state, hit, on_score, off_score = self._auto_task_state_detail(frame)
            if state == "ON":
                self._trace_auto_task_control(state, on_score, off_score, hit, None)
                self._auto_task_recheck_at = now + self._control_recheck_interval_s
                return None
            if state != "OFF":
                self._trace_auto_task_control(state, on_score, off_score, hit, None)
                self._auto_task_recheck_at = now + self.settings.ui_action_interval_s
                return None
            # A failed main-line attempt may turn this control off again.
            # Re-arm only on explicit OFF evidence; UNKNOWN stays zero-input.
            self._auto_task_done = False
            self._auto_task_attempts = 0

        detail_res = getattr(self, "_last_auto_task_detail", None)
        if detail_res and detail_res[0] == state:
            on_score, off_score = detail_res[2], detail_res[3]
        else:
            on_score, off_score = 0.0, 0.0
        pending_since = self._auto_task_pending_since
        pending_age = round(now - pending_since, 2) if pending_since is not None else None

        if pending_since is not None:
            if state == "ON":
                self._auto_task_done = True
                self._auto_task_recheck_at = now + self._control_recheck_interval_s
                self._auto_task_pending_since = None
                self._auto_task_next_observe_at = None
                return None
            if now < (self._auto_task_next_observe_at or now):
                self._trace_auto_task_control(state, on_score, off_score, hit, pending_age)
                print(
                    f"[L1] 自动任务等待勾选状态稳定（零输入，"
                    f"{pending_age:.1f}/{self.settings.ui_action_interval_s:.1f}s）"
                )
                return LoopAction.Continue
            self._auto_task_pending_since = None
            self._auto_task_next_observe_at = None
            if state != "OFF":
                self._trace_auto_task_control(state, on_score, off_score, hit, pending_age)
                print("[L1] 自动任务观察窗到期仍 UNKNOWN，保守零输入")
                return LoopAction.Continue

        if state == "ON":
            self._trace_auto_task_control(state, on_score, off_score, hit, pending_age)
            print("[L1] 自动任务开启模式已验证（已勾选）")
            self._auto_task_done = True
            self._auto_task_recheck_at = now + self._control_recheck_interval_s
            return None
        if self._auto_task_attempts >= 3:
            self._trace_auto_task_control(state, on_score, off_score, hit, pending_age)
            if self._passenger_mode():
                print(f"[L1] 蹭车自动任务重试已达上限 ({self._auto_task_attempts})，本局跳过该步并继续")
                self._auto_task_done = True
                self._auto_task_recheck_at = 0.0
                return None
            print(f"[L1] 自动任务点击重试已达上限 ({self._auto_task_attempts})，Fail-Closed 停止运行")
            self.set_phase(Phase.ERROR, "auto_task attempt limit reached")
            self.stop()
            return LoopAction.Break

        toggle = self._find_auto_task_toggle(frame)
        if not toggle:
            self._trace_auto_task_control(state, on_score, off_score, hit, pending_age)
            return None

        self._auto_task_attempts += 1
        self._trace_auto_task_control(state, on_score, off_score, toggle, pending_age)
        print(f"[L1] 自动开启【自动任务】左键 @ {toggle.center} (尝试 {self._auto_task_attempts}/3)")
        if self.act_click(toggle, "EnableAutoTask"):
            self._auto_task_pending_since = time.time()
            self._auto_task_next_observe_at = (
                self._auto_task_pending_since + self.settings.ui_action_interval_s
            )
            return LoopAction.Continue

        if self._auto_task_attempts >= 3:
            if self._passenger_mode():
                print(f"[L1] 蹭车自动任务输入失败已达上限 ({self._auto_task_attempts})，本局跳过该步并继续")
                self._auto_task_done = True
                self._auto_task_recheck_at = 0.0
                return None
            print(f"[L1] 自动任务点击失败且重试已达上限 ({self._auto_task_attempts})，Fail-Closed 停止运行")
            self.set_phase(Phase.ERROR, "EnableAutoTask click failed")
            self.stop()
            return LoopAction.Break
        return LoopAction.Continue

    def _find_failure_gift(self, frame: Frame) -> MatchResult | None:
        res = self.find(frame, ["failGiftClose"], threshold=0.80, roi=(0.40, 0.15, 0.65, 0.40))
        if res is not None and getattr(res, "name", None) == "failGiftClose":
            return res
        return None


    # Card-badge rarity order: EX/UR > SSR > SR > R > N.
    RARITY_BANDS = (
        ("red", 5),
        ("orange", 4),
        ("purple", 3),
        ("blue", 2),
        ("white", 1),
        ("green", 0),
    )

    @staticmethod
    def _normalized_bbox(frame: Frame, roi: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
        x0, y0, x1, y1 = roi
        return (
            int(frame.width * x0), int(frame.height * y0),
            int(frame.width * x1), int(frame.height * y1),
        )

    @staticmethod
    def _description_line_bands(
        frame: Frame,
        roi: tuple[float, float, float, float],
        scan_y1: float,
    ) -> list[tuple[int, int]]:
        """Find bright text rows inside one card without sending the icon to OCR."""
        if frame.bgr is None or frame.bgr.size == 0:
            return []
        x0, y0, x1, _ = roi
        px0 = int(frame.width * x0)
        px1 = int(frame.width * x1)
        py0 = int(frame.height * y0)
        py1 = min(frame.height, int(frame.height * scan_y1))
        pad = max(4, int((px1 - px0) * 0.05))
        ix0, ix1 = px0 + pad, px1 - pad
        if ix1 <= ix0 or py1 <= py0:
            return []
        crop = frame.bgr[py0:py1, ix0:ix1]
        if crop.size == 0:
            return []
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        row_counts = ((hsv[:, :, 2] > 145).sum(axis=1))
        minimum = max(4, int(crop.shape[1] * 0.02))
        rows = [int(row) for row in np.flatnonzero(row_counts >= minimum)]
        groups: list[list[int]] = []
        for row in rows:
            if not groups or row > groups[-1][-1] + 1:
                groups.append([row])
            else:
                groups[-1].append(row)
        bands: list[tuple[int, int]] = []
        for group in groups:
            if len(group) < 2 or len(group) > 20:
                continue
            bands.append((
                max(py0, py0 + group[0] - 6),
                min(py1, py0 + group[-1] + 7),
            ))
            if len(bands) >= 5:
                break
        return bands

    def _ocr_panel_slots(self, frame: Frame, kind: str) -> list[dict]:
        """Read title (+ treasure description) lines with deterministic layout=3 or 4 detection.
        When layout is determined, name ROI, desc ROI, rarity ROI and click centers MUST use the same layout.
        """
        if self._ocr_client is None or not LayoutTransform.is_supported(frame.width, frame.height):
            return []
        rois_3 = self._OCR_SLOT_ROIS.get(kind)
        rois_4 = self._OCR_SLOT_ROIS_4.get(kind)
        if rois_3 is None:
            return []
        panel_id = f"{kind}:{self._trace_frame_fingerprint(frame)}"
        panel_bbox = (
            int(frame.width * 0.18),
            int(frame.height * 0.14),
            int(frame.width * 0.82),
            int(frame.height * 0.58),
        )

        def scan(rois: tuple, pid: str) -> list[dict]:
            out: list[dict] = []
            for index, roi in enumerate(rois):
                bbox = self._normalized_bbox(frame, roi)
                response = self._ocr_client.shadow_predict(
                    frame,
                    pid,
                    {"index": index, "bbox": bbox, "kind": kind},
                    panel_bbox=panel_bbox,
                )
                top = response.candidates[0] if response.candidates else None
                conf = float(top.confidence) if top else 0.0
                raw = str(response.raw_text or "")
                name = top.name if top and top.name and conf >= 0.45 else None
                if not name and raw:
                    # 只有完整的“名称(已持有/上限)”形态才从 raw_text 回填。
                    # 4 槽 ROI 误扫 3 槽牌面时，常见碎片是 ``0/3)挑占``；
                    # 仅搜索数字比值会把这种碎片当成可用牌名，进而选错布局。
                    ratio_match = re.fullmatch(
                        r"\s*(?P<name>[^()[\]（）]+?)\s*[\[（(]\s*\d+\s*/\s*\d+\s*[\])）)]\s*",
                        raw,
                    )
                    stripped = ratio_match.group("name").strip() if ratio_match else ""
                    if stripped and not re.search(r"\d", stripped):
                        name = stripped
                        conf = max(conf, float(response.rec_score or 0.0))
                out.append({
                    "index": index,
                    "name": name,
                    "confidence": conf,
                    "raw_text": raw,
                    "rec_score": response.rec_score,
                    "status": response.status,
                    "reason": response.reason,
                    "rarity": None,
                    "description": "",
                })
            if kind == "bond":
                self._fill_bond_slots_by_title_template(frame, out, rois)
            return out

        # 4 槽是当前局内羁绊的常见布局，但低置信碎片不足以证明布局。
        # 只有 3 个以上清晰名称时跳过 3 槽扫描；否则补扫一次 3 槽，避免
        # 三张宝物被四槽 ROI 错位后只剩中间两张“看起来像识别成功”。
        candidates_4: list[dict] = []
        if rois_4 is not None and len(rois_4) == 4:
            candidates_4 = scan(rois_4, f"{panel_id}:4s")
        named_4 = sum(1 for s in candidates_4 if s.get("name"))
        candidates_3: list[dict] = []
        if named_4 <= 2:
            candidates_3 = scan(rois_3, panel_id)
        named_3 = sum(1 for s in candidates_3 if s.get("name"))

        def whole_titles(slots: list[dict]) -> int:
            # A misaligned ROI reads two-character fragments (``梭哈``) that
            # can still fuzzy-match a catalog name (``杀敌梭哈``).
            return sum(
                1 for s in slots
                if len(re.sub(r"\s", "", str(s.get("raw_text") or ""))) >= 3
                and float(s.get("rec_score") or 0.0) >= 0.6
            )

        # 2026-09-12 live: 3-slot read 双倍神符/提高上限/木材梭哈, 4-slot read
        # ""/申符/上限/梭哈; both named one card, and the 4-slot tie hid the
        # panel every time. On a tie the layout reading whole titles wins.
        prefer_4 = named_4 > named_3 or (
            named_4 == named_3 and whole_titles(candidates_4) >= whole_titles(candidates_3)
        )
        if rois_4 is not None and named_4 >= 1 and prefer_4:
            slot_count = 4
            slots = candidates_4
            desc_spec = self._OCR_DESC_ROIS_4.get(kind) if hasattr(self, "_OCR_DESC_ROIS_4") else None
        elif named_3 >= 1:
            slot_count = 3
            slots = candidates_3
            desc_spec = self._OCR_DESC_ROIS.get(kind)
        else:
            return []

        # 统一采样该 layout 下所有槽位的 rarity
        for slot in slots:
            letter, band = self._read_slot_rarity_badge(frame, kind, slot["index"], slot_count=slot_count)
            slot["rarity"] = band
            slot["rarity_letter"] = letter

        # 描述 ROI：宝物负面判定必须匹配对应 layout
        if desc_spec is not None:
            half_w = float(desc_spec["half_w"])
            y0 = float(desc_spec["y0"])
            y1 = float(desc_spec["y1"])
            scan_y1 = float(desc_spec.get("scan_y1", y1))
            centers_x = desc_spec["centers_x"]
            for slot in slots:
                idx = slot["index"]
                if idx < len(centers_x):
                    cx = centers_x[idx]
                    desc_roi = (float(cx) - half_w, y0, float(cx) + half_w, y1)
                    bbox = self._normalized_bbox(frame, desc_roi)
                    bands = self._description_line_bands(frame, desc_roi, scan_y1)
                    if not bands:
                        bands = [(bbox[1], bbox[3])]
                    texts: list[str] = []
                    for line_index, (line_y0, line_y1) in enumerate(bands):
                        line_bbox = (bbox[0], line_y0, bbox[2], line_y1)
                        response = self._ocr_client.shadow_predict(
                            frame,
                            f"{panel_id}:desc:{slot_count}:{line_index}",
                            {"index": idx, "bbox": line_bbox, "kind": f"{kind}_desc"},
                            panel_bbox=panel_bbox,
                        )
                        text = (response.raw_text or "").strip()
                        if not text and response.candidates:
                            text = (response.candidates[0].name or "").strip()
                        response_score = float(getattr(response, "rec_score", 0.0) or 0.0)
                        # A real 1600x900 capture showed a few right-edge lines
                        # clipped by only 2-3 pixels (e.g. ``复4%的最大生命值``).
                        # Keep the calibrated crop as the fast path; retry once
                        # only for an empty/very short result, and accept the
                        # wider result only when it is materially more complete.
                        if (
                            str(getattr(response, "status", "ok")) == "ok"
                            and (not text or len(text) <= 3 or response_score < 0.65)
                        ):
                            extra_x = max(2, int(round(frame.width * 0.002)))
                            wide_bbox = (
                                bbox[0],
                                line_y0,
                                min(frame.width, bbox[2] + extra_x),
                                line_y1,
                            )
                            wide_response = self._ocr_client.shadow_predict(
                                frame,
                                f"{panel_id}:desc:{slot_count}:{line_index}:wide",
                                {"index": idx, "bbox": wide_bbox, "kind": f"{kind}_desc"},
                                panel_bbox=panel_bbox,
                            )
                            wide_text = (wide_response.raw_text or "").strip()
                            if not wide_text and wide_response.candidates:
                                wide_text = (wide_response.candidates[0].name or "").strip()
                            wide_score = float(getattr(wide_response, "rec_score", 0.0) or 0.0)
                            wide_usable = (
                                wide_text
                                and str(getattr(wide_response, "status", "ok")) == "ok"
                                and wide_score >= 0.45
                                and re.search(r"[\u4e00-\u9fffA-Za-z]", wide_text)
                            )
                            if wide_usable and (
                                not text
                                or (
                                    len(wide_text) >= max(4, len(text) + 2)
                                    and wide_score >= max(0.45, response_score - 0.15)
                                )
                            ):
                                text = wide_text
                                response_score = wide_score
                        if (
                            text
                            and str(getattr(response, "status", "ok")) == "ok"
                            and response_score >= 0.45
                            and re.search(r"[\u4e00-\u9fffA-Za-z]", text)
                            and text not in texts
                        ):
                            texts.append(text)
                    slot["description"] = "\n".join(texts)

        self._trace_ocr_suggestion = {"kind": kind, "slots": slots, "layout": slot_count}
        return slots

    def _fill_bond_slots_by_title_template(
        self,
        frame: Frame,
        slots: list[dict],
        rois: tuple,
    ) -> None:
        """Fill empty/low-conf bond titles from official cards/*.png glyphs."""
        preferred = self._bond_template_preferences()
        if not preferred or frame is None or getattr(frame, "bgr", None) is None:
            return
        templates: list[tuple[str, str, np.ndarray]] = []
        for code in preferred:
            path = resolve_template(self.images, f"cards/{code}") or resolve_template(
                self.images, code
            )
            tpl = _load_template(path) if path is not None else None
            if tpl is None:
                continue
            label = str(self._fetter_labels.get(code, code)).strip() or code
            templates.append((code, label, tpl))
        if not templates:
            return
        min_score = float(self._BOND_TITLE_TEMPLATE_MIN)
        for slot, roi in zip(slots, rois):
            conf = float(slot.get("confidence") or 0.0)
            name = str(slot.get("name") or "").strip()
            bbox = self._normalized_bbox(frame, roi)
            x0, y0, x1, y1 = bbox
            crop = frame.bgr[y0:y1, x0:x1]
            if crop is None or crop.size == 0:
                continue
            best_s = -1.0
            best_label = ""
            best_code = ""
            for code, label, tpl in templates:
                th, tw = tpl.shape[:2]
                if crop.shape[0] < th or crop.shape[1] < tw:
                    continue
                raw_score = cv2.minMaxLoc(cv2.matchTemplate(crop, tpl, cv2.TM_CCOEFF_NORMED))[1]
                score = float(raw_score)
                if not np.isfinite(score) or score <= best_s:
                    continue
                best_s, best_label, best_code = score, label, code
            if best_s < min_score:
                continue
            if name and conf >= min_score and best_s < conf:
                continue
            slot["name"] = best_label
            slot["confidence"] = max(conf, best_s)
            if not str(slot.get("raw_text") or "").strip():
                slot["raw_text"] = best_label
            slot["reason"] = f"title_template:{best_code}:{best_s:.3f}"
            print(f"[L1] 羁绊标题模板 slot{slot.get('index')} {best_label} {best_s:.3f}")

    def _read_slot_rarity_badge(
        self,
        frame: Frame,
        kind: str,
        index: int,
        slot_count: int = 3,
    ) -> tuple[str | None, str | None]:
        """Read card rarity letter (N/R/SR/SSR/UR/EX) via OCR on the top badge ROI.

        Returns (letter, band), e.g. ('SR', 'purple'), or (None, None).
        """
        if self._ocr_client is None or not getattr(self._ocr_client, "is_ready", False):
            return None, None
        if not LayoutTransform.is_supported(frame.width, frame.height):
            return None, None
        rois_dict = self._RARITY_BADGE_ROIS_4 if slot_count == 4 else self._RARITY_BADGE_ROIS
        rois = rois_dict.get(kind) or rois_dict.get("bond")
        if not rois or index < 0 or index >= len(rois):
            return None, None
        roi = rois[index]
        bbox = self._normalized_bbox(frame, roi)
        resp = self._ocr_client.shadow_predict(
            frame,
            f"{kind}:rarity_badge",
            {"index": index, "bbox": bbox, "kind": "rarity"},
        )
        raw = str(resp.raw_text or "").strip()
        clean = re.sub(r"[^A-Za-z]", "", raw).upper()
        if clean in self._RARITY_LETTER_TO_BAND:
            return clean, self._RARITY_LETTER_TO_BAND[clean]
        return None, None

    def _slot_rarity_band(self, frame: Frame, kind: str, index: int, slot_count: int = 3) -> str | None:
        """Map slot index to a badge-OCR rarity band; unreadable stays unknown."""
        return self._read_slot_rarity_badge(frame, kind, index, slot_count=slot_count)[1]

    def _slots_to_candidates(self, frame: Frame, kind: str, slots: list[dict]) -> tuple[SlotCandidate, ...]:
        """Map OCR slot dicts → SlotCandidate (rarity/description filled when present)."""
        out: list[SlotCandidate] = []
        for slot in slots:
            index = int(slot.get("index", 0))
            rarity = slot.get("rarity")
            rarity_letter = slot.get("rarity_letter")
            if rarity is None and frame is not None:
                letter, band = self._read_slot_rarity_badge(frame, kind, index, slot_count=len(slots))
                rarity = band
                rarity_letter = letter
            description = str(slot.get("description") or "")
            name = slot.get("name")
            family = slot.get("family")
            family_source = slot.get("family_source")
            card_fact = slot.get("card_fact")
            if card_fact is None:
                card_fact = card_fact_from_slot(slot)
            if not family_source and card_fact is not None:
                family_source = getattr(card_fact, "family_source", "unknown")
            out.append(
                SlotCandidate(
                    index=index,
                    name=name,
                    confidence=float(slot.get("confidence") or 0.0),
                    evidence=str(slot.get("raw_text") or ""),
                    rarity=rarity if isinstance(rarity, str) else None,
                    rarity_letter=rarity_letter if isinstance(rarity_letter, str) else None,
                    description=description,
                    family=family or (card_fact.family if card_fact else None),
                    prereq_marker=bool(slot.get("prereq_marker", False)),
                    is_new=bool(slot.get("is_new", False)),
                    skill_level=slot.get("skill_level"),
                    card_fact=card_fact,
                    family_source=str(family_source or "unknown"),
                    zero_cost=bool(slot.get("zero_cost", False)),
                )
            )
        return tuple(out)
    def _policy_settings(self) -> PolicySettings:
        """Cached PolicySettings；初始化时已快照 policy_doc + 习惯偏好。

        首次调用惰性构建一次（assemble_policy_settings 为纯函数，无 I/O），
        之后恒返回同一实例——绝不在每 panel tick 重读 choice_policy.json。
        本方法保留为可 patch 的测试缝（patch.object(med, "_policy_settings", …)）。
        """
        if self._cached_policy_settings is None:
            self._cached_policy_settings = assemble_policy_settings(
                settings=self.settings,
                skill_labels=self._skill_labels,
                fetter_labels=self._fetter_labels,
                policy_doc=self._choice_policy_doc,
                habit_name_scores=self._habit_skill_scores,
                skill_routes_doc=self._skill_routes_doc,
            )
        return self._cached_policy_settings

    def _bond_template_preferences(self) -> list[str]:
        """模板模式将看板中文羁绊还原为已有 cards/<短码> 锚点。"""
        by_label = {label: code for code, label in self._fetter_labels.items()}
        aliases = {"异火": "yihuo", "翼火": "yihuo"}
        preferred: list[str] = []
        for item in [*(getattr(self.settings, "bonds", None) or ()), *(self.settings.cards or ())]:
            text = str(item or "").strip()
            if not text:
                continue
            stem = Path(text).stem
            resolved = aliases.get(text) or (stem if stem in self._fetter_labels else by_label.get(text, stem))
            if resolved not in preferred:
                preferred.append(resolved)
        return preferred

    # ---- L1 运行时技能卡归属（pending/owned）----

    @staticmethod
    def _is_skill_card_click(name: str | None) -> bool:
        """技能面板上的一次点击是否属于选卡（排除刷新/放弃/关闭/隐藏）。"""
        text = (name or "").lower()
        for token in ("refresh", "giveup", "close", "hide"):
            if token in text:
                return False
        return True

    def _stage_skill_card(self, name: str | None) -> None:
        """点击技能卡后暂存卡名；仅 WAIT_MUTATION 确认后才计入已学。"""
        text = str(name or "").strip()
        if not text:
            return
        stem = Path(text).stem
        canonical = str(self._skill_labels.get(stem, stem)).strip()
        if canonical:
            self._skill_cards_pending.append(canonical)

    def _commit_pending_skill_cards(self) -> None:
        """WAIT_MUTATION 观察到内容变化/面板消失 → 确认学得，并入已学序列。

        重复卡必须保留次数（目录含 x2 前置）。赠卡（grant_on_learn）只通过
        verified 的 skill_catalog 助手记录；未知存档等级不产生任何赠卡。
        """
        if not self._skill_cards_pending:
            return
        archive_levels = self._policy_settings().skill_archive_levels
        for name in self._skill_cards_pending:
            self._skill_cards_owned.append(name)
            granted = grant_on_learn_card(name, archive_levels)
            if granted:
                self._skill_cards_owned.append(str(granted))
        self._skill_cards_pending.clear()

    def _clear_pending_skill_cards(self) -> None:
        """确认窗超时/未确认 → 丢弃暂存，绝不记为已学。"""
        self._skill_cards_pending.clear()
        self._bond_cards_pending.clear()

    def _confirmed_skill_cards(self) -> tuple[str, ...]:
        """已确认学得的技能卡名（含重复次数；传给 PanelCandidates）。"""
        return tuple(self._skill_cards_owned)

    def _stage_bond_card(self, name: str | None) -> None:
        """点击羁绊卡后暂存卡名；仅 WAIT_MUTATION 确认后才计入已持有。"""
        text = str(name or "").strip()
        if not text:
            return
        if text.startswith("ocr_bond:"):
            text = text[len("ocr_bond:"):]
        stem = Path(text).stem
        canonical = str(self._fetter_labels.get(stem, stem)).strip()
        if canonical:
            self._bond_cards_pending.append(canonical)

    def _commit_pending_bond_cards(self) -> None:
        """WAIT_MUTATION 观察到内容变化/面板消失 → 确认拿卡，并入已持有序列。"""
        if not self._bond_cards_pending:
            return
        for name in self._bond_cards_pending:
            self._bond_cards_owned.append(name)
        self._bond_cards_pending.clear()

    def _confirmed_bond_cards(self) -> tuple[str, ...]:
        """已确认持有的羁绊卡名（含重复次数；传给 PanelCandidates）。"""
        return tuple(self._bond_cards_owned)

    def _bond_base_progress_pending(self) -> bool:
        """基础卡未达到 80% 时，F 面板独占主动选卡循环。"""
        policy = self._policy_settings()
        bases = policy.bond_base_presets
        if not bases or not policy.bond_advanced_presets:
            return False
        unlock = float(policy.bond_advanced_unlock_s or 0.0)
        elapsed = self._round_elapsed_s()
        if unlock > 0 and elapsed is not None and elapsed >= unlock:
            return False
        required = math.ceil(len(bases) * policy.bond_base_completion_ratio)
        owned = self._confirmed_bond_cards()
        completed = sum(
            any(same_bond_identity(name, base) for name in owned)
            for base in bases
        )
        return completed < required

    def _round_elapsed_s(self) -> float | None:
        started = getattr(self, "_round_started_at", None)
        return None if started is None else max(0.0, time.time() - started)

    def _reset_choice_session(self) -> None:
        self._choice_session = SessionState(
            max_attempts=DEFAULT_MAX_ATTEMPTS,
            max_refreshes=DEFAULT_MAX_REFRESHES,
            max_waits=DEFAULT_MAX_WAITS,
        )
        self._skill_refresh_attempts = 0
        self._choice_fp_before_refresh = None
        self._choice_policy_idle = False
        self._choice_policy_last_reason = ""
        self._ocr_confirm_key = None

    def _record_choice_session(self, decision: PolicyDecision) -> None:
        """Update SessionState after a policy decision.

        WAIT increments waits only (not attempts). SELECT/REFRESH/GIVEUP/CLOSE
        attempts/refreshes are committed after a successful click in the panel
        FSM so a rejected click does not burn budget; before choose_action we
        sync refreshes from ``_skill_refresh_attempts``.
        """
        cur = self._choice_session
        if decision.action == PolicyAction.WAIT:
            self._choice_session = replace(
                cur,
                refreshes=max(cur.refreshes, self._skill_refresh_attempts),
                waits=cur.waits + 1,
            )
            return
        # Keep refreshes mirror in sync for the next tick's choose_action input.
        self._choice_session = replace(
            cur,
            refreshes=max(cur.refreshes, self._skill_refresh_attempts),
        )

    def _bump_choice_attempts(self) -> None:
        """成功执行的 SELECT/REFRESH/GIVEUP/CLOSE 才计 SessionState.attempts。

        WAIT 与被拒点击（act_click False / 找不到按钮）不产生 UI 动作，不得烧预算。
        """
        cur = self._choice_session
        self._choice_session = replace(cur, attempts=cur.attempts + 1)

    def _sync_choice_session_refreshes(self) -> None:
        cur = self._choice_session
        refreshes = max(cur.refreshes, int(self._skill_refresh_attempts))
        if refreshes == cur.refreshes:
            return
        self._choice_session = replace(cur, refreshes=refreshes)

    def _panel_has_giveup(self, frame: Frame, kind: str) -> bool:
        names = {
            "skill": ["skill_giveup_btn", "giveUp"],
            "bond": ["skill_giveup_btn", "giveUp", "bond_hide_btn"],
            "treasure": ["skill_giveup_btn", "giveUp", "treasure_hide_btn"],
        }.get(kind, ["skill_giveup_btn", "giveUp"])
        return self.find(
            frame,
            names,
            threshold=min(0.70, self.settings.match_threshold),
            scales=self._hot_scales(),
            roi=self._PANEL_BUTTONS_ROI,
            early_stop=True,
        ) is not None

    def _panel_can_refresh(self, frame: Frame, kind: str) -> bool:
        return self._find_panel_refresh(frame, kind) is not None

    def _find_panel_refresh(self, frame: Frame, kind: str) -> MatchResult | None:
        names = {
            "skill": ["skill_refresh_btn", "refresh", "bwRefresh", "cardRefresh", "heroRefresh"],
            "bond": ["bond_refresh_btn", "refresh", "cardRefresh", "heroRefresh", "bwRefresh"],
            "treasure": ["treasure_refresh_btn", "refresh", "cardRefresh", "bwRefresh"],
        }.get(kind, ["skill_refresh_btn", "refresh", "bwRefresh", "cardRefresh"])
        def preferred(scales: tuple[float, ...]) -> MatchResult | None:
            # Do not let a high-scoring generic `refresh`/`bwRefresh` template
            # replace the panel-specific refresh button at a different coordinate.
            for name in names:
                hit = self.find(
                    frame, [name], threshold=min(0.70, self.settings.match_threshold),
                    scales=scales, roi=self._PANEL_BUTTONS_ROI,
                )
                if hit is not None:
                    return hit
            return None

        hit = preferred(self._hot_scales())
        if hit is None and self._scaled_up_frame(frame):
            hit = preferred(self._wide_scales())
        return hit

    def _find_skill_hide(self, frame: Frame) -> MatchResult | None:
        return self.find(
            frame,
            ["skill_hide"],
            threshold=min(0.70, self.settings.match_threshold),
            scales=self._hot_scales(),
            roi=self._PANEL_BUTTONS_ROI,
            early_stop=True,
        )

    def _skill_giveup_blocked(self, slots: tuple[SlotCandidate, ...]) -> bool:
        if not slots or all(s.name is None for s in slots):
            return True
        prev = self._choice_session.last_slot_fingerprint
        return bool(prev) and slot_fingerprint(slots) == prev

    def _find_panel_giveup(self, frame: Frame, kind: str) -> MatchResult | None:
        names = {
            "skill": ["skill_giveup_btn", "giveUp"],
            "bond": ["skill_giveup_btn", "giveUp"],
            "treasure": ["skill_giveup_btn", "giveUp"],
        }.get(kind, ["skill_giveup_btn", "giveUp"])
        hit = self.find(
            frame,
            names,
            threshold=min(0.70, self.settings.match_threshold),
            scales=self._hot_scales(),
            roi=self._PANEL_BUTTONS_ROI,
        )
        if hit is None and self._scaled_up_frame(frame):
            hit = self.find(
                frame,
                names,
                threshold=min(0.70, self.settings.match_threshold),
                scales=self._wide_scales(),
                roi=self._PANEL_BUTTONS_ROI,
            )
        return hit

    def _policy_decision_to_hit(
        self,
        frame: Frame,
        kind: str,
        decision: PolicyDecision,
        slots: tuple[SlotCandidate, ...],
    ) -> tuple[str, MatchResult] | None:
        """Map PolicyDecision → (label, MatchResult). WAIT/NONE → idle (None)."""
        self._choice_policy_last_reason = decision.reason or ""
        self._record_choice_session(decision)
        if decision.action == PolicyAction.WAIT:
            self._choice_policy_idle = True
            print(f"[L1] 选卡策略 WAIT：{decision.reason}")
            return None
        if decision.action == PolicyAction.NONE:
            return None
        if decision.action == PolicyAction.SELECT_SLOT:
            if decision.index is None or not slots:
                return None
            name = None
            selected_slot = None
            for slot in slots:
                slot_idx = slot.index if hasattr(slot, "index") else slot.get("index")
                if slot_idx == decision.index:
                    selected_slot = slot
                    name = slot.name if hasattr(slot, "name") else slot.get("name")
                    break
            if kind == "skill" and name:
                # Prefer skill short-code for downstream cycle ownership checks.
                # OCR 变体先过词典规范化（如 奥数箭→奥术箭矢）再反查短码；
                # 词典未收录时保留原文，不硬猜。
                reverse = {v: k for k, v in self._skill_labels.items()}
                reverse.update({"奥数箭": "asj", "奥数激光": "asjg", "奥数射线": "assx"})
                canonical = name
                try:
                    from shuabao.vision.choice_ocr import lookup_lexicon
                    lookup = lookup_lexicon(name, kind="skill")
                    canonical = lookup.canonical or name
                except Exception:
                    pass
                hit_name = reverse.get(name) or reverse.get(canonical) or canonical
            elif name:
                hit_name = f"ocr_{kind}:{name}"
            else:
                hit_name = f"ocr_{kind}:slot{decision.index}"
            if decision.reason:
                print(f"[L1] 选卡策略：{decision.reason}")
            hit = self._choice_slot_hit(frame, kind, int(decision.index), hit_name, slot_count=len(slots))
            label = "技能" if kind == "skill" else kind
            return (label, hit)
        if decision.action == PolicyAction.REFRESH:
            self._choice_fp_before_refresh = slot_fingerprint(slots)
            refresh = self._find_panel_refresh(frame, kind)
            if refresh is None:
                if kind == "skill":
                    give_up = self._find_panel_giveup(frame, kind)
                    if give_up is not None:
                        print(f"[L1] 选卡策略 REFRESH 无刷新按钮，改为放弃：{decision.reason}")
                        return ("技能放弃", give_up)
                close_hit = self._close_current_panel(frame, kind)
                if close_hit is not None:
                    print(f"[L1] 选卡策略 REFRESH 无刷新按钮，安全降级为关闭：{decision.reason}")
                    return (kind if kind != "skill" else "技能", close_hit)
                self._choice_policy_idle = True
                print(f"[L1] 选卡策略 REFRESH 但无刷新和关闭按钮：{decision.reason}")
                return None
            print(f"[L1] 选卡策略 REFRESH：{decision.reason}")
            label = "技能刷新" if kind == "skill" else f"{kind}刷新"
            return (label, refresh)
        if decision.action == PolicyAction.GIVEUP:
            give_up = self._find_panel_giveup(frame, kind)
            if give_up is None:
                close_hit = self._close_current_panel(frame, kind)
                if close_hit is not None:
                    print(f"[L1] 选卡策略 GIVEUP→CLOSE：{decision.reason}")
                    return (kind if kind != "skill" else "技能放弃", close_hit)
                self._choice_policy_idle = True
                return None
            print(f"[L1] 选卡策略 GIVEUP：{decision.reason}")
            label = "技能放弃" if kind == "skill" else f"{kind}放弃"
            return (label, give_up)
        if decision.action == PolicyAction.CLOSE:
            close_hit = self._close_current_panel(frame, kind)
            if close_hit is None:
                self._choice_policy_idle = True
                print(f"[L1] 选卡策略 CLOSE 但无关闭按钮：{decision.reason}")
                return None
            print(f"[L1] 选卡策略 CLOSE：{decision.reason}")
            return (kind if kind != "skill" else "技能", close_hit)
        return None

    @staticmethod
    def _label_choice_hit(kind: str, hit: MatchResult) -> tuple[str, MatchResult]:
        name = (hit.name or "").lower()
        if "refresh" in name:
            return ("技能刷新" if kind == "skill" else f"{kind}刷新", hit)
        if "giveup" in name or name == "giveup":
            return ("技能放弃" if kind == "skill" else f"{kind}放弃", hit)
        if "hide" in name or name in {"hide", "card_hide"}:
            return (kind if kind != "skill" else "技能", hit)
        return ("技能" if kind == "skill" else kind, hit)

    def _choice_slot_hit(self, frame: Frame, kind: str, index: int, name: str, slot_count: int = 3) -> MatchResult:
        if slot_count == 4:
            centers = self._CHOICE_SLOT_CENTERS_4.get(kind) or self._CHOICE_SLOT_CENTERS.get(kind, ())
        else:
            centers = self._CHOICE_SLOT_CENTERS.get(kind, ())
        if index < 0 or index >= len(centers):
            x_ratio, y_ratio = (0.5, 0.5)
        else:
            x_ratio, y_ratio = centers[index]
        x, y = int(frame.width * x_ratio), int(frame.height * y_ratio)
        return MatchResult(name, 1.0, x, y, 0, 0, frame.left + x, frame.top + y)

    @staticmethod
    def _progress_from_text(text: str) -> tuple[int, int] | None:
        match = re.search(r"(\d+)\s*/\s*(\d+)", text or "")
        if not match:
            return None
        have, need = int(match.group(1)), int(match.group(2))
        return (have, need) if 0 <= have <= need and need > 0 else None

    @staticmethod
    def _bond_bar_occupancy(frame: Frame) -> int | None:
        """Count occupied bond-bar cells using LayoutTransform; used only as an overflow guard."""
        if frame.bgr is None or not LayoutTransform.is_supported(frame.width, frame.height):
            return None
        transform = LayoutTransform.from_frame(frame.width, frame.height)
        occupied = 0
        min_pixels = int(250 * transform.scale * transform.scale)
        for cx in (603, 655, 707, 759, 811, 863, 915, 967, 1019, 1071):
            rx1, ry1, rx2, ry2 = transform.logical_roi(cx - 20, 635, cx + 20, 680)
            roi_bgr = frame.bgr[ry1:ry2, rx1:rx2]
            if roi_bgr.size == 0:
                continue
            hsv_roi = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
            colored = (hsv_roi[:, :, 1] > 70) & (hsv_roi[:, :, 2] > 60)
            if int(colored.sum()) >= min_pixels:
                occupied += 1
        return occupied
    def _canonical_bond_name(self, card_name: str) -> str:
        """Map a card name or bond string to canonical 5 bond categories if applicable."""
        for b in ("祝福", "成长", "经济", "贪婪", "挑战"):
            if b in card_name:
                return b
        return card_name

    def _extract_live_set_progress(self, frame: Frame | None) -> dict[str, int] | None:
        """Extract current active bond tier progress counts from confirmed card state.

        Counts are computed from confirmed cards or _owned_bonds; _bond_bar_occupancy
        is only used to check consistency or empty state.
        """
        counts: dict[str, int] = {}
        confirmed = self._confirmed_bond_cards()
        if confirmed:
            for card in confirmed:
                c_str = str(card or "").strip()
                if not c_str:
                    continue
                canon = self._canonical_bond_name(c_str)
                counts[canon] = counts.get(canon, 0) + 1
        elif hasattr(self, "_owned_bonds") and isinstance(self._owned_bonds, dict):
            counts = {k: len(v) if isinstance(v, (list, tuple, set)) else int(v) for k, v in self._owned_bonds.items()}

        if frame is not None:
            occ = self._bond_bar_occupancy(frame)
            if occ is not None and occ == 0:
                return {}

        return counts if counts else None

    def _extract_live_free_slots(self, frame: Frame | None) -> int | None:
        """Extract remaining open card slots from HUD or confirmed game state."""
        if frame is not None:
            occ = self._bond_bar_occupancy(frame)
            if occ is not None:
                return max(0, 10 - int(occ))
        return None
    def _ocr_reward_choice(self, frame: Frame, kind: str) -> MatchResult | None:
        """OCR → SlotCandidate → choice_policy.choose_action → click target.

        Old left-to-right / advanced-bond / min-index heuristics are intentionally
        gone; hard whitelist + rarity-first + negative-treasure live in choose_action.
        """
        slots_raw = self._ocr_panel_slots(frame, kind)
        if not slots_raw:
            return None
        self._sync_choice_session_refreshes()
        slots = self._slots_to_candidates(frame, kind, slots_raw)
        # Live set_progress & free_slots extraction from frame and confirmed state
        bond_progress = self._extract_live_set_progress(frame)
        bond_occupancy = self._bond_bar_occupancy(frame)
        live_free_slots = max(0, 10 - int(bond_occupancy)) if bond_occupancy is not None else None

        can_refresh = self._panel_can_refresh(frame, kind)
        policy_settings = self._policy_settings()
        if kind == "bond" and self._main_line_stalled():
            slots = self._stall_combat_bond_slots(slots)
            policy_settings = self._stall_combat_bond_policy(policy_settings)
        if self._passenger_mode() and kind == "treasure":
            has_valid_names = any(
                s.name is not None and bool(str(s.name).strip()) and s.confidence >= policy_settings.min_confidence
                for s in slots
            )
            pick, reason = hitch_treasure_pick(slots, policy_settings)
            max_hitch_treasure_refreshes = 3
            if pick is not None:
                self._treasure_consecutive_no_pick = 0
                decision = PolicyDecision.select(pick.index, reason)
            elif (
                not has_valid_names
                and can_refresh
                and getattr(self, "_hitch_treasure_total_refreshes", 0) < 3
                and self._choice_session.refreshes < self._choice_session.max_refreshes
                and getattr(self, "_treasure_consecutive_no_pick", 0) < 2
            ):
                # OCR 没读到有效候选名：保持零输入或安全关闭，不要把识别失败当成“无共享道具后刷新”
                self._treasure_consecutive_no_pick += 1
                decision = PolicyDecision.close("蹭车宝物 OCR 未读出有效候选，安全关闭（不刷新）")
            elif (
                can_refresh
                and getattr(self, "_hitch_treasure_total_refreshes", 0) < max_hitch_treasure_refreshes
                and self._choice_session.refreshes < self._choice_session.max_refreshes
                and getattr(self, "_treasure_consecutive_no_pick", 0) < 2
            ):
                decision = PolicyDecision(
                    PolicyAction.REFRESH,
                    None,
                    "蹭车宝物无可共享道具（神符/吞噬丹/英雄卡/EX），刷新后重试",
                )
            else:
                # 末段没有刷新次数时：只允许选择已确认非负面的合法宝物；
                # 若无非负面有效候选（全负面、全未识别、低置信），严格安全关闭，
                # 绝不盲选负面卡或 slot 0。
                candidates = [
                    s for s in slots
                    if s.name and str(s.name).strip()
                    and s.confidence >= policy_settings.min_confidence
                ]
                positive = [s for s in candidates if not is_negative_treasure(s, policy_settings)]
                if positive:
                    fallback = positive[0]
                    self._treasure_consecutive_no_pick = 0
                    decision = PolicyDecision.select(
                        fallback.index,
                        f"蹭车宝物末段兜底选择非负面卡【{fallback.name}】（刷新预算耗尽）",
                    )
                else:
                    self._treasure_consecutive_no_pick += 1
                    decision = PolicyDecision.close("蹭车宝物末段无非负面有效候选，安全关闭（禁止选择负面或未识别卡）")
        else:
            decision = choose_action(
                PanelCandidates(
                    panel_kind=kind,
                    slots=slots,
                    set_progress=bond_progress,
                    free_slots=live_free_slots,
                    refresh_count=self._choice_session.refreshes,
                    has_giveup=self._panel_has_giveup(frame, kind),
                    can_refresh=can_refresh,
                    settings=policy_settings,
                    owned_skill_cards=self._confirmed_skill_cards(),
                    owned_bond_cards=self._confirmed_bond_cards(),
                    round_elapsed_s=self._round_elapsed_s(),
                ),
                self._choice_session,
            )
        _obs_from, _obs_why = None, ""
        if kind == "bond" and decision.action == PolicyAction.REFRESH:
            affordable, wood, price = self._bond_refresh_affordable(frame)
            if not affordable:
                _obs_from = str(PolicyAction.REFRESH)
                _obs_why = f"木材不足：需 {price}，当前 {wood if wood is not None else '未读出'}"
                decision = PolicyDecision.close(
                    f"羁绊刷新需 {price} 木，当前木头 {wood if wood is not None else '未读出'}，隐藏面板"
                )
        _obs = self._observe_log()
        if _obs is not None:
            try:
                _obs.note_choice(
                    round_id=self._observe_round_id(),
                    panel_kind=kind, slots=slots, decision=decision,
                    set_progress=bond_progress, free_slots=live_free_slots,
                    refresh_count=self._choice_session.refreshes,
                    can_refresh=can_refresh,
                    has_giveup=self._panel_has_giveup(frame, kind),
                    round_elapsed_s=self._round_elapsed_s(),
                    wood=getattr(self, "_wood_balance", None),
                    refresh_price=self._bond_refresh_price() if kind == "bond" else None,
                    downgraded_from=_obs_from, downgrade_reason=_obs_why,
                )
            except Exception as exc:
                print(f"[med][observe] 选卡记录失败，跳过：{exc}")
        owned = (
            getattr(self, "_panel_opened_by_us", None) == kind
            or (self._l1_cycle_owned_panel and self._panel_kind == kind)
        )
        reason = str(decision.reason or "")
        skip_confirm = (
            "差一张合成" in reason
            or "已持有合成" in reason
            or (
                decision.action == PolicyAction.SELECT_SLOT
                and self._is_unambiguous_high_confidence_pick(decision, slots, reason)
            )
        )
        if (
            not skip_confirm
            and kind in ("bond", "skill")
            and decision.action == PolicyAction.SELECT_SLOT
        ):
            # The policy already required a whitelist/focus match; a title read
            # at >= 0.95 is not worth another tick (08-29 e2a2714 added the
            # second frame: bond 1.4s -> 2.9-5.2s, skill 1.4s -> 5.8-7.3s).
            # Same-family duplicates (祝福(0/3) x3) are equivalent picks, so the
            # executor's "no duplicate names" rule is not needed for them.
            chosen = next((s for s in slots if s.index == decision.index), None)
            if (
                chosen is not None
                and str(chosen.name or "").strip()
                and float(chosen.confidence or 0.0) >= self._SINGLE_FRAME_PICK_CONFIDENCE
            ):
                skip_confirm = True
        if owned and not skip_confirm and decision.action in {PolicyAction.SELECT_SLOT, PolicyAction.REFRESH}:
            key = (
                kind,
                decision.action.value,
                decision.index,
                tuple((s.index, s.name) for s in slots),
            )
            if key != getattr(self, "_ocr_confirm_key", None):
                self._ocr_confirm_key = key
                self._choice_policy_idle = True
                self._choice_policy_last_reason = f"{kind} 决策待第二帧确认：{decision.reason}"
                print(f"[L1] {self._choice_policy_last_reason}")
                return None
            self._ocr_confirm_key = None
        if self.settings.dry_run:
            append_learning_observation(
                {
                    "panel_kind": kind,
                    "event": "choice_decision",
                    "slots": [
                        {
                            "index": s.index,
                            "name": s.name,
                            "rarity": s.rarity,
                            "confidence": round(float(s.confidence or 0.0), 3),
                        }
                        for s in slots
                    ],
                    "decision": {
                        "action": getattr(decision.action, "name", str(decision.action)),
                        "index": decision.index,
                        "reason": getattr(decision, "reason", "") or "",
                    },
                    "phase": self.phase.name,
                    "context": self._context_cache_value,
                }
            )
        mapped = self._policy_decision_to_hit(frame, kind, decision, slots)
        if mapped is None:
            return None
        return mapped[1]

    _SINGLE_FRAME_PICK_CONFIDENCE = 0.95

    def _live_ocr_miss_refresh(self, frame: Frame, kind: str) -> MatchResult | None:
        """OCR 没读到名字时禁止刷新。预选卡可能已经在画面上。"""
        return None

    @staticmethod
    def _is_unambiguous_high_confidence_pick(
        decision: "PolicyDecision", slots: tuple, reason: str
    ) -> bool:
        """B2 拿卡提速：卡名完整命中白名单预设、OCR>=0.95、四槽无重名歧义时免二次确认。

        其余情形（刷新、模糊/低置信/重名槽位、非预设兜底如品质降级/套装进度）
        仍保留 _ocr_reward_choice 现有的两帧确认。
        """
        if "预设命中" not in reason and "严格命中" not in reason:
            return False
        chosen = next((s for s in slots if s.index == decision.index), None)
        if chosen is None or not chosen.name or float(chosen.confidence or 0.0) < 0.95:
            return False
        named = [str(s.name).strip() for s in slots if s.name and str(s.name).strip()]
        return len(named) == len(set(named))


    def _rarity_choice(self, frame: Frame, panel_kind: str) -> MatchResult | None:
        """Pick the highest readable N/R/SR/SSR/UR/EX badge; never sample color."""
        if panel_kind not in ("treasure", "skill", "bond", "card"):
            return None
        centers = self._CHOICE_SLOT_CENTERS.get(panel_kind, self._CHOICE_SLOT_CENTERS["skill"])
        ranks = dict(self.RARITY_BANDS)
        best: tuple[int, str, str, int, int] | None = None
        for index, (x_ratio, y_ratio) in enumerate(centers):
            letter, band = self._read_slot_rarity_badge(frame, panel_kind, index)
            if band is None:
                continue
            score = ranks.get(band, -1)
            if best is None or score > best[0]:
                best = (score, band, letter or "?", int(frame.width * x_ratio), int(frame.height * y_ratio))
        if best is None:
            return None
        score, band, letter, cx, cy = best
        print(f"[L1] 按品质徽标选卡：{letter}/{band} @ ({cx},{cy})")
        return MatchResult(
            name=f"rarity_{band}",
            score=max(0.0, score / max(1, len(self.RARITY_BANDS) - 1)),
            x=cx,
            y=cy,
            w=0,
            h=0,
            screen_x=frame.left + cx,
            screen_y=frame.top + cy,
        )

    def _fallback_choice(self, frame: Frame, panel_kind: str) -> MatchResult | None:
        """Disabled: never pick 'first card' for bond/card/treasure (A3)."""
        return None

    def _find_reward_choice(self, frame: Frame, anchor: MatchResult | None = None) -> tuple[str, MatchResult] | None:
        """Decision layer for an open reward-choice panel.

        Policy (one action max):
        1. classify panel kind; UNKNOWN → None (caller handles)
        2. OCR live/shadow with candidates → choice_policy.choose_action
        3. template preferred (skills/cards) when OCR unavailable
        4. bond/card: never rarity / first-card bypass
        5. treasure: quality only as last resort; never first-card
        6. skill: refresh up to max → give up
        """
        if anchor is None:
            anchor = self._selection_anchor(frame)
        if not anchor:
            return None

        if self._evolve_hero_choice_pending():
            evo_hit = self._find_evolution_choice(frame, anchor)
            if evo_hit is not None:
                print(f"[L1] 进化英雄选择：{evo_hit.name} @ {evo_hit.center}")
                return ("card", evo_hit)
            rarity_hit = self._rarity_choice(frame, "card") or self._rarity_choice(frame, "skill") or self._rarity_choice(frame, "treasure")
            if rarity_hit is not None:
                print(f"[L1] 进化英雄三选一按品质色：{rarity_hit.name} @ {rarity_hit.center}")
                return ("card", rarity_hit)
        kind = self._panel_kind_of(frame, anchor)
        if kind == "unknown":
            self._record_selection_unknown(frame, anchor, "panel classification failed")
            return None

        if self._archiver is not None:
            self._archiver.sample_panel(
                frame,
                {
                    "phase": str(getattr(self, "phase", "")),
                    "panel_kind": kind,
                    "anchor_score": round(anchor.score, 3),
                    "source": "mediator_panel_sample",
                },
            )

        ocr_mode = getattr(self.settings, "ocr_mode", "off")
        if ocr_mode in {"shadow", "live"} and kind in {"skill", "bond", "treasure"}:
            if ocr_mode == "live":
                # Live：走 _ocr_reward_choice（choose_action）；测试可 patch 该缝。
                ocr_hit = self._ocr_reward_choice(frame, kind)
                if self._choice_policy_idle:
                    return None
                if ocr_hit is not None:
                    return self._label_choice_hit(kind, ocr_hit)
                owned = (
                    getattr(self, "_panel_opened_by_us", None) == kind
                    or (self._l1_cycle_owned_panel and self._panel_kind == kind)
                )
                if owned:
                    # 自己打开的面板：没读到名字就等，绝不刷新烧木头。
                    self._choice_policy_idle = True
                    self._choice_policy_last_reason = f"{kind} OCR 本帧无候选，等下一帧"
                    return None
                if kind == "card":
                    return None
                # 自然弹出的面板：落到下方关闭/模板收口，不走 OCR-miss 刷新。
            else:
                # Shadow：只观察 OCR + 策略，不记账、不授权点击。
                slots_raw = self._ocr_panel_slots(frame, kind)
                if slots_raw:
                    self._sync_choice_session_refreshes()
                    slots = self._slots_to_candidates(frame, kind, slots_raw)
                    decision = choose_action(
                        PanelCandidates(
                            panel_kind=kind,
                            slots=slots,
                            set_progress=None,
                            refresh_count=self._choice_session.refreshes,
                            has_giveup=self._panel_has_giveup(frame, kind),
                            can_refresh=self._panel_can_refresh(frame, kind),
                            settings=self._policy_settings(),
                            owned_skill_cards=self._confirmed_skill_cards(),
                            owned_bond_cards=self._confirmed_bond_cards(),
                        ),
                        self._choice_session,
                    )
                    self._trace_ocr_suggestion = {
                        "kind": kind,
                        "slots": slots_raw,
                        "policy_action": decision.action.value,
                        "policy_reason": decision.reason,
                        "policy_index": decision.index,
                    }

        if kind in ("bond", "treasure", "card"):
            if kind == "bond" and ocr_mode == "live" and (
                getattr(self, "_panel_opened_by_us", None) == "bond"
                or (self._l1_cycle_owned_panel and self._panel_kind == "bond")
            ):
                return None
            if kind == "card" and ocr_mode == "live":
                return None
            preferred = (
                self._bond_template_preferences()
                if kind == "bond"
                else [v.strip() for v in self.settings.cards if v and v.strip()]
            )
            if preferred:
                names = [v if "/" in v else f"cards/{v}" for v in preferred]
                hits = self._match_all_preferred(
                    frame, names, max_results=12,
                )
                hits = sorted(hits, key=lambda h: h.score, reverse=True)
                candidates: list[MatchResult] = []
                for h in hits:
                    if not any(math.hypot(h.x - c.x, h.y - c.y) < 40.0 for c in candidates):
                        candidates.append(h)
                if candidates:
                    by_stem = {Path(c.name).stem: c for c in candidates}
                    for pref in preferred:
                        hit = by_stem.get(Path(pref).stem)
                        if hit is not None:
                            return (kind, hit)
            # A3：bond/card 禁止品质色 / 第一张旁路；未命中 → 关闭或零输入。
            if kind in ("bond", "card"):
                close_hit = self._close_current_panel(frame, kind)
                return (kind, close_hit) if close_hit is not None else None
            # treasure：仅在非 OCR live 模式下允许品质色兜底；OCR live 下严格由 policy fail-closed。
            if ocr_mode != "live" and not self._passenger_mode():
                rarity_hit = self._rarity_choice(frame, kind)
                if rarity_hit is not None:
                    return (kind, rarity_hit)
            close_hit = self._close_current_panel(frame, kind)
            return (kind, close_hit) if close_hit is not None else None

        # skill panel: preferred-only (OCR live already returned above)
        preferred = (
            []
            if ocr_mode == "live"
            else [v.strip() for v in self.settings.skills if v and v.strip()]
        )
        if preferred:
            names = [v if "/" in v else f"skills/{v}" for v in preferred]
            hits = self._match_all_preferred(
                frame, names, max_results=8,
            )
            hits = sorted(hits, key=lambda h: h.score, reverse=True)
            candidates: list[MatchResult] = []
            for h in hits:
                if not any(math.hypot(h.x - c.x, h.y - c.y) < 40.0 for c in candidates):
                    candidates.append(h)
            if candidates:
                by_stem = {Path(c.name).stem: c for c in candidates}
                for pref in preferred:
                    hit = by_stem.get(Path(pref).stem)
                    if hit is not None:
                        return ("技能", hit)
        # 模板模式同样遵守“焦点未命中先刷新”；否则会在已验证的刷新钮旁
        # 直接隐藏技能面板，和 live OCR 策略相反。
        policy = self._policy_settings()
        if (
            policy.skill_refresh_on_focus_miss
            and policy.skill_focus_families
            and self._choice_session.refreshes < self._choice_session.max_refreshes
        ):
            refresh = self._find_panel_refresh(frame, "skill")
            if refresh is not None:
                return ("技能刷新", refresh)
        hide = self._find_skill_hide(frame)
        if hide is not None:
            return ("技能", hide)
        return None

    def _match_all_preferred(self, frame: Frame, names: list[str], max_results: int) -> list:
        """偏好模板多命中收集：先主尺度；配置顺序内的偏好未集齐时宽尺度回退。

        主尺度（基准窗口）通常一次命中全部偏好卡，回退仅在 DPI 缩放窗口
        （如 2348x1080≈1.47x）等主尺度漏检时发生，保证配置序第一的偏好不被吞。

        N2.4：evidence 级 memo（只读检测，无动作授权）——exact-static 同帧
        复用不再每 tick 重扫 match_all（fail_panel exact-static 12 次调用的根因）。
        """
        key = ("match_all_preferred", tuple(names), max_results, round(self._ui_scale, 3))

        def collect(scales: tuple[float, ...]) -> list:
            return match_all(
                frame,
                self.images,
                names,
                threshold=min(0.70, self.settings.match_threshold),
                roi=self._selection_roi(),
                max_results=max_results,
                scales=scales,
            )

        def compute() -> list:
            hits = collect(self._hot_scales())
            if not hits or not self._scaled_up_frame(frame):
                if not hits and self._scaled_up_frame(frame):
                    return collect(self._wide_scales())
                return hits
            hit_stems = {Path(h.name).stem for h in hits}
            preferred_stems = [Path(n).stem for n in names]
            if any(ps not in hit_stems for ps in preferred_stems):
                wide = collect(self._wide_scales())
                if wide:
                    return wide
            return hits

        return self._memo(key, frame, compute)

    CHOICE_BUTTON_RATIOS = {
        "skill": (0.9025, 0.867),
        "bond": (0.864, 0.867),
        "treasure": (0.861, 0.811),
    }

    def _hud_button_hit(self, frame: Frame, name: str, ratios: tuple[float, float]) -> MatchResult:
        x, y = int(frame.width * ratios[0]), int(frame.height * ratios[1])
        return MatchResult(name, 1.0, x, y, 0, 0, frame.left + x, frame.top + y)

    # 神器槽位几何（1600x900 基准，相对比例）：Q(1205,744) W(1205,806) E(1205,868)
    ARTIFACT_SLOT_X = 0.753
    ARTIFACT_SLOT_Y0 = 0.827
    ARTIFACT_SLOT_DY = 0.069

    def _slot_has_artifact(self, frame: Frame, idx: int) -> bool:
        """True when the idx-th artifact slot shows an icon (saturated pixels).

        Empty slots are near-black (video-measured: Q=1245, W=1483, E=86
        saturated pixels in 70x70 ROI); threshold 300 separates cleanly.
        """
        try:
            import cv2 as _cv2
        except Exception:
            return True
        cx = int(frame.width * self.ARTIFACT_SLOT_X)
        cy = int(frame.height * (self.ARTIFACT_SLOT_Y0 + idx * self.ARTIFACT_SLOT_DY))
        w = max(20, int(frame.width * 0.044))
        h = max(20, int(frame.height * 0.078))
        roi = frame.bgr[max(0, cy - h // 2) : cy + h // 2, max(0, cx - w // 2) : cx + w // 2]
        if roi is None or roi.size == 0:
            return True
        hsv = _cv2.cvtColor(roi, _cv2.COLOR_BGR2HSV)
        return int((hsv[:, :, 1] > 80).sum()) >= 300

    def _maybe_fire_artifacts(self, frame: Frame | None = None) -> LoopAction | None:
        """Periodic Q/W/E artifact release (configured cooldown per slot).

        Slots = artifact_slots (1-3) mapping to Q/W/E keys; a slot is skipped
        when its icon is absent (unlocked but empty, or fewer slots). First
        fire deferred ~30s after entering MAIN_LINE.
        """
        if not getattr(self.settings, "auto_artifact", True):
            return None
        # `_main_line_since` is the idle watchdog timestamp and is refreshed
        # after every successful action.  Artifact warm-up must instead use
        # the immutable start time for this game, otherwise active runs can
        # postpone Q/W/E forever.
        if not self._main_line_started_at:
            return None
        now = time.time()
        if now - self._main_line_started_at < 30:
            return None
        cd = max(30, int(getattr(self.settings, "artifact_cd", 120)))
        slots = max(1, min(3, int(getattr(self.settings, "artifact_slots", 2))))
        keys = ("q", "w", "e")[:slots]
        if frame is None:
            return None
        for idx, key in enumerate(keys):
            next_at = getattr(self, f"_artifact_next_{key}", 0.0)
            if now < next_at:
                continue
            if frame is not None and not self._slot_has_artifact(frame, idx):
                print(f"[L1] 神器槽{idx + 1}({key.upper()})为空，跳过释放")
                setattr(self, f"_artifact_next_{key}", now + cd)
                continue
            hit = self._hud_button_hit(
                frame,
                f"artifact_{key}",
                (self.ARTIFACT_SLOT_X, self.ARTIFACT_SLOT_Y0 + idx * self.ARTIFACT_SLOT_DY),
            )
            if not self.act_click(hit, f"Artifact-{key.upper()}"):
                # 输入被拒（前台/急停/遮挡）：不推进 CD，下轮重试
                print(f"[L1] 神器 {key.upper()} 点击被拒绝（不推进冷却）")
                continue
            setattr(self, f"_artifact_next_{key}", now + cd)
            print(f"[L1] 释放神器 {key.upper()}（冷却 {cd}s）")
            # Production invariant: at most one UI-changing action per tick.
            return LoopAction.Continue
        return None

    # 核心发育优先：羁绊(F)与技能(G)发育优先打满，再进入宝物(V)、进化、装备升级、拾取、黑商、神器等支线
    # 20260822 实机（trace 203910 tick259-260）：装备右键升级会异步弹出十级词缀
    # 弹窗，旧顺序 equipment→evolve 在弹窗渲染前就点了进化，双弹窗互斥冲突 15s
    # 后 ERROR 停机。用户确认的正确时序：进化全流程（点进化→选英雄→进化全部）
    # 完成后，才做装备升级与背包道具，故 evolve 排在 equipment 之前。
    _L1_CYCLE_ORDER = ("bond", "skill", "bond", "skill", "treasure", "evolve", "equipment", "pickup", "merchant", "artifact")
    # 蹭车 = 打辅助：羁绊/技能/进化/装备都是发育自己，全部不在环里。
    # 20260910 实机复盘：LIVE 走的是 RuntimeMediator，它此前写死 solo 顺序，
    # 于是蹭车局照样点了进化和 1 号装备升级，而 hitch_idle 一次都没到——
    # 公共背包挂在 hitch_idle 上就永远不会被调用。修复见 runtime_mediator。
    # 这里不再留终点停车位：merchant→treasure→pickup→public_bag 循环滚动，
    # 整局持续捡东西、持续往公共背包丢。
    _HITCH_L1_CYCLE_ORDER = ("merchant", "treasure", "pickup", "public_bag")
    # 宝物次数与黑商杀敌货币不是同一个量；V 空开后短暂退避即可，不能用
    # 会被黑商消耗的余额长期阻止后续宝物领取。
    _HITCH_TREASURE_RETRY_S = 8.0
    _MERCHANT_KILL_BALANCE_ROI = (1340 / 1600, 10 / 900, 1390 / 1600, 35 / 900)
    _MERCHANT_KILL_BALANCE_MIN_SCORE = 0.95
    _MERCHANT_DEVOUR_PILL_KILL_COST = 400
    _MERCHANT_WOOD_KILL_COST = 300
    _MERCHANT_REFRESH_KILL_COST = 350
    # Refreshing is useful only when its result can still be bought.  Reserve
    # both the reroll and one pill rather than spending the last 350 points.
    _MERCHANT_REFRESH_WITH_PILL_BUDGET = (
        _MERCHANT_REFRESH_KILL_COST + _MERCHANT_DEVOUR_PILL_KILL_COST
    )
    _MERCHANT_BUDGET_RECHECK_S = 15.0
    # Open ground above the hero: no HUD element, so no tooltip.
    _POINTER_PARK = (0.62, 0.30)

    def _l1_cycle_order(self) -> tuple[str, ...]:
        """蹭车和单人是两条完全不同的环，统一由 Mediator 提供单一真源。"""
        return self._HITCH_L1_CYCLE_ORDER if self._passenger_mode() else self._L1_CYCLE_ORDER

    def _advance_l1_cycle(self, completed: str | None = None) -> None:
        """Advance by position, not tuple.index(), so duplicate bond/skill steps work."""
        order = self._l1_cycle_order()
        current = completed or getattr(self, "_l1_cycle_step", order[0])
        if current == "hitch_idle" and self._passenger_mode():
            # 旧状态落点：直接回到环首，不再永久停车。
            self._l1_cycle_step = order[0]
            self._l1_cycle_index = 0
            self._l1_cycle_last_advance_at = time.time()
            self._l1_cycle_step_successes = 0
            return
        # Advance by position, not tuple.index(), so duplicate bond/skill steps work.
        idx = int(getattr(self, "_l1_cycle_index", 0) or 0)
        if not (0 <= idx < len(order) and order[idx] == current):
            matches = [i for i, step in enumerate(order) if step == current]
            if matches:
                forward = [i for i in matches if i >= idx]
                idx = forward[0] if forward else matches[0]
            else:
                idx = -1
        next_idx = (idx + 1) % len(order)
        nxt = order[next_idx]
        if nxt == "evolve":
            self._evolve_ok_this_cycle = False
            self._evolve_awaiting_hero_pick = False
            self._devour_dan_consecutive_clicks = 0
        if nxt in ("equipment", "pickup") or completed == "evolve":
            self._inventory_clicks_this_visit = 0
            self._inventory_last_pt = None
            self._inventory_same_pt_hits = 0
            self._inventory_next_at = 0.0
            self._devour_dan_consecutive_clicks = 0
        self._l1_cycle_index = next_idx
        self._l1_cycle_step = nxt
        self._l1_cycle_last_advance_at = time.time()
        self._l1_cycle_step_successes = 0

    # B1 抽干上限：同一步骤（skill/bond/treasure 抽卡面板）单次停留最多
    # 3 次成功选择或 30s 即强制推进，避免面板持续有货（如羁绊一直有新卡）
    # 时把整环卡死在同一步，饿死其余步骤（live 000229 复盘）。
    _L1_STEP_VISIT_MAX_SUCCESSES = 3
    _L1_STEP_VISIT_MAX_SECONDS = 30.0
    _F_DRAW_REOPEN_LIMIT = 2
    _F_DRAW_BACKOFF_S = 30.0
    _EXIT_REARM_LIMIT = 2

    def _l1_step_visit_exhausted(self, now: float) -> bool:
        # One visit rule with the solo planner:
        # F: wood >= 1000 -> 15 (狂暴抽卡，充分转化木材资源), 300..1000 -> 2 (让步给技能与支线), < 300 -> 1;
        # G 5, everything else 3; plus the 30s/60s ceiling below.
        cap = self._L1_STEP_VISIT_MAX_SUCCESSES
        step = getattr(self, "_l1_cycle_step", None)
        wood = getattr(self, "_wood_balance", None)
        if not self._passenger_mode() and step == "skill":
            cap = self._SKILL_VISIT_PICKS
        elif not self._passenger_mode() and step == "bond":
            if wood is not None and wood >= self._BOND_HIGH_WOOD:
                cap = 15
            elif wood is not None and wood < self._BOND_LOW_WOOD:
                cap = 1
            elif wood is not None:
                cap = 2
            else:
                elapsed = self._round_elapsed_s()
                cap = self._BOND_VISIT_PICKS_OPENING if elapsed is not None and elapsed < 60 else self._BOND_VISIT_PICKS
        if getattr(self, "_l1_cycle_step_successes", 0) >= cap:
            return True
        started = getattr(self, "_l1_cycle_last_advance_at", None)
        max_s = 60.0 if (not self._passenger_mode() and step == "bond" and wood is not None and wood >= self._BOND_HIGH_WOOD) else self._L1_STEP_VISIT_MAX_SECONDS
        return started is not None and now - started >= max_s

    _BOND_HIGH_WOOD = 1000
    _BOND_LOW_WOOD = 300
    _WOOD_BALANCE_ROI = (1178 / 1600, 8 / 900, 1240 / 1600, 34 / 900)
    _WOOD_READ_INTERVAL_S = 3.0

    # 挑战券剩余（选关页「开始游戏」下方的第一个数字，右对齐）。
    # 与 _ticket_exhausted 用的是同一条文字带；那个只判"是不是 0"，
    # 这个用 OCR 读出真实数字，供动态局数测算校正。
    _TICKET_REMAINDER_ROI = (1067 / 1600, 850 / 900, 1102 / 1600, 888 / 900)
    _TICKET_READ_INTERVAL_S = 5.0
    _TICKET_COST_PER_ROUND = 2  # Owner 口述；读到真实读数一律以读数为准
    _TICKET_READ_MAX = 999
    # A bond visit that ended without a pick (no wood / nothing eligible) lets
    # the other steps run for this long before the 80% lock resumes.
    _BOND_IDLE_BACKOFF_S = 30.0
    # Short post-pick reopen cooldowns (3s) keep the bond step; only long ones
    # (episode cap = 60s) release it.
    _BOND_LONG_COOLDOWN_S = 10.0

    def _hud_wood_balance(self, frame: Frame) -> int | None:
        """Top-bar wood counter (left of the kill skull), OCR like the kill counter."""
        return self._hud_counter(frame, self._WOOD_BALANCE_ROI, "wood")

    def _reset_solo_plan_state(self) -> None:
        """Per-round orchestration state (draw price, visit caps, backoffs, badges)."""
        self._bond_picks_round = 0
        self._visit_kind = None
        self._visit_picks = 0
        self._bond_priority_suspended_at = None
        self._skill_priority_suspended_at = None
        self._bond_idle_until = 0.0
        self._skill_idle_until = 0.0
        self._skill_points_seen = None
        self._treasure_pending_seen = None
        self._wood_balance = None
        self._wood_next_read_at = 0.0

    def _refresh_solo_signals(self, frame: Frame, now: float) -> None:
        """Wood / unspent skill picks / pending treasure, read at most every 3s."""
        if now < getattr(self, "_wood_next_read_at", 0.0):
            return
        self._wood_next_read_at = now + self._WOOD_READ_INTERVAL_S
        self._wood_balance = self._hud_wood_balance(frame)
        # Badges stay at their last reading while the button is hidden
        # (monster selected / panel covering); None only until first seen.
        skill = self._hud_skill_points(frame)
        if skill is not None:
            self._skill_points_seen = skill
        treasure = self._hud_treasure_pending(frame)
        if treasure is not None:
            self._treasure_pending_seen = treasure

    # Unspent skill picks that pre-empt the early bond priority (Owner:
    # 前期 羁绊>技能>其它, but live 000229 banked 32 picks and lost 4-5).
    _SKILL_BACKLOG_FORCE = 4
    _MAIN_LINE_STALL_SECONDS = 90.0
    # Only cards whose direct combat effect is documented in the 2026-09-15
    # mechanics synthesis may survive a stalled-main-line bond choice.
    _STALL_COMBAT_BOND_PRESETS = (
        "挑战", "法术", "急速", "魔能", "魔术", "体术", "元素师",
    )
    # Picks per visit before the cycle moves on (live data 2026-09-15: F
    # drained wood to 0 by 5-6 min while 16-18 skill picks and 12-17 V picks
    # waited).  The first minute is F's cheap window (20/40/60/80 wood).
    _BOND_VISIT_PICKS = 3
    _BOND_VISIT_PICKS_OPENING = 6
    _SKILL_VISIT_PICKS = 5
    # F draw price: 20/40/60/80 for the first draws, then 100 (live panel text).
    _BOND_REFRESH_MARGIN = 40
    _BOND_REFRESH_MAX_PER_GROUP = 2
    _BOND_REFRESH_PRICES = (40, 60, 80, 100)

    def _bond_next_price(self) -> int:
        picks = int(getattr(self, "_bond_picks_round", 0) or 0)
        return 100 if picks >= 4 else 20 * (picks + 1)

    def _bond_refresh_price(self) -> int:
        """Return the visible F-refresh cost for the current bond draw tier."""
        picks = int(getattr(self, "_bond_picks_round", 0) or 0)
        return self._BOND_REFRESH_PRICES[min(picks, len(self._BOND_REFRESH_PRICES) - 1)]

    def _bond_refresh_affordable(self, frame: Frame) -> tuple[bool, int | None, int]:
        """Refresh only with a current, readable wood balance; unknown is not spend authority."""
        price = self._bond_refresh_price()
        wood = self._hud_wood_balance(frame)
        self._wood_balance = wood
        return (wood is not None and wood >= price, wood, price)

    def _visit_capped(self, kind: str) -> bool:
        if getattr(self, "_visit_kind", None) != kind:
            return False
        if kind == "bond":
            wood = getattr(self, "_wood_balance", None)
            if wood is not None and wood >= self._BOND_HIGH_WOOD:
                cap = 15
            elif wood is not None and wood >= self._BOND_LOW_WOOD:
                cap = 2
            elif wood is not None:
                cap = 1
            else:
                elapsed = self._round_elapsed_s()
                cap = self._BOND_VISIT_PICKS_OPENING if elapsed is not None and elapsed < 60 else self._BOND_VISIT_PICKS
        elif kind == "skill":
            cap = self._SKILL_VISIT_PICKS
        else:
            return False
        return int(getattr(self, "_visit_picks", 0) or 0) >= cap
    # A skill visit that picked nothing (no legal card) backs the force off.
    _SKILL_IDLE_BACKOFF_S = 30.0

    def _panel_kind_available(self, kind: str, now: float) -> bool:
        if self._panel_episode_count.get(kind, 0) >= self.settings.panel_episode_limit_per_kind:
            return False
        return self._panel_cooldown_until.get(kind, 0.0) - now <= self._BOND_LONG_COOLDOWN_S

    def _main_line_stalled(self) -> bool:
        return getattr(self, "_main_line_stall_reason", None) is not None

    def _skill_backlog_force(self) -> int:
        return 1 if self._main_line_stalled() else self._SKILL_BACKLOG_FORCE

    def _stall_combat_bond_slots(
        self, slots: tuple[SlotCandidate, ...]
    ) -> tuple[SlotCandidate, ...]:
        """Keep documented combat bonds and confirmed uncompleted owned bonds after a main-line stall."""
        owned = getattr(self, "_confirmed_bond_cards", lambda: ())()
        return tuple(
            slot for slot in slots
            if matches_bond_preset(slot.name, self._STALL_COMBAT_BOND_PRESETS)
            or (owned and _is_uncompleted_merge_upgrade(slot, owned))
        )

    def _stall_combat_bond_policy(self_or_policy: Any, policy: PolicySettings | None = None) -> PolicySettings:
        """Remove economic/base-card gates while stalled, keeping documented combat presets only."""
        if policy is None:
            pol = self_or_policy
        else:
            pol = policy
        presets = Mediator._STALL_COMBAT_BOND_PRESETS
        return replace(
            pol,
            bond_presets=presets,
            bond_base_presets=(),
            bond_advanced_presets=(),
            bond_advanced_groups=(),
            bond_chain_presets=(),
            bond_must_take=(),
        )

    def _should_hold_core_development(self, frame: Frame | None = None, now: float | None = None) -> bool:
        """True when solo script should remain strictly in core development (F <-> G).

        Triggered when:
        1. Not passenger mode
        2. wood >= 1000 (abundant wood must be converted into combat power via bond draws)
        """
        if self._passenger_mode():
            return False
        wood = getattr(self, "_wood_balance", None)
        return wood is not None and wood >= self._BOND_HIGH_WOOD

    def _solo_plan_panel(self, frame: Frame, now: float, step: str) -> tuple[str | None, str]:
        """Solo panel choice for this tick: (target, why); target None = skip step.

        Order of reasons:
          1. skill backlog >= 8 -> G (urgent pre-emption, regardless of wood)
          2. basic bonds < 80% and F can progress (wood >= 1000) -> F
          3. skill backlog >= 4 -> G (high priority over normal cycle when wood < 1000)
          4. normal cycle step:
             - bond: skip if blocked (wood < price) or visit capped
             - skill/treasure: skip if badge 0 or visit capped
        Unreadable badges/balances never skip a step.
        """
        self._refresh_solo_signals(frame, now)
        skill = getattr(self, "_skill_points_seen", None)
        treasure = getattr(self, "_treasure_pending_seen", None)
        idx = getattr(self, "_l1_cycle_index", None)
        # A capped visit suspends that kind's priority until the cycle comes
        # back to one of its own steps; otherwise the lock would pull the
        # panel straight back and the cap would mean nothing.
        for kind in ("bond", "skill"):
            if self._visit_capped(kind):
                setattr(self, f"_{kind}_priority_suspended_at", idx if idx is not None else -1)
                self._visit_kind = None
                self._visit_picks = 0
            held = getattr(self, f"_{kind}_priority_suspended_at", None)
            if held is not None and step == kind and (idx != held or self._should_hold_core_development()):
                setattr(self, f"_{kind}_priority_suspended_at", None)
        bond_held = getattr(self, "_bond_priority_suspended_at", None) is not None
        skill_held = getattr(self, "_skill_priority_suspended_at", None) is not None
        wood = getattr(self, "_wood_balance", None)

        # 1. 紧急强抢占：技能积压 >= 8，无论木材多少先点技能（清出 5 个技能点）
        if (
            skill is not None
            and skill >= 8
            and not skill_held
            and now >= getattr(self, "_skill_idle_until", 0.0)
            and self._panel_kind_available("skill", now)
        ):
            return "skill", f"技能积压 {skill} ≥ 8（紧急强抢占），先点技能"

        # 2. 狂暴发育期/基础羁绊：木材 >= 1000 优先消耗木材转战力，或基础羁绊未满 80% 且木材充足
        bond_blocked = self._bond_step_blocked(frame, now)
        bond_priority_affordable = wood is None or wood >= self._BOND_HIGH_WOOD
        # A pending V draw gets one explicit service opportunity.  F/G retain
        # priority on the other steps without starving treasure forever.
        treasure_has_pending = treasure is None or treasure > 0
        if (
            not (step == "treasure" and treasure_has_pending)
            and bond_blocked is None
            and not bond_held
            and bond_priority_affordable
            and (self._bond_base_progress_pending() or (wood is not None and wood >= self._BOND_HIGH_WOOD))
        ):
            why = f"木材充足（{wood} ≥ {self._BOND_HIGH_WOOD}），羁绊优先转化战力" if (wood is not None and wood >= self._BOND_HIGH_WOOD) else "基础羁绊未满 80% 且木材充足，羁绊优先"
            return "bond", why

        # 3. 高优先技能：技能积压 4~7，木材 < 1000 时先于普通轮换
        if (
            skill is not None
            and skill >= self._skill_backlog_force()
            and not skill_held
            and now >= getattr(self, "_skill_idle_until", 0.0)
            and self._panel_kind_available("skill", now)
        ):
            return "skill", f"技能积压 {skill} ≥ {self._skill_backlog_force()}，先点技能"

        # 4. 轮换到 bond 时的调度
        if step == "bond":
            if bond_blocked is not None:
                return None, f"羁绊暂不推进（{bond_blocked}）"
            if bond_held:
                return None, "本轮羁绊已拿满，轮换下一步"

        # 5. 轮换到 skill/treasure 时的调度
        if step == "skill" and skill == 0:
            return None, "技能角标为 0，没有可点的技能"
        if step == "skill" and skill_held:
            return None, "本轮技能已点满，轮换下一步"
        if step == "treasure" and treasure == 0:
            return None, "宝物角标为 0，没有待拿宝物"
        return step, "按轮换"

    def _bond_step_blocked(self, frame: Frame, now: float) -> str | None:
        """Why the bond step cannot progress right now, or None when it can."""
        self._refresh_solo_signals(frame, now)
        wood = getattr(self, "_wood_balance", None)
        price = self._bond_next_price()
        if wood is not None and wood < price:
            return f"木材 {wood} < {price}"
        if self._panel_episode_count.get("bond", 0) >= self.settings.panel_episode_limit_per_kind:
            return "羁绊 episode 已达上限"
        if self._panel_cooldown_until.get("bond", 0.0) - now > self._BOND_LONG_COOLDOWN_S:
            return "羁绊长冷却中"
        if now < getattr(self, "_f_draw_backoff_until", 0.0):
            return "同一 F 抽卡无候选，进入有界退避"
        if now < getattr(self, "_bond_idle_until", 0.0):
            return "上次开 F 没有可拿的卡"
        return None

    def _maybe_open_choice_panel(self, frame: Frame, anchor: MatchResult | None = None) -> LoopAction | None:
        """Proactive skill (G) / bond (F) / treasure (V) panel opening.

        The owned cycle drains bonds first, then skills and treasure.
        A panel kind advances only after an owned episode yields no selectable
        result.  The per-kind budget is reserved for abnormal episode reopen
        failures; normal successful episodes must not consume it.
        """
        if anchor is None:
            anchor = self._selection_anchor(frame)
        if anchor:
            return None
        if self._has_active_transaction(frame):
            return None
        if self._panel_state != PanelState.CLOSED:
            # 已有面板会话进行中（WAIT_VISIBLE/ACTIVE/…）：不再发起新打开
            return LoopAction.Continue
        now = time.time()
        target = getattr(self, "_choice_target", None) or self._l1_cycle_step
        if self._passive_choice_mode() and not (
            self._passenger_mode() and target == "treasure"
        ):
            return None
        # 基础卡未满 80% 时锁定 F —— 但只在羁绊确实能推进时。Owner 2026-09-15：
        # 木材 <500 先处理技能，技能处理完再宝物/进化/物品栏/神器/黑商；
        # 实机 000229 木材耗尽后 F 冷却 60s 仍被锁在羁绊，技能 20+ 点一次没点。
        if not self._passenger_mode():
            planned, why = self._solo_plan_panel(frame, now, target)
            self._observe_plan = (planned, why)
            if planned is None:
                print(f"[L1] {why}，转下一步")
                self._advance_l1_cycle(target)
                return LoopAction.Continue
            if planned != target:
                print(f"[L1] 编排：{why}（轮换停在 {target}）")
            target = planned
            if target in ("skill", "bond") and getattr(self, "_visit_kind", None) != target:
                self._visit_kind = target
                self._visit_picks = 0
        if target in ("skill", "bond", "treasure"):
            if target == self._l1_cycle_step and self._l1_step_visit_exhausted(now):
                wood = getattr(self, "_wood_balance", None)
                if target == "bond" and (wood is None or wood < self._BOND_HIGH_WOOD):
                    self._bond_idle_until = now + self._BOND_IDLE_BACKOFF_S
                print(f"[L1] {target} 本次停留已达成功选择/时间上限，推进下一步（抽干上限）")
                self._advance_l1_cycle(target)
                return LoopAction.Continue
            panel_enabled = (
                target == "skill"
                or (target == "bond" and getattr(self.settings, "auto_bond", True))
                or (target == "treasure" and getattr(self.settings, "auto_treasure", True))
            )
            if self._passenger_mode() and target == "treasure":
                retry_at = float(getattr(self, "_hitch_treasure_retry_at", 0.0) or 0.0)
                capped = (
                    self._panel_episode_count.get(target, 0)
                    >= self.settings.panel_episode_limit_per_kind
                )
                if capped and retry_at <= 0.0:
                    # An abnormal V episode still needs a backoff, but its
                    # per-round cap must not permanently disable treasure for
                    # the rest of a long hitch game.
                    self._hitch_treasure_retry_at = now + self._HITCH_TREASURE_RETRY_S
                    print("[L1] 蹭车宝物异常 episode 已达上限，8s 后重置该窗口再试")
                    self._advance_l1_cycle("treasure")
                    return LoopAction.Continue
                if now < retry_at:
                    # A passenger simply skips V this lap while new choices
                    # accrue; pickup, bag and merchant remain reachable.
                    self._advance_l1_cycle("treasure")
                    return LoopAction.Continue
                # 选卡点击 mutation 未确认保护：只比较实际物理面板指纹。
                cur_fp = self._panel_physical_fingerprint(frame)
                unconfirmed_fp = getattr(self, "_hitch_last_treasure_unconfirmed_fp", None)
                if unconfirmed_fp is not None:
                    if cur_fp is not None and cur_fp == unconfirmed_fp:
                        print(f"[L1] 画面仍为上次未确认的宝物物理面板指纹（{cur_fp}），跳过 V 推进循环避免重复点击")
                        self._advance_l1_cycle("treasure")
                        return LoopAction.Continue
                    if cur_fp is None or cur_fp != unconfirmed_fp:
                        self._hitch_last_treasure_unconfirmed_fp = None
                if capped:
                    # The bounded retry window elapsed.  Reset only V's
                    # abnormal-episode accounting, then allow one fresh
                    # attempt instead of making the cap terminal.
                    self._panel_episode_count.pop(target, None)
                    self._panel_cooldown_until.pop(target, None)
                    self._hitch_treasure_retry_at = 0.0
                    print("[L1] 蹭车宝物重试窗口到期，重置 V episode 预算并重新探测")
            if (
                panel_enabled
                and not self._passenger_mode()
                and self._panel_episode_count.get(target, 0)
                >= self.settings.panel_episode_limit_per_kind
            ):
                # Solo: the cap is a 60s backoff for this panel only.  Parking
                # here re-armed the 60s every tick, so the panel never came
                # back and the whole L1 cycle stood still (live 000229: F
                # capped at 6:40, wood back at 3346, no F/G/V/evolve after).
                self._panel_episode_count[target] = 0
                self._panel_cooldown_until[target] = now + 60.0
                print(f"[L1] {target} 异常 episode 已达上限，该面板 60s 后再试，轮换转下一步")
                self._advance_l1_cycle(target)
                return LoopAction.Continue
            if (
                panel_enabled
                and self._panel_episode_count.get(target, 0)
                >= self.settings.panel_episode_limit_per_kind
            ):
                # Episode 上限不再用 float("inf") 永久冻结 COOLDOWN：
                # 长冷却到期后面板 FSM 归位，不得永久阻断压力转移/自动任务/黑商。
                self._panel_kind = target
                self._panel_state = PanelState.COOLDOWN
                self._panel_cooldown_until[target] = now + 60.0
                self._panel_opened_by_us = None
                self._skill_refresh_attempts = 0
                print(f"[L1] {target} episode 上限已达，进入 60s 冷却（本局不再重开该面板）")
                return LoopAction.Continue
            reopen_at = self._panel_cooldown_until.get(target, 0.0)
            if (
                not self._passenger_mode()
                and reopen_at - now > self._BOND_LONG_COOLDOWN_S
            ):
                print(f"[L1] {target} 长冷却 {reopen_at - now:.0f}s，轮换转下一步")
                self._advance_l1_cycle(target)
                return LoopAction.Continue
            if now < reopen_at:
                print(f"[L1] {target} 隐藏后冷却 {reopen_at - now:.1f}s，仍留在本步（不跳到下一步）")
                return None
        if target == "skill":
            if self.act_click(self._hud_button_hit(frame, "skill_button", self.CHOICE_BUTTON_RATIOS["skill"]), "OpenSkillPanel"):
                self._last_skill_panel = now
                self._panel_opened_by_us = "skill"
                self._panel_kind = "skill"
                self._panel_state = PanelState.OPEN_REQUESTED
                self._skill_refresh_attempts = 0
                self._l1_cycle_owned_panel = True
                self._l1_cycle_selected = False
                print("[L1] 开 G 技能（没新卡才转 V）")
            else:
                print("[L1] G 技能按钮点击被拒绝（不推进冷却）")
            return LoopAction.Continue
        if target == "bond" and getattr(self.settings, "auto_bond", True):
            if self.act_click(self._hud_button_hit(frame, "bond_button", self.CHOICE_BUTTON_RATIOS["bond"]), "OpenBondPanel"):
                self._last_bond_attempt = now
                self._panel_opened_by_us = "bond"
                self._panel_kind = "bond"
                self._panel_state = PanelState.OPEN_REQUESTED
                self._l1_cycle_owned_panel = True
                self._l1_cycle_selected = False
                print("[L1] 开 F 羁绊（没新卡才转 G）")
            else:
                print("[L1] F 羁绊按钮点击被拒绝（不推进循环）")
            return LoopAction.Continue
        if target == "treasure" and getattr(self.settings, "auto_treasure", True):
            treasure_request_fp = self._panel_physical_fingerprint(frame)
            if self.act_click(self._hud_button_hit(frame, "treasure_button", self.CHOICE_BUTTON_RATIOS["treasure"]), "OpenTreasurePanel"):
                self._last_treasure_attempt = now
                self._treasure_open_request_fp = treasure_request_fp
                self._panel_opened_by_us = "treasure"
                self._panel_kind = "treasure"
                self._panel_state = PanelState.OPEN_REQUESTED
                self._l1_cycle_owned_panel = True
                self._l1_cycle_selected = False
                cur_kills = self._merchant_kill_balance(frame)
                if cur_kills is not None:
                    self._hitch_last_treasure_kill_balance = cur_kills
                print("[L1] 开 V 宝物（刷不动才转支线）")
            else:
                print("[L1] V 宝物按钮点击被拒绝（不推进循环）")
            return LoopAction.Continue
        if target in ("bond", "treasure"):
            # Disabled panel kind: advance without granting click authority.
            self._advance_l1_cycle()
            return LoopAction.Continue
        return None

    @staticmethod
    def _equipment_slot_one_occupied(frame: Frame) -> bool:
        if frame.bgr is None or not LayoutTransform.is_supported(frame.width, frame.height):
            return False
        transform = LayoutTransform.from_frame(frame.width, frame.height)
        rx1, ry1, rx2, ry2 = transform.logical_roi(1062, 710, 1115, 762)
        roi = frame.bgr[ry1:ry2, rx1:rx2]
        if roi.size == 0:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        colored = (hsv[:, :, 1] > 65) & (hsv[:, :, 2] > 55)
        min_pixels = int(220 * transform.scale * transform.scale)
        return int(colored.sum()) >= max(10, min_pixels)

    def _find_equipment_affix_choice(self, frame: Frame) -> MatchResult | None:
        """Detect the four-row level-10 affix modal and pick color priority."""
        if frame.bgr is None or not LayoutTransform.is_supported(frame.width, frame.height):
            return None
        transform = LayoutTransform.from_frame(frame.width, frame.height)
        hsv = cv2.cvtColor(frame.bgr, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(frame.bgr, cv2.COLOR_BGR2GRAY)
        bx1, by1, bx2, by2 = transform.logical_roi(560, 210, 1040, 445)
        body = gray[by1:by2, bx1:bx2]
        if body.size == 0 or float((body < 80).mean()) < 0.85:
            return None
        gold = ((hsv[:, :, 0] >= 10) & (hsv[:, :, 0] <= 35)
                & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 80))
        gx1, gy1, gx2, gy2 = transform.logical_roi(560, 195, 1040, 245)
        min_gold1 = int(2000 * transform.scale * transform.scale)
        if int(gold[gy1:gy2, gx1:gx2].sum()) < max(50, min_gold1):
            return None
        gx1, gy1, gx2, gy2 = transform.logical_roi(560, 405, 1040, 455)
        min_gold2 = int(900 * transform.scale * transform.scale)
        if int(gold[gy1:gy2, gx1:gx2].sum()) < max(25, min_gold2):
            return None
        rows = (240, 285, 330, 375)
        for y in rows:
            rx1, ry1, rx2, ry2 = transform.logical_roi(650, y, 950, y + 40)
            min_text = int(350 * transform.scale * transform.scale)
            bright = gray[ry1:ry2, rx1:rx2] > 120
            colored = (hsv[ry1:ry2, rx1:rx2, 1] > 50) & (hsv[ry1:ry2, rx1:rx2, 2] > 60)
            if int((bright | colored).sum()) < max(15, min_text):
                return None

        def row_rank(y: int) -> int:
            rx1, ry1, rx2, ry2 = transform.logical_roi(650, y, 950, y + 35)
            roi = hsv[ry1:ry2, rx1:rx2]
            if roi.size == 0:
                return 1
            hue, sat, val = roi[:, :, 0], roi[:, :, 1], roi[:, :, 2]
            # 积极属性多为绿字；优先于红/橙品质色，避免永远点第一行 equipment_affix_0。
            masks = (
                (6, (hue >= 35) & (hue < 90) & (sat > 60) & (val > 80)),
                (5, ((hue <= 10) | (hue >= 170)) & (sat > 80) & (val > 90)),
                (4, (hue > 10) & (hue <= 30) & (sat > 80) & (val > 90)),
                (3, (hue >= 125) & (hue < 170) & (sat > 60) & (val > 80)),
                (2, (hue >= 90) & (hue < 125) & (sat > 60) & (val > 80)),
            )
            for rank, mask in masks:
                if mask.sum() >= 30:
                    return rank
            return 1

        index = max(range(4), key=lambda i: (row_rank(rows[i]), -i))
        px, py = transform.logical_point(800, rows[index] + 20)
        return MatchResult(f"equipment_affix_{index}", 1.0, px, py, 0, 0,
                           frame.left + px, frame.top + py)

    def _find_evolution_choice(self, frame: Frame, anchor: MatchResult | None = None) -> MatchResult | None:
        """Recognize the two-card hero-evolution modal and choose its best rarity."""
        if frame.bgr is None or not LayoutTransform.is_supported(frame.width, frame.height):
            return None
        transform = LayoutTransform.from_frame(frame.width, frame.height)
        # 进化二选一面板支持底部 anchor (toHero 等) 或中央双卡边框特征
        gray = cv2.cvtColor(frame.bgr, cv2.COLOR_BGR2GRAY)
        gradient = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))

        def edge_count(x: int) -> int:
            rx1, ry1, rx2, ry2 = transform.logical_roi(x - 4, 150, x + 5, 510)
            return int((gradient[ry1:ry2, rx1:rx2] > 80).sum())

        scale_area = transform.scale * transform.scale
        if not (
            edge_count(816) >= max(50, int(350 * scale_area))
            and edge_count(1050) >= max(30, int(100 * scale_area))
            and edge_count(408) < max(30, int(600 * scale_area))
            and edge_count(1201) < max(30, int(600 * scale_area))
        ):
            return None
        hsv = cv2.cvtColor(frame.bgr, cv2.COLOR_BGR2HSV)

        def rarity_rank(x1: int, x2: int) -> int:
            rx1, ry1, rx2, ry2 = transform.logical_roi(x1, 145, x2, 515)
            roi = hsv[ry1:ry2, rx1:rx2]
            if roi.size == 0:
                return 0
            colored = (roi[:, :, 1] > 80) & (roi[:, :, 2] > 70)
            min_colored = max(100, int(6000 * scale_area))
            if int(colored.sum()) < min_colored:
                # 未知/神秘进化（灰色/暗色底框，特殊词条）
                # 如果开启未知进化优先(True)，设为最高分 7 (大于 UR 6)；默认设为 3.5 (UR 6 > SSR 4 > 未知 3.5 > SR 3 > R 2)
                return 7 if getattr(self.settings, "evolve_mystic_priority", False) else 3.5
            hue = roi[:, :, 0][colored]
            bands = (
                (6, (hue <= 8) | (hue >= 170)),   # UR/red
                (4, (hue >= 10) & (hue <= 38)),   # SSR/orange-gold
                (3, (hue >= 125) & (hue < 170)),  # SR/purple
                (2, (hue >= 103) & (hue < 125)),  # R/blue
                (1, (hue >= 45) & (hue < 80)),    # N/green
            )
            return max(bands, key=lambda item: int(item[1].sum()))[0]
        ranks = (rarity_rank(540, 790), rarity_rank(810, 1060))
        max_rank = max(ranks)
        # 如果两张都没有 SR (rank>=3)，且有刷新按钮，则优先点击刷新
        if max_rank < 3:
            # 刷新按钮在弹窗底栏右侧 (x≈946, y≈542)
            rx, ry = transform.logical_point(946, 542)
            return MatchResult(
                "evolution_refresh_btn", 1.0,
                rx, ry, 0, 0, frame.left + rx, frame.top + ry,
            )
        index = max(range(2), key=lambda i: (ranks[i], -i))
        base_x, base_y = ((666, 300), (933, 300))[index]
        x, y = transform.logical_point(base_x, base_y)
        return MatchResult(
            f"evolution_card_{index}_rank_{ranks[index]}", 1.0,
            x, y, 0, 0, frame.left + x, frame.top + y,
        )

    def _evolve_button_hit(self, frame: Frame) -> MatchResult:
        """点角色面板金色「点击进化」。不要点左侧羁绊图标（成长/经济）。"""
        x0 = int(frame.width * 0.48)
        y0 = int(frame.height * 0.75)
        x1 = int(frame.width * 0.64)
        y1 = int(frame.height * 0.81)
        roi = frame.bgr[y0:y1, x0:x1] if frame.bgr is not None else None
        if roi is not None and roi.size:
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            gold = (
                (hsv[:, :, 0] >= 14)
                & (hsv[:, :, 0] <= 34)
                & (hsv[:, :, 1] > 100)
                & (hsv[:, :, 2] > 160)
            )
            ys, xs = np.where(gold)
            if xs.size >= 40:
                x = x0 + int(xs.mean())
                y = y0 + int(ys.mean())
                print(f"[L1] 进化金条「点击进化」@ ({x}, {y})")
                return MatchResult(
                    "evolve_hud", 1.0, x, y, 40, 12, frame.left + x, frame.top + y,
                )
        fallback_x = int(frame.width * 0.55)
        fallback_y = int(frame.height * 0.783)
        print(f"[L1] 进化未检出金条像素，回退金条中心 @ ({fallback_x}, {fallback_y})")
        return MatchResult(
            "evolve_hud", 1.0, fallback_x, fallback_y, 40, 12, frame.left + fallback_x, frame.top + fallback_y,
        )

    def _has_evolve_button(self, frame: Frame) -> bool:
        x0 = int(frame.width * 0.48)
        y0 = int(frame.height * 0.75)
        x1 = int(frame.width * 0.64)
        y1 = int(frame.height * 0.81)
        roi = frame.bgr[y0:y1, x0:x1] if frame.bgr is not None else None
        if roi is not None and roi.size:
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            gold = (
                (hsv[:, :, 0] >= 14)
                & (hsv[:, :, 0] <= 34)
                & (hsv[:, :, 1] > 100)
                & (hsv[:, :, 2] > 160)
            )
            return int(gold.sum()) >= 40
        return False
    def _complete_evolve_hero_pick(self) -> None:
        self._evolve_awaiting_hero_pick = False
        self._evolve_ok_this_cycle = True
        self._evolve_feedback_pending = False
        self._evolve_click_cooldown_until = 0.0
        # 英雄三选一完成 = 本轮进化闭环；按既有循环序推进（evolve → 下一步）。
        if self._l1_cycle_step == "evolve":
            self._advance_l1_cycle("evolve")
    def _evolve_feedback_seen(self, frame: Frame) -> bool:
        """P0-2：点击进化后的后置确认 —— 选择面板锚点出现 ∨ 中央区域像素变化。

        164929 假命中现场：模板命中于窗口底部空白/底边框区，点击无任何反馈；
        本函数用于把"点击成功"从 SendInput 成功（act_click 返回 True）中分离出来，
        只有画面证据才算成功推进。
        """
        if self._selection_anchor(frame) is not None:
            return True
        baseline = self._evolve_baseline
        if baseline is None:
            return False
        roi = self._panel_roi_region(frame)
        if roi is None or roi.shape != baseline.shape:
            return roi is not None  # 尺寸变化本身即画面异变
        return self._hero_changed_pixels(baseline, roi) >= 2000

    def _tick_evolve_feedback_pending(self, frame: Frame, now: float) -> LoopAction | None:
        """检查 evolve 点击后的反馈确认或超时。"""
        if not getattr(self, "_evolve_feedback_pending", False):
            return None
        if self._evolve_feedback_seen(frame):
            print("[L1] 进化反馈已确认，等待英雄选择")
            self._evolve_feedback_pending = False
            self._evolve_fail_count = 0
            self._evolve_baseline = None
            self._evolve_awaiting_hero_pick = True
            self._evolve_awaiting_hero_pick_at = now
            self._main_line_since = now
            return LoopAction.Continue
        timeout_s = getattr(self, "_evolve_feedback_window_s", 2.0)
        if now - getattr(self, "_evolve_click_at", 0.0) >= timeout_s:
            self._evolve_feedback_pending = False
            self._evolve_baseline = None
            self._evolve_fail_count = getattr(self, "_evolve_fail_count", 0) + 1
            print(f"[L1] 点击进化无反馈（第 {self._evolve_fail_count} 次失败），等待冷却后重试")
            if self._evolve_fail_count >= 3:
                print("[L1] 进化连续 3 次无反馈，放弃本轮进化（不连续空点）")
                self._evolve_fail_count = 0
                if self._l1_cycle_step == "evolve":
                    self._advance_l1_cycle("evolve")
            return LoopAction.Continue
        return LoopAction.Continue

    def _maybe_opportunistic_evolve(self, frame: Frame, now: float) -> LoopAction | None:
        """HUD_ONLY 机会动作：当金色点击进化高亮且不在冷却中时执行快速事务。"""
        if now < getattr(self, "_evolve_click_cooldown_until", 0.0):
            return None
        if not self._has_evolve_button(frame):
            return None
        evolve_hit = self._evolve_button_hit(frame)
        if evolve_hit:
            print(f"[L1] 机会点击进化 @ {evolve_hit.center}")
            if self.act_click(evolve_hit, "ClickEvolve"):
                self._evolve_click_cooldown_until = now + 5.0
                self._evolve_feedback_pending = True
                self._evolve_click_at = now
                self._evolve_baseline = self._panel_roi_region(frame)
                return LoopAction.Continue
        return None

    def _slot1_upgrade_authorized(self, frame: Frame, now: float) -> bool:
        """Shared authorization rule for slot 1 right-click upgrade across normal and opportunistic paths.

        Strict contract:
        1. 8s cadence interval (now >= _equipment_next_at)
        2. Slot 1 occupied in HUD inventory ROI
        3. EquipmentFSM authorization (can_use(1, now) == True)
        Zero input if any condition fails.
        """
        if now < getattr(self, "_equipment_next_at", 0.0):
            return False
        if not self._equipment_slot_one_occupied(frame):
            return False
        if getattr(self, "_equipment_fsm", None) is not None and not self._equipment_fsm.can_use(1, now):
            return False
        return True

    def _maybe_opportunistic_upgrade_slot1(self, frame: Frame, now: float) -> LoopAction | None:
        """HUD_ONLY 机会动作：1号格武器右键最大升级（仅在 Core Development 下低频 8s CD 触发，走现有 equipment_fsm）。"""
        if not self._should_hold_core_development():
            return None
        if self._merchant_fsm.phase is MerchantPhase.VERIFYING:
            return None
        if not self._slot1_upgrade_authorized(frame, now):
            return None
        hit = self._hud_button_hit(frame, "equipment_slot_1", (1087 / 1600, 737 / 900))
        eq_fp_base = self._equipment_slot_fingerprint(frame, 1)
        if self.act_right_click(hit, "UpgradeEquipmentSlot1-max"):
            lease_s = float(self.settings.ui_action_interval_s)
            self._equipment_fsm = self._equipment_fsm.begin(1, now, lease_s=lease_s, fingerprint=eq_fp_base)
            self._equipment_pending_until = now + lease_s
            self._equipment_next_at = now + 8.0
            return LoopAction.Continue
        return None

    def _tick_equipment_pending(self, frame: Frame, now: float) -> bool:
        """Settle pending equipment verification lease. Returns True if still pending."""
        if getattr(self, "_equipment_fsm", None) is None:
            return False
        if self._equipment_fsm.pending_slot is None:
            return False
        if now < getattr(self, "_equipment_pending_until", 0.0):
            return True
        eq_fp = self._equipment_slot_fingerprint(frame, self._equipment_fsm.pending_slot)
        self._equipment_fsm = self._equipment_fsm.observe(
            now,
            current_fingerprint=eq_fp,
        )
        self._equipment_pending_until = 0.0
        return False

    def _maybe_use_inventory_item(self, frame: Frame) -> LoopAction | None:
        """Use inventory consumables in the verified bottom-right inventory ROI (HUD_ONLY)."""
        if (
            self._pending_action is not None
            and not self._pending_action.is_confirmed(frame)
            and time.time() < self._pending_action.deadline
        ):
            return None
        if self._panel_state != PanelState.CLOSED:
            return None
        if self._public_bag_fsm.active:
            # 公共背包流转正持有队伍资产：此刻任何左键都会当场吃掉吞噬丹。
            return None
        now = time.time()
        inventory_roi = (0.64, 0.77, 0.74, 0.98)
        if self.settings.auto_devour_dan and self._can_consume_inventory_swallow_pill(frame):
            pill = self.find(
                frame,
                ["danGif", "swallow_pill"],
                threshold=0.70,
                roi=inventory_roi,
                scales=(0.8, 0.9, 1.0, 1.1, 1.2),
            )
            if pill is None:
                # 丹在背包里而不在 HUD 栏时，只有背包页开着才看得到它。
                pill = self._bag_page_swallow_pill(frame)
            if pill:
                if now >= self._devour_dan_next_at and self._devour_dan_consecutive_clicks < 5:
                    baseline_occ = getattr(self, "_bond_bar_occupancy", lambda f: None)(frame)
                    if self.act_click(pill, "UseInventory-swallow_pill"):
                        self._devour_dan_next_at = now + 1.0
                        self._inventory_next_at = now + 1.0
                        self._devour_dan_consecutive_clicks += 1
                        self._inventory_clicks_this_visit += 1
                        if self._inventory_last_pt == pill.center:
                            self._inventory_same_pt_hits += 1
                        else:
                            self._inventory_last_pt = pill.center
                            self._inventory_same_pt_hits = 1
                        self._pending_action = PendingAction(
                            kind="WAIT_SWALLOW_PILL_CONFIRM",
                            target_id="swallow_pill",
                            deadline=now + 2.0,
                            verifier=lambda f: bool(
                                baseline_occ is not None
                                and getattr(self, "_bond_bar_occupancy", lambda _: baseline_occ)(f) < baseline_occ
                            ),
                        )
                        return LoopAction.Continue
            else:
                self._devour_dan_consecutive_clicks = 0
        if now < self._inventory_next_at or self._inventory_clicks_this_visit >= 2:
            return None
        # 严格门禁：未点击进化完成前，绝对不点英雄卡（否则点不开并空耗点击）
        if not getattr(self, "_evolve_ok_this_cycle", False):
            return None
        hero_card = self.find(
            frame,
            ["hero_card_item"],
            threshold=0.65,
            roi=inventory_roi,
            scales=(0.8, 0.9, 1.0, 1.1, 1.2),
        )
        if hero_card is not None and self._inventory_clicks_this_visit < 3:
            self._inventory_clicks_this_visit += 1
            if self._inventory_last_pt == hero_card.center:
                self._inventory_same_pt_hits += 1
            else:
                self._inventory_last_pt = hero_card.center
                self._inventory_same_pt_hits = 1
            self._inventory_next_at = now + 1.0
            if self.act_click(hero_card, "UseInventory-hero-card"):
                print(f"[L1] 使用背包英雄卡 @ {hero_card.center}")
                self._pending_action = PendingAction(
                    kind="WAIT_HERO_CHOICE",
                    target_id="hero_card_item",
                    deadline=now + 3.0,
                    verifier=lambda f: bool(self._find_evolution_choice(f, anchor=self._selection_anchor(f)) is not None),
                )
                return LoopAction.Continue
        return LoopAction.Continue
    def _equipment_slot_fingerprint(self, frame: Frame, slot_idx: int) -> str:
        """Extract stable grayscale perceptual/difference hash of the equipment slot ROI (24x24)."""
        if frame is None or frame.bgr is None or frame.bgr.size == 0:
            return ""
        slot_coords = {
            1: (1087 / 1600, 737 / 900),
            2: (1145 / 1600, 737 / 900),
            3: (1087 / 1600, 785 / 900),
            4: (1145 / 1600, 785 / 900),
            5: (1087 / 1600, 833 / 900),
            6: (1145 / 1600, 833 / 900),
        }
        fx, fy = slot_coords.get(slot_idx, (1087 / 1600, 737 / 900))
        h, w = frame.bgr.shape[:2]
        cx, cy = int(fx * w), int(fy * h)
        rx1, rx2 = max(0, cx - 12), min(w, cx + 12)
        ry1, ry2 = max(0, cy - 12), min(h, cy + 12)
        patch = frame.bgr[ry1:ry2, rx1:rx2]
        if patch.size == 0 or patch.shape[0] < 8 or patch.shape[1] < 8:
            return ""
        # Convert patch to normalized grayscale 8x8 block
        gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY) if len(patch.shape) == 3 else patch
        resized = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA)
        avg = float(resized.mean())
        # 64-bit dHash / perceptual bitstring
        bits = [(1 if resized[r, c] > avg else 0) for r in range(8) for c in range(8)]
        hash_hex = hex(int("".join(map(str, bits)), 2))[2:].zfill(16)
        # Also append mean grayscale intensity with 4-level quantization (resilient to minor 1-3px sensor noise)
        quant_intensity = int(avg // 10)
        return f"slot_{slot_idx}_{hash_hex}_{quant_intensity}"

    def _maybe_upgrade_equipment(self, frame: Frame) -> LoopAction:
        """Upgrade weapon/equipment in verified HUD_ONLY inventory ROI.

        Rules:
        - 1 号格：保留右键最大升级（最小间隔 8s）；
        - 2-6 号格：每 30 秒执行一轮巡检，每 tick 顺序左键一个格子（2→3→4→5→6）；
        - 门禁：仅在 InteractionSurface.HUD_ONLY 下执行，一旦有任何弹窗立即冻结整轮。
        - 20260822：升级点击可能异步弹出十级词缀弹窗——动作后停留在本步骤，
          直到词缀弹窗被仲裁层处理消失才推进循环（防 evolve/其它步骤叠弹窗）。
        """
        if self._pending_action is not None and not self._pending_action.is_confirmed(frame):
            return LoopAction.Continue
        if (
            self._panel_state != PanelState.CLOSED
            or self._merchant_fsm.phase is MerchantPhase.VERIFYING
        ):
            return LoopAction.Continue
        now = time.time()
        if self._equipment_fsm.pending_slot is not None:
            if self._tick_equipment_pending(frame, now):
                return LoopAction.Continue
            if self._find_equipment_affix_choice(frame) is not None:
                print("[L1] 装备词缀弹窗待处理，装备步骤暂不推进循环")
                return LoopAction.Continue
        # 1号格升级 (右键最大升级，8s 间隔，需 FSM can_use 授权)
        if self._slot1_upgrade_authorized(frame, now):
            hit = self._hud_button_hit(frame, "equipment_slot_1", (1087 / 1600, 737 / 900))
            eq_fp_base = self._equipment_slot_fingerprint(frame, 1)
            if self.act_right_click(hit, "UpgradeEquipmentSlot1-max"):
                lease_s = float(self.settings.ui_action_interval_s)
                self._equipment_fsm = self._equipment_fsm.begin(1, now, lease_s=lease_s, fingerprint=eq_fp_base)
                self._equipment_pending_until = now + lease_s
                self._equipment_next_at = now + 8.0
                return LoopAction.Continue

        # P0-02: 禁用 2-6 格盲目左键巡检。在具备可靠 item identity 与动作语义前保持零输入。
        return LoopAction.Continue

    @staticmethod
    def _in_merchant_strip(frame: Frame, hit: MatchResult | None) -> bool:
        if hit is None or frame.width <= 0 or frame.height <= 0:
            return False
        fx = hit.x / float(frame.width)
        fy = hit.y / float(frame.height)
        return 0.70 <= fx <= 0.90 and 0.66 <= fy <= 0.76

    @staticmethod
    def _black_merchant_cards_present(frame: Frame) -> bool:
        """Detect filled merchant cards above inventory."""
        if frame.bgr is None or frame.width <= 0 or frame.height <= 0:
            return False
        x0, y0 = int(frame.width * 0.70), int(frame.height * 0.66)
        x1, y1 = int(frame.width * 0.90), int(frame.height * 0.74)
        roi = frame.bgr[y0:y1, x0:x1]
        if roi.size == 0:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        sat = ((hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 70)).astype(np.uint8) * 255
        n_labels, _labels, stats, _cents = cv2.connectedComponentsWithStats(sat, 8)
        blobs = 0
        max_w = roi.shape[1] * 0.45
        for i in range(1, n_labels):
            _x, _y, bw, bh, area = stats[i]
            if area >= 80 and bw >= 14 and bh >= 14 and bw < max_w:
                blobs += 1
        return blobs >= 2

    @staticmethod
    def _black_merchant_present(frame: Frame) -> bool:
        """Detect a merchant card strip, including an empty strip with refresh control."""
        return Mediator._black_merchant_cards_present(frame) or Mediator._merchant_refresh_available(frame)

    @staticmethod
    def _merchant_fingerprint(frame: Frame, slot_items=None) -> str:
        if frame.bgr is None or frame.width <= 0 or frame.height <= 0:
            return ""
        x0, y0, x1, y1 = MERCHANT_STRIP_ROI
        roi = frame.bgr[int(frame.height * y0):int(frame.height * y1),
                        int(frame.width * x0):int(frame.width * x1)]
        return MerchantScanner.compute_merchant_fingerprint(roi, slot_items)


    @staticmethod
    def _bond_bar_nonempty(frame: Frame) -> bool:
        """Conservative prerequisite for consuming a merchant swallow pill."""
        if frame.bgr is None or frame.width <= 0 or frame.height <= 0:
            return False
        x0, y0 = int(frame.width * 0.35), int(frame.height * 0.68)
        x1, y1 = int(frame.width * 0.42), int(frame.height * 0.78)
        roi = frame.bgr[y0:y1, x0:x1]
        if roi.size == 0:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        colored = (hsv[:, :, 1] > 85) & (hsv[:, :, 2] > 65)
        scale = min(frame.width / 1600.0, frame.height / 900.0)
        min_colored = max(20, int(250 * scale * scale))
        return int(colored.sum()) >= min_colored

    def _can_consume_inventory_swallow_pill(self, frame: Frame) -> bool:
        """Fail-closed: ordinary random devouring is forbidden without reliable
        per-slot card identities — occupancy and the saved opt-in cannot prove
        protected cards are absent.
        """
        return False

    def _bag_page_swallow_pill(self, frame: Frame) -> MatchResult | None:
        """Devour pill inside an open bag page's 物品栏, aimed at the slot center.

        Only reachable when the bag page is confirmed by both anchors, so this
        never turns a battlefield false positive into a click.  Left-clicking a
        源物品格 consumes it, which is what ``auto_devour_dan`` wants in solo —
        but under ``lobby_hitch`` the pill is a team asset bound for the public
        bag, so this path stays closed there.
        """
        if self._passenger_mode():
            return None
        layout = self._bag_layout(frame)
        if layout is None:
            return None
        source = self._public_bag_source(frame, layout)
        if source is None:
            return None
        return source["hit"]

    # ---------- 公共背包流转 (docs/gt_lab/PUBLIC_BAG_GT_SPEC_20260909.md) ----------
    #
    # 蹭车 = 打辅助：羁绊/技能/进化都是升级自己的动作，一律不碰。可移动的
    # 装备、宝物与消耗品都交给车队；装备栏 1 号固定为自己的武器，永远不尝试。
    #
    # 20260910 实机：面板常开会挡住战后广场 NPC。有货才开，物品栏先短
    # 距离进个人格，再迁公共格，搬完立刻关。

    _PUBLIC_BAG_ANCHORS = ("bag/public_bag_title", "bag/bag_sell_equipment")
    _PUBLIC_BAG_ANCHOR_THRESHOLD = 0.80
    _PUBLIC_BAG_PILL_TEMPLATES = ("danGif", "swallow_pill")
    _PUBLIC_BAG_EMPTY_CLOSE_S = 1.5
    # The bag page covers the HUD, merchant, auto-task and post-game controls.
    # One open episode may last this long before we close it ourselves, then
    # stay closed for the reopen cooldown (live 2026-09-11: it stayed open for
    # minutes and blocked ContinueGame / the archive plaza).
    _PUBLIC_BAG_MAX_OPEN_S = 30.0
    _PUBLIC_BAG_REOPEN_COOLDOWN_S = 45.0
    # The player closing the page by hand is an instruction, not a glitch.
    _PUBLIC_BAG_USER_CLOSE_COOLDOWN_S = 60.0

    def _public_bag_surface_ok(self, frame: Frame) -> bool:
        """May we open or drain the bag on this frame?

        20260910 K f0000: hitch 局内 2-7，背包关着，zidong/shortKey 全 miss，
        但右缘 [B] 书本 0.88。HUD-only 门禁让探针 60s 零输入后 BLOCKED。
        战后广场仍禁止开包。
        """
        if self._bag_layout(frame) is not None:
            return True
        if self._post_game_state(frame) in {
            "NPC_HUB",
            "POST_VICTORY",
            "ARCHIVE_PANEL",
            "HEIRLOOM_DIALOG",
            "GREAT_RIFT_CONFIRM",
            "TQTZ_CONFIRM",
        }:
            return False
        if self._is_in_game_hud(frame):
            return True
        return self._hud_hotkey_button(frame, "bag/bag_toggle_button") is not None

    def _hud_hotkey_button(self, frame: Frame, name: str) -> MatchResult | None:
        """Locate one of the right-edge clickable hotkey twins ([B] / [Z]).

        20260910: the deposit probe pressed B five times, every press reported
        SUCCESS, and the bag never opened — the game simply does not take that
        keystroke (bundle public_backpack_deposit_20260910_122808_521256, all
        five after-frames show plain HUD).  Mouse input is the injection path
        this project has live evidence for, and the HUD draws a clickable book
        icon labelled [B] right next to the [Z] pickup hand, so we click those
        instead of trusting the key.
        """
        hit = self.find(
            frame,
            [name],
            threshold=0.70,
            scales=self._hot_scales(),
            roi=ANCHOR_ROIS[name],
            mode=f"hud_hotkey:{name}",
        )
        if hit is None:
            return None
        x, y = hit.x + hit.w // 2, hit.y + hit.h // 2
        return MatchResult(name, hit.score, x, y, 0, 0, frame.left + x, frame.top + y)

    def _toggle_bag_page(self, frame: Frame, reason: str) -> bool:
        """Click the HUD [B] book, else key B. Same control opens and closes."""
        button = self._hud_hotkey_button(frame, "bag/bag_toggle_button")
        if button is not None:
            return self.act_click(button, reason)
        return self.act_key("b", reason)

    def _open_bag_page(self, frame: Frame) -> bool:
        return self._toggle_bag_page(frame, "PublicBackpackDepositB")

    def _bag_layout(self, frame: Frame) -> BagLayout | None:
        """Fresh-confirm the bag page (spec step 4) and the public bag (step 5).

        Both anchors must be present *and* agree on one panel origin.  A single
        template hit on a busy battlefield is not a bag page, and the whole
        deposit chain hangs off this returning ``None`` when unsure.
        """
        if frame.bgr is None or not LayoutTransform.is_supported(frame.width, frame.height):
            return None
        title_name, sell_name = self._PUBLIC_BAG_ANCHORS
        title = self.find(
            frame,
            [title_name],
            threshold=self._PUBLIC_BAG_ANCHOR_THRESHOLD,
            scales=self._hot_scales(),
            roi=ANCHOR_ROIS[title_name],
            mode="bag:public_title",
        )
        if title is None:
            return None
        sell = self.find(
            frame,
            [sell_name],
            threshold=self._PUBLIC_BAG_ANCHOR_THRESHOLD,
            scales=self._hot_scales(),
            roi=ANCHOR_ROIS[sell_name],
            mode="bag:sell_equipment",
        )
        if sell is None:
            return None
        scale = LayoutTransform.from_frame(frame.width, frame.height).uniform_scale
        layout = BagLayout.from_anchor(title_name, title.x, title.y, scale)
        if layout is None or not layout.anchor_matches(sell_name, sell.x, sell.y):
            return None
        return layout

    @staticmethod
    def _bag_slot_signature(frame: Frame, rect: tuple[int, int, int, int] | None) -> tuple[float, int] | None:
        """(grayscale std, saturated pixel count) for one slot rect."""
        if rect is None or frame.bgr is None:
            return None
        x0, y0, x1, y1 = rect
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(frame.width, x1), min(frame.height, y1)
        if x1 - x0 < 4 or y1 - y0 < 4:
            return None
        roi = frame.bgr[y0:y1, x0:x1]
        if roi.size == 0:
            return None
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        saturated = int(
            ((hsv[:, :, 1] > SLOT_SATURATION_MIN) & (hsv[:, :, 2] > SLOT_VALUE_MIN)).sum()
        )
        std = float(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY).std())
        return (std, saturated)

    @staticmethod
    def _bag_area_scale(frame: Frame) -> float:
        return min(frame.width / 1600.0, frame.height / 900.0) ** 2

    def _bag_slot_empty(self, frame: Frame, rect: tuple[int, int, int, int] | None) -> bool:
        """True only for a *verifiably* empty slot.

        A cursor-occluded slot measures std 24-76 on the GT keyframes and fails
        this check, so the deposit skips it instead of clicking through the
        cursor into an unknown cell.
        """
        signature = self._bag_slot_signature(frame, rect)
        if signature is None:
            return False
        std, saturated = signature
        limit = max(20.0, EMPTY_SLOT_MAX_SATURATED * self._bag_area_scale(frame))
        return std < EMPTY_SLOT_MAX_STD and saturated < limit

    def _bag_slot_occupied(self, frame: Frame, rect: tuple[int, int, int, int] | None) -> bool:
        """True only for a *verifiably* occupied slot.

        Empty and occupied are separate positive tests on purpose: the mouse
        cursor alone reaches std 76 but never more than ~118 saturated pixels,
        while a real item icon carries 103-823.  A cell that answers neither is
        simply skipped this tick.
        """
        signature = self._bag_slot_signature(frame, rect)
        if signature is None:
            return False
        std, saturated = signature
        floor = max(20.0, OCCUPIED_SLOT_MIN_SATURATED * self._bag_area_scale(frame))
        return std >= OCCUPIED_SLOT_MIN_STD and saturated >= floor

    # The HUD's own 物品栏 (bottom right, 1600x900 baseline), laid out
    # 1 2 / 3 4 / 5 6; slot 1 is the hero's fixed gear.  It stays visible with
    # the bag page open and draws each icon larger than the page's copy.
    _HUD_ITEM_BAR_FIRST = (1082, 735)
    _HUD_ITEM_BAR_PITCH = 60
    _HUD_ITEM_BAR_PROBE_HALF = 16

    def _hud_item_bar_rect(self, frame: Frame, index: int) -> tuple[int, int, int, int] | None:
        if frame.bgr is None or not LayoutTransform.is_supported(frame.width, frame.height):
            return None
        col, row = index % 2, index // 2
        cx = self._HUD_ITEM_BAR_FIRST[0] + col * self._HUD_ITEM_BAR_PITCH
        cy = self._HUD_ITEM_BAR_FIRST[1] + row * self._HUD_ITEM_BAR_PITCH
        h = self._HUD_ITEM_BAR_PROBE_HALF
        return LayoutTransform.from_frame(frame.width, frame.height).logical_roi(
            cx - h, cy - h, cx + h, cy + h
        )

    def _hud_item_bar_state(self, frame: Frame) -> str:
        """'items' / 'empty' / 'unknown' for the movable HUD slots 2-6.

        A slot already retired as unmovable this round does not count.
        """
        all_empty = True
        for index in range(1, ITEM_BAR_SLOTS):
            rect = self._hud_item_bar_rect(frame, index)
            if rect is None:
                return "unknown"
            if self._public_bag_source_exhausted(f"item_bar_{index}"):
                continue
            if self._bag_slot_occupied(frame, rect):
                return "items"
            if not self._bag_slot_empty(frame, rect):
                all_empty = False
        return "empty" if all_empty else "unknown"

    def _hud_item_bar_occupied_count(self, frame: Frame) -> int | None:
        """Return the confirmed count of movable HUD slots, else ``None``.

        Range pickup is not a periodic combat action.  It is reserved for the
        actual equipment-overflow condition, so a partially occluded HUD must
        not be guessed as full.
        """
        occupied = 0
        for index in range(1, ITEM_BAR_SLOTS):
            rect = self._hud_item_bar_rect(frame, index)
            if rect is None:
                return None
            if self._bag_slot_occupied(frame, rect):
                occupied += 1
                continue
            if not self._bag_slot_empty(frame, rect):
                return None
        return occupied

    def _hud_item_bar_overflowed(self, frame: Frame) -> bool:
        """True only when all movable equipment slots are visibly occupied."""
        occupied = self._hud_item_bar_occupied_count(frame)
        return occupied == ITEM_BAR_SLOTS - 1

    def _item_bar_slot_occupied(self, frame: Frame, layout: BagLayout, index: int) -> bool:
        """Bag-page 物品栏 slot holds an item.

        Live 2026-09-12 the hero card measured 135 saturated pixels on the
        page against a 140 floor (kept to reject the cursor), so it was never
        handed over.  An icon the page can't call empty counts when the HUD's
        larger copy of the same slot is clearly occupied - the cursor cannot
        sit on both.
        """
        rect = layout.item_bar_slot_probe_rect(index)
        if self._bag_slot_occupied(frame, rect):
            return True
        if self._bag_slot_empty(frame, rect):
            return False
        hud = self._hud_item_bar_rect(frame, index)
        return hud is not None and self._bag_slot_occupied(frame, hud)

    def _public_bag_empty_slot(
        self, frame: Frame, layout: BagLayout
    ) -> tuple[int, int, MatchResult] | None:
        """Spec step 6: first verified PUBLIC_BAG_EMPTY_SLOT in fill order."""
        for row, col in layout.public_slots():
            rect = layout.public_slot_rect(row, col)
            if not self._bag_slot_empty(frame, rect):
                continue
            center = layout.public_slot_center(row, col)
            if center is None:
                continue
            x, y = center
            return (
                row,
                col,
                MatchResult(
                    f"public_bag_slot_{row}_{col}",
                    1.0,
                    x,
                    y,
                    0,
                    0,
                    frame.left + x,
                    frame.top + y,
                ),
            )
        return None

    def _public_bag_empty_personal_slot(
        self, frame: Frame, layout: BagLayout
    ) -> tuple[int, int, MatchResult] | None:
        """First verified empty personal-grid cell for the short item-bar stash."""
        for row, col in layout.public_slots():
            rect = layout.personal_slot_rect(row, col)
            if not self._bag_slot_empty(frame, rect):
                continue
            center = layout.personal_slot_center(row, col)
            if center is None:
                continue
            x, y = center
            return (
                row,
                col,
                MatchResult(
                    f"personal_bag_slot_{row}_{col}",
                    1.0,
                    x,
                    y,
                    0,
                    0,
                    frame.left + x,
                    frame.top + y,
                ),
            )
        return None

    def _pickup_bag_has_space(self, frame: Frame) -> bool:
        """Allow range pickup only with one freshly verified bag cell.

        The item bar being full alone is not permission to press Z: if the
        bag page or either grid cannot be read, leave the ground item alone.
        """
        layout = self._bag_layout(frame)
        if layout is None:
            return False
        return (
            self._public_bag_empty_slot(frame, layout) is not None
            or self._public_bag_empty_personal_slot(frame, layout) is not None
        )

    def _public_bag_source(self, frame: Frame, layout: BagLayout) -> dict | None:
        """Spec step 1: fresh-confirm the next thing to hand to the team.

        In passenger modes every occupied item-bar slot 2–6 is team loot
        (hero cards, gear, pills, talismans). We do not filter by template.
        Drain the personal grid first, then the item bar. A slot that is
        neither clearly empty nor occupied is skipped, not guessed.
        """
        for row, col in layout.public_slots():
            if self._public_bag_source_exhausted(f"personal_{row}_{col}"):
                continue
            if not self._bag_slot_occupied(frame, layout.personal_slot_rect(row, col)):
                continue
            center = layout.personal_slot_center(row, col)
            if center is None:
                continue
            x, y = center
            return {
                "kind": "personal",
                "slot_index": -1,
                "cell": (row, col),
                "source_id": f"personal_{row}_{col}",
                "hit": MatchResult(
                    f"personal_bag_slot_{row}_{col}",
                    1.0,
                    x,
                    y,
                    0,
                    0,
                    frame.left + x,
                    frame.top + y,
                ),
            }
        # 界面装备栏是 1..6，而这里用 0-based index。1 号（index 0）是固定
        # 自身装备，不能移动；从界面的 2..6 开始扫描，避免先右键自己的武器。
        for index in range(1, ITEM_BAR_SLOTS):
            if self._public_bag_source_exhausted(f"item_bar_{index}"):
                continue
            if not self._item_bar_slot_occupied(frame, layout, index):
                continue
            center = layout.item_bar_slot_center(index)
            if center is None:
                continue
            x, y = center
            return {
                "kind": "item_bar",
                "slot_index": index,
                "cell": None,
                "source_id": f"item_bar_{index}",
                "hit": MatchResult(
                    f"item_bar_slot_{index}", 1.0, x, y, 0, 0, frame.left + x, frame.top + y
                ),
            }
        return None

    _PUBLIC_BAG_SOURCE_MAX_FAILURES = 2

    def _public_bag_source_exhausted(self, source_id: str) -> bool:
        return self._public_bag_failed_sources.get(source_id, 0) >= self._PUBLIC_BAG_SOURCE_MAX_FAILURES

    def _public_bag_note_source_failure(self, source_id: str) -> None:
        """Retire an independently verified-but-unmovable source for this round."""
        if not source_id:
            return
        count = self._public_bag_failed_sources.get(source_id, 0) + 1
        self._public_bag_failed_sources[source_id] = count
        if count >= self._PUBLIC_BAG_SOURCE_MAX_FAILURES:
            print(f"[L1] 公共背包：{source_id} 连续 {count} 次搬不动，本局跳过该格")

    def _public_bag_source_rect(
        self, layout: BagLayout, fsm: PublicBagFSM
    ) -> tuple[int, int, int, int] | None:
        if fsm.source_kind == "item_bar":
            return layout.item_bar_slot_probe_rect(fsm.source_slot)
        if fsm.source_kind == "personal" and fsm.source_cell is not None:
            return layout.personal_slot_rect(*fsm.source_cell)
        return None

    def _public_bag_left_click_allowed(
        self, layout: BagLayout, hit: MatchResult, *, target_kind: str = "public"
    ) -> bool:
        """Left click: empty personal cell for stash, or public cell for deposit.

        Occupied personal cells and the 物品栏 stay right-click-only.
        """
        if target_kind == "personal":
            return layout.inside_personal_grid(hit.x, hit.y) and not (
                layout.item_bar_slot_index(hit.x, hit.y) is not None
            )
        if layout.inside_personal_surface(hit.x, hit.y):
            return False
        return layout.inside_public_grid(hit.x, hit.y)

    def _public_bag_deposit_confirmed(
        self, frame: Frame, layout: BagLayout | None
    ) -> bool | None:
        """Spec step 8.  ``None`` = undecided, keep waiting inside the deadline.

        A transfer is only confirmed when both ends moved: the public target
        stopped being empty *and* the source slot is now empty.  Requiring both
        is what separates a real transfer from a repaint or a cursor artefact.
        """
        fsm = self._public_bag_fsm
        target = fsm.target_slot
        if layout is None or target is None:
            return None
        row, col = target
        target_rect = (
            layout.personal_slot_rect(row, col)
            if fsm.target_kind == "personal"
            else layout.public_slot_rect(row, col)
        )
        if self._bag_slot_empty(frame, target_rect):
            return None
        source_rect = self._public_bag_source_rect(layout, fsm)
        if source_rect is None:
            return None
        if self._bag_slot_empty(frame, source_rect):
            return True
        if self._bag_slot_occupied(frame, source_rect):
            baseline = self._public_bag_deposit_before
            current = self._bag_slot_signature(frame, source_rect)
            if baseline is not None and current is not None:
                # A stack that only lost some of its count still counts as a
                # move; an unchanged icon does not.
                if abs(current[1] - int(baseline[1])) >= 20:
                    return True
        return None

    def _public_bag_close_page(self, frame: Frame, fsm: PublicBagFSM, now: float) -> LoopAction:
        if self._toggle_bag_page(frame, "PublicBackpackClose"):
            self._public_bag_fsm = fsm.request_close(now)
            self._public_bag_empty_since = None
            print("[L1] 公共背包：无待搬物品，关闭背包页")
        return LoopAction.Continue

    def _public_bag_close_when_empty(
        self, frame: Frame, fsm: PublicBagFSM, now: float
    ) -> LoopAction:
        """Wait a beat after open/stash before closing — occupancy lags a tick."""
        if self._public_bag_empty_since is None:
            self._public_bag_empty_since = now
            return LoopAction.Continue
        if now - self._public_bag_empty_since < self._PUBLIC_BAG_EMPTY_CLOSE_S:
            return LoopAction.Continue
        return self._public_bag_close_page(frame, fsm, now)

    def _maybe_public_backpack_deposit(self, frame: Frame, now: float) -> LoopAction | None:
        """PUBLIC_BACKPACK_DEPOSIT: stash item-bar → personal, then personal → public, then close."""
        if not self._passenger_mode():
            return None
        if self._pending_action is not None and time.time() < self._pending_action.deadline:
            return None
        layout = self._bag_layout(frame)
        bag_visible = layout is not None
        if layout is not None:
            # Remember movable items left in the personal grid (a lease
            # expiry, an aborted hop): they justify the next open even with
            # an empty 物品栏.
            self._public_bag_personal_leftover = any(
                not self._public_bag_source_exhausted(f"personal_{row}_{col}")
                and self._bag_slot_occupied(frame, layout.personal_slot_rect(row, col))
                for row, col in layout.public_slots()
            )

        previous = self._public_bag_fsm
        deposit_confirmed = (
            self._public_bag_deposit_confirmed(frame, layout)
            if previous.phase is PublicBagPhase.DEPOSIT_REQUESTED
            else None
        )
        fsm = previous.observe(now, bag_visible=bag_visible, deposit_confirmed=deposit_confirmed)
        if previous.phase is PublicBagPhase.DEPOSIT_REQUESTED and fsm.phase is not previous.phase:
            self._tick_post_confirm = fsm.deposits > previous.deposits
            if fsm.deposits > previous.deposits:
                hop = "个人格" if previous.target_kind == "personal" else "公共格"
                print(f"[L1] 公共背包：第 {fsm.deposits} 件已确认进{hop}")
        if fsm.phase is PublicBagPhase.ABORTED and previous.phase is not PublicBagPhase.ABORTED:
            print(f"[L1] 公共背包流转中止：{fsm.abort_reason}")
            if fsm.abort_reason.startswith("deposit_postcondition") or fsm.abort_reason in {
                # A right-clicked item that never got placed is a failed move
                # of that source too; without counting it the same cell was
                # retried forever with the page held open.
                "deposit_slot_timeout",
                "bag_page_lost_while_carrying",
            }:
                self._public_bag_note_source_failure(previous.source_id)
            if fsm.abort_reason == "bag_page_lost" and previous.phase is PublicBagPhase.BAG_VISIBLE:
                # We did not ask for the close: the player shut the page.
                self._public_bag_next_at = max(
                    self._public_bag_next_at, now + self._PUBLIC_BAG_USER_CLOSE_COOLDOWN_S
                )
                print(
                    f"[L1] 公共背包：背包页被手动关闭，{self._PUBLIC_BAG_USER_CLOSE_COOLDOWN_S:.0f}s 内不再自动打开"
                )
        self._public_bag_open_since = (
            (self._public_bag_open_since or now) if bag_visible else None
        )
        self._public_bag_fsm = fsm

        if fsm.phase is PublicBagPhase.IDLE:
            if bag_visible and fsm.can_adopt_open_page():
                if now < self._public_bag_next_at:
                    # Inside a reopen cooldown (lease expiry / manual close):
                    # an open page is not ours to work and not ours to close.
                    return None
                if layout is not None and self._public_bag_source(frame, layout) is not None:
                    self._public_bag_empty_since = None
                    self._public_bag_fsm = fsm.confirm_bag_visible(now)
                    return LoopAction.Continue
                return self._public_bag_close_when_empty(frame, fsm, now)
            if not fsm.can_start(now) or now < self._public_bag_next_at:
                return None
            if not self._public_bag_surface_ok(frame):
                return None
            if (
                self._hud_item_bar_state(frame) == "empty"
                and not self._public_bag_personal_leftover
            ):
                # Open the bag only for something to hand over: an item in
                # 物品栏 2-6 (or one we left in the personal grid).  Live
                # 2026-09-12 it opened and closed empty after every pickup.
                return None
            if self._open_bag_page(frame):
                self._public_bag_fsm = fsm.request_bag_open(now)
                self._public_bag_next_at = now + 1.0
                self._public_bag_empty_since = None
                print("[L1] 公共背包：请求打开背包页")
                return LoopAction.Continue
            return None

        if fsm.phase is PublicBagPhase.BAG_OPEN_REQUESTED:
            return LoopAction.Continue

        if fsm.phase is PublicBagPhase.BAG_VISIBLE:
            if layout is None:
                return LoopAction.Continue
            open_since = self._public_bag_open_since
            if open_since is not None and now - open_since >= self._PUBLIC_BAG_MAX_OPEN_S:
                # Nothing is on the cursor in BAG_VISIBLE, so closing is safe.
                # Whatever is left waits for the next episode.
                self._public_bag_next_at = max(
                    self._public_bag_next_at, now + self._PUBLIC_BAG_REOPEN_COOLDOWN_S
                )
                print(
                    f"[L1] 公共背包：本次已打开 {now - open_since:.0f}s，先关闭背包页，"
                    f"{self._PUBLIC_BAG_REOPEN_COOLDOWN_S:.0f}s 后再处理剩余物品"
                )
                return self._public_bag_close_page(frame, fsm, now)
            source = self._public_bag_source(frame, layout)
            if source is None:
                return self._public_bag_close_when_empty(frame, fsm, now)
            self._public_bag_empty_since = None
            if (
                self._public_bag_empty_slot(frame, layout) is None
                and self._public_bag_empty_personal_slot(frame, layout) is None
            ):
                self._public_bag_fsm = fsm.abort("public_bag_full_or_unverified", now)
                return LoopAction.Continue
            if self.act_right_click(source["hit"], "PublicBackpackDepositRightClick"):
                source_rect = (
                    layout.item_bar_slot_probe_rect(source["slot_index"])
                    if source["kind"] == "item_bar"
                    else layout.personal_slot_rect(*source["cell"])
                )
                self._public_bag_deposit_before = self._bag_slot_signature(frame, source_rect)
                self._public_bag_fsm = fsm.select_source(
                    source["source_id"],
                    now,
                    kind=source["kind"],
                    slot_index=source["slot_index"],
                    cell=source["cell"],
                )
                print(f"[L1] 公共背包：右键取出 {source['source_id']}")
            else:
                self._public_bag_note_source_failure(source["source_id"])
            return LoopAction.Continue

        if fsm.phase is PublicBagPhase.SOURCE_SELECTED:
            if layout is None:
                return LoopAction.Continue
            target_kind = "public"
            slot = None
            if fsm.source_kind == "item_bar":
                slot = self._public_bag_empty_personal_slot(frame, layout)
                if slot is not None:
                    target_kind = "personal"
            if slot is None:
                slot = self._public_bag_empty_slot(frame, layout)
                target_kind = "public"
            if slot is None:
                self._public_bag_fsm = fsm.abort("public_bag_full_or_unverified", now)
                return LoopAction.Continue
            row, col, hit = slot
            if not self._public_bag_left_click_allowed(layout, hit, target_kind=target_kind):
                self._public_bag_fsm = fsm.abort("deposit_target_outside_public_bag", now)
                return LoopAction.Continue
            reason = "PublicBackpackStash" if target_kind == "personal" else "PublicBackpackDeposit"
            if self.act_click(hit, reason):
                self._public_bag_fsm = fsm.request_deposit(
                    row, col, now, target_kind=target_kind
                )
                hop = "个人格" if target_kind == "personal" else "公共格"
                print(f"[L1] 公共背包：左键放入{hop} ({row},{col})")
            return LoopAction.Continue

        if fsm.phase is PublicBagPhase.DEPOSIT_REQUESTED:
            return LoopAction.Continue

        if fsm.phase is PublicBagPhase.CLOSE_REQUESTED:
            return LoopAction.Continue

        return LoopAction.Continue

    def _public_backpack_deposit_postcondition(
        self, before_frame: Frame | None, frame: Frame
    ) -> dict:
        """Business postcondition for the live harness (never "click succeeded")."""
        result: dict[str, object] = {
            "observed": False,
            "state": "public_bag_surface_not_confirmed",
            "kind": "public_backpack_deposit",
        }
        layout = self._bag_layout(frame) if frame is not None else None
        if layout is None:
            return result
        fsm = self._public_bag_fsm
        target = fsm.target_slot
        result["deposits"] = fsm.deposits
        result["phase"] = fsm.phase.name
        if target is None:
            result["state"] = "no_deposit_requested"
            return result
        row, col = target
        result["target_slot"] = [row, col]
        result["target_kind"] = fsm.target_kind
        target_rect = (
            layout.personal_slot_rect(row, col)
            if fsm.target_kind == "personal"
            else layout.public_slot_rect(row, col)
        )
        if before_frame is not None:
            before_layout = self._bag_layout(before_frame)
            if before_layout is not None and not self._bag_slot_empty(
                before_frame, (
                    before_layout.personal_slot_rect(row, col)
                    if fsm.target_kind == "personal"
                    else before_layout.public_slot_rect(row, col)
                )
            ):
                result["state"] = "target_slot_was_not_empty_before"
                return result
        if self._bag_slot_empty(frame, target_rect):
            result["state"] = "target_slot_still_empty"
            return result

        source_rect = self._public_bag_source_rect(layout, fsm)
        if source_rect is None:
            result["state"] = "source_slot_not_identified"
            return result
        source_empty = self._bag_slot_empty(frame, source_rect)
        if source_empty:
            result["source_state"] = "empty"
        else:
            baseline = getattr(self, "_public_bag_deposit_before", None)
            if before_frame is not None and baseline is None:
                before_layout = self._bag_layout(before_frame)
                if before_layout is not None:
                    before_src_rect = self._public_bag_source_rect(before_layout, fsm)
                    if before_src_rect is not None:
                        baseline = self._bag_slot_signature(before_frame, before_src_rect)
            current = self._bag_slot_signature(frame, source_rect)
            if baseline is not None and current is not None and abs(current[1] - int(baseline[1])) >= 20:
                result["source_state"] = "decreased"
            else:
                result["state"] = "source_slot_not_vacated_or_decreased"
                return result

        result["observed"] = True
        result["state"] = "confirmed"
        return result

    @staticmethod
    def _merchant_refresh_hit(frame: Frame) -> MatchResult:
        """Click the recycle control to the right of the 5-slot strip, not the level badge."""
        # 1600x900 live: recycle icon with remaining refreshes sits at ~0.911, 0.702.
        # 0.935,0.715 was grass to the right of that icon and never mutated stock.
        x, y = int(frame.width * 0.911), int(frame.height * 0.702)
        return MatchResult("black_merchant_refresh", 1.0, x, y, 0, 0, frame.left + x, frame.top + y)

    @staticmethod
    def _merchant_refresh_available(frame: Frame) -> bool:
        if frame.bgr is None or frame.width <= 0 or frame.height <= 0:
            return False
        x0, y0 = int(frame.width * 0.88), int(frame.height * 0.66)
        x1, y1 = int(frame.width * 0.94), int(frame.height * 0.73)
        roi = frame.bgr[y0:y1, x0:x1]
        if roi.size == 0:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        gold = (
            (hsv[:, :, 0] >= 10)
            & (hsv[:, :, 0] <= 45)
            & (hsv[:, :, 1] > 60)
            & (hsv[:, :, 2] > 80)
        )
        scale = min(frame.width / 1600.0, frame.height / 900.0)
        min_gold = max(10, int(80 * scale * scale))
        return int(gold.sum()) >= min_gold

    @staticmethod
    def _merchant_slot_index(frame: Frame, hit: MatchResult) -> int:
        """Map a product match to the nearest fixed merchant slot center."""
        match_cx = hit.x + hit.w / 2.0
        return min(
            range(5),
            key=lambda index: abs(
                match_cx
                - frame.width * MerchantScanner.get_slot_center_ratio(index)[0]
            ),
        )

    @staticmethod
    def _normalize_merchant_discount(text: str) -> str:
        """Normalize only observed OCR confusions; keep unknown text fail-closed."""
        compact = re.sub(r"\s+", "", text or "")
        # These aliases are from real merchant captures.  Do not turn generic
        # substrings such as ``2S`` into a discount: that caused full-price
        # items to become purchase candidates in earlier runs.
        for raw, normalized in (
            ("12折", "2折"),
            ("15折", "5折"),
            ("A2", "2折"),
            ("A２", "2折"),
        ):
            if raw in compact:
                compact = compact.replace(raw, normalized)
        return compact

    def _merchant_discount_slots(
        self,
        frame: Frame,
        fingerprint: str,
    ) -> list[MerchantSlotItem]:
        """Read only explicit 2/5-fold labels through the existing OCR sidecar."""
        client = getattr(self, "_ocr_client", None)
        if client is None or not bool(getattr(client, "is_available", False)):
            return []
        # Live 1600x900 evidence: the discount badge occupies only the small
        # upper-left price ribbon.  Sending the whole icon to OCR produced
        # i/bi instead of 2折/5折 and the old 64px split was shifted left.
        badge_panel = (1150 / 1600, 617 / 900, 1410 / 1600, 640 / 900)
        panel_bbox = self._normalized_bbox(frame, badge_panel)
        px0, py0, px1, py1 = panel_bbox
        badge_pixels = frame.bgr[py0:py1, px0:px1]
        badge_fingerprint = hashlib.md5(badge_pixels.tobytes()).hexdigest()
        ocr_fingerprint = f"{fingerprint}:{badge_fingerprint}"
        panel_id = f"merchant:{ocr_fingerprint}"
        items: list[MerchantSlotItem] = []
        for slot_index in range(5):
            slot_roi = (
                (1150 + 55 * slot_index) / 1600,
                617 / 900,
                (1190 + 55 * slot_index) / 1600,
                640 / 900,
            )
            bbox = self._normalized_bbox(frame, slot_roi)
            try:
                response = client.shadow_predict(
                    frame,
                    panel_id,
                    # Keep the existing worker kind contract.  Discount
                    # detection uses only its raw OCR text and never asks the
                    # lexicon to guess an item name.
                    {"index": slot_index, "bbox": bbox},
                    fingerprint=ocr_fingerprint,
                    panel_bbox=panel_bbox,
                )
            except (AttributeError, OSError, TypeError, ValueError):
                continue
            if str(getattr(response, "status", "ok")) != "ok":
                continue
            candidate = response.candidates[0].name if response.candidates else ""
            text = self._normalize_merchant_discount(
                f"{response.raw_text or ''}{candidate}"
            )
            label = next(
                (
                    keyword
                    for keyword in DISCOUNT_KEYWORDS
                    if re.search(
                        rf"(?<![0-9一二三四五六七八九十]){re.escape(keyword)}"
                        rf"(?![0-9一二三四五六七八九十])",
                        text,
                    )
                ),
                None,
            )
            if label is not None:
                items.append(
                    MerchantSlotItem(
                        slot_index=slot_index,
                        center_ratio=MerchantScanner.get_slot_center_ratio(slot_index),
                        item_type="discount",
                        label=label,
                        score=float(getattr(response, "rec_score", 0.0) or 0.0),
                    )
                )
        return items

    def _hud_counter(
        self,
        frame: Frame,
        roi: tuple[float, float, float, float],
        key: str,
        *,
        min_score: float | None = None,
        max_value: int | None = None,
    ) -> int | None:
        """OCR one integer from a HUD counter/badge; None when not trusted."""
        if frame.bgr is None or frame.bgr.size == 0:
            return None
        bbox = self._normalized_bbox(frame, roi)
        x0, y0, x1, y1 = bbox
        crop = frame.bgr[y0:y1, x0:x1]
        if crop.size == 0:
            return None
        fingerprint = hashlib.md5(crop.tobytes()).hexdigest()
        cache = getattr(self, "_hud_counter_cache", None)
        if cache is None:
            cache = self._hud_counter_cache = {}
        hit = cache.get(key)
        if hit is not None and hit[0] == fingerprint:
            return hit[1]
        cache[key] = (fingerprint, None)
        client = getattr(self, "_ocr_client", None)
        if client is None or not bool(getattr(client, "is_available", False)):
            return None
        try:
            response = client.shadow_predict(
                frame,
                f"hud-{key}:{fingerprint}",
                {"index": 0, "bbox": bbox, "kind": "counter"},
                fingerprint=fingerprint,
                panel_bbox=bbox,
            )
        except (AttributeError, OSError, TypeError, ValueError):
            return None
        if str(getattr(response, "status", "")) != "ok":
            return None
        floor = self._MERCHANT_KILL_BALANCE_MIN_SCORE if min_score is None else min_score
        if float(getattr(response, "rec_score", 0.0) or 0.0) < floor:
            return None
        raw = str(getattr(response, "raw_text", "") or "")
        if not raw:
            candidates = tuple(getattr(response, "candidates", ()) or ())
            raw = str(getattr(candidates[0], "name", "") or "") if candidates else ""
        values = re.findall(r"(?<!\d)(\d{1,6})(?!\d)", raw)
        if len(values) != 1:
            return None
        value = int(values[0])
        if max_value is not None and value > max_value:
            return None
        cache[key] = (fingerprint, value)
        return value

    # Yellow badge digits on the hero command card (live 000229 f0200: G 技能
    # "13" at (1464,781), V 宝物 "2" at (1407,719) @1600x900).  No badge =
    # nothing pending.  OCR reads the digits right but with 0.2-0.97 scores
    # (the sparkling border also reads as "-"), hence the lower floor.
    _SKILL_BADGE_ROI = (1448 / 1600, 768 / 900, 1482 / 1600, 794 / 900)
    _TREASURE_BADGE_ROI = (1394 / 1600, 707 / 900, 1422 / 1600, 731 / 900)
    _BADGE_MIN_SCORE = 0.6

    # Icon bodies that prove the button itself is on screen (a selected
    # monster replaces the command card; an open panel only dims it).
    _SKILL_ICON_ROI = (1432 / 1600, 787 / 900, 1472 / 1600, 810 / 900)
    _TREASURE_ICON_ROI = (1372 / 1600, 700 / 900, 1402 / 1600, 745 / 900)

    def _hud_button_visible(self, frame: Frame, key: str) -> bool:
        if key == "skill_badge":
            x0, y0, x1, y1 = self._normalized_bbox(frame, self._SKILL_ICON_ROI)
            hsv = cv2.cvtColor(frame.bgr[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
            hit = ((hsv[:, :, 0] < 8) | (hsv[:, :, 0] > 172)) & (hsv[:, :, 1] > 150) & (hsv[:, :, 2] > 110)
        else:
            x0, y0, x1, y1 = self._normalized_bbox(frame, self._TREASURE_ICON_ROI)
            hsv = cv2.cvtColor(frame.bgr[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
            hit = (hsv[:, :, 0] > 70) & (hsv[:, :, 0] < 100) & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 80)
        return int(hit.sum()) >= 60

    def _hud_badge(self, frame: Frame, roi: tuple[float, float, float, float], key: str) -> int | None:
        if frame.bgr is None or frame.bgr.size == 0:
            return None
        if not self._hud_button_visible(frame, key):
            return None
        x0, y0, x1, y1 = self._normalized_bbox(frame, roi)
        crop = frame.bgr[y0:y1, x0:x1]
        if crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        yellow = (hsv[:, :, 0] > 15) & (hsv[:, :, 0] < 40) & (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 100)
        if int(yellow.sum()) < 6:
            return 0
        return self._hud_counter(frame, roi, key, min_score=self._BADGE_MIN_SCORE, max_value=99)

    def _hud_skill_points(self, frame: Frame) -> int | None:
        """Unspent skill picks shown on the G 技能 button (None = unreadable)."""
        return self._hud_badge(frame, self._SKILL_BADGE_ROI, "skill_badge")

    def _hud_treasure_pending(self, frame: Frame) -> int | None:
        """Pending treasure picks shown on the V 宝物 button (None = unreadable)."""
        return self._hud_badge(frame, self._TREASURE_BADGE_ROI, "treasure_badge")

    def _merchant_kill_balance(self, frame: Frame) -> int | None:
        """Read the top-right skull counter used by black-merchant prices.

        The counter is deliberately read from the HUD rather than inferred from
        elapsed time or a configured kill target.  A malformed/low-confidence
        OCR result has no spending authority.
        """
        if frame.bgr is None or frame.bgr.size == 0:
            return None
        bbox = self._normalized_bbox(frame, self._MERCHANT_KILL_BALANCE_ROI)
        x0, y0, x1, y1 = bbox
        crop = frame.bgr[y0:y1, x0:x1]
        if crop.size == 0:
            return None
        fingerprint = hashlib.md5(crop.tobytes()).hexdigest()
        cached = getattr(self, "_merchant_kill_balance_value", None)
        if (
            fingerprint == getattr(self, "_merchant_kill_balance_fingerprint", None)
            and cached is not None
        ):
            return cached

        self._merchant_kill_balance_fingerprint = fingerprint
        self._merchant_kill_balance_value = None
        client = getattr(self, "_ocr_client", None)
        if client is None or not bool(getattr(client, "is_available", False)):
            return None
        try:
            response = client.shadow_predict(
                frame,
                f"merchant-kill:{fingerprint}",
                {"index": 0, "bbox": bbox, "kind": "counter"},
                fingerprint=fingerprint,
                panel_bbox=bbox,
            )
        except (AttributeError, OSError, TypeError, ValueError):
            return None
        if str(getattr(response, "status", "")) != "ok":
            return None
        if float(getattr(response, "rec_score", 0.0) or 0.0) < self._MERCHANT_KILL_BALANCE_MIN_SCORE:
            return None
        raw = str(getattr(response, "raw_text", "") or "")
        if not raw:
            candidates = tuple(getattr(response, "candidates", ()) or ())
            raw = str(getattr(candidates[0], "name", "") or "") if candidates else ""
        values = re.findall(r"(?<!\d)(\d{1,6})(?!\d)", raw)
        if len(values) != 1:
            return None
        self._merchant_kill_balance_value = int(values[0])
        return self._merchant_kill_balance_value

    def _merchant_kill_budget_allows(
        self, frame: Frame, now: float, required: int, action: str
    ) -> bool:
        """Grant a merchant spend when the balance proves it, with solo fallback."""
        balance = self._merchant_kill_balance(frame)
        if balance is not None and balance >= required:
            self._merchant_budget_retry_at = 0.0
            return True
        if balance is None and not self._passenger_mode():
            # Solo historically used verified merchant controls without a
            # kill-counter OCR gate.  Do not turn an unreadable HUD into a
            # permanent merchant starvation loop; hitch remains fail-closed.
            print(f"[L1] 黑商{action}杀敌数不可读，单人按已验证控件继续")
            return True
        self._merchant_budget_retry_at = max(
            float(getattr(self, "_merchant_budget_retry_at", 0.0) or 0.0),
            now + self._MERCHANT_BUDGET_RECHECK_S,
        )
        if balance is None:
            print(f"[L1] 黑商{action}未拿到可信杀敌数，零输入并稍后复核")
        else:
            print(f"[L1] 黑商{action}需要 {required} 杀敌数，当前 {balance}，本轮跳过")
        return False

    def _maybe_black_merchant(self, frame: Frame, allow_reroll: bool = True) -> LoopAction | None:
        """Buy only mode-authorized merchant stock, then use the existing refresh path."""
        now = time.time()
        present = self._black_merchant_present(frame)
        cards_present = self._black_merchant_cards_present(frame)
        refresh_available = self._merchant_refresh_available(frame)
        detected_slots: list[MerchantSlotItem] = []
        roi = (0.70, 0.66, 0.90, 0.76)
        if present:
            pill = self.find(
                frame,
                ["danGif"],
                threshold=0.90,
                scales=(0.5, 0.6, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5),
                roi=roi,
            )
            if self._in_merchant_strip(frame, pill):
                slot_idx = self._merchant_slot_index(frame, pill)
                detected_slots.append(
                    MerchantSlotItem(
                        slot_index=slot_idx,
                        center_ratio=MerchantScanner.get_slot_center_ratio(slot_idx),
                        item_type="devour_pill",
                        label="danGif",
                    )
                )

            wood = self.find(
                frame,
                ["merchant_wood"],
                threshold=0.95,
                scales=(0.9, 1.0, 1.1),
                roi=roi,
            )
            if self._in_merchant_strip(frame, wood):
                slot_idx = self._merchant_slot_index(frame, wood)
                detected_slots.append(
                    MerchantSlotItem(
                        slot_index=slot_idx,
                        center_ratio=MerchantScanner.get_slot_center_ratio(slot_idx),
                        item_type="wood",
                        label="merchant_wood",
                    )
                )
        fingerprint = self._merchant_fingerprint(frame, detected_slots) if present else ""
        # OCR discount slots are part of the stock identity.  Resolve them
        # before the FSM observes the frame; otherwise a successful 2/5-fold
        # purchase leaves the fingerprint unchanged and the FSM evicts the
        # encounter on its verification deadline.
        if cards_present:
            discounts = self._merchant_discount_slots(frame, fingerprint)
            detected_slots.extend(discounts)
            if discounts:
                fingerprint = self._merchant_fingerprint(frame, detected_slots)
        previous_fsm = self._merchant_fsm
        self._merchant_fsm = previous_fsm.observe(present, fingerprint, now)
        if (
            self._passenger_mode()
            and previous_fsm.phase is MerchantPhase.VERIFYING
            and previous_fsm.purchases > 0
            and fingerprint != previous_fsm.pending_fingerprint
        ):
            print("[L1] 蹭车黑商吞噬丹购买已确认，转宝物神符")
            self._advance_l1_cycle("merchant")
            return LoopAction.Continue
        if not present or self._merchant_fsm.phase is MerchantPhase.EVICTED:
            return None
        merchant_enabled_flag = getattr(self.settings, "merchant_enabled", True)
        if merchant_enabled_flag is False:
            return None

        # If fsm is currently waiting or leased, return Continue to avoid falling through
        if self._merchant_fsm.phase is MerchantPhase.VERIFYING:
            return LoopAction.Continue
        if self._merchant_next_at > 0 and now < self._merchant_next_at:
            return LoopAction.Continue

        scanner = MerchantScanner(
            attr_routes=list(getattr(self.settings, "attributes", []) or []),
            focus_skills=list(getattr(self.settings, "skills", []) or []),
            focus_bonds=list(getattr(self.settings, "bonds", []) or []),
            auto_refresh=True,
        )
        retry_s = max(1.2, float(self.settings.ui_action_interval_s))

        # Buying a merchant pill is independent from consuming it in the
        # inventory. The latter keeps its own bond-bar guard in
        # _maybe_use_inventory_item; do not hide merchant recognition behind it.
        ranked = scanner.rank_purchases(detected_slots, solo=not self._passenger_mode())
        # 0 means no script cap: keep refreshing while the recycle control is up.
        reroll_cap = int(getattr(self.settings, "merchant_max_rerolls", 0)) or 20

        if ranked and self._merchant_fsm.can_purchase(5):
            target_item = ranked[0]
            cost = (
                self._MERCHANT_WOOD_KILL_COST
                if target_item.item_type == "wood"
                else self._MERCHANT_DEVOUR_PILL_KILL_COST
            )
            item_label = {
                "devour_pill": "吞噬丹",
                "wood": "木材",
                "discount": "折扣商品",
            }.get(target_item.item_type, target_item.item_type)
            if not self._merchant_kill_budget_allows(
                frame,
                now,
                cost,
                f"{item_label}购买",
            ):
                return None
            hit = self._hud_button_hit(
                frame,
                f"black_merchant_slot_{target_item.slot_index}",
                target_item.center_ratio,
            )
            action_name = f"BlackMerchant-{target_item.item_type}"
            if target_item.item_type == "devour_pill":
                action_name = "BlackMerchant-swallow_pill"
            elif target_item.item_type == "wood":
                action_name = "BlackMerchant-wood"
            elif target_item.item_type == "discount":
                action_name = "BlackMerchant-discount"
            click_res = self.act_click(hit, action_name)
            if getattr(click_res, "success", bool(click_res)):
                self._merchant_fsm = self._merchant_fsm.begin_purchase(now, timeout_s=retry_s)
                self._merchant_next_at = now + retry_s
            return LoopAction.Continue

        if not allow_reroll:
            return None

        # Nothing left to buy, or purchase budget exhausted: refresh this
        # encounter's remaining stock. Empty strip uses the same path.
        if allow_reroll and refresh_available and self._merchant_fsm.can_reroll(reroll_cap):
            if not self._merchant_kill_budget_allows(
                frame,
                now,
                self._MERCHANT_REFRESH_WITH_PILL_BUDGET,
                "刷新（含后续吞噬丹预留）",
            ):
                return None
            refresh = self._merchant_refresh_hit(frame)
            click_res = self.act_click(refresh, "BlackMerchant-refresh")
            if getattr(click_res, "success", bool(click_res)):
                self._merchant_fsm = self._merchant_fsm.begin_reroll(
                    now, timeout_s=retry_s, cap=reroll_cap
                )
                self._merchant_next_at = now + retry_s
            return LoopAction.Continue
        if self._merchant_fsm.rerolls >= reroll_cap and not ranked:
            print(f"[L1] 黑商刷新预算已用完（{self._merchant_fsm.rerolls}/{reroll_cap}），推进轮换下一步")
            self._advance_l1_cycle("merchant")
            if self._passenger_mode():
                return LoopAction.Continue
            return None
        if (
            self._merchant_fsm.phase is MerchantPhase.READY
            and not ranked
            and (not refresh_available or not self._merchant_fsm.can_reroll(reroll_cap))
        ):
            self._advance_l1_cycle("merchant")
            return None
        if self._passenger_mode():
            # 蹭车只拿吞噬丹；已识别到的木头/折扣不是购买授权，
            # 且没有可刷新控件时必须把控制权交给宝物步骤。
            return None
        return LoopAction.Continue if (present and (detected_slots or ranked or refresh_available)) else None

    def _maybe_opportunistic_merchant(self, frame: Frame, now: float) -> LoopAction | None:
        """HUD_ONLY opportunistic single high-value merchant buy without rerolls."""
        if getattr(self.settings, "merchant_enabled", True) is False:
            return None
        if now < getattr(self, "_opportunistic_merchant_next_at", 0.0):
            return None
        if not self._black_merchant_present(frame):
            return None
        action = self._maybe_black_merchant(frame, allow_reroll=False)
        if action is not None:
            self._opportunistic_merchant_next_at = now + 8.0
            return action
        return None

    def _maybe_opportunistic_hero_card(self, frame: Frame, now: float) -> LoopAction | None:
        """HUD_ONLY opportunistic hero card usage during core development."""
        if now < getattr(self, "_opportunistic_hero_card_next_at", 0.0):
            return None
        # 严格复用现有英雄卡业务门禁：未确认进化完成前（_evolve_ok_this_cycle=True）绝对零输入；
        # 不能用“当前没识别到 evolve button”代替“进化已成功”
        if not getattr(self, "_evolve_ok_this_cycle", False):
            return None
        if self._has_evolve_button(frame):
            return None
        if getattr(self, "_evolve_awaiting_hero_pick", False) or getattr(self, "_evolve_feedback_pending", False):
            return None
        inventory_roi = (0.65, 0.78, 0.82, 0.98)
        hero_card = self.find(
            frame,
            ["hero_card_item"],
            threshold=0.65,
            roi=inventory_roi,
            scales=(0.8, 0.9, 1.0, 1.1, 1.2),
        )
        if hero_card is not None:
            self._opportunistic_hero_card_next_at = now + 4.0
            if self.act_click(hero_card, "Opportunistic-hero-card"):
                print(f"[L1] 核心发育期机会使用英雄卡 @ {hero_card.center}")
                self._pending_action = PendingAction(
                    kind="WAIT_HERO_CHOICE",
                    target_id="hero_card_item",
                    deadline=now + 3.0,
                    verifier=lambda f: bool(self._find_evolution_choice(f, anchor=self._selection_anchor(f)) is not None),
                )
                self._evolve_awaiting_hero_pick = True
                self._evolve_awaiting_hero_pick_at = now
                return LoopAction.Continue
        return None

    def _find_compact_skill_choice(self, frame: Frame) -> MatchResult | None:
        """Find a configured skill in the live bottom-right G quick panel."""
        preferred = [v.strip() for v in self.settings.skills if v and v.strip()]
        if not preferred:
            return None
        hits = match_all(
            frame,
            self.images,
            [v if "/" in v else f"skills/{v}" for v in preferred],
            threshold=0.72,
            roi=(0.68, 0.62, 0.95, 0.80),
            max_results=12,
            scales=self._adapt_scales((0.45, 0.50, 0.55, 0.60)),
        )
        by_stem = {Path(hit.name).stem: hit for hit in hits}
        return next((by_stem[Path(name).stem] for name in preferred if Path(name).stem in by_stem), None)

    def _handle_self_opened_compact_panel(self, frame: Frame) -> LoopAction | None:
        """Choose from, or safely close, a G/F/V panel without central anchors."""
        kind = getattr(self, "_panel_opened_by_us", None)
        if kind not in ("skill", "bond", "treasure"):
            return None
        if kind == "skill":
            hit = self._find_compact_skill_choice(frame)
            if hit is not None:
                print(f"[L1] 右下角技能候选选择 {hit.name} score={hit.score:.3f} @ {hit.center}")
                if self.act_click(hit, "CompactSkillChoice"):
                    self._panel_opened_by_us = None
                return LoopAction.Continue

        hit = self._hud_button_hit(frame, f"{kind}_button", self.CHOICE_BUTTON_RATIOS[kind])
        if self.act_click(hit, f"Close{kind.title()}Panel"):
            print(f"[L1] {kind} 候选无配置命中，再点按钮关闭")
            self._panel_opened_by_us = None
        else:
            print(f"[L1] 关闭 {kind} 候选被拒绝（不推进冷却）")
        return LoopAction.Continue

    def _close_current_panel(self, frame: Frame, panel_kind: str | None = None) -> MatchResult | None:
        """Resolve a verified physical hide/close affordance for a card panel."""
        kind = panel_kind or getattr(self, "_panel_opened_by_us", None)
        if kind in ("技能", "技能刷新", "技能放弃"):
            kind = "skill"
        if kind == "skill":
            names = ["skill_hide", "card_hide", "hide"]
        elif kind == "treasure":
            names = ["treasure_hide_btn", "hide"]
        elif kind in ("bond", "card"):
            names = ["card_hide", "bond_hide_btn", "skill_hide", "hide"]
        else:
            names = [
                "skill_hide", "card_hide", "bond_hide_btn",
                "treasure_hide_btn", "hide",
            ]
        roi = (0.15, 0.48, 0.88, 0.82)
        hit = self.find(
            frame,
            names,
            threshold=0.55,
            scales=self._hot_scales(),
            roi=roi,
            early_stop=True,
        )
        if hit is None:
            hit = self.find(
                frame,
                names,
                threshold=0.55,
                scales=self._wide_scales(),
                roi=roi,
                early_stop=True,
            )
        if hit is None:
            hit = self._hide_fallback_hit(frame, kind)
        return hit

    def _hide_fallback_hit(self, frame: Frame, kind: str | None = None) -> MatchResult:
        # 1600x900：暂时隐藏在放弃左侧。技能三选现已有暂时隐藏，不能点 放弃(0.36,0.61)。
        if kind == "treasure":
            rx, ry = 0.234, 0.636
        else:
            rx, ry = 0.30, 0.613
        x = int(frame.width * rx)
        y = int(frame.height * ry)
        print(f"[L1] 暂时隐藏模板未命中，按底栏位置点击 @ ({x}, {y})")
        return MatchResult(
            "hide_fallback", 1.0, x, y, 60, 28, frame.left + x, frame.top + y,
        )

    # ---------- 战后页面多锚点判别（P1-B0/B1）----------

    # 战后模板的已知位置 ROI（1600x900 基准比例，经 replay/postgame fixtures 验证）。
    _POST_GAME_ROIS = {
        "pauseGame": (0.30, 0.30, 0.70, 0.60),
        "pause_continue_game": (0.35, 0.20, 0.65, 0.65),
        "pause_return_game": (0.35, 0.20, 0.65, 0.65),
        "continueGame": (0.40, 0.50, 0.65, 0.75),
        "cjbtiaozhan": (0.35, 0.15, 0.65, 0.40),
        "mijingOk": (0.30, 0.40, 0.60, 0.65),
        "ok": (0.30, 0.40, 0.60, 0.65),
        "archiveChallenge": (0.40, 0.00, 0.60, 0.08),
        "close": (0.55, 0.15, 0.70, 0.35),
        "damijing": (0.45, 0.15, 1.00, 0.55),
        "quit": (0.00, 0.00, 0.12, 0.15),
        "HeroChallenge": (0.00, 0.00, 0.30, 0.20),
    }

    # 挑战广场标签位于游戏画面中上部；与顶部常驻“存档挑战”计时条
    # 分开取 ROI。标签尺寸会随客户端渲染缩放，不能只扫 _hot_scales()。
    _POST_GAME_HUB_ENTRY_ROIS = {
        "archive": (0.35, 0.15, 0.55, 0.40),
        # 20260910 hitch 局内：传家宝挑战标签在 (1016,205) 宽 116px，右缘
        # 超出 0.65，旧 ROI 把模板裁掉，find 直接 miss。
        "heirloom": (0.45, 0.16, 0.80, 0.45),
    }

    # 存档页右侧时光之穴 Boss 卡是缩小后的 58~70px 图标；传家宝页的
    # 卡片也可能使用同一套缩放。这里仍调用配置 Boss 的既有模板，只扩大
    # 观察尺度，不引入新的识别/决策逻辑。
    _POST_GAME_BOSS_ROIS = {
        "ARCHIVE_PANEL": (0.64, 0.24, 0.86, 0.60),
        "HEIRLOOM_DIALOG": (0.30, 0.22, 0.76, 0.72),
    }
    _POST_GAME_BOSS_SCROLLBAR_ROIS = {
        "ARCHIVE_PANEL": (0.841, 0.270, 0.847, 0.556),
        "HEIRLOOM_DIALOG": (0.620, 0.268, 0.626, 0.535),
    }
    _POST_GAME_BOSS_SCALES = (0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.80)
    _BOSS_WIDE_SCALES = (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90)
    # Compact post-game cards are rendered with a small overlay/border
    # difference from the source templates. Keep the normal entry threshold
    # unchanged; this lower bound applies only inside a classified post-game
    # list and is still above the observed near-match noise floor.
    _POST_GAME_BOSS_MATCH_THRESHOLD = 0.65
    # A configured card can sit far below the initially visible rows. Scroll
    # until the list proves it is at bottom; this is only a safety fuse.
    _POST_GAME_BOSS_SCROLL_LIMIT = 16
    _POST_GAME_BOSS_SCROLL_CLICKS = -5
    _POST_GAME_BOSS_BOTTOM_STABLE_FRAMES = 2
    _POST_GAME_BOSS_UNRESOLVED_LIMIT = 3
    _POST_GAME_BOSS_LOCATE_LIMIT = 3
    # The last visible row can be partly covered by the game's notification
    # stack.  This threshold is used only inside a geometry-predicted card
    # slot, never for a free-form page search.
    _POST_GAME_BOSS_RETRY_THRESHOLD = 0.45
    _POST_GAME_ACTION_RECHECK_S = 0.35
    _ARCHIVE_CHALLENGE_NAMES = (
        "skill", "strengthen", "gem", "loot",
        "key", "recast", "blessing", "skill2",
    )
    # 蹭车结算只消费玩家实际需要的四类存档挑战。宝石、战利品的
    # ``0/8`` 是不可挑战，不是“已挑战”；密钥和祝福必须逐项发出输入。
    _HITCH_ARCHIVE_CHALLENGE_SLOTS = (
        ("gem", 2), ("loot", 3), ("key", 4), ("blessing", 6),
    )
    # 依据真实 1596x921/1597x929 战后 fixture；仅在 ARCHIVE_PANEL 已分类后使用。
    _ARCHIVE_CHALLENGE_X = (0.396, 0.465, 0.535, 0.604)
    _ARCHIVE_CHALLENGE_Y = (0.350, 0.466)
    # Eight fixed post-game card slots only need the next rendered frame to
    # confirm their green completion overlay; do not inherit the slower
    # generic panel cadence between every one of the eight clicks.
    _ARCHIVE_CHALLENGE_RECHECK_S = 0.35

    def _post_game_action_recheck(self, requested_s: float | None = None) -> float:
        """Keep the serialized post-game chain responsive after each input."""
        requested = (
            float(requested_s)
            if requested_s is not None
            else float(getattr(self.settings, "ui_action_interval_s", 1.5) or 1.5)
        )
        return max(0.15, min(requested, self._POST_GAME_ACTION_RECHECK_S))

    def _find_archive_challenge_card(self, frame: Frame, index: int) -> MatchResult | None:
        """Return the classified archive card hitbox for one of the eight slots.

        The page classifier is the authority; this helper only maps the stable
        4x2 page layout to a guarded click box and rejects an empty/invalid crop.
        It intentionally does not infer challenge semantics or create a FSM.
        """
        if frame.bgr is None or not (0 <= index < len(self._ARCHIVE_CHALLENGE_NAMES)):
            return None
        col, row = index % 4, index // 4
        cx = int(frame.width * self._ARCHIVE_CHALLENGE_X[col])
        cy = int(frame.height * self._ARCHIVE_CHALLENGE_Y[row])
        half_w = max(24, int(frame.width * 0.030))
        half_h = max(24, int(frame.height * 0.052))
        x0, x1 = max(0, cx - half_w), min(frame.width, cx + half_w)
        y0, y1 = max(0, cy - half_h), min(frame.height, cy + half_h)
        crop = frame.bgr[y0:y1, x0:x1]
        if crop.size == 0:
            return None
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        texture = float(np.std(gray))
        if texture < 8.0:
            return None
        score = min(0.99, max(0.60, texture / 100.0))
        return MatchResult(
            f"archive_challenge_{self._ARCHIVE_CHALLENGE_NAMES[index]}",
            score,
            x0,
            y0,
            x1 - x0,
            y1 - y0,
            frame.left + cx,
            frame.top + cy,
        )

    def _archive_challenge_completed(self, frame: Frame, index: int) -> bool:
        """Whether the classified card carries the green ``已挑战`` overlay."""
        if frame.bgr is None or not (0 <= index < len(self._ARCHIVE_CHALLENGE_NAMES)):
            return False
        col, row = index % 4, index // 4
        cx = int(frame.width * self._ARCHIVE_CHALLENGE_X[col])
        cy = int(frame.height * self._ARCHIVE_CHALLENGE_Y[row])
        x0, x1 = max(0, int(cx - frame.width * 0.040)), min(frame.width, int(cx + frame.width * 0.040))
        y0, y1 = max(0, int(cy - frame.height * 0.035)), min(frame.height, int(cy + frame.height * 0.060))
        crop = frame.bgr[y0:y1, x0:x1]
        if crop.size == 0:
            return False
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        green = cv2.inRange(hsv, (42, 120, 100), (88, 255, 255))
        green_pixels = int(np.count_nonzero(green))
        # A dense green fill is used by replay fixtures.  In the live client
        # the overlay itself is three compact glyphs; raw pixel count alone
        # also accepted green chat text crossing the key card (5/8).
        if green_pixels >= int(green.size * 0.75):
            return True
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(green)
        glyphs = sum(
            7 <= w <= 25 and 16 <= h <= 24 and area >= 80
            for _x, _y, w, h, area in stats[1:count]
        )
        return bool(glyphs >= 3)

    def _archive_hitch_card_progress_state(self, frame: Frame, card_index: int) -> str:
        """解析存档挑战进度状态。

        状态取值：
        - 'UNAVAILABLE': 明确解析为 0/8（资源不足无法挑战）
        - 'AVAILABLE': 明确解析为 1/8..7/8（未满且可挑战）
        - 'COMPLETED': 明确解析为 8/8（已满）
        - 'UNKNOWN': 无法可信解析；UNKNOWN 绝不授权判定为不可挑战（Fail-Open 允许尝试或零输入等待）
        """
        if frame.bgr is None or card_index not in {2, 3, 4, 6}:
            return "AVAILABLE"
        col, row = card_index % 4, card_index // 4
        cx = int(frame.width * self._ARCHIVE_CHALLENGE_X[col])
        cy = int(frame.height * self._ARCHIVE_CHALLENGE_Y[row])
        x0 = min(frame.width, cx + int(frame.width * 0.002))
        y0 = max(0, cy - int(frame.height * 0.078))
        x1 = min(frame.width, cx + int(frame.width * 0.027))
        y1 = max(0, cy - int(frame.height * 0.039))
        counter = frame.bgr[y0:y1, x0:x1]
        if counter.size == 0:
            return "UNKNOWN"

        # 红色像素检测（当次数为 0 时，数字 0 呈现红色警告色；可用次数为白色或绿色）
        b, g, r = cv2.split(counter)
        red_pixels = int(np.count_nonzero((r > 150) & (g < 100) & (b < 100)))

        # 优先使用 OCR client 解析 counter ROI
        ocr_client = getattr(self, "_ocr_client", None)
        if ocr_client and getattr(ocr_client, "is_available", False):
            try:
                resp = ocr_client.shadow_predict(
                    frame,
                    "archive_counter",
                    {"index": card_index, "bbox": (x0, y0, x1, y1), "kind": "counter"},
                )
                status = str(getattr(resp, "status", "") or "").lower()
                text = (getattr(resp, "raw_text", "") or "").strip()
                score = float(getattr(resp, "rec_score", 0.0) or 0.0)
                if status == "ok" and score >= 0.75:
                    import re
                    # 1. 结构化正则匹配带有标点者：如 "0/8", "0|8", "0-8"
                    m_slash = re.search(r"(\d+)\s*[/|\\-]\s*(\d+)", text)
                    if m_slash:
                        num, den = int(m_slash.group(1)), int(m_slash.group(2))
                        if den == 8:
                            if num == 0:
                                return "UNAVAILABLE"
                            if num >= den:
                                return "COMPLETED"
                            return "AVAILABLE"
                    # 2. 识别为 "018"（0 + 斜杠识别为1 + 8）
                    if text == "018" or re.fullmatch(r"01?8", text):
                        return "UNAVAILABLE"
                    # 3. 识别为 "18" 或包含 "8" 且伴随明显红色 0 像素证据（red_pixels >= 40）
                    if red_pixels >= 40 and ("8" in text or text.endswith("8")):
                        return "UNAVAILABLE"
                    # 4. 正常解析 1/8..7/8
                    m_num = re.search(r"^([1-7])1?8$", text)
                    if m_num:
                        return "AVAILABLE"
            except Exception:
                pass
        return "UNKNOWN"

    def _archive_hitch_card_unavailable(self, frame: Frame, card_index: int) -> bool:
        """C6 语义兼容接口：仅当明确解析为 UNAVAILABLE 时才返回 True。"""
        state = self._archive_hitch_card_progress_state(frame, card_index)
        return state == "UNAVAILABLE"

    def _archive_challenge_insufficient_notice(self, frame: Frame) -> bool:
        """第二证据：检测是否弹出「今日挑战次数不足」或类似提示。"""
        if frame.bgr is None or frame.bgr.size == 0:
            return False
        # Toast 区域位于屏幕居中偏下 (730, 540, 880, 590)
        x0, y0 = int(frame.width * 0.456), int(frame.height * 0.600)
        x1, y1 = int(frame.width * 0.550), int(frame.height * 0.656)
        crop = frame.bgr[y0:y1, x0:x1]
        if crop.size == 0:
            return False
        # 快速颜色筛选：Toast 文本包含明亮金黄色/白色字符
        b, g, r = cv2.split(crop)
        bright = (r > 180) & (g > 160) & (b < 180)
        if np.count_nonzero(bright) < 15:
            return False
        ocr_client = getattr(self, "_ocr_client", None)
        if ocr_client and getattr(ocr_client, "is_available", False):
            try:
                resp = ocr_client.shadow_predict(
                    frame,
                    "archive_toast",
                    {"bbox": (x0, y0, x1, y1), "kind": "toast"},
                )
                text = (getattr(resp, "raw_text", "") or "").strip()
                score = float(getattr(resp, "rec_score", 0.0) or 0.0)
                if score >= 0.60 and any(k in text for k in ("今日", "次数不足", "不足", "无法")):
                    return True
            except Exception:
                pass
        # 像素兜底：若有强黄色字符像素群（>= 60）
        return bool(np.count_nonzero(bright) >= 60)

    def _archive_challenge_plan(self) -> tuple[tuple[str, int], ...]:
        """All eight cards, left to right, in both solo and team modes."""
        return tuple((label, index) for index, label in enumerate(self._ARCHIVE_CHALLENGE_NAMES))

    # Pause after the sweep so the last clicks can render their green mark
    # before the verify pass re-reads them.
    _ARCHIVE_VERIFY_SETTLE_S = 1.0

    def _archive_card_skip_reason(self, frame: Frame, card_index: int) -> str | None:
        """Never click a card that shows 已挑战 or a 0/8 counter."""
        if self._archive_challenge_completed(frame, card_index):
            return "已挑战"
        # The key card's tiny 0/8 counter was repeatedly read from its
        # decorative border in solo live runs. A visible green completion
        # mark remains authoritative; every other key state gets one sweep
        # click and the normal single verify click.
        if card_index == 4:
            return None
        if self._archive_hitch_card_unavailable(frame, card_index):
            return "0/8 次数已用完"
        return None

    def _maybe_click_archive_challenge(self, frame: Frame, now: float) -> LoopAction | None:
        """Sweep the eight archive cards once, then one verify pass.

        Owner rule (2026-09-14): speed comes from clicking 1 -> 8 in one go,
        not from re-clicking one card until it turns green.
          * sweep: left to right, skip 已挑战 / 0/8, click every other card
            exactly once and move on without waiting for its green mark;
          * verify: re-read only the cards clicked in the sweep; one that is
            neither 已挑战 nor 0/8 gets at most one more click.
        No card is clicked more than twice; 已挑战 / 0/8 cards never.
        """
        recheck_s = self._post_game_action_recheck(self._ARCHIVE_CHALLENGE_RECHECK_S)
        plan = self._archive_challenge_plan()
        index = int(getattr(self, "_archive_challenge_index", 0) or 0)
        clicked = self._archive_challenge_clicked
        verified = self._archive_challenge_verified
        verify_queue = [
            (label, card_index) for label, card_index in plan
            if card_index in clicked and card_index not in verified
        ]
        if index >= len(plan) and not verify_queue:
            return None
        if now < getattr(self, "_archive_challenge_next_at", 0.0):
            return LoopAction.Continue

        if index < len(plan):
            while index < len(plan):
                reason = self._archive_card_skip_reason(frame, plan[index][1])
                if reason is None:
                    break
                print(f"[med] 存档挑战 {plan[index][0]} {reason}，不点击，转下一张")
                index += 1
            self._archive_challenge_index = index
            if index < len(plan):
                label, card_index = plan[index]
                hit = self._find_archive_challenge_card(frame, card_index)
                if hit is None:
                    self._archive_challenge_observe_attempts += 1
                    if self._archive_challenge_observe_attempts >= 5:
                        print(f"[med] 存档挑战卡位 {card_index + 1}/8 连续 5 次无卡面证据，跳过并继续")
                        self._archive_challenge_index = index + 1
                        self._archive_challenge_observe_attempts = 0
                        return LoopAction.Continue
                    self._archive_challenge_next_at = now + recheck_s
                    print(f"[med] 存档挑战卡位 {card_index + 1}/8 无有效卡面证据，零输入复核 ({self._archive_challenge_observe_attempts}/5)")
                    return LoopAction.Continue
                print(f"[med] 存档挑战扫卡 {index + 1}/{len(plan)}：点击 {label} @ {hit.center}（每张只点一次）")
                if self.act_click(hit, f"ArchiveChallenge-{label}"):
                    clicked.add(card_index)
                    self._archive_challenge_index = index + 1
                    self._archive_challenge_observe_attempts = 0
                    self._archive_challenge_click_attempts = 0
                    self._post_game_route = "archive_active"
                else:
                    # An input-layer refusal is not a game answer: bounded retry.
                    self._archive_challenge_click_attempts = getattr(self, "_archive_challenge_click_attempts", 0) + 1
                    if self._archive_challenge_click_attempts >= 3:
                        print(f"[med] 存档挑战 {label} 点击被拒达 3 次，跳过并转下一张卡")
                        self._archive_challenge_index = index + 1
                        self._archive_challenge_click_attempts = 0
                        self._archive_challenge_observe_attempts = 0
                    else:
                        print(f"[med] 存档挑战 {label} 点击被拒，冷却后重试 ({self._archive_challenge_click_attempts}/3)")
                self._archive_challenge_next_at = now + recheck_s
                return LoopAction.Continue
            if verify_queue and not self._archive_verify_started:
                self._archive_verify_started = True
                self._archive_challenge_next_at = now + self._ARCHIVE_VERIFY_SETTLE_S
                print(f"[med] 存档挑战 1-8 已扫完（点击 {len(clicked)} 张），{self._ARCHIVE_VERIFY_SETTLE_S:.0f}s 后复查一轮")
                return LoopAction.Continue

        for label, card_index in verify_queue:
            verified.add(card_index)
            if self._archive_card_skip_reason(frame, card_index) is not None:
                continue
            hit = self._find_archive_challenge_card(frame, card_index)
            if hit is None:
                continue
            print(f"[med] 存档挑战复查：{label} 未变绿也非 0/8，补点一次 @ {hit.center}")
            self.act_click(hit, f"ArchiveChallenge-{label}-verify")
            self._archive_challenge_next_at = now + recheck_s
            return LoopAction.Continue
        print("[med] 存档挑战扫卡与复查完成")
        return None

    @property
    def _post_game_boss_scroll_step(self) -> int:
        """Configurable scroll step (clicks) for post-game boss list."""
        return int(getattr(self.settings, "post_game_boss_scroll_clicks", self._POST_GAME_BOSS_SCROLL_CLICKS) or self._POST_GAME_BOSS_SCROLL_CLICKS)

    def _post_game_boss_grid_fingerprint(self, frame: Frame, post_game: str | None) -> str | None:
        """Compute visual fingerprint of the post-game boss grid area."""
        roi = self._POST_GAME_BOSS_ROIS.get(post_game or "")
        if frame.bgr is None or frame.bgr.size == 0 or roi is None:
            return None
        x0, y0, x1, y1 = self._normalized_bbox(frame, roi)
        crop = frame.bgr[y0:y1, x0:x1]
        if crop.size == 0:
            return None
        from shuabao.interaction_surface import compute_frame_roi_fingerprint
        return compute_frame_roi_fingerprint(crop)

    def _post_game_boss_scroll_point(self, frame: Frame, post_game: str | None) -> tuple[int, int] | None:
        """Return a point inside a classified Boss list, if one is known."""
        roi = self._POST_GAME_BOSS_ROIS.get(post_game or "")
        if roi is None:
            return None
        rx1, ry1, rx2, ry2 = roi
        return (
            frame.left + int(frame.width * (rx1 + rx2) / 2.0),
            frame.top + int(frame.height * (ry1 + ry2) / 2.0),
        )

    def _post_game_boss_has_no_scrollbar(self, frame: Frame, post_game: str | None) -> bool:
        """Positive evidence that the boss list has no scrollbar (fits on 1 screen)."""
        scrollbar_roi = self._POST_GAME_BOSS_SCROLLBAR_ROIS.get(post_game or "")
        if frame.bgr is None or frame.bgr.size == 0 or scrollbar_roi is None:
            return False
        x0, y0, x1, y1 = self._normalized_bbox(frame, scrollbar_roi)
        strip = frame.bgr[y0:y1, x0:x1]
        if strip.size == 0:
            return False
        gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
        mask = gray >= 180
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
        has_bright_comp = any(
            2 <= w <= 12 and h >= 8
            for _x, _y, w, h, _area in stats[1:count]
        )
        mean_val = float(np.mean(gray))
        std_val = float(np.std(gray))
        return (
            not has_bright_comp
            and 15.0 <= mean_val < 60.0
            and std_val < 25.0
        )

    def _post_game_boss_list_at_bottom(self, frame: Frame, post_game: str | None) -> bool:
        """Require bottom confirmation before selecting a fallback.

        通用证据：若发生过向下滚动，且滚动后网格指纹未发生变化，证明已到底（停止空滚）。
        若无滚动条（fits on 1 screen），需要双帧稳定。
        """
        scrollbar_roi = self._POST_GAME_BOSS_SCROLLBAR_ROIS.get(post_game or "")
        if frame.bgr is None or frame.bgr.size == 0 or scrollbar_roi is None:
            return False

        # 通用证据：滚动后网格指纹不变 = 到底
        last_fp = getattr(self, "_boss_challenge_scroll_grid_fp", None)
        curr_fp = self._post_game_boss_grid_fingerprint(frame, post_game)
        if (
            getattr(self, "_boss_challenge_scroll_attempts", 0) > 0
            and last_fp is not None
            and curr_fp is not None
            and last_fp == curr_fp
        ):
            print(f"[med] post-game {post_game} 滚动后网格指纹未变化（{curr_fp}），通用证据确认到底")
            self._boss_challenge_scroll_stable_frames = (
                int(getattr(self, "_boss_challenge_scroll_stable_frames", 0) or 0) + 1
            )
            return True

        if self._post_game_boss_has_no_scrollbar(frame, post_game):
            self._boss_challenge_scroll_stable_frames = (
                int(getattr(self, "_boss_challenge_scroll_stable_frames", 0) or 0) + 1
            )
            return bool(
                self._boss_challenge_scroll_stable_frames
                >= self._POST_GAME_BOSS_BOTTOM_STABLE_FRAMES
            )

        x0, y0, x1, y1 = self._normalized_bbox(frame, scrollbar_roi)
        strip = frame.bgr[y0:y1, x0:x1]
        if strip.size == 0:
            return False
        mask = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY) >= 180
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
        height = max(1, strip.shape[0])
        at_bottom = any(
            2 <= w <= 12 and h >= 8 and y + h >= int(height * 0.94)
            for _x, y, w, h, _area in stats[1:count]
        )
        if at_bottom:
            self._boss_challenge_scroll_stable_frames = (
                int(getattr(self, "_boss_challenge_scroll_stable_frames", 0) or 0) + 1
            )
        else:
            self._boss_challenge_scroll_stable_frames = 0
        return bool(
            self._boss_challenge_scroll_attempts > 0
            and self._boss_challenge_scroll_stable_frames
            >= self._POST_GAME_BOSS_BOTTOM_STABLE_FRAMES
        )

    def _post_game_boss_list_at_top(self, frame: Frame, post_game: str | None) -> bool:
        """Check if the scrollable Boss list is confirmed at the top (requires 2 stable frames).

        If list has no scrollbar, both at_top and at_bottom hold (requires 2 stable frames).
        """
        scrollbar_roi = self._POST_GAME_BOSS_SCROLLBAR_ROIS.get(post_game or "")
        if frame.bgr is None or frame.bgr.size == 0 or scrollbar_roi is None:
            return False
        if self._post_game_boss_has_no_scrollbar(frame, post_game):
            self._boss_challenge_scroll_top_stable_frames = (
                int(getattr(self, "_boss_challenge_scroll_top_stable_frames", 0) or 0) + 1
            )
            return bool(
                getattr(self, "_boss_challenge_scroll_top_stable_frames", 0) >= 2
            )

        x0, y0, x1, y1 = self._normalized_bbox(frame, scrollbar_roi)
        strip = frame.bgr[y0:y1, x0:x1]
        if strip.size == 0:
            return False
        mask = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY) >= 180
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
        height = max(1, strip.shape[0])
        at_top = any(
            2 <= w <= 12 and h >= 8 and y <= int(height * 0.08)
            for _x, y, w, h, _area in stats[1:count]
        )
        if at_top:
            self._boss_challenge_scroll_top_stable_frames = (
                int(getattr(self, "_boss_challenge_scroll_top_stable_frames", 0) or 0) + 1
            )
        else:
            self._boss_challenge_scroll_top_stable_frames = 0
        return bool(
            getattr(self, "_boss_challenge_scroll_top_stable_frames", 0) >= 2
        )

    def _find_last_recognized_post_game_boss(
        self, frame: Frame, post_game: str | None, scales: Sequence[float] | None = None
    ) -> MatchResult | None:
        """Find the physically last card on a classified, bottomed-out list."""
        subdir = {
            "ARCHIVE_PANEL": "boss",
            "HEIRLOOM_DIALOG": "chuanjiaobao",
        }.get(post_game or "")
        roi = self._POST_GAME_BOSS_ROIS.get(post_game or "")
        if subdir is None or roi is None:
            return None

        names = [f"{subdir}/{path.stem}" for path in (self.images / subdir).glob("*.png")]
        use_scales = scales if scales is not None else self._adapt_scales(self._POST_GAME_BOSS_SCALES)
        hits = match_all(
            frame,
            self.images,
            names,
            threshold=self._POST_GAME_BOSS_MATCH_THRESHOLD,
            scales=use_scales,
            roi=roi,
            max_results=96,
        )
        catalog = getattr(self, "_boss_catalog_cache", None)
        valid_hits: list[MatchResult] = []
        for hit in hits:
            if post_game == "HEIRLOOM_DIALOG":
                stem = Path(hit.name).stem
                no = parse_boss_order_number(stem, catalog)
                if no is not None and not (1 <= no <= 20):
                    continue
            valid_hits.append(hit)
        return max(valid_hits, key=lambda hit: (hit.y + hit.h, hit.x + hit.w), default=None)

    def _record_boss_challenge_skipped_incident(
        self, page_type: str, reason: str = "anomaly"
    ) -> None:
        """Record an incident when boss challenge is skipped due to unrecognized cards."""
        if getattr(self, "_archiver", None) is None:
            return
        frame = self._last_frame
        if frame is None or frame.bgr is None or frame.bgr.size == 0:
            return
        self._archiver.maybe_record(
            frame_before=self._prev_frame or frame,
            frame_now=frame,
            metadata=self._incident_meta(
                "boss_challenge_skipped",
                f"boss challenge on {page_type} skipped: {reason}",
                final_action="skip",
                extra={"page_type": page_type, "reason": reason},
            ),
        )

    def _handle_boss_anomaly_retry_or_skip(
        self, frame: Frame, now: float, post_game: str | None, recheck_s: float
    ) -> tuple[LoopAction, MatchResult | None, str]:
        """Handle anomaly when not a single boss card can be recognized.

        Returns (LoopAction, boss_hit, action_name):
        - If wide scale retry finds a card: returns (LoopAction.Continue, boss_hit, "BossLastVisibleFallback")
        - If still retrying (pointer park + wait): returns (LoopAction.Continue, None, "")
        - If retries exhausted: records incident, tracks consecutive skips, emits warning if >= 2,
          and skips boss challenge into close path, returning (LoopAction.Continue, None, "SKIPPED")
        """
        anomaly_limit = self._POST_GAME_BOSS_UNRESOLVED_LIMIT * 2
        self._boss_anomaly_retry_attempts = getattr(self, "_boss_anomaly_retry_attempts", 0) + 1

        # 1. 鼠标停车清理悬停遮挡
        if self._POINTER_PARK is not None:
            self.act_move(
                int(frame.width * self._POINTER_PARK[0]),
                int(frame.height * self._POINTER_PARK[1]),
                "BossAnomalyParkPointer",
            )

        # 2. 用更宽尺度重新识别一次
        wide_card = self._find_last_recognized_post_game_boss(
            frame, post_game, scales=self._adapt_scales(self._BOSS_WIDE_SCALES)
        )
        if wide_card is not None:
            self._boss_anomaly_retry_attempts = 0
            self._boss_challenge_unresolved_attempts = 0
            print(f"[med] [BossLastVisibleFallback] 宽尺度重试成功命中末卡 {wide_card.name} @ {wide_card.center}")
            return (LoopAction.Continue, wide_card, "BossLastVisibleFallback")

        if self._boss_anomaly_retry_attempts < anomaly_limit:
            self._boss_challenge_next_at = now + self._post_game_action_recheck(recheck_s)
            print(
                f"[med] Boss 列表未认出任何卡片，鼠标停车并以宽尺度重试 "
                f"({self._boss_anomaly_retry_attempts}/{anomaly_limit})"
            )
            return (LoopAction.Continue, None, "")

        # 达到 2 倍上限，全部失败，跳过本次 Boss 挑战
        print(
            f"[med] [BossChallengeSkipped] 一张卡都认不出，重试 {self._boss_anomaly_retry_attempts} 次耗尽，"
            f"跳过本次 Boss 挑战 (reason=anomaly)"
        )
        self._trace_actions.append({
            "intent": "boss_challenge_skipped",
            "reason": "anomaly",
            "page": post_game,
        })
        if not hasattr(self, "_boss_anomaly_skip_counts"):
            self._boss_anomaly_skip_counts = {}
        consecutive = self._boss_anomaly_skip_counts.get(post_game or "", 0) + 1
        self._boss_anomaly_skip_counts[post_game or ""] = consecutive
        if consecutive >= 2:
            page_title = "时光之穴" if post_game == "ARCHIVE_PANEL" else ("传家宝" if post_game == "HEIRLOOM_DIALOG" else (post_game or ""))
            warn_msg = f"警告：{page_title}连续 {consecutive} 局没有认出任何卡，请检查分辨率 / 遮挡"
            print(f"[med] {warn_msg}")
            LOGGER.warning(warn_msg)

        self._record_boss_challenge_skipped_incident(post_game or "", reason="anomaly")

        self._boss_anomaly_retry_attempts = 0
        self._boss_challenge_unresolved_attempts = 0
        self._boss_challenge_attempts = 0

        # 进入关闭/继续路径，绝不停机
        if post_game == "ARCHIVE_PANEL":
            self._time_cave_boss_done = True
            self._post_game_route = "archive"
        elif post_game == "HEIRLOOM_DIALOG":
            self._boss_challenge_attempts = 3
            self._heirloom_boss_confirm_unconfirmed = True
            if self._post_game_pending and getattr(self, "_post_game_route", "") == "heirloom_active":
                self._post_game_pending = False

        return (LoopAction.Continue, None, "SKIPPED")

    def _bbox_to_normalized_roi(
        self, frame: Frame, bbox: tuple[int, int, int, int], padding: int = 12
    ) -> tuple[float, float, float, float]:
        px, py, pw, ph = bbox
        x1 = max(0, px - padding)
        y1 = max(0, py - padding)
        x2 = min(frame.width, px + pw + padding)
        y2 = min(frame.height, py + ph + padding)
        return (x1 / frame.width, y1 / frame.height, x2 / frame.width, y2 / frame.height)

    def _find_visible_post_game_boss_cards(
        self, frame: Frame, post_game: str | None
    ) -> list[tuple[VisibleCard, MatchResult]]:
        """Recognize and parse all visible boss cards within the post-game list ROI."""
        subdir = {
            "ARCHIVE_PANEL": "boss",
            "HEIRLOOM_DIALOG": "chuanjiaobao",
        }.get(post_game or "")
        roi = self._POST_GAME_BOSS_ROIS.get(post_game or "")
        if subdir is None or roi is None:
            return []

        template_dir = self.images / subdir
        if not template_dir.exists():
            return []

        names = [f"{subdir}/{path.stem}" for path in template_dir.glob("*.png")]
        hits = match_all(
            frame,
            self.images,
            names,
            threshold=self._POST_GAME_BOSS_MATCH_THRESHOLD,
            scales=self._adapt_scales(self._POST_GAME_BOSS_SCALES),
            roi=roi,
            max_results=96,
        )
        catalog = getattr(self, "_boss_catalog_cache", None)
        results: list[tuple[VisibleCard, MatchResult]] = []
        seen_centers: list[tuple[int, int]] = []
        for hit in sorted(hits, key=lambda h: h.score, reverse=True):
            stem = Path(hit.name).stem
            no = parse_boss_order_number(stem, catalog)
            if no is None:
                continue
            if post_game == "HEIRLOOM_DIALOG" and not (1 <= no <= 20):
                print(f"[med] 传家宝列表忽略超出范围序号卡片 {hit.name} (no={no})")
                continue
            if any(abs(hit.center[0] - cx) < 20 and abs(hit.center[1] - cy) < 20 for cx, cy in seen_centers):
                continue
            seen_centers.append(hit.center)
            vc = VisibleCard(
                no=no,
                name=stem,
                x=hit.x,
                y=hit.y,
                w=hit.w,
                h=hit.h,
                score=hit.score,
            )
            results.append((vc, hit))
        return sorted(results, key=lambda pair: (pair[0].y, pair[0].x))

    def _post_game_boss_grid_end_card(
        self,
        frame: Frame,
        post_game: str | None,
        visible_pairs: list[tuple[VisibleCard, MatchResult]],
        slot_empty_checker,
    ) -> tuple[MatchResult | None, bool]:
        """Prove the end from a full row followed by a partial row and an empty next slot."""
        if not visible_pairs:
            self._boss_grid_end_signature = None
            self._boss_grid_end_stable_frames = 0
            return None, False
        by_no = {card.no: (card, hit) for card, hit in visible_pairs}
        last_no = max(by_no)
        last_row, last_col = divmod(last_no - 1, 4)
        if last_row <= 0 or last_col >= 3:
            self._boss_grid_end_signature = None
            self._boss_grid_end_stable_frames = 0
            return None, False
        preceding = range((last_row - 1) * 4 + 1, last_row * 4 + 1)
        partial = range(last_row * 4 + 1, last_no + 1)
        if not all(no in by_no for no in preceding) or not all(no in by_no for no in partial):
            self._boss_grid_end_signature = None
            self._boss_grid_end_stable_frames = 0
            return None, False
        next_slot = predict_card_slot(
            last_no + 1, [card for card, _ in visible_pairs], cols_per_row=4
        )
        if next_slot is None or not slot_empty_checker(next_slot):
            self._boss_grid_end_signature = None
            self._boss_grid_end_stable_frames = 0
            return None, False
        signature = (post_game, last_no, tuple(sorted(by_no)))
        if signature == getattr(self, "_boss_grid_end_signature", None):
            self._boss_grid_end_stable_frames = int(
                getattr(self, "_boss_grid_end_stable_frames", 0) or 0
            ) + 1
        else:
            self._boss_grid_end_signature = signature
            self._boss_grid_end_stable_frames = 1
        card, hit = by_no[last_no]
        if self._boss_grid_end_stable_frames >= 2:
            print(
                f"[med] Boss 网格末行确认：上一行满、{last_no + 1} 空，"
                f"末卡 {card.name} @ {hit.center}"
            )
            return hit, True
        print(f"[med] Boss 网格末行候选：上一行满、{last_no + 1} 空，等待第二帧确认")
        return None, True

    def _verify_boss_predicted_slot(
        self,
        frame: Frame,
        post_game: str | None,
        target_name: str | None,
        pred_box: tuple[int, int, int, int] | None,
    ) -> MatchResult | None:
        """Seek evidence (lowered template threshold or OCR) in the predicted card box."""
        if not target_name or not pred_box:
            return None
        subdir = {
            "ARCHIVE_PANEL": "boss",
            "HEIRLOOM_DIALOG": "chuanjiaobao",
        }.get(post_game or "")
        pred_roi = self._bbox_to_normalized_roi(frame, pred_box, padding=12)
        compact_scales = self._adapt_scales(self._POST_GAME_BOSS_SCALES)
        # P2-8: 严格限定为当前页面子目录，不跨目录试探
        template_names = [f"{subdir}/{target_name}"] if subdir else [target_name]
        hit = self.find(
            frame,
            template_names,
            threshold=self._POST_GAME_BOSS_RETRY_THRESHOLD,
            scales=compact_scales,
            roi=pred_roi,
            mode="post-game-boss-predicted",
        )
        if hit is not None:
            px, py, pw, ph = pred_box
            cx, cy = hit.center
            if px <= cx <= px + pw and py <= cy <= py + ph:
                return hit
            print(f"[med] 预测格位命中越界，忽略 {hit.name} @ {hit.center}")

        # P0-1: OCR 验证路径，遵循 ShadowClient 真实签名 (frame, panel_id, slot) 并捕获异常
        ocr_client = getattr(self, "_ocr_client", None)
        if ocr_client and getattr(ocr_client, "is_available", False) and frame.bgr is not None:
            try:
                px, py, pw, ph = pred_box
                x0 = max(0, px)
                y0 = max(0, py)
                x1 = min(frame.width, px + pw)
                y1 = min(frame.height, py + ph)
                target_no = parse_boss_order_number(target_name, getattr(self, "_boss_catalog_cache", None)) or 0
                resp = ocr_client.shadow_predict(
                    frame,
                    "post_game_boss_slot",
                    {"index": target_no, "bbox": (x0, y0, x1, y1), "kind": "boss_name"},
                )
                status = str(getattr(resp, "status", "") or "").lower()
                text = (getattr(resp, "raw_text", "") or "").strip()
                score = float(getattr(resp, "rec_score", 0.0) or 0.0)
                label = re.sub(r"^\d+", "", target_name).strip()
                if status == "ok" and score >= 0.75 and label and label in text:
                    cx = (x0 + x1) // 2
                    cy = (y0 + y1) // 2
                    return MatchResult(
                        f"ocr_boss:{target_name}",
                        score,
                        x0,
                        y0,
                        pw,
                        ph,
                        frame.left + cx,
                        frame.top + cy,
                    )
            except Exception as e:
                print(f"[med] 预测格位 OCR 异常: {e}")
        return None

    def _record_boss_locate_failed_incident(self, bosses: list[str], last_card: str) -> None:
        """Record an incident when boss order locating fails and exhausts attempts."""
        if getattr(self, "_archiver", None) is None:
            return
        frame = self._last_frame
        if frame is None or frame.bgr is None or frame.bgr.size == 0:
            return
        self._archiver.maybe_record(
            frame_before=self._prev_frame or frame,
            frame_now=frame,
            metadata=self._incident_meta(
                "boss_order_locate_failed",
                f"target boss {bosses} locate failed; fallback to last card {last_card}",
                final_action="click_last",
                extra={"configured_bosses": bosses, "last_card": last_card},
            ),
        )

    def _find_post_game_hub_entry(self, frame: Frame, route: str) -> MatchResult | None:
        """Find a real challenge-hub label after the hub itself is classified.

        ``archiveChallenge`` is also the always-visible top HUD timer, so the
        route ROI is essential. The two labels plus the right-side ``damijing``
        anchor form the page evidence; this method alone never grants action
        authority outside the classified NPC hub.
        """
        # The hovered plaza label renders bold, the other one thin.  Live
        # 2026-09-14 f0707 (pointer parked on 存档挑战) scored the bold-only
        # 传家宝 template 0.45-0.57, so the hub never classified; the thin
        # variant scores 0.83-1.0 there and <=0.53 off-label.
        names = {
            "archive": ["archiveChallenge"],
            "heirloom": ["chuanjiabao", "chuanjiabao_thin", "cjbtiaozhan"],
        }.get(route)
        roi = self._POST_GAME_HUB_ENTRY_ROIS.get(route)
        if not names or roi is None:
            return None
        hit = self.find(
            frame,
            names,
            # Cloud audit A1: real 传家宝 hits are >=0.83 while the bold template
            # scores 0.573 on 存档挑战; 0.58 left a 0.007 margin.
            threshold=self._HUB_ENTRY_THRESHOLD.get(route, 0.58),
            scales=self._adapt_scales((0.60, 0.70, 0.80, 0.90, 1.00, 1.10, 1.20)),
            roi=roi,
            mode=f"post-game-hub:{route}",
        )
        if hit is None:
            return None
        if not (
            frame.width * roi[0] <= hit.x <= frame.width * roi[2]
            and frame.height * roi[1] <= hit.y <= frame.height * roi[3]
        ):
            return None
        return hit

    @staticmethod
    def _post_game_hub_label_pair(
        frame: Frame, archive: MatchResult | None, heirloom: MatchResult | None
    ) -> bool:
        """Are these the plaza's two side-by-side NPC labels?

        Live frame ``f0133`` scores ``damijing`` at 0.597, so the old rift-NPC
        gate could never classify that page and the heirloom entry was never
        reached.  The replacement evidence is the label *pair*, and a pair is
        only page evidence when it has the plaza's geometry: 存档挑战 and
        传家宝挑战 render on one baseline, archive first, nearly touching.
        Two unrelated 0.58 hits scattered across the battlefield do not.
        """
        if archive is None or heirloom is None:
            return False
        if abs(archive.y - heirloom.y) > frame.height * 0.02:
            return False
        if archive.x >= heirloom.x:
            return False
        gap = heirloom.x - (archive.x + archive.w)
        return -frame.width * 0.01 <= gap <= frame.width * 0.10

    _HUB_ENTRY_THRESHOLD = {"heirloom": 0.70}
    _HUB_LABEL_OCR_MIN_SCORE = 0.80
    _HUB_LABEL_OCR_INTERVAL_S = 1.0
    _HUB_LABEL_OCR_MAX_BOXES = 4
    _HUB_LABEL_OCR_STABLE_PX = 8

    def _heirloom_label_ocr_fallback(self, frame: Frame) -> MatchResult | None:
        """Every heirloom template missed: find the label by reading it.

        Only inside a running post-game chain on the confirmed plaza (top-bar
        存档) and only inside the heirloom ROI: white word boxes from
        ``white_text_word_boxes`` go to the existing box OCR, and a box that
        reads 传家宝 must repeat within a few pixels on a second, different
        frame before it is returned.  OCR text alone never authorises input;
        the caller still clicks the fixed offset below the label.
        """
        if not self._post_game_pending or self._top_bar_mode(frame) != "plaza":
            self._hub_label_ocr_last = None
            return None
        client = getattr(self, "_ocr_client", None)
        if client is None or frame.bgr is None:
            return None
        now = time.time()
        if now < self._hub_label_ocr_next_at:
            return None
        self._hub_label_ocr_next_at = now + self._HUB_LABEL_OCR_INTERVAL_S
        roi = self._POST_GAME_HUB_ENTRY_ROIS["heirloom"]
        boxes = white_text_word_boxes(frame.bgr, roi)[: self._HUB_LABEL_OCR_MAX_BOXES]
        found: tuple[int, int, int, int, float] | None = None
        for index, (x, y, w, h) in enumerate(boxes):
            bbox = (max(0, x - 3), max(0, y - 3), min(frame.width, x + w + 3), min(frame.height, y + h + 3))
            try:
                resp = client.shadow_predict(
                    frame, "post_game_hub_label", {"index": index, "bbox": bbox, "kind": "text"}
                )
            except Exception as exc:  # OCR is advisory; a worker hiccup is a miss.
                print(f"[med] 传家宝标签 OCR 兜底调用失败：{exc}")
                continue
            text = str(getattr(resp, "raw_text", "") or "").replace(" ", "")
            score = float(getattr(resp, "rec_score", 0.0) or 0.0)
            if (
                str(getattr(resp, "status", "") or "").lower() == "ok"
                and "传家宝" in text
                and score >= self._HUB_LABEL_OCR_MIN_SCORE
            ):
                found = (x, y, w, h, score)
                break
        last = self._hub_label_ocr_last
        self._hub_label_ocr_last = (found, frame) if found is not None else None
        if found is None:
            return None
        x, y, w, h, score = found
        stable = (
            last is not None
            and last[1] is not frame
            and abs(last[0][0] - x) <= self._HUB_LABEL_OCR_STABLE_PX
            and abs(last[0][1] - y) <= self._HUB_LABEL_OCR_STABLE_PX
        )
        if not stable:
            print(f"[med] 传家宝标签模板未命中，OCR 兜底首帧读到 @ ({x},{y})，等待第二帧确认（零动作）")
            return None
        print(f"[med] 传家宝标签 OCR 兜底两帧确认 @ ({x},{y}) score={score:.2f}")
        return MatchResult(
            "heirloom_label_ocr", score, x, y, w, h, frame.left + x + w // 2, frame.top + y + h // 2
        )

    def _post_game_hub_entry_click(self, frame: Frame, route: str) -> MatchResult | None:
        """Turn a verified hub label into a click on the corresponding NPC."""
        label = self._find_post_game_hub_entry(frame, route)
        if label is None and route == "heirloom":
            label = self._heirloom_label_ocr_fallback(frame)
        if label is None:
            return None
        # The label is above the NPC in both the real 1600x900 capture and the
        # 1597x929 replay fixture. Keep the offset relative to the frame, not a
        # second hard-coded screen coordinate.
        x = label.x + label.w // 2
        y = min(frame.height - 1, label.y + label.h + max(18, int(frame.height * 0.03)))
        return MatchResult(
            f"post_game_{route}_npc",
            label.score,
            max(0, x - label.w // 2),
            y,
            label.w,
            label.h,
            frame.left + x,
            frame.top + y,
        )

    def _post_game_state(self, frame: Frame) -> str | None:
        """Multi-anchor post-game page classifier.

        Combines legacy-template anchors with normalized position checks. The
        legacy anchors alone are NOT page-specific (archiveChallenge/cjb/ok/close
        all hit shared post-game HUD elements), so position disambiguation is
        required. Thresholds validated against fixtures/reborn_wow/endgame/*.

        N2.1/N2.2：每 evidence 只算一次（memo）；每个模板按已知位置裁 ROI 并
        只试主尺度；选择面板存在时跳过战后独占页（ARCHIVE_PANEL/NPC_HUB）扫描
        —— 战后独占页不可能与局内选择面板同时出现。

        Returns one of:
          PAUSED              game pause overlay (zero-action wait)
          POST_VICTORY        victory modal + continue button
          HEIRLOOM_DIALOG     heirloom boss dialog (cjbtiaozhan banner)
          GREAT_RIFT_CONFIRM  great-rift confirm dialog (center ok/mijingOk)
          ARCHIVE_PANEL       archive challenge panel (modal close, no rift NPC)
          NPC_HUB             post-victory world lobby (quit top-left + rift NPC right)
        or None when no post-game page is recognized.

        A configured Boss challenge that has been accepted is deliberately not
        classified as NPC_HUB while its active route is ``boss_active``.  The
        game can still render the archive/heirloom NPC labels over the live map
        during the challenge; those labels are not evidence that the battle is
        over.
        """
        w, h = frame.width, frame.height
        if w < 480 or h < 270:
            return None
        key = ("post_game", round(self._ui_scale, 3))

        def compute() -> str | None:
            self._post_game_archive_pending_only = False

            def find(name: str, threshold: float) -> MatchResult | None:
                return self.find(
                    frame,
                    [name],
                    threshold=threshold,
                    scales=self._hot_scales(),
                    roi=self._POST_GAME_ROIS.get(name),
                )

            # Pause overlay must precede generic center-button classifiers.
            paused = find("pauseGame", 0.80)
            if paused:
                px = paused.screen_x - frame.left
                py = paused.screen_y - frame.top
                if w * 0.35 <= px <= w * 0.60 and h * 0.35 <= py <= h * 0.55:
                    return "PAUSED"

            for name in ("pause_continue_game", "pause_return_game"):
                pause_button = find(name, 0.70)
                if pause_button:
                    px = pause_button.screen_x - frame.left
                    py = pause_button.screen_y - frame.top
                    if w * 0.35 <= px <= w * 0.65 and h * 0.20 <= py <= h * 0.55:
                        return "PAUSED"

            # 1) Victory: continue button is unique to the victory modal.
            if find("continueGame", 0.80):
                return "POST_VICTORY"
            # The 胜利 banner animates in over the archive panel before 继续游戏
            # is drawn (live 12:13, 0.97-1.0 on every victory frame, <=0.65
            # elsewhere).  Without it that frame read as ARCHIVE_PANEL and the
            # passenger started the archive chain under the victory modal.
            if self.find(
                frame, ["env/victory_banner"], threshold=0.85,
                scales=self._hot_scales(), roi=(0.35, 0.10, 0.65, 0.40),
            ):
                return "POST_VICTORY"

            # 2) Heirloom: cjbtiaozhan banner is unique to the heirloom dialog.
            if find("cjbtiaozhan", 0.80):
                return "HEIRLOOM_DIALOG"

            # 3) Great rift confirm: the grey 是 button (mijingOk 0.91 on the
            #    real dialog).  The generic orange ok/确认 is not rift evidence:
            #    live 2026-09-12 the player's own 退出游戏 confirmation scored
            #    0.97 on it and was "cancelled" as a rift, and the failure modal
            #    reached mijingOk 0.753 under the old 0.75 floor.
            m = find("mijingOk", 0.85)
            if (
                m and w * 0.30 <= m.x <= w * 0.60 and h * 0.40 <= m.y <= h * 0.65
                and self._find_exit_confirm(frame) is None
            ):
                # 提前挑战确认框用同一个灰色「是」。标题区分：大秘境=红字「大秘境」
                # + 黄字「是否开启大秘境挑战？」；提前挑战=白字「是否确认提前挑战？」。
                kind = self._grey_yes_dialog_kind(frame, m)
                self._great_rift_title_verified = kind == "rift"
                return "TQTZ_CONFIRM" if kind == "tqtz" else "GREAT_RIFT_CONFIRM"

            # 新版挑战广场底部的普通物品会误命中 heroRefresh；在前景弹窗
            # 均被排除后，三个页面专属锚点足以确认 NPC_HUB。
            hub_quit = find("quit", 0.75)
            hub_rift = find("damijing", 0.80)
            hub_hero = find("HeroChallenge", 0.85)
            if (
                hub_quit and hub_quit.x <= w * 0.10 and hub_quit.y <= h * 0.15
                and hub_rift and w * 0.45 <= hub_rift.x <= w * 0.70 and h * 0.15 <= hub_rift.y <= h * 0.55
                and hub_hero and w * 0.15 <= hub_hero.x <= w * 0.35 and hub_hero.y <= h * 0.15
                and getattr(self, "_post_game_route", "") != "boss_active"
                # B4：存档面板关闭按钮可见 ⇒ 这是 ARCHIVE_PANEL 不是纯 NPC_HUB；
                # 两类战后页面互斥，绝不互相触发。
                and self._find_archive_panel_close(frame) is None
            ):
                return "NPC_HUB"

            # 选择面板不再扫描存档/广场等底层页面；前景胜利、传家宝、
            # 秘境确认和三锚点广场已在此之前排除。
            if self._selection_anchor(frame) and not self._post_game_pending:
                return None

            # 4) Archive panel. Keep the original high-confidence path for
            # legacy pages, and accept the modal close button when archive evidence is present.
            rift_npc = hub_rift
            rift_npc_right = bool(rift_npc and rift_npc.x >= w * 0.55 and h * 0.15 <= rift_npc.y <= h * 0.55)
            legacy_arch = find("archiveChallenge", 0.85)
            legacy_close = find("close", 0.85)
            if legacy_arch and legacy_close and legacy_close.x >= w * 0.55 and legacy_close.y <= h * 0.40 and not rift_npc_right:
                return "ARCHIVE_PANEL"
            arch = self.find(
                frame, ["archiveChallenge"], threshold=0.60,
                scales=(0.50, 0.60, 0.70, 0.80, 0.90, 1.00, 1.10, 1.20, 1.30, 1.40, 1.50),
                roi=(0.48, 0.15, 0.68, 0.45),
            )
            close_hit = self._find_archive_panel_close(frame)
            completed_cards = sum(self._archive_challenge_completed(frame, index) for index in range(8))
            archive_scene = self.find_scene(frame, "archive")
            strong_archive_evidence = (
                completed_cards == len(self._ARCHIVE_CHALLENGE_NAMES)
                or arch is not None
                or archive_scene is not None
            )
            if (
                close_hit
                and (
                    strong_archive_evidence
                    or getattr(self, "_post_game_pending", False)
                )
                and close_hit.x >= w * 0.55
                and close_hit.y <= h * 0.40
                and not (not arch and not getattr(self, "_post_game_pending", False) and rift_npc_right)
            ):
                self._post_game_archive_pending_only = (
                    not strong_archive_evidence
                    and getattr(self, "_post_game_pending", False)
                )
                return "ARCHIVE_PANEL"

            # 5) NPC hub: quit button at the very top-left + rift NPC on the right +
            #    the hero challenge indicator.  Newer real frames omit the
            #    HeroChallenge marker, so the two page-specific hub labels are
            #    accepted as the equivalent second page evidence.
            quit_hit = find("quit", 0.75)
            hero_hit = find("HeroChallenge", 0.85)
            hub_archive = self._find_post_game_hub_entry(frame, "archive")
            hub_heirloom = self._find_post_game_hub_entry(frame, "heirloom")
            if (
                getattr(self, "_post_game_route", "") != "boss_active"
                and
                quit_hit
                and quit_hit.x <= w * 0.10
                and quit_hit.y <= h * 0.15
                and (
                    (rift_npc_right and hero_hit)
                    or self._post_game_hub_label_pair(frame, hub_archive, hub_heirloom)
                    # Live 2026-09-12 f0333: the camera left only the 传家宝挑战
                    # label in reach.  The top bar's 存档 mode label (0.97 on
                    # every plaza frame, absent from wave HUDs) is the page
                    # evidence; one NPC label anchors the hub itself.
                    or (
                        getattr(self, "_post_game_pending", False)
                        and self._top_bar_mode(frame) == "plaza"
                        and (hub_archive is not None or hub_heirloom is not None)
                    )
                )
                # B4：与 ARCHIVE_PANEL 互斥——关闭按钮可见时不分类为 NPC_HUB。
                and close_hit is None
            ):
                return "NPC_HUB"

            return None

        return self._memo(key, frame, compute)

    # The mode label right of the top-bar clock: 第N/5波 during waves, 存档 on
    # the post-game plaza (and its archive/heirloom pages), 团本 in a raid.
    _TOP_BAR_LABEL_ROI = (0.38, 0.0, 0.47, 0.07)

    def _top_bar_mode(self, frame: Frame) -> str | None:
        """'plaza' (存档), 'raid' (团本) or None (a wave counter / unknown)."""
        if frame.bgr is None or frame.width < 480 or frame.height < 270:
            return None
        plaza = self.find(frame, ["cundangInfo"], threshold=0.85, roi=self._TOP_BAR_LABEL_ROI)
        # 团本 scores 0.63 against 存档, so it must clear its own high floor
        # and beat the plaza label.
        raid = self.find(frame, ["tuanben"], threshold=0.85, roi=self._TOP_BAR_LABEL_ROI)
        if raid is not None and (plaza is None or raid.score > plaza.score):
            return "raid"
        if plaza is not None:
            return "plaza"
        return None

    _HITCH_INSTANCE_FRAMES = 3
    _HITCH_HEIRLOOM_EXIT_S = 60.0
    # Solo fights its own heirloom Boss, so it gets a longer window (user,
    # 2026-09-14: "逻辑一样时间放长一点").
    _SOLO_HEIRLOOM_EXIT_S = 120.0
    _HITCH_POSTGAME_HARD_CAP_S = 300.0

    def _heirloom_exit_window_s(self) -> float:
        return self._HITCH_HEIRLOOM_EXIT_S if self._passenger_mode() else self._SOLO_HEIRLOOM_EXIT_S

    def _solo_heirloom_secret(self) -> bool:
        """Solo with auto secret realm: the heirloom rule arms the rift."""
        return not self._passenger_mode() and bool(getattr(self.settings, "auto_secret_realm", False))

    def _hitch_left_plaza(self, frame: Frame) -> bool:
        """After the heirloom click: were we moved into 秘境 / 团本?

        The host starts those from the plaza and the whole team is
        teleported, so a passenger sees it as the plaza mode label going
        away while the in-game chrome (top-left 退出游戏) stays - over three
        distinct frames, so a loading screen or a dialog is not a verdict.
        The top bar's 团本 label is a verdict on its own.  Latched until the
        next heirloom wait.
        """
        if getattr(self, "_hitch_instance_seen", False):
            return True
        mode = self._top_bar_mode(frame)
        if mode == "raid":
            self._hitch_instance_seen = True
            return True
        if mode == "plaza":
            self._hitch_instance_frames = 0
            self._hitch_instance_last_frame = None
            return False
        quit_hit = self.find(frame, ["quit"], threshold=0.75, roi=(0.0, 0.0, 0.12, 0.08))
        if quit_hit is None or self._post_game_state(frame) is not None:
            self._hitch_instance_frames = 0
            self._hitch_instance_last_frame = None
            return False
        if self.find_scene(frame, "fail") or self.find_scene(frame, "disconnect"):
            self._hitch_instance_frames = 0
            self._hitch_instance_last_frame = None
            return False
        # Hold the counted frame itself: ids of freed frames get reused.
        if frame is not getattr(self, "_hitch_instance_last_frame", None):
            self._hitch_instance_last_frame = frame
            self._hitch_instance_frames = int(getattr(self, "_hitch_instance_frames", 0) or 0) + 1
        if self._hitch_instance_frames >= self._HITCH_INSTANCE_FRAMES:
            self._hitch_instance_seen = True
        return bool(self._hitch_instance_seen)

    def _find_archive_panel_close(self, frame: Frame) -> MatchResult | None:
        hit = self.find(
            frame,
            ["lobby/archive_panel_close"],
            threshold=0.80,
            scales=self._hot_scales(),
            roi=(0.55, 0.15, 0.70, 0.35),
        )
        if hit and frame.width * 0.55 <= hit.x <= frame.width * 0.70 and frame.height * 0.15 <= hit.y <= frame.height * 0.35:
            return hit
        hit = self.find(
            frame,
            ["close"],
            threshold=0.80,
            scales=self._hot_scales(),
            roi=(0.55, 0.15, 0.70, 0.35),
        )
        if hit and frame.width * 0.55 <= hit.x <= frame.width * 0.70 and frame.height * 0.15 <= hit.y <= frame.height * 0.35:
            return hit
        return None

    def _find_heirloom_close(self, frame: Frame) -> MatchResult | None:
        hit = self.find(frame, ["close"], threshold=0.85, scales=self._hot_scales(), roi=(0.55, 0.15, 0.70, 0.35))
        if not hit:
            return None
        if not (frame.width * 0.55 <= hit.x <= frame.width * 0.70):
            return None
        if not (frame.height * 0.15 <= hit.y <= frame.height * 0.35):
            return None
        return hit

    def _find_great_rift_cancel(self, frame: Frame) -> MatchResult | None:
        yes = self.find(frame, ["mijingOk", "ok"], threshold=0.80, scales=self._hot_scales(), roi=(0.30, 0.40, 0.60, 0.65))
        if not yes:
            return None
        yes_x, yes_y = yes.center
        x = yes_x - frame.left + int(frame.width * 0.104)
        y = yes_y - frame.top
        if not (frame.width * 0.50 <= x <= frame.width * 0.65):
            return None
        if not (frame.height * 0.45 <= y <= frame.height * 0.60):
            return None
        return MatchResult("great_rift_cancel", yes.score, x, y, 0, 0, frame.left + x, frame.top + y)

    def _configured_boss_challenge_names(self) -> list[str]:
        names: list[str] = []
        for boss in (self.settings.cjb_boss, self.settings.sgzx_boss):
            text = str(boss or "").strip()
            if text and text not in names:
                names.append(text)
        return names

    def _last_visible_boss_hit(self, frame: Frame) -> MatchResult | None:
        """Find the final visible challenge card through its verified template."""
        names = [
            f"{folder}/{image.stem}"
            for folder in ("chuanjiaobao", "boss")
            for image in (self.images / folder).glob("*.png")
        ]
        hits = match_all(
            frame,
            self.images,
            names,
            threshold=self.settings.match_threshold,
            scales=self._adapt_scales((1.0,)),
            max_results=96,
        )
        return max(hits, key=lambda hit: (hit.y + hit.h, hit.x + hit.w), default=None)

    def _maybe_challenge_configured_boss(
        self, frame: Frame, now: float, *, recheck_s: float | None = None
    ) -> LoopAction | None:
        """Click configured Boss card when the Boss challenge entry is visible."""
        post_game = self._post_game_state(frame)
        if post_game is None and getattr(self, "_post_game_pending", False):
            # After Continue, an unclassified transition frame is observation-only.
            # Keep the existing HUD early-challenge path available when no
            # post-game route is pending, but never search or click through it.
            print("[med] 战后页面未分类，Boss 挑战零输入等待")
            return LoopAction.Continue
        bosses = self._configured_boss_challenge_names()
        if post_game in ("ARCHIVE_PANEL", "HEIRLOOM_DIALOG"):
            previous_page = getattr(self, "_boss_challenge_page", None)
            if previous_page is not None and previous_page != post_game:
                # Every list owns an independent navigation budget and bottom
                # evidence; time-cave state must not leak into heirloom.
                self._boss_challenge_attempts = 0
                self._boss_challenge_scroll_attempts = 0
                self._boss_challenge_scroll_signature = None
                self._boss_challenge_scroll_stable_frames = 0
                self._boss_challenge_scroll_top_stable_frames = 0
                self._boss_challenge_unresolved_attempts = 0
                self._boss_challenge_locate_attempts = 0
                self._boss_challenge_locate_exhausted = False
                self._boss_challenge_bottom_scroll_attempts = 0
                self._boss_challenge_next_at = 0.0
            self._boss_challenge_page = post_game
        if post_game == "ARCHIVE_PANEL":
            configured = str(getattr(self.settings, "sgzx_boss", "") or "").strip()
            bosses = [configured] if configured else []
        elif post_game == "HEIRLOOM_DIALOG":
            configured = str(getattr(self.settings, "cjb_boss", "") or "").strip()
            bosses = [configured] if configured else []
        compact_roi = self._POST_GAME_BOSS_ROIS.get(post_game or "")
        if not bosses and compact_roi is None:
            print("[med] 非战后 Boss 入口未配置目标，零输入")
            return None

        # A Boss click is one-shot until heirloom has either shown its result
        # or its bounded confirmation window expires.
        if (
            post_game == "HEIRLOOM_DIALOG"
            and self._boss_challenge_attempts > 0
            and getattr(self, "_heirloom_boss_clicked_at", None) is not None
        ):
            if self._heirloom_boss_result_visible(frame):
                print("[med] 传家宝 Boss 后置已确认，停止重复点击")
            elif self._heirloom_boss_confirm_expired(now):
                print(
                    f"[med] 传家宝 Boss 后置 {self._HEIRLOOM_BOSS_CONFIRM_TIMEOUT_S:.0f}s 未出现，"
                    "有界收敛并允许关闭弹窗（不计成功）"
                )
            else:
                print("[med] 传家宝 Boss 已发起，等待‘已挑战’后置（零动作）")
            return LoopAction.Continue
        if self._boss_challenge_attempts >= 3:
            return LoopAction.Continue
        if now < self._boss_challenge_next_at:
            return LoopAction.Continue

        boss_hit = None
        if bosses and compact_roi is not None:
            # The page classifier already proved where these compact cards can
            # exist.  Searching the entire 1600x900 frame first delayed the
            # post-game chain by a full template pass per card, after other
            # players had already left the lobby.
            compact_scales = self._adapt_scales(self._POST_GAME_BOSS_SCALES)
            for name in bosses:
                boss_hit = self.find(
                    frame,
                    [name, f"boss/{name}", f"chuanjiaobao/{name}"],
                    threshold=self._POST_GAME_BOSS_MATCH_THRESHOLD,
                    scales=compact_scales,
                    roi=compact_roi,
                    mode="post-game-boss-grid",
                )
                if boss_hit is not None:
                    break
        else:
            # Outside a classified post-game list, retain the legacy
            # full-frame search: we do not infer a list ROI from UNKNOWN.
            for name in bosses:
                boss_hit = self.find(
                    frame,
                    [name, f"boss/{name}", f"chuanjiaobao/{name}"],
                    threshold=0.80,
                    scales=self._hot_scales(),
                )
                if boss_hit is not None:
                    break
            if boss_hit is None and bosses and self._post_game_pending:
                compact_scales = self._adapt_scales(self._POST_GAME_BOSS_SCALES)
                for name in bosses:
                    for roi in self._POST_GAME_BOSS_ROIS.values():
                        boss_hit = self.find(
                            frame,
                            [name, f"boss/{name}", f"chuanjiaobao/{name}"],
                            threshold=self._POST_GAME_BOSS_MATCH_THRESHOLD,
                            scales=compact_scales,
                            roi=roi,
                            mode="post-game-boss-grid",
                        )
                        if boss_hit is not None:
                            break
                    if boss_hit is not None:
                        break

        # A compact-list ROI clips candidate top-left positions, not their
        # centres.  Reject a card whose click point spills outside the list;
        # live 2026-09-20 otherwise clicked a notification at (1390, 602)
        # instead of Time Cave card 15.
        if boss_hit is not None and compact_roi is not None:
            x0, y0, x1, y1 = self._normalized_bbox(frame, compact_roi)
            cx, cy = boss_hit.center
            if not (x0 <= cx <= x1 and y0 <= cy <= y1):
                print(f"[med] Boss 列表命中越界，忽略 {boss_hit.name} @ {boss_hit.center}")
                boss_hit = None

        used_fallback = False
        action_name = "BossConfigured"
        # A target can already be partly visible on the next row even though
        # the all-card pass cannot clear its normal threshold.  Use the
        # verified grid geometry to inspect that one slot before scrolling:
        # this fixes the live Time Cave 15-slot being obscured by a toast,
        # without broadening the click authority beyond a classified panel.
        if boss_hit is None and compact_roi is not None and bosses:
            target_name = bosses[0]
            target_no = parse_boss_order_number(
                target_name, getattr(self, "_boss_catalog_cache", None)
            )
            if target_no is not None:
                visible_pairs = self._find_visible_post_game_boss_cards(frame, post_game)
                predicted_box = predict_card_slot(
                    target_no,
                    [card for card, _hit in visible_pairs],
                    cols_per_row=4,
                )
                if predicted_box is not None:
                    boss_hit = self._verify_boss_predicted_slot(
                        frame, post_game, target_name, predicted_box
                    )
                    if boss_hit is not None:
                        print(
                            f"[med] Boss {target_name} 在预测格位获得受限证据，"
                            f"直接点击 @ {boss_hit.center}"
                        )
        if boss_hit is None and compact_roi is not None:
            target_name = bosses[0] if bosses else None
            target_no = parse_boss_order_number(target_name, getattr(self, "_boss_catalog_cache", None))
            visible_pairs = self._find_visible_post_game_boss_cards(frame, post_game)
            visible_cards = [vc for vc, mr in visible_pairs]
            card_map = {vc.no: mr for vc, mr in visible_pairs}

            vx0 = int(frame.width * compact_roi[0])
            vy0 = int(frame.height * compact_roi[1])
            vx1 = int(frame.width * compact_roi[2])
            vy1 = int(frame.height * compact_roi[3])
            viewport_box = (vx0, vy0, vx1, vy1)

            def check_slot_empty(b: tuple[int, int, int, int]) -> bool:
                if frame.bgr is None or frame.bgr.size == 0:
                    return True
                bx0, by0 = max(0, b[0]), max(0, b[1])
                bx1, by1 = min(frame.width, b[0] + b[2]), min(frame.height, b[1] + b[3])
                crop = frame.bgr[by0:by1, bx0:bx1]
                return is_slot_empty(crop)

            grid_end_hit, grid_end_candidate = self._post_game_boss_grid_end_card(
                frame, post_game, visible_pairs, check_slot_empty
            )
            if grid_end_candidate and grid_end_hit is None:
                self._boss_challenge_next_at = now + self._post_game_action_recheck(recheck_s)
                return LoopAction.Continue
            at_bottom = self._post_game_boss_list_at_bottom(frame, post_game) or grid_end_hit is not None
            at_top = self._post_game_boss_list_at_top(frame, post_game)

            decision = decide_boss_order_action(
                target_no,
                visible_cards,
                at_bottom=at_bottom,
                at_top=at_top,
                scroll_attempts=self._boss_challenge_scroll_attempts,
                scroll_limit=self._POST_GAME_BOSS_SCROLL_LIMIT,
                locate_attempts=getattr(self, "_boss_challenge_locate_attempts", 0),
                locate_limit=getattr(self, "_POST_GAME_BOSS_LOCATE_LIMIT", 3),
                locate_exhausted=getattr(self, "_boss_challenge_locate_exhausted", False),
                bottom_scroll_attempts=getattr(self, "_boss_challenge_bottom_scroll_attempts", 0),
                bottom_scroll_limit=self._POST_GAME_BOSS_SCROLL_LIMIT,
                page_type=post_game or "",
                can_scroll=not self._post_game_boss_has_no_scrollbar(frame, post_game),
                viewport_box=viewport_box,
                slot_empty_checker=check_slot_empty,
                frame_bgr=frame.bgr,
                catalog=getattr(self, "_boss_catalog_cache", None),
            )

            if decision.action == BossOrderAction.CLICK_TARGET:
                boss_hit = card_map.get(decision.target_card.no) if decision.target_card else None
                action_name = "BossConfigured"
            elif decision.action == BossOrderAction.CONFIRM_PREDICTED:
                boss_hit = self._verify_boss_predicted_slot(frame, post_game, target_name, decision.predicted_box)
                if boss_hit is not None:
                    action_name = "BossConfigured"
                else:
                    self._boss_challenge_locate_attempts = getattr(self, "_boss_challenge_locate_attempts", 0) + 1
                    if self._boss_challenge_locate_attempts >= self._POST_GAME_BOSS_LOCATE_LIMIT:
                        self._boss_challenge_locate_exhausted = True
                    print(
                        f"[med] 预测格位未获得有效证据 "
                        f"({self._boss_challenge_locate_attempts}/{self._POST_GAME_BOSS_LOCATE_LIMIT})，零输入等待"
                    )
                    self._boss_challenge_next_at = now + self._post_game_action_recheck(recheck_s)
                    return LoopAction.Continue
            elif decision.action == BossOrderAction.SCROLL_DOWN:
                scroll_point = self._post_game_boss_scroll_point(frame, post_game)
                if scroll_point is None:
                    print("[med] 已分类 Boss 列表缺少受约束滚动点，零输入等待")
                    return LoopAction.Continue
                is_bottom_fallback = (decision.stage == "return_to_bottom") or ("回到底部" in decision.reason)
                if is_bottom_fallback:
                    self._boss_challenge_locate_exhausted = True
                    next_attempt = getattr(self, "_boss_challenge_bottom_scroll_attempts", 0) + 1
                    scroll_tag = "BossConfigured-scroll-bottom"
                    log_limit = f"{next_attempt}/{self._POST_GAME_BOSS_SCROLL_LIMIT}"
                else:
                    next_attempt = self._boss_challenge_scroll_attempts + 1
                    scroll_tag = "BossConfigured-scroll"
                    log_limit = f"{next_attempt}/{self._POST_GAME_BOSS_SCROLL_LIMIT}"
                self._boss_challenge_next_at = now + self._post_game_action_recheck(recheck_s)
                x, y = scroll_point
                print(f"[med] {decision.reason}，向下滚动挑战列表 ({log_limit})")
                self._boss_challenge_scroll_grid_fp = self._post_game_boss_grid_fingerprint(frame, post_game)
                if self.act_scroll(x, y, self._post_game_boss_scroll_step, scroll_tag):
                    if is_bottom_fallback:
                        self._boss_challenge_bottom_scroll_attempts = next_attempt
                    else:
                        self._boss_challenge_scroll_attempts = next_attempt
                    self._boss_challenge_unresolved_attempts = 0
                return LoopAction.Continue
            elif decision.action == BossOrderAction.SCROLL_UP:
                scroll_point = self._post_game_boss_scroll_point(frame, post_game)
                if scroll_point is None:
                    print("[med] 已分类 Boss 列表缺少受约束滚动点，零输入等待")
                    return LoopAction.Continue
                next_attempt = self._boss_challenge_scroll_attempts + 1
                self._boss_challenge_next_at = now + self._post_game_action_recheck(recheck_s)
                x, y = scroll_point
                print(
                    f"[med] {decision.reason}，"
                    f"向上滚动挑战列表 ({next_attempt}/{self._POST_GAME_BOSS_SCROLL_LIMIT})"
                )
                if self.act_scroll(x, y, abs(self._post_game_boss_scroll_step), "BossConfigured-scroll-up"):
                    self._boss_challenge_scroll_attempts = next_attempt
                    self._boss_challenge_unresolved_attempts = 0
                return LoopAction.Continue
            elif decision.action == BossOrderAction.CLICK_LAST_NOT_UNLOCKED:
                boss_hit = self._find_last_recognized_post_game_boss(frame, post_game)
                used_fallback = boss_hit is not None
                if boss_hit is None:
                    loop_act, boss_hit, act_name = self._handle_boss_anomaly_retry_or_skip(frame, now, post_game, recheck_s)
                    if boss_hit is not None:
                        used_fallback = True
                        action_name = act_name
                    else:
                        return loop_act
                else:
                    action_name = "BossNotUnlockedLast" if bosses else "BossBottomFallback"
                    source = "未配置" if not bosses else f"配置 Boss {bosses} 未解锁 (T > L)"
                    print(f"[med] [BossNotUnlockedLast] {source}，列表已确认到底，兜底点击物理最后卡 {boss_hit.name} @ {boss_hit.center}")
            elif decision.action == BossOrderAction.CLICK_LAST_LOCATE_FAILED:
                boss_hit = self._find_last_recognized_post_game_boss(frame, post_game)
                used_fallback = boss_hit is not None
                if boss_hit is None:
                    loop_act, boss_hit, act_name = self._handle_boss_anomaly_retry_or_skip(frame, now, post_game, recheck_s)
                    if boss_hit is not None:
                        used_fallback = True
                        action_name = act_name
                    else:
                        return loop_act
                else:
                    action_name = "BossOrderLocateFailed"
                    print(
                        f"[med] BossOrderLocateFailed: 目标 Boss {bosses} 定位失败（尝试耗尽），"
                        f"兜底点击末卡 {boss_hit.name} @ {boss_hit.center}"
                    )
                    self._record_boss_locate_failed_incident(bosses, boss_hit.name)
            elif decision.action == BossOrderAction.WAIT:
                self._boss_challenge_unresolved_attempts += 1
                if self._boss_challenge_unresolved_attempts >= self._POST_GAME_BOSS_UNRESOLVED_LIMIT:
                    # A lower-right card visible mid-list is not a fallback.
                    # It becomes one only once the scrollbar or the explicit
                    # full-row/partial-row-empty-slot witness proves the end.
                    last_card = (
                        grid_end_hit
                        if grid_end_hit is not None
                        else (
                            self._find_last_recognized_post_game_boss(frame, post_game)
                            if at_bottom else None
                        )
                    )
                    if last_card is not None:
                        boss_hit = last_card
                        used_fallback = True
                        action_name = "BossLastVisibleFallback"
                        self._boss_challenge_unresolved_attempts = 0
                        print(
                            f"[med] [BossLastVisibleFallback] {decision.reason}，未决达到上限 "
                            f"({self._POST_GAME_BOSS_UNRESOLVED_LIMIT})，兜底点击画面内物理最后卡 "
                            f"{boss_hit.name} @ {boss_hit.center}"
                        )
                    else:
                        loop_act, boss_hit, act_name = self._handle_boss_anomaly_retry_or_skip(frame, now, post_game, recheck_s)
                        if boss_hit is not None:
                            used_fallback = True
                            action_name = act_name
                        else:
                            return loop_act
                else:
                    self._boss_challenge_next_at = now + self._post_game_action_recheck(recheck_s)
                    print(f"[med] {decision.reason}，零输入等待")
                    return LoopAction.Continue

        self._boss_challenge_attempts += 1
        delay = (
            self._post_game_action_recheck(recheck_s)
            if compact_roi is not None
            else self._challenge_recheck_delay()
        )
        self._boss_challenge_next_at = now + delay
        if boss_hit is None:
            print(
                f"[med] boss_entry 未匹配到配置 Boss {bosses} "
                f"（尝试 {self._boss_challenge_attempts}/3），零输入等待"
            )
            return LoopAction.Continue

        if not used_fallback:
            print(f"[med] Boss 挑战：点击配置 Boss {boss_hit.name} @ {boss_hit.center} (尝试 {self._boss_challenge_attempts}/3)")
        if self.act_click(boss_hit, action_name):
            self._main_line_since = now
            self._boss_anomaly_retry_attempts = 0
            if hasattr(self, "_boss_anomaly_skip_counts") and post_game in self._boss_anomaly_skip_counts:
                self._boss_anomaly_skip_counts[post_game] = 0
            if post_game == "ARCHIVE_PANEL":
                # A click request is not a Time Cave challenge.  Keep the
                # panel owned until a later classified surface proves it left.
                self._time_cave_boss_clicked_at = now
                self._boss_challenge_next_at = now + self._post_game_action_recheck(recheck_s)
            elif post_game == "HEIRLOOM_DIALOG" and getattr(self, "_post_game_pending", False):
                self._post_game_route = "heirloom_active"
                self._heirloom_boss_clicked_at = now
            if getattr(self, "_early_challenge_pending", False):
                self._early_challenge_clicked_at = now
        return LoopAction.Continue

    #: 传家宝 Boss 点击后等待「已挑战」的上限。3s 在实测 1.64s/tick 的节拍下
    #: 只够 1.8 个 tick，等于没给后置确认第二次机会；6s 至少覆盖三帧新证据。
    _HEIRLOOM_BOSS_CONFIRM_TIMEOUT_S = 6.0

    def _heirloom_boss_confirm_expired(self, now: float) -> bool:
        """True once the post-click confirm window has run out.

        Records the miss so the outcome stays honest: the page is allowed to
        close, but nothing reports the challenge as confirmed.
        """
        clicked_at = getattr(self, "_heirloom_boss_clicked_at", None)
        if clicked_at is None:
            return False
        if now - clicked_at < self._HEIRLOOM_BOSS_CONFIRM_TIMEOUT_S:
            return False
        self._heirloom_boss_confirm_unconfirmed = True
        return True

    def _heirloom_boss_result_visible(self, frame: Frame) -> bool:
        """Detect the live page's post-click ``已挑战`` result toast.

        The current game build renders this short red status toast below the
        heirloom dialog rather than changing the Boss card itself. This is a
        bounded postcondition check for the already-classified heirloom page;
        it grants no click authority and does not add another production FSM.

        The band used to be a 9%-wide, 6%-tall rectangle pinned to the frame
        centre.  Any window move, DPI change or the toast drifting a few
        percent put it outside, and the caller then waited for ever.  Search
        the dialog's whole lower-middle band instead; the connected-component
        floor below is what keeps combat VFX from passing.
        """
        if frame.bgr is None or frame.width < 480 or frame.height < 270:
            return False
        x0, x1 = int(frame.width * 0.34), int(frame.width * 0.66)
        y0, y1 = int(frame.height * 0.52), int(frame.height * 0.74)
        crop = frame.bgr[max(0, y0):min(frame.height, y1), max(0, x0):min(frame.width, x1)]
        if crop.size == 0:
            return False
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        red = (
            (((hsv[:, :, 0] <= 12) | (hsv[:, :, 0] >= 160)))
            & (hsv[:, :, 1] >= 100)
            & (hsv[:, :, 2] >= 100)
        )
        # Combat VFX can leak through the translucent dialog as scattered
        # red pixels.  A result toast has a compact connected text/background
        # region; require both enough red pixels and one meaningful component
        # so a live attack cannot authorize closing the page.
        red_mask = (red.astype(np.uint8) * 255)
        _count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(red_mask, 8)
        largest_component = max(
            (int(stat[cv2.CC_STAT_AREA]) for stat in stats[1:]),
            default=0,
        )
        return int(np.count_nonzero(red)) >= 100 and largest_component >= 50

    def _heirloom_loot_popup_visible(self, frame: Frame) -> bool:
        """Detect either the legacy toast or the live right-side loot list.

        The live build renders several aligned green ``已获取`` rows in the
        right-side equipment panel. This detector is only called after the
        configured heirloom Boss result has been confirmed and its dialog has
        closed, so it cannot grant click authority during ordinary combat.
        """
        hit = self.find(
            frame,
            ["zhuangbei"],
            threshold=0.75,
            scales=self._hot_scales(),
            roi=(0.32, 0.22, 0.68, 0.58),
        )
        if hit is not None and "zhuangbei" in str(getattr(hit, "name", "")):
            return True
        if frame.bgr is None or frame.width < 640 or frame.height < 360:
            return False

        x0, x1 = int(frame.width * 0.70), int(frame.width * 0.98)
        y0, y1 = int(frame.height * 0.12), int(frame.height * 0.72)
        crop = frame.bgr[y0:y1, x0:x1]
        if crop.size == 0:
            return False
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        green = (
            (hsv[:, :, 0] >= 35)
            & (hsv[:, :, 0] <= 95)
            & (hsv[:, :, 1] >= 90)
            & (hsv[:, :, 2] >= 110)
        )
        row_counts = np.count_nonzero(green, axis=1)
        strong_rows = np.flatnonzero(row_counts >= max(6, int(crop.shape[1] * 0.025)))
        if strong_rows.size == 0:
            return False

        bands: list[list[int]] = []
        for row in strong_rows:
            row_i = int(row)
            if not bands or row_i - bands[-1][-1] > 6:
                bands.append([row_i])
            else:
                bands[-1].append(row_i)

        candidates: list[tuple[float, float]] = []
        for band in bands:
            top, bottom = band[0], band[-1]
            band_mask = green[top : bottom + 1]
            if int(np.count_nonzero(band_mask)) < 40:
                continue
            columns = np.flatnonzero(np.any(band_mask, axis=0))
            if columns.size == 0:
                continue
            width = int(columns[-1] - columns[0] + 1)
            if width < 18 or width > int(crop.shape[1] * 0.18):
                continue
            candidates.append(
                ((top + bottom) / 2.0, (int(columns[0]) + int(columns[-1])) / 2.0)
            )

        min_gap = frame.height * 0.05
        max_gap = frame.height * 0.11
        max_x_drift = frame.width * 0.04
        for start in range(len(candidates)):
            chain = 1
            previous_y, previous_x = candidates[start]
            for current_y, current_x in candidates[start + 1 :]:
                gap = current_y - previous_y
                if gap > max_gap:
                    break
                if gap >= min_gap and abs(current_x - previous_x) <= max_x_drift:
                    chain += 1
                    previous_y, previous_x = current_y, current_x
                    if chain >= 3:
                        return True
        return False

    def _solo_boss_is_alive(self, frame: Frame) -> bool:
        """Visual detection of a live Boss health bar in the plaza."""
        if frame.bgr is None or frame.width <= 0 or frame.height <= 0:
            return False
        h, w = frame.height, frame.width
        x0, x1 = int(w * 0.25), int(w * 0.85)
        y0, y1 = int(h * 0.15), int(h * 0.65)
        plaza = frame.bgr[y0:y1, x0:x1]
        hsv = cv2.cvtColor(plaza, cv2.COLOR_BGR2HSV)
        red1 = (hsv[:, :, 0] <= 10) & (hsv[:, :, 1] >= 140) & (hsv[:, :, 2] >= 100)
        red2 = (hsv[:, :, 0] >= 170) & (hsv[:, :, 1] >= 140) & (hsv[:, :, 2] >= 100)
        red = (red1 | red2).astype(np.uint8) * 255
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3))
        closed = cv2.morphologyEx(red, cv2.MORPH_CLOSE, kernel)
        n_labels, _, stats, _ = cv2.connectedComponentsWithStats(closed, 8)
        for i in range(1, n_labels):
            bx, by, bw, bh, area = stats[i]
            if bw >= 80 and 8 <= bh <= 28 and area >= 800 and (bw / max(1, bh)) >= 3.8:
                roi_red = red[by:by + bh, bx:bx + bw]
                fill_ratio = np.count_nonzero(roi_red) / float(bw * bh)
                if fill_ratio >= 0.60:
                    return True
        return False

    def _solo_heirloom_boss_is_clear(self, frame: Frame) -> bool:
        """Two-frame reward proxy; vetoed if Boss health bar is visually alive."""
        if self._solo_boss_is_alive(frame):
            self._solo_heirloom_boss_clear_frames = 0
            self._solo_heirloom_boss_clear_last_frame = None
            return False
        clear = (
            self._top_bar_mode(frame) == "plaza"
            and self._heirloom_loot_popup_visible(frame)
        )
        if not clear:
            self._solo_heirloom_boss_clear_frames = 0
            self._solo_heirloom_boss_clear_last_frame = None
            return False
        if frame is not self._solo_heirloom_boss_clear_last_frame:
            self._solo_heirloom_boss_clear_last_frame = frame
            self._solo_heirloom_boss_clear_frames += 1
        return self._solo_heirloom_boss_clear_frames >= 2

    def _maybe_ensure_hero_panel_focus(self, frame: Frame, now: float) -> LoopAction | None:
        """Only recover hero focus from two distinct, positively identified HUD frames."""
        if self._panel_state != PanelState.CLOSED:
            return None
        if getattr(self, "_post_game_pending", False):
            return None
        if now < getattr(self, "_hero_focus_next_check_at", 0.0):
            return None

        # UNKNOWN/transition/black frames have zero input authority.  This is
        # deliberately checked before elevation and before the hero ROI: a
        # missing hero indicator is not evidence that the current page is HUD.
        if not self._is_in_game_hud(frame):
            self._hero_focus_lost_count = 0
            self._hero_focus_last_frame_id = None
            return None

        # Tests/offline replay cannot pre-empt the state machine; real input
        # still goes through the administrator/UIPI SendInput guard.
        from shuabao.input.keyboard_mouse import is_current_process_elevated
        if not is_current_process_elevated():
            return None

        self._hero_focus_next_check_at = now + 1.0
        hero_indicators = ["jihuo", "shortKey", "hc", "artifact_slot_e", "pingfu1"]
        hit = self.find(frame, hero_indicators, threshold=0.75, roi=(0.60, 0.60, 0.98, 0.98))
        if hit is not None:
            self._hero_focus_lost_count = 0
            self._hero_focus_last_frame_id = None
            return None
        # The bag page and its item tooltips cover the hero strip; that is our
        # own UI, not lost hero focus. F2 there would only fight the bag hop.
        bag_fsm = getattr(self, "_public_bag_fsm", None)
        if (bag_fsm is not None and bag_fsm.active) or self._bag_layout(frame) is not None:
            self._hero_focus_lost_count = 0
            self._hero_focus_last_frame_id = None
            return None

        frame_id = id(frame)
        if frame_id == getattr(self, "_hero_focus_last_frame_id", None):
            # capture() deliberately reuses the same Frame object for identical
            # frozen content.  Never convert repeated ticks of that object into
            # a two-frame authorization.
            return None
        self._hero_focus_last_frame_id = frame_id
        self._hero_focus_lost_count = getattr(self, "_hero_focus_lost_count", 0) + 1
        if self._hero_focus_lost_count < 2:
            print("[med] 英雄面板缺失候选第 1 帧，等待不同 HUD 帧确认（零动作）")
            return None

        print("[med] 连续两个不同 HUD 帧均缺英雄面板，发送 F2 回归阵地")
        if not getattr(self.settings, "dry_run", False):
            self.act_key("F2", "HeroFocusFallback")
        self._hero_focus_lost_count = 0
        self._hero_focus_last_frame_id = None
        self._hero_focus_next_check_at = now + 1.5
        return LoopAction.Continue

    def _maybe_ensure_post_game_hero_focus(self, frame: Frame, now: float) -> LoopAction | None:
        """In post-game NPC hub, recover hero focus via F1 if target focus was lost to mobs/bosses."""
        if self._panel_state != PanelState.CLOSED:
            return None
        if not getattr(self, "_post_game_pending", False):
            return None
        if self._has_active_transaction(frame):
            return None
        if now < getattr(self, "_post_game_hero_focus_next_check_at", 0.0):
            return None

        # UNKNOWN/transition frames have zero input authority.
        post_game = self._post_game_state(frame)
        if post_game != "NPC_HUB":
            self._post_game_hero_focus_lost_count = 0
            self._post_game_hero_focus_last_frame = None
            return None

        hero_indicators = ["jihuo", "shortKey", "hc", "artifact_slot_e", "pingfu1"]
        hit = self.find(frame, hero_indicators, threshold=0.75, roi=(0.60, 0.60, 0.98, 0.98))
        if hit is not None:
            self._post_game_hero_focus_lost_count = 0
            self._post_game_hero_focus_last_frame = None
            return None

        if frame is getattr(self, "_post_game_hero_focus_last_frame", None):
            return None
        self._post_game_hero_focus_last_frame = frame
        self._post_game_hero_focus_lost_count = getattr(self, "_post_game_hero_focus_lost_count", 0) + 1
        if self._post_game_hero_focus_lost_count < 2:
            print("[med] 战后广场英雄焦点丢失候选第 1 帧，等待不同帧确认（零动作）")
            return None

        print("[med] 战后广场连续 2 帧丢失英雄焦点，按 F1 重新选定自身英雄")
        if not getattr(self.settings, "dry_run", False):
            self.act_key("F1", "PostGameSelectHeroFocus")
        self._post_game_hero_focus_lost_count = 0
        self._post_game_hero_focus_last_frame = None
        self._post_game_hero_focus_next_check_at = now + 1.0
        return LoopAction.Continue
    # Icon centre sits 48px above the caption centre at 900px height.
    _TQTZ_ICON_LIFT = 48 / 900
    # The icon opens 「是否确认提前挑战？」 with the same grey 是/否 buttons as
    # the great-rift dialog (live 2026-09-14 f0582: classified
    # GREAT_RIFT_CONFIRM, mijingOk 0.91 @ (711,388), no rift 否 anchor ->
    # zero input until the Owner clicked 是 by hand).
    _TQTZ_DIALOG_WINDOW_S = 30.0

    def _tqtz_confirm_dialog_expected(self, frame: Frame, now: float) -> bool:
        """In-round 是/否 dialog that belongs to our own 提前挑战 click."""
        # _post_game_route defaults to "secret" inside the round, so only the
        # states that really are post-game exclude the dialog.
        if (
            self._post_game_pending
            or self._secret_realm_request_pending
            or getattr(self, "_hitch_heirloom_exit_since", None)
            or str(getattr(self, "_post_game_route", "")).endswith("_active")
        ):
            return False
        if getattr(self, "_tqtz_abandoned", False):
            return False
        if now <= getattr(self, "_tqtz_dialog_expected_until", 0.0):
            return True
        # Dialog opened without our click (manual / after the window): the
        # 提前挑战 caption is still on the HUD, which never happens on the
        # post-game plaza where the real rift dialog lives.
        return self._is_in_game_hud(frame) and self.find(
            frame, ["tqtz"], threshold=0.80, roi=(0.20, 0.03, 0.45, 0.15)
        ) is not None

    def _confirm_tqtz_dialog(self, frame: Frame, now: float) -> LoopAction:
        if now < getattr(self, "_tqtz_confirm_next_at", 0.0):
            return LoopAction.Continue
        attempts = getattr(self, "_tqtz_confirm_attempts", 0)
        if attempts >= 3:
            print("[early] 提前挑战确认框点「是」3 次未消失，放弃提前挑战（不再点）")
            self._tqtz_abandoned = True
            self._tqtz_pending = False
            self._early_challenge_pending = False
            self._tqtz_dialog_expected_until = 0.0
            return LoopAction.Continue
        accept_hit = self._find_great_rift_accept(frame)
        if accept_hit is None:
            print("[early] 提前挑战确认框未找到受锚定的「是」，零动作等待")
            return LoopAction.Continue
        self._tqtz_confirm_attempts = attempts + 1
        self._tqtz_confirm_next_at = now + 1.5
        self._tqtz_dialog_expected_until = max(
            getattr(self, "_tqtz_dialog_expected_until", 0.0), now + 5.0
        )
        print(f"[early] 提前挑战确认框：点击「是」@ {accept_hit.center}（{attempts + 1}/3）")
        if self.act_click(accept_hit, "ConfirmTQTZ"):
            # 是 summons the attack/final Boss directly; there is no Boss
            # picker to wait for, so the main loop resumes right away.
            self._tqtz_clicked = True
            self._tqtz_pending = False
            self._tqtz_pending_frame = None
            self._early_challenge_pending = False
            self._early_challenge_clicked_at = None
            self._main_line_since = now
        return LoopAction.Continue

    def _maybe_click_tqtz(self, frame: Frame, now: float) -> LoopAction | None:
        """局内检测到『提前挑战』图标（tqtz.png）时主动点击触发打 Boss。

        开放时间因人而异（Owner 2026-09-14）：常规 10 分钟，UR「时间管理大师」
        8 分钟，再叠远古神藏 EX「圣剑」6 分钟；前提都是 5-5 已打完。因此这里
        只认图标出现，绝不按固定时长门控或推断。

        点击成功 ≠ 挑战已接受（B1 修复）：点击只挂起 pending，随后必须在
        fresh 帧上确认图标消失（或 Boss 目标面出现）才落定 `_tqtz_clicked`；
        5 秒观察窗超时则清 pending 允许有界重试。
        """
        if getattr(self, "_tqtz_abandoned", False):
            # Abandoned means "stop trying", not "own the tick": returning
            # Continue here pre-empted every later main-line action for the
            # rest of the round (live solo 2026-09-14: zero input from 12min).
            return None
        if getattr(self, "_tqtz_pending", False):
            # C5 修复：同 generation / same request frame => ZERO INPUT => NOT CONFIRMED
            req_gen = getattr(self, "_tqtz_request_generation", None)
            cur_evidence = self._ensure_evidence(frame)
            cur_gen = cur_evidence.gen if cur_evidence else None
            if req_gen is not None and cur_gen is not None and cur_gen <= req_gen:
                # 墙钟硬截止：即使证据 generation 不前进（same Frame / frozen frame），
                # 5.0s 后 pending 也必须收敛，防止永久零输入挂起（C5 后续加固）。
                if now - self._tqtz_pending_since >= 5.0:
                    attempts = getattr(self, "_tqtz_attempts", 0)
                    self._tqtz_pending = False
                    self._tqtz_pending_frame = None
                    self._early_challenge_pending = False
                    if attempts >= 3:
                        self._tqtz_abandoned = True
                        self._tqtz_clicked = False
                        print("[early] tqtz 同帧证据 5s 墙钟超时且尝试已满 3 次，标记 ABANDONED")
                    else:
                        print(f"[early] tqtz 同帧证据 5s 墙钟超时，清 pending 允许重试（{attempts}/3）")
                return LoopAction.Continue

            # 观察窗内零输入等待
            if now < getattr(self, "_tqtz_next_check_at", 0.0):
                return LoopAction.Continue
            self._tqtz_next_check_at = now + 1.0

            tqtz_hit = self.find(
                frame,
                ["tqtz"],
                threshold=0.80,
                roi=(0.20, 0.03, 0.45, 0.15),
            )
            frame_valid = frame is not None and frame.bgr is not None and getattr(frame, "is_valid", True)
            boss_entry = self.find_scene(frame, "boss_entry")

            # 业务确认优先级 1：fresh boss_entry / 明确 challenge destination => CONFIRMED
            if frame_valid and boss_entry:
                print("[early] boss_entry 面板出现（fresh 强后置证据），提前挑战已确认")
                self._tqtz_clicked = True
                self._tqtz_pending = False
                self._tqtz_pending_frame = None
                return LoopAction.Continue

            # 业务确认优先级 2：可信游戏内且 tqtz 图标已消失
            if frame_valid and self._is_in_game_hud(frame) and (tqtz_hit is None or not isinstance(tqtz_hit, MatchResult)):
                print("[early] tqtz 图标消失（fresh 可信局内帧确认），提前挑战已确认")
                self._tqtz_clicked = True
                self._tqtz_pending = False
                self._tqtz_pending_frame = None
                return LoopAction.Continue

            # 未确认且已等待 5s：先清 pending 结束本次确认请求；
            # 第 3 次尝试的超时在此收尾为 ABANDONED（绝不允许静默伪装成功）。
            if now - self._tqtz_pending_since >= 5.0:
                attempts = getattr(self, "_tqtz_attempts", 0)
                self._tqtz_pending = False
                self._tqtz_pending_frame = None
                self._early_challenge_pending = False
                if attempts >= 3:
                    self._tqtz_abandoned = True
                    self._tqtz_clicked = False
                    print("[early] tqtz 3次尝试均未确认且第3次已超时，标记 ABANDONED 放弃")
                    return LoopAction.Continue
                print(f"[early] tqtz 点击后 5s 图标仍在，重试次数 {attempts}/3，允许重试")
            return LoopAction.Continue
        if getattr(self, "_tqtz_attempts", 0) >= 3:
            # C5 修复：exhausted 必须标记为 _tqtz_abandoned，绝不能伪装 _tqtz_clicked = True
            print("[early] tqtz 重试达上限 3 次，标记 ABANDONED 放弃提前挑战（不再尝试，非成功）")
            self._tqtz_abandoned = True
            self._tqtz_pending = False
            self._tqtz_clicked = False
            self._tqtz_pending_frame = None
            self._early_challenge_pending = False
            return LoopAction.Continue
        if getattr(self, "_tqtz_clicked", False):
            return None

        if now < getattr(self, "_tqtz_next_check_at", 0.0):
            return None
        tqtz_hit = self.find(
            frame,
            ["tqtz"],
            threshold=0.80,
            roi=(0.20, 0.03, 0.45, 0.15),
        )
        if tqtz_hit is None or not isinstance(tqtz_hit, MatchResult):
            return None

        takeover_elapsed = (
            round(now - self._round_started_at, 1)
            if self._round_started_at is not None
            else None
        )
        # The template is the 提前挑战 caption; the clickable button is the
        # phoenix icon right above it (live 2026-09-14 f0511: caption centre
        # (480,90), icon centre (479,42) at 1600x900).  Three clicks on the
        # caption never triggered the challenge.
        lift = int(round(frame.height * self._TQTZ_ICON_LIFT))
        icon_hit = MatchResult(
            "tqtz_icon", tqtz_hit.score, tqtz_hit.x, max(0, tqtz_hit.y - lift),
            tqtz_hit.w, tqtz_hit.h, tqtz_hit.screen_x, tqtz_hit.screen_y - lift,
        )
        print(
            f"[early] tqtz 出现（游戏侧 5-5 已过 + 开放时间到，常规10/8/6min）"
            f" takeover_elapsed={takeover_elapsed}s，点击提前挑战图标 @ {icon_hit.center}"
        )
        if self.act_click(icon_hit, "ClickTQTZ"):
            self._tqtz_attempts = getattr(self, "_tqtz_attempts", 0) + 1
            self._tqtz_dialog_expected_until = now + self._TQTZ_DIALOG_WINDOW_S
            self._tqtz_pending = True
            self._tqtz_pending_since = now
            self._tqtz_next_check_at = now + 1.0
            self._tqtz_pending_frame = frame
            evidence = self._ensure_evidence(frame)
            self._tqtz_request_generation = evidence.gen if evidence else 0
            self._early_challenge_pending = True
            self._early_challenge_started_at = now
            self._early_challenge_clicked_at = None
            self._main_line_since = now
            # 若配置了 5-5 后取消自动主线挑战，此时已过 5-5，触发关闭自动主线
            if getattr(self.settings, "auto_close_main_line", False) or getattr(self.settings, "early_challenge", False):
                self._close_main_line_triggered = True
            return LoopAction.Continue
        return None
    def _tick_early_challenge(self, frame: Frame, now: float) -> LoopAction | None:
        """After tqtz, wait for and enter the configured Boss challenge before G/F/V."""
        if not getattr(self, "_early_challenge_pending", False):
            return None
        if getattr(self, "_early_challenge_clicked_at", None) is not None:
            if not self.find_scene(frame, "boss_entry"):
                self._early_challenge_pending = False
                self._early_challenge_clicked_at = None
                print("[med] 提前挑战 Boss 入口已消失，确认进入挑战流程")
            return LoopAction.Continue
        if now - getattr(self, "_early_challenge_started_at", now) > 15.0:
            print("[med] 提前挑战未出现 Boss 入口，结束等待并恢复主循环")
            self._early_challenge_pending = False
            return None
        if self.find_scene(frame, "boss_entry"):
            return self._maybe_challenge_configured_boss(frame, now, recheck_s=1.0) or LoopAction.Continue
        return LoopAction.Continue
    def _maybe_resume_paused(self, frame: Frame, now: float) -> LoopAction:
        """暂停页只点击已验证模板按钮，有界重试 + 页面变化确认。

        20260823（v012653 复盘）：旧固定坐标 fallback 点在按钮下方 (985,513)
        造成无限狂点。恢复按钮一律走实机裁剪模板（pause_continue_game=
        简单暂停弹窗"继续游戏" / pause_return_game=暂停菜单"返回游戏"）；
        模板缺失时零输入等待，重试上限后 Fail-Closed 停止，绝不盲点坐标。
        """
        attempts = int(getattr(self, "_pause_resume_attempts", 0) or 0)
        if attempts >= 5:
            if self._unattended_recovery_enabled():
                print("[med] 暂停恢复重试已达上限（5次），保持零输入观察，不终止运行")
                return LoopAction.Continue
            print("[med] 暂停恢复重试已达上限（5 次），Fail-Closed 停止运行")
            self.set_phase(Phase.ERROR, "pause resume attempts exhausted")
            self.stop()
            return LoopAction.Break
        if now < getattr(self, "_pause_resume_next_at", 0.0):
            return LoopAction.Continue
        hit = self.find(
            frame,
            ["pause_continue_game", "pause_return_game"],
            threshold=0.80,
            scales=self._hot_scales(),
            roi=(0.35, 0.20, 0.65, 0.65),
        )
        if hit is None:
            print("[med] 暂停页未识别到已验证恢复按钮（继续游戏/返回游戏），零输入等待")
            return LoopAction.Continue
        attempts += 1
        self._pause_resume_attempts = attempts
        print(
            f"[med] 暂停页面自动点击恢复 {hit.name} @ {hit.center} (尝试 {attempts}/5)"
        )
        if self.act_click(hit, "ResumePausedGame"):
            self._pause_resume_next_at = now + 1.0
        return LoopAction.Continue

    _MAIN_LINE_TASKBAR_ROI = (1410 / 1600, 295 / 900, 1585 / 1600, 335 / 900)
    _MAIN_LINE_STAGE_RE = re.compile(r"主线\s*(\d+)\s*[-一—]\s*(\d+)")

    def _record_main_line_stage(self, stage: tuple[int, int], now: float) -> None:
        previous = getattr(self, "_main_line_stall_stage", None)
        if stage != previous:
            self._main_line_stall_stage = stage
            self._main_line_stall_since = now
            self._main_line_stall_reason = None
            return
        since = getattr(self, "_main_line_stall_since", None)
        if (
            since is not None
            and now - since >= self._MAIN_LINE_STALL_SECONDS
            and not self._main_line_stalled()
        ):
            self._main_line_stall_reason = "same_stage"
            print(f"[L1] 主线 {stage[0]}-{stage[1]} 停滞 {now - since:.0f}s，技能优先")

    def _record_main_line_failure(self, raw_text: str) -> None:
        normalized = re.sub(r"\s+", "", raw_text)
        if "主线挑战失败" in normalized or "提升实力后再来挑战" in normalized:
            if not self._main_line_stalled():
                print("[L1] OCR 读到主线挑战失败，技能优先")
            self._main_line_stall_reason = "challenge_failure"

    def _read_main_line_stage(self, frame: Frame, now: float) -> tuple[int, int] | None:
        """从右上角任务栏 OCR 识别当前主线 (章, 节)。

        局内最多每 10s OCR 一次（复用现有 OCR worker，禁止新进程）。
        """
        if now < getattr(self, "_main_line_ocr_next_at", 0.0):
            return None
        self._main_line_ocr_next_at = now + 10.0

        client = getattr(self, "_ocr_client", None)
        if client is None or bool(getattr(client, "disabled", False)):
            return None

        bbox = self._normalized_bbox(frame, self._MAIN_LINE_TASKBAR_ROI)
        try:
            resp = client.shadow_predict(
                frame,
                "main_line_taskbar",
                {"index": 0, "bbox": bbox, "kind": "main_line"},
            )
        except Exception:
            return None

        if not resp or str(getattr(resp, "status", "ok")) != "ok":
            return None

        raw_text = str(resp.raw_text or "")
        self._record_main_line_failure(raw_text)
        match = self._MAIN_LINE_STAGE_RE.search(raw_text)
        if match:
            try:
                stage = (int(match.group(1)), int(match.group(2)))
                self._record_main_line_stage(stage, now)
                return stage
            except (ValueError, TypeError):
                pass
        if "已完成当前难度全部主线" in raw_text or "全部主线" in raw_text:
            stage = (6, 1)
            self._record_main_line_stage(stage, now)
            return stage
        return None

    def _maybe_close_main_line_after_5_5(self, frame: Frame, now: float) -> LoopAction | None:
        """打完 5-5 后取消右侧『自动任务』勾选，避免挑战 5-10 主线 Boss 翻车。"""
        if not getattr(self.settings, "auto_close_main_line", False) and not getattr(self.settings, "early_challenge", False):
            return None
        if not getattr(self, "_close_main_line_triggered", False):
            stage = self._read_main_line_stage(frame, now)
            if stage is not None and stage > (5, 5):
                print(f"[med] 任务栏识别主线进度为 {stage[0]}-{stage[1]}（>(5,5)），触发取消【自动任务】")
                self._close_main_line_triggered = True
            else:
                return None
        if getattr(self, "_main_line_closed_done", False):
            return None
        state, hit = self._auto_task_state(frame)
        if state == "OFF":
            print("[med] 5-5 后已成功取消【自动任务】主线挑战")
            self._main_line_closed_done = True
            return None
        if state == "ON" and hit is not None:
            print(f"[med] 5-5 完成，按配置点击取消【自动任务】@ {hit.center}")
            if self.act_click(hit, "DisableAutoTask"):
                self._main_line_closed_done = True
                self._main_line_since = now
                return LoopAction.Continue
        return None


    def _maybe_clear_pressure_monsters(self, frame: Frame, now: float) -> LoopAction | None:
        """周期性触发 F4 清除挑怪（压力转移）。

        P1 安全收口：单人模式（normal_farm）禁用纯定时自动按 F4（避免清除进行中的挑战）。
        """
        if not self._passenger_mode():
            return None
        if not getattr(self.settings, "auto_pressure", False):
            return None
        if now < getattr(self, "_pressure_next_at", 0.0):
            return None
        if not self._is_in_game_hud(frame):
            return None
        interval = float(getattr(self.settings, "pressure_interval_s", 20.0) or 20.0)
        self._pressure_next_at = now + interval
        if self.act_key("f4", "ClearPressureMonsters"):
            print(f"[L1] 压力转移: 按下 F4 清除挑怪 (下次间隔 {interval}s)")
            self._main_line_since = now
            return LoopAction.Continue
        return None

    # User rule (2026-09-12): whenever the pressure-transfer button is on
    # screen it is the first thing to click; without it nothing waits for it.
    _HITCH_PRESSURE_CLICK_COOLDOWN_S = 3.0
    # KK closes the button about 60s into the round.  Inside this window the
    # visible button also holds other input between clicks; past it (a stuck
    # or mis-detected button) it is still clicked first but no longer holds.
    _HITCH_PRESSURE_PRIORITY_WINDOW_S = 60.0

    def _maybe_click_hitch_pressure_transfer(self, frame: Frame, now: float) -> LoopAction | None:
        """Pressure transfer: first priority while visible, never a blocker.

        * button visible -> click it (cooldown between clicks); inside the
          priority window the ticks between clicks stay zero input so no
          panel opens over it;
        * button not visible -> ``None``: auto-task, the four challenges and
          everything else proceed.  A takeover mid-round or a round without
          the button therefore never hangs on it;
        * ``_hitch_pressure_transferred`` is telemetry only: set when a fresh
          frame no longer shows the button after our click.
        """
        if not self._team_mode_enabled():
            return None
        if self._post_game_state(frame) is not None:
            return None
        if not self._is_in_game_hud(frame):
            return None
        hit = self.find(
            frame,
            ["yalizhuanyi"],
            threshold=0.65,
            roi=(0.30, 0.50, 0.90, 0.95),
        )
        click_at = getattr(self, "_hitch_pressure_click_at", None)
        if hit is None:
            if click_at is not None:
                evidence = self._ensure_evidence(frame)
                cur_gen = evidence.gen if evidence else None
                req_gen = getattr(self, "_hitch_pressure_request_generation", None)
                if req_gen is None or cur_gen is None or cur_gen > req_gen:
                    self._hitch_pressure_transferred = True
                    self._hitch_pressure_click_at = None
                    print("[med] 压力转移按钮已消失，转移后置条件确认")
            self._hitch_pressure_seen_since = None
            return None

        seen_since = getattr(self, "_hitch_pressure_seen_since", None)
        if seen_since is None:
            seen_since = self._hitch_pressure_seen_since = now
        if click_at is None or now - click_at >= self._HITCH_PRESSURE_CLICK_COOLDOWN_S:
            print(f"[med] 发现压力转移按钮 @ {hit.center}，优先点击")
            if self.act_click(hit, "HitchPressureTransfer"):
                self._hitch_pressure_click_at = now
                self._hitch_pressure_request_attempts = (
                    getattr(self, "_hitch_pressure_request_attempts", 0) + 1
                )
                evidence = self._ensure_evidence(frame)
                self._hitch_pressure_request_generation = evidence.gen if evidence else 0
            return LoopAction.Continue
        if now - seen_since < self._HITCH_PRESSURE_PRIORITY_WINDOW_S:
            return LoopAction.Continue
        return None

    def _hitch_arm_opening_pressure(self, why: str) -> bool:
        """Arm the opening pressure-transfer gate on the room -> round edge.

        Returns True for a natural round entry (our own Ready was confirmed in
        the room).  Only that path owns the gate; a mid-game attach never
        guesses that the opening step is due.  The caller then enters
        MAIN_LINE as a new round so the per-round state (pressure, auto-task,
        challenges, post-game route) starts fresh instead of inheriting the
        previous round's "done" flags.
        """
        if not self._hitch_enabled():
            return False
        natural = getattr(self, "_hitch_ready_confirmed_at", None) is not None
        if natural and not self._hitch_opening_pressure_armed:
            print(f"[med] 蹭车开局压力转移门禁已武装（{why}）")
        self._hitch_opening_pressure_armed = natural
        return natural

    # After a right-click the hero first walks to the NPC; the dialog opens
    # only on arrival (live 2026-09-14: 3 clicks 3s apart, gave up 2s after
    # the last one, no dialog).
    _RIFT_NPC_WALK_S = 5.0
    _RIFT_NPC_RETRY_COOLDOWN_S = 15.0

    def _rift_npc_body_hit(self, frame: Frame, label: MatchResult) -> MatchResult:
        """The 大秘境 template is the floating caption; the NPC stands under it.

        Live f0578/f0657 (1600x900): caption centre (1183,213), robed NPC at
        about (1163,266) — left of the caption centre and ~40px below it.  A
        right-click on the caption text opened nothing.
        """
        x = label.x + label.w // 2 - int(label.w * 0.28)
        y = min(frame.height - 1, label.y + label.h + max(18, int(frame.height * 0.045)))
        return MatchResult(
            "damijing_npc", label.score, max(0, x - label.w // 2), y,
            label.w, label.h, frame.left + x, frame.top + y,
        )

    def _find_secret_realm_npc(self, frame: Frame) -> MatchResult | None:
        hit = self.find(
            frame,
            ["damijing"],
            threshold=0.80,
            scales=self._hot_scales(),
            roi=(0.60, 0.15, 0.85, 0.55),
        )
        if not hit:
            return None
        if not (frame.width * 0.60 <= hit.x <= frame.width * 0.85):
            return None
        if not (frame.height * 0.15 <= hit.y <= frame.height * 0.55):
            return None
        return hit

    # 标题行 / 副标题行相对「是」按钮中心的位置（@900p）：大秘境框 f0584 是(713,447)
    # 标题 y≈270，提前挑战框 f0582 是(711,388) 标题 y≈212。
    _GREY_YES_TITLE_BANDS = ((-190, -158), (-150, -118))

    def _grey_yes_dialog_kind(self, frame: Frame, yes: MatchResult) -> str | None:
        """'rift' / 'tqtz' / None for a dialog carrying the grey 是 button.

        Title templates first (real frames: 1.0 on their own dialog, no hit on
        the other); OCR of the lines above 是 as the font-change fallback.
        """
        scales = self._hot_scales()
        if self.find(frame, ["env/great_rift_title"], threshold=0.80, scales=scales, roi=(0.40, 0.15, 0.60, 0.35)):
            return "rift"
        if self.find(frame, ["env/tqtz_confirm_title"], threshold=0.80, scales=scales, roi=(0.36, 0.15, 0.64, 0.35)):
            return "tqtz"
        client = getattr(self, "_ocr_client", None)
        if client is None or not bool(getattr(client, "is_available", False)) or frame.bgr is None:
            return None
        unit = frame.height / 900.0
        bx = yes.x + yes.w // 2
        by = yes.y + yes.h // 2
        texts: list[str] = []
        for dy0, dy1 in self._GREY_YES_TITLE_BANDS:
            bbox = (
                max(0, bx - int(110 * unit)), max(0, by + int(dy0 * unit)),
                min(frame.width, bx + int(290 * unit)), max(1, by + int(dy1 * unit)),
            )
            crop = frame.bgr[bbox[1]:bbox[3], bbox[0]:bbox[2]]
            if crop.size == 0:
                continue
            fingerprint = hashlib.md5(crop.tobytes()).hexdigest()
            try:
                response = client.shadow_predict(
                    frame, f"grey-yes-title:{fingerprint}",
                    {"index": 0, "bbox": bbox, "kind": "counter"},
                    fingerprint=fingerprint, panel_bbox=bbox,
                )
            except (AttributeError, OSError, TypeError, ValueError):
                continue
            if str(getattr(response, "status", "")) == "ok":
                texts.append(str(getattr(response, "raw_text", "") or ""))
        joined = "".join(texts)
        if "秘境" in joined:
            return "rift"
        if "提前" in joined or "BOSS" in joined.upper():
            return "tqtz"
        return None

    def _find_great_rift_accept(self, frame: Frame) -> MatchResult | None:
        hit = self.find(
            frame,
            ["mijingOk", "ok"],
            threshold=0.80,
            scales=self._hot_scales(),
            roi=(0.30, 0.40, 0.60, 0.65),
        )
        if not hit:
            return None
        if not (frame.width * 0.30 <= hit.x <= frame.width * 0.60):
            return None
        if not (frame.height * 0.40 <= hit.y <= frame.height * 0.65):
            return None
        return hit

    def _find_game_exit(self, frame: Frame) -> MatchResult | None:
        hit = self.find(frame, ["quit"], threshold=0.78, scales=self._hot_scales(), roi=(0.0, 0.0, 0.12, 0.15))
        if hit is not None and hit.x <= frame.width * 0.12 and hit.y <= frame.height * 0.15:
            return hit
        # 蹭车误开的游戏大厅「退出游戏」在右上角，不是局内左上角。
        if self._passenger_mode():
            hit = self.find(
                frame, ["quit"], threshold=0.78, scales=self._hot_scales(), roi=(0.80, 0.00, 0.99, 0.12)
            )
            if hit is not None and hit.x >= frame.width * 0.80 and hit.y <= frame.height * 0.15:
                return hit
        return None

    # The in-game "输入信息……/发送" chat input bar.  It lies across the failure
    # modal's button row and swallowed the 退出游戏 click (01:55 run); recovery
    # also routes around it via the top-left exit.  Enter toggles it (user,
    # 2026-09-12); Esc never closed it (10:19 run, 3 appearances x 2 presses).
    _GAME_CHAT_ROI = (0.35, 0.58, 0.65, 0.72)
    _GAME_CHAT_CLOSE_LIMIT = 2
    _GAME_CHAT_CLOSE_WAIT_S = 2.0
    _GAME_CHAT_CONFIRM_FRAMES = 2

    def _game_chat_input_visible(self, frame: Frame) -> bool:
        if not self._is_game_client_frame(frame):
            return False
        return self.find(
            frame,
            ["env/game_chat_input_bar"],
            threshold=0.85,
            scales=self._hot_scales(),
            roi=self._GAME_CHAT_ROI,
        ) is not None

    def _maybe_close_game_chat(self, frame: Frame, now: float) -> LoopAction | None:
        """Close the chat bar with Enter - only on proof it is open.

        Enter *opens* the bar too, so a key is sent only after two distinct
        frames both show it, then the next two frames must be observed again
        before any retry; two tries per appearance, then it is left alone
        (clicks elsewhere work under it).
        """
        if not self._game_chat_input_visible(frame):
            self._game_chat_frames = 0
            self._game_chat_close_attempts = 0
            return None
        if frame is not getattr(self, "_game_chat_last_frame", None):
            self._game_chat_last_frame = frame
            self._game_chat_frames = int(getattr(self, "_game_chat_frames", 0) or 0) + 1
        attempts = int(getattr(self, "_game_chat_close_attempts", 0) or 0)
        if attempts >= self._GAME_CHAT_CLOSE_LIMIT:
            return None
        if self._game_chat_frames < self._GAME_CHAT_CONFIRM_FRAMES:
            return None
        if now < float(getattr(self, "_game_chat_close_next_at", 0.0) or 0.0):
            return None
        print("[med] 局内聊天输入条连续两帧可见，按 Enter 关闭")
        if self.act_key("enter", "CloseGameChat"):
            self._game_chat_close_attempts = attempts + 1
            self._game_chat_close_next_at = now + self._GAME_CHAT_CLOSE_WAIT_S
            self._game_chat_frames = 0
        return LoopAction.Continue

    def _find_exit_confirm(self, frame: Frame) -> MatchResult | None:
        hit = self.find(
            frame,
            ["lobby/exit_confirm_btn"],
            threshold=0.78,
            scales=self._hot_scales(),
            roi=(0.38, 0.50, 0.50, 0.68),
        )
        if not hit:
            return None
        if not (frame.width * 0.38 <= hit.x <= frame.width * 0.50):
            return None
        if not (frame.height * 0.50 <= hit.y <= frame.height * 0.68):
            return None
        return hit

    def _find_challenge_button(self, frame: Frame, scene_key: str) -> tuple[MatchResult, MatchResult] | None:
        """Return (label hit, icon click hit) for one bottom challenge toggle."""
        threshold = min(0.68, self.settings.match_threshold)
        label = self.find_scene(frame, scene_key, threshold=threshold)
        if not label:
            return None
        click_hit = MatchResult(
            name=label.name,
            score=label.score,
            x=label.x,
            y=max(0, label.y - 42),
            w=label.w,
            h=label.h,
            screen_x=label.screen_x,
            screen_y=max(frame.top, label.screen_y - 42),
        )
        return label, click_hit

    @staticmethod
    def _challenge_green_count(frame: Frame, label_hit: MatchResult | None) -> int | None:
        if not label_hit or label_hit.score < 0.70 or frame.bgr is None:
            return None
        x1 = max(0, label_hit.x - 5)
        x2 = min(frame.width, label_hit.x + label_hit.w + 5)
        y1 = max(0, label_hit.y - 60)
        y2 = max(y1, label_hit.y - 25)
        roi = frame.bgr[y1:y2, x1:x2]
        if roi.size == 0:
            return None
        b, g, r = cv2.split(roi)
        green = (g > 120) & (g.astype(int) - r.astype(int) > 30) & (g.astype(int) - b.astype(int) > 20)
        return int(green.sum())

    @staticmethod
    def _resolve_challenge_state(frame: Frame, label_hit: MatchResult | None) -> ChallengeState:
        """Resolve ON/OFF/UNKNOWN from the existing green counter evidence."""
        green_count = Mediator._challenge_green_count(frame, label_hit)
        if green_count is None:
            return ChallengeState.UNKNOWN
        if green_count >= 30:
            return ChallengeState.ON
        if green_count < 10:
            return ChallengeState.OFF
        return ChallengeState.UNKNOWN

    def _trace_challenge_control(
        self,
        scene_key: str,
        state: ChallengeState,
        green_count: int | None,
        label_hit: MatchResult | None,
        click_hit: MatchResult | None,
        pending_age: float | None,
    ) -> None:
        self._trace_controls.append({
            "control": scene_key,
            "state": state.name,
            "green_count": green_count,
            "label_bbox": [label_hit.x, label_hit.y, label_hit.w, label_hit.h] if label_hit else None,
            "click_point": list(click_hit.center) if click_hit else None,
            "pending_age": pending_age,
        })

    @staticmethod
    def _challenge_is_auto(frame: Frame, label: MatchResult) -> bool:
        """Backward compatibility wrapper returning True if challenge state is ON."""
        return Mediator._resolve_challenge_state(frame, label) == ChallengeState.ON

    def _challenge_recheck_delay(self) -> float:
        """四挑战 ON 的周期复查间隔（配置可调，默认 30s，钳制 5..300s）。

        ON 开关是"周期复查"而非永久完成：复查发现被切回 OFF 时，
        在配置 cadence 内再点一次恢复自动。UNKNOWN 仍走有界零输入收口。
        """
        raw = getattr(self.settings, "challenge_recheck_interval_s", 30.0)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 30.0
        return max(5.0, min(300.0, value))

    def _ensure_challenge_buttons(self, frame: Frame) -> LoopAction | None:
        """Enable four challenge toggles in fixed order with post-click settle windows."""
        now = time.time()
        for scene_key, label in (
            ("coin_challenge", "金币"),
            ("wood_challenge", "木材"),
            ("experience_challenge", "经验"),
            ("treasure_challenge", "宝物"),
        ):
            if scene_key in self._challenge_done:
                if self._passenger_mode():
                    # 蹭车开局只尝试一次四挑战；后续的 F4/状态波动不得
                    # 重新阻断黑商、宝物和战后等待。
                    self._challenge_states[scene_key] = ChallengeState.ON
                    self._challenge_unknown_since.pop(scene_key, None)
                    continue
                recheck_at = self._challenge_recheck_at.get(scene_key)
                if recheck_at is None or now < recheck_at:
                    if recheck_at is None:
                        # 防御：已标记 done 却从未排程复查 → 立即排程，绝不永久 done。
                        self._challenge_recheck_at[scene_key] = (
                            now + self._challenge_recheck_delay()
                        )
                    self._challenge_states[scene_key] = ChallengeState.ON
                    self._challenge_unknown_since.pop(scene_key, None)
                    continue
                found = self._find_challenge_button(frame, scene_key)
                label_hit = found[0] if found else None
                click_hit = found[1] if found else None
                state = (
                    self._resolve_challenge_state(frame, label_hit)
                    if label_hit is not None
                    else ChallengeState.UNKNOWN
                )
                green_count = self._challenge_green_count(frame, label_hit)
                self._trace_challenge_control(
                    scene_key, state, green_count, label_hit, click_hit, None
                )
                if state == ChallengeState.ON:
                    self._challenge_recheck_at[scene_key] = (
                        now + self._challenge_recheck_delay()
                    )
                    continue
                if state != ChallengeState.OFF:
                    # Periodic UNKNOWN/MISSING is not click authority.  Retry
                    # soon without discarding the last verified ON state.
                    self._challenge_recheck_at[scene_key] = (
                        now + self.settings.ui_action_interval_s
                    )
                    continue
                self._challenge_done.remove(scene_key)
                self._challenge_attempts[scene_key] = 0

            found = self._find_challenge_button(frame, scene_key)
            label_hit = found[0] if found else None
            click_hit = found[1] if found else None
            state = (
                self._resolve_challenge_state(frame, label_hit)
                if label_hit is not None
                else ChallengeState.UNKNOWN
            )
            green_count = self._challenge_green_count(frame, label_hit)
            pending_since = self._challenge_pending_since.get(scene_key)
            pending_age = round(now - pending_since, 2) if pending_since is not None else None
            self._trace_challenge_control(
                scene_key, state, green_count, label_hit, click_hit, pending_age
            )

            if pending_since is not None:
                if state == ChallengeState.ON:
                    print(f"[L1] {label}挑战已是自动模式")
                    self._challenge_states[scene_key] = ChallengeState.ON
                    self._challenge_done.add(scene_key)
                    self._challenge_recheck_at[scene_key] = now + self._challenge_recheck_delay()
                    self._challenge_pending_since.pop(scene_key, None)
                    self._challenge_next_observe_at.pop(scene_key, None)
                    self._challenge_unknown_since.pop(scene_key, None)
                    continue
                if now < self._challenge_next_observe_at.get(scene_key, now):
                    self._challenge_states[scene_key] = ChallengeState.PENDING
                    print(
                        f"[L1] {label}挑战等待确认（零输入，"
                        f"{pending_age:.1f}/{self.settings.ui_action_interval_s:.1f}s）"
                    )
                    return LoopAction.Continue
                self._challenge_pending_since.pop(scene_key, None)
                self._challenge_next_observe_at.pop(scene_key, None)
                if state != ChallengeState.OFF:
                    self._challenge_states[scene_key] = ChallengeState.UNKNOWN
                    if label_hit is None:
                        print(f"[L1] {label}挑战观察期后按钮缺失，保守零输入")
                        return LoopAction.Continue
                    unknown_since = self._challenge_unknown_since.setdefault(scene_key, now)
                    unknown_timeout = max(3, min(self.settings.query_timeout, 30))
                    unknown_elapsed = now - unknown_since
                    if unknown_elapsed >= unknown_timeout:
                        print(f"[L1] {label}挑战状态连续 UNKNOWN {unknown_elapsed:.1f}s，跳过该挑战继续")
                        self._challenge_done.add(scene_key)
                        self._challenge_recheck_at[scene_key] = now + self.settings.ui_action_interval_s
                        self._challenge_unknown_since.pop(scene_key, None)
                        continue
                    print(f"[L1] {label}挑战观察期后仍 UNKNOWN，零动作等待")
                    return LoopAction.Continue

            attempts = self._challenge_attempts.get(scene_key, 0)
            if attempts >= 3:
                if self._passenger_mode():
                    print(f"[L1] 蹭车 {label}挑战重试已达上限 ({attempts})，本局跳过该步并继续")
                    self._challenge_done.add(scene_key)
                    self._challenge_recheck_at.pop(scene_key, None)
                    continue
                print(f"[L1] {label}挑战重试次数已达上限 ({attempts}) 且未确认开启，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, f"{scene_key} attempt limit reached")
                self.stop()
                return LoopAction.Break

            if label_hit is None:
                self._challenge_unknown_since.pop(scene_key, None)
                print(f"[L1] {label}挑战按钮未出现（MISSING），跳过本 tick 继续")
                continue

            if state == ChallengeState.ON:
                print(f"[L1] {label}挑战已是自动模式")
                self._challenge_states[scene_key] = ChallengeState.ON
                self._challenge_done.add(scene_key)
                self._challenge_recheck_at[scene_key] = now + self._challenge_recheck_delay()
                self._challenge_unknown_since.pop(scene_key, None)
                continue

            if state == ChallengeState.UNKNOWN:
                unknown_since = self._challenge_unknown_since.setdefault(scene_key, now)
                unknown_timeout = max(3, min(self.settings.query_timeout, 30))
                unknown_elapsed = now - unknown_since
                self._challenge_states[scene_key] = ChallengeState.UNKNOWN
                if unknown_elapsed >= unknown_timeout:
                    print(f"[L1] {label}挑战状态连续 UNKNOWN {unknown_elapsed:.1f}s，跳过该挑战继续")
                    self._challenge_done.add(scene_key)
                    self._challenge_recheck_at[scene_key] = now + self.settings.ui_action_interval_s
                    self._challenge_unknown_since.pop(scene_key, None)
                    continue
                print(
                    f"[L1] {label}挑战状态为 UNKNOWN（模糊/低置信），"
                    f"零动作等待 {unknown_elapsed:.1f}/{unknown_timeout}s"
                )
                return LoopAction.Continue

            self._challenge_unknown_since.pop(scene_key, None)
            self._challenge_attempts[scene_key] = attempts + 1
            current_attempts = self._challenge_attempts[scene_key]
            print(f"[L1] 自动开启【{label}挑战】右键 @ {click_hit.center} (尝试 {current_attempts}/3)")
            act_res = self.act_right_click(click_hit, f"{label}Challenge-right_click")
            self._challenge_states[scene_key] = ChallengeState.PENDING
            if self.phase == Phase.ERROR or self.stop_signal.is_set():
                return LoopAction.Break
            if not act_res and current_attempts >= 3:
                if self._passenger_mode():
                    print(f"[L1] 蹭车 {label}挑战输入失败已达上限 ({current_attempts})，本局跳过该步并继续")
                    self._challenge_done.add(scene_key)
                    self._challenge_recheck_at.pop(scene_key, None)
                    continue
                print(f"[L1] {label}挑战右键发送失败且重试已达上限 ({current_attempts})，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, f"{scene_key} right_click failed limit reached")
                self.stop()
                return LoopAction.Break
            if act_res:
                clicked_at = time.time()
                self._challenge_pending_since[scene_key] = clicked_at
                self._challenge_next_observe_at[scene_key] = (
                    clicked_at + self.settings.ui_action_interval_s
                )
            return LoopAction.Continue

        return None

    @staticmethod
    def _hero_reference_frame(frame: Frame) -> bool:
        """Hero controls support standard 16:9 resolutions via LayoutTransform."""
        return LayoutTransform.is_supported(frame.width, frame.height)

    @staticmethod
    def _hero_roi(frame: Frame, box: tuple[int, int, int, int]) -> np.ndarray | None:
        if not Mediator._hero_reference_frame(frame):
            return None
        transform = LayoutTransform.from_frame(frame.width, frame.height)
        rx1, ry1, rx2, ry2 = transform.logical_roi(*box)
        roi = frame.bgr[ry1:ry2, rx1:rx2]
        if roi.shape[:2] != (ry2 - ry1, rx2 - rx1):
            return None
        return cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    @staticmethod
    def _hero_changed_pixels(before: np.ndarray, after: np.ndarray) -> int:
        if before.shape != after.shape:
            return 0
        if before.ndim == 3:
            # cv2.countNonZero 仅接受单通道；BGR ROI 先转灰度（面板刷新/WAIT_MUTATION 场景实测崩溃 'cn == 1'）
            before = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
            after = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
        difference = cv2.absdiff(before, after)
        _, changed = cv2.threshold(difference, 15, 255, cv2.THRESH_BINARY)
        return int(cv2.countNonZero(changed))

    @staticmethod
    def _hero_point(frame: Frame, name: str, x: int, y: int) -> MatchResult:
        transform = LayoutTransform.from_frame(frame.width, frame.height)
        px, py = transform.logical_point(x, y)
        return MatchResult(
            name=name,
            score=1.0,
            x=px,
            y=py,
            w=0,
            h=0,
            screen_x=frame.left + px,
            screen_y=frame.top + py,
        )

    def _find_hero_entry(self, frame: Frame) -> MatchResult | None:
        if not self._hero_reference_frame(frame):
            return None
        hit = self.find(frame, ["lobby/stage_hero_mode_btn"], threshold=0.90)
        if not hit:
            return None
        transform = LayoutTransform.from_frame(frame.width, frame.height)
        rx1, ry1, rx2, ry2 = transform.logical_roi(1170, 790, 1270, 840)
        if not (rx1 <= hit.x <= rx2 and ry1 <= hit.y <= ry2):
            return None
        return hit
    def _hero_modal_buttons(self, frame: Frame) -> tuple[MatchResult, MatchResult] | None:
        if not self._hero_reference_frame(frame):
            return None
        start = self.find(frame, ["lobby/hero_modal_start"], threshold=0.90)
        cancel = self.find(frame, ["lobby/hero_modal_cancel"], threshold=0.90)
        if not start or not cancel:
            return None
        if not (540 <= start.x <= 730 and 820 <= start.y <= 890):
            return None
        if not (750 <= cancel.x <= 940 and 820 <= cancel.y <= 890):
            return None
        return start, cancel

    def _hero_initial_zero_confirmed(self, frame: Frame, spec: "FactionSpec") -> bool:
        if not spec.unselected_template:
            return False
        transform = LayoutTransform.from_frame(frame.width, frame.height)
        # 局部列区域匹配：限定在本阵营卡片列内（容忍 ±10px 抖动与 0.65 动态对比度）
        rx1, ry1, rx2, ry2 = transform.logical_roi(
            spec.card_match_window[0] - 10, spec.card_match_window[2] - 10,
            spec.card_match_window[1] + 165, spec.card_match_window[3] + 175,
        )
        col_crop = frame.bgr[ry1:ry2, rx1:rx2]
        card_template_path = resolve_template(self.images, spec.unselected_template)
        if col_crop is None or card_template_path is None:
            return False
        card_template = _load_template(card_template_path)
        if card_template is None or col_crop.shape[0] < card_template.shape[0] or col_crop.shape[1] < card_template.shape[1]:
            return False
        card_score = float(cv2.minMaxLoc(cv2.matchTemplate(col_crop, card_template, cv2.TM_CCOEFF_NORMED))[1])
        if card_score < 0.65:
            return False
        # 难度等级为 0 的判定：
        # 1. 模板匹配（以 hero_level_zero 在难度框小区域内做局部匹配，容忍 ±4px 坐标漂移）
        transform = LayoutTransform.from_frame(frame.width, frame.height)
        rx1, ry1, rx2, ry2 = transform.logical_roi(
            spec.level_roi[0] - 6, spec.level_roi[1] - 6, spec.level_roi[2] + 6, spec.level_roi[3] + 6
        )
        search_roi = frame.bgr[ry1:ry2, rx1:rx2]
        template_path = resolve_template(self.images, "lobby/hero_level_zero")
        if search_roi is not None and template_path is not None:
            template = _load_template(template_path)
            if template is not None and search_roi.shape[0] >= template.shape[0] and search_roi.shape[1] >= template.shape[1]:
                score = float(cv2.minMaxLoc(cv2.matchTemplate(search_roi, template, cv2.TM_CCOEFF_NORMED))[1])
                if score >= 0.85:
                    return True
        # 2. 备用兜底：如果卡片未选中态精准命中（score >= 0.90），则初始零等级成立
        return card_score >= 0.90
    def _hero_fail(self, reason: str) -> LoopAction:
        print(f"[英雄模式] {reason}，Fail-Closed 停止运行")
        self.set_phase(Phase.ERROR, reason)
        self.stop()
        return LoopAction.Break

    def _hero_observation_timeout(self) -> float:
        """Allow for the slowest real client capture before failing closed.

        Hero setup uses full-frame template matching.  On the recorded 1600x900
        client a fresh frame can take roughly 9–10 seconds, so the old 2–3s
        deadlines expired before the next frame could prove the click worked.
        Keep the bound finite while leaving enough room for one slow capture
        plus one confirmation frame.
        """
        return max(20.0, min(float(self.settings.query_timeout), 60.0))

    def _hero_alloc_plan(self) -> list[tuple[int, int]]:
        """声望分配计划：优先读 reputation_allocations（多阵营自由组合），
        否则回退旧单阵营字段。返回 [(faction_id, points)]，points 1..10。"""
        raw = getattr(self.settings, "reputation_allocations", None)
        items: list[tuple[int, int]] = []
        if isinstance(raw, dict) and raw:
            for key, value in raw.items():
                try:
                    fid = int(key)
                    pts = int(value or 0)
                except (TypeError, ValueError):
                    continue
                if fid in FACTION_SPECS and 1 <= pts <= 10:
                    items.append((fid, pts))
            items.sort(key=lambda t: (-t[1], t[0]))
            return items
        fid = int(getattr(self.settings, "reputation_type", 0) or 0)
        lvl = int(getattr(self.settings, "reputation_level", 0) or 0)
        if fid in FACTION_SPECS and 1 <= lvl <= 10:
            return [(fid, lvl)]
        return []

    def _begin_hero_setup(self, frame: Frame) -> LoopAction:
        plan = self._hero_alloc_plan()
        if not plan:
            return self._hero_fail("无有效声望分配（每阵营 1–10 点）")
        for fid, pts in plan:
            spec = FACTION_SPECS.get(fid)
            if spec is None or not spec.verified:
                return self._hero_fail(f"阵营 {fid} 缺少实机未选中模板")
        self._hero_plan = plan
        self._hero_plan_index = 0
        rep_level = plan[0][1]
        if not 1 <= rep_level <= 10:
            return self._hero_fail("英雄模式仅支持 1–10 点")
        if not self._hero_reference_frame(frame):
            return self._hero_fail(
                f"英雄模式要求支持的 16:9 分辨率，当前为 {frame.width}x{frame.height}"
            )
        entry = self._find_hero_entry(frame)
        if not entry:
            if self._action_timed_out():
                return self._hero_fail("未找到经录屏验证的英雄模式入口")
            print("[英雄模式] 等待右下角专用入口（零动作）")
            return LoopAction.Continue
        if not self.act_click(entry, "OpenHeroModeModal"):
            return LoopAction.Continue
        self._hero_state = "WAIT_MODAL"
        self._hero_verified_level = 0
        self._hero_level_baseline = None
        self._hero_level_candidate = None
        self._hero_card_baseline = None
        self._hero_modal_missing_frames = 0
        self._hero_step_deadline = time.time() + self._hero_observation_timeout()
        self.set_phase(Phase.HERO_SETUP, "hero entry clicked")
        return LoopAction.Continue

    def _observe_ticket_balance(self, frame: Frame, now: float | None = None) -> int | None:
        """机会性读取挑战券剩余。读不出返回 None，**绝不当 0**。

        选关页/游戏大厅才看得见这个计数；蹭车大部分时间待在 KK 房间列表里，
        所以这里是"能读到就校正"，读不到完全正常，由死算兜着。
        """
        now = time.time() if now is None else now
        if now < self._ticket_next_read_at:
            return self._ticket_balance
        self._ticket_next_read_at = now + self._TICKET_READ_INTERVAL_S
        value = self._hud_counter(
            frame, self._TICKET_REMAINDER_ROI, "ticket", max_value=self._TICKET_READ_MAX
        )
        if value is None:
            return self._ticket_balance
        # 真实读数一律覆盖死算结果 —— 跨零点补票、手动买票都靠这条自然收敛。
        if value != self._ticket_projected_remaining():
            print(f"[L0] 挑战券读数校正：{self._ticket_balance} -> {value}（死算已走 {self._ticket_rounds_since_read} 局）")
        self._ticket_balance = int(value)
        self._ticket_balance_at = now
        self._ticket_rounds_since_read = 0
        return self._ticket_balance

    def _ticket_projected_remaining(self) -> int | None:
        """死算剩余：最近读数 - 每局消耗 x 已完成局数。从没读到过则 None。"""
        if self._ticket_balance is None:
            return None
        spent = self._TICKET_COST_PER_ROUND * max(0, self._ticket_rounds_since_read)
        return self._ticket_balance - spent

    def _ticket_budget_spent_one_round(self) -> None:
        """完成一局后推进死算。有真实读数时下次读取会把它覆盖掉。"""
        self._ticket_rounds_since_read += 1

    def _ticket_budget_allows_another_round(self) -> bool:
        """够不够再来一局。

        **从没读到过读数时返回 True** —— 未知不是"耗尽"，这一条是有意的
        fail-open：它只决定"要不要再搜一把房"，不授权任何输入，而误判成耗尽
        会让长线程测试提前收工。真正的下限由 cycle_num 和 --duration 兜。
        """
        projected = self._ticket_projected_remaining()
        if projected is None:
            return True
        return projected >= self._TICKET_COST_PER_ROUND

    def _ticket_exhausted(self, frame: Frame) -> bool:
        """True when the yellow challenge-ticket remainder is 0.

        The counter is below the 选关页「开始游戏」button, not below「扫荡」:
        full region (1032,850)-(1155,888) in a 1600x900 client. The current
        remainder is right-aligned in the first number slot; detect a zero in
        its right digit position and reject frames with ink in the two
        preceding digit positions (so 120/120 does not match its own zero).
        """
        if not getattr(self.settings, "auto_archaeology", True):
            return False
        # Remainder text band: x≈1067..1102, y≈868..888. The rightmost
        x1 = int(frame.width * 1067 / 1600.0)
        y1 = int(frame.height * 850 / 900.0)
        x2 = int(frame.width * 1102 / 1600.0)
        y2 = int(frame.height * 888 / 900.0)
        if x2 <= x1 or y2 <= y1:
            return False
        remainder = Frame(
            frame.bgr[y1:y2, x1:x2],
            left=frame.left + x1,
            top=frame.top + y1,
            window_title=frame.window_title,
            hwnd=frame.hwnd,
        )
        zero = self.find(
            Frame(remainder.bgr[:, 21:35], left=remainder.left + 21, top=remainder.top,
                  window_title=remainder.window_title, hwnd=remainder.hwnd),
            ["lobby/ticket_zero"],
            threshold=0.72,
            scales=(0.9, 1.0, 1.1, 1.2),
        )
        if zero is None:
            return False
        # Reject 120/120 and other multi-digit remainders: left digit area must
        # contain no bright digit ink in the central text band.
        gray = cv2.cvtColor(remainder.bgr[14:34, :21], cv2.COLOR_BGR2GRAY)
        return int((gray > 150).sum()) < 18

    def _archaeology_mode_anchor(self, frame: Frame) -> MatchResult | None:
        """考古模式业务锚点：kaogu/kaoguMode 任一命中即视为考古页证据。"""
        return self.find(
            frame,
            ["kaogu", "kaoguMode"],
            threshold=0.70,
            scales=self._hot_scales(),
        )

    def _maybe_switch_to_archaeology(self, frame: Frame) -> LoopAction | None:
        """票尽 / cycle 完成 → 考古模式 request → fresh 证据确认（contract #8）。

        click 仅 request；只有 request 之后 fresh evidence generation 上命中
        ``kaogu``/``kaoguMode`` 业务锚点，才 COMPLETE +
        ARCHAEOLOGY_HANDOFF_COMPLETE。click success/frame mutation 绝不当成功。
        """
        if not getattr(self.settings, "auto_archaeology", True) and not getattr(self, "_archaeology_handoff_pending", False):
            return None
        click_at = getattr(self, "_archaeology_click_at", None)
        if click_at is not None:
            req_gen = self._archaeology_click_generation
            evidence = self._ensure_evidence(frame)
            cur_gen = evidence.gen if evidence else None
            if req_gen is not None and cur_gen is not None and cur_gen <= req_gen:
                return LoopAction.Continue
            if self._archaeology_mode_anchor(frame) is not None:
                print("[med] 考古模式业务锚点 fresh 命中，handoff COMPLETE")
                self._archaeology_handoff_confirmed = True
                self._archaeology_click_at = None
                self.set_phase(Phase.COMPLETE, "archaeology mode confirmed")
                self.stop()
                return LoopAction.Break
            if time.time() - click_at >= 30.0:
                print("[med] 考古模式点击后 30s 未见 kaogu 锚点，Fail-Closed 停止")
                self.set_phase(Phase.ERROR, "archaeology mode confirmation timeout")
                self.stop()
                return LoopAction.Break
            print("[med] 考古模式点击后等待 fresh kaogu/kaoguMode 锚点（零动作）")
            return LoopAction.Continue
        handoff_pending = getattr(self, "_archaeology_handoff_pending", False)
        if handoff_pending:
            self._ticket_zero_frames = 0
            print("[L0] cycle 完成 handoff：点击考古模式（request，待 fresh 锚点确认）")
        elif self._ticket_exhausted(frame):
            count = getattr(self, "_ticket_zero_frames", 0) + 1
            self._ticket_zero_frames = count
            if count < 3:
                print(f"[L0] 挑战券剩余为 0（确认 {count}/3），等待稳定…")
                return LoopAction.Continue
            print("[L0] 挑战券已清空，点击考古模式（request，待 fresh 锚点确认）")
        else:
            self._ticket_zero_frames = 0
            return None
        arch_hit = self.find(frame, ["lobby/stage_archaeology_btn"], threshold=0.70)
        if arch_hit is None:
            # G0 Phase B：模板 miss 绝不伪造固定坐标 request。有界 fresh
            # reobserve（零输入）；超界 → FATAL（_classify_run_exit 归因）。
            self._archaeology_template_miss_budget -= 1
            if self._archaeology_template_miss_budget <= 0:
                print("[med] 考古按钮模板持续未出现，reobserve 预算耗尽，Fail-Closed 停止")
                self.set_phase(Phase.ERROR, "archaeology button never observed")
                self.stop()
                return LoopAction.Break
            print(f"[med] 考古按钮模板未出现，零输入 reobserve（剩余 {self._archaeology_template_miss_budget}）")
            return LoopAction.Continue
        result = self.act_click(arch_hit, "SwitchToArchaeology")
        self._ticket_zero_frames = 0
        if not result:
            self._archaeology_click_attempts += 1
            if self._archaeology_click_attempts >= 3:
                self.set_phase(Phase.ERROR, "archaeology switch input rejected")
                self.stop()
                return LoopAction.Break
            return LoopAction.Continue
        evidence = self._ensure_evidence(frame)
        self._archaeology_click_at = time.time()
        self._archaeology_click_generation = evidence.gen if evidence else None
        return LoopAction.Continue

    def _current_faction_spec(self) -> "FactionSpec":
        plan = getattr(self, "_hero_plan", None)
        index = getattr(self, "_hero_plan_index", 0)
        if plan:
            fid = plan[min(index, len(plan) - 1)][0]
        else:
            fid = int(getattr(self.settings, "reputation_type", 0) or 0)
        return FACTION_SPECS.get(fid, FACTION_SPECS[3])

    def _tick_hero_setup(self, frame: Frame) -> LoopAction:
        now = time.time()
        if not self._hero_reference_frame(frame):
            return self._hero_fail(
                f"英雄模式过程中客户区尺寸改变为 {frame.width}x{frame.height}"
            )
        if self._hero_step_deadline is not None and now >= self._hero_step_deadline:
            return self._hero_fail(f"英雄模式步骤 {self._hero_state} 超时")

        spec = self._current_faction_spec()
        buttons = self._hero_modal_buttons(frame)
        level_roi = self._hero_roi(frame, spec.level_roi)
        card_roi = self._hero_roi(frame, spec.card_roi)
        plan = getattr(self, "_hero_plan", None) or []
        index = min(getattr(self, "_hero_plan_index", 0), max(0, len(plan) - 1))
        target_level = plan[index][1] if plan else int(self.settings.reputation_level)

        if self._hero_state == "WAIT_MODAL":
            if not buttons or level_roi is None or card_roi is None:
                print("[英雄模式] 等待开启/取消双按钮同时出现（零动作）")
                return LoopAction.Continue
            # 今日可获得声望检测：若检测到今日可得声望为 0，立即点击取消退出英雄模式，降级为常规模式
            reputation_box = self._hero_roi(frame, (1000, 750, 1400, 880))
            if reputation_box is not None:
                # 优先识别右下角可得声望数字
                pass
            if not self._hero_initial_zero_confirmed(frame, spec):
                print(f"[英雄模式] 弹窗已出现，但{spec.name}未选中卡和初始 0 级未同时确认（零动作）")
                return LoopAction.Continue
            self._hero_level_baseline = level_roi.copy()
            self._hero_card_baseline = card_roi.copy()
            plus = self._hero_point(frame, f"hero_{spec.slug}_plus", *spec.plus_xy)
            if not self.act_click(plus, f"{spec.action_label}-1"):
                return LoopAction.Continue
            self._hero_state = "WAIT_LEVEL_CHANGE"
            self._hero_step_deadline = now + self._hero_observation_timeout()
            return LoopAction.Continue

        if self._hero_state == "WAIT_LEVEL_CHANGE":
            if not buttons or level_roi is None or self._hero_level_baseline is None:
                return self._hero_fail("难度变化确认时英雄弹窗丢失")
            changed = self._hero_changed_pixels(self._hero_level_baseline, level_roi)
            if changed < 50:
                print(f"[英雄模式] 等待难度数字变化（{changed}/50 像素，零动作）")
                return LoopAction.Continue
            self._hero_level_candidate = level_roi.copy()
            self._hero_state = "WAIT_LEVEL_STABLE"
            self._hero_step_deadline = now + self._hero_observation_timeout()
            return LoopAction.Continue

        if self._hero_state == "WAIT_LEVEL_STABLE":
            if not buttons or level_roi is None or self._hero_level_candidate is None:
                return self._hero_fail("难度稳定确认时英雄弹窗丢失")
            stable_delta = self._hero_changed_pixels(self._hero_level_candidate, level_roi)
            if stable_delta > 20:
                self._hero_level_candidate = level_roi.copy()
                print(f"[英雄模式] 难度数字仍在变化（{stable_delta} 像素，零动作）")
                return LoopAction.Continue

            self._hero_verified_level += 1
            if self._hero_verified_level == 1 and getattr(self, "_hero_plan_index", 0) == 0:
                # 首个阵营：加级后必须从「未选中模板」翻转为选中态。
                # 后续阵营已在 WAIT_FACTION_SELECTED 验证过选中，跳过。
                if card_roi is None or self._hero_card_baseline is None:
                    return self._hero_fail(f"无法确认{spec.name}选中态")
                selected_delta = self._hero_changed_pixels(self._hero_card_baseline, card_roi)
                if selected_delta < 10000:
                    return self._hero_fail(
                        f"第一次加级后{spec.name}卡片未切换为选中态（{selected_delta}/10000 像素）"
                    )

            print(f"[英雄模式] 已确认{spec.name}难度 {self._hero_verified_level}/{target_level}")
            if self._hero_verified_level < target_level:
                self._hero_level_baseline = level_roi.copy()
                plus = self._hero_point(frame, f"hero_{spec.slug}_plus", *spec.plus_xy)
                next_level = self._hero_verified_level + 1
                if not self.act_click(plus, f"{spec.action_label}-{next_level}"):
                    return LoopAction.Continue
                self._hero_state = "WAIT_LEVEL_CHANGE"
                self._hero_step_deadline = now + self._hero_observation_timeout()
                return LoopAction.Continue

            if index + 1 < len(plan):
                next_fid = plan[index + 1][0]
                next_spec = FACTION_SPECS[next_fid]
                nx1, ny1, nx2, ny2 = next_spec.card_roi
                center = self._hero_point(
                    frame,
                    f"hero_{next_spec.slug}_card",
                    (nx1 + nx2) // 2,
                    (ny1 + ny2) // 2,
                )
                next_card_roi = self._hero_roi(frame, next_spec.card_roi)
                self._hero_card_baseline = (
                    next_card_roi.copy() if next_card_roi is not None else None
                )
                if not self.act_click(center, f"{next_spec.action_label}-select"):
                    return LoopAction.Continue
                self._hero_plan_index = index + 1
                self._hero_state = "WAIT_FACTION_SELECTED"
                self._hero_step_deadline = now + self._hero_observation_timeout()
                return LoopAction.Continue

            start = buttons[0]
            if not self.act_click(start, "StartHeroModeChallenge"):
                return LoopAction.Continue
            self._hero_state = "WAIT_MODAL_CLOSE"
            self._hero_modal_missing_frames = 0
            self._hero_step_deadline = now + self._hero_observation_timeout()
            return LoopAction.Continue

        if self._hero_state == "WAIT_FACTION_SELECTED":
            if not buttons or level_roi is None or card_roi is None:
                # 弹窗短暂丢失：重发点击选中下一阵营，绝不 Fail-Closed 停机
                print("[英雄模式] 切换阵营时英雄弹窗丢失，重试点击选中（Fail-Forward）")
                index = min(getattr(self, "_hero_plan_index", 0), max(0, len(plan) - 1))
                spec_retry = FACTION_SPECS[plan[index][0]]
                nx1, ny1, nx2, ny2 = spec_retry.card_roi
                center = self._hero_point(
                    frame, f"hero_{spec_retry.slug}_card",
                    (nx1 + nx2) // 2, (ny1 + ny2) // 2,
                )
                if self.act_click(center, f"{spec_retry.action_label}-select-retry"):
                    self._hero_step_deadline = now + self._hero_observation_timeout()
                return LoopAction.Continue
            prev_card = self._hero_card_baseline
            if prev_card is not None:
                switched = self._hero_changed_pixels(prev_card, card_roi)
                # 实际实测翻转像素在 1500~8000 左右（153x168 总像素 25704），阈值设为 1200
                if switched < 1200:
                    retries = getattr(self, "_hero_select_retries", 0) + 1
                    self._hero_select_retries = retries
                    if retries > 3:
                        # 达到重试上限：不再死循环，认为选中或直接尝试加级（Fail-Forward）
                        print(f"[英雄模式] {spec.name} 达到选中重试上限({retries}/3)，直接尝试加级（Fail-Forward）")
                        self._hero_select_retries = 0
                    else:
                        print(
                            f"[英雄模式] 等待{spec.name}卡片切换为选中态"
                            f"（{switched}/1200 像素，第 {retries}/3 次重试）"
                        )
                        index = min(getattr(self, "_hero_plan_index", 0), max(0, len(plan) - 1))
                        spec_retry = FACTION_SPECS[plan[index][0]]
                        nx1, ny1, nx2, ny2 = spec_retry.card_roi
                        center = self._hero_point(
                            frame, f"hero_{spec_retry.slug}_card",
                            (nx1 + nx2) // 2, (ny1 + ny2) // 2,
                        )
                        self.act_click(center, f"{spec_retry.action_label}-select-retry")
                        self._hero_step_deadline = now + self._hero_observation_timeout()
                        return LoopAction.Continue
            self._hero_select_retries = 0
            self._hero_verified_level = 0
            self._hero_level_baseline = level_roi.copy()
            self._hero_level_candidate = None
            self._hero_card_baseline = card_roi.copy()
            plus = self._hero_point(frame, f"hero_{spec.slug}_plus", *spec.plus_xy)
            if not self.act_click(plus, f"{spec.action_label}-1"):
                return LoopAction.Continue
            self._hero_state = "WAIT_LEVEL_CHANGE"
            self._hero_step_deadline = now + self._hero_observation_timeout()
            return LoopAction.Continue

        if self._hero_state == "WAIT_MODAL_CLOSE":
            if buttons:
                self._hero_modal_missing_frames = 0
                print("[英雄模式] 已点击开启，等待弹窗消失（零动作，不重复点击）")
                return LoopAction.Continue
            self._hero_modal_missing_frames += 1
            if self._hero_modal_missing_frames < 2:
                print("[英雄模式] 弹窗按钮首帧消失，等待连续确认（零动作）")
                return LoopAction.Continue
            self._hero_state = "WAIT_INGAME"
            self._hero_step_deadline = now + self._hero_observation_timeout()
            return LoopAction.Continue

        if self._hero_state == "WAIT_INGAME":
            hero_hud = self.find(frame, ["HeroChallenge"], threshold=0.85)
            if hero_hud and hero_hud.x <= 400 and hero_hud.y <= 150:
                print("[英雄模式] 已确认局内【英雄挑战】标识，开始主线")
                self._hero_state = "DONE"
                self.set_phase(Phase.MAIN_LINE, "hero mode in-game HUD verified")
                return LoopAction.Continue
            if self._find_hero_entry(frame):
                return self._hero_fail("开启挑战后返回选关页")
            print("[英雄模式] 等待加载完成和局内英雄挑战标识（零动作）")
            return LoopAction.Continue

        return self._hero_fail(f"未知英雄模式内部状态 {self._hero_state}")

    # ---------- 阶段推进 ----------

    def _reset_tqtz_round_state(self) -> None:
        """每局边界清零提前挑战（tqtz）状态：重试预算/ABANDONED 绝不跨局残留。"""
        self._tqtz_clicked = False
        self._tqtz_pending = False
        self._tqtz_pending_since = 0.0
        self._tqtz_pending_frame = None
        self._tqtz_next_check_at = 0.0
        self._tqtz_request_generation = -1
        self._tqtz_attempts = 0
        self._tqtz_abandoned = False
        self._tqtz_dialog_expected_until = 0.0
        self._tqtz_confirm_attempts = 0
        self._tqtz_confirm_next_at = 0.0

    def _is_reentry_or_attach(self, note: str) -> bool:
        """判断进入 MAIN_LINE 的附注是否为已有局重新附着/对齐（不执行局级清零）。

        A. 真正的新局（STAGE_STARTING -> MAIN_LINE 等）：执行完整局级 reset。
        B. 已有局重新附着 / reconcile：保持现有不能误清局内状态的行为。
        TODO: 后续重构可将 round boundary 触发原因统一抽象为显式 RoundBoundaryReason 枚举。
        """
        return any(
            marker in note for marker in (
                "already in game",
                "reconcile",
                "paused game",
                "existing game",
                "challenge return",
            )
        )

    def set_phase(self, phase: Phase, note: str = "") -> None:
        previous_phase = self.phase
        if phase != self.phase:
            print(f"[med] phase {self.phase.name} → {phase.name} {note}")
        if self.phase == Phase.ROOM_STARTING and phase != Phase.ROOM_STARTING:
            self._room_start_deadline = None
            self._room_start_next_retry_at = 0.0
        if phase in (Phase.LOBBY_ROOM, Phase.PLATFORM_MAP) and self.phase not in (Phase.LOBBY_ROOM, Phase.PLATFORM_MAP):
            self._stage_selected = False
            self._stage_target_name = None
            self._stage_target_position = None
            self._room_dialog_filled = False
            self._room_form_step = 0
            self._create_room_pending_since = None
            self._create_room_next_observe_at = None
            self._create_room_flow_deadline = None
            self._create_room_attempts = 0
            self._create_room_opened_ok = False
            self._create_room_last_candidate = None
        if phase in (Phase.PLATFORM_MAP, Phase.CREATE_ROOM):
            self._room_action_deadline = time.time() + self.settings.query_timeout
        if phase == Phase.CREATE_ROOM:
            self._room_dialog_filled = False
            self._room_form_step = 0
        if phase in (Phase.ROOM_STARTING, Phase.STAGE_STARTING):
            # 不覆盖调用方已设置的重试上下文（deadline/attempts 由点击发起方写入）；
            # 仅当未设置时才填默认值，避免 15s 验证窗被改写成 60s、attempts 被清零。
            if self._room_action_deadline is None:
                self._room_action_deadline = time.time() + self.settings.query_timeout
        if phase == Phase.STAGE_STARTING:
            # startChallenge 子状态机惰性初始化：测试/回放 harness 直接
            # set_phase(STAGE_STARTING) 时补建默认上下文，避免 None 状态卡死。
            if self._challenge_start_state is None:
                self._challenge_start_state = "WAIT_TRANSITION"
                self._challenge_start_source = "stage"
                self._challenge_start_deadline = time.time() + max(20, min(self.settings.query_timeout, 60))
                self._challenge_start_hud_frames = 0
                self._challenge_start_hero_modal_frames = 0
        if self.phase == Phase.STAGE_STARTING and phase != Phase.STAGE_STARTING:
            # 离开 STAGE_STARTING：清空帧级进度；attempts 是跨回退的重试预算，
            # 只在超时分支 +1（>=2 时 Fail-Closed），此处不重置以保证有界重试。
            self._challenge_start_state = None
            self._challenge_start_hud_frames = 0
            self._challenge_start_hero_modal_frames = 0
        if phase == Phase.STAGE_SELECT and self.phase != Phase.STAGE_SELECT:
            self._stage_scroll_attempts = 0
            self._old_world_switch_attempts = 0
            # 跨局重置：次局进入选关页必须重新选关（上一局残留会跳过选关/点错关）
            self._stage_selected = False
            self._stage_target_name = None
            self._stage_target_position = None
            self._stage_candidate_name = None
            self._stage_candidate_position = None
            self._stage_candidate_frames = 0
            self._stage_select_attempts = 0
            self._stage_scroll_cooldown_until = 0.0
            self._room_action_deadline = time.time() + self._l0_transition_timeout()
            self._hero_state = "IDLE"
            self._hero_verified_level = 0
            self._hero_level_baseline = None
            self._hero_level_candidate = None
            self._hero_card_baseline = None
            self._hero_step_deadline = None
            self._hero_modal_missing_frames = 0
            # S0 ④/⑥：进入选关页 = 新一轮开始 → 清 round 字段与 outcome 守卫，
            # 下一局拥有全新 hard deadline 与一次 outcome 记录权。
            self._round_started_at = None
            self._round_deadline = None
            self._outcome_recorded = False
            # 跨局重置：提前挑战重试预算/ABANDONED 必须随新一轮清零
            self._reset_tqtz_round_state()
            # Task 2: round/episode boundary — stale in-flight action tokens
            # must not bleed into the next episode and gate its first ticks.
            self._pending_action = None
            self._pending_action_unconfirmed_count = 0
            self._round_outcome = None
            # S0 ⑤：跨局每类面板会话计数/冷却清零（上限按"每局每类"计）
            self._panel_episode_count = {}
            self._panel_cooldown_until = {}
            self._panel_state = PanelState.CLOSED
            self._panel_kind = None
            self._panel_episode_id = None
            self._panel_first_seen_at = None
            self._panel_last_progress_at = None
            self._panel_episode_started = None
            self._panel_visible_deadline = None
            self._panel_mutation_baseline = None
            self._panel_pending_choice_action = None
            self._panel_pending_choice_fingerprint = None
            self._panel_opened_by_us = None
            self._panel_fingerprint = None
            self._panel_fingerprint_attempts = 0
            self._panel_anchor_candidate = None
            self._reset_f_draw_guard()
        is_reentry_or_attach = self._is_reentry_or_attach(note)
        entering_main_line = (
            phase == Phase.MAIN_LINE
            and not is_reentry_or_attach
            and (previous_phase != Phase.MAIN_LINE or "new game" in note)
        )
        if entering_main_line:
            self._stage_attempt_budget = None
            self._l1_cycle_step = "merchant" if self._passenger_mode() else "bond"
            self._reset_solo_plan_state()
            self._public_bag_fsm = PublicBagFSM()
            self._public_bag_failed_sources = {}
            self._public_bag_personal_leftover = False
            self._l1_cycle_last_advance_at = time.time()
            self._l1_cycle_step_successes = 0
            self._panel_visit_force_advance = False
            self._hitch_last_treasure_kill_balance = None
            self._hitch_treasure_total_refreshes = 0
            self._hitch_last_treasure_unconfirmed_fp = None
            self._treasure_consecutive_no_pick = 0
            self._reset_f_draw_guard()
        if phase == Phase.RECOVER_FAILURE and self.phase != Phase.RECOVER_FAILURE:
            # 进入恢复：清面板许可与待输入 token（抢占后 panel FSM 全部状态让位）
            self._panel_state = PanelState.CLOSED
            self._panel_opened_by_us = None
            self._panel_fingerprint = None
            self._panel_fingerprint_attempts = 0
            self._panel_anchor_candidate = None
            self._selection_unknown_attempts = 0
            self._selection_unknown_since = None
        # L0 cycle counter: increment when falling back to PLATFORM_MAP from a later L0 phase
        if phase == Phase.PLATFORM_MAP and self.phase in (Phase.ROOM_WAITING, Phase.ROOM_STARTING):
            self._l0_cycle_count += 1
            print(f"[med] L0 cycle {self._l0_cycle_count}/{self._l0_cycle_limit}")
        # Reset cycle counter when successfully advancing to game phases
        if phase in (Phase.STAGE_SELECT, Phase.MAIN_LINE):
            self._l0_cycle_count = 0
        if phase == Phase.ERROR:
            # B1-2：进入 Fail-Closed 前留档（此时 self.phase 仍是发生错误的原阶段）
            self._record_fail_closed_incident(note)
        self.phase = phase
        if phase == Phase.ERROR:
            self._interrupt_reason = note or "unspecified"
        if entering_main_line:
            self._main_line_since = time.time()
            self._main_line_started_at = self._main_line_since
            self._selection_click_cooldown_until = 0.0
            self._selection_unknown_attempts = 0
            self._selection_unknown_since = None
            self._selection_repeat_key = None
            self._selection_repeat_attempts = 0
            self._skill_refresh_attempts = 0
            self._skill_cards_pending.clear()
            self._skill_cards_owned.clear()
            self._bond_cards_pending.clear()
            self._bond_cards_owned.clear()
            self._hero_focus_lost_count = 0
            self._hero_focus_next_check_at = 0.0
            self._early_challenge_pending = False
            self._early_challenge_started_at = None
            self._early_challenge_clicked_at = None
            self._challenge_done.clear()
            self._challenge_attempts.clear()
            self._challenge_unknown_since.clear()
            self._challenge_pending_since.clear()
            self._challenge_next_observe_at.clear()
            self._reset_tqtz_round_state()
            self._pause_resume_attempts = 0
            self._pause_resume_next_at = 0.0
            self._close_main_line_triggered = False
            self._main_line_closed_done = False
            self._main_line_ocr_next_at = 0.0
            self._main_line_stall_stage = None
            self._main_line_stall_since = None
            self._main_line_stall_reason = None
            self._challenge_recheck_at.clear()
            # Per-round panel caps.  Hitch rounds never pass STAGE_SELECT,
            # where these used to reset, so round 2 inherited a capped V.
            self._panel_episode_count = {}
            self._panel_cooldown_until = {}
            self._hitch_treasure_retry_at = 0.0
            self._hitch_instance_seen = False
            self._hitch_instance_frames = 0
            self._hitch_instance_announced = False
            self._hitch_instance_last_frame = None
            # F4 clears challenges.  The first confirmed HUD frame belongs to
            # the normal bond-first opening cycle, so do not let a reset timer
            # clear challenges immediately on game entry.
            if self._passenger_mode():
                self._pressure_next_at = 0.0
            else:
                pressure_interval = float(getattr(self.settings, "pressure_interval_s", 20.0) or 20.0)
                self._pressure_next_at = self._main_line_since + pressure_interval
            self._challenge_states = {
                "coin_challenge": ChallengeState.PENDING,
                "wood_challenge": ChallengeState.PENDING,
                "experience_challenge": ChallengeState.PENDING,
                "treasure_challenge": ChallengeState.PENDING,
            }
            self._auto_task_done = False
            self._auto_task_attempts = 0
            self._auto_task_pending_since = None
            self._auto_task_next_observe_at = None
            self._auto_task_recheck_at = 0.0
            self._hitch_pressure_transferred = False
            self._hitch_pressure_click_at = None
            self._hitch_pressure_seen_since = None
            self._hitch_pressure_request_generation = None
            self._hitch_pressure_retry_count = 0
            self._hitch_pressure_request_attempts = 0
            self._hitch_pressure_core_failed = False
            self._archaeology_handoff_pending = False
            self._archaeology_handoff_own_room = False
            self._archaeology_click_at = None
            self._archaeology_click_generation = None
            self._archaeology_click_attempts = 0
            self._archaeology_template_miss_budget = 40
            self._room_leave_pending = False
            self._auto_task_unknown_since = None
            self._victory_continue_attempts = 0
            self._victory_continue_since = None
            self._post_game_pending = False
            self._hitch_postgame_started_at = None
            # Task 2: runtime watchdog HUD latch re-arms from zero on each
            # MAIN_LINE entry; stale confirmations from the prior episode
            # would grant unverified input authority on first ticks.
            self._runtime_watchdog_hud_confirmations = 0
            self._runtime_watchdog_last_frame_id = None
            self._post_game_hud_confirmations = 0
            self._pending_archive_panel_frames = 0
            self._post_game_archive_pending_only = False
            # 20260831 审查（P1-c）：route 必须随新局重置。残留的
            # archive/heirloom route 会让"无战后上下文"的未验证入口守卫
            # 永久豁免，直至其他逻辑改写。
            self._post_game_route = "secret"
            self._time_cave_boss_done = False
            self._time_cave_boss_clicked_at = None
            self._archive_challenge_index = 0
            self._archive_challenge_clicked = set()
            self._archive_challenge_verified = set()
            self._archive_verify_started = False
            self._archive_challenge_observe_attempts = 0
            self._archive_challenge_click_attempts = 0
            self._archive_challenge_confirm_attempts = 0
            self._heirloom_boss_clicked_at = None
            self._heirloom_boss_confirm_unconfirmed = False
            self._heirloom_boss_result_confirmed = False
            self._solo_heirloom_boss_waiting = False
            self._solo_heirloom_boss_waiting_since = None
            self._solo_heirloom_boss_clear_frames = 0
            self._solo_heirloom_boss_clear_last_frame = None
            self._post_game_hero_focus_lost_count = 0
            self._post_game_hero_focus_last_frame = None
            self._post_game_hero_focus_next_check_at = 0.0
            self._opportunistic_merchant_next_at = 0.0
            self._opportunistic_hero_card_next_at = 0.0
            self._passenger_heirloom_for_secret = False
            self._time_cave_boss_search_attempts = 0
            self._hitch_postgame_hero_selected = False
            self._hitch_postgame_returned_to_base = False
            self._post_game_hub_entered_at = None
            self._post_game_active_wait_since = None
            self._team_exit_ocr_next_at = 0.0
            self._team_exit_ocr_hits = 0
            self._team_exit_ocr_error_logged_at = 0.0
            self._post_game_close_attempts = 0
            self._secret_realm_request_pending = False
            self._secret_realm_request_since = None
            self._secret_realm_request_attempts = 0
            self._secret_realm_next_observe_at = 0.0
            self._secret_realm_entering_since = None
            self._secret_realm_confirm_attempts = 0
            self._secret_realm_confirm_next_observe_at = 0.0
            self._secret_realm_hud_confirmations = 0
            self._secret_realm_last_hud_frame_id = None
            self._secret_realm_active = False
            self._boss_challenge_attempts = 0
            self._boss_challenge_scroll_attempts = 0
            self._boss_challenge_scroll_signature = None
            self._boss_challenge_scroll_stable_frames = 0
            self._boss_challenge_next_at = 0.0
            self._boss_challenge_page = None
            self._aux_dialog_attempts = {"HEIRLOOM_DIALOG": 0, "GREAT_RIFT_CONFIRM": 0}
            # A verified game start owns a fresh retry/recovery episode.  A
            # timeout retry keeps its budget until this transition succeeds.
            self._challenge_start_attempts = 0
            self._failure_candidate_frames = 0
            self._failure_candidate_kind = None
            self._failure_candidate_gen = None
            self._recovery_step = None
            self._recovery_state = None
            # S0 ④：首次经连续局内锚点进入 MAIN_LINE 才设置不可续期 hard deadline；
            # 同一局重复 set_phase(MAIN_LINE)（挑战/英雄验证过渡）不得覆盖。
            if (
                self._round_deadline is None
                or previous_phase in (Phase.STAGE_STARTING, Phase.HERO_SETUP, Phase.STAGE_SELECT)
                or "new game" in note
            ):
                self._round_started_at = time.time()
                self._round_deadline = self._round_started_at + self.settings.round_timeout_s
            # S0 ⑤ 跨局 L1 瞬态重置：主动面板标记/神器 CD/主动面板时间戳/进化冷却
            self._panel_state = PanelState.CLOSED
            self._panel_kind = None
            self._panel_episode_id = None
            self._panel_first_seen_at = None
            self._panel_last_progress_at = None
            self._panel_episode_started = None
            self._panel_visible_deadline = None
            self._panel_mutation_baseline = None
            self._panel_pending_choice_action = None
            self._panel_pending_choice_fingerprint = None
            self._panel_opened_by_us = None
            self._panel_fingerprint = None
            self._panel_fingerprint_attempts = 0
            self._panel_anchor_candidate = None
            self._pending_action = None
            self._pending_action_unconfirmed_count = 0
            self._last_skill_panel = 0.0
            self._last_bond_attempt = 0.0
            self._last_treasure_attempt = 0.0
            self._artifact_next_q = 0.0
            self._artifact_next_w = 0.0
            self._artifact_next_e = 0.0
            self._evolve_click_cooldown_until = 0.0
            self._evolve_feedback_pending = False
            self._evolve_click_at = 0.0
            self._evolve_fail_count = 0
            self._evolve_baseline = None
            self._l1_cycle_step = "merchant" if self._passenger_mode() else "bond"
            self._public_bag_fsm = PublicBagFSM()
            self._public_bag_empty_since = None
            self._public_bag_failed_sources = {}
            self._l1_cycle_owned_panel = False
            self._l1_cycle_selected = False
            self._merchant_next_at = 0.0
            self._merchant_budget_retry_at = 0.0
            self._merchant_kill_balance_fingerprint = None
            self._merchant_kill_balance_value = None
            self._merchant_discovery_deadline = None
            self._merchant_fsm = MerchantFSM()
            self._equipment_next_at = 0.0
            self._equipment_pending_until = 0.0
            self._pickup_next_at = 0.0
            self._fail_gift_attempts = 0
            self._evolution_attempts = 0
            self._evolution_next_at = 0.0
            self._evolution_baseline = None
            self._evolve_ok_this_cycle = False
            self._inventory_clicks_this_visit = 0
            self._inventory_last_pt = None
            self._inventory_same_pt_hits = 0
            self._inventory_next_at = 0.0
            self._devour_dan_consecutive_clicks = 0
        # Keep the exit-chain retry budget across QUIT -> NEXT -> QUIT, but
        # clear it at a real room/round boundary or when a new chain starts.
        if phase not in (Phase.QUIT, Phase.NEXT) or self.phase not in (Phase.QUIT, Phase.NEXT):
            self._exit_rearm_attempts = 0
        if phase == Phase.QUIT:
            self._exit_button_attempts = 0
            self._exit_since = time.time()
        if phase == Phase.NEXT:
            self._exit_confirm_attempts = 0
            self._exit_since = time.time()
        if phase == Phase.LONGZHU:
            # 对齐「退出游戏时间还剩下 ~178 秒」
            sec = max(self.settings.archive_boss_time, self.settings.boss_live_time, 180)
            self._longzhu_deadline = time.time() + sec
            self._f1_fallback_done = False

    def longzhu_timed_out(self) -> bool:
        if self._longzhu_deadline is None:
            return False
        return time.time() >= self._longzhu_deadline

    # ---------- S0 ③ RECOVER_FAILURE：有门闩、分脚本、有限预算 ----------

    def _begin_recovery(self, kind: RecoveryKind) -> None:
        """抢占确认后启动恢复 episode：总预算 recovery_timeout_s 固定，不可续期。

        恢复期间不进入 QUIT；恢复完成（_finish_recovery）才 set_phase(QUIT)，
        届时 _exit_since 初始化 —— 退出期限从恢复完成那一刻开始计算。
        """
        now = time.time()
        timeout_s = min(float(self.settings.recovery_timeout_s), 120.0)
        self._recovery_state = RecoveryState(
            kind=kind,
            step=RecoveryStep.FAIL_CONFIRM if kind == RecoveryKind.FAIL else RecoveryStep.DISCONNECT_RETRY,
            started_at=now,
            deadline=now + timeout_s,
            attempts={},
            next_allowed_at=now,
        )
        self._recovery_step = None
        self.set_phase(Phase.RECOVER_FAILURE, f"recovery start ({kind.name})")
        # G0 P0 contract #3：最近恢复动作可读（fail-closed bounded list）。
        self.recent_recovery_actions = (self.recent_recovery_actions + [f"{kind.name}:start:{int(now)}"])[-20:]
        self._record_recovery_incident("recovery_start")

    def _recovery_anchor(self, frame: Frame, rs: RecoveryState) -> MatchResult | None:
        """本步前置锚点（任一命中才允许动作；缺锚点 = 一次有界重试消耗）。"""
        if rs.step == RecoveryStep.FAIL_CONFIRM:
            return self.find_scene(frame, "fail")
        if rs.step == RecoveryStep.FAIL_EXIT_CONFIRM:
            return self._find_exit_confirm(frame)
        if rs.step == RecoveryStep.FAIL_CLOSE:
            return self.find_scene(frame, "close")
        if rs.step == RecoveryStep.DISCONNECT_RETRY:
            return self.find_scene(frame, "disconnect")
        return None

    def _recovery_action(self, frame: Frame, rs: RecoveryState) -> MatchResult | None:
        """本步动作：FAIL=点 ok（确定）；FAIL_CLOSE=点 close；DISCONNECT=仅点重连按钮。

        断线脚本只操作 disconnect/retry/reconnect 独立锚点：find_scene("disconnect")
        命中的若是 gameDisconnect 文字模板则零输入等待，绝不点击 fail 的 ok/close。
        """
        if rs.step == RecoveryStep.FAIL_CONFIRM:
            hit = None
            if self._game_chat_input_visible(frame):
                # The chat bar lies across the modal's button row: never
                # click through it, use the top-left 退出游戏 instead.
                rs.prefer_game_exit = True
            if not rs.prefer_game_exit:
                hit = self.find_scene(frame, "ok") or self._find_failure_exit_button(frame)
            if hit is not None:
                return hit
            # The real secret-realm failure page has no center modal.  It keeps
            # the strong fail anchor visible and requires the dedicated top-left
            # game exit, followed by the standard exit confirmation dialog.
            exit_hit = self._find_game_exit(frame)
            if exit_hit is None:
                return None
            return MatchResult(
                "failure_open_exit",
                exit_hit.score,
                exit_hit.x,
                exit_hit.y,
                exit_hit.w,
                exit_hit.h,
                exit_hit.screen_x,
                exit_hit.screen_y,
            )
        if rs.step == RecoveryStep.FAIL_EXIT_CONFIRM:
            return self._find_exit_confirm(frame)
        if rs.step == RecoveryStep.FAIL_CLOSE:
            return self.find_scene(frame, "close")
        if rs.step == RecoveryStep.DISCONNECT_RETRY:
            hit = self.find_scene(frame, "disconnect")
            if hit is not None and hit.name == "retryConnect":
                return hit
            return None
        return None

    def _find_failure_exit_button(self, frame: Frame) -> MatchResult | None:
        """Find the red 退出游戏 button on the real 1.4.11 failure modal.

        The modal has no OK button. Authority requires the strong gameFail
        anchor plus a red/green sibling pair in its constrained bottom row,
        or an authoritative red exit component in the modal's left bottom row
        when the green button is hovered or obscured.
        """
        fail = self.find_scene(frame, "fail")
        if fail is None or frame.bgr is None or frame.width < 1000 or frame.height < 600:
            return None
        x0, x1 = int(frame.width * 0.30), int(frame.width * 0.70)
        y0, y1 = int(frame.height * 0.55), int(frame.height * 0.75)
        roi = frame.bgr[y0:y1, x0:x1]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        def components(mask: np.ndarray) -> list[tuple[int, int, int, int, int]]:
            count, _labels, stats, _centers = cv2.connectedComponentsWithStats(
                mask.astype("uint8")
            )
            out = []
            for x, y, w, h, area in stats[1:count]:
                if 70 <= w <= 180 and 20 <= h <= 65 and area >= 1000:
                    out.append((int(x), int(y), int(w), int(h), int(area)))
            return out

        red = components(
            ((hsv[:, :, 0] <= 10) | (hsv[:, :, 0] >= 170))
            & (hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 80)
        )
        green = components(
            (hsv[:, :, 0] >= 35) & (hsv[:, :, 0] <= 90)
            & (hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 80)
        )
        for rx, ry, rw, rh, area in sorted(red, key=lambda item: -item[4]):
            rcx, rcy = rx + rw // 2, ry + rh // 2
            if any(gx > rx and abs((gy + gh // 2) - rcy) <= 20
                   for gx, gy, gw, gh, _area in green):
                x, y = x0 + rcx, y0 + rcy
                return MatchResult(
                    "failure_exit", min(1.0, area / 2500.0), x, y, rw, rh,
                    frame.left + x, frame.top + y,
                )
        roi_w = x1 - x0
        # 20260831 审查：红兜底要求组件位于 gameFail 图标下方的按钮带
        # （真实模态：图标中心 y≈0.49，按钮行 y≈0.64），排除图标上方/同排的
        # 红色警告组件被误点。
        button_band_top = fail.y + fail.h
        for rx, ry, rw, rh, area in sorted(red, key=lambda item: -item[4]):
            rcx, rcy = rx + rw // 2, ry + rh // 2
            if rcx < roi_w * 0.52 and y0 + rcy >= button_band_top:
                x, y = x0 + rcx, y0 + rcy
                return MatchResult(
                    "failure_exit", min(1.0, area / 2500.0), x, y, rw, rh,
                    frame.left + x, frame.top + y,
                )
        return None

    def _recovery_post_confirmed(self, frame: Frame, rs: RecoveryState) -> bool:
        """WAIT_CONFIRM 后置确认：画面 mutation（模板消失）∨ 必需 post-anchor 出现。"""
        if rs.step == RecoveryStep.FAIL_CONFIRM:
            confirm = self._find_exit_confirm(frame)
            if confirm is not None:
                rs.opening_exit_confirm = True
                rs.post_anchor_seen = True
                return True
            if rs.opening_exit_confirm:
                return False
            if self.find_scene(frame, "fail") is None:
                rs.mutation_seen = True
                return True
            if rs.direct_exit:
                return False
            if self.find_scene(frame, "close") is not None:
                rs.post_anchor_seen = True
                return True
            return False
        if rs.step == RecoveryStep.FAIL_CLOSE:
            gone = self.find_scene(frame, "fail") is None and self.find_scene(frame, "close") is None
            if gone:
                rs.mutation_seen = True
            return gone
        if rs.step == RecoveryStep.DISCONNECT_RETRY:
            if self.find_scene(frame, "disconnect") is None:
                rs.mutation_seen = True
                return True
            if self._selection_anchor(frame) or self._is_in_game_hud(frame):
                rs.post_anchor_seen = True
                return True
            return False
        return False

    def _advance_recovery(self, frame: Frame, rs: RecoveryState, now: float) -> LoopAction:
        """后置确认成立：推进到下一步或完成。"""
        if rs.step == RecoveryStep.FAIL_CONFIRM:
            if rs.opening_exit_confirm:
                rs.step = RecoveryStep.FAIL_EXIT_CONFIRM
                rs.opening_exit_confirm = False
                rs.waiting_confirm = False
                rs.next_allowed_at = max(
                    now,
                    rs.input_at + self.settings.ui_action_interval_s,
                )
                print("[med] 失败页已打开标准退出确认框，等待安全点击确认")
                return LoopAction.Continue
            if rs.direct_exit:
                return self._finish_direct_failure_exit(rs, now)
            # ok 点击后：close 按钮出现 → FAIL_CLOSE；失败弹窗消失 → 直接完成
            if self.find_scene(frame, "close") is not None:
                rs.step = RecoveryStep.FAIL_CLOSE
            else:
                return self._finish_recovery(rs, now)
        elif rs.step == RecoveryStep.FAIL_EXIT_CONFIRM:
            return self._finish_direct_failure_exit(rs, now)
        elif rs.step == RecoveryStep.FAIL_CLOSE:
            return self._finish_recovery(rs, now)
        elif rs.step == RecoveryStep.DISCONNECT_RETRY:
            return self._finish_recovery(rs, now)
        rs.waiting_confirm = False
        rs.next_allowed_at = now
        print(f"[med] 恢复步骤推进：{rs.kind.name}/{rs.step.name}")
        return LoopAction.Continue

    def _finish_direct_failure_exit(self, rs: RecoveryState, now: float) -> LoopAction:
        """A verified failure-exit action was sent; verify return to the same room."""
        rs.step = RecoveryStep.DONE
        if self._secret_realm_active:
            # A great-rift run naturally ends on its first failed layer.  The
            # main map was already won, so this is a completed unattended cycle,
            # not one strike toward the consecutive real-failure fuse.
            self._record_round_outcome(
                RoundOutcome.VICTORY,
                "secret realm ended; verified exit",
            )
        else:
            self._record_round_outcome(RoundOutcome.FAILURE, "verified failure exit")
        self._recovery_step = "DONE"
        self._recovery_state = None
        if self._hitch_enabled():
            return self._finish_hitch_round(now, "verified failure exit; hitch re-search")
        self._awaiting_room_return = True
        self.set_phase(Phase.PREPARE, "failure exit clicked; verify same room")
        self._room_action_deadline = now + min(self.settings.query_timeout, 30)
        return LoopAction.Continue

    def _recovery_failed(self, rs: RecoveryState, reason: str) -> LoopAction:
        """恢复重试耗尽/总预算到期：普通模式直接 ERROR、停止、写 incident；hitch 模式清理后回大厅观察。"""
        if self._hitch_enabled():
            now = time.time()
            last = getattr(self, "_last_frame", None)
            if last is not None and self._is_game_client_frame(last):
                # The game is still up (live 2026-09-12: failure page with the
                # modal buttons covered).  Leave it through the standard quit
                # chain: top-left 退出游戏 -> confirmation -> next round.
                print(f"[med] 蹭车恢复未完成（{reason}），游戏窗口仍在：改走左上角退出游戏链路")
                self._record_round_outcome(RoundOutcome.FAILURE, f"hitch recovery fallback ({reason})")
                self._recovery_state = None
                # "DONE" keeps the QUIT phase from re-preempting into
                # recovery on the still-visible failure page.
                self._recovery_step = "DONE"
                self.set_phase(Phase.QUIT, f"hitch recovery failed ({reason}); quit game")
                return LoopAction.Continue
            print(f"[med] 蹭车恢复重试耗尽（{reason}）：执行后置退出清理，进入大厅观察，不终止运行")
            self._hitch_after_exit(now)
            self.set_phase(Phase.LOBBY_ROOM, f"hitch recovery failed ({reason}); awaiting lobby observation")
            return LoopAction.Continue
        print(f"[med] 恢复失败（{reason}）：Fail-Closed 停止运行")
        self._record_recovery_incident("recovery_failed", reason=reason)
        self.set_phase(Phase.ERROR, f"recovery failed: {reason}")
        self.stop()
        return LoopAction.Break

    def _finish_recovery(self, rs: RecoveryState, now: float) -> LoopAction:
        """恢复确认完毕：outcome = FAILURE/DISCONNECT，然后才进入 QUIT（退出期限此刻起算）。"""
        rs.step = RecoveryStep.DONE
        outcome = RoundOutcome.DISCONNECT if rs.kind == RecoveryKind.DISCONNECT else RoundOutcome.FAILURE
        self._record_round_outcome(outcome, f"recovery complete ({rs.kind.name})")
        self._recovery_step = "DONE"  # trace/benchmark 兼容镜像；不承载推进语义
        self._recovery_state = None
        print(f"[med] 恢复完成（{rs.kind.name}），进入 QUIT（退出窗口从现在开始）")
        self.set_phase(Phase.QUIT, f"recovery complete ({rs.kind.name})")
        return LoopAction.Continue

    def _tick_recovery(self, frame: Frame) -> LoopAction:
        """RECOVER_FAILURE 阶段处理器：每步门闩 anchor∧input_ok∧(mutation∨post_anchor)。

        每动作 ≤ recovery_action_limit 次、间隔 ≥ recovery_retry_interval_s、
        总预算 recovery_timeout_s（开始时固定）；恢复完成前 QUIT 输入为 0。
        """
        rs = self._recovery_state
        if rs is None:
            # 防御：无状态但进入 RECOVER_FAILURE（异常回放/直接 set_phase）
            self.set_phase(Phase.ERROR, "recovery state missing")
            self.stop()
            return LoopAction.Break
        now = time.time()
        if now >= rs.deadline:
            return self._recovery_failed(rs, "recovery timeout")
        step = rs.step
        if rs.waiting_confirm:
            # 已点击成功：每 tick 观察 mutation/后置锚点（不受输入间隔限制）；
            # 未确认不得再次选择。
            if self._recovery_post_confirmed(frame, rs):
                return self._advance_recovery(frame, rs, now)
            if now - rs.input_at >= rs.confirm_window:
                # 确认窗超时：本步保留，消耗一次有界重试后回 READY
                rs.waiting_confirm = False
                if step == RecoveryStep.FAIL_CONFIRM and rs.direct_exit:
                    # The modal exit click changed nothing: switch to the
                    # top-left 退出游戏 path for the remaining attempts.
                    rs.direct_exit = False
                    rs.prefer_game_exit = True
                    print("[med] 失败页中间退出按钮点击无效，改用左上角退出游戏")
                return self._recovery_retry_or_fail(rs, step, now, "no mutation/post-anchor")
            return LoopAction.Continue
        if now < rs.next_allowed_at:
            return LoopAction.Continue  # 输入间隔 ≥1.5s（零动作）
        # READY：前置锚点 + 动作 + 输入成功门闩
        anchor = self._recovery_anchor(frame, rs)
        if anchor is None:
            return self._recovery_retry_or_fail(rs, step, now, "anchor missing")
        action_hit = self._recovery_action(frame, rs)
        if action_hit is None:
            # 锚点存在但本步动作按钮未出现（如断线弹窗只有文字）：零输入等待，
            # 不消耗尝试（属正常等待，非失败尝试）。
            return LoopAction.Continue
        rs.anchor_before = anchor
        clicked = self.act_click(action_hit, reason=f"Recovery-{rs.kind.name}-{rs.step.name}")
        rs.input_ok = clicked
        rs.attempts[step] = rs.attempts.get(step, 0) + 1
        rs.next_allowed_at = now + self.settings.recovery_retry_interval_s
        if clicked:
            if action_hit.name == "failure_exit":
                rs.direct_exit = True
            elif action_hit.name == "failure_open_exit":
                rs.opening_exit_confirm = True
            elif step == RecoveryStep.FAIL_EXIT_CONFIRM:
                # Match the normal NEXT handler: after a dedicated confirmation
                # anchor and successful input, PREPARE owns the bounded room
                # return verification.  Waiting on the closing game HWND here
                # would turn a successful exit into a capture failure.
                return self._finish_direct_failure_exit(rs, now)
            rs.waiting_confirm = True
            rs.input_at = now
            # A modal exit either closes the game quickly or was swallowed.
            window = 5.0 if rs.direct_exit else 15.0
            rs.confirm_window = min(window, rs.deadline - now)
            print(f"[med] 恢复步骤 {rs.kind.name}/{rs.step.name} 已输入（等待后置确认）")
        else:
            limit = min(int(self.settings.recovery_action_limit), 3)
            if rs.attempts[step] > limit or now >= rs.deadline:
                return self._recovery_failed(rs, "input rejected, attempts exhausted")
            print(f"[med] 恢复输入被拒（{action_hit.name}），保留本步等待重试间隔")
        return LoopAction.Continue

    def _recovery_retry_or_fail(
        self, rs: RecoveryState, step: RecoveryStep, now: float, reason: str
    ) -> LoopAction:
        """缺锚点/无后置确认：保留本步并消耗/等待其有界重试。"""
        rs.attempts[step] = rs.attempts.get(step, 0) + 1
        rs.next_allowed_at = now + self.settings.recovery_retry_interval_s
        limit = min(int(self.settings.recovery_action_limit), 3)
        if rs.attempts[step] > limit or now >= rs.deadline:
            return self._recovery_failed(rs, reason)
        print(f"[med] 恢复 {rs.kind.name}/{step.name} 未推进（{reason}，尝试 {rs.attempts[step]}/"
              f"{self.settings.recovery_action_limit}）")
        return LoopAction.Continue

    def _record_round_outcome(self, outcome: RoundOutcome, reason: str) -> None:
        """一局只能落一个终局 outcome（_outcome_recorded 守卫，防恢复/退出双重计数）。

        仅确认完整胜利链才 success_count+1 且 failure_streak=0；FAILURE/TIMEOUT/
        DISCONNECT 均属于不成功局而递增 streak（防断线/超时绕开熔断）。
        """
        if self._outcome_recorded:
            return
        self._outcome_recorded = True
        self._round_outcome = outcome
        self._last_outcome = outcome
        if outcome == RoundOutcome.VICTORY:
            self._success_count += 1
            self._failure_streak = 0
            print(f"[med] outcome=VICTORY（{reason}）success={self._success_count} streak=0")
        else:
            if outcome == RoundOutcome.FAILURE:
                self._failure_count += 1
            elif outcome == RoundOutcome.DISCONNECT:
                self._disconnect_count += 1
            elif outcome == RoundOutcome.TIMEOUT:
                self._timeout_count += 1
            self._failure_streak += 1
            print(f"[med] outcome={outcome.name}（{reason}）failure_streak={self._failure_streak}"
                  f"/{self.settings.failure_streak_limit}")
            self._maybe_downgrade_stage_target()

    def _maybe_downgrade_stage_target(self) -> None:
        """打不过自动降级（Owner 2026-09-15）：连续 N 局非胜利后选关目标降一级。

        复用 `_failure_streak`（与熔断同一口径）；降级成功即清零，避免降级
        那局还没打就被 `failure_streak_limit` 熔断停机。已在 1-1 时不再降级，
        让 streak 继续累积直到熔断——「熔断只对降到 1-1 仍失败生效」。
        """
        n = int(getattr(self.settings, "downgrade_after_failures", 0) or 0)
        if n <= 0 or self._failure_streak < n:
            return
        current = configured_stage_id(self.settings.stage_targets, self.settings.stage1, self.settings.stage2)
        if current is None or current.index <= 1:
            return
        downgraded = StageId(current.chapter, current.index - 1)
        self.settings.stage_targets = [str(downgraded)]
        print(f"[med] 降级 {current}→{downgraded}（连续失败 {self._failure_streak} 局）")
        self._failure_streak = 0

    # ---------- B1-2 incident 归档辅助（无 incident_dir 时全部空转）----------

    def _incident_meta(
        self,
        kind: str,
        reason: str,
        *,
        score: float | None = None,
        final_action: str = "stop",
        action: str | None = None,
        attempt: int | None = None,
        deadline: float | None = None,
        rois: list | None = None,
        extra: dict | None = None,
    ) -> dict:
        """S0.5 统一 incident metadata：至少 phase/context/evidence/action/attempt/
        deadline/outcome/reason/health；ROI 与模板分数来自已裁检测区域；敏感字段
        由 _scrub_sensitive_keys 兜底（房间密码等永不落盘）。
        """
        frame = self._last_frame
        meta: dict = {
            "kind": kind,
            "phase": self.phase.name,
            "context": self._context_cache_value,
            "hwnd": frame.hwnd if frame is not None else None,
            "window_title": frame.window_title if frame is not None else "",
            "size": [frame.width, frame.height] if frame is not None else None,
            "score": score,
            "candidate_actions": list(self._trace_actions),
            "action": action,
            "attempt": attempt,
            "deadline": deadline,
            "outcome": self._round_outcome.name if self._round_outcome else None,
            "final_action": final_action,
            "reason": reason,
            "rois": rois if rois is not None else (self._panel_roi(frame) if frame is not None else []),
            "evidence": {
                "scenes": list(self._trace_scenes),
                "generation": self._evidence.gen if self._evidence is not None else None,
                "hwnd": frame.hwnd if frame is not None else None,
                "ui_scale": self._ui_scale,
            },
        }
        if extra:
            meta.update(extra)
        return _scrub_sensitive_keys(meta)

    def _record_recovery_incident(self, kind: str, reason: str = "") -> None:
        """S0.5：恢复 episode 起点/失败归档（dedup 由 archiver 指纹窗口承担）。"""
        if self._archiver is None:
            return
        frame = self._last_frame
        if frame is None or frame.bgr is None or frame.bgr.size == 0:
            return
        rs = self._recovery_state
        saved = self._archiver.maybe_record(
            frame_before=self._prev_frame,
            frame_now=frame,
            metadata=self._incident_meta(
                f"recovery_{kind}",
                reason or f"recovery {kind}",
                final_action="wait" if kind == "recovery_start" else "stop",
                attempt=None,
                deadline=rs.deadline if rs is not None else None,
                extra={
                    "recovery_kind": rs.kind.name if rs is not None else None,
                    "recovery_step": rs.step.name if rs is not None else None,
                },
            ),
            healthy=True,
            health_issues=[],
            health_details="",
        )
        if saved is not None:
            self._incident_pending_fp = saved
            if self._tick_reason is None:
                self._tick_reason = "incident_write"

    def _record_fail_closed_incident(self, note: str) -> None:
        """B1-2/S0.5：进入 Phase.ERROR（LIVE Fail-Closed / dry-run OBSERVE）前归档当前帧证据。

        事件来源：所有 Fail-Closed 停机分支统一经 set_phase(Phase.ERROR, ...)
        汇合；在此留档可覆盖未知页超时、重试耗尽、页面异变、不健康帧超时、
        round/recovery/exit timeout 等全部场景，无需逐个分支埋点。调用发生在
        self.phase 赋值之前，metadata.phase 因此是发生错误的原阶段而非 ERROR。
        """
        if self._archiver is None:
            return
        frame = self._last_frame
        if frame is None or frame.bgr is None or frame.bgr.size == 0:
            return
        health = self._last_health
        saved = self._archiver.maybe_record(
            frame_before=self._prev_frame,
            frame_now=frame,
            metadata=self._incident_meta(
                "fail_closed",
                note or "unspecified",
                deadline=self._round_deadline,
            ),
            healthy=bool(health is None or health.is_healthy),
            health_issues=[i.value for i in (health.issues if health else [])],
            health_details=health.details if health else "",
        )
        if saved is not None:
            self._incident_pending_fp = saved

    def _record_selection_unknown(self, frame: Frame, anchor: MatchResult | None, reason: str) -> None:
        """B1-2：选择面板分类失败/无候选命中时归档（不产生任何输入）。

        事件来源：_find_reward_choice 中 _classify_choice_panel 返回 None
        （面板锚点存在但按钮组合无法归类）——旧行为会因此假装 skill 扫全库。
        """
        if self._archiver is None:
            return
        saved = self._archiver.maybe_record(
            frame_before=self._prev_frame,
            frame_now=frame,
            metadata=self._incident_meta(
                "selection_unknown",
                reason,
                score=anchor.score if anchor is not None else None,
                final_action="wait",
                deadline=self._round_deadline,
            ),
            healthy=True,
            health_issues=[],
            health_details="",
        )
        if saved is not None:
            self._incident_pending_fp = saved

    def _record_lobby_observation_incident(
        self,
        kind: str,
        reason: str,
        frame: Frame | None = None,
        *,
        attempt: int | None = None,
        extra: dict | None = None,
    ) -> None:
        """Archive a lobby recovery observation without entering ERROR/stop."""
        if self._archiver is None:
            return
        current = frame or self._last_frame
        if current is None or current.bgr is None or current.bgr.size == 0:
            return
        saved = self._archiver.maybe_record(
            frame_before=self._prev_frame,
            frame_now=current,
            metadata=self._incident_meta(
                f"lobby_{kind}",
                reason,
                final_action="wait",
                attempt=attempt,
                deadline=self._hitch_floor_exit_deadline,
                extra=extra,
            ),
            healthy=True,
            health_issues=[],
            health_details="",
        )
        if saved is not None:
            self._incident_pending_fp = saved
            if self._tick_reason is None:
                self._tick_reason = "incident_write"

    def _record_repeat_click(self, frame: Frame, choice: tuple[str, MatchResult], attempts: int) -> None:
        """B1-2：同一选择连续 2 次点击无页面变化时归档。

        事件来源：_tick_main_line 的 _selection_repeat_key/attempts 重试检测；
        attempts==3 表示同面板同选项已连续出现 3 次（第 1、2 次点击均未改变
        页面），正是蓝图 B4-3「连续 2 次无变化」的检测点。
        """
        if self._archiver is None:
            return
        kind, hit = choice
        saved = self._archiver.maybe_record(
            frame_before=self._prev_frame,
            frame_now=frame,
            metadata=self._incident_meta(
                "repeat_click_no_change",
                f"{kind}选择 {hit.name} 连续 {attempts} 次点击无页面变化",
                score=hit.score,
                final_action="close_panel",
                attempt=attempts,
                deadline=self._round_deadline,
                rois=self._panel_roi(frame),
                extra={
                    "candidate_actions": [
                        {
                            "intent": f"click:{hit.name}",
                            "at": [hit.screen_x, hit.screen_y],
                            "reason": f"{kind}选择",
                            "repeat_attempts": attempts,
                        }
                    ]
                },
            ),
            healthy=True,
            health_issues=[],
            health_details="",
        )
        if saved is not None:
            self._incident_pending_fp = saved

    def _panel_roi(self, frame: Frame) -> list[dict]:
        """选择面板 ROI（帧内坐标），供 incident 裁剪参考图。"""
        x1, y1, x2, y2 = self._selection_roi()
        return [
            {
                "label": "panel",
                "x": int(frame.width * x1),
                "y": int(frame.height * y1),
                "w": int(frame.width * (x2 - x1)),
                "h": int(frame.height * (y2 - y1)),
            }
        ]

    # ---------- L0 显式页面链 ----------

    def _auto_room_enabled(self) -> bool:
        return self.settings.auto_create_room or self.settings.game_mode == 1

    def _hitch_enabled(self) -> bool:
        return str(getattr(self.settings, "mode_id", "") or "") == "lobby_hitch"

    def _follow_enabled(self) -> bool:
        return str(getattr(self.settings, "mode_id", "") or "") == "follow_team"

    def _passenger_mode(self) -> bool:
        """Hitch and follow share the in-game/post-game passenger contract."""
        return self._hitch_enabled() or self._follow_enabled()

    # Desktop live modes that run unattended for many rounds (mode_specs:
    # live_enabled + desktop_start).  Cloud audit 2026-09-14 B0: recovery
    # used to ride on _passenger_mode(), so normal_farm stopped the whole
    # run on UI hiccups that hitch already recovers from.
    _UNATTENDED_RECOVERY_MODES = frozenset({"normal_farm", "lobby_hitch", "follow_team"})

    def _unattended_recovery_enabled(self) -> bool:
        """May a recoverable UI failure end the round instead of the run?

        Only the lifecycle changes: action authority stays fail-closed (an
        unknown page still gets zero input), and every re-armed wait stays
        bounded by the liveness supervisor, the post-game cap and the round
        deadline.  Passenger business rules keep using _passenger_mode().
        """
        return str(getattr(self.settings, "mode_id", "") or "") in self._UNATTENDED_RECOVERY_MODES

    def _team_mode_enabled(self) -> bool:
        mode = str(getattr(self.settings, "mode_id", "") or "")
        return mode in {"lobby_hitch", "follow_team", "lead_team", "lead"}

    def _team_post_game_player_left(self, frame: Frame, now: float) -> bool:
        """Return true only after two bounded OCR confirmations of a leave notice."""
        if now < self._team_exit_ocr_next_at:
            return False
        self._team_exit_ocr_next_at = now + 1.0
        client = getattr(self, "_ocr_client", None)
        if client is None:
            return False
        bbox = self._normalized_bbox(frame, (0.25, 0.58, 0.75, 0.74))
        try:
            response = client.shadow_predict(
                frame,
                "post_game_chat",
                {"slot_id": 0, "bbox": bbox, "kind": "text"},
                session="post_game",
                panel_bbox=bbox,
            )
        except (AttributeError, OSError, TypeError, ValueError) as exc:
            if now >= self._team_exit_ocr_error_logged_at:
                print(f"[med] 战后队友退出 OCR 不可用: {type(exc).__name__}")
                self._team_exit_ocr_error_logged_at = now + 10.0
            return False
        if response.status != "ok":
            return False
        text = "".join(str(response.raw_text or "").split())
        markers = ("退出游戏", "离开游戏", "退出了游戏", "离开房间")
        self._team_exit_ocr_hits = self._team_exit_ocr_hits + 1 if any(marker in text for marker in markers) else 0
        if self._team_exit_ocr_hits >= 2:
            print("[med] 战后队友退出提示已连续 OCR 确认")
            return True
        return False

    def _wait_for_team_post_game_exit(self, frame: Frame, now: float) -> LoopAction:
        if self._post_game_hub_entered_at is None:
            self._post_game_hub_entered_at = now
        if self._team_post_game_player_left(frame, now):
            reason = "player left observed, team post-game exit"
        elif now - self._post_game_hub_entered_at >= 180.0:
            reason = "post-game team wait 180s timeout"
        else:
            print("[med] 组队战后等待队友退出或 180 秒上限（零输入）")
            return LoopAction.Continue
        self._post_game_pending = False
        self._record_round_outcome(RoundOutcome.VICTORY, reason)
        self.set_phase(Phase.QUIT, reason)
        return LoopAction.Continue

    def _passive_choice_mode(self) -> bool:
        return self._passenger_mode()

    @staticmethod
    def _hitch_room_list_row_count(frame: Frame, anchor: MatchResult) -> int:
        """Count independent occupancy-row bands below the list surface anchor.

        The occupancy cells are deliberately used only as corroboration.  A
        single template hit, a tab background, or a generic blue button is not
        enough to grant ROOM_LIST identity.
        """
        if frame.bgr is None or frame.width <= 0 or frame.height <= 0:
            return 0
        x0 = int(frame.width * 0.48)
        x1 = int(frame.width * 0.82)
        y0 = min(frame.height, int(anchor.y + anchor.h + frame.height * 0.025))
        y1 = int(frame.height * 0.88)
        roi = frame.bgr[y0:y1, x0:x1]
        if roi.size == 0:
            return 0
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        # KK's n/4 cell is bright text on a dark row; keep low-saturation text
        # and exclude the colored row icons/avatars.
        mask = ((gray >= 145) & (hsv[:, :, 1] < 125)).astype(np.uint8)
        _count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
        centers: list[tuple[int, int]] = []
        for x, y, width, height, area in stats[1:]:
            x, y, width, height, area = map(int, (x, y, width, height, area))
            if not (2 <= width <= 70 and 4 <= height <= 28 and area >= 8):
                continue
            centers.append((y + height // 2, area))
        centers.sort()
        bands: list[list[int]] = []
        for center_y, area in centers:
            if not bands or center_y - bands[-1][0] > 18:
                bands.append([center_y, 1, area])
            else:
                bands[-1][1] += 1
                bands[-1][2] += area
        return sum(1 for _center_y, components, area in bands if components >= 2 or area >= 24)

    def _lobby_room_list_evidence(self, frame: Frame) -> bool:
        """Require the search/table/row surface, never a low-information patch.

        The search icon, room-list header, and either row occupancy evidence or
        a refresh/selected-tab control must agree.  If the search control is
        temporarily absent, the header itself is the structural row anchor so
        the bounded search-recovery subflow can still run.  Join authority
        remains stricter and requires the real search icon below.  Modal shell
        detection runs first because a modal keeps the underlying list visible
        by design.
        """
        if self._kk_platform_modal_shell(frame) is not None:
            return False
        search = self.find_scene(frame, "lobby_search_icon")
        header = self.find_scene(frame, "lobby_room_list")
        if header is None:
            return False
        if search is not None and not (int(frame.height * 0.15) <= search.y <= int(frame.height * 0.45)):
            return False
        refresh = self.find_scene(frame, "lobby_refresh")
        tab = frame.bgr[
            int(frame.height * 0.24):int(frame.height * 0.29),
            int(frame.width * 0.22):int(frame.width * 0.32),
        ] if frame.bgr is not None else None
        selected_pixels = 0
        if tab is not None and tab.size:
            blue, green, red = cv2.split(tab)
            selected_pixels = int(np.count_nonzero(
                (blue > 100) & (green > 80) & (red < 100)
                & ((blue.astype(np.int16) - red.astype(np.int16)) > 70)
            ))
        rows = self._hitch_room_list_row_count(frame, search or header)
        return bool(
            (rows >= 2 and (refresh is not None or selected_pixels >= 20))
            or (refresh is not None and selected_pixels >= 20)
        )

    def _find_hitch_room_list_tab(self, frame: Frame) -> MatchResult | None:
        """Find only the fixed room-list tab slot, never a different active tab."""
        if frame.bgr is None or frame.width <= 0 or frame.height <= 0:
            return None
        x0, x1 = int(frame.width * 0.22), int(frame.width * 0.32)
        # KK chrome is fixed-pixel: the map tab strip sits ~244px below the
        # client top on both the 945- and the 812-high lobby, so a pure height
        # fraction misses it on the shorter client.  The lower bound stays
        # below the green header buttons (y<=200).
        y0 = max(int(frame.height * 0.23), 208)
        y1 = max(int(frame.height * 0.29), 262)
        hit = self.find_scene(frame, "lobby_room_list_tab")
        if hit is not None and x0 <= hit.x <= x1 and y0 <= hit.y <= y1:
            return hit
        # KK keeps the room-list label in this fixed navigation slot even when
        # the active tab is elsewhere.  Require visible label pixels first.
        slot = frame.bgr[y0:y1, x0:x1]
        if slot.size == 0:
            return None
        gray = cv2.cvtColor(slot, cv2.COLOR_BGR2GRAY)
        ys, xs = np.nonzero(gray >= 160)
        if xs.size < 80:
            return None
        # Click the label itself, wherever the strip landed in the slot.
        x, y = x0 + int(np.median(xs)), y0 + int(np.median(ys))
        return MatchResult(
            "lobby_room_list_tab_slot", 1.0, x, y, 1, 1,
            frame.left + x, frame.top + y,
        )

    @staticmethod
    def _hitch_room_number_key(frame: Frame, row_y: int) -> str | None:
        """Return a scale-stable visual key for one lobby row's room number."""
        if frame.bgr is None or frame.width <= 0 or frame.height <= 0:
            return None
        y0, y1 = max(0, row_y - 18), min(frame.height, row_y + 18)
        x0, x1 = int(frame.width * 0.17), int(frame.width * 0.29)
        crop = frame.bgr[y0:y1, x0:x1]
        if crop.size == 0:
            return None
        mask = (cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) >= 135).astype(np.uint8) * 255
        if int(np.count_nonzero(mask)) < 20:
            return None
        normalized = cv2.resize(mask, (72, 24), interpolation=cv2.INTER_NEAREST)
        return hashlib.sha256(normalized.tobytes()).hexdigest()

    def _find_hitch_joinable_row(self, frame: Frame) -> MatchResult | None:
        """Return the first visible ``n/4`` row that is safe to join."""
        w, h = frame.width, frame.height
        if w <= 0 or h <= 0 or frame.bgr is None or not self._lobby_room_list_evidence(frame):
            return None
        # A degraded list surface may remain classifiable for bounded search
        # recovery when the search box is occluded.  It must not grant room-row
        # click authority without the real search-area anchor.
        if self.find_scene(frame, "lobby_search_icon") is None:
            return None

        img_dir = self.images
        tpl_lock = _load_template(img_dir / "lobby" / "lobby_room_lock.png")
        tpl_4_4 = _load_template(img_dir / "lobby" / "lobby_4_4.png")
        tpl_ingame = _load_template(img_dir / "lobby" / "lobby_in_game.png")
        if tpl_4_4 is None or float(np.std(tpl_4_4)) < 8.0:
            print("[L0] hitch row-safety templates invalid; search is allowed, joining is blocked")
            return None

        def has_gray_lock(row_crop: np.ndarray) -> bool:
            """Detect the gray lock by its own shackle/body shape in the name cell."""
            name_left, name_right = int(w * 0.25), int(w * 0.55)
            name = row_crop[:, name_left:name_right]
            if name.size == 0:
                return False
            gray = cv2.cvtColor(name, cv2.COLOR_BGR2GRAY)
            spread = name.max(axis=2).astype(np.int16) - name.min(axis=2).astype(np.int16)
            neutral = ((gray > 80) & (spread < 28)).astype(np.uint8)
            labels_count, labels, stats, _ = cv2.connectedComponentsWithStats(neutral, 8)
            for label in range(1, labels_count):
                lx, ly, lw, lh, area = stats[label]
                if not (8 <= lw <= 12 and 11 <= lh <= 14 and 65 <= area <= 120):
                    continue
                component = labels[ly:ly + lh, lx:lx + lw] == label
                split = max(1, lh // 2)
                top_fill = float(np.mean(component[:split]))
                bottom_fill = float(np.mean(component[split:]))
                first_fill = float(np.mean(component[0]))
                # Live lock: sparse curved shackle over a nearly solid body.
                # Ordinary room-name glyphs in the same rows do not have a
                # solid lower half, and yellow badges are excluded as non-gray.
                if (
                    0.30 <= top_fill <= 0.75
                    and bottom_fill >= 0.90
                    and 0.20 <= first_fill <= 0.70
                ):
                    return True
            return False

        def text_metrics(crop: np.ndarray) -> tuple[int, int, int]:
            """Return bright glyph pixels, width and height for one table cell."""
            if crop.size == 0:
                return 0, 0, 0
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            threshold = max(80.0, float(np.median(gray)) + 45.0)
            ys, xs = np.where(gray > threshold)
            if xs.size == 0:
                return 0, 0, 0
            return (
                int(xs.size),
                int(xs.max() - xs.min() + 1),
                int(ys.max() - ys.min() + 1),
            )

        row_step = max(1, int(h * (48.0 / 945.0)))
        first_row_y = int(h * (385.0 / 945.0))
        count_left = int(w * 0.60)
        count_right = int(w * 0.82)
        count_text_left = int(w * 0.66)
        count_text_right = int(w * 0.75)
        for i in range(10):
            row_y = first_row_y + i * row_step
            if row_y + 20 >= h:
                break
            if row_y in self._hitch_rejected_row_ys:
                continue
            row_crop = frame.bgr[row_y - 20:row_y + 20, :]
            room_key = self._hitch_room_number_key(frame, row_y)
            if room_key is not None and room_key in self._hitch_blacklisted_room_keys:
                continue

            # Fast rejection order from live evidence: 游戏中 → 4/4 → 灰锁.
            status_crop = row_crop[:, count_right:]
            status_pixels, status_width, _ = text_metrics(status_crop)
            if status_pixels >= 80 or status_width >= 24:
                continue
            if tpl_ingame is not None and float(np.std(tpl_ingame)) >= 8.0:
                result = cv2.matchTemplate(status_crop, tpl_ingame, cv2.TM_CCOEFF_NORMED)
                if float(cv2.minMaxLoc(result)[1]) >= 0.85:
                    continue

            count_pixels, count_width, count_height = text_metrics(
                row_crop[:, count_text_left:count_text_right]
            )
            # A room is a candidate only when the occupancy cell positively
            # looks like one compact ``n/4`` token. Blank/unknown rows fail closed.
            if not (
                40 <= count_pixels <= 140
                and 16 <= count_width <= 24
                and 7 <= count_height <= 14
            ):
                continue

            result = cv2.matchTemplate(
                row_crop[:, count_left:count_right],
                tpl_4_4,
                cv2.TM_CCOEFF_NORMED,
            )
            if float(cv2.minMaxLoc(result)[1]) >= 0.90:
                continue

            if has_gray_lock(row_crop):
                continue
            if tpl_lock is not None and float(np.std(tpl_lock)) >= 8.0:
                lock_left = int(w * 0.25)
                lock_right = int(w * 0.55)
                result = cv2.matchTemplate(
                    row_crop[:, lock_left:lock_right],
                    tpl_lock,
                    cv2.TM_CCOEFF_NORMED,
                )
                if float(cv2.minMaxLoc(result)[1]) >= 0.85:
                    continue
            click_x = int(w * 0.35)
            click_y = row_y
            return MatchResult(
                name="room_list_row",
                score=1.0,
                x=click_x,
                y=click_y,
                w=int(w * 0.4),
                h=int(h * 0.04),
                screen_x=int(frame.left + click_x),
                screen_y=int(frame.top + click_y),
            )
        return None

    def _hitch_room_blue_controls(
        self,
        frame: Frame,
        *,
        require_text: bool = True,
    ) -> list[tuple[MatchResult, int]]:
        """Return blue controls in the room action bar.

        ``require_text`` is false only for ROOM page corroboration; click
        authorization continues to use the labelled-control path.
        """
        if frame.bgr is None or frame.width <= 0 or frame.height <= 0:
            return []
        w, h = frame.width, frame.height
        x0, x1 = int(w * 0.45), int(w * 0.95)
        y0, y1 = int(h * 0.55), int(h * 0.75)
        roi = frame.bgr[y0:y1, x0:x1]
        if roi.size == 0:
            return []
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        # The live KK blue has shifted BGR values across captures; HSV hue and
        # saturation remain stable for both Ready and CancelReady controls.
        mask = (
            (hsv[:, :, 0] >= 85)
            & (hsv[:, :, 0] <= 125)
            & (hsv[:, :, 1] >= 100)
            & (hsv[:, :, 2] >= 90)
        ).astype(np.uint8)
        _, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        controls: list[tuple[MatchResult, int]] = []
        for x, y, cw, ch, area in stats[1:]:
            if not (
                w * 0.045 <= cw <= w * 0.16
                and h * 0.025 <= ch <= h * 0.06
                and area >= cw * ch * 0.55
            ):
                continue
            crop = frame.bgr[y0 + y:y0 + y + ch, x0 + x:x0 + x + cw]
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            saturation = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[:, :, 1]
            margin_x = max(2, int(cw * 0.03))
            margin_y = max(2, int(ch * 0.08))
            gray = gray[margin_y:ch - margin_y, margin_x:cw - margin_x]
            saturation = saturation[margin_y:ch - margin_y, margin_x:cw - margin_x]
            ys, xs = np.where((gray > 150) & (saturation < 100))
            if xs.size < 60:
                if require_text:
                    continue
                text_width = 0
            else:
                text_width = int(xs.max() - xs.min() + 1)
                text_height = int(ys.max() - ys.min() + 1)
                if not (18 <= text_width <= 90 and 8 <= text_height <= 22):
                    if require_text:
                        continue
                    text_width = 0
            hit_x, hit_y = int(x0 + x), int(y0 + y)
            controls.append((
                MatchResult(
                    name="room_blue_action",
                    score=1.0,
                    x=hit_x,
                    y=hit_y,
                    w=int(cw),
                    h=int(ch),
                    screen_x=int(frame.left + hit_x + cw // 2),
                    screen_y=int(frame.top + hit_y + ch // 2),
                ),
                text_width,
            ))
        return sorted(controls, key=lambda item: item[0].x)

    def _hitch_room_action_control(self, frame: Frame) -> tuple[MatchResult, int] | None:
        """Return the room's blue primary control and its white-label width."""
        for hit, text_width in self._hitch_room_blue_controls(frame):
            if hit.x < frame.width * 0.78:
                return replace(hit, name="room_primary_action"), text_width
        return None

    def _hitch_room_cover(self, frame: Frame) -> tuple[int, int, int, int] | None:
        """Find the large square room artwork used by the real room surface."""
        if frame.bgr is None or frame.width <= 0 or frame.height <= 0:
            return None
        hsv = cv2.cvtColor(frame.bgr, cv2.COLOR_BGR2HSV)
        mask = ((hsv[:, :, 1] >= 90) & (hsv[:, :, 2] >= 70)).astype(np.uint8)
        _count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
        candidates: list[tuple[int, tuple[int, int, int, int]]] = []
        for x, y, width, height, area in stats[1:]:
            x, y, width, height, area = map(int, (x, y, width, height, area))
            if not (
                width >= max(80, int(frame.width * 0.08))
                and height >= max(80, int(frame.height * 0.12))
                and width <= int(frame.width * 0.30)
                and height <= int(frame.height * 0.40)
                and x <= int(frame.width * 0.45)
                and y <= int(frame.height * 0.52)
                and 0.65 <= width / max(height, 1) <= 1.45
                and area >= int(width * height * 0.45)
            ):
                continue
            candidates.append((area, (x, y, width, height)))
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]

    def _hitch_room_surface_evidence(
        self,
        frame: Frame,
    ) -> tuple[tuple[int, int, int, int], list[tuple[MatchResult, int]]] | None:
        """Return multi-signal ROOM evidence without low-information assets.

        The classic contract reads KK's default blue action bar.  Decorated
        (VIP-skinned) rooms paint those controls gold, so a skin-independent
        seat-table + label contract backs it up with no controls attached.
        """
        classic = self._hitch_room_surface_evidence_classic(frame)
        if classic is not None:
            return classic
        skinless = self._hitch_room_skinless_evidence(frame)
        if skinless is not None:
            return skinless["cover"], []
        return None

    # Action-bar slots, artwork-relative like the seat table: the primary
    # control (准备 / 取消准备 / 开始游戏 / 等待准备) and 退出.  Their white label
    # pixel count (V>=200, S<=60, at the 188px artwork scale) does not depend
    # on the room skin: measured on the default blue and the gold VIP theme,
    # two characters give 120-165, four characters 260-335, the greyed
    # 等待准备 zero.
    _ROOM_PRIMARY_SLOT = (690.0, 423.0, 140.0, 36.0)
    _ROOM_EXIT_SLOT = (934.0, 423.0, 88.0, 36.0)
    _ROOM_TWO_CHAR_LABEL = (80, 220)
    _ROOM_FOUR_CHAR_LABEL_MIN = 230

    def _hitch_room_slot(
        self, frame: Frame, cover: tuple[int, int, int, int], slot: tuple[float, float, float, float],
        name: str,
    ) -> tuple[float, MatchResult] | None:
        """White label pixels in one action-bar slot, plus its click target."""
        if frame.bgr is None:
            return None
        cx, cy, cw, _ch = cover
        k = cw / self._ROOM_ART_PX
        dx, dy, w, h = slot
        x0, y0 = cx + int(round(dx * k)), cy + int(round(dy * k))
        x1, y1 = x0 + int(round(w * k)), y0 + int(round(h * k))
        if x0 < 0 or y0 < 0 or x1 > frame.width or y1 > frame.height or x1 - x0 < 8 or y1 - y0 < 8:
            return None
        hsv = cv2.cvtColor(frame.bgr[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
        rh, rw = hsv.shape[:2]
        inner = hsv[int(rh * 0.2):int(rh * 0.8), int(rw * 0.1):int(rw * 0.9)]
        white = int(np.count_nonzero((inner[..., 2] >= 200) & (inner[..., 1] <= 60)))
        count = white / max(k * k, 1e-6)
        mx, my = (x0 + x1) // 2, (y0 + y1) // 2
        return count, MatchResult(name, 1.0, x0, y0, x1 - x0, y1 - y0, frame.left + mx, frame.top + my)

    def _hitch_room_skinless_evidence(self, frame: Frame) -> dict | None:
        """ROOM identity from the seat table and the 退出 label, any skin."""
        def compute() -> dict | None:
            cover = self._hitch_room_cover(frame)
            if cover is None:
                return None
            rows = self._hitch_room_rows(frame)
            if not rows or not any(row["status"] == "host" or row["combo"] for row in rows):
                return None
            exit_slot = self._hitch_room_slot(frame, cover, self._ROOM_EXIT_SLOT, "room_exit")
            lo, hi = self._ROOM_TWO_CHAR_LABEL
            if exit_slot is None or not lo <= exit_slot[0] <= hi:
                return None
            primary = self._hitch_room_slot(frame, cover, self._ROOM_PRIMARY_SLOT, "room_primary_action")
            return {
                "cover": cover,
                "exit": exit_slot[1],
                "primary": None if primary is None else primary[1],
                "primary_white": 0.0 if primary is None else primary[0],
            }

        return self._memo(("hitch_room_skinless",), frame, compute)

    def _hitch_room_surface_evidence_classic(
        self,
        frame: Frame,
    ) -> tuple[tuple[int, int, int, int], list[tuple[MatchResult, int]]] | None:
        """The default blue action-bar ROOM contract."""
        cover = self._hitch_room_cover(frame)
        if cover is None:
            return None
        controls = [
            item for item in self._hitch_room_blue_controls(frame)
            if item[0].x > cover[0] + cover[2] + int(frame.width * 0.12)
            and item[0].y >= cover[1] + cover[3] + int(frame.height * 0.12)
        ]
        geometry_controls = [
            item for item in self._hitch_room_blue_controls(frame, require_text=False)
            if item[0].x > cover[0] + cover[2] + int(frame.width * 0.12)
            and item[0].y >= cover[1] + cover[3] + int(frame.height * 0.12)
        ]
        primary = [item for item in controls if item[0].x < int(frame.width * 0.82)]
        has_authentic_start = self._find_room_start(frame) is not None
        if (not primary or len(geometry_controls) < 2) and not has_authentic_start:
            # A promoted guest is shown as a red host while KK changes the
            # primary action to green "等待准备".  It is still a real ROOM
            # surface, even though there is no blue primary or Start control.
            # A host on any row sees seat drop-downs, so a promotion is still
            # a ROOM when our row is not the first one.
            host_waiting = (
                self._hitch_host_marker_visible(frame) or self._hitch_self_is_host(frame)
            ) and self._find_hitch_exit_button(frame) is not None
            if not host_waiting:
                return None
        # Player/seat area: require independent colored content between the
        # cover and the action bar.  This rejects an isolated blue lobby button
        # even when a page happens to contain a saturated icon.
        x0 = min(frame.width - 1, cover[0] + cover[2] + int(frame.width * 0.02))
        x1 = max(x0 + 1, int(frame.width * 0.92))
        y0 = min(frame.height, cover[1] + int(cover[3] * 0.05))
        # Start-only / template-only rooms may have no geometric blue control;
        # the action bar then starts at the artwork-relative bar position.
        bar_y = min(
            (hit.y for hit, _text_width in geometry_controls),
            default=cover[1] + cover[3] * 2,
        )
        y1 = min(frame.height, bar_y - 8)
        seat_roi = frame.bgr[y0:y1, x0:x1]
        if seat_roi.size == 0:
            return None
        seat_hsv = cv2.cvtColor(seat_roi, cv2.COLOR_BGR2HSV)
        seat_pixels = int(np.count_nonzero(
            (seat_hsv[:, :, 1] >= 45) & (seat_hsv[:, :, 2] >= 75)
        ))
        if seat_pixels < max(180, int(frame.width * frame.height * 0.00015)):
            return None
        return cover, sorted(controls, key=lambda item: item[0].x)

    def _hitch_room_ready_contract(self, frame: Frame) -> tuple[str, MatchResult | None]:
        """Classify real ROOM action state: ready/cancel-ready/start/unknown."""
        surface = self._hitch_room_surface_evidence(frame)
        if surface is None:
            return "unknown", None
        _cover, controls = surface
        if not controls:
            # Skinned room: read the primary label length instead of colour.
            skinless = self._hitch_room_skinless_evidence(frame)
            if skinless is None or skinless["primary"] is None:
                return "unknown", None
            white = skinless["primary_white"]
            lo, hi = self._ROOM_TWO_CHAR_LABEL
            if lo <= white <= hi:
                return "ready", replace(skinless["primary"], name="room_ready")
            if white >= self._ROOM_FOUR_CHAR_LABEL_MIN:
                return ("start" if self._find_room_start(frame) is not None else "cancel_ready"), None
            return "unknown", None
        primary = next((item for item in controls if item[0].x < int(frame.width * 0.82)), None)
        if primary is None:
            return "unknown", None
        hit, text_width = primary
        if self._find_room_start(frame) is not None:
            return "start", None
        ratio = text_width / max(hit.w, 1)
        if ratio <= 0.27:
            return "ready", replace(hit, name="room_ready")
        if ratio >= 0.32:
            return "cancel_ready", None
        return "unknown", None

    def _find_hitch_ready_button(self, frame: Frame) -> MatchResult | None:
        # 只返回真实 ROOM 结构内的 Ready。取消准备和房主 Start 都是
        # 后置状态，绝不能把它们重新当作客人 Ready 点击。
        state, hit = self._hitch_room_ready_contract(frame)
        return hit if state == "ready" else None

    def _hitch_room_controls_visible(self, frame: Frame) -> bool:
        return self._hitch_room_surface_evidence(frame) is not None

    def _hitch_tangible_room_evidence(self, frame: Frame) -> bool:
        """明确的多证据 ROOM 页面证据；低信息暗块没有 authority。"""
        return self._hitch_room_surface_evidence(frame) is not None

    def _is_confirmed_room_frame(self, frame: Frame) -> bool:
        """ROOM identity is a page-level multi-signal contract."""
        return self._hitch_room_surface_evidence(frame) is not None

    def _hitch_exit_modal_visible(self, frame: Frame) -> bool:
        """Return True if frame visibly contains explicit exit-specific modal evidence.

        Generic dialog frames (lobby_popup_dialog, lobby_popup_title) indicate a popup,
        but only high-information exit-specific markers (exit_confirm_btn,
        exit_cancel_btn, exit_confirm) grant authority to click HitchConfirmLeave.
        The old ``lobby_popup_leave`` crop is a low-information dark block and is
        deliberately excluded from both room and exit authority.
        """
        if frame.bgr is None or frame.width <= 0 or frame.height <= 0:
            return False
        # Direct high-information exit-specific template recognition.
        if self.find(
            frame,
            ["lobby/exit_confirm_btn", "lobby/exit_cancel_btn"],
            threshold=0.75,
        ) is not None:
            return True
        if (
            self.find_scene(frame, "exit_confirm") is not None
            or self._find_hitch_exit_confirm_button(frame) is not None
        ):
            return True
        return False

    def _find_hitch_exit_confirm_button(self, frame: Frame) -> MatchResult | None:
        """Find the blue Confirm control in KK's modern exit-room dialog."""
        if frame.bgr is None or frame.width <= 0 or frame.height <= 0:
            return None
        w, h = frame.width, frame.height
        x0, x1 = int(w * 0.05), int(w * 0.62)
        y0, y1 = int(h * 0.25), int(h * 0.75)
        roi = frame.bgr[y0:y1, x0:x1]
        if roi.size == 0:
            return None
        blue, green, red = cv2.split(roi)
        mask = (
            (blue > 90) & (green > 40) & (green < 220)
            & (red < 50) & ((blue.astype(np.int16) - red.astype(np.int16)) > 75)
        ).astype(np.uint8)
        _, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        for x, y, bw, bh, area in stats[1:]:
            if not (
                w * 0.10 <= bw <= w * 0.40
                and h * 0.03 <= bh <= h * 0.12
                and area >= bw * bh * 0.55
            ):
                continue
            return MatchResult(
                name="hitch_exit_confirm",
                score=1.0,
                x=x0 + int(x),
                y=y0 + int(y),
                w=int(bw),
                h=int(bh),
                screen_x=int(frame.left + x0 + x + bw // 2),
                screen_y=int(frame.top + y0 + y + bh // 2),
            )
        return None

    def _find_verified_room_exit_confirm(self, frame: Frame) -> MatchResult | None:
        """Return KK's exit-room Confirm only after the existing modal proof."""
        return self._find_hitch_exit_confirm_button(frame) if self._hitch_exit_modal_visible(frame) else None

    def _find_hitch_exit_button(self, frame: Frame) -> MatchResult | None:
        for hit, text_width in reversed(self._hitch_room_blue_controls(frame)):
            if hit.x > frame.width * 0.80 and text_width <= 45:
                return replace(hit, name="room_exit")
        # The modern dark-blue Exit control is intentionally excluded from
        # the saturated-blue geometry scan above; use its dedicated semantic
        # template as the fallback, still scoped to the confirmed ROOM page.
        # Next the artwork-relative 退出 slot with a verified 2-char label: it
        # holds for skinned rooms and for client sizes where the blue scan
        # band clips the button (the template then matched the top bar).
        skinless = self._hitch_room_skinless_evidence(frame)
        if skinless is not None:
            return skinless["exit"]
        hit = self.find(frame, ["room_exit_btn"], threshold=0.75)
        if hit is not None and hit.x > frame.width * 0.80:
            return replace(hit, name="room_exit")
        return None

    # KK draws the seat table at a fixed pixel size next to the square room
    # artwork.  Offsets below are artwork-relative pixels at the 188px artwork
    # measured identically on 1224x904, 1032x720 and 1600x900 room captures:
    # row 1 centre 48px below the artwork top, 40px row pitch, avatar 35px and
    # status text 695-745px right of the artwork.
    _ROOM_ART_PX = 188.0
    _ROOM_ROW1_DY = 48.0
    _ROOM_ROW_PITCH = 40.0
    _ROOM_FLOOR_ONE_SIG_DIFF = 0.20

    def _hitch_room_rows(self, frame: Frame) -> list[dict] | None:
        """Classify the four seat rows of a real ROOM page.

        Each row reports ``status`` (``host`` red 房主 / ``ready`` green 已准备 /
        ``empty`` blue open-slot avatar / ``blank`` occupied without status),
        ``combo`` (the name cell is a drop-down, which KK draws only for the
        host) and ``name_sig`` (a normalised mask of the name text).
        """
        def compute() -> list[dict] | None:
            cover = self._hitch_room_cover(frame)
            if cover is None or frame.bgr is None:
                return None
            cx, cy, cw, ch = cover
            kx, ky = cw / self._ROOM_ART_PX, ch / self._ROOM_ART_PX
            right = cx + cw

            def px(value: float, k: float) -> int:
                return int(round(value * k))

            rows: list[dict] = []
            for index in range(4):
                yc = cy + px(self._ROOM_ROW1_DY + self._ROOM_ROW_PITCH * index, ky)
                half = max(6, px(9, ky))
                band = max(8, px(16, ky))
                if yc + band >= frame.height or right + px(760, kx) >= frame.width:
                    return None
                ax, ar = right + px(35, kx), max(6, px(10, kx))
                avatar = frame.bgr[yc - ar:yc + ar, ax - ar:ax + ar].astype(np.int16)
                ab, ag, a_r = avatar[..., 0], avatar[..., 1], avatar[..., 2]
                empty = float(np.mean((ab >= 170) & (ag >= 70) & (ag <= 170) & (a_r <= 70)))
                status_roi = frame.bgr[yc - half:yc + half, right + px(695, kx):right + px(745, kx)]
                sb, sg, sr = (status_roi[..., i].astype(np.int16) for i in range(3))
                green = int(np.count_nonzero((sg >= 140) & (sg - sr >= 40) & (sg - sb >= 40)))
                hsv = cv2.cvtColor(status_roi, cv2.COLOR_BGR2HSV)
                red = int(np.count_nonzero(
                    ((hsv[..., 0] <= 12) | (hsv[..., 0] >= 170))
                    & (hsv[..., 1] >= 100) & (hsv[..., 2] >= 80)
                ))
                # Host drop-downs: a 1px border line brighter than the pixels
                # directly above and below, spanning most of the name column.
                gray = cv2.cvtColor(
                    frame.bgr[yc - band:yc + band, right + px(50, kx):right + px(270, kx)],
                    cv2.COLOR_BGR2GRAY,
                ).astype(np.int16)
                line = (gray[1:-1] - gray[:-2] >= 10) & (gray[1:-1] - gray[2:] >= 10)
                longest = 0
                for mask_row in line:
                    padded = np.concatenate(([0], mask_row.astype(np.int8), [0]))
                    edges = np.flatnonzero(np.diff(padded))
                    if edges.size:
                        longest = max(longest, int(np.max(edges[1::2] - edges[::2])))
                name = frame.bgr[yc - half:yc + half, right + px(62, kx):right + px(185, kx)]
                name_mask = (name.max(axis=2) >= 150).astype(np.float32)
                name_sig = (
                    cv2.resize(name_mask, (48, 12), interpolation=cv2.INTER_AREA)
                    if name_mask.sum() >= 20 else None
                )
                if red >= 35:
                    status = "host"
                elif green >= 25:
                    status = "ready"
                elif empty >= 0.25:
                    status = "empty"
                else:
                    status = "blank"
                rows.append({
                    "row": index + 1,
                    "status": status,
                    "combo": longest >= int(cw * 0.80),
                    "name_sig": name_sig,
                })
            return rows

        return self._memo(("hitch_room_rows",), frame, compute)

    def _hitch_room_like(self, frame: Frame) -> bool:
        """Any seat-table evidence, even when the full ROOM contract fails."""
        if self._is_confirmed_room_frame(frame):
            return True
        rows = self._hitch_room_rows(frame)
        return bool(rows) and any(
            row["combo"] or row["status"] in ("host", "ready", "empty") for row in rows
        )

    def _hitch_self_is_host(self, frame: Frame) -> bool:
        """KK shows seat drop-downs only to the room's host: that host is us."""
        rows = self._hitch_room_rows(frame)
        return bool(rows) and any(row["combo"] for row in rows)

    def _hitch_track_room_seats(self, frame: Frame) -> None:
        """Learn our own row and the floor-one occupant from fresh room frames."""
        generation = int(getattr(self, "_capture_generation", 0) or 0)
        if generation == getattr(self, "_hitch_seat_generation", None):
            return
        self._hitch_seat_generation = generation
        rows = self._hitch_room_rows(frame)
        if not rows or any(row["combo"] for row in rows):
            return
        statuses = [row["status"] for row in rows]
        pre_ready = getattr(self, "_hitch_pre_ready_rows", None)
        if getattr(self, "_hitch_self_row", None) is None and pre_ready is not None:
            # Our own Ready turns exactly our row from blank to 已准备.
            turned = [
                index for index, (before, after) in enumerate(zip(pre_ready, statuses))
                if before == "blank" and after == "ready"
            ]
            if len(turned) == 1:
                self._hitch_self_row = turned[0] + 1
                print(f"[L0] hitch 本方座位由准备前后差分确定: 第 {self._hitch_self_row} 行")
        if getattr(self, "_hitch_floor_one_baseline", None) is None:
            first = rows[0]
            if first["status"] != "empty" and first["name_sig"] is not None:
                candidate = getattr(self, "_hitch_floor_one_candidate", None)
                if (
                    candidate is not None
                    and float(np.mean(np.abs(first["name_sig"] - candidate)))
                    <= self._ROOM_FLOOR_ONE_SIG_DIFF
                ):
                    self._hitch_floor_one_baseline = candidate
                else:
                    self._hitch_floor_one_candidate = first["name_sig"]

    def _hitch_note_pre_ready_rows(self, frame: Frame) -> None:
        """Remember seat statuses on the frame our Ready click was sent from."""
        rows = self._hitch_room_rows(frame)
        if not rows:
            return
        statuses = [row["status"] for row in rows]
        self._hitch_pre_ready_rows = statuses
        if getattr(self, "_hitch_self_row", None) is None and statuses.count("blank") == 1:
            # Every other occupied seat is host or already ready: the one
            # seat without a status is ours.
            self._hitch_self_row = statuses.index("blank") + 1
            print(f"[L0] hitch 本方座位由唯一未准备行确定: 第 {self._hitch_self_row} 行")

    def _hitch_room_seat_decision(self, frame: Frame) -> str:
        """Apply the hitch seat rules to a real ROOM page.

        User rules (2026-09-11), ready or not: leave when we are the host,
        when we sit on floor one (row 1), or when the floor-one player leaves.
        Rules only apply after our own Ready transaction (or once KK offers us
        no Ready at all); a fresh room is observed first, never rejected.
        UNKNOWN is wait/reobserve only and never authorizes exit.
        """
        if self._hitch_room_surface_evidence(frame) is None:
            return "unknown"
        if getattr(self, "_hitch_ready_confirmed_at", None) is None:
            return "unknown"
        rows = self._hitch_room_rows(frame)
        if not rows:
            return "unknown"
        if any(row["combo"] for row in rows):
            return "reject_host_takeover"
        if getattr(self, "_hitch_self_row", None) == 1:
            return "reject_self_floor_one"
        baseline = getattr(self, "_hitch_floor_one_baseline", None)
        if baseline is not None:
            first = rows[0]
            if first["status"] == "empty":
                return "reject_floor_one_left"
            if (
                first["name_sig"] is not None
                and float(np.mean(np.abs(first["name_sig"] - baseline)))
                > self._ROOM_FLOOR_ONE_SIG_DIFF
            ):
                return "reject_floor_one_left"
        return "unknown"

    def _hitch_host_marker_visible(self, frame: Frame) -> bool:
        """Detect the red ``房主`` label in the first player row.

        This is deliberately scoped to the room cover's first-row status
        column, rather than a global red-pixel heuristic.  The marker is a
        stable high-information cue on the KK room page and survives the
        client scaling used by the live harness.
        """
        if frame.bgr is None or frame.width <= 0 or frame.height <= 0:
            return False
        cover = self._hitch_room_cover(frame)
        if cover is None:
            return False
        x0 = max(0, int(frame.width * 0.80))
        x1 = min(frame.width, int(frame.width * 0.98))
        y0 = max(0, cover[1] - int(cover[3] * 0.02))
        y1 = min(frame.height, cover[1] + int(cover[3] * 0.38))
        roi = frame.bgr[y0:y1, x0:x1]
        if roi.size == 0:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        red = (
            (((hsv[:, :, 0] <= 12) | (hsv[:, :, 0] >= 170))
             & (hsv[:, :, 1] >= 100)
             & (hsv[:, :, 2] >= 80))
        )
        return int(np.count_nonzero(red)) >= 35

    def _hitch_ocr_text(self, frame: Frame | None = None) -> str:
        override = getattr(self, "_hitch_ocr_override", None)
        if override is not None:
            return str(override)
        target_frame = frame if frame is not None else getattr(self, "_last_frame", None)
        if target_frame is not None:
            if self._find_hitch_joinable_row(target_frame) is not None:
                return "3/4"
            if self.find_scene(target_frame, "lobby_3_4") is not None:
                return "3/4"
        return ""

    def _hitch_prefix_ok(self, frame: Frame | None = None) -> bool:
        """Rows are eligible only while a confirmed search transaction stands."""
        tx = self._hitch_search
        return tx is not None and tx.confirmed

    # The search control is an absolute-size KK asset: measured identically
    # (179x25 box, 26x22 magnifier, 152px of text area left of the icon) on
    # both a 1332x945 and a 1600x900 client.  Offsets below are template-space
    # pixels, scaled by the matched icon width so a scaled client still maps.
    _SEARCH_ICON_W = 26
    _SEARCH_BOX_TEXT_W = 152
    _SEARCH_BOX_PAD_Y = 2
    _SEARCH_GLYPH_W = 16
    # Visual confirmation budget, measured from the moment the input action
    # completes.  The shipped 3.0s ran from tick start, so the 1.3s that
    # search_text() spent on the real client came out of it and left room for
    # a single OCR sample before the timeout fired.
    _HITCH_SEARCH_CONFIRM_S = 3.0

    # P1-1：进房/未知弹窗的有界 Esc 关闭预算。输入层成功不等于弹窗关闭，
    # 所以关闭尝试计数、冷却，并在 fresh 帧证明弹窗消失后重置；
    # 耗尽后零输入观察，绝不无限循环发 Esc。
    _HITCH_POPUP_ESC_LIMIT = 4
    _HITCH_POPUP_ESC_COOLDOWN_S = 2.0
    _HITCH_FLOOR_EXIT_BUDGET_S = 8.0

    def _hitch_popup_esc_budget(self, now: float) -> str:
        """Classify the bounded popup-Esc budget: allow / cooldown / exhausted."""
        if self._hitch_popup_esc_attempts >= self._HITCH_POPUP_ESC_LIMIT:
            return "exhausted"
        last = self._hitch_popup_esc_last_at
        if last is not None and now - float(last) < self._HITCH_POPUP_ESC_COOLDOWN_S:
            return "cooldown"
        return "allow"

    def _hitch_modal_observation_key(self, frame: Frame) -> tuple[int, float]:
        """Identify a fresh application observation, not a Python object."""
        generation = int(getattr(self, "_capture_generation", 0) or 0)
        timestamp = float(getattr(frame, "timestamp", 0.0) or 0.0)
        return generation, round(timestamp, 6)

    def _kk_platform_modal_shell(self, frame: Frame) -> PlatformModalShell | None:
        """Recognize the shared KK prompt shell from its cyan rim, dark panel and X.

        This deliberately does not read the body or inspect the blue primary button:
        the same shell is used by kicked, level and membership notices.  A plain KK
        window has no authority; all three shell features are required.
        """
        title = (frame.window_title or "").lower()
        if (
            frame.role != "l0"
            or not any(token in title for token in ("kk", "对战平台", "platform"))
            or self._is_game_client_frame(frame)
            or frame.bgr is None
            or frame.width <= 0
            or frame.height <= 0
        ):
            return None

        def compute() -> PlatformModalShell | None:
            hsv = cv2.cvtColor(frame.bgr, cv2.COLOR_BGR2HSV)
            cyan = cv2.inRange(hsv, np.array([85, 120, 120]), np.array([110, 255, 255]))
            _count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(cyan)
            min_rim_width = max(80, int(frame.width * 0.12))
            max_rim_width = frame.width
            max_rim_height = max(5, int(frame.height * 0.01))
            for x, y, width, height, _area in stats[1:]:
                x, y, width, height = map(int, (x, y, width, height))
                if not (min_rim_width <= width <= max_rim_width and 1 <= height <= max_rim_height):
                    continue
                close_height = max(24, int(width * 0.11))
                if x + width > frame.width or y + close_height > frame.height:
                    continue
                panel = frame.bgr[y + max(8, int(width * 0.03)):min(frame.height, y + max(60, int(width * 0.23))), x + 8:x + width - 8]
                if panel.size == 0 or float(np.mean(cv2.cvtColor(panel, cv2.COLOR_BGR2GRAY) < 80)) < 0.65:
                    continue
                close_roi = frame.bgr[y + max(6, int(width * 0.02)):y + close_height, x + int(width * 0.87):x + int(width * 0.99)]
                close_gray = cv2.cvtColor(close_roi, cv2.COLOR_BGR2GRAY)
                neutral = (
                    (np.max(close_roi, axis=2) - np.min(close_roi, axis=2) < 35)
                    & (close_gray > 100)
                )
                ys, xs = np.where(neutral)
                if len(xs) < 30 or np.ptp(xs) < 6 or np.ptp(ys) < 6:
                    continue
                close_x = x + int(width * 0.87) + int(round(float(np.mean(xs))))
                close_y = y + max(6, int(width * 0.02)) + int(round(float(np.mean(ys))))
                close = MatchResult(
                    "kk_platform_modal_close", 1.0,
                    close_x - 5, close_y - 5, 10, 10,
                    frame.left + close_x, frame.top + close_y,
                )
                compact = x <= max(2, int(frame.width * 0.01)) and y <= max(2, int(frame.height * 0.01)) and width >= int(frame.width * 0.90)
                return PlatformModalShell("compact_child" if compact else "main_overlay", close)
            return None

        return self._memo(("kk_platform_modal_shell",), frame, compute)

    def _tick_hitch_platform_modal(
        self,
        frame: Frame,
        shell: PlatformModalShell | None,
        now: float,
    ) -> LoopAction | None:
        """Close one owned platform prompt and reconcile only after its fresh absence."""
        previous_observation = self._hitch_platform_modal_input_observation
        current_observation = self._hitch_modal_observation_key(frame)
        if previous_observation is not None and current_observation != previous_observation and shell is None:
            self._hitch_platform_modal_input_frame = None
            self._hitch_platform_modal_input_observation = None
            self._hitch_platform_modal_last_action = None
            self._hitch_popup_esc_attempts = 0
            self._hitch_popup_esc_last_at = None
            self._hitch_platform_modal_reobserve_until = None
            self._hitch_platform_modal_reacquire_attempts = 0
            if self._hitch_sm.pending_join:
                self._hitch_reject_pending_join(now, "join_rejected")
                self._hitch_search_actions.append("reject")
            print("[L0] hitch KK 平台提示已在 fresh 帧消失，恢复大厅找房")
            return self._hitch_reset_lobby("platform_modal_dismissed", now)
        if shell is None:
            return None
        if previous_observation is not None and current_observation == previous_observation:
            print("[L0] hitch 平台提示等待 fresh 帧复核（零输入）")
            return LoopAction.Continue

        reobserve_until = self._hitch_platform_modal_reobserve_until
        if reobserve_until is not None:
            if now < reobserve_until:
                print("[L0] hitch 平台提示执行有界 reacquire/reclassify（零输入）")
                return LoopAction.Continue
            self._hitch_platform_modal_reobserve_until = None
            self._hitch_platform_modal_input_frame = None
            self._hitch_platform_modal_input_observation = None
            self._hitch_platform_modal_last_action = None
            if not self.settings.dry_run and self._hitch_platform_modal_reacquire_attempts < 2:
                self._hitch_platform_modal_reacquire_attempts += 1
                try:
                    self._reacquire_target_window(getattr(frame, "hwnd", None), timeout_s=0.5)
                except Exception as exc:
                    print(f"[L0] hitch 平台提示 reacquire 失败: {type(exc).__name__}")

        budget = self._hitch_popup_esc_budget(now)
        if budget == "exhausted":
            self._hitch_status = "platform_modal_still_visible"
            self._record_lobby_observation_incident(
                "platform_modal_dismissal_budget_exhausted",
                "Esc/X 有界尝试耗尽，转入 fresh capture/reclassify",
                frame,
                attempt=self._hitch_popup_esc_attempts,
                extra={"capture_generation": getattr(self, "_capture_generation", 0)},
            )
            # This is a recovery boundary, not proof that the modal is gone.
            # Space retries so a stuck prompt cannot receive an unbounded key
            # storm, while keeping the long-running worker alive.
            retry_round = min(3, int(getattr(self, "_hitch_platform_modal_reacquire_attempts", 0)) + 1)
            self._hitch_platform_modal_reobserve_until = now + 2.0 + retry_round
            self._hitch_platform_modal_input_frame = None
            self._hitch_platform_modal_input_observation = None
            self._hitch_platform_modal_last_action = None
            self._hitch_popup_esc_last_at = now
            print("[L0] hitch 平台提示中性关闭预算耗尽，已记录 incident 并转入有界重采集（继续运行）")
            return LoopAction.Continue
        if budget == "cooldown":
            print("[L0] hitch 平台提示关闭冷却中，零输入等待 fresh 帧")
            return LoopAction.Continue

        self._hitch_popup_esc_attempts += 1
        self._hitch_popup_esc_last_at = now
        if self._hitch_platform_modal_last_action == "esc":
            accepted = self.act_click(shell.close, "HitchDismissPlatformModalClose")
            self._hitch_platform_modal_last_action = "close"
        else:
            accepted = self.act_key("esc", "HitchDismissPlatformModalEsc")
            self._hitch_platform_modal_last_action = "esc"
        if accepted:
            self._hitch_platform_modal_input_frame = frame
            self._hitch_platform_modal_input_observation = current_observation
        else:
            print("[L0] hitch 平台提示中性关闭输入被拒绝，等待受控重试")
        return LoopAction.Continue

    def _find_hitch_search_box(self, frame: Frame) -> MatchResult | None:
        """Locate the search control by its magnifier, never by its content.

        The shipped ``lobby_search_box`` asset spans the whole input, so the
        placeholder text is part of the pattern: typing the prefix — the very
        action we are trying to confirm — drops it from 0.96 to 0.62-0.74,
        under the production ``match_threshold``.  The magnifier is the one
        part of the control that does not change with EMPTY/typed/focused
        state, and it holds 0.987-1.000 across every measured frame.
        """
        icon = self.find_scene(frame, "lobby_search_icon")
        if icon is None:
            return None
        scale = max(int(icon.w), 1) / self._SEARCH_ICON_W
        # Click the middle of the text area: inside the edit box, clear of the
        # magnifier (which is KK's submit affordance, not a focus target).
        x = icon.x - int(round(self._SEARCH_BOX_TEXT_W / 2 * scale))
        y = icon.y + icon.h // 2
        return replace(
            icon,
            name="lobby_search_box_input",
            x=x,
            y=y,
            screen_x=(getattr(frame, "left", 0) or 0) + x,
            screen_y=(getattr(frame, "top", 0) or 0) + y,
        )

    def _hitch_search_content_bbox(
        self, frame: Frame, icon: MatchResult, prefix: str
    ) -> tuple[int, int, int, int] | None:
        """Crop only the typed-text corner of the box, derived from the icon.

        The shipped ROI was a fixed normalized band that mostly framed the
        empty area and the divider rule above the control, clipped the glyph
        bottoms, and swallowed both the magnifier and the I-beam pointer that
        ``search_text()`` leaves inside the box.  On the incident frames the
        production OCR read that crop as ``"a"``.  Anchoring on the icon and
        keeping only enough width for the prefix plus one unexpected glyph
        reads ``"4"`` instead, and still shows the placeholder (never a digit)
        while the box is empty.
        """
        scale = max(int(icon.w), 1) / self._SEARCH_ICON_W

        def px(value: float) -> int:
            """Template-space pixels -> this frame's pixels."""
            return int(round(value * scale))

        width = min(
            max(self._SEARCH_GLYPH_W * (len(prefix) + 2), self._SEARCH_GLYPH_W * 3),
            self._SEARCH_BOX_TEXT_W,
        )
        x0 = icon.x - px(self._SEARCH_BOX_TEXT_W)
        x1 = x0 + px(width)
        y0 = icon.y - px(self._SEARCH_BOX_PAD_Y)
        y1 = icon.y + icon.h + px(self._SEARCH_BOX_PAD_Y)
        x0, x1 = max(0, x0), min(frame.width, x1)
        y0, y1 = max(0, y0), min(frame.height, y1)
        if x1 - x0 < 8 or y1 - y0 < 8:
            return None
        return (x0, y0, x1, y1)

    def _hitch_search_prefix_confirmed(self, frame: Frame, prefix: str, now: float) -> bool:
        """Verify the lobby search box before using its filtered room rows."""
        override = getattr(self, "_hitch_search_text_override", None)
        if override is not None:
            return has_prefix_evidence(str(override), prefix)
        if now < self._hitch_search_ocr_next_at:
            return False
        self._hitch_search_ocr_next_at = now + 0.5
        client = getattr(self, "_ocr_client", None)
        if client is None:
            return False
        icon = self.find_scene(frame, "lobby_search_icon")
        if icon is None:
            return False
        bbox = self._hitch_search_content_bbox(frame, icon, prefix)
        if bbox is None:
            return False
        try:
            response = client.shadow_predict(
                frame,
                "lobby_search_box",
                {"slot_id": 0, "bbox": bbox, "kind": "text"},
                session="lobby_hitch",
                panel_bbox=bbox,
            )
        except (AttributeError, OSError, TypeError, ValueError) as exc:
            if now >= self._hitch_search_ocr_error_logged_at:
                print(f"[L0] hitch 搜索框 OCR 不可用: {type(exc).__name__}")
                self._hitch_search_ocr_error_logged_at = now + 10.0
            return False
        if response.status != "ok":
            return False
        return has_prefix_evidence(str(response.raw_text or ""), prefix)

    def _hitch_room_matched(self, frame: Frame | None = None) -> bool:
        override = getattr(self, "_hitch_match_override", None)
        if override is not None:
            return bool(override)
        if frame is not None:
            return self._find_hitch_joinable_row(frame) is not None
        return False

    def _hitch_action_hit(self, frame: Frame, action: HitchAction):
        override = getattr(self, "_hitch_hit_override", None)
        if override is not None:
            return override
        if action == HitchAction.JOIN:
            # lobby_hitch never uses Quick Join; only a verified room row is safe.
            return self._find_hitch_joinable_row(frame)
        if action == HitchAction.REFRESH:
            if not self._lobby_room_list_evidence(frame):
                return None
            detected = self.find_scene(frame, "lobby_refresh")
            if detected is not None:
                return replace(
                    detected,
                    screen_y=detected.screen_y - detected.h // 2,
                )
            w, h = frame.width, frame.height
            left = getattr(frame, "left", 0) or 0
            top = getattr(frame, "top", 0) or 0
            rx = int(w * (1055.0 / 1332.0))
            ry = int(h * (292.0 / 945.0))
            return MatchResult(
                name="lobby_refresh",
                score=1.0,
                x=rx,
                y=ry,
                w=40,
                h=30,
                screen_x=left + rx,
                screen_y=top + ry,
            )
        if action == HitchAction.GO_HOME:
            for key in ("lobby_home", "lobby_back"):
                hit = self.find_scene(frame, key)
                if hit is not None:
                    return hit
        return None
    def _hitch_lobby_home_visible(self, frame: Frame) -> bool:
        override = getattr(self, "_hitch_lobby_home_override", None)
        if override is not None:
            return bool(override)
        for key in ("lobby_list", "lobby_room_list", "lobby_home"):
            if self.find_scene(frame, key) is not None:
                return True
        return False

    def _hitch_reject_pending_join(self, now: float, reason: str) -> None:
        if self._hitch_pending_row_y is not None:
            self._hitch_rejected_row_ys.add(self._hitch_pending_row_y)
        self._hitch_pending_row_y = None
        # P1-1：origin hwnd 保留到 fresh 帧证明回到主窗口再清；关闭预算
        # 不在此重置——Esc 后弹窗可能仍在，预算沿用本 episode。
        self._hitch_sm.reject_join(now)
        self._hitch_refresh_required = True
        self._hitch_status = reason

    def _hitch_begin_room_exit(
        self, exit_hit: MatchResult, now: float, reason: str, status: str,
    ) -> bool:
        """Click the room's Exit control and open (or continue) the exit
        transaction.  Ready and not-ready guests share this one chain:
        Exit -> KK's separate confirm HWND -> Confirm -> fresh lobby.
        """
        if not self.act_click(exit_hit, reason):
            return False
        if self._hitch_pending_row_y is not None:
            self._hitch_rejected_row_ys.add(self._hitch_pending_row_y)
        self._hitch_pending_row_y = None
        self._hitch_floor_exit_pending = True
        self._hitch_floor_exit_confirmed = False
        self._hitch_floor_exit_attempted_at = now
        if getattr(self, "_hitch_floor_exit_started_at", None) is None:
            self._hitch_floor_exit_started_at = now
        self._hitch_floor_exit_clicks = int(getattr(self, "_hitch_floor_exit_clicks", 0) or 0) + 1
        self._hitch_floor_exit_deadline = now + self._HITCH_FLOOR_EXIT_BUDGET_S
        self._hitch_floor_exit_input_generation = int(getattr(self, "_capture_generation", 0) or 0)
        self._hitch_floor_exit_reobserve_until = None
        self._hitch_status = status
        return True

    def _hitch_room_exit_blocked(self, frame: Frame, now: float, detail: str) -> LoopAction:
        """End an exit transaction that cannot complete, with evidence."""
        self._record_lobby_observation_incident(
            "hitch_room_exit_blocked",
            detail,
            frame,
            extra={
                "exit_clicks": getattr(self, "_hitch_floor_exit_clicks", 0),
                "confirm_clicks": getattr(self, "_hitch_floor_exit_confirm_clicks", 0),
                "hwnd": frame.hwnd,
                "confirmed_room_hwnd": getattr(self, "_confirmed_room_hwnd", None),
            },
        )
        print(f"[L0] hitch 退房事务无法完成（{detail}），BLOCKED 停止")
        self.set_phase(Phase.ERROR, "hitch room exit blocked")
        self.stop()
        return LoopAction.Break

    # ---------- hitch liveness supervisor ----------

    def _hitch_observe_world(self) -> str:
        """What the screen really is, independent of the current phase."""
        try:
            game = self._probe_l1_game_frame()
        except Exception:
            game = None
        if game is not None and game.bgr is not None and game.bgr.size:
            if self.find_scene(game, "fail") or self.find_scene(game, "disconnect"):
                return "game_failure"
            if self._post_game_state(game) is not None:
                return "game_postgame"
            if self._host_choosing_difficulty(game):
                return "game_waiting"
            if self._is_in_game_hud(game):
                return "game_round"
            if self._find_stage_page(game):
                return "game_stage"
            return "game_unknown"
        try:
            kk = self._capture_best(",".join(L0_WINDOW_KEYWORDS), "l0")
        except Exception:
            kk = None
        if kk is None or kk.bgr is None or not kk.bgr.size:
            return "none"
        if self._is_confirmed_room_frame(kk):
            return "kk_room"
        if self._lobby_room_list_evidence(kk):
            return "kk_lobby"
        return "kk_other"

    def _hitch_soft_reset(self, now: float) -> None:
        """Drop the stalled phase's transient state so its flow starts over."""
        self.invalidate_evidence("hitch-liveness")
        if self.phase == Phase.LOBBY_ROOM:
            self._hitch_sm = self._new_hitch_sm()
            self._hitch_search = None
            self._hitch_refresh_required = True
            self._hitch_nav_reset()
        elif self.phase == Phase.MAIN_LINE:
            self._panel_state = PanelState.CLOSED
            self._panel_opened_by_us = None
            self._pending_action = None
            self._pending_action_unconfirmed_count = 0
            fsm = self._public_bag_fsm
            self._public_bag_fsm = PublicBagFSM(deposits=fsm.deposits, aborts=fsm.aborts)
            self._public_bag_open_since = None
            self._l1_cycle_step = "merchant" if self._passenger_mode() else "bond"
            self._auto_task_recheck_at = now
            self._pause_resume_attempts = 0
            self._pause_resume_next_at = 0.0
        elif self.phase in (Phase.QUIT, Phase.NEXT):
            self._exit_button_attempts = 0
            self._exit_confirm_attempts = 0
            self._exit_since = now
        elif self.phase == Phase.ROOM_WAITING:
            self._hitch_seat_streak = None
            self._hitch_host_difficulty_since = None

    def _liveness_reset(self, now: float) -> None:
        self._liveness_last_progress_at = now
        self._liveness_level = 0
        self._liveness_level_at = None

    def _hitch_declared_wait_until(self) -> float:
        """End of a designed, self-bounded zero-input wait; its budget starts
        only after it.  Undeclared waits get no extension."""
        if self.phase == Phase.LOBBY_ROOM and self._hitch_sm.phase == HitchPhase.SLEEP_RETRY:
            return float(self._hitch_sm.sleep_until or 0.0)
        return 0.0

    def _hitch_liveness_supervise(self) -> None:
        """One liveness contract for every hitch phase.

        Local handlers may wait with zero input; this ladder bounds how long.
        When a phase goes a whole budget without a successful input:
          1. reconcile - observe the real screen and hand it to its owner phase,
             or soft-reset the stalled phase's transient state;
          2. leave - quit a running game / leave the KK room / restart search;
          3. BLOCKED - ERROR + stop with an incident, never silent forever.
        Any successful input (blind stall-watchdog keys excluded) resets it.
        A running round's legitimate idle only ever gets the soft reset; the
        round hard deadline bounds it.
        """
        if self.settings.dry_run or self.stop_signal.is_set():
            return
        hitch = self._hitch_enabled()
        if not hitch and not (
            self._unattended_recovery_enabled()
            and self.phase in self._UNATTENDED_SUPERVISED_PHASES
        ):
            # Solo/follow: only the in-game phases share this ladder; their
            # lobby/room flows keep their own bounded transactions.
            return
        if self.phase in (Phase.ERROR, Phase.COMPLETE):
            return
        now = time.time()
        if self.phase == Phase.MAIN_LINE and self._round_deadline is None:
            # An attached (non-natural) round skipped the new-round init; it
            # still owns a hard deadline.
            self._round_started_at = now
            self._round_deadline = now + self.settings.round_timeout_s
        progressed = self._tick_input_executed and (
            self.last_business_action not in self._LIVENESS_BLIND_REASONS
        )
        if self._hitch_dwell_cap_hit(now):
            return
        if progressed or getattr(self, "_liveness_last_progress_at", None) is None:
            self._liveness_reset(now)
            return
        since = max(
            self._liveness_last_progress_at,
            self._liveness_level_at or 0.0,
            self._hitch_declared_wait_until(),
        )
        budget = self._HITCH_STALL_BUDGET_S.get(self.phase, self._HITCH_STALL_DEFAULT_S)
        if now - since < budget:
            return
        stalled = now - self._liveness_last_progress_at
        world = self._hitch_observe_world()
        target = self._HITCH_WORLD_PHASE.get(world)
        if self.phase in (Phase.QUIT, Phase.NEXT) and world.startswith("game"):
            # The exit chain owns any game page; a swallowed menu goes back to
            # the exit button instead of back into the round.
            target = Phase.QUIT
        if not hitch and target not in (Phase.QUIT, Phase.MAIN_LINE):
            # The KK room/lobby targets belong to the hitch search flow.
            target = None
        if self.phase == Phase.MAIN_LINE and world == "game_round":
            print(f"[med] 无进展监督：局内 {stalled:.0f}s 无输入，软复位局内瞬态（不退局）")
            self._liveness_level_at = now
            self._hitch_soft_reset(now)
            return
        self._liveness_level = int(getattr(self, "_liveness_level", 0) or 0) + 1
        self._liveness_level_at = now
        level = self._liveness_level
        print(
            f"[med] 无进展监督：{self.phase.name} 已 {stalled:.0f}s 无有效输入，"
            f"实际画面={world}，升级第 {level} 级"
        )
        self._record_environment_incident(f"hitch_liveness_stall_l{level}", stalled)
        if level == 1:
            if target is not None and target != self.phase:
                self._hitch_reconcile_to(target, world, now)
            else:
                self._hitch_soft_reset(now)
            return
        if level == 2 and (hitch or world.startswith("game")):
            # Non-hitch modes can only leave a running game; a vanished game
            # window has no solo lobby path here and goes to BLOCKED.
            self._hitch_liveness_leave(world, now)
            return
        print(f"[med] 无进展监督：校正/撤离后仍无有效输入（{world}），BLOCKED 停止")
        self.set_phase(Phase.ERROR, f"hitch liveness blocked ({world})")
        self.stop()

    def _hitch_dwell_cap_hit(self, now: float) -> bool:
        """Livelock guard: inputs that never get a phase family anywhere.

        The no-input ladder cannot see a loop that keeps clicking (exit button
        -> no confirmation -> exit button ...).  The exit chain, failure
        recovery and the room each get a total dwell cap; the running round is
        bounded by its own hard deadline and the lobby search may run forever.
        """
        family = self._HITCH_PHASE_FAMILY.get(self.phase)
        if family != getattr(self, "_liveness_family", None):
            self._liveness_family = family
            self._liveness_family_since = now
            self._hitch_dwell_room_left = False
            return False
        cap = self._HITCH_DWELL_CAP_S.get(family) if family else None
        since = getattr(self, "_liveness_family_since", None)
        if cap is None or since is None or now - since < cap:
            return False
        dwell = now - since
        self._liveness_family_since = now
        world = self._hitch_observe_world()
        print(f"[med] 蹭车停留上限：{family} 已停留 {dwell:.0f}s 未推进（实际画面={world}）")
        self._record_environment_incident(f"hitch_dwell_cap_{family}", dwell)
        if family == "recover" and world.startswith("game"):
            self._hitch_reconcile_to(Phase.QUIT, world, now)
            return True
        if family == "room" and not getattr(self, "_hitch_dwell_room_left", False):
            self._hitch_dwell_room_left = True
            self._hitch_liveness_leave(world, now)
            return True
        print(f"[med] 蹭车停留上限：{family} 无法推进，BLOCKED 停止")
        self.set_phase(Phase.ERROR, f"hitch {family} dwell cap ({world})")
        self.stop()
        return True

    def _hitch_liveness_leave(self, world: str, now: float) -> None:
        if world.startswith("game"):
            self._recovery_state = None
            self._recovery_step = "DONE"
            print(f"[med] 无进展监督：离开卡住的游戏（{world}）")
            self.set_phase(Phase.QUIT, f"hitch liveness: leave stalled game ({world})")
            return
        if world == "kk_room":
            # The room's own bounded exit transaction (Esc, fresh-lobby proof,
            # BLOCKED after its grace) does the leaving.
            self._hitch_ready_timeout_pending = True
            self._hitch_ready_timeout_leave_at = None
            self._hitch_ready_timeout_attempts = 0
            self._hitch_ready_timeout_deadline = now + 30.0
            print("[med] 蹭车无进展监督：离开卡住的房间")
            self.set_phase(Phase.ROOM_WAITING, "hitch liveness: leave stalled room")
            return
        self._hitch_after_exit(now)
        print(f"[med] 蹭车无进展监督：重新开始大厅找房（{world}）")
        self.set_phase(Phase.LOBBY_ROOM, f"hitch liveness: restart lobby search ({world})")

    def _hitch_reconcile_to(self, target: Phase, world: str, now: float) -> None:
        note = f"hitch liveness reconcile ({world})"
        if target == Phase.QUIT:
            self._recovery_state = None
            self._recovery_step = "DONE"
        elif target == Phase.MAIN_LINE:
            if self.phase in (Phase.ROOM_WAITING, Phase.LOBBY_ROOM) and self._hitch_arm_opening_pressure(
                "liveness reconcile"
            ):
                note = "hitch natural round entry"
        elif target in (Phase.LOBBY_ROOM, Phase.ROOM_WAITING) and self.phase in (
            IN_GAME_FAILURE_PREEMPT_PHASES | {Phase.RECOVER_FAILURE, Phase.NEXT}
        ):
            # The game is gone without our verified exit: the old round's
            # transient state must not leak into the KK flow.
            self._hitch_after_exit(now)
        print(f"[med] 蹭车无进展监督：阶段校正 {self.phase.name} → {target.name}（{world}）")
        self.set_phase(target, note)

    def _new_hitch_sm(self) -> HitchSearchSM:
        return HitchSearchSM(
            prefix=self._hitch_sm.prefix,
            prefixes=self._hitch_sm.prefixes,
            rotate_interval=self._hitch_sm.rotate_interval,
            join_limit=self._hitch_sm.join_limit,
            search_timeout_s=self._hitch_sm.search_timeout_s,
            sleep_s=self._hitch_sm.sleep_s,
            refresh_s_min=self._hitch_sm.refresh_s_min,
            refresh_s_max=self._hitch_sm.refresh_s_max,
            continuous=self._hitch_sm.continuous,
        )

    def _hitch_after_exit(self, now: float) -> None:
        self._awaiting_room_return = False
        self._hitch_re_search = True
        self._hitch_sm = self._new_hitch_sm()
        # KK keeps the previously typed text in the box across a room exit, so
        # clearing our own transaction is exactly right: the next episode must
        # re-prove the prefix visually rather than inherit this one's proof.
        self._hitch_search = None
        self._hitch_refresh_required = True
        self._hitch_pending_row_y = None
        self._hitch_join_origin_hwnd = None
        self._hitch_pending_room_key = None
        self._hitch_host_difficulty_since = None
        # Task 2: floor-exit transient must not leak across episode re-entry;
        # every hitch reset path converges here, so clear the pending/confirmed
        # latch at this single real episode boundary.
        self._hitch_floor_exit_pending = False
        self._hitch_floor_exit_confirmed = False
        self._hitch_floor_exit_attempted_at = None
        self._hitch_floor_exit_deadline = None
        self._hitch_floor_exit_input_generation = None
        self._hitch_floor_exit_reobserve_until = None
        self._hitch_floor_exit_started_at = None
        self._hitch_floor_exit_clicks = 0
        self._hitch_floor_exit_confirm_clicks = 0
        self._hitch_floor_exit_confirm_at = None
        # Seat knowledge belongs to one room visit.
        self._hitch_member_room_hwnd = None
        self._hitch_pre_ready_rows = None
        self._hitch_self_row = None
        self._hitch_floor_one_baseline = None
        self._hitch_floor_one_candidate = None
        self._hitch_seat_streak = None
        self._hitch_seat_generation = None
        self._hitch_join_preexisting_hwnds = frozenset()
        # P0-6：70s 超时退房生命周期随每次 episode 边界一并收敛
        self._hitch_ready_timeout_pending = False
        self._hitch_ready_timeout_leave_at = None
        self._hitch_ready_timeout_attempts = 0
        self._hitch_ready_timeout_deadline = None
        self._hitch_ready_confirmed_at = None
        self._hitch_opening_pressure_armed = False
        self._hitch_heirloom_exit_since = None
        self._hitch_postgame_started_at = None
        self._hitch_rejected_row_ys.clear()
        # P1-1：关闭预算不在此重置——本函数也服务被踢重置路径，那里
        # 弹窗可能仍在，重置会重新计满预算造成无限 Esc。预算只随
        # 「fresh 帧证明弹窗消失」收敛（见 _tick_lobby_hitch 顶部）。
        # 蹭车可能从加载画面直接进 MAIN_LINE，不经 STAGE_SELECT。
        # 因此已验证的离局边界必须自己清理上局 hard deadline/outcome，
        # 否则次局会继承过期 deadline 并立即退出。
        self._round_started_at = None
        self._round_deadline = None
        self._outcome_recorded = False
        self._round_outcome = None

    def _hitch_quit_misopened_stage(self) -> LoopAction:
        """Solo stage/map page means we accidentally hosted. Quit, don't wait."""
        if self._hitch_pending_room_key is not None:
            self._hitch_blacklisted_room_keys.add(self._hitch_pending_room_key)
        print("[L0] hitch 误开选关/游戏大厅，退出当前游戏")
        self.set_phase(Phase.QUIT, "hitch misopened stage page")
        return LoopAction.Continue

    def _finish_hitch_round(
        self, now: float, note: str, *, already_counted: bool = False
    ) -> LoopAction:
        """记录一次已验证的蹭车离局，然后回到大厅继续找房。"""
        if not already_counted:
            self.game_count += 1
        self._hitch_game_exit_at = now
        self._ticket_budget_spent_one_round()
        projected = self._ticket_projected_remaining()
        print(
            f"[med] 蹭车已完成离局 count={self.game_count}"
            + (f" 挑战券估算剩余≈{projected}" if projected is not None else " 挑战券未读出")
        )
        goal_reached = self.settings.cycle_num > 0 and self.game_count >= self.settings.cycle_num
        # 票不够再来一局 -> 下一局不再搜房，直接走同一条考古出口。
        # 估算读不出时 _ticket_budget_allows_another_round() 返回 True（未知不是耗尽）。
        budget_out = not goal_reached and not self._ticket_budget_allows_another_round()
        if budget_out:
            print(
                f"[med] 挑战券估算剩余≈{projected} < 每局 {self._TICKET_COST_PER_ROUND}，"
                f"不再搜房（已完成 {self.game_count} 局）"
            )
        if goal_reached or budget_out:
            if str(getattr(self.settings, "hitch_after_goal", "solo") or "solo") == "arch":
                # The guest must leave the verified room before using the
                # existing normal-farm route to its own stage page.  The
                # pending flag then authorizes only the existing archaeology
                # request/confirm transaction; it never starts another hitch round.
                self.settings.mode_id = "normal_farm"
                # hitch_lobby_chain disables room creation while searching;
                # archaeology handoff is a new solo run and must restore the
                # normal-farm room owner before the fresh stage route.
                self.settings.auto_create_room = True
                self._hitch_after_exit(now)
                self._hitch_goal_archaeology_handoff = True
                self._archaeology_handoff_pending = True
                self._room_leave_pending = True
                self._room_leave_next_at = 0.0
                self._room_action_deadline = now + min(self.settings.query_timeout, 30)
                self.set_phase(Phase.ROOM_WAITING, "hitch cycle complete; leaving room for archaeology")
                why = "cycle_num 达标" if goal_reached else "挑战券预算不足"
                print(f"[med] 蹭车收尾（{why}），离房后进入考古")
                return LoopAction.Continue
            why = "cycle_num 达标" if goal_reached else "挑战券预算不足"
            print(f"[med] 蹭车收尾（{why}），转 COMPLETE 停止")
            self.set_phase(Phase.COMPLETE, "cycle_num reached" if goal_reached else "ticket budget exhausted")
            self.stop()
            return LoopAction.Break
        self._hitch_after_exit(now)
        self.set_phase(Phase.LOBBY_ROOM, note)
        return LoopAction.Continue

    def _hitch_reset_lobby(self, evidence: str, now: float) -> LoopAction:
        print(f"[L0] hitch {evidence} 触发，重置状态回大厅")
        if self._hitch_pending_room_key is not None:
            self._hitch_blacklisted_room_keys.add(self._hitch_pending_room_key)
            print(f"[L0] hitch 拉黑房间 key={self._hitch_pending_room_key} ({evidence})")
        self._hitch_after_exit(now)
        self._hitch_status = "大厅主页"
        self._hitch_re_search = False
        self.set_phase(Phase.LOBBY_ROOM, f"hitch {evidence} reset")
        return LoopAction.Continue

    def _tick_follow_team(
        self,
        frame: Frame,
        context: str,
        room_start=None,
        stage_page: bool = False,
    ) -> LoopAction:
        phase = self._follow_sm.tick(
            in_game=context in ("MAIN_LINE", "IN_GAME"),
            in_room=room_start is not None or context == "ROOM_WAITING",
            stage_page=bool(stage_page) or context == "STAGE_SELECT",
        )
        if phase is FollowPhase.IN_GAME:
            self.set_phase(Phase.MAIN_LINE, "follow already in game")
            return LoopAction.Continue
        if phase is FollowPhase.STAGE_WAIT:
            self.set_phase(Phase.STAGE_SELECT, "follow stage page wait")
            print("[L0] follow_team 选关页可见，零输入等待进局（不点关卡）")
            return LoopAction.Continue
        if phase is FollowPhase.WAIT_HOST:
            self.set_phase(Phase.ROOM_WAITING, "follow in room waiting host")
            print("[L0] follow_team 已在房，等待房主开始（不点 RoomStart）")
            return LoopAction.Continue
        self.set_phase(Phase.LOBBY_ROOM, "follow waiting to be in room")
        print("[L0] follow_team 未在房间，零输入等待（不创房、不 quick join）")
        return LoopAction.Continue

    # KK chrome is drawn at a fixed pixel size.  Offsets are from the top-left
    # of the "kk!官方对战平台" logo, measured on the live 1332x812 and 1332x945
    # lobby: the "游戏" label box and the sidebar selection background.
    _KK_NAV_GAME_BOX = (228, 2, 266, 26)
    _KK_NAV_GAME_CLICK = (246, 14)
    _KK_NAV_MAX_CLICKS = 6
    _KK_NAV_COOLDOWN_S = 1.5
    _KK_NAV_BLOCK_S = 60.0

    def _hitch_kk_main_nav(self, frame: Frame) -> dict | None:
        """Read the KK main window's navigation state, or None if this frame
        is not the main window (room windows cut the logo; dialogs are small).
        """
        if frame.bgr is None or frame.width < 1000 or frame.height < 600:
            return None
        logo = self.find(frame, ["lobby/kk_nav_logo"], threshold=0.85, roi=(0.0, 0.0, 0.35, 0.12))
        if logo is None or logo.x > 40 or logo.y > 30:
            return None
        gray = cv2.cvtColor(frame.bgr, cv2.COLOR_BGR2GRAY)
        bx0, by0, bx1, by1 = self._KK_NAV_GAME_BOX
        game_box = gray[logo.y + by0:logo.y + by1, logo.x + bx0:logo.x + bx1]
        # Active tab label is pure white; inactive labels peak around 131.
        game_active = bool(game_box.size) and int(np.count_nonzero(game_box >= 220)) >= 60
        gx, gy = logo.x + self._KK_NAV_GAME_CLICK[0], logo.y + self._KK_NAV_GAME_CLICK[1]
        game_click = MatchResult(
            "kk_nav_game_tab", 1.0, gx, gy, 1, 1, frame.left + gx, frame.top + gy,
        )
        side: dict[str, tuple[MatchResult, bool]] = {}
        for key, template in (
            ("cssss", "lobby/kk_side_cssss_icon"),
            ("yxsg", "lobby/kk_side_yxsg_icon"),
        ):
            hit = self.find(frame, [template], threshold=0.80, roi=(0.0, 0.05, 0.16, 1.0))
            if hit is None or hit.x > 200:
                continue
            cy = hit.y + hit.h // 2
            patch = gray[max(0, cy - 6):cy + 6, hit.x + 125:hit.x + 137]
            # Selected sidebar rows are painted ~46 gray, others ~23.
            selected = bool(patch.size) and float(np.mean(patch)) >= 35.0
            side[key] = (hit, selected)
        return {"game_active": game_active, "game_click": game_click, "side": side}

    def _hitch_nav_reset(self) -> None:
        self._hitch_nav_since = None
        self._hitch_nav_clicks = 0
        self._hitch_nav_last_click_at = None
        self._hitch_nav_input_generation = None

    def _tick_hitch_kk_nav(self, frame: Frame, nav: dict, now: float) -> LoopAction | None:
        """Last-resort navigation back to the game page of the right game.

        Only runs for the KK main window off the room list (never for rooms,
        prompts or join children).  ``None`` means navigation is already
        correct and the map-page flow owns the frame.
        """
        side_ok = any(selected for _hit, selected in nav["side"].values())
        if nav["game_active"] and side_ok:
            return None
        if getattr(self, "_hitch_nav_since", None) is None:
            self._hitch_nav_since = now
        generation = int(getattr(self, "_capture_generation", 0) or 0)
        input_generation = getattr(self, "_hitch_nav_input_generation", None)
        if input_generation is not None and generation <= int(input_generation):
            print("[L0] hitch 导航兜底等待 fresh 帧复核（零输入）")
            return LoopAction.Continue
        last = getattr(self, "_hitch_nav_last_click_at", None)
        if last is not None and now - float(last) < self._KK_NAV_COOLDOWN_S:
            print("[L0] hitch 导航兜底冷却中（零输入）")
            return LoopAction.Continue
        clicks = int(getattr(self, "_hitch_nav_clicks", 0) or 0)
        if clicks >= self._KK_NAV_MAX_CLICKS or now - float(self._hitch_nav_since) >= self._KK_NAV_BLOCK_S:
            self._record_lobby_observation_incident(
                "kk_nav_recovery_exhausted",
                "KK 主窗口导航兜底耗尽：未回到 游戏 + 英雄三国/重生魔兽刷刷刷",
                frame,
                extra={"clicks": clicks, "game_active": nav["game_active"],
                       "side": {k: v[1] for k, v in nav["side"].items()}},
            )
            print("[L0] hitch KK 主窗口导航兜底耗尽，BLOCKED 停止")
            self.set_phase(Phase.ERROR, "hitch kk navigation blocked")
            self.stop()
            return LoopAction.Break
        if not nav["game_active"]:
            target, reason = nav["game_click"], "HitchNavGameTab"
            label = "顶部「游戏」"
        else:
            entry = nav["side"].get("cssss") or nav["side"].get("yxsg")
            if entry is None:
                # Sidebar not rendered yet (or the game is not listed):
                # nothing verifiable to click; the time bound above ends it.
                print("[L0] hitch 导航兜底：侧栏未出现英雄三国/重生魔兽刷刷刷入口，零输入等待")
                return LoopAction.Continue
            hit = entry[0]
            cx, cy = hit.x + hit.w // 2, hit.y + hit.h // 2
            target = MatchResult(
                "kk_nav_sidebar_game", 1.0, cx, cy, 1, 1, frame.left + cx, frame.top + cy,
            )
            reason = "HitchNavSidebarGame"
            label = "侧栏「重生魔兽刷刷刷」" if "cssss" in nav["side"] else "侧栏「英雄三国」"
        self._hitch_nav_last_click_at = now
        if self.act_click(target, reason):
            self._hitch_nav_clicks = clicks + 1
            self._hitch_nav_input_generation = generation
            self._hitch_search = None
            print(f"[L0] hitch 大厅不在目标页，导航兜底点击{label}（第 {self._hitch_nav_clicks} 次）")
        else:
            print(f"[L0] hitch 导航兜底点击{label}被拒绝，冷却后重试")
        self.set_phase(Phase.LOBBY_ROOM, "hitch kk navigation fallback")
        return LoopAction.Continue

    def _tick_hitch_room_list_tab(self, frame: Frame, now: float) -> LoopAction | None:
        """Acquire the room-list tab inside the search operation's budget.

        ``None`` hands the tick to ``HitchSearchSM``.  Tab acquisition used to
        sit outside every budget: a tab that was never recognised, or one that
        was clicked but never switched, could hold the run on zero input
        forever.  The click path also never consulted ``next_allowed_at``, so
        the ``defer_retry()`` beside it throttled nothing.
        """
        if self._hitch_sm.search_window_expired(now):
            # Time cannot switch a tab.  Drop any stale proof and let the
            # state machine take its bounded way back to a safe baseline.
            self._hitch_search = None
            self._hitch_status = "房间列表 Tab 预算耗尽"
            print("[L0] hitch 房间列表 Tab 预算耗尽，交由状态机回退安全基线")
            return None
        tab_unselected = self._find_hitch_room_list_tab(frame)
        if tab_unselected is None:
            self._hitch_sm.defer_retry(now)
            self._hitch_status = "等待可信房间列表 Tab"
            print("[L0] hitch 未识别房间列表 Tab，零输入等待")
            return LoopAction.Continue
        if self._hitch_room_like(frame):
            # The fixed tab slot of the lobby lands on the first seat's avatar
            # in a room window (2026-09-11 misclick, (672,308)).  A page with
            # seat-table evidence never gets lobby navigation authority.
            self._hitch_sm.defer_retry(now)
            self._hitch_status = "房间页禁止大厅导航"
            print("[L0] hitch 当前帧具有房间座位特征，禁止点击房间列表 Tab（零输入）")
            return LoopAction.Continue
        if not self._hitch_sm.input_allowed(now):
            # A cooldown throttles what we send, never what we look at.
            self._hitch_status = "房间列表 Tab 重试冷却"
            print("[L0] hitch 房间列表 Tab 重试冷却中，零输入观察")
            return LoopAction.Continue
        if self.act_click(tab_unselected, "HitchSelectTab"):
            print(
                "[L0] hitch 点击切换至房间列表 Tab: "
                f"({tab_unselected.screen_x}, {tab_unselected.screen_y})"
            )
        else:
            print("[L0] hitch 房间列表 Tab 点击被拒绝，零输入等待")
        # A successful click is an input, not a switched page: cool down either
        # way and re-prove the surface from a later frame.
        self._hitch_sm.defer_retry(now)
        return LoopAction.Continue

    def _tick_hitch_search(self, frame: Frame, now: float) -> LoopAction | None:
        """Drive one bounded search transaction on a trusted room-list frame.

        ``None`` means the operation's budget is spent and the state machine
        owns the next decision.
        """
        surface = (frame.hwnd, frame.width, frame.height)
        tx = self._hitch_search
        if tx is not None and (
            # A rotated prefix invalidates whatever the box currently proves.
            tx.prefix != self._hitch_sm.prefix
            # So does a different window or client size: the proof was about
            # a surface that is no longer the one in front of us.
            or (tx.surface is not None and tx.surface != surface)
        ):
            tx = self._hitch_search = None

        if tx is not None and tx.awaiting_confirm:
            if self._hitch_search_prefix_confirmed(frame, tx.prefix, now):
                tx.confirmed = True
                self._hitch_rejected_row_ys.clear()
                print(f"[L0] hitch 搜索词 '{tx.prefix}' 已由搜索框视觉证据确认")
            elif now - float(tx.typed_at or now) >= self._HITCH_SEARCH_CONFIRM_S:
                # Elapsed time cannot manufacture visual evidence, so this
                # never confirms.  Reopen the same operation for a bounded
                # retype; the durable budget below still owns the way out.
                tx.reopen_for_retype()
                self._hitch_sm.defer_retry(now)
                print(f"[L0] hitch 搜索词 '{tx.prefix}' 未获视觉确认，零输入重试")
            else:
                print(f"[L0] hitch 等待搜索词 '{tx.prefix}' 生效确认（零输入）")
            # 确认成立的当前 tick 仍不扫描房间；下一张新帧才允许使用过滤结果。
            return LoopAction.Continue

        if tx is None or not tx.confirmed:
            prefix = self._hitch_sm.prefix
            if not self._hitch_sm.search_window_expired(now):
                search_hit = self._find_hitch_search_box(frame)
                if search_hit is None:
                    self._hitch_sm.defer_retry(now)
                    print("[L0] hitch 未识别搜索框，零输入等待")
                elif not self._hitch_sm.input_allowed(now):
                    # A cooldown throttles what we send, never what we look
                    # at; the postcondition above keeps reading every frame.
                    print(f"[L0] hitch 搜索词 '{prefix}' 重试冷却中，零输入观察")
                else:
                    if tx is None:
                        tx = self._hitch_search = SearchTransaction(
                            prefix=prefix, opened_at=now, surface=surface,
                        )
                    if self.act_search_box(search_hit, prefix, "HitchSearchBox"):
                        # Stamped after the action returns: search_text()
                        # spends over a second clicking/clearing/typing on the
                        # real client and that must not be billed to the
                        # visual confirmation window.
                        tx.typed_at = time.time()
                        print(
                            f"[L0] hitch 搜索词 '{prefix}' 已输入并回车，等待后置确认: "
                            f"({search_hit.screen_x}, {search_hit.screen_y})"
                        )
                    else:
                        self._hitch_sm.defer_retry(now)
                        print(f"[L0] hitch 搜索词 '{prefix}' 输入被拒绝，保持未搜索状态")
                return LoopAction.Continue
            # Durable budget spent without a confirmed search.  Drop the
            # operation and fall through to the state machine, which owns the
            # bounded way back (GO_HOME -> lobby home -> sleep retry).  The
            # postcondition is never faked and rows stay ineligible, so an
            # unfiltered list can still not be joined.
            self._hitch_search = None
            self._hitch_status = "搜索预算耗尽"
            print(f"[L0] hitch 搜索词 '{prefix}' 预算耗尽，交由状态机回退安全基线")
            return None
        # A confirmed transaction falls through: the row scan is the caller's.
        return None

    def _find_hitch_platform_prompt_cancel(self, frame: Frame) -> MatchResult | None:
        """KK 主窗口上覆盖的「平台提示」（如被房主移出）里的灰色「取消」按钮。

        旧的 lobby_popup_dialog 模板裁进了房间列表背景，被踢时从不命中；
        这里只用弹窗自身的标题 + 取消按钮，并要求两者处在同一对话框几何内。
        """
        scales = (1.0, 0.9, 1.1)
        title = self.find(frame, ["lobby/kk_platform_prompt_title"], threshold=0.85, scales=scales)
        if title is None:
            return None
        cancel = self.find(frame, ["lobby/kk_platform_prompt_cancel"], threshold=0.85, scales=scales)
        if cancel is None:
            return None
        dx, dy = cancel.x - title.x, cancel.y - title.y
        if not (120 <= dx <= 260 and 100 <= dy <= 170):
            return None
        return cancel

    def _tick_hitch_platform_prompt(self, frame: Frame, now: float) -> LoopAction | None:
        """点「取消」关掉 KK 主窗口上的平台提示，等待 fresh 帧消失复核后再回大厅重新找房。

        先于 G0 的 _tick_hitch_platform_modal（Esc→X）执行；两者识别互为兜底。
        440x260 子窗口（退出确认、房间已满等）交给 G0 分支：退出确认
        同样带「平台提示/取消」，点取消会中断离房，所以这里只看主窗口。
        实机证据：被踢提示上 Esc 连按 3 次都关不掉，只能点按钮。
        """
        if (
            frame.role != "l0"
            or frame.width <= 600
            or self.phase not in (Phase.ROOM_WAITING, Phase.LOBBY_ROOM)
            or getattr(self, "_hitch_floor_exit_pending", False)
        ):
            return None

        previous_observation = getattr(self, "_hitch_platform_prompt_input_observation", None)
        current_observation = self._hitch_modal_observation_key(frame)
        cancel = self._find_hitch_platform_prompt_cancel(frame)

        # 3A: fresh frame proves prompt absent -> then reset/search
        if previous_observation is not None and current_observation != previous_observation and cancel is None:
            self._hitch_platform_prompt_input_observation = None
            self._hitch_platform_prompt_click_at = None
            self._hitch_platform_prompt_pending = False
            if self._hitch_pending_room_key is not None:
                self._hitch_blacklisted_room_keys.add(self._hitch_pending_room_key)
            if self._hitch_sm.pending_join:
                self._hitch_reject_pending_join(now, "join_rejected")
                self._hitch_search_actions.append("reject")
            print("[L0] hitch 平台提示已在 fresh 帧消失，回大厅重新找房")
            return self._hitch_reset_lobby("platform_prompt_dismissed", now)

        if cancel is None:
            return None

        if previous_observation is not None and current_observation == previous_observation:
            print("[L0] hitch 平台提示等待 fresh 帧复核（零输入）")
            return LoopAction.Continue

        last = getattr(self, "_hitch_platform_prompt_click_at", None)
        if last is not None and now - last < 1.5:
            print("[L0] hitch 平台提示关闭冷却中，零输入观察")
            return LoopAction.Continue

        self._hitch_platform_prompt_click_at = now
        if self.act_click(cancel, "HitchDismissPlatformPrompt"):
            # 3A: Click success 不是 dismiss success。记录输入观察，零输入等待 fresh 帧证明消失。
            self._hitch_platform_prompt_input_observation = current_observation
            self._hitch_platform_prompt_pending = True
            print(f"[L0] hitch 平台提示已发起取消: ({cancel.screen_x}, {cancel.screen_y})，零输入等待消失确认")
            return LoopAction.Continue
        else:
            # 3B: Cancel 被拒绝，记录冷却并重观察，禁止发猜想性 Esc 或立刻重置
            print("[L0] hitch 平台提示「取消」点击被拒绝，记录冷却并零输入重观察")
            return LoopAction.Continue

    def _hitch_room_buttons_visible(self, frame: Frame) -> bool:
        """房间窗口身份：G0 多信号 ROOM 契约或房间退出按钮（实机大厅 78 帧零误报）。"""
        return (
            self._is_confirmed_room_frame(frame)
            or self._find_hitch_exit_button(frame) is not None
        )

    # 平台侧弹窗 30s 即算卡死；游戏窗口实测加载画面约 50s，放宽到 60s。
    _HITCH_STALL_ESC_L0_S = 30.0
    _HITCH_STALL_ESC_GAME_S = 60.0
    _HITCH_READY_WAIT_S = 70.0
    # 蹭车在游戏内等待房主选难度的超时时间（秒）。
    # 正常房主选关在 5~15s 内完成；若超过 60s 仍未选，说明房主挂机/掉线或卡死，
    # 蹭车客人应主动退出避免无进展死等；与 _HITCH_STALL_ESC_GAME_S (60s) 和 _HITCH_READY_WAIT_S (70s) 同量级。
    _HITCH_HOST_DIFFICULTY_TIMEOUT_S = 60.0
    # Upper bound for holding the lobby flow while our readied room's window
    # still exists but is not recognised (ready wait + exit + margin).
    _HITCH_MEMBER_ROOM_HOLD_S = 150.0
    # Hitch liveness supervisor (user, 2026-09-12): no hitch phase may sit
    # without a successful input for long, whatever branch is waiting.
    # Budgets sit above the legitimate quiet stretches of each phase (the 70s
    # ready wait plus exit, the ~70s quiet gaps of an auto-fighting round, a
    # host picking the difficulty).
    _HITCH_STALL_BUDGET_S = {
        Phase.LOBBY_ROOM: 90.0,
        Phase.ROOM_WAITING: 180.0,
        Phase.MAIN_LINE: 180.0,
        Phase.RECOVER_FAILURE: 90.0,
        Phase.QUIT: 60.0,
        Phase.NEXT: 60.0,
    }
    _HITCH_STALL_DEFAULT_S = 150.0
    # Non-hitch unattended modes share the ladder only inside a game.
    _UNATTENDED_SUPERVISED_PHASES = frozenset(
        {Phase.MAIN_LINE, Phase.RECOVER_FAILURE, Phase.QUIT, Phase.NEXT}
    )
    # Observed world -> the phase that owns it.
    _HITCH_WORLD_PHASE = {
        "game_failure": Phase.QUIT,
        "game_stage": Phase.QUIT,
        "game_round": Phase.MAIN_LINE,
        "game_postgame": Phase.MAIN_LINE,
        "game_waiting": Phase.ROOM_WAITING,
        "kk_room": Phase.ROOM_WAITING,
        "kk_lobby": Phase.LOBBY_ROOM,
    }
    # After a verified game exit the window takes a moment to close; the
    # lobby phase must not re-adopt it as a running round meanwhile.
    _HITCH_GAME_CLOSE_GRACE_S = 25.0
    # Keys pressed blindly by a local stall watchdog are not progress.
    _LIVENESS_BLIND_REASONS = frozenset(
        {"HitchStallWatchdogEsc", "HitchLeaveMisopenedStage", "CloseGameChat", "ParkPointer"}
    )
    # Livelock caps: total dwell per phase family, inputs or not.
    _HITCH_PHASE_FAMILY = {
        Phase.QUIT: "exit", Phase.NEXT: "exit",
        Phase.RECOVER_FAILURE: "recover",
        Phase.ROOM_WAITING: "room",
    }
    _HITCH_DWELL_CAP_S = {"exit": 240.0, "recover": 180.0, "room": 600.0}
    # Lobby/room phases whose every KK surface stays unusable this long end in
    # an explicit BLOCKED (ERROR) instead of zero-input observation forever.
    _HITCH_L0_UNHEALTHY_BLOCK_S = 120.0
    # Room exit: re-click Exit / Confirm when a fresh frame shows the click was
    # swallowed; give up with an explicit BLOCKED after the hard cap.
    _HITCH_EXIT_RETRY_S = 4.0
    _HITCH_EXIT_MAX_CLICKS = 3
    _HITCH_EXIT_HARD_CAP_S = 60.0
    _HITCH_READY_TIMEOUT_GRACE_S = 60.0

    def _tick_hitch_stall_watchdog(self, frame: Frame, context: str, now: float) -> LoopAction | None:
        """无进展兜底：大厅/房间等待阶段持续 UNKNOWN 且期间零输入时按一次 Esc。

        覆盖模板还没收录的弹窗（实机：被踢提示 73s、游戏大厅弹窗 60s 零输入）。
        确认的房间内不按——房间里 Esc 等于离房。Esc 本身计为输入，
        所以仍卡住时每隔同样时长再试一次。
        """
        if self.phase not in (Phase.ROOM_WAITING, Phase.LOBBY_ROOM):
            self._hitch_unknown_since = None
            return None
        # 3D: 如果存在 active exit transaction、confirmed room、known platform prompt、generic modal shell，不得发送 Esc
        if getattr(self, "_hitch_floor_exit_pending", False):
            return None
        game = self._is_game_client_frame(frame)
        if not game and frame.hwnd is not None and (
            self._is_confirmed_room_frame(frame)
            or self._hitch_room_buttons_visible(frame)
        ):
            self._hitch_room_window_hwnd = frame.hwnd

        confirmed_room_hwnd = getattr(self, "_confirmed_room_hwnd", None)
        if (
            (confirmed_room_hwnd is not None and frame.hwnd == confirmed_room_hwnd)
            or self._is_confirmed_room_frame(frame)
            or self._hitch_room_buttons_visible(frame)
        ):
            return None
        if (
            self._find_hitch_platform_prompt_cancel(frame) is not None
            or getattr(self, "_hitch_platform_prompt_pending", False)
        ):
            return None
        if self._kk_platform_modal_shell(frame) is not None:
            return None
        if context != "UNKNOWN":
            self._hitch_unknown_since = None
            return None
        if self._hitch_unknown_since is None:
            self._hitch_unknown_since = now
            return None
        # 开局倒计时/反作弊升级会盖住按钮，但仍是房间窗口：记住的 hwnd 兜底
        if not game and frame.hwnd is not None and frame.hwnd == self._hitch_room_window_hwnd:
            return None
        limit = self._HITCH_STALL_ESC_GAME_S if game else self._HITCH_STALL_ESC_L0_S
        quiet_since = max(self._hitch_unknown_since, self._last_input_at or 0.0)
        if now - quiet_since < limit:
            return None
        print(f"[L0] hitch {now - quiet_since:.0f}s 无进展（UNKNOWN 且零输入），Esc 兜底")
        self.act_key("esc", "HitchStallWatchdogEsc")
        return LoopAction.Continue

    def _tick_hitch_host_choosing_difficulty(self, now: float) -> LoopAction:
        """非一楼在游戏内等待房主选难度：有界等待；超时则拉黑该房并走真实退出链。"""
        self._hitch_status = "host_choosing_difficulty"
        if self._hitch_host_difficulty_since is None:
            self._hitch_host_difficulty_since = now
        elapsed = now - self._hitch_host_difficulty_since
        if elapsed >= self._HITCH_HOST_DIFFICULTY_TIMEOUT_S:
            print(
                f"[L0] hitch 游戏内等待 1 号位选择难度超时（{elapsed:.0f}s >= "
                f"{self._HITCH_HOST_DIFFICULTY_TIMEOUT_S:.0f}s），退出游戏并拉黑"
            )
            self._hitch_host_difficulty_since = None
            if self._hitch_pending_room_key is not None:
                self._hitch_blacklisted_room_keys.add(self._hitch_pending_room_key)
            self.set_phase(Phase.QUIT, "hitch host difficulty timeout")
            return LoopAction.Continue
        print(
            f"[L0] hitch 游戏内等待 1 号位选择难度（已等待 "
            f"{elapsed:.0f}s/{self._HITCH_HOST_DIFFICULTY_TIMEOUT_S:.0f}s，零输入）"
        )
        return LoopAction.Continue

    def _tick_lobby_hitch(
        self,
        frame: Frame,
        context: str,
        room_start=None,
        stage_page: bool = False,
    ) -> LoopAction:
        now = time.time()
        # P0-1：蹭车在 ROOM_WAITING 收到已验证的游戏窗帧时，绝不强推 MAIN_LINE
        # （旧实现会把 game client 帧误判成已在局内而吞掉房内状态）；零输入交给
        # 后续 surface reconciliation（stage/hero/hud/战后入口各归其位）。
        if self.phase == Phase.ROOM_WAITING and self._is_game_client_frame(frame):
            if self._is_in_game_hud(frame):
                self._hitch_host_difficulty_since = None
                # A successful guest Ready transition is the authoritative
                # natural-entry proof.  Room-number OCR is only needed for
                # blacklist bookkeeping and must not suppress the opening
                # pressure gate when the number is temporarily unreadable.
                self._hitch_opening_pressure_armed = bool(
                    self._hitch_ready_confirmed_at is not None
                )
                if getattr(self, "_hitch_ready_timeout_pending", False):
                    self._hitch_ready_timeout_pending = False
                    self._hitch_ready_timeout_leave_at = None
                    print("[L0] hitch 70s 等待期间房主开局（可信局内 HUD），取消超时退房并移交游戏流程")
                print("[L0] hitch ROOM_WAITING 观察到游戏客户端帧，零输入移交状态对齐")
                return LoopAction.Continue
            if self._host_choosing_difficulty(frame):
                return self._tick_hitch_host_choosing_difficulty(now)
            if stage_page or self._find_stage_page(frame):
                return self._hitch_quit_misopened_stage()
            if getattr(self, "_hitch_ready_timeout_pending", False):
                print("[L0] hitch 游戏客户端帧无可信局内证据，保持超时退房（零输入）")
                return LoopAction.Continue
            print("[L0] hitch ROOM_WAITING 观察到游戏客户端帧，零输入移交状态对齐")
            return LoopAction.Continue
        if context in ("MAIN_LINE", "IN_GAME"):
            self._hitch_host_difficulty_since = None
            self._hitch_re_search = False
            if self.phase == Phase.ROOM_WAITING and self._hitch_arm_opening_pressure(
                "room -> in-game context"
            ):
                self.set_phase(Phase.MAIN_LINE, "hitch natural round entry")
                return LoopAction.Continue
            self.set_phase(Phase.MAIN_LINE, "hitch already in game")
            return LoopAction.Continue
        if stage_page or context == "STAGE_SELECT":
            # 蹭车客人不应出现在单人选关/游戏大厅（扫荡/开始游戏/考古模式）。
            # 出现即误开或自己成了房主，立刻退出，不要零输入干等。
            # 例外：「等待玩家1选择难度」是客人看到的正常开局前页面。
            if self._host_choosing_difficulty(frame):
                return self._tick_hitch_host_choosing_difficulty(now)
            if self._is_game_client_frame(frame):
                return self._hitch_quit_misopened_stage()
            print("[L0] hitch 忽略非游戏窗口的 STAGE_SELECT 晋级请求，零输入保持大厅状态")
            return LoopAction.Continue
        if self._is_game_client_frame(frame) and not self._lobby_room_list_evidence(frame):
            # A game window (loading, prelude panels) never gets lobby search,
            # tab or join authority (nor the lobby stall-watchdog Esc); the
            # in-game HUD hands over to MAIN_LINE.  A timed-out join is still
            # settled so its row is skipped and the list refreshed later.
            sm = self._hitch_sm
            if (
                sm.pending_join
                and sm.join_clicked_at is not None
                and now - sm.join_clicked_at >= sm.join_confirm_timeout_s
            ):
                self._hitch_reject_pending_join(now, "join_rejected")
                self._hitch_search_actions.append("reject")
            # _tick_l0 classifies with the l0 role, which never reports QUIT;
            # read the failure/disconnect anchors of the game frame directly.
            if context == "QUIT" or self.find_scene(frame, "fail") or self.find_scene(frame, "disconnect"):
                # A failure/disconnect page of a game we are no longer
                # tracking: leave it through the standard quit chain
                # (top-left 退出游戏 -> confirmation) instead of waiting.
                self._recovery_step = "DONE"
                print("[L0] hitch 游戏窗口停在失败/断线页，走左上角退出游戏链路")
                self.set_phase(Phase.QUIT, "hitch game window on failure page; quit game")
                return LoopAction.Continue
            self._hitch_status = "game_window_align"
            print("[L0] hitch 英雄三国窗口已在前台流程中，零输入等待局内状态对齐")
            return LoopAction.Continue
        if frame.bgr is None or not frame.bgr.size or float(np.mean(frame.bgr)) < 3.0:
            print("[L0] hitch 黑帧/空帧，零输入等待可信大厅页面")
            return LoopAction.Continue

        # A confirmed room is a separate surface class: generic modal handling
        # never gets authority to Esc it.
        room_surface = self._is_confirmed_room_frame(frame)
        platform_modal = None if room_surface else self._kk_platform_modal_shell(frame)
        exit_pending = getattr(self, "_hitch_floor_exit_pending", False)
        confirmed_room_hwnd = getattr(self, "_confirmed_room_hwnd", None)

        # 1. ACTIVE EXIT TRANSACTION (highest authority)
        if exit_pending:
            # The dedicated exit transaction owns the page even when the
            # confirmation dialog is still visible.  Its deadline is a
            # recovery boundary, never proof that the room was left.  Handle
            # it before the modal branch so an unrecognised/partially rendered
            # exit dialog cannot park the transaction past its budget.
            current_generation = int(getattr(self, "_capture_generation", 0) or 0)
            input_generation = getattr(self, "_hitch_floor_exit_input_generation", None)
            fresh_after_input = input_generation is None or current_generation > int(input_generation)
            tangible_room_for_budget = bool(
                frame.hwnd is not None
                and confirmed_room_hwnd is not None
                and frame.hwnd == confirmed_room_hwnd
                and room_surface
            )
            lobby_for_budget = self._lobby_room_list_evidence(frame)
            lobby_done = lobby_for_budget and not tangible_room_for_budget and fresh_after_input
            started_at = getattr(self, "_hitch_floor_exit_started_at", None)
            if (
                started_at is not None
                and now - float(started_at) >= self._HITCH_EXIT_HARD_CAP_S
                and not lobby_done
            ):
                return self._hitch_room_exit_blocked(
                    frame, now,
                    f"退房事务 {now - float(started_at):.0f}s 未取得 fresh 大厅证据",
                )
            deadline = getattr(self, "_hitch_floor_exit_deadline", None)
            if (
                deadline is not None
                and now >= float(deadline)
                and not (lobby_for_budget and not tangible_room_for_budget and fresh_after_input)
            ):
                reobserve_until = getattr(self, "_hitch_floor_exit_reobserve_until", None)
                if reobserve_until is not None and now < float(reobserve_until):
                    print("[L0] hitch 退出事务预算到期，处于有界 reacquire/reclassify 观察期（零输入）")
                    return LoopAction.Continue
                self._record_lobby_observation_incident(
                    "floor_exit_reobserve_timeout",
                    "退出事务预算到期，未把时间当作已退出，重新采集并分类",
                    frame,
                    extra={"capture_generation": current_generation},
                )
                self._hitch_floor_exit_reobserve_until = now + 2.0
                self._hitch_floor_exit_deadline = now + self._HITCH_FLOOR_EXIT_BUDGET_S
                if not self.settings.dry_run:
                    try:
                        self._reacquire_target_window(getattr(frame, "hwnd", None), timeout_s=0.5)
                    except Exception as exc:
                        print(f"[L0] hitch 退出事务 reacquire 失败: {type(exc).__name__}")
                print("[L0] hitch 退出事务预算到期，已记录 incident 并重新观察（继续运行）")
                return LoopAction.Continue
            if (
                getattr(self, "_hitch_floor_exit_reobserve_until", None) is not None
                and now >= float(self._hitch_floor_exit_reobserve_until)
            ):
                self._hitch_floor_exit_reobserve_until = None
            # KK hosts "是否确认退出房间?" in its own small same-title HWND
            # (440x260 on every live capture), not inside the room window.
            exit_dialog_child = bool(
                frame.hwnd is not None
                and frame.hwnd != confirmed_room_hwnd
                and not room_surface
                and frame.width <= 700
                and frame.height <= 450
            )
            if (
                frame.hwnd is not None
                and (
                    (confirmed_room_hwnd is not None and frame.hwnd == confirmed_room_hwnd)
                    or exit_dialog_child
                )
                and self._hitch_exit_modal_visible(frame)
            ):
                exit_confirm = self._find_verified_room_exit_confirm(frame)
                confirmed = getattr(self, "_hitch_floor_exit_confirmed", False)
                confirm_at = getattr(self, "_hitch_floor_exit_confirm_at", None)
                confirm_clicks = int(getattr(self, "_hitch_floor_exit_confirm_clicks", 0) or 0)
                # A Confirm that a fresh frame still shows was swallowed.
                retry = bool(
                    confirmed
                    and fresh_after_input
                    and confirm_at is not None
                    and now - float(confirm_at) >= self._HITCH_EXIT_RETRY_S
                    and confirm_clicks < self._HITCH_EXIT_MAX_CLICKS
                )
                if exit_confirm is not None and (not confirmed or retry):
                    if self.act_click(exit_confirm, "HitchConfirmLeave"):
                        if self._hitch_pending_room_key is not None:
                            self._hitch_blacklisted_room_keys.add(self._hitch_pending_room_key)
                        self._hitch_floor_exit_confirmed = True
                        self._hitch_floor_exit_confirm_at = now
                        self._hitch_floor_exit_confirm_clicks = confirm_clicks + 1
                        self._hitch_floor_exit_input_generation = current_generation
                        self._hitch_status = "exit_confirmed"
                return LoopAction.Continue
            if platform_modal is not None:
                print("[L0] hitch 主动退出事务未识别到专用确认按钮，禁止通用关闭抢占")
                return LoopAction.Continue

        # 2. KNOWN PLATFORM PROMPT
        prompt_action = self._tick_hitch_platform_prompt(frame, now)
        if prompt_action is not None:
            return prompt_action

        # 3. GENERIC VERIFIED PLATFORM MODAL
        modal_action = self._tick_hitch_platform_modal(frame, platform_modal, now)
        if modal_action is not None:
            return modal_action

        # 4. STALL WATCHDOG (only last resort)
        stall_action = self._tick_hitch_stall_watchdog(frame, context, now)
        if stall_action is not None:
            return stall_action
        ready_state, ready_hit = self._hitch_room_ready_contract(frame)
        confirmed_room_hwnd = getattr(self, "_confirmed_room_hwnd", None)
        in_room = bool(
            frame.hwnd is not None
            and confirmed_room_hwnd is not None
            and frame.hwnd == confirmed_room_hwnd
            and self._is_confirmed_room_frame(frame)
        )
        if (
            self._hitch_sm.pending_join
            and not in_room
            and self._hitch_sm.join_clicked_at is not None
            and now - self._hitch_sm.join_clicked_at >= self._hitch_sm.join_confirm_timeout_s
        ):
            # Blocking modal has already been handled by PlatformModalShell.
            # Without that shell this is a genuine unknown surface: reject the
            # join transaction but never send a blind Esc.
            self._hitch_reject_pending_join(now, "join_rejected")
            self._hitch_search_actions.append("reject")
            origin_hwnd = self._hitch_join_origin_hwnd
            if origin_hwnd is not None and frame.hwnd != origin_hwnd:
                self._reacquire_target_window(origin_hwnd, timeout_s=0.5)
            print("[L0] hitch 进房超时且无平台 modal shell：零输入拒绝本次进房回大厅")
            self.set_phase(Phase.LOBBY_ROOM, "hitch join rejected")
            return LoopAction.Continue

        if getattr(self, "_hitch_floor_exit_pending", False):
            # 走到这里已经证明退出确认弹窗不在当前帧（exit_confirm/dialog 分支
            # 都提前 return）。act_click 被拒（鼠标被移动 / SendInput 校验失败）
            # 或用户手动 Esc 关掉弹窗时，_hitch_floor_exit_confirmed 永远不会置真。
            # 因此只有实体房间控件才算仍在房内；陈旧的 context=="ROOM_WAITING"
            # 不能无限挂住退出闩锁。但预算到期本身绝不是“已经退出”的证据。
            tangible_room = bool(
                frame.hwnd is not None
                and confirmed_room_hwnd is not None
                and frame.hwnd == confirmed_room_hwnd
                and self._is_confirmed_room_frame(frame)
            )
            lobby_visible = self._lobby_room_list_evidence(frame)
            if frame.bgr is None or float(np.mean(frame.bgr)) < 3.0:
                print("[L0] hitch 退出后捕获到黑帧，保持退出状态等待确认窗口/大厅")
                return LoopAction.Continue
            current_generation = int(getattr(self, "_capture_generation", 0) or 0)
            input_generation = getattr(self, "_hitch_floor_exit_input_generation", None)
            fresh_after_input = input_generation is None or current_generation > int(input_generation)
            if lobby_visible and not tangible_room and fresh_after_input:
                # 只有 fresh 大厅页面证据才可完成事务；不由时间预算推断。
                if self._hitch_pending_room_key is not None:
                    self._hitch_blacklisted_room_keys.add(self._hitch_pending_room_key)
                self._hitch_floor_exit_pending = False
                self._hitch_floor_exit_confirmed = False
                self._hitch_floor_exit_attempted_at = None
                self._hitch_floor_exit_deadline = None
                self._hitch_floor_exit_input_generation = None
                self._hitch_floor_exit_reobserve_until = None
                self._hitch_re_search = False
                self._hitch_after_exit(now)
                self._hitch_re_search = False
                self.set_phase(Phase.LOBBY_ROOM, "hitch floor-one rejection returned to lobby")
                print("[L0] hitch 一楼条件不符，fresh 大厅证据确认已回大厅；下个动作先刷新")
                return LoopAction.Continue
            if lobby_visible and not tangible_room:
                print("[L0] hitch 退出事务已看到大厅，但尚未取得 action 后 fresh 观察，零输入等待")
                return LoopAction.Continue
            attempted_at = getattr(self, "_hitch_floor_exit_attempted_at", None)
            exit_clicks = int(getattr(self, "_hitch_floor_exit_clicks", 0) or 0)
            if (
                tangible_room
                and fresh_after_input
                and not getattr(self, "_hitch_floor_exit_confirmed", False)
                and attempted_at is not None
                and now - float(attempted_at) >= self._HITCH_EXIT_RETRY_S
                and 0 < exit_clicks < self._HITCH_EXIT_MAX_CLICKS
            ):
                # A fresh room frame with no confirm prompt after the retry
                # interval: the Exit click never reached KK.  Re-send the same
                # semantic control (bounded); the hard cap ends the episode.
                exit_hit = self._find_hitch_exit_button(frame)
                if exit_hit is not None and self._hitch_begin_room_exit(
                    exit_hit, now, "HitchLeaveFloorOne", self._hitch_status or "exit_retry",
                ):
                    print(f"[L0] hitch 退出点击未生效，重试第 {self._hitch_floor_exit_clicks} 次")
                    return LoopAction.Continue
            if not (lobby_visible and not tangible_room):
                print(
                    "[L0] hitch 已点击退出，等待大厅列表且无房间实体控件（零输入）: "
                    f"lobby_visible={lobby_visible}, tangible_room={tangible_room}"
                )
                return LoopAction.Continue

        if getattr(self, "_hitch_ready_timeout_pending", False):
            # P0-6 & C4：70s 超时退房进行中。
            # 1. 房主若在此期间开局：取消退出、绝不拉黑、转交游戏内流程（被动 L1 接管）
            if self._is_game_client_frame(frame):
                if self._is_in_game_hud(frame):
                    self._hitch_ready_timeout_pending = False
                    self._hitch_ready_timeout_attempts = 0
                    self._hitch_ready_timeout_deadline = None
                    print("[L0] hitch 70s 等待期间房主开局（可信局内 HUD），房间已消失，转交游戏内流程")
                    return LoopAction.Continue
                if stage_page or self._find_stage_page(frame):
                    return self._hitch_quit_misopened_stage()
                print("[L0] hitch 退房 episode 中游戏客户端帧无可信面证据，保持退房（零输入）")
                return LoopAction.Continue

            # 2. 物理证明已离房且大厅可见：拉黑房号，重置状态，回大厅找房
            lobby_visible = self._lobby_room_list_evidence(frame)
            if lobby_visible and not in_room:
                if self._hitch_pending_room_key is not None:
                    self._hitch_blacklisted_room_keys.add(self._hitch_pending_room_key)
                self._hitch_pending_room_key = None
                self._hitch_ready_timeout_pending = False
                self._hitch_ready_timeout_attempts = 0
                self._hitch_ready_timeout_deadline = None
                self._hitch_after_exit(now)
                self.set_phase(Phase.LOBBY_ROOM, "hitch ready timeout returned to lobby")
                print("[L0] hitch 70s 超时退出已确认回大厅，房间拉黑并继续找房")
                return LoopAction.Continue

            # 3. C4 修复：有界退房 episode（最多 3 次安全退出输入，>=5s 间隔，30s 截止期）
            # Prefer the semantic room Exit control.  Esc is only the fallback
            # when it cannot be located; ignored Esc presses must not strand
            # a ready guest in the room forever.
            exit_hit = self._find_hitch_exit_button(frame) if in_room else None
            if exit_hit is not None and self._hitch_begin_room_exit(
                exit_hit, now, "HitchReadyTimeoutLeave", "ready_timeout_exit_clicked",
            ):
                self._hitch_ready_timeout_pending = False
                self._hitch_ready_timeout_attempts = 0
                self._hitch_ready_timeout_deadline = None
                print("[L0] hitch ready timeout: clicked room exit, awaiting explicit confirmation")
                return LoopAction.Continue

            deadline = getattr(self, "_hitch_ready_timeout_deadline", None)
            attempts = getattr(self, "_hitch_ready_timeout_attempts", 0)
            if deadline is not None and now > deadline + self._HITCH_READY_TIMEOUT_GRACE_S:
                self._hitch_ready_timeout_pending = False
                return self._hitch_room_exit_blocked(
                    frame, now, "70s 超时退房截止期后仍未取得 fresh 大厅证据",
                )
            if deadline is not None and (now > deadline or attempts >= 3):
                # 尝试/截止期耗尽只撤销输入许可，不能返回 Break 结束整个长期运行。
                # 后续 fresh 大厅证据仍可自动收尾；UNKNOWN 保持零输入观察。
                print("[L0] hitch 70s 退房重试预算耗尽（3次/超时），停止发键并持续等待可信大厅证据")
                return LoopAction.Continue

            # Esc（HitchReadyTimeoutExit）只允许在 fresh 房间证据上发出：
            # in_room（窗口匹配 + room signature）或当前帧物理确认房间实体控件。
            # 未知 surface 一律零输入；预算耗尽由上方 deadline 守卫 Break 兜底。
            last = getattr(self, "_hitch_ready_timeout_leave_at", None)
            if (
                (in_room or self._is_confirmed_room_frame(frame))
                and attempts < 3
                and (last is None or now - last >= 5.0)
            ):
                self.act_key("esc", "HitchReadyTimeoutExit")
                self._hitch_ready_timeout_leave_at = now
                self._hitch_ready_timeout_attempts = attempts + 1

            print("[L0] hitch 70s 退出进行中，等待离房并回到大厅（零输入等待）")
            return LoopAction.Continue

        if in_room:
            if self._hitch_re_search and ready_state in {"ready", "cancel_ready", "start"}:
                self._hitch_re_search = False
            if self._hitch_sm.pending_join:
                self._hitch_sm.complete_join()
                self._hitch_join_origin_hwnd = None
                self._hitch_join_refresh_count = self._hitch_sm.attempts
            # 70 秒从「已点准备」起算。先进房点准备，避免因未准备被踢；
            # 准备后再记房号、观察一楼。一楼不符才退房并拉黑。
            ready_confirmed_at = getattr(self, "_hitch_ready_confirmed_at", None)
            if (
                ready_confirmed_at is not None
                and now - ready_confirmed_at >= self._HITCH_READY_WAIT_S
                and not getattr(self, "_hitch_ready_timeout_pending", False)
            ):
                self._hitch_ready_timeout_pending = True
                self._hitch_ready_timeout_leave_at = None
                self._hitch_ready_timeout_attempts = 0
                self._hitch_ready_timeout_deadline = now + 30.0
                print("[L0] hitch 房间已准备等待超过 70 秒，房主未开局，发起安全退房 episode（当帧 0 输入）")
                return LoopAction.Continue

            # Seat knowledge (our row, the floor-one occupant) is learnt from
            # every fresh room frame, including the one we Ready on.
            self._hitch_track_room_seats(frame)
            # KK offers the host no Ready; never press a Ready-looking control
            # on a page that shows us the host's seat drop-downs.
            host_view = self._hitch_self_is_host(frame)
            if ready_state == "ready" and ready_hit is not None and not host_view:
                if self.act_click(ready_hit, "HitchReady"):
                    self._hitch_pending_row_y = None
                    self._hitch_status = "已点击准备"
                    self._hitch_member_room_hwnd = frame.hwnd
                    self._hitch_note_pre_ready_rows(frame)
                    print(f"[L0] hitch 点击客人准备: ({ready_hit.screen_x}, {ready_hit.screen_y})")
                else:
                    self._hitch_sm.defer_retry(now)
                    print("[L0] hitch 准备点击被拒绝，保持房间等待")
                self.set_phase(Phase.ROOM_WAITING, "hitch guest ready")
                return LoopAction.Continue

            if (
                getattr(self, "_hitch_ready_confirmed_at", None) is None
                and ready_state != "ready"
            ):
                self._hitch_ready_confirmed_at = now
                print(
                    f"[L0] hitch 已准备，记录房间号 key={self._hitch_pending_room_key}"
                )

            seat_decision = self._hitch_room_seat_decision(frame)
            # Only the explicit seat rules may return "reject*".  UNKNOWN and
            # legacy strings are observation states with zero exit/blacklist
            # authority.
            if seat_decision.startswith("reject"):
                generation = int(getattr(self, "_capture_generation", 0) or 0)
                streak = getattr(self, "_hitch_seat_streak", None)
                if streak is None or streak[0] != seat_decision:
                    confirmations = 1
                elif streak[1] != generation:
                    confirmations = streak[2] + 1
                else:
                    confirmations = streak[2]
                self._hitch_seat_streak = (seat_decision, generation, confirmations)
                if confirmations < 2:
                    # One frame can catch KK mid-redraw (rows re-laid out as a
                    # player leaves).  A second fresh frame must agree.
                    print(f"[L0] hitch 座位规则命中({seat_decision})，等待第二张 fresh 帧复核（零输入）")
                    self.set_phase(Phase.ROOM_WAITING, "hitch seat rule reobserve")
                    return LoopAction.Continue
                exit_hit = self._find_hitch_exit_button(frame)
                if exit_hit is not None and self._hitch_begin_room_exit(
                    exit_hit, now, "HitchLeaveFloorOne", seat_decision,
                ):
                    print(
                        f"[L0] hitch 座位规则拒绝({seat_decision})，点击退出: "
                        f"({exit_hit.screen_x}, {exit_hit.screen_y})"
                    )
                else:
                    self._hitch_sm.defer_retry(now)
                    print(f"[L0] hitch 座位规则拒绝({seat_decision})，但退出按钮未确认")
                self.set_phase(Phase.ROOM_WAITING, "hitch reject by seat detector")
                return LoopAction.Continue
            self._hitch_seat_streak = None

            if ready_state in {"cancel_ready", "start"}:
                self.set_phase(Phase.ROOM_WAITING, "hitch room ready contract observed")
                print(f"[L0] hitch ROOM action={ready_state}，零输入等待开局")
                return LoopAction.Continue
            # seat/Ready 都无法判断时只 fresh reobserve，绝不因为 UNKNOWN 退出。
            self._hitch_status = f"room_reobserve:{seat_decision}:{ready_state}"
            self.set_phase(Phase.ROOM_WAITING, "hitch in room waiting host")
            print(
                "[L0] hitch ROOM/seat 证据不足，fresh reobserve（零输入）: "
                f"seat={seat_decision}, ready={ready_state}"
            )
            return LoopAction.Continue
        if self._hitch_re_search and not in_room:
            self._hitch_re_search = False
        member_room = getattr(self, "_hitch_member_room_hwnd", None)
        ready_at = getattr(self, "_hitch_ready_confirmed_at", None)
        if (
            self.phase == Phase.ROOM_WAITING
            and member_room is not None
            and frame.hwnd != member_room
            and member_room in getattr(self, "_last_l0_target_hwnds", ())
            and (ready_at is None or now - ready_at < self._HITCH_MEMBER_ROOM_HOLD_S)
        ):
            # We readied in that room and its window still exists (a skinned
            # room page, the start countdown).  Live 2026-09-12 losing its
            # classification sent the lobby flow to join another room while
            # ours was starting.  Only a verified exit, a kick prompt or the
            # room window disappearing may return us to the room list.
            self._hitch_status = "member_room_still_open"
            print("[L0] hitch 已准备的房间窗口仍在，不回大厅找房（零输入）")
            return LoopAction.Continue
        main_nav = None
        lobby_list = self._lobby_room_list_evidence(frame)
        if lobby_list:
            if getattr(self, "_hitch_nav_since", None) is not None:
                self._hitch_nav_reset()
        elif (
            not self._hitch_sm.pending_join
            and platform_modal is None
            and not self._hitch_room_like(frame)
        ):
            # Final fallback for a KK main window left on some other page
            # (profile, store, another game...): top "游戏" tab first, then the
            # 英雄三国 / 重生魔兽刷刷刷 sidebar entry.  Proven navigation also
            # gives an UNKNOWN map sub-page (e.g. 任务) back to the tab flow.
            main_nav = self._hitch_kk_main_nav(frame)
            if main_nav is not None:
                nav_action = self._tick_hitch_kk_nav(frame, main_nav, now)
                if nav_action is not None:
                    return nav_action
        if context == "UNKNOWN" and main_nav is None and not lobby_list:
            # After a join attempt an unanchored child can be a room loading
            # surface or an unrecognised platform popup.  It is never proof
            # of the browser's room-list tab, so do not turn bright row pixels
            # into a click on an avatar or any other room control.
            self._hitch_status = "unknown_surface_no_lobby_input"
            print("[L0] hitch UNKNOWN 未获大厅/房间/弹窗实体证据，零输入等待")
            return LoopAction.Continue
        if self._hitch_sm.can_confirm_lobby_home(now, self._hitch_lobby_home_visible(frame)):
            self._hitch_sm.confirm_lobby_home()
            self._hitch_status = "大厅主页"
            print("[L0] hitch unmatched 后置确认大厅主页")
            self.set_phase(Phase.LOBBY_ROOM, "hitch 大厅主页")
            return LoopAction.Continue

        # The lobby search operation begins at the room-list tab, not at the
        # search box: acquiring the tab, locating the control, typing and
        # proving the prefix are stages of one bounded operation, so they
        # share one budget.  Arming the clock here — rather than inside
        # HitchSearchSM.tick(), which sits behind every early return in both
        # stages — is what makes those waits terminate instead of parking
        # forever on zero input.
        self._hitch_sm.begin_search_window(now)

        # 1. 检查是否在房间列表中，若在地图详情等其他 Tab，点击「房间列表 99+」Tab 切换
        if not self._lobby_room_list_evidence(frame):
            action = self._tick_hitch_room_list_tab(frame, now)
        else:
            action = self._tick_hitch_search(frame, now)
        if action is not None:
            return action

        # 3. 扫描房间列表寻找可加入的房间（非 4/4 且 非 游戏中）
        joinable_hit = None
        if self._hitch_refresh_required:
            # Failed joins and rejected in-room seats make the visible list
            # stale.  Do not inspect or join another row before one real refresh.
            decision = self._hitch_sm.tick(
                now=now,
                matched=False,
                ocr_text="",
                prefix_ok=True,
                in_room=False,
            )
        else:
            prefix_ok = self._hitch_prefix_ok(frame)
            joinable_hit = self._find_hitch_joinable_row(frame) if prefix_ok else None
            decision = self._hitch_sm.tick(
                now=now,
                matched=joinable_hit is not None,
                ocr_text="",
                prefix_ok=prefix_ok,
                in_room=in_room,
            )
        if decision.action == HitchAction.JOIN:
            hit = joinable_hit
            if hit is not None:
                clicked = bool(self.act_double_click(hit, "HitchJoin"))
                if clicked:
                    self._hitch_sm.note_join_click(now)
                    self._hitch_join_origin_hwnd = frame.hwnd
                    self._hitch_join_preexisting_hwnds = frozenset(
                        getattr(self, "_last_l0_target_hwnds", ())
                    )
                    self._hitch_pending_row_y = hit.y
                    self._hitch_pending_room_key = self._hitch_room_number_key(frame, hit.y)
                    self._hitch_search_actions.append("join")
                    self._hitch_status = "search"
                    print(
                        f"[L0] hitch 发现可加入房间，点击进入: ({hit.screen_x}, {hit.screen_y})"
                        f" key={self._hitch_pending_room_key}"
                    )
                else:
                    self._hitch_sm.defer_retry(now)
                    print("[L0] hitch 进房点击被拒绝，等待 CD 后重试")
                self.set_phase(Phase.LOBBY_ROOM, "hitch join")
                return LoopAction.Continue

        if decision.action == HitchAction.REFRESH:
            hit = self._hitch_action_hit(frame, HitchAction.REFRESH)
            if hit is None:
                self._hitch_sm.defer_retry(now)
                print("[L0] hitch REFRESH 无可信刷新位置，等待 CD 后重试")
                self.set_phase(Phase.LOBBY_ROOM, "hitch search observe")
                return LoopAction.Continue
            clicked = bool(self.act_click(hit, "HitchRefresh"))
            if clicked:
                rotated = self._hitch_sm.note_refresh(now)
                if rotated:
                    self._hitch_search = None
                    print(f"[L0] hitch 连续刷新未命中，自动轮换搜索词 -> {self._hitch_sm.prefix}")
                self._hitch_refresh_required = False
                self._hitch_rejected_row_ys.clear()
                self._hitch_pending_row_y = None
                self._hitch_search_actions.append("refresh")
                self._hitch_join_refresh_count = self._hitch_sm.attempts
                self._hitch_status = "search"
                print(
                    f"[L0] hitch refresh attempt={self._hitch_sm.attempts}/"
                    f"{self._hitch_sm.join_limit} search={self._hitch_sm.prefix}"
                )
            else:
                self._hitch_sm.defer_retry(now)
                print("[L0] hitch 刷新点击被拒绝，等待 CD 后重试")
            self.set_phase(Phase.LOBBY_ROOM, "hitch refresh")
            return LoopAction.Continue
        if decision.action == HitchAction.GO_HOME:
            hit = self._hitch_action_hit(frame, HitchAction.GO_HOME)
            clicked = False
            if hit is not None:
                clicked = bool(self.act_click(hit, "HitchGoHome"))
            if clicked:
                self._hitch_sm.note_go_home(now)
                print("[L0] hitch GO_HOME 已点击，等待大厅页证据（本 tick 不改写大厅主页）")
            else:
                # GO_HOME is only decided once the operation is exhausted, so
                # an unreachable anchor here would otherwise re-decide the same
                # dead action every tick.  Back off instead of spinning; this
                # sends nothing and a later wake retries from scratch.
                self._hitch_sm.enter_sleep_retry(now)
                self._hitch_status = "休眠重试"
                print("[L0] hitch GO_HOME 无导航锚点，转入有界休眠重试（零输入）")
            self.set_phase(Phase.LOBBY_ROOM, "hitch go_home")
            return LoopAction.Continue
        if decision.action == HitchAction.SLEEP:
            self._hitch_status = "休眠重试"
            print("[L0] hitch 休眠重试")
            self.set_phase(Phase.LOBBY_ROOM, "hitch 休眠重试")
            return LoopAction.Continue
        if decision.action == HitchAction.RESET:
            return self._hitch_reset_lobby(decision.reason, now)
        self.set_phase(Phase.LOBBY_ROOM, "hitch search")
        return LoopAction.Continue

    @staticmethod
    def _create_room_candidate_payload(hit: MatchResult | None) -> dict | None:
        if hit is None:
            return None
        return {
            "name": hit.name,
            "score": round(hit.score, 3),
            "bbox": [hit.x, hit.y, hit.w, hit.h],
            "click_point": [hit.screen_x, hit.screen_y],
        }

    def _trace_create_room_control(
        self,
        state: str,
        *,
        candidate: MatchResult | None = None,
        click_ok: bool | None = None,
        post_confirm: bool | None = None,
        now: float | None = None,
    ) -> None:
        """Record the bounded L0 create-room request without granting input authority."""
        pending_age = None
        if self._create_room_pending_since is not None:
            pending_age = round(max(0.0, (now or time.time()) - self._create_room_pending_since), 3)
        self._trace_controls.append(
            {
                "control": "create_room",
                "state": state,
                "candidate": (
                    self._create_room_candidate_payload(candidate)
                    if candidate is not None
                    else self._create_room_last_candidate
                ),
                "click_ok": click_ok,
                "post_confirm": post_confirm,
                "pending_age": pending_age,
                "attempt": self._create_room_attempts,
            }
        )

    def _clear_create_room_request(self) -> None:
        self._create_room_pending_since = None
        self._create_room_next_observe_at = None
        self._create_room_flow_deadline = None
        self._create_room_attempts = 0
        self._create_room_opened_ok = False
        self._create_room_last_candidate = None

    def _request_create_room(self, candidate: MatchResult, now: float) -> LoopAction:
        """Request the create-room dialog and keep aligning to observed state.

        Input acceptance is not dialog confirmation.  A successful click opens
        a four-second observation window; if the dedicated confirmation anchor
        is still absent afterwards, PLATFORM_MAP re-validates the exact
        create-room template and may retry.  Only the macro phase deadline can
        terminate this recoverable loop.
        """
        self._create_room_last_candidate = self._create_room_candidate_payload(candidate)

        if self.settings.dry_run:
            self.act_click(candidate, "CreateRoom-open")
            self._trace_create_room_control(
                "LEARN_OBSERVE",
                candidate=candidate,
                click_ok=False,
                now=now,
            )
            print(
                f"[L0] 学习模式：记录「创建房间」@{candidate.center} "
                "（不点击、不等待弹窗）"
            )
            append_learning_observation(
                {
                    "panel_kind": "l0",
                    "event": "create_room_intent",
                    "candidate": self._create_room_last_candidate,
                    "decision": {"action": "WOULD_CLICK", "reason": "CreateRoom-open"},
                    "phase": self.phase.name,
                    "context": self._context_cache_value,
                }
            )
            self._create_room_pending_since = None
            self._create_room_next_observe_at = now + max(
                2.0, float(self.settings.ui_action_interval_s)
            )
            return LoopAction.Continue

        if self._create_room_flow_deadline is None:
            self._create_room_flow_deadline = now + self._l0_transition_timeout()
        if now >= self._create_room_flow_deadline:
            self._trace_create_room_control("TIMEOUT", post_confirm=False, now=now)
            print("[L0] 创房状态对齐超过宏观期限，Fail-Closed")
            self.set_phase(Phase.ERROR, "create dialog alignment timeout")
            self.stop()
            return LoopAction.Break

        self._create_room_attempts += 1  # telemetry only; not a stop condition
        clicked = self.act_click(candidate, "CreateRoom-open")
        self._trace_create_room_control(
            "OPEN_REQUESTED" if clicked else "CLICK_FAILED",
            candidate=candidate,
            click_ok=clicked,
            now=now,
        )
        self._create_room_opened_ok = False
        if clicked:
            self._create_room_pending_since = now
            self._create_room_next_observe_at = now + self._CREATE_ROOM_CONFIRM_WINDOW_S
        else:
            self._create_room_pending_since = None
            self._create_room_next_observe_at = now + max(
                0.5, float(self.settings.ui_action_interval_s)
            )
        return LoopAction.Continue

    def _find_room_start(self, frame: Frame) -> MatchResult | None:
        return self.find_scene(frame, "room_start")

    def _find_stage_start(self, frame: Frame) -> MatchResult | None:
        hit = self.find_scene(frame, "stage_start", threshold=self._STAGE_START_THRESHOLD)
        if hit is None and (self._stage_selected or self._find_stage_page(frame)):
            # 1600x900 开始游戏 plate (1012,784)-(1168,850)。金按钮模板经常 miss。
            x = int(frame.width * 1090 / 1600.0)
            y = int(frame.height * 817 / 900.0)
            hit = MatchResult(
                "stage_start_fallback",
                1.0,
                x,
                y,
                80,
                40,
                frame.left + x,
                frame.top + y,
            )
            print(f"[L0] 开始游戏模板未命中，按底栏位置点击 @ ({x}, {y})")
        if hit is not None and hit.name == "stage_action_buttons":
            # 组合图（扫荡+开始游戏）整框中心落在两按钮之间；点击点取右半
            # （开始游戏）区域中心：1600x900 实测开始游戏文字中心在组合图
            # (0.71w, 0.65h)，取 (0.75w, 0.65h) 落在按钮 plate 内且避开
            # 底部票数徽标（y>0.73h）。
            dx = int(hit.w * 0.25)
            dy = int(hit.h * 0.15)
            hit.x += dx
            hit.y += dy
            hit.screen_x += dx
            hit.screen_y += dy
        return hit

    def _visible_stage_rows(self, frame: Frame) -> list:
        """证据级 memo 的选关行解析（无 matchTemplate；numpy 字形比对）。"""
        return self._memo(("stage_rows", round(self._ui_scale, 3)), frame, lambda: visible_stage_rows(frame, self.images))

    def _is_game_client_frame(self, frame: Frame) -> bool:
        return classify_window_role(getattr(frame, "window_title", None)) == WindowRole.GAME

    def _find_stage_page(self, frame: Frame) -> bool:
        key = ("stage_page",)

        def compute() -> bool:
            title = (frame.window_title or "").lower()
            # 明确属于 KK 平台窗口、且不是已知 game-client title 时，在 _visible_stage_rows 之前拒绝
            if title and any(kw in title for kw in ("kk", "对战平台", "platform")) and not self._is_game_client_frame(frame):
                return False
            if self._visible_stage_rows(frame):
                return True
            # The numbered-row parser above is the preferred detector.  The
            # legacy image fallback is only meaningful on the actual game window;
            # scanning it on a KK map page is both slow and prone to false hits.
            title = frame.window_title.lower()
            game_keywords = [keyword for keyword in L1_WINDOW_KEYWORDS if keyword.lower() != "kk"]
            if not title or not any(keyword.lower() in title for keyword in game_keywords):
                return False
            start = self.find_scene(frame, "stage_start", threshold=self._STAGE_START_THRESHOLD)
            if start is not None:
                return True
            names = [name for name in self.templates("stage_page") if Path(name).stem not in ("stage", "toHero", "HeroChallenge")]
            if not names:
                return False
            # N2.4：关卡编号列实测 x≈0.655（stage_select 1600x900 实测 x=1048），
            # 只扫编号列 ROI，不再全帧。
            # P1-1（LOBBY_AUDIT P2）：遗留模板 fallback 复用 L0 绝对尺度优先序
            # （stage_page 在 _L0_GATE_SCENES；find_scene 的 names 过滤语义不适用
            # ——stage/toHero/HeroChallenge 必须排除），非 1.0 窗口不再先扫 ui 邻域。
            hit = self.find(
                frame, names,
                scales=self._l0_scales(),
                roi=self._STAGE_ROWS_ROI,
                early_stop=True,
                mode="stage_page:l0",
            )
            # stage.png is the large map card; toHero/HeroChallenge are hero icons.
            # They are not sufficient to prove that the numbered stage list is open.
            return bool(
                hit
                and hit.name not in ("stage", "toHero", "HeroChallenge")
                and hit.x >= int(frame.width * 0.55)
            )

        return bool(self._memo(key, frame, compute))
    def _find_map_create_room(self, frame: Frame) -> MatchResult | None:
        # The map page renders both "create room" and "quick join" as blue
        # actions.  Colour and relative position are therefore not click
        # authority.  Only the dedicated create-room template may authorize
        # this input; a transient template miss must stay observe-only.
        return self.find_scene(frame, "map_create_room")

    def _find_create_confirm(self, frame: Frame) -> MatchResult | None:
        # 严格语义模板匹配授权：仅限 create_room_confirm 场景模板匹配。
        # 移除任何颜色/结构兜底对点击授权的输出（颜色兜底不得产生 MatchResult 点击权限）。
        return self.find_scene(frame, "create_room_confirm")

    def _find_stage_target(self, frame: Frame) -> MatchResult | None:
        if self.settings.stage_targets:
            return find_stage_labels(frame, self.images, self.settings.stage_targets)
        return find_stage_in_range(
            frame,
            self.images,
            self.settings.stage1,
            self.settings.stage2,
        )

    def _stage_target_has_consistent_neighbor(self, frame: Frame, target: MatchResult) -> bool:
        """Reject an isolated or transient OCR row before it becomes a click."""
        rows = self._visible_stage_rows(frame)
        selected = next(
            (
                row
                for row in rows
                if abs(row.center_x - target.x) <= 3 and abs(row.center_y - target.y) <= 3
            ),
            None,
        )
        if selected is None:
            return False
        for other in rows:
            dy = other.center_y - selected.center_y
            if not 25 <= abs(dy) <= 80:
                continue
            expected_step = 1 if dy > 0 else -1
            if (
                other.stage_id.chapter == selected.stage_id.chapter
                and other.stage_id.index - selected.stage_id.index == expected_step
            ):
                return True
        return False

    def _fill_room_dialog(self, frame: Frame, confirm: MatchResult) -> bool:
        if not self.settings.room_name and not self.settings.room_password:
            return True
        boxes = find_input_boxes(frame, anchor=confirm)
        if len(boxes) < 2:
            print("[L0] 建房弹窗未安全识别到房间名/密码输入框，拒绝盲填")
            return False

        # One field operation per call/tick.  The caller only sets
        # _room_dialog_filled after this sequence completes, so confirmation
        # is necessarily dispatched on a later tick as well.
        steps: list[tuple[MatchResult, str, str | None]] = []
        if self.settings.room_name:
            steps.extend((
                (boxes[0], "CreateRoom-focus-name", None),
                (boxes[0], "CreateRoom-select-name", "hotkey"),
                (boxes[0], "CreateRoom-paste-name", self.settings.room_name),
            ))
        if self.settings.room_password:
            steps.extend((
                (boxes[1], "CreateRoom-focus-pwd", None),
                (boxes[1], "CreateRoom-select-pwd", "hotkey"),
                (boxes[1], "CreateRoom-paste-pwd", self.settings.room_password),
            ))

        step = int(getattr(self, "_room_form_step", 0) or 0)
        if step >= len(steps):
            return True
        hit, reason, payload = steps[step]
        if payload == "hotkey":
            ok = self.act_hotkey("ctrl", "a", reason=reason)
        elif payload is None:
            ok = self.act_click(hit, reason)
        else:
            ok = self.act_paste_text(payload, reason)
        if not ok:
            print(f"[L0] 建房弹窗步骤失败/取消: {reason}")
            return False
        self._room_form_step = step + 1
        if self._room_form_step < len(steps):
            return False
        print("[L0] 建房弹窗已分阶段填写房间名/密码")
        return True

    def _l0_transition_timeout(self) -> float:
        """Macro timeout for recoverable L0 alignment episodes."""
        try:
            configured = float(self.settings.query_timeout)
        except (TypeError, ValueError):
            configured = self._L0_TRANSITION_TIMEOUT_S
        return max(30.0, min(configured, self._L0_TRANSITION_TIMEOUT_S))

    def _stage_budget(self, now: float) -> AttemptBudget:
        if self._stage_attempt_budget is None:
            self._stage_attempt_budget = AttemptBudget(
                started_at=now,
                hard_deadline=now + self._l0_transition_timeout(),
                actions_left=self._STAGE_ACTION_LIMIT,
                retries_left=self._STAGE_RETRY_LIMIT,
            )
        return self._stage_attempt_budget

    def _fail_stage_budget(self, reason: str) -> LoopAction:
        print(f"[L0] 选关尝试预算耗尽（{reason}），Fail-Closed 停止运行")
        self.set_phase(Phase.ERROR, f"stage attempt budget exhausted: {reason}")
        self.stop()
        return LoopAction.Break

    def _stage_budget_guard(self, now: float) -> LoopAction | None:
        budget = self._stage_budget(now)
        if budget.exhausted(now):
            reason = (
                "hard deadline" if now >= budget.hard_deadline
                else "actions" if budget.actions_left <= 0
                else "challenge retries"
            )
            return self._fail_stage_budget(reason)
        if self._stage_select_attempts >= self._STAGE_SELECT_LIMIT:
            return self._fail_stage_budget("stage select attempts")
        return None

    def _consume_stage_action(self, now: float, action: str) -> LoopAction | None:
        if not self._stage_budget(now).consume_action(now):
            return self._fail_stage_budget(action)
        return None


    def _action_timed_out(self) -> bool:
        return self._room_action_deadline is not None and time.time() >= self._room_action_deadline

    def _challenge_start_timeout(self, stage_page: bool) -> LoopAction:
        """Re-align a failed stage start while the stage page is still proven."""
        if self._challenge_start_source == "hero":
            print("[L0] 英雄挑战开始超时（无局内锚点），停止运行")
            self.set_phase(Phase.ERROR, "hero challenge start timeout")
            self.stop()
            return LoopAction.Break
        if stage_page:
            now = time.time()
            if not self._stage_budget(now).consume_retry(now):
                return self._fail_stage_budget("challenge retries")
            self._challenge_start_attempts += 1
            print(
                f"[L0] 选关后未进局，仍在选关页；回到状态对齐重选 "
                f"(retry {self._challenge_start_attempts}/{self._STAGE_RETRY_LIMIT})"
            )
            self._stage_selected = False
            self._stage_target_name = None
            self.set_phase(Phase.STAGE_SELECT, "challenge start realign")
            return LoopAction.Continue
        print("[L0] 选关后超时且选关页/英雄入口均消失（页面异变），停止运行")
        self.set_phase(Phase.ERROR, "challenge start page mutation")
        self.stop()
        return LoopAction.Break
    def _startup_state(self, frame: Frame) -> str:
        """Classify the currently captured taskbar window before L0 actions."""
        if self._is_game_client_frame(frame):
            # P0-3：战后界面（存档/传家宝/NPC 广场）先于选关页判定——这些面板
            # 会携带类选关页锚点，先查选关页会把战后入口误抢占成 STAGE_SELECT。
            post_game = self._post_game_state(frame)
            if post_game in {"ARCHIVE_PANEL", "HEIRLOOM_DIALOG", "NPC_HUB", "POST_VICTORY"}:
                return post_game
            if post_game == "PAUSED":
                return "PAUSED"
            if self._find_stage_page(frame):
                return "STAGE_SELECT"
            # C1 修复：禁止以 std > 8 弱视觉噪声直接授权 IN_GAME。
            # 必须具有可信的局内 HUD 证据（_is_in_game_hud），才允许确认 IN_GAME；
            # 其它无法证明任何已知业务界面的游戏客户端帧统一归为 UNKNOWN（零输入）。
            if self._is_in_game_hud(frame):
                return "IN_GAME"
            return "UNKNOWN"
        if self._find_stage_page(frame):
            return "STAGE_SELECT"
        if self._find_room_start(frame):
            return "ROOM_WAITING"
        if self._find_create_confirm(frame):
            return "CREATE_ROOM"
        if self._auto_room_enabled() and self._find_map_create_room(frame):
            return "PLATFORM_MAP"
        return "UNKNOWN"


    def _tick_leave_old_room(self, frame: Frame, room_start, now: float) -> LoopAction | None:
        """G0 P0 contract #7：同房返回证明完成后离开旧房的最小 owner。

        复用既有语义控件（GO_HOME: lobby_home/lobby_back/room_exit_btn 与
        房间退出按钮），只发 request；绝不通过尺寸或 click success 宣称已
        离房。只有 fresh room-list authority（既有 ``_lobby_room_list_evidence``）
        成立才放行进 PLATFORM_MAP。预算 bounded：超时 → Fail-Closed 保持
        手动房等待语义（不创建新房、不猜测）。

        Returns None to continue normal L0 flow (episode not started).
        """
        if not self._room_leave_pending:
            return None
        # KK moves "是否确认退出房间?" into a small same-title child HWND.
        # _capture_best probes that child while this transaction is pending;
        # confirm it before asking any page classifier to reason about it.
        exit_confirm = self._find_verified_room_exit_confirm(frame)
        if exit_confirm is not None:
            if now >= self._room_leave_next_at:
                if self.act_click(exit_confirm, "LeaveOldRoom-confirm"):
                    self._room_leave_attempts += 1
                self._room_leave_next_at = now + 3.0
            print("[med] 确认退出旧房，等待 fresh room-list authority（零输入观察）")
            return LoopAction.Continue
        # fresh room-list authority：真实房间列表证据成立才算已离房。
        if self._lobby_room_list_evidence(frame) and room_start is None:
            self._room_leave_pending = False
            self._room_leave_attempts = 0
            self.set_phase(Phase.PLATFORM_MAP, "left old room; create next")
            self._room_action_deadline = None
            return LoopAction.Continue
        if self._action_timed_out():
            print("[med] 离开旧房超时（fresh room-list 未成立），回大厅保持手动房等待，不创建新房")
            self._room_leave_pending = False
            # 必须清掉过期 deadline：成功分支同样清理，否则残留会污染后续
            # _action_timed_out() 消费者（LOBBY_ROOM 阶段的正常有界等待）。
            self._room_action_deadline = None
            self.set_phase(Phase.LOBBY_ROOM, "leave old room timeout; manual room wait")
            return LoopAction.Continue
        if now >= self._room_leave_next_at:
            # 只发一次 request，然后等待 fresh 证据；click success 不构成离房。
            hit = self._hitch_action_hit(frame, HitchAction.GO_HOME)
            # A completed/disabled room shows ``游戏中`` instead of an
            # actionable room-start button. It is still a real room and the
            # handoff must use its semantic Exit control.
            if hit is None and (room_start is not None or self._is_confirmed_room_frame(frame)):
                hit = self._find_hitch_exit_button(frame)
            if hit is not None:
                if self.act_click(hit, "LeaveOldRoom"):
                    self._room_leave_attempts += 1
                self._room_leave_next_at = now + 3.0
            else:
                self._room_leave_next_at = now + 1.0
        print("[med] 离开旧房等待 fresh room-list authority（零输入观察）")
        return LoopAction.Continue



    def _tick_l0(self, frame: Frame) -> LoopAction:
        """Handle map → create dialog → room → stage without guessing clicks."""
        # 机会性校正挑战券读数：只有选关页/游戏大厅看得见这个计数，蹭车大部分
        # 时间待在 KK 房间列表里，所以读不到是常态，由死算兜着（见
        # _observe_ticket_balance）。内部有 5s 间隔闸，不会每 tick 都 OCR。
        self._observe_ticket_balance(frame)
        if not getattr(self, "_awaiting_room_return", False) and self.phase in {
            Phase.BOOT,
            Phase.PREPARE,
            Phase.LOBBY_ROOM,
            Phase.WAIT_UI,
            Phase.ROOM_WAITING,
        }:
            startup = self._startup_state(frame)
            if startup in {"ARCHIVE_PANEL", "HEIRLOOM_DIALOG", "NPC_HUB", "POST_VICTORY"}:
                self.set_phase(Phase.MAIN_LINE, f"startup reconcile to {startup}")
                self._post_game_pending = True
                self._post_game_reconciled = True
                if startup == "ARCHIVE_PANEL":
                    self._post_game_route = "archive"
                elif startup == "HEIRLOOM_DIALOG":
                    self._post_game_route = "heirloom_active"
                elif startup == "NPC_HUB":
                    self._post_game_route = "team_wait_exit" if self._team_mode_enabled() else "npc_hub"
                return LoopAction.Continue
            if startup == "PAUSED":
                self.set_phase(Phase.MAIN_LINE, "startup found paused game")
                return LoopAction.Continue
            if startup == "IN_GAME":
                # P0-1：ROOM_WAITING 下只有可信局内 HUD 才允许接管到 MAIN_LINE；
                # 其余（UNKNOWN L1 帧/静态黑帧）零输入等待，不武断进局。
                if self.phase == Phase.ROOM_WAITING and not self._is_in_game_hud(frame):
                    print("[L0] ROOM_WAITING 游戏帧缺少可信局内 HUD，零输入等待状态对齐")
                    return LoopAction.Continue
                if self.phase in (Phase.ROOM_WAITING, Phase.LOBBY_ROOM) and self._hitch_arm_opening_pressure(
                    "room -> in-game HUD"
                ):
                    # The natural room -> round entry: the first fresh in-game
                    # HUD a readied guest sees.  _tick_lobby_hitch's own arming
                    # branch is never reached once MAIN_LINE is set here, and
                    # an "existing game" note would skip the new-round init.
                    self.set_phase(Phase.MAIN_LINE, "hitch natural round entry")
                    return LoopAction.Continue
                self.set_phase(Phase.MAIN_LINE, "startup found existing game")
                return LoopAction.Continue

        # The hero modal has its own exact guards.  Skipping the generic L0
        # classifier here also avoids several full-screen template scans while
        # waiting for one small, time-sensitive digit change.
        if self.phase == Phase.HERO_SETUP:
            return self._tick_hero_setup(frame)
        context = self._detect_context(frame, "l0")
        print(f"[med] decision context={context} phase={self.phase.name}")
        # Lobby rows can contain generic room-looking fragments. In hitch mode,
        # a positive room-list anchor outranks the generic room_start matcher.
        if (
            self._hitch_enabled()
            and context == "ROOM_WAITING"
            and self._lobby_room_list_evidence(frame)
            and not getattr(self, "_hitch_floor_exit_pending", False)
        ):
            context = "LOBBY_ROOM"
            stage_page = False
            room_start = None

        else:
            # 选关页底部也会误匹配通用 room_start；沿用分类器的优先级，
            # 先确认编号关卡页，再查房间开始按钮。
            stage_page = context == "STAGE_SELECT"
            room_start = None if stage_page else self._find_room_start(frame)

        if self._room_leave_pending:
            leave = self._tick_leave_old_room(frame, room_start, now=time.time())
            if leave is not None:
                return leave
        if self._awaiting_room_return and self._hitch_enabled():
            self._awaiting_room_return = False
            self._hitch_re_search = True
            # When the game window disappears before the room window returns,
            # the generic return-proof branch increments game_count itself.
            # Route the configured final round through the same finish logic;
            # otherwise a 5th round falls back to ROOM_WAITING and waits for a
            # host forever, never arming the archaeology handoff.
            if self.settings.cycle_num > 0 and self.game_count >= self.settings.cycle_num:
                return self._finish_hitch_round(
                    time.time(), "same room verified; hitch cycle complete", already_counted=True
                )

        if self._awaiting_room_return:
            if room_start:
                self._awaiting_room_return = False
                self.game_count += 1
                print(f"[med] 已返回原 KK 房间 count={self.game_count} → 准备下一局")
                # S0 ⑥：连续不成功局熔断 —— streak 达上限（完成当前安全回房后）
                # 转 ERROR 停止，不得尝试下一局。
                if self._failure_streak >= self.settings.failure_streak_limit:
                    print(f"[med] 连续 {self._failure_streak} 局失败/超时/断线，Fail-Closed 停止运行")
                    self.set_phase(Phase.ERROR, "failure streak limit reached")
                    self.stop()
                    return LoopAction.Break
                # S0 ⑥：cycle_num>0 且已完成指定局数。
                if self.settings.cycle_num > 0 and self.game_count >= self.settings.cycle_num:
                    if getattr(self.settings, "auto_archaeology", True) and not self._hitch_enabled():
                        # G0 P0 contract #8：cycle 完成 + auto_archaeology →
                        # 交由既有选关路由进入考古模式（request/confirm），
                        # 不立即停止，保留正常房间/生命周期证据链。
                        print("[med] cycle 完成 + auto_archaeology，经既有选关路由进入考古模式")
                        self._archaeology_handoff_pending = True
                        self.set_phase(Phase.ROOM_WAITING, "cycle complete; archaeology via stage select")
                        self._room_action_deadline = time.time() + self.settings.query_timeout
                        return LoopAction.Continue
                    print(f"[med] 已完成 cycle_num={self.settings.cycle_num} 局，转 COMPLETE 停止（不点下一局开始）")
                    self.set_phase(Phase.COMPLETE, "cycle_num reached")
                    self.stop()
                    return LoopAction.Break
                if (
                    self._auto_room_enabled()
                    and getattr(self.settings, "new_room_every_times", False)
                    and not self._hitch_enabled()
                    and not self._follow_enabled()
                ):
                    # G0 P0 contract #7 (only with 每局新建房间)：先用既有语义控件
                    # （lobby_home/lobby_back/room_exit_btn）离开旧房，fresh
                    # room-list authority 后才进 PLATFORM_MAP 创建下一房。
                    # Owner 2026-09-14: otherwise the solo player stays host in
                    # the same room and just presses 开始游戏 — the leave click
                    # moved the host from seat 1 to row 2 (live f0662→f0664).
                    self._room_leave_pending = True
                    self._room_leave_next_at = 0.0
                    self._room_action_deadline = time.time() + min(self.settings.query_timeout, 30)
                    self.set_phase(Phase.PREPARE, "same room verified; leaving old room")
                    return LoopAction.Continue
                self.set_phase(Phase.ROOM_WAITING, "same room verified")
                self._room_action_deadline = time.time() + self.settings.query_timeout
                return LoopAction.Continue
            if self._action_timed_out():
                print("[med] 退出游戏后未验证回到原 KK 房间，停止而不是重新建房")
                self.set_phase(Phase.ERROR, "same room return timeout")
                self.stop()
                return LoopAction.Break
            print("[med] 等待返回原 KK 房间（零动作，不重建房间）")
            return LoopAction.Continue

        if context in ("MAIN_LINE", "IN_GAME") and self.phase != Phase.STAGE_STARTING:
            # STAGE_STARTING 的进局判定归 startChallenge 子状态机（锚点连续 2 帧
            # 确认），不走全局"已在局内"捷径
            print("[L1] 开始主线 / phase=MAIN_LINE")
            self.set_phase(Phase.MAIN_LINE, "already in game")
            return LoopAction.Continue

        if self._hitch_enabled():
            return self._tick_lobby_hitch(
                frame, context, room_start=room_start, stage_page=stage_page
            )

        if self._follow_enabled():
            return self._tick_follow_team(
                frame, context, room_start=room_start, stage_page=stage_page
            )

        if self.phase in (Phase.BOOT, Phase.WAIT_EXIT, Phase.PREPARE, Phase.LOBBY_ROOM, Phase.WAIT_UI):
            if stage_page:
                self.set_phase(Phase.STAGE_SELECT, "stage page detected")
                return LoopAction.Continue
            if room_start:
                self.set_phase(Phase.ROOM_WAITING, "room page detected")
                return LoopAction.Continue
            if context == "CREATE_ROOM":
                self.set_phase(Phase.CREATE_ROOM, "create dialog detected")
                return LoopAction.Continue
            if self._is_game_client_frame(frame):
                self.set_phase(Phase.STAGE_SELECT, "game client takeover")
                print("[L0] 游戏窗口已打开，从当前页接手选关")
                return LoopAction.Continue
            if self._auto_room_enabled():
                self.set_phase(Phase.PLATFORM_MAP, "auto create room enabled")
                return LoopAction.Continue
            self.set_phase(Phase.LOBBY_ROOM, "waiting for manual room")
            print("[L0] 未找到房间开始按钮；未启用自动建房，不执行 F1/蓝色全局兜底")
            return LoopAction.Continue

        if self.phase == Phase.PLATFORM_MAP:
            if stage_page:
                self._clear_create_room_request()
                self.set_phase(Phase.STAGE_SELECT, "stage page detected")
                return LoopAction.Continue
            if room_start and self._create_room_pending_since is None:
                self._clear_create_room_request()
                self.set_phase(Phase.ROOM_WAITING, "room already exists")
                return LoopAction.Continue
            now = time.time()
            confirm = self._find_create_confirm(frame)
            if confirm:
                self._trace_create_room_control(
                    "CONFIRMED",
                    post_confirm=self._create_room_pending_since is not None,
                    now=now,
                )
                self._clear_create_room_request()
                self.set_phase(Phase.CREATE_ROOM, "create dialog detected")
                return LoopAction.Continue

            if self._create_room_pending_since is not None:
                if (
                    self._create_room_next_observe_at is not None
                    and now < self._create_room_next_observe_at
                ):
                    print("[L0] 创房请求等待专用弹窗确认（零动作）")
                    return LoopAction.Continue
                # Four seconds elapsed without the dedicated dialog anchor.
                # Re-align to the page and re-validate the semantic create
                # template; never promote input acceptance to opened state.
                self._trace_create_room_control(
                    "CONFIRM_TIMEOUT", post_confirm=False, now=now
                )
                print("[L0] 创房弹窗 4s 未出现，回到地图状态对齐并重新识别")
                self._create_room_pending_since = None
                self._create_room_next_observe_at = None
                self._create_room_opened_ok = False
            elif (
                self._create_room_next_observe_at is not None
                and now < self._create_room_next_observe_at
            ):
                if self.settings.dry_run:
                    print("[L0] 学习模式观察节流（零动作）")
                else:
                    print("[L0] 创房点击失败，等待输入节流窗口（零动作）")
                return LoopAction.Continue

            if (
                self._create_room_flow_deadline is not None
                and now >= self._create_room_flow_deadline
            ):
                self._trace_create_room_control("TIMEOUT", post_confirm=False, now=now)
                print("[L0] 创房状态对齐超过宏观期限，Fail-Closed")
                self.set_phase(Phase.ERROR, "create dialog alignment timeout")
                self.stop()
                return LoopAction.Break

            create = self._find_map_create_room(frame)
            if create:
                print(f"[L0] 检测到创建房间按钮 {create.name} @ {create.center}")
                return self._request_create_room(create, now)
            if self._action_timed_out():
                print("[L0] 地图页超时仍未安全识别创建房间按钮，停止而不是点击快速加入")
                self.set_phase(Phase.ERROR, "create room button not found")
                self.stop()
                return LoopAction.Break
            print("[L0] 未找到创建房间按钮；拒绝点击快速加入/快速匹配")
            return LoopAction.Continue

        if self.phase == Phase.CREATE_ROOM:
            confirm = self._find_create_confirm(frame)
            if not confirm:
                if room_start:
                    self.set_phase(Phase.ROOM_WAITING, "dialog already closed")
                    if getattr(self, "_archaeology_handoff_pending", False):
                        self._archaeology_handoff_own_room = True
                    return LoopAction.Continue
                if self._action_timed_out():
                    print("[L0] 建房弹窗超时，回到地图页等待，不假报建房成功")
                    self.set_phase(Phase.PLATFORM_MAP, "create dialog timeout")
                else:
                    print("[L0] 等待建房弹窗确认按钮…")
                return LoopAction.Continue
            if not self._room_dialog_filled:
                if not self._fill_room_dialog(frame, confirm):
                    return LoopAction.Continue
                self._room_dialog_filled = True
                return LoopAction.Continue
            if not self.act_click(confirm, "CreateRoom-confirm"):
                return LoopAction.Continue
            self._room_action_deadline = time.time() + self.settings.query_timeout
            self.set_phase(Phase.ROOM_WAITING, "create confirmed")
            if getattr(self, "_archaeology_handoff_pending", False):
                self._archaeology_handoff_own_room = True
            return LoopAction.Continue

        if self.phase == Phase.ROOM_WAITING:
            if stage_page:
                self.set_phase(Phase.STAGE_SELECT, "stage page after room")
                return LoopAction.Continue
            if getattr(self, "_archaeology_handoff_pending", False) and not getattr(
                self, "_archaeology_handoff_own_room", False
            ):
                # G0 P0 contract #8 / Stage1 P1-1：考古 handoff 待处理且这间房
                # **不是我们自己建的**（别人的蹭车房，或离房后还没建成），绝不点
                # RoomStart 开新局（违反 S0⑥）。零输入等选关页自然出现，进入上方
                # stage_page 分支后交给考古 request/confirm 路由收敛。
                # 有界：选关页始终不出现则 Fail-Closed 停止（绝不改点房间开始/建房）。
                #
                # 20260921：本分支原先不区分房间归属，于是蹭车达标 → 离房 → 自建
                # 新房之后仍然禁止点开始，而 ROOM_WAITING 下选关页**不会**自然出现
                # （它是点了开始才有的），必然超时进 ERROR —— 实机表现为"进新房间
                # 又不开始游戏"。自建房里点开始进的是 ROOM_STARTING → STAGE_SELECT，
                # 不是直接开一局；真正开局要在选关页选关再确认，而那一步会被
                # _maybe_switch_to_archaeology 抢先改成点考古。
                if self._action_timed_out():
                    print("[L0] cycle 完成考古 handoff 超时仍未出现选关页，Fail-Closed 停止")
                    self.set_phase(Phase.ERROR, "archaeology handoff stage page timeout")
                    self.stop()
                    return LoopAction.Break
                print("[L0] cycle 完成考古 handoff：零输入等待选关页，绝不点房间开始")
                return LoopAction.Continue
            if room_start:
                print(f"[L0] 房间内点击开始 {room_start.name} score={room_start.score:.3f}")
                if not self.act_click(room_start, "RoomStart"):
                    return LoopAction.Continue
                now = time.time()
                self._room_action_attempts = 1
                self._room_start_deadline = now + self._l0_transition_timeout()
                self._room_start_next_retry_at = now + self._CREATE_ROOM_CONFIRM_WINDOW_S
                self.set_phase(Phase.ROOM_STARTING, "room start clicked")
                return LoopAction.Continue
            if self._action_timed_out():
                if self._auto_room_enabled():
                    print("[L0] 房间等待超时；返回地图页继续状态对齐")
                    self.set_phase(Phase.PLATFORM_MAP, "room wait alignment timeout")
                else:
                    print("[L0] 房间等待超时；保持手动房间等待，不猜测创建按钮")
                    self.set_phase(Phase.LOBBY_ROOM, "manual room wait timeout")
            else:
                print("[L0] 等待房间开始按钮…")
            return LoopAction.Continue

        if self.phase == Phase.ROOM_STARTING:
            if stage_page:
                self.set_phase(Phase.STAGE_SELECT, "stage page after room start")
                return LoopAction.Continue
            now = time.time()
            if self._room_start_deadline is None:
                self._room_start_deadline = now + self._l0_transition_timeout()
            if now >= self._room_start_deadline:
                print("[L0] 房间开始状态对齐超过宏观期限，回到房间等待")
                self.set_phase(Phase.ROOM_WAITING, "room start alignment timeout")
                return LoopAction.Continue
            if room_start and now >= self._room_start_next_retry_at:
                print(
                    f"[L0] 仍在房间页，按状态对齐重试开始 "
                    f"(telemetry={self._room_action_attempts + 1})"
                )
                if self.act_click(room_start, "RoomStart-retry"):
                    self._room_action_attempts += 1
                self._room_start_next_retry_at = now + self._CREATE_ROOM_CONFIRM_WINDOW_S
                return LoopAction.Continue
            print("[L0] 等待游戏窗口/选关页…")
            return LoopAction.Continue

        if self.phase == Phase.STAGE_SELECT:
            now = time.time()
            budget_result = self._stage_budget_guard(now)
            if budget_result is not None:
                return budget_result
            if not stage_page:
                if self._is_game_client_frame(frame):
                    print("[L0] 游戏窗仍在，继续对齐选关页")
                elif self._action_timed_out():
                    print("[L0] 选关页消失但未出现局内 UI，回到房间等待")
                    self.set_phase(Phase.ROOM_WAITING, "stage page disappeared")
                    return LoopAction.Continue
                else:
                    return LoopAction.Continue
            # 黄色挑战券清空 → 自动进考古模式并结束脚本
            arch_res = self._maybe_switch_to_archaeology(frame)
            if arch_res is not None:
                return arch_res
            # L0-RECOVERY（实机 20260816_204613）：客户端记忆停留在团本分页时，
            # 右侧列表没有 1-x 行，直接扫描会盲目滚动并误点未开放关卡。普通主线
            # （chapter=1，1-1~1-23）都在「旧世大陆」大区页签下——先切回再扫列表。
            wanted_id = configured_stage_id(
                self.settings.stage_targets,
                self.settings.stage1,
                self.settings.stage2,
            )
            if (
                wanted_id is not None
                and wanted_id.chapter == 1
                and now >= self._stage_scroll_cooldown_until
            ):
                old_world_tab = find_unselected_old_world_tab(frame, self.images)
                if old_world_tab is not None:
                    print(
                        f"[L0] 检测到当前不在旧世大陆，按状态对齐切换页签 "
                        f"(telemetry={self._old_world_switch_attempts + 1})"
                    )
                    budget_result = self._consume_stage_action(now, "continent page")
                    if budget_result is not None:
                        return budget_result
                    if not self.act_click(old_world_tab, "SwitchOldWorldTab"):
                        return LoopAction.Continue
                    self._old_world_switch_attempts += 1
                    self._stage_selected = False
                    self._stage_target_name = None
                    self._stage_target_position = None
                    self._stage_candidate_name = None
                    self._stage_candidate_position = None
                    self._stage_candidate_frames = 0
                    self._stage_scroll_attempts = 0
                    self._stage_scroll_cooldown_until = now + 1.0  # 给予 1.0s 充分刷新时间
                    return LoopAction.Continue
            if not self._stage_selected:
                already = selected_stage_row(frame, self.images)
                if already is not None and wanted_id is not None and already.stage_id == wanted_id:
                    print(f"[L0] 目标关卡 {wanted_id} 已高亮，跳过点选")
                    self._stage_selected = True
                    self._stage_target_name = f"stage_target_{wanted_id}"
                    self._stage_target_position = (already.center_x, already.center_y)
                    self._stage_click_cooldown_until = 0.0
            if not self._stage_selected:
                if now < self._stage_scroll_cooldown_until:
                    print("[L0] 关卡列表滚动后等待稳定…")
                    return LoopAction.Continue
                target = self._find_stage_target(frame)
                if not target:
                    # 目标不在可见列表：滚动寻找。
                    # 原版 SelectStage 语义：stage2>12 时在关卡列表 (1090,390) 向下滚轮
                    # （pyautogui 负值=向下；录屏确认 1-24+ 在列表下方）。
                    # 触发条件覆盖 stage_targets 与 stage1/stage2 范围两种配置。
                    # State alignment: while the stage page is proven and the
                    # macro deadline is alive, keep scrolling at a controlled
                    # cadence.  The counter is telemetry only.
                    x, y = stage_list_scroll_point(frame)
                    target_hwnd = self._last_frame.hwnd if self._last_frame else None
                    budget_result = self._consume_stage_action(now, "stage scroll")
                    if budget_result is not None:
                        return budget_result
                    res_scroll = self.executor.scroll(
                        x, y, -2,
                        target_hwnd=target_hwnd,
                        dry_run=self.settings.dry_run,
                    )
                    if getattr(res_scroll, "success", bool(res_scroll)):
                        self._stage_scroll_attempts += 1
                        self._stage_scroll_cooldown_until = now + 0.6
                        self._tick_input_executed = True
                        self._input_seq += 1
                        if not self.settings.dry_run:
                            self.invalidate_evidence("input")
                        self._stage_candidate_name = None
                        self._stage_candidate_position = None
                        self._stage_candidate_frames = 0
                        print(
                            f"[L0] 目标关卡不在当前列表，持续向下滚动寻找 "
                            f"(telemetry={self._stage_scroll_attempts})"
                        )
                    else:
                        print(f"[L0] 关卡列表滚动取消/失败: {res_scroll.message}")
                    return LoopAction.Continue
                if not self._stage_target_has_consistent_neighbor(frame, target):
                    self._stage_candidate_name = None
                    self._stage_candidate_position = None
                    self._stage_candidate_frames = 0
                    print("[L0] 目标关卡行缺少连续相邻关卡佐证，等待下一帧（零动作）")
                    return LoopAction.Continue
                position = (target.x, target.y)
                if self._stage_candidate_name == target.name:
                    self._stage_candidate_frames += 1
                    self._stage_candidate_position = position
                else:
                    self._stage_candidate_name = target.name
                    self._stage_candidate_position = position
                    self._stage_candidate_frames = 1
                if self._stage_candidate_frames < 2:
                    print(f"[L0] 目标关卡 {target.name} 首帧命中，等待坐标稳定复核（零动作）")
                    return LoopAction.Continue
                print(f"[L0] 选关 SelectStage {target.name} @ {target.center}")
                budget_result = self._consume_stage_action(now, "stage select")
                if budget_result is not None:
                    return budget_result
                if not self.act_click(target, "SelectStage-target"):
                    return LoopAction.Continue
                self._stage_selected = True
                self._stage_target_name = target.name
                self._stage_target_position = position
                self._stage_select_attempts += 1
                self._stage_click_cooldown_until = now + 1.5
                return LoopAction.Continue
            if now < self._stage_click_cooldown_until:
                print("[L0] 等待关卡选中状态稳定…")
                return LoopAction.Continue
            # 高亮落在别的关才重点。1-21 金边经常解析不出高亮，不能因此拒绝点开始游戏。
            highlighted = selected_stage_row(frame, self.images)
            if (
                highlighted is not None
                and wanted_id is not None
                and highlighted.stage_id != wanted_id
            ):
                print(
                    f"[L0] 高亮在 {highlighted.stage_id} 而不是目标 {wanted_id}，"
                    "重点目标行，不开始游戏"
                )
                self._stage_selected = False
                self._stage_target_name = None
                self._stage_target_position = None
                self._stage_candidate_name = None
                self._stage_candidate_position = None
                self._stage_candidate_frames = 0
                return LoopAction.Continue
            print(f"[L0] 目标关卡 {wanted_id} 已点选，点击开始游戏")
            if self.settings.auto_reputation:
                return self._begin_hero_setup(frame)
            start = self._find_stage_start(frame)
            if not start:
                print("[L0] 已选关，但未找到棕色开始游戏按钮")
                return LoopAction.Continue
            print(f"[L0] 选关后点击开始 {start.name} score={start.score:.3f}")
            budget_result = self._consume_stage_action(now, "challenge start")
            if budget_result is not None:
                return budget_result
            if not self.act_click(start, "StageStart"):
                return LoopAction.Continue
            self._room_action_attempts = 1
            self._room_action_deadline = time.time() + min(self.settings.query_timeout, 15)
            # startChallenge 子状态机初始化（进入 STAGE_STARTING）：
            # attempts 是跨回退保留的重试预算，此处不重置（超时分支 +1，>=2 时 Fail-Closed）
            self._challenge_start_state = "WAIT_TRANSITION"
            self._challenge_start_source = "stage"  # hero 弹窗开始走 HERO_SETUP，不经本分支
            self._challenge_start_deadline = time.time() + max(20, min(self.settings.query_timeout, 60))
            self._challenge_start_hud_frames = 0
            self._challenge_start_hero_modal_frames = 0
            self.set_phase(Phase.STAGE_STARTING, "stage start clicked")
            return LoopAction.Continue

        if self.phase == Phase.STAGE_STARTING:
            # ---- startChallenge 显式子状态机：WAIT_TRANSITION → VERIFY_INGAME → DONE ----
            # 每 tick 至多一个输入；未知/超时/页面异变 → Fail-Closed 停机，不猜测点击
            now = time.time()
            budget_result = self._stage_budget_guard(now)
            if budget_result is not None:
                return budget_result
            window = max(20, min(self.settings.query_timeout, 60))
            state = self._challenge_start_state or "WAIT_TRANSITION"
            if self._challenge_start_state is None:
                # 防御：直接进入本分支但子状态缺失时按 WAIT_TRANSITION 处理
                self._challenge_start_state = state
                if self._challenge_start_deadline is None:
                    self._challenge_start_deadline = now + window
            # 统一"已进局"定义：选择面板/四挑战/环境锚点任一可信证据即可
            in_game = self._is_in_game_hud(frame) or context == "MAIN_LINE"
            if self._challenge_start_source == "hero":
                # hero 来源额外接受 HeroChallenge 左上角局内锚点
                hero_hud = self.find(frame, ["HeroChallenge"], threshold=0.85)
                if hero_hud and hero_hud.x <= 400 and hero_hud.y <= 150:
                    in_game = True

            if state == "DONE":
                # DONE 但仍在 STAGE_STARTING（正常路径 set_phase 已离开）：直接推进
                self.set_phase(Phase.MAIN_LINE, "challenge start verified (DONE)")
                return LoopAction.Continue

            if state == "VERIFY_INGAME":
                if in_game:
                    self._challenge_start_hud_frames += 1
                    if self._challenge_start_hud_frames >= 2:
                        self._challenge_start_state = "DONE"
                        print("[L0] 局内锚点连续 2 帧确认，进入 MAIN_LINE")
                        self.set_phase(Phase.MAIN_LINE, "challenge start verified")
                        return LoopAction.Continue
                    print(f"[L0] 等待目标帧（追帧中）…（局内锚点第 {self._challenge_start_hud_frames} 帧，"
                          f"需连续 2 帧确认）")
                    return LoopAction.Continue
                # 锚点中断 1 帧 → 回 WAIT_TRANSITION（不算失败）
                self._challenge_start_state = "WAIT_TRANSITION"
                self._challenge_start_hud_frames = 0
                print("[L0] 局内锚点中断，回到 WAIT_TRANSITION（不算失败）")
                return LoopAction.Continue

            if state == "WAIT_TRANSITION":
                if in_game:
                    self._challenge_start_state = "VERIFY_INGAME"
                    self._challenge_start_hud_frames = 1
                    self._challenge_start_deadline = now + window  # 锚点出现，延长同窗
                    print(f"[L0] 局内锚点出现（第 1 帧），进入 VERIFY_INGAME 连续确认"
                          f" [source={self._challenge_start_source}/attempts={self._challenge_start_attempts}/"
                          f"deadline={self._challenge_start_deadline - now:.0f}s]")
                    return LoopAction.Continue
                hero_note = ""
                if self._challenge_start_source == "hero":
                    # hero 来源且弹窗按钮消失满 2 帧：继续留在 WAIT_TRANSITION
                    # 等待局内锚点，不额外动作
                    if not self._hero_modal_buttons(frame):
                        self._challenge_start_hero_modal_frames += 1
                    else:
                        self._challenge_start_hero_modal_frames = 0
                    if self._challenge_start_hero_modal_frames >= 2:
                        hero_note = "（英雄弹窗已关闭，等待局内锚点）"
                # 超时与失败分支：deadline 到期仍未 VERIFY_INGAME
                if self._challenge_start_deadline is not None and now >= self._challenge_start_deadline:
                    return self._challenge_start_timeout(stage_page)
                remain = (
                    self._challenge_start_deadline - now
                    if self._challenge_start_deadline is not None
                    else float("inf")
                )
                print(f"[L0] 等待目标帧（追帧中）…"
                      f" [source={self._challenge_start_source}/attempts={self._challenge_start_attempts}/"
                      f"deadline={remain:.0f}s]{hero_note}")
                return LoopAction.Continue

            # 未知子状态：Fail-Closed，不猜测点击
            print(f"[L0] 未知 startChallenge 子状态 {state}，停止运行")
            self.set_phase(Phase.ERROR, f"unknown challenge start state {state}")
            self.stop()
            return LoopAction.Break

        return LoopAction.Continue

    # ---------- 主循环（中介调度）----------

    def _snapshot_window_existence(self) -> None:
        """G0 P0 contract #3/#6：游戏/平台窗口存在性快照（只读 Win32 枚举）。"""
        try:
            game_targets = find_window_targets(
                ",".join(L1_WINDOW_KEYWORDS), role="l1", allow_minimized=True
            )
        except Exception:
            game_targets = []
        try:
            platform_targets = find_window_targets(
                ",".join(L0_WINDOW_KEYWORDS), role="l0", allow_minimized=True
            )
        except Exception:
            platform_targets = []
        self.game_platform_window_snapshot = {
            "game": bool(game_targets),
            "platform": bool(platform_targets),
        }

    def _record_environment_incident(self, kind: str, elapsed: float) -> None:
        """G0 P0 contract #6/#4：环境/压力异常 incident 归档（archiver 缺省空转）。"""
        if self._archiver is None:
            return
        frame = self._last_frame
        if frame is None or frame.bgr is None or frame.bgr.size == 0:
            return
        saved = self._archiver.maybe_record(
            frame_before=self._prev_frame,
            frame_now=frame,
            metadata=self._incident_meta(
                kind,
                f"{kind} persisted {elapsed:.1f}s",
                final_action="wait" if kind == "hitch_pressure_core_failed" else "stop",
                extra={"window_snapshot": dict(self.game_platform_window_snapshot)},
            ),
            healthy=False,
            health_issues=[],
            health_details=kind,
        )
        if saved is not None:
            self._incident_pending_fp = saved
            if self._tick_reason is None:
                self._tick_reason = "incident_write"

    def stop(self) -> None:
        self._running = False
        # G0 P0 contract：先到的外部 stop reason（F12/Shift+F12/UI 等）拥有
        # 归因权，Mediator.stop() 绝不覆盖；只在尚无外部 stop 时写信号。
        if not self.stop_signal.is_set():
            self.stop_signal.trigger("Mediator.stop()")

    def tick(self) -> LoopAction:
        """单步：一帧截屏 → 按阶段决策 → 执行。"""
        self._tick_no += 1
        t0 = time.perf_counter()
        phase_before = self.phase.name
        phase_before_value = self.phase
        try:
            action = self._tick_impl()
            if action is LoopAction.Continue:
                self._hitch_liveness_supervise()
                if self.stop_signal.is_set() and self.phase == Phase.ERROR:
                    action = LoopAction.Break
            # dry_run is observation mode: an uncertain/unsupported page may
            # record an incident, but must not terminate the replay/observer.
            if (
                self.settings.dry_run
                and action is LoopAction.Break
                and self.phase == Phase.ERROR
                and (not self.stop_signal.is_set() or self.stop_signal.reason == "Mediator.stop()")
            ):
                print(f"[med] OBSERVE incident: {self._interrupt_reason}; continue with zero input")
                if self.stop_signal.reason == "Mediator.stop()":
                    self.stop_signal.reset()
                self.phase = phase_before_value
                self._running = True
                return LoopAction.Continue
            return action
        finally:
            self._trace_tick(phase_before, t0)

    def set_trace(self, path: str | None) -> None:
        """开启/关闭 JSONL tick trace（卡死/误操作后最后几十个 tick 的可回放诊断）。

        幂等：先开新句柄、后关旧句柄，任何时刻至多一个打开的 trace 文件；
        新路径打开失败时旧 trace 不被意外关闭。
        """
        new_fh = None
        self._trace_path = path
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            new_fh = open(path, "a", encoding="utf-8")
        if self._trace_fh is not None:
            self._trace_fh.close()
            self._trace_fh = None
        self._trace_fh = new_fh

    def _trace_tick(self, phase_before: str, t0: float) -> None:
        if self._trace_fh is None:
            return
        frame = self._last_frame
        row: dict = {
            "tick": self._tick_no,
            "ts": round(time.time(), 3),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 1),
            "phase_before": phase_before,
            "phase_after": self.phase.name,
            "run_mode": "OBSERVE" if self.settings.dry_run else "LIVE",
            "interrupt_reason": self._interrupt_reason,
            "context": self._context_cache_value,
            "hwnd": frame.hwnd if frame is not None else None,
            "size": [frame.width, frame.height] if frame is not None else None,
            "actions": self._trace_actions,
            "controls": self._trace_controls,
            "scenes": self._trace_scenes,
            # N2：无法解释 tick>1s 白名单 reason + evidence generation
            "reason": self._tick_reason,
            "evidence_gen": self._evidence.gen if self._evidence is not None else None,
            # B1-1 证据与遥测扩展
            "build_id": BUILD_ID,
            "settings_summary": self._trace_settings_summary(),
            "frame_fingerprint": self._trace_frame_fingerprint(frame),
            "panel": self._trace_panel_candidates(),
            "ocr_suggestion": self._trace_ocr_suggestion,
            "decision": self._trace_decision(),
            "post_confirm": self._trace_post_confirm(),
            # S0：阶段转换 reason/outcome/deadline 与 panel FSM 状态（增量字段，
            # 不改变 N0 action ledger 动作行；compare_ledger.py 显式忽略）。
            "s0": {
                "round_deadline": round(self._round_deadline, 1) if self._round_deadline else None,
                "round_outcome": self._round_outcome.name if self._round_outcome else None,
                "last_outcome": self._last_outcome.name if self._last_outcome else None,
                "failure_streak": self._failure_streak,
                "game_count": self.game_count,
                "panel_state": self._panel_state.name,
                "recovery_step": self._recovery_state.step.name if self._recovery_state else self._recovery_step,
                "recovery_kind": self._recovery_state.kind.name if self._recovery_state else None,
                "f1_live": self._f1_live,
                "f1_shadow_correct": self._f1_shadow_correct,
                "f1_shadow_misfire": self._f1_shadow_misfire,
            },
        }
        # Additive audit fields: why a tick made no decision (health gate),
        # which capture path chose the HWND, and the hitch transactions.
        health = getattr(self, "_last_health", None)
        row["health"] = (
            None if health is None or health.is_healthy
            else [issue.value for issue in health.issues]
        )
        row["capture"] = {
            "candidates": getattr(self, "_capture_candidates", None),
            "selected_by": getattr(self, "_capture_selected_by", None),
            "black_hwnds": list(getattr(self, "_capture_black_hwnds", ()) or ()),
        }
        if self._hitch_enabled():
            row["hitch"] = self._trace_hitch_state()
        self._trace_fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._trace_fh.flush()

    def _trace_hitch_state(self) -> dict:
        sm = self._hitch_sm
        now = time.time()
        return {
            "status": self._hitch_status,
            "pending_join": bool(sm.pending_join),
            "join_age_s": (
                round(now - sm.join_clicked_at, 1) if sm.join_clicked_at is not None else None
            ),
            "origin_hwnd": self._hitch_join_origin_hwnd,
            "confirmed_room_hwnd": getattr(self, "_confirmed_room_hwnd", None),
            "exit_pending": bool(getattr(self, "_hitch_floor_exit_pending", False)),
            "exit_clicks": int(getattr(self, "_hitch_floor_exit_clicks", 0) or 0),
            "exit_confirm_clicks": int(getattr(self, "_hitch_floor_exit_confirm_clicks", 0) or 0),
            "ready_timeout_pending": bool(getattr(self, "_hitch_ready_timeout_pending", False)),
            "self_row": getattr(self, "_hitch_self_row", None),
            "floor_one_baseline": getattr(self, "_hitch_floor_one_baseline", None) is not None,
            "seat_streak": (
                list(self._hitch_seat_streak) if getattr(self, "_hitch_seat_streak", None) else None
            ),
            "stall_s": (
                round(now - self._liveness_last_progress_at, 1)
                if getattr(self, "_liveness_last_progress_at", None) is not None else None
            ),
            "stall_level": int(getattr(self, "_liveness_level", 0) or 0),
        }

    def _trace_settings_summary(self) -> dict:
        """掩码设置摘要：仅白名单字段进 trace，密码类字段显式排除。

        ocr_mode 在 Settings 尚未定义该字段时按 "off" 处理（B3 前无运行时
        OCR，与基线动作序列一致）。challenge 记录挑战相关配置名。
        """
        s = self.settings
        summary = {
            "ocr_mode": getattr(s, "ocr_mode", "off"),
            "skills": list(s.skills or []),
            "challenge": {
                "stage_targets": list(s.stage_targets or []) or [f"{s.stage1}-{s.stage2}"],
                "cjb_boss": s.cjb_boss,
                "sgzx_boss": s.sgzx_boss,
            },
        }
        return _scrub_sensitive_keys(summary)

    def _trace_frame_fingerprint(self, frame: Frame | None) -> str | None:
        """帧指纹：size + bgr md5（无现成指纹函数时的简单实现）。

        相同 Frame 对象（静态帧复用）缓存指纹，避免每 tick 重复哈希。
        缓存持有 Frame 强引用并用 ``is`` 判同：``id(frame)`` 在对象被 GC 后
        可能被同址新对象复用，导致旧指纹误命中。
        """
        if frame is None or frame.bgr is None:
            return None
        cached = self._trace_fingerprint_cache
        if cached is not None and cached[0] is frame:
            return cached[1]
        try:
            digest = hashlib.md5(frame.bgr.tobytes()).hexdigest()
        except Exception:
            return None
        fingerprint = f"{frame.width}x{frame.height}:{digest}"
        self._trace_fingerprint_cache = (frame, fingerprint)
        return fingerprint

    def _trace_panel_candidates(self) -> list[dict]:
        """面板模板候选 top3（name+score），按分差取，复用 _trace_scenes 截断逻辑。"""
        top = sorted(self._trace_scenes, key=lambda s: s.get("score", 0.0), reverse=True)[:3]
        return [{"name": s["name"], "score": s["score"]} for s in top]

    def _trace_decision(self) -> str | None:
        """本 tick 最终决策 reason_code，从 _tick_impl 现有分支状态取。

        优先级：Fail-Closed/错误原因 → 停止原因 → 最后一条动作的 reason；
        没有现成决策点时返回 None。
        """
        if self._interrupt_reason:
            return f"error:{self._interrupt_reason}"
        if self.stop_signal.is_set() and self.stop_signal.reason:
            return f"stop:{self.stop_signal.reason}"
        if self._trace_actions:
            reason = self._trace_actions[-1].get("reason")
            if reason:
                return f"act:{reason}"
        return None

    def _trace_post_confirm(self) -> bool | None:
        """后置确认结果：仅在有现成确认点处填写，其余为 None。

        现成确认点：
          * 失败恢复链完成（``_recovery_step == "DONE"``）说明 FAIL→OK→CLOSE
            三步点击均已被后续帧确认；
          * 选择面板 WAIT_MUTATION 落定：mutation/面板消失 → True，确认窗
            超时 → False。第 1 个神符点选成功却记 null，正是这一段缺失
            （2026-09-09 trace tick 175）。
          * 公共背包存入后置确认（DEPOSIT→DONE / ABORTED）。
        """
        if self._recovery_step == "DONE":
            return True
        return getattr(self, "_tick_post_confirm", None)

    def _tick_impl(self) -> LoopAction:
        self._trace_actions = []
        self._trace_scenes = []
        self._trace_controls = []
        self._trace_ocr_suggestion = None
        self._tick_post_confirm = None
        self._interrupt_reason = None
        self._tick_reason = None
        self._tick_input_executed = False
        if self.stop_signal.is_set():
            print(f"[med] Stop signal active ({self.stop_signal.reason}), breaking loop")
            self._running = False
            return LoopAction.Break

        frame = self.see("tick")
        if self.stop_signal.is_set():
            print(f"[med] Stop signal active after capture ({self.stop_signal.reason}), skipping decision")
            self._running = False
            return LoopAction.Break

        health = check_frame_health(frame, prev_frame=self._prev_frame)
        self._last_health = health
        if not health.is_healthy:
            issue_values = {i.value for i in health.issues}
            static_frame_ok = issue_values.issubset({"frozen", "old_frame"})
            if static_frame_ok:
                # 静止帧 / 捕获耗时造成的陈旧帧：页面内容可信（与上一帧相同），
                # 常见于静态弹窗（建房、断线确认）或双窗口捕获慢的伪影。
                # 放行识别与阶段推进；输入仍受 InputExecutor 的 HWND/前台/急停检查保护。
                print(f"[med] 静态/陈旧帧（{health.details}），继续识别（坐标可信）")
                self._missing_window_since = None
            else:
                print(f"[med] Frame health check failed ({health.details}), skipping decision and input")
                now = time.time()
                self._missing_window_since = self._missing_window_since or now
                elapsed = now - self._missing_window_since
                print(f"[med] Unhealthy frame ({health.details}), waiting {elapsed:.1f}s phase={self.phase.name}")
                if self._hitch_enabled():
                    # 蹭车是长期观察模式；黑屏/转场/窗口短暂消失只撤销
                    # 输入权，不得把整个 run 终止。Shift+F12/用户停止仍在上方抢占。
                    # G0 P0 contract #6：unhealthy 期间做有界窗口存在性观察——
                    # 游戏/平台窗口均长时间不存在 → 记录 evidence 并
                    # FATAL_ENVIRONMENT_FAILURE；不产生任何业务输入。
                    sm = self._hitch_sm
                    if (
                        sm.pending_join
                        and sm.join_clicked_at is not None
                        and now - sm.join_clicked_at >= sm.join_confirm_timeout_s
                    ):
                        # The join's own timeout lives in _tick_lobby_hitch,
                        # which an unhealthy frame never reaches.  Release the
                        # join here (zero input) so the join probe stops
                        # preferring a non-origin window and the next capture
                        # re-ranks towards a window with page evidence.
                        self._hitch_reject_pending_join(now, "join_rejected_unhealthy_surface")
                        self._hitch_search_actions.append("reject")
                        print("[L0] hitch 进房后只有不健康/黑色表面，零输入拒绝本次进房并重新选择大厅窗口")
                    self._snapshot_window_existence()
                    bound = max(30.0, min(float(self.settings.query_timeout), 60.0))
                    if elapsed >= bound:
                        if (
                            not self.game_platform_window_snapshot.get("game")
                            and self.game_platform_window_snapshot.get("platform")
                        ):
                            # G0 contract #6：游戏窗消失 + fresh 平台房间列表权威
                            # 实际成立 → 回大厅；绝不 timeout blind set_phase。
                            platform_frame = self._capture_best(",".join(L0_WINDOW_KEYWORDS), "l0")
                            if (
                                platform_frame is not None
                                and platform_frame.is_valid
                                and self._lobby_room_list_evidence(platform_frame)
                            ):
                                print("[med] 蹭车 unhealthy：游戏窗消失但平台房间列表 fresh 权威成立，回 LOBBY_ROOM")
                                self._hitch_after_exit(now)
                                self.set_phase(Phase.LOBBY_ROOM, "unhealthy handoff: fresh platform room list")
                                self._missing_window_since = None
                                return LoopAction.Continue
                        if (
                            not self.game_platform_window_snapshot.get("game")
                            and not self.game_platform_window_snapshot.get("platform")
                        ):
                            print("[med] 蹭车 unhealthy 期间游戏/平台窗口均不存在超过边界，FATAL_ENVIRONMENT_FAILURE")
                            self._record_environment_incident("hitch_windows_missing", elapsed)
                            self.set_phase(Phase.ERROR, "hitch no game/platform window")
                            self.stop()
                            return LoopAction.Break
                        if (
                            self.phase in (Phase.LOBBY_ROOM, Phase.ROOM_WAITING)
                            and not self.game_platform_window_snapshot.get("game")
                            and elapsed >= self._HITCH_L0_UNHEALTHY_BLOCK_S
                        ):
                            # Lobby/room phases with only unusable KK surfaces
                            # (e.g. every KK window black) for this long cannot
                            # recover on their own; end explicitly instead of
                            # observing a dead surface forever.
                            print(
                                "[med] 蹭车 L0 阶段持续无可用平台画面 "
                                f"{elapsed:.0f}s（{health.details} hwnd={frame.hwnd}），BLOCKED 停止"
                            )
                            self._record_environment_incident("hitch_l0_surface_blocked", elapsed)
                            self.set_phase(Phase.ERROR, "hitch l0 surface blocked")
                            self.stop()
                            return LoopAction.Break
                        # 至少一个窗口仍在（但无 fresh 权威）：只撤销输入权，
                        # 继续有界观察，绝不盲目改阶段。
                        return LoopAction.Continue
                    return LoopAction.Continue
                in_game_phases = {Phase.MAIN_LINE, Phase.EARLY_CHALLENGE, Phase.ANCHOR_BOSS, Phase.LONGZHU}
                if self.phase == Phase.ROOM_STARTING:
                    if self._room_start_deadline is None:
                        self._room_start_deadline = now + self._l0_transition_timeout()
                    if now >= self._room_start_deadline:
                        print("[med] ROOM_STARTING 不健康帧超过宏观过渡期限，回退房间等待")
                        self.set_phase(Phase.ROOM_WAITING, "room start unhealthy alignment timeout")
                    return LoopAction.Continue
                elif self.phase == Phase.STAGE_SELECT:
                    if self._room_action_deadline is None:
                        self._room_action_deadline = now + self._l0_transition_timeout()
                    if now >= self._room_action_deadline:
                        print("[med] STAGE_SELECT 不健康帧超过宏观期限，续期继续（不停止）")
                        self._room_action_deadline = now + self._l0_transition_timeout()
                    return LoopAction.Continue
                elif self.phase in in_game_phases:
                    if elapsed >= 60:
                        print("[med] 局内阶段不健康帧持续超过 60s，停止运行")
                        self.set_phase(Phase.ERROR, "unhealthy frame timeout")
                        self.stop()
                        return LoopAction.Break
                elif self.phase in (Phase.HERO_SETUP, Phase.STAGE_STARTING):
                    # 英雄弹窗/加载过场的黑帧可能较长：与观察窗对齐（最高 60s），不提前误杀
                    hero_window = getattr(self, "_hero_observation_timeout", lambda: 60)()
                    window = max(hero_window, self.settings.query_timeout)
                    if elapsed >= window:
                        print(f"[med] {self.phase.name} 不健康帧持续超过 {window:.0f}s，停止运行")
                        self.set_phase(Phase.ERROR, "unhealthy frame timeout")
                        self.stop()
                        return LoopAction.Break
                elif self.phase == Phase.BOOT:
                    # The platform/game process can take longer than one
                    # capture cycle to create a visible window.  Keep waiting
                    # for a bounded period instead of failing after two slow
                    # splash-screen captures.
                    boot_timeout = min(self.settings.query_timeout, 15)
                    if self.settings.query_timeout > 15:
                        boot_timeout = max(30, min(self.settings.query_timeout, 60))
                    if elapsed >= boot_timeout:
                        print(f"[med] 启动阶段等待窗口超过 {boot_timeout}s，停止运行")
                        self.set_phase(Phase.ERROR, "unhealthy frame timeout")
                        self.stop()
                        return LoopAction.Break
                elif self.phase in (Phase.CREATE_ROOM, Phase.PLATFORM_MAP, Phase.ROOM_WAITING, Phase.LOBBY_ROOM):
                    # 建房弹窗/平台窗短暂不可见（用户操作间隙、弹窗切换）不应 15s 误杀；
                    # 与 BOOT 同窗容忍，超时才 Fail-Closed。
                    l0_timeout = max(30, min(self.settings.query_timeout, 60))
                    if elapsed >= l0_timeout:
                        print(f"[med] {self.phase.name} 等待窗口超过 {l0_timeout}s，停止运行")
                        self.set_phase(Phase.ERROR, "unhealthy frame timeout")
                        self.stop()
                        return LoopAction.Break
                elif elapsed >= min(self.settings.query_timeout, 15):
                    self.set_phase(Phase.ERROR, "unhealthy frame timeout")
                    self.stop()
                    return LoopAction.Break
                return LoopAction.Continue

        self._missing_window_since = None


        # N2.2：本 tick 动作授权锚点（健康放行后才建立）。
        # 任一成功输入会推进 evidence.gen / _input_seq；act_* 前置断言
        # gen 与输入序列未变，stale → 零输入。
        tick_ev = self._evidence
        self._tick_evidence = tick_ev
        self._tick_gen = tick_ev.gen if tick_ev is not None else None
        self._tick_input_seq = self._input_seq
        # ---- B1-2 证据归档（无 incident_dir 时全部空转；归档不产生任何输入）----
        # 注：此处仅健康帧/静态帧可达（不健康非静态分支均已 return）。
        if self._archiver is not None:
            # 1) 触发后下一帧补齐 frame_after（同一 incident 只补一次）
            if self._incident_pending_fp:
                if self._archiver.attach_frame_after(self._incident_pending_fp, frame):
                    self._incident_pending_fp = None
                    if self._tick_reason is None:
                        self._tick_reason = "incident_write"
            # 2) context=UNKNOWN 连续 2 秒 → 未知页面 incident；
            #    同一 UNKNOWN episode 内每个不同页面只记一次（episode 结束重置）。
            now = time.time()
            if self._context_cache_value == "UNKNOWN":
                self._unknown_since = self._unknown_since or now
                if now - self._unknown_since >= 2.0:
                    fp_now = self._archiver.fingerprint(frame)
                    if fp_now is not None and fp_now != self._unknown_recorded_fp:
                        saved = self._archiver.maybe_record(
                            frame_before=self._prev_frame,
                            frame_now=frame,
                            metadata={
                                "kind": "unknown_page",
                                "phase": self.phase.name,
                                "hwnd": frame.hwnd,
                                "window_title": frame.window_title,
                                "size": [frame.width, frame.height],
                                "score": None,
                                "candidate_actions": [],
                                "final_action": "wait",
                                "reason": "context=UNKNOWN >= 2s",
                            },
                            healthy=True,  # 本路径仅健康/静态帧可达
                            health_issues=[],
                            health_details="",
                        )
                        self._unknown_recorded_fp = fp_now
                        if saved is not None:
                            self._incident_pending_fp = saved
                            if self._tick_reason is None:
                                self._tick_reason = "incident_write"
            else:
                self._unknown_since = None
                self._unknown_recorded_fp = None

        # ---- S0 ② 全局抢占：disconnect / STRONG_FAIL 优先于 selection/panel FSM ----
        # 每类强证据单独按连续 tick 计数；真实视频每次捕获都会产生新的 evidence
        # generation，不能把“同 generation”误当成“连续帧”。两帧中断即归零；
        # giveup 不计入强失败。抢占后先失效证据
        # （旧帧动作授权不得延续），再进入 RECOVER_FAILURE——本 tick 不再执行任何
        # selection/panel/artifact/challenge/主动开面板输入。
        if self.phase == Phase.RECOVER_FAILURE:
            return self._tick_recovery(frame)
        # 强失败与断线抢占仅在真实局内阶段生效；大厅/选关/过渡阶段绝无局内强失败或重连，
        # 严禁在此类阶段被小尺寸 retryConnect 或环境色块误抢占。
        if self.phase in IN_GAME_FAILURE_PREEMPT_PHASES:
            disconnect_hit = self.find_scene(frame, "disconnect")
            strong_fail_hit = None if disconnect_hit else self.find_scene(frame, "fail")
        else:
            disconnect_hit = None
            strong_fail_hit = None
        if disconnect_hit or strong_fail_hit:
            kind = "DISCONNECT" if disconnect_hit else "FAIL"
            if self._recovery_step == "DONE" and self.phase == Phase.QUIT:
                self._failure_candidate_frames = 0
            else:
                if self._failure_candidate_kind != kind:
                    self._failure_candidate_frames = 1
                    self._failure_candidate_kind = kind
                else:
                    self._failure_candidate_frames += 1
                self._failure_candidate_gen = self._tick_gen
                if self._failure_candidate_frames < 2:
                    print(f"[med] {kind} 候选第 {self._failure_candidate_frames} 帧，等待连续证据（零动作）")
                    return LoopAction.Continue
                print(f"[med] {kind} 连续两帧确认，抢占并进入 RECOVER_FAILURE")
                self.invalidate_evidence("failure-preempt")
                self._begin_recovery(
                    RecoveryKind.DISCONNECT if disconnect_hit else RecoveryKind.FAIL
                )
                return LoopAction.Continue
        else:
            self._failure_candidate_frames = 0
            self._failure_candidate_kind = None
            self._failure_candidate_gen = None
            if self._recovery_step == "DONE":
                self._recovery_step = None
            # S0 ① giveUp 单独出现：AMBIGUOUS_GIVEUP —— 非失败、无恢复动作权。
            # 有面板锚点 → 记 ambiguous 证据并继续 panel FSM（选卡遵守 panel FSM）；
            # 无面板锚点 → 未知/安全等待（零输入），不得自动判为失败。
            if self.find_scene(frame, "giveup") is not None:
                if self._selection_anchor(frame):
                    self._ambiguous_giveup_frames += 1
                    print("[med] giveUp + 选择面板锚点：AMBIGUOUS_GIVEUP，非失败，继续面板 FSM")
                elif self.phase in (
                    Phase.MAIN_LINE,
                    Phase.RECOVER_FAILURE,
                    Phase.EARLY_CHALLENGE,
                    Phase.ANCHOR_BOSS,
                    Phase.LONGZHU,
                    Phase.QUIT,
                    Phase.NEXT,
                ):
                    # giveUp 单独出现且无面板锚点（局内）：未知/安全等待（零输入），
                    # 不得自动判为失败；round hard deadline 兜底有界。
                    print("[med] giveUp 单独出现（无面板锚点）：非失败，零输入安全等待")
                    return LoopAction.Continue
                else:
                    # L0 等非局内阶段：仅记录 ambiguous 证据，不阻断 L0 链
                    self._ambiguous_giveup_frames += 1

        if self.phase in {
            Phase.BOOT,
            Phase.WAIT_EXIT,
            Phase.LOBBY_ROOM,
            Phase.PREPARE,
            Phase.WAIT_UI,
            Phase.PLATFORM_MAP,
            Phase.CREATE_ROOM,
            Phase.ROOM_WAITING,
            Phase.ROOM_STARTING,
            Phase.STAGE_SELECT,
            Phase.STAGE_STARTING,
            Phase.HERO_SETUP,
        }:
            return self._tick_l0(frame)

        if self.phase == Phase.MAIN_LINE:
            return self._tick_main_line(frame)

        if self.phase == Phase.RECOVER_FAILURE:
            return self._tick_recovery(frame)

        if self.phase in {
            Phase.EARLY_CHALLENGE,
            Phase.ANCHOR_BOSS,
            Phase.LONGZHU,
            Phase.QUIT,
            Phase.NEXT,
        }:
            return self._tick_l1_tail(frame)

        if self.phase == Phase.COMPLETE:
            # S0 ⑥：cycle_num 达成即安全停止；绝不点下一局开始。
            print("[med] 已达 cycle_num 目标局数，COMPLETE 停止运行")
            self.stop()
            return LoopAction.Break

        print(f"[med] unhandled phase {self.phase}")
        return LoopAction.Continue

    # ---------- S0 ⑤ 面板会话 FSM / S0 ⑧ 局尾门控 ----------

    def _round_tail_checks_active(self) -> bool:
        """S0 ⑧ archive/boss 未验证入口检查的触发条件（局尾窗口）：

        - 战后流程进行中（_post_game_pending / 胜利链已点击继续）；
        - 或距 round hard deadline 不足 round_tail_window_s（boss 等出现在局尾）。
        LONGZHU 色相检查只在 LONGZHU 阶段（_tick_l1_tail）执行，不在此列。
        """
        if self._post_game_pending or self._victory_continue_attempts > 0:
            return True
        if self._round_deadline is not None:
            return self._round_deadline - time.time() <= self.settings.round_tail_window_s
        return False

    def _panel_kind_of(self, frame: Frame, anchor: MatchResult) -> str:
        """面板种类：主动打开的键位优先于单锚点/色块。

        13号 200601：按了 G 之后 treasure_lock 误匹配、HSV 把金卡三选判成宝物，
        整局按宝物 OCR（槽位全 disabled）空刷 227 次。我们刚按的 G/F/V
        比「锁模板单独命中」或中间花屏更可信。
        """
        opened = getattr(self, "_panel_opened_by_us", None)
        # 放弃按钮是技能面板独有（放弃/giveUp）；宝物面板绝无放弃按钮。
        if anchor.name in {"skill_giveup_btn"}:
            return "skill"
        if opened == "treasure":
            # V 前后选卡区域未变化，说明打开请求落在已有面板上，不能借 V
            # 把该面板误判为宝物；发生变化才是本轮 V 真正打开的新面板。
            requested_fp = getattr(self, "_treasure_open_request_fp", None)
            current_fp = self._panel_physical_fingerprint(frame)
            if requested_fp is None:
                # 兼容旧会话及回放：它们没有按键前画面，沿用主动 V 标记。
                return "treasure"
            if current_fp is not None and current_fp != requested_fp:
                return "treasure"
            generic = self._classify_choice_panel_at(
                frame, min(0.70, self.settings.match_threshold), self._hot_scales()
            )
            return generic or "unknown"
        if opened in ("skill", "bond"):
            return opened
        if anchor.name in {"bond_hide_btn", "bond_refresh_btn"}:
            # P0-3（215302）：单一 bond 锚点（bond_refresh_btn 0.742 贴阈值单独出现）
            # 不足为 bond 定类；bond 需 bond_hide+bond_refresh 联合证据
            # （_classify_choice_panel 裁决），或主动打开标记 / card_hide 关闭兜底。
            if opened == "bond" or self._classify_choice_panel(frame) == "bond":
                return "bond"
            # R8-REVIEW 补修：joint bond 失败（215302：bond_hide 0.39 miss）但
            # card_hide 高置信（≥match_threshold）命中时仍按 bond 处理——card_hide
            # 是该类面板的"暂时隐藏"关闭按钮，允许 OCR/关闭路径，避免 215302 式
            # 自然面板落入 unknown timeout。
            if self.find(
                frame, ["card_hide"],
                threshold=self.settings.match_threshold,
                scales=self._hot_scales(),
                roi=self._PANEL_BUTTONS_ROI,
            ) is not None:
                return "bond"
            # 单锚点证据不足：继续用其它锚点/分类器裁决，不轻信 bond 定类
        elif anchor.name == "card_hide" and LayoutTransform.is_supported(frame.width, frame.height):
            return "bond"
        elif anchor.name == "skill_giveup_btn":
            return "skill"
        elif (
            anchor.name == "skill_refresh_btn"
            and frame.bgr is not None
            and LayoutTransform.is_supported(frame.width, frame.height)
        ):
            # 刷新图与 V 共用。放弃钮在则一定是 G；否则才用色块区分自然弹出的 V。
            if self.find(
                frame, ["skill_giveup_btn"],
                threshold=min(0.70, self.settings.match_threshold),
                scales=self._hot_scales(),
                roi=self._PANEL_BUTTONS_ROI,
            ) is not None:
                return "skill"
            transform = LayoutTransform.from_frame(frame.width, frame.height)
            rx1, ry1, rx2, ry2 = transform.logical_roi(450, 180, 1145, 515)
            roi = frame.bgr[ry1:ry2, rx1:rx2]
            if roi.size == 0:
                return "skill"
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            colored = (hsv[:, :, 1] > 70) & (hsv[:, :, 2] > 60)
            min_pixels = int(60000 * transform.scale * transform.scale)
            return "treasure" if int(colored.sum()) >= max(1000, min_pixels) else "skill"
        elif anchor.name == "skill_hide":
            return "skill"
        elif anchor.name in {"treasure_hide_btn", "treasure_lock_btn", "treasure_refresh_btn"}:
            classified = self._classify_choice_panel(frame)
            if classified in ("skill", "treasure", "bond"):
                return classified
            return "unknown"
        if opened in ("skill", "bond", "treasure"):
            return opened
        return self._classify_choice_panel(frame) or "unknown"

    @staticmethod
    def _panel_choice_action_kind(hit_name: str | None) -> str:
        text = str(hit_name or "").lower()
        if "refresh" in text:
            return "refresh"
        if any(token in text for token in ("hide", "close", "giveup")):
            return "close"
        return "select"

    # B2 拿卡提速：局内选卡面板（skill/bond/treasure）关闭（本次没有可拿卡）→
    # 下次可重开该面板的间隔。刻意与全局 ui_action_interval_s（1.5s，UI 输入
    # 最小间隔）解耦，不改后者的默认值/其它用途。
    _L1_PANEL_REOPEN_INTERVAL_S = 0.5

    def _arm_panel_reopen_cooldown(self, kind: str | None, now: float) -> None:
        if kind not in ("skill", "bond", "treasure"):
            return
        delay = max(2.0, min(15.0, float(getattr(self.settings, "panel_reopen_cooldown_s", 3.0))))
        self._panel_cooldown_until[kind] = max(
            self._panel_cooldown_until.get(kind, 0.0), now + delay
        )

    def _stage_panel_choice_action(self, action: str, fingerprint: tuple | None) -> None:
        self._panel_pending_choice_action = action
        self._panel_pending_choice_fingerprint = fingerprint

    def _confirm_panel_choice_action(self, now: float) -> None:
        action = self._panel_pending_choice_action
        if action is not None:
            self._tick_post_confirm = True
        if action == "select":
            if (
                self._l1_cycle_owned_panel
                and self._panel_kind == self._l1_cycle_step
                and self._panel_kind in ("skill", "bond", "treasure")
            ):
                self._l1_cycle_selected = True
            if self._panel_kind in ("skill", "bond"):
                if getattr(self, "_visit_kind", None) != self._panel_kind:
                    self._visit_kind = self._panel_kind
                    self._visit_picks = 0
                self._visit_picks = getattr(self, "_visit_picks", 0) + 1
            if self._panel_kind == "bond":
                self._bond_picks_round = getattr(self, "_bond_picks_round", 0) + 1
            if self._panel_kind in ("skill", "bond", "treasure"):
                self._l1_cycle_step_successes = getattr(self, "_l1_cycle_step_successes", 0) + 1
            if self._panel_kind == "skill":
                self._last_skill_panel = 0.0
            elif self._panel_kind == "bond":
                self._last_bond_attempt = 0.0
            elif self._panel_kind == "treasure":
                self._last_treasure_attempt = 0.0
            self._hitch_last_treasure_unconfirmed_fp = None
        elif action == "close":
            fp = self._panel_pending_choice_fingerprint
            hit_name = str(fp[1]).lower() if fp and len(fp) > 1 else ""
            if "giveup" in hit_name:
                self._l1_cycle_selected = True
            self._arm_panel_reopen_cooldown(self._panel_kind, now)
        elif action == "refresh":
            self._skill_refresh_attempts = getattr(self, "_skill_refresh_attempts", 0) + 1
            if self._panel_kind == "treasure":
                self._hitch_treasure_total_refreshes = (
                    getattr(self, "_hitch_treasure_total_refreshes", 0) + 1
                )
            self._sync_choice_session_refreshes()
            self._skill_refresh_failed_attempts = 0
            if self._panel_kind == "skill":
                self._panel_opened_by_us = "skill"
        self._panel_pending_choice_action = None
        self._panel_pending_choice_fingerprint = None

    def _expire_panel_choice_action(self) -> str | None:
        action = self._panel_pending_choice_action
        if action is not None:
            self._tick_post_confirm = False
        self._panel_pending_choice_action = None
        self._panel_pending_choice_fingerprint = None
        return action

    def _reset_f_draw_guard(self) -> None:
        self._f_draw_fingerprint = None
        self._f_draw_first_seen_at = None
        self._f_draw_last_reopen_at = None
        self._f_draw_reopen_count = 0
        self._f_draw_backoff_until = 0.0

    def _track_f_draw_episode(self, frame: Frame, kind: str, now: float) -> None:
        """Track one physical F draw across generic panel episode resets."""
        if self._passenger_mode() or kind != "bond":
            return
        fingerprint = self._panel_physical_fingerprint(frame)
        if fingerprint is None:
            return
        if fingerprint != self._f_draw_fingerprint:
            self._f_draw_fingerprint = fingerprint
            self._f_draw_first_seen_at = now
            self._f_draw_last_reopen_at = None
            self._f_draw_reopen_count = 0
            self._f_draw_backoff_until = 0.0
            return
        self._f_draw_reopen_count += 1
        self._f_draw_last_reopen_at = now
        print(
            f"[L1] 同一 F 抽卡重新打开 {self._f_draw_reopen_count} 次 "
            f"（fingerprint={fingerprint[:12]}）"
        )

    def _enter_panel_episode(self, frame: Frame, anchor: MatchResult, kind: str, opened: bool) -> None:
        """进入 ACTIVE 会话：记录 kind/指纹起点；不消耗异常重开预算。"""
        now = time.time()
        self._panel_state = PanelState.ACTIVE
        self._panel_kind = kind
        self._track_f_draw_episode(frame, kind, now)
        self._panel_episode_id = f"ep_{int(now * 1000)}"
        self._panel_first_seen_at = now
        self._panel_last_progress_at = now
        self._panel_hard_deadline_s = float(getattr(self.settings, "panel_hard_deadline_s", 10.0))
        self._panel_executed_actions = 0
        self._panel_confirmed_actions = 0
        self._panel_closing_attempts = 0
        self._panel_closing_started_at = None
        self._panel_episode_started = now
        self._panel_mutation_baseline = None
        self._panel_pending_choice_action = None
        self._panel_pending_choice_fingerprint = None
        self._panel_f1_used_this_episode = False
        self._skill_refresh_failed_attempts = 0
        self._clear_pending_skill_cards()
        self._reset_choice_session()
        if kind == "bond":
            self._choice_session = replace(
                self._choice_session,
                max_refreshes=self._BOND_REFRESH_MAX_PER_GROUP,
            )

    def _finish_panel_episode(self) -> None:
        cycle_kind = self._panel_kind
        cycle_owned = self._l1_cycle_owned_panel
        cycle_selected = self._l1_cycle_selected
        force_advance = getattr(self, "_panel_visit_force_advance", False)
        stale_f_draw = (
            cycle_owned
            and cycle_kind == "bond"
            and not cycle_selected
            and self._f_draw_reopen_count >= self._F_DRAW_REOPEN_LIMIT
        )
        if stale_f_draw:
            until = time.time() + self._F_DRAW_BACKOFF_S
            self._f_draw_backoff_until = max(self._f_draw_backoff_until, until)
            self._bond_idle_until = max(getattr(self, "_bond_idle_until", 0.0), until)
            print(
                f"[L1] 同一 F 抽卡无合法选择且连续重开已达上限，"
                f"进入 {self._F_DRAW_BACKOFF_S:.0f}s 有界退避"
            )
        elif cycle_kind == "bond" and cycle_selected:
            # A confirmed selection consumes this draw.  A future draw with
            # identical pixels must still get a fresh liveness budget.
            self._reset_f_draw_guard()
        self._panel_visit_force_advance = False
        self._panel_state = PanelState.CLOSED
        self._panel_kind = None
        self._panel_episode_id = None
        self._panel_first_seen_at = None
        self._panel_last_progress_at = None
        self._panel_executed_actions = 0
        self._panel_confirmed_actions = 0
        self._panel_closing_attempts = 0
        self._panel_closing_started_at = None
        self._panel_episode_started = None
        self._panel_mutation_baseline = None
        self._panel_fingerprint = None
        self._panel_fingerprint_attempts = 0
        self._panel_pending_choice_action = None
        self._panel_pending_choice_fingerprint = None
        self._panel_opened_by_us = None
        self._panel_anchor_candidate = None
        self._selection_repeat_key = None
        self._selection_repeat_attempts = 0
        self._selection_unknown_attempts = 0
        self._selection_unknown_since = None
        self._l1_cycle_owned_panel = False
        self._l1_cycle_selected = False
        self._clear_pending_skill_cards()
        self._reset_choice_session()
        if self._passenger_mode() and cycle_owned and cycle_kind == "treasure":
            self._advance_l1_cycle("treasure")
            return
        if (
            cycle_owned
            and cycle_kind == "bond"
            and not cycle_selected
            and not self._passenger_mode()
        ):
            wood = getattr(self, "_wood_balance", None)
            if wood is None or wood < self._BOND_HIGH_WOOD:
                self._bond_idle_until = time.time() + self._BOND_IDLE_BACKOFF_S
        if (
            cycle_owned
            and cycle_kind == "skill"
            and not cycle_selected
            and not self._passenger_mode()
        ):
            self._skill_idle_until = time.time() + self._SKILL_IDLE_BACKOFF_S
        if (
            cycle_owned
            and cycle_kind == self._l1_cycle_step
            and cycle_kind in ("skill", "bond", "treasure")
            and (not cycle_selected or force_advance)
        ):
            nxt = {
                "bond": "技能 G",
                "skill": "宝物 V",
                "treasure": "支线（进化/装备/黑商）",
            }.get(cycle_kind, "下一步")
            if force_advance:
                print(f"[L1] {cycle_kind} 单次停留已达 3 次成功选择/30s 抽干上限，转入{nxt}")
            else:
                print(f"[L1] {cycle_kind} 没有新的可拿，转入{nxt}")
            self._advance_l1_cycle(cycle_kind)

    def panel_episode_diagnostics(self) -> dict:
        """Return snapshot of current panel episode state and metrics for telemetry/diagnostics."""
        now = time.time()
        stale_duration = 0.0
        if self._panel_last_progress_at is not None:
            stale_duration = max(0.0, now - self._panel_last_progress_at)
        elif self._panel_episode_started is not None:
            stale_duration = max(0.0, now - self._panel_episode_started)

        return {
            "panel_state": self._panel_state.name,
            "episode_id": self._panel_episode_id,
            "kind": self._panel_kind,
            "first_seen_at": self._panel_first_seen_at,
            "last_progress_at": self._panel_last_progress_at,
            "episode_started_at": self._panel_episode_started,
            "hard_deadline_s": self._panel_hard_deadline_s,
            "stale_duration": stale_duration,
            "current_fingerprint": self._panel_fingerprint,
            "fingerprint_attempts": self._panel_fingerprint_attempts,
            "f_draw_fingerprint": self._f_draw_fingerprint,
            "f_draw_first_seen_at": self._f_draw_first_seen_at,
            "f_draw_last_reopen_at": self._f_draw_last_reopen_at,
            "f_draw_reopen_count": self._f_draw_reopen_count,
            "f_draw_backoff_until": self._f_draw_backoff_until,
            "executed_actions": self._panel_executed_actions,
            "confirmed_actions": self._panel_confirmed_actions,
            "closing_attempts": self._panel_closing_attempts,
            "pending_action": self._panel_pending_choice_action,
        }

    def _panel_roi_region(self, frame: Frame) -> np.ndarray | None:
        """面板中央三选区域（帧内坐标）——WAIT_MUTATION 的像素 mutation 对比。"""
        if frame.bgr is None or frame.bgr.size == 0 or frame.width < 100 or frame.height < 100:
            return None
        x1 = int(frame.width * 0.24)
        y1 = int(frame.height * 0.16)
        x2 = int(frame.width * 0.76)
        y2 = int(frame.height * 0.66)
        roi = frame.bgr[y1:y2, x1:x2]
        return roi if roi.size > 0 else None

    def _panel_physical_fingerprint(self, frame: Frame) -> str | None:
        """计算面板中央三选区域的真实物理图像指纹（MD5 摘要）。"""
        roi = self._panel_roi_region(frame)
        if roi is None:
            return None
        from shuabao.interaction_surface import compute_frame_roi_fingerprint
        return compute_frame_roi_fingerprint(roi)

    def _verify_action_mutation(self, frame: Frame) -> bool:
        """Alias for _panel_mutation_confirmed verifying post-action frame mutation."""
        return self._panel_mutation_confirmed(frame)

    def _panel_mutation_confirmed(self, frame: Frame) -> bool:
        """WAIT_MUTATION 后置确认：面板中央区域内容相对点击前 baseline 发生变化。"""
        baseline = self._panel_mutation_baseline
        if baseline is None:
            return False
        roi = self._panel_roi_region(frame)
        if roi is None or roi.shape != baseline.shape:
            return True  # 尺寸变化本身即画面异变
        if self._hero_changed_pixels(baseline, roi) >= 2000:
            return True
        if getattr(self, "_panel_pending_choice_action", None) == "refresh":
            cur_fp = self._panel_physical_fingerprint(frame)
            prev_fp = getattr(self, "_choice_fp_before_refresh_physical", None)
            if cur_fp and prev_fp and cur_fp != prev_fp:
                return True
        return False

    def _panel_f1_shadow_record(self, would_trigger: bool, correct: bool | None) -> None:
        """F1 兜底 shadow 灰度：累计 20 次正确、0 误触才写 LIVE 标志。

        - would_trigger=True 且 correct=True → correct+1；correct=False → 误触清零；
        - 每 panel episode 最多一次（_panel_f1_used_this_episode 守卫）；
        - F1 不得用于 UNKNOWN/无 anchor（调用方保证）。
        """
        if not would_trigger:
            return
        if self._f1_live:
            return
        if correct is None:
            # 生产 shadow：只记录候选（无法即时判定正确性），不改变计数
            return
        if correct:
            self._f1_shadow_correct += 1
            self._f1_shadow_misfire = 0
            if self._f1_shadow_correct >= 20:
                print("[L1] F1 兜底 shadow 累计 20 次正确、0 误触，允许 LIVE")
                self._f1_live = True
        else:
            self._f1_shadow_correct = 0
            self._f1_shadow_misfire += 1
            print(f"[L1] F1 兜底 shadow 误触（累计 {self._f1_shadow_misfire} 次），清零并保持关闭")

    def _panel_anchor_confirmed(self, anchor: MatchResult) -> bool:
        """P0-3（215302）：自然面板进入需同类型锚点连续 2 帧，或单帧 score ≥0.85。

        旧行为：单帧贴阈值锚点（0.742 bond_refresh_btn / 0.799 card_hide）即进入
        面板处理，检测空洞期间脚本盲点进化、恢复后又因单一弱锚点误入面板。
        本门闩跨 tick 保留锚点类型；类型漂移或锚点消失（调用方清零）即重置。
        """
        # 旧版通用隐藏按钮容易在低分辨率文字页面上稳定误命中：
        # skill_panel_video_zero_input.png（852x480，非游戏 HUD）连续两帧均把
        # skill_hide 误报为 0.719。连续出现只能证明画面稳定，不能把弱模板升级
        # 成动作权限；legacy hide 必须先达到独立的 0.75 置信下限。
        if anchor.name in {"skill_hide", "card_hide", "hide"} and anchor.score < 0.75:
            self._panel_anchor_candidate = None
            return False
        if anchor.score >= 0.85:
            self._panel_anchor_candidate = (anchor.name, anchor.score)
            return True
        cand = self._panel_anchor_candidate
        if cand is not None and cand[0] == anchor.name:
            self._panel_anchor_candidate = (anchor.name, anchor.score)
            return True
        self._panel_anchor_candidate = (anchor.name, anchor.score)
        return False

    def _hitch_fail_close_choice_panel(self, frame: Frame, now: float) -> bool:
        """跟车/蹭车局内选择面板立即关闭；零刷新、零挑选。处理了本 tick 则 True。"""
        if not self._passive_choice_mode():
            return False
        if self._passenger_mode() and self._panel_kind == "treasure":
            return False
        close_kind = self._panel_kind if self._panel_kind in ("skill", "bond", "treasure", "card") else None
        close_hit = self._close_current_panel(frame, close_kind)
        if close_hit is not None:
            name = (close_hit.name or "").lower()
            if "refresh" in name or "giveup" in name:
                close_hit = None
        if close_hit is not None:
            print("[L1] lobby_hitch 选择面板 Fail-Closed 关闭（不刷新、不挑选）")
            if self.act_click(close_hit, "HitchPanelFailClosed"):
                self._selection_click_cooldown_until = now + self.settings.ui_action_interval_s
                kind = self._panel_kind or "skill"
                self._stage_panel_choice_action("close", (kind, close_hit.name))
                self._panel_state = PanelState.WAIT_MUTATION
                self._panel_mutation_baseline = self._panel_roi_region(frame)
                self._panel_last_input_at = now
                self._panel_cooldown_until[kind] = now + self.settings.ui_action_interval_s
                self._panel_opened_by_us = None
            return True
        print("[L1] lobby_hitch 选择面板 Fail-Closed（零挑选零刷新）")
        self._finish_panel_episode()
        return True

    def _tick_panel_fsm(self, frame: Frame, anchor: MatchResult | None, now: float) -> LoopAction | None:
        """S0 ⑤ 面板会话 FSM：CLOSED→OPEN_REQUESTED→WAIT_VISIBLE→ACTIVE→
        WAIT_MUTATION→CLOSING→COOLDOWN。

        强失败/断线在全部状态抢占（_tick_impl 先于本 FSM 执行）；round hard
        deadline 在所有非恢复状态抢占（_tick_main_line 顶部）。
        """
        st = self._panel_state

        # S0.5 Episode Liveness & Hard Deadline 守护（非 CLOSED/COOLDOWN 状态生效）
        if st not in (PanelState.CLOSED, PanelState.COOLDOWN):
            if self._panel_episode_started is not None:
                episode_duration = now - self._panel_episode_started
                hard_deadline = self._panel_hard_deadline_s
                if episode_duration >= hard_deadline:
                    print(f"[L1] 面板 episode {self._panel_episode_id or ''} ({self._panel_kind}) 超时 "
                          f"{episode_duration:.1f}s >= {hard_deadline:.1f}s 无有效进展，强制脱困")
                    self._record_fail_closed_incident(
                        f"panel_episode_timeout: kind={self._panel_kind} "
                        f"ep_id={self._panel_episode_id} duration={episode_duration:.2f}s"
                    )
                    kind = self._panel_kind or "unknown"
                    if kind in ("skill", "bond", "treasure"):
                        self._panel_episode_count[kind] = self._panel_episode_count.get(kind, 0) + 1
                    self._panel_opened_by_us = None
                    self._skill_refresh_attempts = 0
                    self._panel_episode_started = None
                    if self._passenger_mode() and anchor is not None:
                        print(f"[L1] 蹭车面板超时脱困但画面仍有锚点，转 CLOSING 物理隐藏面板避免遮挡主线")
                        self._panel_state = PanelState.CLOSING
                        self._panel_closing_attempts = 0
                        self._panel_closing_started_at = now
                        return LoopAction.Continue
                    self._panel_state = PanelState.COOLDOWN
                    self._panel_cooldown_until[kind] = now + self.settings.ui_action_interval_s
                    return LoopAction.Continue

        if st == PanelState.CLOSED:
            if anchor is None or anchor.score < 0.70:
                self._panel_anchor_candidate = None
                return None
            if not self._panel_anchor_confirmed(anchor):
                print(f"[L1] 面板锚点 {anchor.name} {anchor.score:.3f} 待双帧确认")
                return LoopAction.Continue
            kind = self._panel_kind_of(frame, anchor)
            if (
                kind in ("skill", "bond", "treasure")
                and self._panel_episode_count.get(kind, 0)
                >= self.settings.panel_episode_limit_per_kind
            ):
                # 遮挡面板达到 episode 上限：不再用 float("inf") 永久冻结。
                # 蹭车模式：放弃选择面板时必须点"暂时隐藏"并以面板消失为后置条件，绝不能直接 finish 放行主线遮挡画面；
                # 非蹭车模式：60s 长冷却后归位。
                self._panel_kind = kind
                self._panel_opened_by_us = None
                self._skill_refresh_attempts = 0
                if self._passenger_mode():
                    print(f"[L1] 蹭车 {kind} episode 上限已达 ({self._panel_episode_count.get(kind, 0)} >= {self.settings.panel_episode_limit_per_kind})，"
                          f"转 CLOSING 物理隐藏面板避免遮挡主线")
                    self._panel_state = PanelState.CLOSING
                    self._panel_closing_attempts = 0
                    self._panel_closing_started_at = now
                    return LoopAction.Continue
                self._panel_state = PanelState.COOLDOWN
                self._panel_cooldown_until[kind] = now + 60.0
                print(f"[L1] {kind} natural episode 上限已达，进入 60s 冷却（本局不再重入）")
                return LoopAction.Continue
            self._enter_panel_episode(frame, anchor, kind, opened=False)
            # 自然面板：本 tick 直接进入 ACTIVE 处理
            st = self._panel_state

        if st == PanelState.OPEN_REQUESTED:
            # 已按 G/F/V：2s 可见窗内零动作（不得下一 tick 反点关闭）
            self._panel_state = PanelState.WAIT_VISIBLE
            self._panel_visible_deadline = now + self.settings.panel_visible_timeout_s
            return LoopAction.Continue

        if st == PanelState.WAIT_VISIBLE:
            if anchor is not None:
                kind = self._panel_kind_of(frame, anchor)
                if self._panel_opened_by_us == "treasure" and kind != "treasure":
                    print(f"[L1] 按 V 后检测到非宝物面板（{kind}），撤销主动宝物打开标记")
                    self._panel_opened_by_us = None
                self._enter_panel_episode(frame, anchor, kind, opened=bool(self._panel_opened_by_us == kind))
                print(f"[L1] 主动面板 {kind} 已可见（{self.settings.panel_visible_timeout_s}s 窗内）")
            elif now >= self._panel_visible_deadline:
                print(f"[L1] 主动面板 {self._panel_kind} 可见窗超时，没有中央面板，转入下一步")
                self._l1_cycle_selected = False
                self._panel_state = PanelState.COOLDOWN
                kind = self._panel_kind
                if self._passenger_mode() and kind == "treasure":
                    # V without a panel is the game's "宝物选择次数不足":
                    # normal, not a failure.  Retry after new choices had
                    # time to accrue instead of burning the per-round cap.
                    self._hitch_treasure_retry_at = now + self._HITCH_TREASURE_RETRY_S
                    self._panel_cooldown_until[kind] = now + self._L1_PANEL_REOPEN_INTERVAL_S
                    cur_kills = self._merchant_kill_balance(frame)
                    if cur_kills is not None:
                        self._hitch_last_treasure_kill_balance = cur_kills
                elif kind in ("skill", "bond", "treasure") and not self._passenger_mode():
                    # Solo: G/V without points and F without wood simply do not
                    # open.  Counting that as an abnormal episode (08-29
                    # 59563fd) capped the panel after 5 presses (live 000229).
                    self._panel_cooldown_until[kind] = now + self.settings.ui_action_interval_s
                    if kind == "bond":
                        self._bond_idle_until = now + self._BOND_IDLE_BACKOFF_S
                    elif kind == "skill":
                        self._skill_idle_until = now + self._SKILL_IDLE_BACKOFF_S
                elif kind in ("skill", "bond", "treasure"):
                    self._panel_episode_count[kind] = self._panel_episode_count.get(kind, 0) + 1
                    self._panel_cooldown_until[kind] = now + self._L1_PANEL_REOPEN_INTERVAL_S
                self._panel_opened_by_us = None
                return LoopAction.Continue
            else:
                return LoopAction.Continue  # 零动作等待可见
            st = self._panel_state

        if st == PanelState.ACTIVE:
            if anchor is None:
                # 面板已自然消失（episode 结束）
                self._finish_panel_episode()
                return LoopAction.Continue
            if self._hitch_fail_close_choice_panel(frame, now):
                return LoopAction.Continue
            if (
                self._l1_cycle_owned_panel
                and self._panel_kind == self._l1_cycle_step
                and self._panel_kind in ("skill", "bond", "treasure")
                and self._l1_step_visit_exhausted(now)
            ):
                wood = getattr(self, "_wood_balance", None)
                if self._panel_kind == "bond" and (wood is None or wood < self._BOND_HIGH_WOOD):
                    self._bond_idle_until = now + self._BOND_IDLE_BACKOFF_S
                print(f"[L1] {self._panel_kind} 单次停留已达成功选择/时间上限，转 CLOSING 收口推进下一步")
                self._panel_visit_force_advance = True
                self._panel_state = PanelState.CLOSING
                self._panel_closing_attempts = 0
                self._panel_closing_started_at = now
                return LoopAction.Continue
            if now < self._selection_click_cooldown_until:
                print("[L1] 选择面板等待输入间隔…")
                return LoopAction.Continue
            # 同 fingerprint 同动作 ≤ panel_action_limit_per_fingerprint 次
            choice = self._find_reward_choice(frame, anchor=anchor)
            if choice is None and self._choice_policy_idle:
                # 策略明确 WAIT：本 tick 零输入，不走关闭/未知超时收口。
                self._choice_policy_idle = False
                print(f"[L1] 选卡策略本 tick 零输入（{self._choice_policy_last_reason or 'WAIT'}）")
                return LoopAction.Continue
            if choice:
                kind, hit = choice
                fingerprint = (kind, hit.name, hit.screen_x // 8, hit.screen_y // 8)
                is_refresh_action = "refresh" in str(kind).lower() or "refresh" in str(hit.name).lower()
                if fingerprint == self._panel_fingerprint and not is_refresh_action:
                    self._panel_fingerprint_attempts += 1
                else:
                    self._panel_fingerprint = fingerprint
                    self._panel_fingerprint_attempts = 1
                if self._panel_fingerprint_attempts == 3:
                    # 同一选择连续 2 次点击无页面变化 → 归档证据
                    self._record_repeat_click(frame, choice, self._panel_fingerprint_attempts)
                if self._panel_fingerprint_attempts > self.settings.panel_action_limit_per_fingerprint:
                    # 同指纹同动作超限：严格进入 CLOSING 转物理关闭并收敛冷却，不再盲点
                    print(f"[L1] 同一选择连续 {self.settings.panel_action_limit_per_fingerprint} 次无画面变化，"
                          f"面板转 CLOSING 物理关闭避免活锁")
                    self._panel_state = PanelState.CLOSING
                    self._panel_closing_attempts = 0
                    self._panel_closing_started_at = now
                    self._panel_opened_by_us = None
                    if kind == "skill":
                        self._skill_refresh_attempts = 0
                        self._skill_idle_until = now + self._SKILL_IDLE_BACKOFF_S
                    elif kind == "bond":
                        self._bond_idle_until = now + self._BOND_IDLE_BACKOFF_S
                    else:
                        self._skill_refresh_attempts = 0
                    return LoopAction.Continue
                action_kind = self._panel_choice_action_kind(hit.name)
                if kind == "treasure":
                    if action_kind == "refresh":
                        action_label = "treasure刷新"
                    elif action_kind == "close":
                        action_label = "treasure关闭"
                    else:
                        action_label = "treasure选择"
                        cur_fp = self._panel_physical_fingerprint(frame)
                        if cur_fp is not None and cur_fp == getattr(self, "_hitch_last_treasure_unconfirmed_fp", None):
                            print(f"[L1] 宝物面板物理指纹（{cur_fp}）与上次未确认选卡一致，拒绝重复点击同一未响应面板，转 CLOSING")
                            self._panel_state = PanelState.CLOSING
                            self._panel_closing_attempts = 0
                            self._panel_closing_started_at = now
                            self._panel_opened_by_us = None
                            self._skill_refresh_attempts = 0
                            return LoopAction.Continue
                else:
                    action_label = f"{kind}选择"
                print(f"[L1] 动作派发: {action_label} [{hit.name}] score={hit.score:.3f} @ {hit.center}")
                clicked = self.act_click(hit, action_label)
                if not clicked and self._last_input_dispatched_unverified():
                    # 点击已注入，只是后置窗口校验没过（2026-09-09 tick 464 暴怒神符）。
                    # 当作已发出：进 WAIT_MUTATION 走后置确认，不再对同一张卡重复点。
                    print(f"[L1] {action_label}点击已注入但窗口后置未验证，转 WAIT_MUTATION 后置确认")
                    self._panel_mutation_baseline = self._panel_roi_region(frame)
                    self._panel_state = PanelState.WAIT_MUTATION
                    self._panel_confirm_window = max(
                        5.0, min(15.0, self.settings.recovery_timeout_s)
                    )
                    self._panel_last_input_at = now
                    self._selection_click_cooldown_until = now + self.settings.ui_action_interval_s
                    self._stage_panel_choice_action(
                        action_kind, fingerprint
                    )
                    if kind == "treasure" and action_kind == "select":
                        self._hitch_last_treasure_unconfirmed_fp = self._panel_physical_fingerprint(frame)
                        cur_kills = self._merchant_kill_balance(frame)
                        if cur_kills is not None:
                            self._hitch_last_treasure_kill_balance = cur_kills
                    self._panel_opened_by_us = None
                    return LoopAction.Continue
                if clicked:
                    # 成功执行的选卡/刷新/放弃/关闭动作才计入尝试预算（WAIT/被拒不加）。
                    self._bump_choice_attempts()
                    self._panel_executed_actions += 1
                    self._panel_last_progress_at = now
                    self._stage_panel_choice_action(action_kind, fingerprint)
                    # 技能选卡点击成功只暂存；必须等 mutation/面板消失后才记为已学。
                    if action_kind == "select" and kind == "技能" and self._is_skill_card_click(hit.name):
                        self._stage_skill_card(hit.name)
                    if action_kind == "select" and kind == "羁绊":
                        self._stage_bond_card(hit.name)
                    if action_kind == "select" and getattr(self, "_evolve_awaiting_hero_pick", False):
                        self._complete_evolve_hero_pick()
                    self._selection_click_cooldown_until = now + self.settings.ui_action_interval_s
                    self._panel_last_input_at = now
                    if "refresh" in (hit.name or "").lower():
                        self._choice_fp_before_refresh_physical = self._panel_physical_fingerprint(frame)
                        self._panel_mutation_baseline = self._panel_roi_region(frame)
                        self._panel_state = PanelState.WAIT_MUTATION
                        self._panel_confirm_window = max(
                            5.0, min(15.0, self.settings.recovery_timeout_s)
                        )
                        self._panel_opened_by_us = "skill" if kind == "skill" else None
                    else:
                        self._panel_mutation_baseline = self._panel_roi_region(frame)
                        self._panel_state = PanelState.WAIT_MUTATION
                        self._panel_confirm_window = max(
                            5.0, min(15.0, self.settings.recovery_timeout_s)
                        )
                        if kind == "treasure" and action_kind == "select":
                            self._hitch_last_treasure_unconfirmed_fp = self._panel_physical_fingerprint(frame)
                            cur_kills = self._merchant_kill_balance(frame)
                            if cur_kills is not None:
                                self._hitch_last_treasure_kill_balance = cur_kills
                        self._panel_opened_by_us = None
                self._selection_unknown_attempts = 0
                self._selection_unknown_since = None
                self._main_line_since = now
                return LoopAction.Continue

            # 无候选：只记录 shadow。未分类面板属于 UNKNOWN，必须零输入；
            # 不能用物理 F1 把“识别失败”变成点击/按键权限。
            if not self._panel_f1_used_this_episode:
                self._panel_f1_used_this_episode = True
                self._panel_f1_shadow_record(True, None)
                print("[L1] 未分类面板：记录 F1 shadow，保持零输入")
            self._selection_unknown_since = self._selection_unknown_since or now
            elapsed = now - self._selection_unknown_since
            # 不再零输入等到 10s unknown timeout（R8-REVIEW）。
            opened_by_us = getattr(self, "_panel_opened_by_us", None)
            if opened_by_us:
                close_hit = self._close_current_panel(frame)
                close_reason = "CloseSelfOpenedPanel"
            elif self._panel_kind in ("bond", "card"):
                close_hit = self.find(
                    frame,
                    ["card_hide", "bond_hide_btn"],
                    threshold=self.settings.match_threshold,
                    scales=self._hot_scales(),
                    roi=self._PANEL_BUTTONS_ROI,
                    early_stop=True,
                )
                close_reason = "CloseNaturalPanel"
            else:
                close_hit = None
                close_reason = "CloseSelfOpenedPanel"
            if close_hit is not None and close_hit.name == "hide_fallback":
                close_hit = None
            if close_hit is None and opened_by_us and elapsed >= 2.0:
                close_hit = self._hide_fallback_hit(frame, self._panel_kind)
                close_reason = "CloseFallback"
            if close_hit is not None:
                print(f"[L1] 面板无法匹配卡牌，点击关闭 {close_hit.name} ({close_reason})")
                if self.act_click(close_hit, close_reason):
                    self._bump_choice_attempts()
                    self._panel_executed_actions += 1
                    self._panel_last_progress_at = now
                    self._stage_panel_choice_action("close", (self._panel_kind, close_hit.name))
                    self._selection_click_cooldown_until = now + self.settings.ui_action_interval_s
                    self._panel_state = PanelState.WAIT_MUTATION
                    self._panel_mutation_baseline = self._panel_roi_region(frame)
                    self._panel_last_input_at = now
                self._panel_opened_by_us = None
                self._selection_unknown_attempts = 0
                self._selection_unknown_since = None
                return LoopAction.Continue
            if elapsed >= 3.0:
                if self.find_scene(frame, "giveup"):
                    return LoopAction.Continue
                # 20260822：删除「吞吐量优先」的 3s 品质盲选与固定坐标推进
                # （实机 trace 与用户反馈均证实盲选=乱拿；AGENTS.md Fail-Closed：
                # UNKNOWN 屏态零输入）。未知面板由 episode hard deadline
                # （panel_hard_deadline_s，默认 10s）强制 COOLDOWN 脱困，
                # run 不中断、也不产生任何盲点输入。
                print(f"[L1] 当前选择无配置命中（已等 {elapsed:.0f}s），保持零输入等待…")
                return LoopAction.Continue
            print(f"[L1] 当前选择无配置命中（已等 {elapsed:.0f}s），保持零输入等待…")
            return LoopAction.Continue
        if st == PanelState.WAIT_MUTATION:
            if anchor is None:
                # 面板消失是最强消费/关闭证据；此时才确认 semantic action。
                self._panel_confirmed_actions += 1
                self._panel_last_progress_at = now
                self._confirm_panel_choice_action(now)
                self._commit_pending_skill_cards()
                self._commit_pending_bond_cards()
                self._finish_panel_episode()
                return LoopAction.Continue
            if self._panel_pending_choice_action == "close":
                # 关闭动作必须以面板完全消失（anchor is None）为后置条件，不能仅因画面扰动就重返 ACTIVE
                if now - self._panel_last_input_at >= self._panel_confirm_window:
                    print("[L1] 关闭动作确认窗超时，面板仍未消失，转 CLOSING 重试物理关闭")
                    self._panel_state = PanelState.CLOSING
                    self._panel_closing_attempts = 0
                    self._panel_closing_started_at = now
                return LoopAction.Continue
            if self._panel_mutation_confirmed(frame):
                # 内容变化（新候选/选卡消费/关闭过渡）后才确认成功。
                self._panel_confirmed_actions += 1
                self._panel_last_progress_at = now
                self._confirm_panel_choice_action(now)
                self._commit_pending_skill_cards()
                self._commit_pending_bond_cards()
                self._panel_state = PanelState.ACTIVE
                self._panel_mutation_baseline = None
                return LoopAction.Continue
            if now - self._panel_last_input_at >= self._panel_confirm_window:
                failed_action = self._expire_panel_choice_action()
                self._clear_pending_skill_cards()
                self._panel_mutation_baseline = None
                if failed_action == "select":
                    # Real-machine 2026-08-16: SendInput returned success while
                    # bond card stayed visible. Never hammer the same slot again;
                    # close this stale episode physically, then the reopen cooldown
                    # gives the UI/resource state time to settle.
                    print("[L1] 选卡点击未观察到 mutation；禁止重复同槽，转物理关闭")
                    self._panel_state = PanelState.CLOSING
                    self._panel_closing_attempts = 0
                    self._panel_closing_started_at = now
                elif failed_action == "refresh":
                    self._skill_refresh_failed_attempts = getattr(self, "_skill_refresh_failed_attempts", 0) + 1
                    print(f"[L1] 刷新点击未观察到 mutation（第 {self._skill_refresh_failed_attempts} 次失败）；不消耗刷新预算")
                    if self._skill_refresh_failed_attempts >= 2:
                        print("[L1] 刷新连续 2 次无 mutation 响应，放弃刷新，转物理关闭")
                        self._panel_state = PanelState.CLOSING
                        self._panel_closing_attempts = 0
                        self._panel_closing_started_at = now
                    else:
                        self._panel_state = PanelState.ACTIVE
                else:
                    print("[L1] 面板 mutation 确认窗超时，回到 ACTIVE（零输入）")
                    self._panel_state = PanelState.ACTIVE
            return LoopAction.Continue

        if st == PanelState.CLOSING:
            self._panel_closing_attempts += 1
            if self._panel_closing_started_at is None:
                self._panel_closing_started_at = now
            closing_elapsed = now - self._panel_closing_started_at
            close_hit = self._close_current_panel(frame, self._panel_kind)
            if close_hit is None:
                if self._panel_closing_attempts >= 3 or closing_elapsed >= 3.0:
                    print(f"[L1] CLOSING 状态无法找到关闭锚点（{self._panel_closing_attempts} 次 / "
                          f"{closing_elapsed:.1f}s 超时），强制进入 COOLDOWN 避免活锁")
                    self._panel_state = PanelState.COOLDOWN
                    kind = self._panel_kind or "unknown"
                    if kind in ("skill", "bond", "treasure"):
                        self._panel_episode_count[kind] = self._panel_episode_count.get(kind, 0) + 1
                    self._panel_cooldown_until[kind] = now + self.settings.ui_action_interval_s
                    self._panel_opened_by_us = None
                    return LoopAction.Continue
                return LoopAction.Continue  # 零动作等待明确 close 锚点
            if self.act_click(close_hit, "PanelClose"):
                self._panel_executed_actions += 1
                self._panel_last_progress_at = now
                self._stage_panel_choice_action("close", (self._panel_kind, close_hit.name))
                self._panel_state = PanelState.WAIT_MUTATION
                self._panel_last_input_at = now
                self._panel_mutation_baseline = self._panel_roi_region(frame)
                self._selection_click_cooldown_until = now + self.settings.ui_action_interval_s
            return LoopAction.Continue

        if st == PanelState.COOLDOWN:
            if anchor is None and not self._passenger_mode():
                # The per-kind reopen gate (_panel_cooldown_until) still holds
                # this panel back; everything else on the HUD may run.  Live
                # 000229: a 60s bond cooldown froze skills/V/evolve/merchant.
                self._finish_panel_episode()
                return None
            if now >= self._panel_cooldown_until.get(self._panel_kind, 0):
                if self._passenger_mode() and anchor is not None:
                    print(f"[L1] 蹭车 COOLDOWN 到期但面板仍未消失，转 CLOSING 物理关闭避免遮挡主线")
                    self._panel_state = PanelState.CLOSING
                    self._panel_closing_attempts = 0
                    self._panel_closing_started_at = now
                    return LoopAction.Continue
                self._finish_panel_episode()
                return None  # 落到无面板链
            return LoopAction.Continue

        return None

    def _record_round_timeout_incident(self) -> None:
        """S0.5：round hard deadline 到期归档。"""
        if self._archiver is None:
            return
        frame = self._last_frame
        if frame is None or frame.bgr is None or frame.bgr.size == 0:
            return
        saved = self._archiver.maybe_record(
            frame_before=self._prev_frame,
            frame_now=frame,
            metadata=self._incident_meta(
                "round_timeout",
                "round hard deadline expired",
                final_action="quit",
                deadline=self._round_deadline,
            ),
            healthy=True,
            health_issues=[],
            health_details="",
        )
        if saved is not None:
            self._incident_pending_fp = saved
            if self._tick_reason is None:
                self._tick_reason = "incident_write"

    def _observe_secret_realm_entry(self, frame: Frame, now: float, post_game: str | None) -> LoopAction:
        """Observe the post-confirmation transition without granting input.

        A single HUD-looking frame is not enough to prove that the great-rift
        confirmation actually entered a new round.  The pending post-game
        route stays latched until two distinct ``no post-game + HUD`` frames
        arrive.  Any modal/UNKNOWN/interruption frame resets that latch.
        """
        started = self._secret_realm_entering_since
        if started is None:
            return LoopAction.Continue
        elapsed = now - started
        timeout = max(3.0, min(float(self.settings.query_timeout), 15.0))
        if now < self._secret_realm_confirm_next_observe_at:
            print("[med] 等待大秘境局内 HUD（零动作）")
            return LoopAction.Continue

        frame_id = id(frame)
        if (
            post_game is not None
            or not self._post_game_pending
            or not self._is_in_game_hud(frame)
        ):
            self._secret_realm_hud_confirmations = 0
            self._secret_realm_last_hud_frame_id = frame_id
        elif frame_id != self._secret_realm_last_hud_frame_id:
            self._secret_realm_last_hud_frame_id = frame_id
            self._secret_realm_hud_confirmations += 1

        if self._secret_realm_hud_confirmations >= 2:
            self._secret_realm_active = True
            self._secret_realm_request_pending = False
            self._secret_realm_request_since = None
            self._secret_realm_request_attempts = 0
            self._secret_realm_next_observe_at = 0.0
            self._secret_realm_entering_since = None
            self._secret_realm_confirm_attempts = 0
            self._secret_realm_hud_confirmations = 0
            self._secret_realm_last_hud_frame_id = None
            self._post_game_pending = False
            self._hitch_postgame_started_at = None
            self._post_game_close_attempts = 0
            self._post_game_route = "secret"
            self._victory_continue_attempts = 0
            self._victory_continue_since = None
            self._round_started_at = now
            self._round_deadline = now + self.settings.round_timeout_s
            self._main_line_since = now
            print("[med] 大秘境局内 HUD 连续两帧确认，恢复局内循环；失败后沿原退出重开链处理")
            return LoopAction.Continue

        if elapsed >= timeout:
            if self._unattended_recovery_enabled():
                return self._abandon_secret_realm("确认后未出现连续局内 HUD")
            print("[med] 大秘境确认后未出现连续局内 HUD，Fail-Closed 停止运行")
            self.set_phase(Phase.ERROR, "great rift entry verification timeout")
            self.stop()
            return LoopAction.Break
        print("[med] 大秘境载入中，等待连续局内 HUD（零动作）")
        return LoopAction.Continue

    def _abandon_secret_realm(self, why: str) -> LoopAction:
        """Unattended: a secret-realm step we cannot prove ends this round.

        The round itself was won (the rift is only offered after Victory), so
        the outcome stays VICTORY; the exit chain then leaves the game and the
        next round starts as usual instead of stopping the whole run.
        """
        print(f"[med] 大秘境{why}：放弃本局秘境，退出当前局（不停整个运行）")
        self._record_environment_incident("secret_realm_abandoned", 0.0)
        self._secret_realm_request_pending = False
        self._secret_realm_request_since = None
        self._secret_realm_request_attempts = 0
        self._secret_realm_next_observe_at = 0.0
        self._secret_realm_entering_since = None
        self._secret_realm_confirm_attempts = 0
        self._secret_realm_hud_confirmations = 0
        self._secret_realm_last_hud_frame_id = None
        self._post_game_pending = False
        self._record_round_outcome(RoundOutcome.VICTORY, f"secret realm abandoned: {why}")
        self.set_phase(Phase.QUIT, f"secret realm abandoned: {why}")
        return LoopAction.Continue

    def _observe_round_id(self) -> str:
        """观测记录的分局键。局未开始时归到 lobby，不与任何一局混账。"""
        started = getattr(self, "_round_started_at", None)
        return "lobby" if started is None else f"r{int(started * 1000)}"

    def _observe_log(self):
        """惰性取观测记录器；关闭时永远返回 None，且只判定一次。"""
        log = self._observe
        if log is not None:
            return None if getattr(log, "disabled", False) else log
        if self._observe_ready:
            return None
        self._observe_ready = True
        try:
            from shuabao import observe_log as _ol

            if not _ol.observe_enabled():
                return None
            self._observe = _ol.ObserveLog()
            print("[med][observe] 局内观测记录器已开启（只读，零输入）")
            return self._observe
        except Exception as exc:
            print(f"[med][observe] 记录器初始化失败，保持关闭：{exc}")
            return None

    def _observe_tick(self) -> None:
        """每个 MAIN_LINE tick 记一次资源与编排。默认关闭时是一次属性读。"""
        log = self._observe_log()
        if log is None:
            return
        try:
            target, reason = getattr(self, "_observe_plan", (None, ""))
            log.note_tick(
                round_id=self._observe_round_id(),
                round_elapsed_s=self._round_elapsed_s(),
                phase=getattr(getattr(self, "phase", None), "name", ""),
                cycle_step=getattr(self, "_l1_cycle_step", None),
                wood=getattr(self, "_wood_balance", None),
                skill_points=getattr(self, "_skill_points_seen", None),
                treasure_count=getattr(self, "_treasure_pending_seen", None),
                plan_target=target,
                plan_reason=reason,
            )
        except Exception as exc:
            print(f"[med][observe] tick 记录失败，跳过：{exc}")

    def _tick_main_line(self, frame: Frame) -> LoopAction:
        now = time.time()
        self._observe_tick()
        secret_entry_observation = self._secret_realm_entering_since is not None
        if not secret_entry_observation and self._hitch_enabled():
            event = classify_hitch_ocr(self._hitch_ocr_text())
            if event:
                return self._hitch_reset_lobby(event, now)

        # G0 P0 contract：post-game outcome authority（POST_VICTORY / ARCHIVE /
        # NPC / PAUSED 等）必须在压力门禁之前观察。压力尚未完成不得遮蔽
        # victory/failure；强失败/断线全局抢占仍在 _tick_impl 更早处。
        post_game = self._post_game_state(frame)
        if (
            getattr(self, "_time_cave_boss_clicked_at", None) is not None
            and post_game in {"HEIRLOOM_DIALOG", "NPC_HUB"}
        ):
            self._time_cave_boss_done = True
            self._time_cave_boss_clicked_at = None

        # The hard round deadline owns every MAIN_LINE page.  It must run
        # before repeatable chat/pressure inputs, otherwise a persistent
        # pressure button can return early forever after the deadline.
        if not secret_entry_observation and self._round_deadline is not None and now >= self._round_deadline:
            print(f"[med] round hard deadline 到期（{self.settings.round_timeout_s}s），记录 TIMEOUT 并转 QUIT")
            self._record_round_outcome(RoundOutcome.TIMEOUT, "round deadline")
            self._record_round_timeout_incident()
            self.invalidate_evidence("round-deadline")
            self.set_phase(Phase.QUIT, "round deadline expired")
            return LoopAction.Continue

        if not secret_entry_observation and self._unattended_recovery_enabled() and (
            post_game is not None or self._post_game_pending
        ):
            if post_game == "POST_VICTORY" and (
                getattr(self, "_hitch_heirloom_exit_since", None)
                or getattr(self, "_solo_heirloom_boss_waiting", False)
            ):
                # The heirloom Boss's own Victory opens a new post-game
                # transaction; the old budget (from the first Victory, kept
                # across the heirloom wait) would quit before the rift.
                self._hitch_postgame_started_at = now
            if self._hitch_postgame_started_at is None:
                self._hitch_postgame_started_at = now
            elif now - self._hitch_postgame_started_at >= self._HITCH_POSTGAME_HARD_CAP_S:
                why = f"post-game UI {self._HITCH_POSTGAME_HARD_CAP_S:.0f}s hard cap"
                print(f"[med] 战后界面总预算到期，转 QUIT（{why}）")
                self._record_round_outcome(RoundOutcome.TIMEOUT, why)
                self.set_phase(Phase.QUIT, why)
                return LoopAction.Continue
        elif (
            not secret_entry_observation
            and self._unattended_recovery_enabled()
            and not self._hitch_heirloom_exit_since
        ):
            # A one-frame false candidate must not age the next real
            # post-game transaction.  Heirloom plaza/instance observation
            # keeps the same budget until its own 60/120s rule resolves.
            self._hitch_postgame_started_at = None

        if not secret_entry_observation and self._passenger_mode():
            # An open chat input swallows clicks under it and every hotkey;
            # close it before any other in-game input.
            chat_res = self._maybe_close_game_chat(frame, now)
            if chat_res is not None:
                return chat_res
        if (
            not secret_entry_observation
            and self._hitch_enabled()
            and post_game is None
        ):
            # 用户规则（2026-09-12）：画面里只要有压力转移按钮，永远先点它；
            # 没有按钮就不等待，自动任务、四挑战等照常进行（中途接管、按钮已
            # 自动关闭的局也不会卡死）。必须在所有局内分发之前检查。
            pt_res = self._maybe_click_hitch_pressure_transfer(frame, now)
            if pt_res is not None:
                return pt_res

        # ---- 专属动作后置条件等待 (PendingAction Active Waiting) ----
        if self._pending_action is not None:
            if self._pending_action.is_confirmed(frame):
                print(f"[med][pending] 后置动作验证成功: {self._pending_action.kind} ({self._pending_action.target_id})")
                self._pending_action = None
            elif self._pending_action.is_expired(now):
                print(f"[med][pending] 后置动作验证超时: {self._pending_action.kind} ({self._pending_action.target_id})")
                self._pending_action_unconfirmed_count += 1
                # B2: timeout -> clear, apply target cooldown, record unconfirmed metric, do not advance state blindly
                if self._pending_action.target_id == "hero_card_item" or self._pending_action.kind == "WAIT_HERO_CHOICE":
                    self._inventory_next_at = now + 1.0
                    # 20260822：验证超时必须同时清掉等待标志，否则残留的
                    # _evolve_awaiting_hero_pick 会让进化兜底在普通面板上盲点。
                    self._evolve_awaiting_hero_pick = False
                elif self._pending_action.target_id == "danGif" or self._pending_action.kind == "WAIT_DEVOUR_DAN":
                    self._devour_dan_next_at = now + 1.0
                elif self._pending_action.target_id == "equipment_upgrade" or self._pending_action.kind == "EQUIPMENT_UPGRADE":
                    self._equipment_pending_until = now + 1.0
                self._pending_action = None
        if (
            not secret_entry_observation
            and self._unattended_recovery_enabled()
            and getattr(self, "_solo_heirloom_boss_waiting", False)
            and post_game != "POST_VICTORY"
        ):
            waiting_since = getattr(self, "_solo_heirloom_boss_waiting_since", None)
            if waiting_since is None:
                self._solo_heirloom_boss_waiting_since = now
                waiting_since = now
            is_clear = self._solo_heirloom_boss_is_clear(frame)
            is_alive = self._solo_boss_is_alive(frame)
            timeout = (now - waiting_since) >= self._SOLO_HEIRLOOM_EXIT_S
            if is_alive:
                if timeout:
                    print(
                        f"[med] 单人传家宝 Boss 达到 {self._SOLO_HEIRLOOM_EXIT_S:.0f}s 但画面仍有明确 ALIVE 证据，"
                        f"否决秘境流转，保持零输入观察"
                    )
                else:
                    print(
                        f"[med] 单人传家宝 Boss 处于 ALIVE 战斗中，保持零输入观察 "
                        f"(已等待 {now - waiting_since:.1f}s/{self._SOLO_HEIRLOOM_EXIT_S:.0f}s)"
                    )
                return LoopAction.Continue
            if not is_clear and not timeout:
                print(f"[med] 单人传家宝 Boss 仍未确认结束，保持零输入观察 (已等待 {now - waiting_since:.1f}s/{self._SOLO_HEIRLOOM_EXIT_S:.0f}s)")
                return LoopAction.Continue
            self._solo_heirloom_boss_waiting = False
            self._solo_heirloom_boss_waiting_since = None
            self._hitch_heirloom_exit_since = None
            self._hitch_postgame_started_at = now
            if timeout and not is_clear:
                outcome_reason = "solo heirloom boss timeout fallback"
                print(f"[med] 单人传家宝 Boss 等待 {self._SOLO_HEIRLOOM_EXIT_S:.0f}s 超时未见掉落且无 ALIVE 证据，超时兜底流转（非 Boss CLEAR）")
            else:
                outcome_reason = "solo heirloom boss clear"
                print("[med] 单人传家宝 Boss 已清除（掉落代理确认）")
            if self.settings.auto_secret_realm:
                print(f"[med] 进入大秘境路线 ({outcome_reason})")
                self._post_game_pending = True
                self._post_game_route = "secret"
                self._secret_realm_request_pending = False
                self._secret_realm_request_since = None
                self._secret_realm_request_attempts = 0
                self._secret_realm_next_observe_at = 0.0
                return LoopAction.Continue
            print(f"[med] 退出当前局 ({outcome_reason})")
            self._record_round_outcome(RoundOutcome.VICTORY, outcome_reason)
            self.set_phase(Phase.QUIT, outcome_reason)
            return LoopAction.Continue
        if (
            not secret_entry_observation
            and self._unattended_recovery_enabled()
            and getattr(self, "_hitch_heirloom_exit_since", None)
            and self._passenger_mode()
        ):
            # User rule (2026-09-12) after the heirloom Boss is sent:
            #   1. the right-side equipment list and still on the plaza -> exit;
            #   2. 60s on the plaza -> exit;
            #   3. a failed game exits through the failure chain.
            # Teleported into 秘境 / 团本 -> never exit here; that run ends
            # in its own failure (or victory) page, which exits as usual.
            # Solo (user, 2026-09-14): the same rule with a 120s window; with
            # auto_secret_realm the trigger arms the rift instead of exiting
            # and the heirloom Victory then continues into it (bounded 2x).
            window = self._heirloom_exit_window_s()
            if not self._follow_enabled() and self._hitch_left_plaza(frame):
                self._hitch_postgame_started_at = None
                if not getattr(self, "_hitch_instance_announced", False):
                    self._hitch_instance_announced = True
                    print("[med] 传家宝后画面已离开战后广场（秘境/团本），暂不退出，等失败/胜利页再退")
            else:
                # Rules 1/2 need the plaza on screen: an off-plaza frame may be
                # the first of a teleport still being judged.  Neither plaza
                # nor instance for another full window (a screen we can't
                # read) still exits.
                on_plaza = self._follow_enabled() or self._top_bar_mode(frame) == "plaza"
                loot = on_plaza and self._heirloom_loot_popup_visible(frame)
                waited = now - float(self._hitch_heirloom_exit_since)
                timer_due = waited >= window and (on_plaza or waited >= 2 * window)
                if self._solo_heirloom_secret():
                    if loot or timer_due:
                        # Solo has no heirloom Victory page (live 2026-09-14
                        # f0570-f0584: the Boss dies on the plaza and the game
                        # stays there), so the trigger goes straight to the
                        # rift NPC via the NPC_HUB "secret" route.
                        trigger = "掉落已确认" if loot else f"已等 {window:.0f}s"
                        print(f"[med] 单人传家宝{trigger}，已开自动秘境：去大秘境 NPC 开启秘境")
                        self._hitch_heirloom_exit_since = None
                        self._passenger_heirloom_for_secret = False
                        self._post_game_pending = True
                        self._post_game_route = "secret"
                        self._secret_realm_request_pending = False
                        self._secret_realm_request_since = None
                        self._secret_realm_request_attempts = 0
                        self._secret_realm_next_observe_at = 0.0
                        self._hitch_postgame_started_at = now
                        return LoopAction.Continue
                elif loot:
                    if self._follow_enabled() and self.settings.auto_secret_realm:
                        self._hitch_heirloom_exit_since = None
                        self._passenger_heirloom_for_secret = True
                        print("[med] 跟车已确认传家宝掉落，等待 Victory 后继续秘境")
                        return LoopAction.Continue
                    why = "heirloom loot popup"
                    print(f"[med] 传家宝后退出：{why}")
                    self._hitch_heirloom_exit_since = None
                    self._record_round_outcome(RoundOutcome.VICTORY, why)
                    self.set_phase(Phase.QUIT, why)
                    return LoopAction.Continue
                elif timer_due:
                    if self._follow_enabled() and self.settings.auto_secret_realm:
                        print("[med] 跟车传家宝掉落未识别，继续等待 Victory/失败，不提前退出")
                        return LoopAction.Continue
                    why = f"heirloom {window:.0f}s timeout"
                    print(f"[med] 传家宝后退出：{why}")
                    self._hitch_heirloom_exit_since = None
                    self._record_round_outcome(RoundOutcome.TIMEOUT, why)
                    self.set_phase(Phase.QUIT, why)
                    return LoopAction.Continue
        if (
            self._passenger_mode()
            and post_game is None
            and self._find_exit_confirm(frame) is not None
        ):
            # A 退出游戏 confirmation we did not open (our own exit runs in
            # QUIT/NEXT) is the player's: leave it alone.  Live 2026-09-12 it
            # was misread as the rift dialog and "cancelled".
            print("[med] 局内出现非脚本打开的退出确认框，零输入（不替玩家取消）")
            return LoopAction.Continue
        if self._passenger_heirloom_for_secret and post_game is None:
            return LoopAction.Continue

        fail_gift = None if secret_entry_observation else self._find_failure_gift(frame)
        if fail_gift is not None:
            print(f"[med] 拦截到失败结算奖励弹窗 @ {fail_gift.center}，点击关闭")
            self.act_click(fail_gift, "DismissFailureReward")
            return LoopAction.Continue
        # 若没有弹窗（_panel_state == CLOSED），但右下角未检测到英雄操作/技能/神符面板，
        # 说明视角或焦点未锁定在英雄上，主动发送 F1 键切回英雄操作面板。

        # 战后页面优先于一切局内动作。胜利后只允许以下专用链：
        # 继续游戏 → 关闭存档面板（如出现）→ NPC 广场 → 局内退出。
        # Once the great-rift “是” click is accepted, every subsequent frame
        # is observation-only until the dedicated two-frame HUD postcondition
        # below is proven.  This guard must precede all post-game handlers so
        # an unexpected modal cannot trigger a second click.
        if self._secret_realm_entering_since is not None:
            return self._observe_secret_realm_entry(frame, now, post_game)
        if (
            self._passenger_mode()
            and post_game is None
            and not self._is_in_game_hud(frame)
            and self._host_choosing_difficulty(frame)
        ):
            # Pre-round stage lobby of a guest: the round has not started, so
            # none of the in-game gates (pressure, auto-task fuse) may run.
            # Hitch goes back to ROOM_WAITING so the real round entry passes
            # the room -> in-game edge that arms the pressure gate.
            print("[med] 乘客模式：游戏内等待 1 号位选择难度（零输入）")
            if self._hitch_enabled():
                self.set_phase(Phase.ROOM_WAITING, "guest waits for player 1 difficulty")
            return LoopAction.Continue
        # The bag page covers the post-game controls it opened over.  Live
        # 2026-09-11 it hid the archive plaza after ContinueGame, so the page
        # never classified and the chain waited with zero input.  Close it on
        # every post-game surface, and while the post-continue page is still
        # unconfirmed.
        bag_blocks_post_game = post_game in {
            "NPC_HUB", "POST_VICTORY", "ARCHIVE_PANEL", "HEIRLOOM_DIALOG",
        } or (post_game is None and getattr(self, "_post_game_pending", False))
        if self._unattended_recovery_enabled() and bag_blocks_post_game:
            bag_open = self._bag_layout(frame) is not None
            fsm = self._public_bag_fsm
            if bag_open:
                if fsm.phase is PublicBagPhase.CLOSE_REQUESTED:
                    self._public_bag_fsm = fsm.observe(now, bag_visible=True)
                    return LoopAction.Continue
                why = {
                    "POST_VICTORY": "胜利页",
                    "NPC_HUB": "战后广场",
                    "ARCHIVE_PANEL": "存档面板",
                    "HEIRLOOM_DIALOG": "传家宝弹窗",
                }.get(post_game, "战后转场")
                print(f"[med] {why}背包仍开着，先关闭以免挡住继续游戏/NPC")
                if self._toggle_bag_page(frame, "PublicBackpackClose"):
                    self._public_bag_fsm = PublicBagFSM(
                        deposits=fsm.deposits,
                        aborts=fsm.aborts,
                    ).request_close(now)
                return LoopAction.Continue
            if fsm.phase is PublicBagPhase.CLOSE_REQUESTED:
                self._public_bag_fsm = fsm.observe(now, bag_visible=False)
        # 结算面板关闭后有一个短暂的“存档”过渡帧：旧分类器可能暂时既
        # 识别不到 ARCHIVE_PANEL，也还没识别成 NPC_HUB。此时不能被选关页
        # 误判抢先退出，否则传家宝入口永远没有机会点击。优先保留已确定
        # 的 heirloom/archive 路由，等广场锚点出现后由下方统一入口点击。
        # 放在关背包之后：背包盖住广场时入口不可见，先关背包。
        if (
            self._passenger_mode()
            and post_game is None
            and self._post_game_pending
            and getattr(self, "_post_game_route", "") in {"archive", "heirloom"}
            and (
                self._top_bar_mode(frame) == "plaza"
                or self.find_scene(frame, "archive") is not None
            )
        ):
            route = getattr(self, "_post_game_route", "")
            entry = self._post_game_hub_entry_click(frame, route)
            if entry is not None:
                reason = "OpenArchiveChallenges" if route == "archive" else "OpenHeirloomChallenges"
                print(f"[med] 战后过渡帧确认广场入口：打开{('存档' if route == 'archive' else '传家宝')}挑战 @ {entry.center}")
                if self.act_click(entry, reason):
                    self._post_game_route = f"{route}_active"
                    self._main_line_since = now
            else:
                print(f"[med] 战后{route}路由仍在过渡帧，等待广场入口（零动作）")
            return LoopAction.Continue
        if (
            self._passenger_mode()
            and post_game is None
            and not self._is_in_game_hud(frame)
            and self._find_stage_page(frame)
            # The top-bar mode label (存档/团本) only exists inside a game.
            # Live 2026-09-14 f0353/f0707: the post-game plaza read as a
            # stage page and quit before the heirloom click / 60s rule; the
            # real stage pages (f0034/f0410) carry no mode label.
            and self._top_bar_mode(frame) is None
        ):
            if self._hitch_pending_room_key is not None:
                self._hitch_blacklisted_room_keys.add(self._hitch_pending_room_key)
            print("[med] hitch 误开选关/游戏大厅，退出当前游戏")
            self.set_phase(Phase.QUIT, "hitch misopened stage page")
            return LoopAction.Continue
        if post_game == "ARCHIVE_PANEL" and self._post_game_archive_pending_only:
            if frame is getattr(self, "_prev_frame", None):
                print("[med] 存档 pending+X 捕获未变化，不计入第二帧（零动作）")
                return LoopAction.Continue
            self._pending_archive_panel_frames += 1
            if self._pending_archive_panel_frames < 2:
                print("[med] 存档面板仅有 pending+X 候选第 1 帧，等待不同捕获证据（零动作）")
                return LoopAction.Continue
        else:
            self._pending_archive_panel_frames = 0

        awaiting_challenge_hud = (
            self._post_game_pending
            and post_game is None
            and getattr(self, "_post_game_route", "") in {"archive_active", "heirloom_active", "boss_active"}
        )
        challenge_hud = awaiting_challenge_hud and self._is_in_game_hud(frame)
        if challenge_hud:
            if frame is getattr(self, "_prev_frame", None):
                print("[med] 战后挑战 HUD 捕获未变化，不计入第二帧（零动作）")
                return LoopAction.Continue
            self._post_game_hud_confirmations += 1
            if self._post_game_hud_confirmations < 2:
                print("[med] 战后挑战目的地 HUD 候选第 1 帧，等待不同捕获证据（零动作）")
                return LoopAction.Continue
            route = getattr(self, "_post_game_route", "")
            print(f"[med] 战后挑战目的地 HUD 连续两帧确认（{route}），恢复既有局内循环")
            self._post_game_pending = False
            self._hitch_postgame_started_at = None
            self._post_game_close_attempts = 0
            self._post_game_hud_confirmations = 0
            if route != "boss_active":
                self._post_game_route = "archive"
            if route == "heirloom_active":
                # 下一次胜利重新从存档挑战 1/8 开始；本轮游标仍保留在 trace。
                self._archive_challenge_index = 0
                self._archive_challenge_clicked = set()
                self._archive_challenge_verified = set()
                self._archive_verify_started = False
                self._archive_challenge_next_at = 0.0
            return LoopAction.Continue
        if not challenge_hud:
            self._post_game_hud_confirmations = 0
        if (
            self.settings.auto_secret_realm
            and self._post_game_pending
            and self._secret_realm_request_pending
            and self._secret_realm_request_since is not None
            and now - self._secret_realm_request_since >= max(3.0, min(float(self.settings.query_timeout), 15.0))
            and post_game != "NPC_HUB"
        ):
            if self._unattended_recovery_enabled():
                print("[med] 大秘境请求未回到 NPC 广场，保持零输入等待页面归类（不退出当前局）")
                return LoopAction.Continue
            print("[med] 大秘境请求超时，Fail-Closed 停止运行")
            self.set_phase(Phase.ERROR, "secret realm request timeout")
            self.stop()
            return LoopAction.Break

        if not post_game and self._round_tail_checks_active():
            # A live Boss challenge may still show the archive label in the
            # map HUD. It is not an unverified post-game entry until Victory
            # has actually been observed.
            if (
                not getattr(self, "_post_game_pending", False)
                and getattr(self, "_post_game_route", "") not in {"boss_active", "archive", "archive_active", "heirloom", "heirloom_active"}
                and self.find_scene(frame, "archive")
            ):
                if self._unattended_recovery_enabled():
                    print("[med] 识别到未验证战后入口 archive，保持零输入观察（不直接停机）")
                    return LoopAction.Continue
                print("[med] 识别到未验证战后入口 archive，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "unverified archive entry")
                self.stop()
                return LoopAction.Break
            if getattr(self, "_post_game_route", "") != "boss_active" and self.find_scene(frame, "boss_entry"):
                # 20260822：同 S0⑧ 门控——boss_entry 是 Boss 挑战入口，不 ERROR。
                return self._maybe_challenge_configured_boss(frame, now)
        for dialog in self._aux_dialog_attempts:
            if post_game != dialog:
                self._aux_dialog_attempts[dialog] = 0
        if post_game != "PAUSED" and int(getattr(self, "_pause_resume_attempts", 0) or 0) > 0:
            # 后置确认：暂停锚点消失（用户手动恢复或我们的点击生效）→ 清计数回主线。
            print("[med] 暂停已恢复（暂停锚点消失确认），回到主线任务判断")
            self._pause_resume_attempts = 0
            self._pause_resume_next_at = 0.0
            self._main_line_since = now
        if post_game == "PAUSED":
            self._main_line_since = now
            return self._maybe_resume_paused(frame, now)
        if post_game == "POST_VICTORY":
            if self._unattended_recovery_enabled() and (
                getattr(self, "_hitch_heirloom_exit_since", None)
                or getattr(self, "_solo_heirloom_boss_waiting", False)
            ):
                self._hitch_heirloom_exit_since = None
                self._solo_heirloom_boss_waiting = False
                if self._follow_enabled() and self.settings.auto_secret_realm:
                    self._passenger_heirloom_for_secret = True
                    print("[med] 跟车传家宝 Victory 已确认，继续游戏后进入秘境")
                elif self._solo_heirloom_secret():
                    self._passenger_heirloom_for_secret = True
                    print("[med] 单人传家宝 Victory 已确认，继续游戏后进入秘境")
                else:
                    print("[med] 传家宝后出现胜利页，直接退出当前游戏")
                    self._record_round_outcome(RoundOutcome.VICTORY, "heirloom victory")
                    self.set_phase(Phase.QUIT, "heirloom victory")
                    return LoopAction.Continue
            # "Continue already clicked" needs our click on record.  Live
            # 2026-09-12 12:13: the victory banner animates over the archive
            # panel, which classified ARCHIVE_PANEL first and set the pending
            # flag; the finished victory page then read as "clicked, waiting"
            # with no click time, so the wait never timed out and 继续游戏 was
            # never pressed.
            if self._post_game_pending and self._victory_continue_since is not None:
                elapsed = now - self._victory_continue_since
                if elapsed >= min(self.settings.query_timeout, 30):
                    if self._unattended_recovery_enabled():
                        print("[med] 继续游戏后胜利页仍在，重新武装有界点击并继续观察")
                        self._post_game_pending = False
                        self._victory_continue_attempts = 0
                        self._victory_continue_since = None
                        return LoopAction.Continue
                    print("[med] 继续游戏后胜利页未消失，Fail-Closed 停止运行")
                    self.set_phase(Phase.ERROR, "victory page did not close")
                    self.stop()
                    return LoopAction.Break
                print("[med] 已点击继续游戏，等待胜利页消失（零动作）")
                return LoopAction.Continue

            if self._victory_continue_attempts >= 3:
                if self._unattended_recovery_enabled():
                    print("[med] 继续游戏重试预算耗尽，重新武装并保持运行")
                    self._victory_continue_attempts = 0
                    return LoopAction.Continue
                print("[med] 胜利结算点击继续游戏重试已达上限，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "victory continue attempts exhausted")
                self.stop()
                return LoopAction.Break

            hit = self.find(frame, ["continueGame"], threshold=0.80, scales=self._hot_scales(), roi=(0.40, 0.50, 0.65, 0.75))
            if not hit:
                return LoopAction.Continue
            self._victory_continue_attempts += 1
            print(f"[med] 胜利结算 点击继续游戏 @ {hit.center} (尝试 {self._victory_continue_attempts}/3)")
            if self.act_click(hit, "ContinueGame"):
                if self._panel_state != PanelState.CLOSED:
                    self._finish_panel_episode()
                route_before_continue = getattr(self, "_post_game_route", "archive")
                self._post_game_pending = True
                # A real Boss challenge owns the post-victory transition. Do
                # not reopen archive/heirloom just because those labels happen
                # to be visible after Continue. Secret-realm entry, when
                # enabled, is handled by the existing NPC_HUB branch below.
                if self._passenger_heirloom_for_secret:
                    self._post_game_route = "secret"
                    self._passenger_heirloom_for_secret = False
                else:
                    self._post_game_route = (
                        "boss_postgame"
                        if route_before_continue == "boss_active"
                        else "archive"
                    )
                # A previous mid-round Boss probe must not consume the
                # post-game page's independent configured-Boss observation
                # budget.
                self._boss_challenge_attempts = 0
                self._boss_challenge_scroll_attempts = 0
                self._boss_challenge_scroll_signature = None
                self._boss_challenge_scroll_stable_frames = 0
                self._boss_challenge_next_at = 0.0
                if route_before_continue != "boss_active":
                    self._time_cave_boss_done = False
                self._victory_continue_since = now
                self._main_line_since = now
            return LoopAction.Continue

        if post_game == "ARCHIVE_PANEL":
            if not self._post_game_pending:
                if self._unattended_recovery_enabled():
                    print("[med] 未经胜利页直接识别到存档挑战页，接管战后链并继续")
                    self._post_game_pending = True
                    self._post_game_route = "archive"
                    return LoopAction.Continue
                print("[med] 非胜利链路进入存档面板，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "unexpected archive panel")
                self.stop()
                return LoopAction.Break
            if self._team_mode_enabled() and not self._hitch_postgame_hero_selected:
                if self.act_key("F1", "HitchPostGameSelectOwnHero"):
                    self._hitch_postgame_hero_selected = True
                    self._archive_challenge_next_at = now + self._post_game_action_recheck()
                return LoopAction.Continue
            if getattr(self, "_post_game_route", "") == "boss_active":
                if self._passenger_mode():
                    # 20260910 hitch: 点了时光之穴后面板还在，旧逻辑永久零输入
                    # 等 HUD，存档窗关不上，传家宝 NPC 永远走不到。
                    print("[med] 时光之穴点击后仍在存档面板，关闭面板并转传家宝")
                    self._post_game_route = "archive"
                    self._time_cave_boss_done = True
                else:
                    print("[med] 时光之穴 Boss 已发起，等待存档面板消失和局内 HUD（零动作）")
                    return LoopAction.Continue
            clicked_at = getattr(self, "_time_cave_boss_clicked_at", None)
            if clicked_at is not None:
                if now - clicked_at < 1.0:
                    print("[med] 时光之穴 Boss 点击后等待列表变化（零动作）")
                    return LoopAction.Continue
                self._time_cave_boss_clicked_at = None
                print("[med] 时光之穴 Boss 点击后列表未变化，重新定位卡位")
            # 存档面板的八个挑战先逐项尝试；这不会复制生产策略，只消费已分类
            # 页面上的稳定卡位。完成八卡后先尝试时光之穴 Boss，全部完成后关闭面板并转传家宝。
            archive_action = self._maybe_click_archive_challenge(frame, now)
            if archive_action is not None:
                if self._archive_challenge_index < len(self._ARCHIVE_CHALLENGE_NAMES):
                    return archive_action
                if getattr(self, "_post_game_route", "") == "archive_active":
                    self._post_game_route = "archive"
                return archive_action
            # 蹭车战后链即使没有预设，也必须在时光之穴探底后选物理最后卡；
            # 普通刷图无预设时维持既有“关存档面板→退局”流程。
            sgzx_boss_cfg = str(getattr(self.settings, "sgzx_boss", "") or "").strip()
            needs_time_cave_boss = bool(sgzx_boss_cfg or self._passenger_mode())
            if needs_time_cave_boss and not getattr(self, "_time_cave_boss_done", False):
                if now < self._boss_challenge_next_at:
                    return LoopAction.Continue
                boss_action = self._maybe_challenge_configured_boss(frame, now)
                if getattr(self, "_time_cave_boss_done", False):
                    return LoopAction.Continue
                if boss_action is not None:
                    return boss_action
                # boss_action is None：入口或卡面本 tick 未能识别，计入观察预算。
                self._time_cave_boss_search_attempts += 1
                if self._boss_challenge_attempts >= 3 or self._time_cave_boss_search_attempts >= 5:
                    print("[med] 时光之穴 Boss 未能识别或确认，跳过该步并继续关闭存档面板")
                    self._time_cave_boss_done = True
                    self._boss_challenge_attempts = 0
                    self._time_cave_boss_search_attempts = 0
                    self._post_game_route = "archive"
                    # 落到下方 _find_archive_panel_close 关闭存档面板
                else:
                    return LoopAction.Continue

            if self._post_game_close_attempts >= 3:
                if self._unattended_recovery_enabled():
                    print("[med] 存档面板关闭重试预算耗尽，重新武装并继续等待专用关闭按钮")
                    self._post_game_close_attempts = 0
                    return LoopAction.Continue
                print("[med] 存档面板关闭重试已达上限，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "archive close attempts exhausted")
                self.stop()
                return LoopAction.Break
            close_hit = self._find_archive_panel_close(frame)
            if not close_hit:
                print("[med] 存档面板未找到专用关闭按钮，零动作等待")
                return LoopAction.Continue
            self._post_game_close_attempts += 1
            cjb_boss_cfg = str(getattr(self.settings, "cjb_boss", "") or "").strip()
            self._post_game_route = "heirloom" if (cjb_boss_cfg or self._passenger_mode()) else "npc_hub"
            print(f"[med] 存档与时光之穴完成，关闭存档面板 @ {close_hit.center} (尝试 {self._post_game_close_attempts}/3) 并转 {self._post_game_route}")
            self.act_click(close_hit, "CloseArchivePanel")
            return LoopAction.Continue
        if post_game == "NPC_HUB":
            if not self._post_game_pending:
                if self._unattended_recovery_enabled():
                    print("[med] 未经胜利页直接识别到战后挑战广场，接管存档→传家宝链")
                    self._post_game_pending = True
                    self._post_game_route = "archive"
                    return LoopAction.Continue
                print("[med] 非胜利链路进入挑战广场，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "unexpected post-game NPC hub")
                self.stop()
                return LoopAction.Break
            if self._secret_realm_entering_since is not None:
                # The real recording briefly returns one NPC-hub frame after
                # clicking “是” and before the rift HUD appears.  During this
                # transition a second right-click would reopen the dialog and
                # corrupt an otherwise successful entry.
                elapsed = now - self._secret_realm_entering_since
                timeout = max(3.0, min(float(self.settings.query_timeout), 15.0))
                if elapsed >= timeout:
                    if self._unattended_recovery_enabled():
                        return self._abandon_secret_realm("确认后仍停留挑战广场")
                    print("[med] 大秘境确认后仍停留挑战广场，Fail-Closed 停止运行")
                    self.set_phase(Phase.ERROR, "great rift entry remained on npc hub")
                    self.stop()
                    return LoopAction.Break
            f1_action = self._maybe_ensure_post_game_hero_focus(frame, now)
            if f1_action is not None:
                return f1_action
            route = getattr(self, "_post_game_route", "secret")
            if route == "boss_postgame" and self._team_mode_enabled():
                if not self._hitch_postgame_returned_to_base:
                    if self.act_key("F2", "HitchPostBossReturnOwnBase"):
                        self._hitch_postgame_returned_to_base = True
                        cjb_boss_cfg = str(getattr(self.settings, "cjb_boss", "") or "").strip()
                        self._post_game_route = "heirloom" if cjb_boss_cfg else "team_wait_exit"
                    return LoopAction.Continue
                self._post_game_route = "team_wait_exit"
                route = "team_wait_exit"
            if route == "team_wait_exit":
                return self._wait_for_team_post_game_exit(frame, now)
            if route in {"archive", "heirloom"}:
                entry = self._post_game_hub_entry_click(frame, route)
                if entry is None:
                    print(f"[med] 挑战广场未找到{route}入口锚点，零动作等待")
                    return LoopAction.Continue
                reason = "OpenArchiveChallenges" if route == "archive" else "OpenHeirloomChallenges"
                print(f"[med] 战后顺序：打开{('存档' if route == 'archive' else '传家宝')}挑战 @ {entry.center}")
                if self.act_click(entry, reason):
                    self._post_game_route = f"{route}_active"
                    self._main_line_since = now
                return LoopAction.Continue
            if route in {"archive_active", "heirloom_active"}:
                if getattr(self, "_post_game_active_wait_since", None) is None:
                    self._post_game_active_wait_since = now
                if now - self._post_game_active_wait_since > 3.0:
                    print(f"[med] 等待{('存档' if route == 'archive_active' else '传家宝')}面板超时，重置路由避免死锁")
                    self._post_game_route = "archive" if route == "archive_active" else "heirloom"
                    self._post_game_active_wait_since = None
                else:
                    print(f"[med] 已请求{('存档' if route == 'archive_active' else '传家宝')}挑战，等待页面切换（零动作）")
                return LoopAction.Continue
            else:
                self._post_game_active_wait_since = None
            if self.settings.auto_secret_realm and not self._hitch_enabled():
                # Three walks to the NPC plus the wait after the last one.
                timeout = max(
                    3.0,
                    min(float(self.settings.query_timeout), 15.0),
                    3 * self._RIFT_NPC_WALK_S + 2.0,
                )
                if self._secret_realm_request_since is None:
                    self._secret_realm_request_since = now
                elapsed = now - self._secret_realm_request_since
                # Let the hero arrive after each right-click before judging it,
                # including the third one.
                if now < self._secret_realm_next_observe_at and elapsed < timeout:
                    print("[med] 已右键大秘境 NPC，英雄走向 NPC，等待确认框（零动作）")
                    return LoopAction.Continue
                if self._secret_realm_request_attempts >= 3 or elapsed >= timeout:
                    if self._unattended_recovery_enabled():
                        # A right-click only proves that SendInput accepted it;
                        # it does not prove the hero reached the NPC. Keep the
                        # rift route alive, then retry a small batch after a
                        # quiet cooldown. The round deadline remains the only
                        # normal terminal bound for an unconfirmed request.
                        self._secret_realm_request_attempts = 0
                        self._secret_realm_request_since = now
                        self._secret_realm_next_observe_at = now + self._RIFT_NPC_RETRY_COOLDOWN_S
                        print("[med] 大秘境 NPC 未出现确认框，15s 零输入后重新尝试（不退出当前局）")
                        return LoopAction.Continue
                    print("[med] 大秘境 NPC 未能打开确认框，Fail-Closed 停止运行")
                    self.set_phase(Phase.ERROR, "great rift npc request timeout")
                    self.stop()
                    return LoopAction.Break
                rift_label = self._find_secret_realm_npc(frame)
                if not rift_label:
                    print("[med] 挑战广场未找到受锚定的大秘境 NPC，零动作等待")
                    return LoopAction.Continue
                rift_npc = self._rift_npc_body_hit(frame, rift_label)
                self._secret_realm_request_attempts += 1
                print(
                    f"[med] 自动秘境开启，右键大秘境 NPC 本体 @ {rift_npc.center} "
                    f"（标签 @ {rift_label.center}，尝试 {self._secret_realm_request_attempts}/3）"
                )
                self._secret_realm_next_observe_at = now + self._RIFT_NPC_WALK_S
                if self.act_right_click(rift_npc, "OpenGreatRift"):
                    self._secret_realm_request_pending = True
                    self._main_line_since = now
                return LoopAction.Continue
            self._post_game_pending = False
            # S0 ⑥：完整胜利链确认点（继续游戏→存档→NPC 广场）→ success+1、streak 清零
            self._record_round_outcome(RoundOutcome.VICTORY, "post-game NPC hub verified")
            self.set_phase(Phase.QUIT, "post-game NPC hub verified")
            return LoopAction.Continue

        if post_game == "HEIRLOOM_DIALOG":
            if getattr(self, "_post_game_route", "") == "boss_active":
                # The close click may take one or more frames to remove the
                # modal. Never click the X again and never treat the lingering
                # panel as a new challenge while the battle route is active.
                print("[med] 传家宝面板关闭过渡中，Boss 挑战进行中（零动作）")
                return LoopAction.Continue
            if getattr(self, "_boss_challenge_page", None) != post_game:
                # The outer dispatch must hand this page its own budget before
                # checking attempts; otherwise an exhausted archive budget
                # skips the handler that would have reset it.
                self._boss_challenge_attempts = 0
                self._boss_challenge_scroll_attempts = 0
                self._boss_challenge_scroll_signature = None
                self._boss_challenge_scroll_stable_frames = 0
                self._boss_challenge_next_at = 0.0
                self._boss_challenge_page = post_game
            heirloom_chain_active = (
                getattr(self, "_post_game_route", "") in {"heirloom", "heirloom_active"}
                and (
                    self._post_game_pending
                    or
                    bool(str(getattr(self.settings, "cjb_boss", "") or "").strip())
                    or self._passenger_mode()
                )
            ) or (
                self._post_game_pending
                and bool(str(getattr(self.settings, "cjb_boss", "") or "").strip())
            )
            if heirloom_chain_active and self._boss_challenge_attempts < 3:
                # The page remains open after a successful click and displays
                # a short “已挑战” toast. Once visible, close the dialog once
                # and continue the already-selected post-game route; before
                # then the configured-Boss handler is observation-only.
                if self._heirloom_boss_result_visible(frame):
                    self._heirloom_boss_result_confirmed = True
                    print("[med] 传家宝 Boss 业务后置确认成功，关闭传家宝面板")
                elif self._heirloom_boss_confirm_expired(now):
                    # 有界收敛：允许关闭，但明确记成未确认，绝不当成功上报。
                    print("[med] 传家宝 Boss 后置确认超时，有界关闭弹窗（记为未确认）")
                else:
                    return self._maybe_challenge_configured_boss(frame, now, recheck_s=1.0)
            attempts = self._aux_dialog_attempts[post_game]
            if attempts >= 3:
                if self._unattended_recovery_enabled():
                    print("[med] 传家宝弹窗关闭重试预算耗尽，重新武装并继续观察")
                    self._aux_dialog_attempts[post_game] = 0
                    return LoopAction.Continue
                print("[med] 传家宝弹窗关闭重试已达上限，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "heirloom dialog close attempts exhausted")
                self.stop()
                return LoopAction.Break
            close_hit = self._find_heirloom_close(frame)
            if not close_hit:
                print("[med] 传家宝弹窗未找到受约束的关闭按钮，零动作等待")
                return LoopAction.Continue
            self._aux_dialog_attempts[post_game] = attempts + 1
            print(f"[med] 关闭传家宝弹窗 @ {close_hit.center} (尝试 {attempts + 1}/3)")
            confirmed_boss = bool(
                self._heirloom_boss_result_visible(frame)
                or getattr(self, "_heirloom_boss_result_confirmed", False)
            )
            if self.act_click(close_hit, "DismissHeirloomDialog"):
                if getattr(self, "_post_game_route", "") == "heirloom_active":
                    if confirmed_boss:
                        self._post_game_route = "boss_active"
                        self._post_game_pending = False
                        self._post_game_close_attempts = 0
                        self._heirloom_boss_result_confirmed = False
                        if self._passenger_mode() and self._unattended_recovery_enabled():
                            self._hitch_heirloom_exit_since = now
                            self._hitch_instance_seen = False
                            self._hitch_instance_frames = 0
                            self._hitch_instance_announced = False
                            then = "进入秘境" if self._solo_heirloom_secret() else "退出"
                            print(
                                f"[med] 传家宝 Boss 已确认发起：广场上识别到装备获取信息立刻{then}，"
                                f"否则 {self._heirloom_exit_window_s():.0f}s 后{then}；进入秘境/团本则等失败再退"
                            )
                        else:
                            self._solo_heirloom_boss_waiting = True
                            self._solo_heirloom_boss_waiting_since = now
                            self._solo_heirloom_boss_clear_frames = 0
                            self._solo_heirloom_boss_clear_last_frame = None
                            print("[med] 单人传家宝 Boss 已确认发起，等待掉落代理证据（零动作）")
                    else:
                        print("[med] 传家宝 Boss 未确认成功，关闭面板后重置路由（不假冒 boss_active）")
                        if self._boss_challenge_attempts >= 3 or getattr(self, "_heirloom_boss_confirm_unconfirmed", False):
                            self._post_game_route = "secret" if self.settings.auto_secret_realm else "npc_hub"
                        else:
                            self._post_game_route = "heirloom"
            self._main_line_since = now
            return LoopAction.Continue

        if post_game == "TQTZ_CONFIRM":
            return self._confirm_tqtz_dialog(frame, now)
        if (
            post_game == "GREAT_RIFT_CONFIRM"
            and not getattr(self, "_great_rift_title_verified", False)
            and self._tqtz_confirm_dialog_expected(frame, now)
        ):
            # Neither title could be read; fall back to our own click context.
            return self._confirm_tqtz_dialog(frame, now)
        if post_game == "GREAT_RIFT_CONFIRM":
            if (
                self.settings.auto_secret_realm
                and not self._secret_realm_request_pending
                and not self._hitch_enabled()
                and (
                    (self._post_game_pending and getattr(self, "_post_game_route", "") == "secret")
                    or (self._solo_heirloom_secret() and getattr(self, "_hitch_heirloom_exit_since", None))
                )
            ):
                # The rift dialog can open before our own right-click (live
                # 2026-09-14 f0584, 37s after the heirloom); on the rift
                # route it is ours to accept, not a stray dialog to cancel.
                print("[med] 秘境路由上出现大秘境确认框，视为本次秘境请求")
                self._hitch_heirloom_exit_since = None
                self._post_game_pending = True
                self._post_game_route = "secret"
                self._secret_realm_request_pending = True
                self._secret_realm_request_since = now
            if (
                self.settings.auto_secret_realm
                and self._post_game_pending
                and self._secret_realm_request_pending
            ):
                started = self._secret_realm_request_since or now
                timeout = max(3.0, min(float(self.settings.query_timeout), 15.0))
                if self._secret_realm_confirm_attempts >= 3 or now - started >= timeout:
                    if self._unattended_recovery_enabled():
                        return self._abandon_secret_realm("确认框“是”超时")
                    self.set_phase(Phase.ERROR, "great rift confirm timeout")
                    self.stop()
                    return LoopAction.Break
                if now < self._secret_realm_confirm_next_observe_at:
                    print("[med] 已确认大秘境，等待确认框消失（零动作）")
                    return LoopAction.Continue
                accept_hit = self._find_great_rift_accept(frame)
                if not accept_hit:
                    print("[med] 大秘境确认框未找到受锚定的“是”按钮，零动作等待")
                    return LoopAction.Continue
                self._secret_realm_confirm_attempts += 1
                print(
                    f"[med] 点击大秘境“是” @ {accept_hit.center} "
                    f"(尝试 {self._secret_realm_confirm_attempts}/3)"
                )
                self._secret_realm_confirm_next_observe_at = now + self.settings.ui_action_interval_s
                if self.act_click(accept_hit, "ConfirmGreatRift"):
                    self._secret_realm_entering_since = now
                    self._secret_realm_hud_confirmations = 0
                    self._secret_realm_last_hud_frame_id = None
                    self._main_line_since = now
                return LoopAction.Continue

            attempts = self._aux_dialog_attempts[post_game]
            if attempts >= 3:
                if self._unattended_recovery_enabled():
                    print("[med] 大秘境确认框取消重试预算耗尽，重新武装并继续观察")
                    self._aux_dialog_attempts[post_game] = 0
                    return LoopAction.Continue
                print("[med] 大秘境确认框取消重试已达上限，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "great rift cancel attempts exhausted")
                self.stop()
                return LoopAction.Break
            cancel_hit = self._find_great_rift_cancel(frame)
            if not cancel_hit:
                print("[med] 大秘境确认框未找到受锚定的“否”按钮，零动作等待")
                return LoopAction.Continue
            self._aux_dialog_attempts[post_game] = attempts + 1
            print(f"[med] 大秘境未满足自动前置，点击“否” @ {cancel_hit.center} (尝试 {attempts + 1}/3)")
            self.act_click(cancel_hit, "CancelGreatRift")
            self._main_line_since = now
            return LoopAction.Continue
        if post_game:
            if self._unattended_recovery_enabled():
                print(f"[med] 遇到未实现战后页面 {post_game}，零输入等待可识别页面")
                return LoopAction.Continue
            print(f"[med] 识别到尚未实现的战后页面 {post_game}，Fail-Closed 停止运行（零输入）")
            self.set_phase(Phase.ERROR, f"unverified post-game page {post_game}")
            self.stop()
            return LoopAction.Break

        if (
            self._post_game_pending
            and getattr(self, "_post_game_route", "") == "heirloom"
        ):
            entry = self._post_game_hub_entry_click(frame, "heirloom")
            if entry is not None:
                print(f"[med] 战后顺序：打开传家宝挑战 @ {entry.center}")
                if self.act_click(entry, "OpenHeirloomChallenges"):
                    self._post_game_route = "heirloom_active"
                    self._main_line_since = now
                return LoopAction.Continue
        # ---- 单界面交互仲裁 (InteractionSurface Arbitration) ----
        has_recovery = (self.phase == Phase.RECOVER_FAILURE) or bool(getattr(self, "_recovery_step", None) and self._recovery_step != "DONE")
        has_affix = self._find_equipment_affix_choice(frame) is not None
        anchor = self._selection_anchor(frame)
        # 20260822（trace 181735 结尾 2.69s 冲突停机）：底部按钮行已定性为
        # skill/bond/treasure/card 的面板绝不可能是进化弹窗——进化弹窗没有
        # 刷新/放弃/隐藏按钮行。此前宝物面板被边缘计数误判成进化弹窗，
        # 与 has_card 互斥 → CONFLICT → 2.5s 后整个运行被 ERROR 停掉。
        _panel_class = self._classify_choice_panel(frame) if anchor else None
        has_hero = bool(
            self._evolve_hero_choice_pending()
            and anchor
            and _panel_class is None
            and self._find_evolution_choice(frame, anchor)
        )
        has_card = (not has_hero) and (bool(anchor) or self._panel_state != PanelState.CLOSED)
        # 商店检测在存在中央选卡/进化/词条弹窗或主线处于前置主动步骤(F/G/V/进化/装备/拾取)时严格抑制，绝不插队抢点击
        mainline_proactive_active = self._l1_cycle_step in ("bond", "skill", "treasure", "evolve", "equipment", "pickup")
        # A visible pressure button already returned above; its absence never
        # holds anything, so only auto-task and the four challenges bootstrap.
        hitch_bootstrap_pending = self._passenger_mode() and (
            not self._auto_task_done
            or len(self._challenge_done) < len(self._challenge_states)
        )
        has_merchant = False if (
            has_card
            or has_hero
            or has_affix
            or mainline_proactive_active
            or hitch_bootstrap_pending
        ) else self._black_merchant_present(frame)

        surface = resolve_interaction_surface(
            recovery_modal=has_recovery,
            hero_choice_modal=has_hero,
            equipment_affix_modal=has_affix,
            center_card_modal=has_card,
            merchant_modal=has_merchant,
        )
        if surface == InteractionSurface.CONFLICT:
            if self._surface_conflict_since is None:
                self._surface_conflict_since = now
            conflict_duration = now - self._surface_conflict_since
            print(f"[med][surface] 检测到互斥弹窗冲突 (CONFLICT)，严格零输入等待下一帧 (INV-CONFLICT-01, elapsed={conflict_duration:.2f}s)")
            # 20260822：冲突不再 2.5s 硬停机（第二局自退的直接根因）。
            # 降级策略：我们自己打开过的面板（G/F/V）拥有最高可信度，
            # 冲突持续超过一个稳定窗后按已知面板类型继续走面板 FSM；
            # 词缀弹窗是游戏强制模态（不选无法继续），检测到即优先处理；
            # 完全未知才在 panel_hard_deadline_s（默认 15s）后 ERROR。
            _opened_kind = getattr(self, "_panel_opened_by_us", None)
            conflict_deadline = max(5.0, float(getattr(self.settings, "panel_hard_deadline_s", 15.0)))
            if conflict_duration >= 2.5 and _opened_kind in ("skill", "bond", "treasure"):
                print(f"[med][surface] 冲突 {conflict_duration:.2f}s：信任已打开的 {_opened_kind} 面板，降级为中心面板处理")
                surface = InteractionSurface.CENTER_CARD_MODAL
                self._surface_conflict_since = None
            elif conflict_duration >= 2.5 and self._find_equipment_affix_choice(frame) is not None:
                print(f"[med][surface] 冲突 {conflict_duration:.2f}s：词缀弹窗为游戏强制模态，优先处理装备词缀")
                surface = InteractionSurface.EQUIPMENT_AFFIX_MODAL
                self._surface_conflict_since = None
            elif conflict_duration >= conflict_deadline:
                if self._passenger_mode():
                    print(f"[med][surface] 蹭车互斥弹窗冲突持续 {conflict_duration:.2f}s，保持零输入等待表面收敛")
                    return LoopAction.Continue
                print(f"[med][surface] 互斥弹窗冲突持续超时 ({conflict_duration:.2f}s >= {conflict_deadline:.2f}s)，记录 incident 并转 Phase.ERROR")
                self.set_phase(Phase.ERROR, f"interaction surface conflict timeout ({conflict_duration:.2f}s)")
                self.stop()
                return LoopAction.Break
            else:
                return LoopAction.Continue
        else:
            self._surface_conflict_since = None
        if surface == InteractionSurface.EQUIPMENT_AFFIX_MODAL:
            affix = self._find_equipment_affix_choice(frame)
            if affix is not None:
                print(f"[L1] 装备十级词缀选择 {affix.name} @ {affix.center}")
                if self.act_click(affix, "SelectEquipmentAffix"):
                    self._equipment_pending_until = 0.0
                    if self._l1_cycle_step == "equipment":
                        self._advance_l1_cycle("equipment")
                    self._main_line_since = now
                return LoopAction.Continue
            return LoopAction.Continue
        elif surface == InteractionSurface.HERO_CHOICE_MODAL:
            # 20260822：_rarity_choice 兜底会在非进化面板上盲点（trace 181735
            # 18:19:41-45 连点 9 次 evolution_card_0_rank_4 实为宝物面板中卡）。
            # 只有真正的进化几何检测失败且无选择面板证据时才允许兜底；
            # 且点击节奏必须尊重 _evolution_next_at 冷却。
            if now < getattr(self, "_evolution_next_at", 0.0):
                return LoopAction.Continue
            evolution_choice = self._find_evolution_choice(frame, anchor)
            if evolution_choice is None and self._classify_choice_panel(frame) is None:
                evolution_choice = self._rarity_choice(frame, "skill")
            if evolution_choice is not None:
                if self.act_click(evolution_choice, "SelectEvolutionCard"):
                    self._evolution_attempts += 1
                    self._evolution_next_at = now + self.settings.ui_action_interval_s
                    self._panel_state = PanelState.CLOSED
                    self._panel_opened_by_us = None
                    self._selection_unknown_attempts = 0
                    self._selection_unknown_since = None
                    self._main_line_since = now
                    self._complete_evolve_hero_pick()
                return LoopAction.Continue
        elif surface == InteractionSurface.CENTER_CARD_MODAL:
            prev_st = self._panel_state
            res = self._tick_panel_fsm(frame, anchor, now)
            if res is not None:
                self._main_line_since = now
                return res
            if prev_st != PanelState.CLOSED and self._panel_state == PanelState.CLOSED:
                self._main_line_since = now
                return LoopAction.Continue
            if self._passenger_mode() and anchor is not None:
                # 蹭车模式：面板未消失严禁穿透到主线 HUD 动作（防止面板遮挡结算/继续游戏）
                return LoopAction.Continue
        elif surface == InteractionSurface.MERCHANT:
            merchant_res = self._maybe_black_merchant(frame)
            if merchant_res is not None:
                self._main_line_since = now
                return merchant_res
        elif surface == InteractionSurface.RECOVERY_MODAL:
            return self._tick_recovery(frame)
        elif surface not in (InteractionSurface.HUD_ONLY, InteractionSurface.MERCHANT):
            return LoopAction.Continue

        # ---- S0 ⑧ 阶段门控：未验证战后入口检查只在局尾窗口触发 ----
        # 正常中段 idle HUD 不再每 tick 支付 archive/boss/longzhu 全帧扫描
        # （N2 waiver 复评项）；longzhu 色相检查已移至 LONGZHU 阶段（_tick_l1_tail）。
        # 20260822：boss_entry 不再 Fail-Closed ERROR——它是传家宝/时光之穴的
        # Boss 挑战入口，配置了挑战 Boss 时必须点（用户核心诉求"提前挑战没点"）。
        # archive 入口保持 ERROR（未验证语义不变）。
        if not anchor and self._round_tail_checks_active():
            if (
                getattr(self, "_post_game_route", "") != "boss_active"
                and getattr(self, "scenes", None)
                and "archive" in self.scenes
                and self.find_scene(frame, "archive")
            ):
                if self._unattended_recovery_enabled():
                    print("[med] 识别到未验证战后入口 archive，保持零输入观察（不直接停机）")
                    return LoopAction.Continue
                print("[med] 识别到未验证战后入口 archive，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "unverified archive entry")
                self.stop()
                return LoopAction.Break
            if (
                getattr(self, "_post_game_route", "") != "boss_active"
                and getattr(self, "scenes", None)
                and "boss_entry" in self.scenes
                and self.find_scene(frame, "boss_entry")
            ):
                return self._maybe_challenge_configured_boss(frame, now)

        # 点击继续游戏后、页面确认前：不认识的页面一律零动作等待，绝不落到
        # 自动任务/挑战/选关分支（防止胜利→大厅过渡期误触）。
        if self._post_game_pending:
            elapsed = now - self._victory_continue_since if self._victory_continue_since else 0.0
            if elapsed >= min(self.settings.query_timeout, 30):
                if self._unattended_recovery_enabled():
                    print("[med] 战后转场超时，保持零输入等待存档面板/挑战广场")
                    return LoopAction.Continue
                print("[med] 继续游戏后未确认到存档面板或挑战广场，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "post-game transition timeout")
                self.stop()
                return LoopAction.Break
            print("[med] 等待继续游戏后的页面确认（零动作）")
            return LoopAction.Continue


        if self._panel_state == PanelState.CLOSED:
            self._selection_unknown_attempts = 0
            self._selection_unknown_since = None
            self._selection_repeat_key = None
            self._selection_repeat_attempts = 0
            self._skill_refresh_attempts = 0
            self._panel_fingerprint = None
            self._panel_fingerprint_attempts = 0

        # Stage rows never grant click authority inside MAIN_LINE.  A genuine
        # stage page is handed back to the guarded L0 state; in-game HUD anchors
        # suppress glyph false positives from task text / Boss countdowns.
        # 20260828（实机 20260828_001049）：本守卫必须先于自动任务门禁——
        # 选关页上永远等不到【自动任务】复选框，旧顺序被门禁 return 阻断，
        # MAIN_LINE 卡死按 F1 直到 LivenessTimeout。
        # A top-bar mode label (存档/团本) proves we are still in a game:
        # live 2026-09-14 f0353 the heirloom plaza read as a stage page and
        # quit 14s into the 60s heirloom wait.
        if (
            self._find_stage_page(frame)
            and not self._is_in_game_hud(frame)
            and self._top_bar_mode(frame) is None
        ):
            self.set_phase(Phase.STAGE_SELECT, "guarded stage page detected from MAIN_LINE")
            return LoopAction.Continue

        if surface == InteractionSurface.HUD_ONLY and not self._is_in_game_hud(frame):
            # No modal is not HUD evidence.  Every opportunistic MAIN_LINE
            # input below must be backed by a positive in-game HUD anchor.
            print("[L1] MAIN_LINE 当前画面无正向 HUD 证据，严格零输入等待")
            return LoopAction.Continue

        # Everything below reads the HUD (auto-task box, challenges, merchant
        # strip, item bar).  A tooltip left by our own last click must not
        # decide those reads.
        park = self._maybe_park_pointer(frame)
        if park is not None:
            return park

        # ---- Boss 提前挑战（中段 HUD 入口，30s 节流 + 有界尝试）----
        # 20260822：boosIcon 等入口图标只出现在 idle HUD 上（无中央面板），
        # 与四挑战开关同一 cadence 纪律；配置了 cjb_boss/sgzx_boss 才扫描。
        if (
            surface == InteractionSurface.HUD_ONLY
            and not anchor
            and not self._post_game_pending
            and getattr(self, "_post_game_route", "") != "boss_active"
            and self._configured_boss_challenge_names()
            and self._boss_challenge_attempts < 3
            and now >= self._boss_challenge_next_at
            and getattr(self, "scenes", None)
            and "boss_entry" in self.scenes
            and self.find_scene(frame, "boss_entry")
        ):
            return self._maybe_challenge_configured_boss(frame, now)

        # 右侧“自动任务”复选框（左键点击）
        auto_res = self._ensure_auto_task_enabled(frame)
        if auto_res is not None:
            self._main_line_since = now
            return auto_res
        if not self._auto_task_done and not self.settings.dry_run and getattr(self.settings, "auto_task", True) and not getattr(self, "_skip_auto_task_gate", False):
            if self._panel_state == PanelState.CLOSED:
                f1_res = self._maybe_ensure_hero_panel_focus(frame, now)
                if f1_res is not None:
                    return f1_res
                print("[L1] 尚未确认【自动任务】已开启，阻断四挑战和其他局内动作")
                return LoopAction.Continue
        # 挑战按钮有自己的模板和自动状态检测，避免固定坐标反复切换开关。
        ch_res = self._ensure_challenge_buttons(frame)
        if ch_res is not None:
            self._main_line_since = now
            return ch_res

        # 自动任务已确认但英雄操作栏仍未出现，同样先 F1 恢复英雄焦点；
        # 否则后续 G/F/V 会落在错误的 UI 层。
        f1_res = self._maybe_ensure_hero_panel_focus(frame, now)
        if f1_res is not None:
            return f1_res
        # P0-01 仲裁：提前挑战服从单界面仲裁，仅在 HUD_ONLY 且无活跃事务时执行
        if self._is_in_game_hud(frame) and not self._has_active_transaction(frame):
            pending_early = self._tick_early_challenge(frame, now)
            if pending_early is not None:
                return pending_early
            tqtz_res = self._maybe_click_tqtz(frame, now)
            if tqtz_res is not None:
                return tqtz_res

        # B3's taskbar OCR also drives the stalled-main-line recovery path.
        # The close-after-5-5 helper performs this same scan when enabled.
        if not (
            getattr(self.settings, "auto_close_main_line", False)
            or getattr(self.settings, "early_challenge", False)
        ):
            self._read_main_line_stage(frame, now)

        # 5-5 完成后取消自动主线挑战（避免挑战 5-10 翻车）
        close_ml_res = self._maybe_close_main_line_after_5_5(frame, now)
        if close_ml_res is not None:
            return close_ml_res

        # F4 是“清除挑战”，不是“压力转移”；蹭车模式在未验证压力转移
        # 按钮锚点前禁止自动按 F4，避免清掉仍可完成的挑战。
        if not self._passenger_mode():
            pressure_res = self._maybe_clear_pressure_monsters(frame, now)
            if pressure_res is not None:
                return pressure_res

        # During the pre-wave setup the game can show its banned-card picker.
        # Pressing F/V there overlays our panel on top of that UI and caused the
        # recorded random-card episode.  Natural reward panels still preempt
        # above; only proactive G/F/V input is delayed.
        if (
            not self.settings.dry_run
            and self._main_line_started_at is not None
            and now - self._main_line_started_at < 20.0
            and not getattr(self.settings, "skip_pre_wave_delay", False)
            and getattr(self.settings, "pre_wave_protection", False)
        ):
            return LoopAction.Continue

        # 我们主动打开的 G/F/V 候选条可能没有中央面板锚点。
        compact_res = self._handle_self_opened_compact_panel(frame)
        if compact_res is not None:
            self._main_line_since = now
            return compact_res

        # 推进装备租约观察确认（使得非 equipment 步骤下的机会强化能够正常结算）
        self._tick_equipment_pending(frame, now)

        # 进化事务管理：feedback_pending 或 awaiting_hero_pick 时独占主线，严禁启动 G/F/V 等新动作
        if self._evolve_hero_choice_pending():
            feedback_res = self._tick_evolve_feedback_pending(frame, now)
            if feedback_res is not None:
                self._main_line_since = now
                return feedback_res
            if getattr(self, "_evolve_awaiting_hero_pick", False):
                if now - getattr(self, "_evolve_awaiting_hero_pick_at", now) >= 15.0:
                    print("[L1] 等待英雄模态弹窗超时(15s)，释放 evolve 事务锁")
                    self._evolve_awaiting_hero_pick = False
                else:
                    return LoopAction.Continue

        if (
            not self._passenger_mode()
            and self._panel_state == PanelState.CLOSED
            and anchor is None
            and not self._has_active_transaction(frame)
            and surface == InteractionSurface.HUD_ONLY
        ):
            # HUD Opportunistic 微操：神器 CD 到期独立触发
            artifact_res = self._maybe_fire_artifacts(frame)
            if artifact_res is not None:
                self._main_line_since = now
                return artifact_res

            # 吞噬丹在羁绊卡位充足时安全使用
            if (
                self.settings.auto_devour_dan
                and self._can_consume_inventory_swallow_pill(frame)
                and now >= getattr(self, "_devour_dan_next_at", 0.0)
            ):
                dan_res = self._maybe_use_inventory_item(frame)
                if dan_res is not None:
                    self._main_line_since = now
                    return dan_res

            # 溢出安全拾取：非 pickup 轮换步时，当物品栏溢出且背包有空位触发 [Z]
            if (
                self._l1_cycle_step != "pickup"
                and now >= self._pickup_next_at
                and self._hud_item_bar_overflowed(frame)
                and self._pickup_bag_has_space(frame)
            ):
                pickup_button = self._hud_hotkey_button(frame, "bag/hud_pickup_button")
                picked = (
                    self.act_click(pickup_button, "Pickup-Z")
                    if pickup_button is not None
                    else self.act_key("z", "Pickup-Z")
                )
                if picked:
                    self._pickup_next_at = now + 10.0
                    self._main_line_since = now
                    return LoopAction.Continue

        # 技能/羁绊/宝物优先于会重复出现的进化按钮，避免 G/F/V 饿死。
        opened = self._maybe_open_choice_panel(frame, anchor=anchor)
        if opened is not None:
            self._main_line_since = now
            return opened

        if (
            not self._passenger_mode()
            and self._panel_state == PanelState.CLOSED
            and anchor is None
            and not self._has_active_transaction(frame)
            and surface == InteractionSurface.HUD_ONLY
        ):
            # 机会强化武器 1 号格：在 HUD_ONLY 且无活跃事务、非 equipment 步骤时低频右键最大升级（8s CD）
            if self._l1_cycle_step != "equipment":
                slot1_res = self._maybe_opportunistic_upgrade_slot1(frame, now)
                if slot1_res is not None:
                    self._main_line_since = now
                    return slot1_res

            # 机会点击进化：在 HUD 空闲时触发
            if self._l1_cycle_step != "evolve":
                evolve_res = self._maybe_opportunistic_evolve(frame, now)
                if evolve_res is not None:
                    self._main_line_since = now
                    return evolve_res

            # 机会使用英雄卡：在 HUD 空闲、无点击进化按钮时使用背包英雄卡（4s CD）
            hero_card_res = self._maybe_opportunistic_hero_card(frame, now)
            if hero_card_res is not None:
                self._main_line_since = now
                return hero_card_res

            # 机会黑商单次购买：在 HUD 空闲、黑商在场时单次购买高价值物品（8s CD）
            merchant_res = self._maybe_opportunistic_merchant(frame, now)
            if merchant_res is not None:
                self._main_line_since = now
                return merchant_res

        if self._passenger_mode() and self._l1_cycle_step == "hitch_idle":
            # legacy 停车位：新环不再产生这个步，留作旧状态的安全落点。
            self._advance_l1_cycle("hitch_idle")
            return LoopAction.Continue

        # 显式循环中的神器阶段；无到期槽位时推进到技能。
        if self._l1_cycle_step == "artifact":
            artifact_res = self._maybe_fire_artifacts(frame)
            if artifact_res is not None:
                self._main_line_since = now
                return artifact_res
            self._advance_l1_cycle("artifact")
            return LoopAction.Continue

        if self._l1_cycle_step == "evolve":
            if getattr(self, "_evolve_awaiting_hero_pick", False):
                # 英雄三选一进行中：面板/弹窗处理会调 _complete_evolve_hero_pick 推进。
                return LoopAction.Continue
            # P0-2（164929/215302）：进化点击后置确认。点击后必须观察到面板/
            # 画面反馈才算成功；无反馈计失败并重试（5s 冷却保留），每轮 ≤3 次后
            # 放弃本轮进化，绝不连续空点。
            if getattr(self, "_evolve_feedback_pending", False):
                return self._tick_evolve_feedback_pending(frame, now) or LoopAction.Continue
            if now < getattr(self, "_evolve_click_cooldown_until", 0.0):
                return LoopAction.Continue
            if self._has_evolve_button(frame):
                # 金色「点击进化」条优先定位（避免点到左侧羁绊图标）
                evolve_hit = self._evolve_button_hit(frame)
            else:
                evolve_hit = self.find(
                    frame,
                    ["click_evolve", "click_evolve_v2"],
                    threshold=0.75,
                    scales=(0.9, 1.0, 1.1),
                )
            if evolve_hit:
                print(f"[L1] 点击进化 @ {evolve_hit.center}")
                if self.act_click(evolve_hit, "ClickEvolve"):
                    self._evolve_click_cooldown_until = now + 5.0
                    self._evolve_feedback_pending = True
                    self._evolve_click_at = now
                    self._evolve_baseline = self._panel_roi_region(frame)
                    self._main_line_since = now
                    return LoopAction.Continue
            # 金条/模板均未命中或输入失败：本轮进化无事可做，推进循环
            self._advance_l1_cycle("evolve")
            return LoopAction.Continue

        if self._l1_cycle_step == "equipment":
            if not self.settings.auto_weapon:
                self._advance_l1_cycle("equipment")
                return LoopAction.Continue
            result = self._maybe_upgrade_equipment(frame)
            if (
                self._equipment_fsm.pending_slot is None
                and self._pending_action is None
                and self._find_equipment_affix_choice(frame) is None
            ):
                self._advance_l1_cycle("equipment")
            self._main_line_since = now
            return result
        if self._l1_cycle_step == "public_bag":
            deposit_res = self._maybe_public_backpack_deposit(frame, now)
            if deposit_res is not None:
                self._main_line_since = now
                return deposit_res
            if self._public_bag_fsm.active or (
                self._bag_layout(frame) is not None and now >= self._public_bag_next_at
            ):
                return LoopAction.Continue
            self._advance_l1_cycle("public_bag")
            return LoopAction.Continue

        if self._l1_cycle_step == "pickup":
            # 1. 拾取 Z 不是常驻战斗按键。只有可移动装备栏 2-6 已全部
            #    占满、确有溢出风险时才做范围拾取；空栏/不确定画面零输入。
            #    和背包同理：优先点 HUD 上的 [Z] 按钮，键盘只作兜底。
            if (
                now >= self._pickup_next_at
                and self._hud_item_bar_overflowed(frame)
                and self._pickup_bag_has_space(frame)
            ):
                pickup_button = self._hud_hotkey_button(frame, "bag/hud_pickup_button")
                picked = (
                    self.act_click(pickup_button, "Pickup-Z")
                    if pickup_button is not None
                    else self.act_key("z", "Pickup-Z")
                )
                if picked:
                    self._pickup_next_at = now + 10.0
                    self._main_line_since = now
            if self._passenger_mode():
                # 蹭车不吃丹、不用英雄卡：那是队伍资产，只负责搬进公共背包。
                self._advance_l1_cycle("pickup")
                return LoopAction.Continue
            # 2. 进化完成后的背包消耗品与英雄卡使用（在 evolve 之后安全使用）
            item_res = self._maybe_use_inventory_item(frame)
            if item_res is not None:
                self._main_line_since = now
                return item_res
            self._advance_l1_cycle("pickup")
            return LoopAction.Continue

        if self._l1_cycle_step == "merchant":
            if now < getattr(self, "_merchant_budget_retry_at", 0.0):
                # 余额不足/不可读时让循环继续做宝物、拾取和公共背包，等下一
                # 个预算观察窗口再回来，而不是把整局卡在黑商步骤。
                self._advance_l1_cycle("merchant")
                return LoopAction.Continue
            if now < self._merchant_next_at:
                return LoopAction.Continue
            if not self._black_merchant_present(frame):
                if self._passenger_mode():
                    if self._merchant_discovery_deadline is None:
                        self._merchant_discovery_deadline = now + 10.0
                        print("[L1] 蹭车黑商尚未出现，零输入观察最多 10s")
                        return LoopAction.Continue
                    if now < self._merchant_discovery_deadline:
                        return LoopAction.Continue
                print("[L1] 黑商不在，转回 G 技能")
                self._advance_l1_cycle("merchant")
                return LoopAction.Continue
            self._merchant_discovery_deadline = None
            merchant_res = self._maybe_black_merchant(frame)
            if merchant_res is not None:
                self._main_line_since = now
                return merchant_res
            print("[L1] 黑商无可买/杀敌不够刷新，转回 G 技能")
            self._advance_l1_cycle("merchant")
            return LoopAction.Continue

        # 活性看门狗只步进已验证的内部循环；绝不向未知前台注入全局 ESC。
        if self._main_line_since is not None and (now - self._main_line_since) >= 15.0:
            print("[med] 活性看门狗：15s 无动作，步进已验证循环")
            self._advance_l1_cycle()
            self._main_line_since = now
            return LoopAction.Continue
        print("[med] 主线 idle（等待局内选择/挑战 UI）")
        return LoopAction.Continue

    def _classify_exit_surface(self, frame: Frame) -> str:
        """Reclassify a disappeared exit confirmation without inferring HUD."""
        if not self._is_game_client_frame(frame) and self._find_room_start(frame):
            return "room"
        if self._is_in_game_hud(frame):
            return "hud"
        if self._is_game_client_frame(frame):
            return "transition"
        return "unknown"

    def _rearm_exit_chain(self, reason: str) -> bool:
        """Re-arm QUIT once within the session budget; never reset forever."""
        if self._exit_rearm_attempts >= self._EXIT_REARM_LIMIT:
            return False
        self._exit_rearm_attempts += 1
        print(
            f"[med] 退出链 {reason}，有界重新进入 QUIT "
            f"({self._exit_rearm_attempts}/{self._EXIT_REARM_LIMIT})"
        )
        self.set_phase(Phase.QUIT, reason)
        return True

    def _tick_l1_tail(self, frame: Frame) -> LoopAction:
        if self.phase in (Phase.EARLY_CHALLENGE, Phase.ANCHOR_BOSS, Phase.LONGZHU):
            # S0 ⑧：longzhu 色相检查只在 LONGZHU 阶段执行（N2 waiver 复评：
            # MAIN_LINE 不再每 tick 全帧扫 longzhu）。本阶段 G0 未实现，仍 Fail-Closed。
            if self.phase == Phase.LONGZHU and self.find_scene(frame, "longzhu"):
                print("[med] LONGZHU 阶段识别到龙珠入口但状态机未实现，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "unverified longzhu entry (LONGZHU phase)")
                self.stop()
                return LoopAction.Break
            print(f"[med] 战后/大秘境阶段 ({self.phase.name}) 未完成前置校验与安全状态机，Fail-Closed 停止运行")
            self.set_phase(Phase.ERROR, f"unverified {self.phase.name} phase")
            self.stop()
            return LoopAction.Break

        timeout = max(3, min(self.settings.query_timeout, 15))
        elapsed = time.time() - self._exit_since if self._exit_since else 0.0

        if self.phase == Phase.QUIT:
            if not self._is_game_client_frame(frame) and self._find_room_start(frame):
                print("[med] 局内退出阶段检测到已在房间准备界面，退出完成")
                self._awaiting_room_return = True
                self.set_phase(Phase.PREPARE, "already back in room")
                self._room_action_deadline = time.time() + min(self.settings.query_timeout, 30)
                self._longzhu_deadline = None
                self._f1_fallback_done = False
                return LoopAction.Continue
            if self._find_exit_confirm(frame):
                self.set_phase(Phase.NEXT, "exit confirmation already visible")
                return LoopAction.Continue
            if self._exit_button_attempts >= 3 or elapsed >= timeout:
                surface = self._classify_exit_surface(frame)
                if surface == "room":
                    print("[med] 局内退出超时但检测到房间准备界面，退出完成")
                    self._awaiting_room_return = True
                    self.set_phase(Phase.PREPARE, "room detected after quit timeout")
                    self._room_action_deadline = time.time() + min(self.settings.query_timeout, 30)
                    self._longzhu_deadline = None
                    self._f1_fallback_done = False
                    return LoopAction.Continue
                if surface == "hud" and self._rearm_exit_chain("quit surface still HUD"):
                    return LoopAction.Continue
                if surface == "transition" and elapsed < timeout * 2:
                    print("[med] 局内退出处于转场/加载，继续有界等待（零动作）")
                    return LoopAction.Continue
                print("[med] 未能打开专用退出确认框，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "exit button timeout")
                self.stop()
                return LoopAction.Break
            exit_hit = self._find_game_exit(frame)
            if not exit_hit:
                if self._passenger_mode() and self._find_stage_page(frame):
                    self.act_key("esc", "HitchLeaveMisopenedStage")
                    return LoopAction.Continue
                print("[med] 等待局内左上角专用退出按钮（零动作）")
                return LoopAction.Continue
            self._exit_button_attempts += 1
            print(f"[med] 点击局内退出 @ {exit_hit.center} (尝试 {self._exit_button_attempts}/3)")
            if self.act_click(exit_hit, "QuitGame-open-confirm"):
                self.set_phase(Phase.NEXT, "exit button clicked")
            return LoopAction.Continue

        if self.phase == Phase.NEXT:
            if not self._is_game_client_frame(frame) and self._find_room_start(frame):
                print("[med] 退出确认阶段检测到已在房间准备界面")
                if self._hitch_enabled():
                    return self._finish_hitch_round(time.time(), "exit confirmed; hitch re-search")
                self._awaiting_room_return = True
                self.set_phase(Phase.PREPARE, "room detected after exit confirm")
                self._room_action_deadline = time.time() + min(self.settings.query_timeout, 30)
                self._longzhu_deadline = None
                self._f1_fallback_done = False
                return LoopAction.Continue

            confirm_hit = self._find_exit_confirm(frame)
            if confirm_hit is not None:
                if self._exit_confirm_attempts >= 3:
                    print("[med] 退出确认按钮点击已达 3 次仍未退出，Fail-Closed 停止")
                    self.set_phase(Phase.ERROR, "exit confirmation attempts exhausted")
                    self.stop()
                    return LoopAction.Break
                self._exit_confirm_attempts += 1
                print(f"[med] 确认退出当前游戏 @ {confirm_hit.center} (尝试 {self._exit_confirm_attempts}/3)")
                if not self.act_click(confirm_hit, "QuitGame-confirm"):
                    return LoopAction.Continue
                if self._hitch_enabled():
                    return self._finish_hitch_round(time.time(), "exit confirmed; hitch re-search")
                self._awaiting_room_return = True
                self.set_phase(Phase.PREPARE, "exit confirmed; verify same room")
                self._room_action_deadline = time.time() + min(self.settings.query_timeout, 30)
                self._longzhu_deadline = None
                self._f1_fallback_done = False
                return LoopAction.Continue

            # confirm_hit is None:
            surface = self._classify_exit_surface(frame)
            if surface == "room":
                print("[med] 退出确认按钮消失且已在房间界面，退出完成")
                self._awaiting_room_return = True
                self.set_phase(Phase.PREPARE, "room detected after confirm disappeared")
                self._room_action_deadline = time.time() + min(self.settings.query_timeout, 30)
                self._longzhu_deadline = None
                self._f1_fallback_done = False
                return LoopAction.Continue
            if surface == "hud" and self._exit_confirm_attempts > 0:
                if self._rearm_exit_chain("confirm disappeared on HUD"):
                    return LoopAction.Continue
                print("[med] 退出确认消失后仍为 HUD 且重试预算耗尽，Fail-Closed 停止")
                self.set_phase(Phase.ERROR, "exit confirmation HUD rearm exhausted")
                self.stop()
                return LoopAction.Break
            if surface == "transition":
                if elapsed < timeout * 2:
                    print("[med] 退出确认消失，处于转场/加载，继续有界等待（零动作）")
                    return LoopAction.Continue
                print("[med] 退出确认转场等待超时，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "exit confirmation transition timeout")
                self.stop()
                return LoopAction.Break
            if elapsed >= timeout or self._exit_confirm_attempts >= 3:
                if surface == "room":
                    print("[med] 确认按钮消失且已在房间界面，退出完成")
                    self._awaiting_room_return = True
                    self.set_phase(Phase.PREPARE, "room detected after confirm disappeared")
                    self._room_action_deadline = time.time() + min(self.settings.query_timeout, 30)
                    self._longzhu_deadline = None
                    self._f1_fallback_done = False
                    return LoopAction.Continue
                print("[med] 退出确认框未能安全确认，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "exit confirmation timeout")
                self.stop()
                return LoopAction.Break

            print("[med] 等待专用退出确认按钮（零动作）")
            return LoopAction.Continue

        print(f"[med] unhandled phase {self.phase}")
        return LoopAction.Continue

    def run(self, max_steps: int | None = None) -> None:
        self._running = True
        self.set_phase(Phase.BOOT)
        # 英雄三国已存在时必须先接管游戏窗；没有游戏窗才允许激活 KK 平台。
        targets = find_window_targets(
            ",".join(L1_WINDOW_KEYWORDS), role="l1", allow_minimized=True
        ) or find_window_targets(allow_fallback=True, allow_minimized=True)
        if targets:
            activate_window(targets[0].hwnd)
        steps = 0
        print(
            f"[med] Run learning_mode={self.settings.dry_run} mode={self.settings.game_mode} "
            f"auto_room={self._auto_room_enabled()} "
            f"stage={self.settings.stage1}/{self.settings.stage2} "
            f"targets={self.settings.stage_targets or '-'} "
            f"secret_realm={self.settings.auto_secret_realm} "
            f"threshold={self.settings.match_threshold} images={self.images} "
            "l0_uia=disabled"
        )
        if self.settings.dry_run:
            print(
                "[med] 学习模式：只观察/记录决策，不会真的点击；"
                "要自动创房刷图请关闭「学习模式」"
            )
        else:
            from shuabao.input.keyboard_mouse import is_current_process_elevated

            if not is_current_process_elevated():
                print(
                    "[med] FATAL: dry_run=False 但当前进程不是管理员。"
                    "原版 GameScript 与 KK 平台均以管理员运行；"
                    "非提权进程的 SendInput 会被 Windows UIPI 静默丢弃（返回成功但游戏无响应）。"
                    "请右键刷刷宝（ShuaBao.exe），以管理员身份重新启动。"
                )
                self.set_phase(Phase.ERROR, "real input requires elevation (UIPI)")
                self._running = False
                self.exit_reason = RunExitReason.UIPI_PERMISSION_FAILURE
                return
            print("[med] elevation OK — real SendInput path enabled")
        self.emergency_listener = EmergencyStopListener(self.stop_signal)
        self.emergency_listener.start()
        self.exit_reason = None
        try:
            while self._running and not self.stop_signal.is_set():
                # N2.3：固定 cadence —— sleep = max(0, cadence - elapsed)，time.monotonic。
                # loop_sleep_ms 仅作兼容上限（默认 400ms 会盖住 loading 档的 500ms）。
                tick_started = time.monotonic()
                try:
                    action = self.tick()
                except Exception:
                    # G0 contract #1/#2：运行循环内未捕获异常 → PROCESS_CRASH，
                    # 归因后原样上抛（不吞异常、不改变传播语义）。
                    self.exit_reason = RunExitReason.PROCESS_CRASH
                    raise
                steps += 1
                if action == LoopAction.Break:
                    break
                if max_steps is not None and steps >= max_steps:
                    # max_steps 只属于测试/回放探针，不是业务终止归因。
                    print(f"[med] max_steps={max_steps}")
                    self.exit_reason = RunExitReason.UNEXPECTED_TERMINATION
                    break
                elapsed = time.monotonic() - tick_started

                cadence = self._cadence_for_current_state()
                cap = max(0.0, self.settings.loop_sleep_ms / 1000.0)
                # N2-REVIEW #5：loop_sleep_ms 仅作稳定档兼容上限，loading/转场档
                # （500ms，无可动作证据的安全等待）不被 400ms 上限压缩。
                sleep = cadence if cadence >= 0.5 else min(cadence, cap)
                time.sleep(max(0.0, sleep - elapsed))
        finally:
            if self.emergency_listener:
                self.emergency_listener.stop()
                self.emergency_listener = None
            if self._ocr_client is not None:
                self._ocr_client.close()
            if self.exit_reason is None:
                self.exit_reason = self._classify_run_exit()
            print(f"[med] end steps={steps} games={self.game_count} exit={self.exit_reason.value if self.exit_reason else 'N/A'}")

    def _classify_run_exit(self) -> RunExitReason:
        """run() 退出时的唯一停止归因（G0 P0 contract #2）。

        先到的外部 StopSignal 拥有归因权（绝不覆盖）：F12/Shift+F12 →
        EMERGENCY_STOP，其余外部 reason（RunnerService/Headless/UI 等）→
        USER_STOP。Mediator.stop() 只在尚无外部 stop 时才写信号，随后读
        mediator 锚点：考古 handoff 已确认 → ARCHAEOLOGY_HANDOFF_COMPLETE；
        Phase.COMPLETE（cycle_num 达成）→ CONFIGURED_CYCLE_COMPLETE；
        其余 fail-closed/未分类 break → FATAL_ENVIRONMENT_FAILURE /
        UNEXPECTED_TERMINATION。
        """
        if self.stop_signal.is_set():
            reason = str(self.stop_signal.reason or "")
            if reason and reason != "Mediator.stop()":
                # 先到的外部 stop 拥有归因权；Mediator.stop() 只走锚点分支。
                if "emergency" in reason.lower():
                    return RunExitReason.EMERGENCY_STOP
                return RunExitReason.USER_STOP
        if getattr(self, "_archaeology_handoff_confirmed", False):
            return RunExitReason.ARCHAEOLOGY_HANDOFF_COMPLETE
        if self.phase == Phase.COMPLETE:
            return RunExitReason.CONFIGURED_CYCLE_COMPLETE
        if self.phase == Phase.ERROR:
            return RunExitReason.FATAL_ENVIRONMENT_FAILURE
        return RunExitReason.UNEXPECTED_TERMINATION

    @property
    def round_elapsed(self) -> float | None:
        """G0 contract #3：本局已进行秒数（round 起点 = hard deadline 锚点）。"""
        if self._round_started_at is None:
            return None
        return max(0.0, time.time() - self._round_started_at)

    def _cadence_for_current_state(self) -> float:
        """状态分级 cadence（秒）：动作后 100ms / 稳定 HUD 300ms / loading 500ms / 候选 300ms。

        不读取动态网络或新增设置层；InputExecutor 内部点击等待（~390ms）不在此列，
        未经可靠性实验不得缩短。
        """
        if getattr(self, "_tick_input_executed", False):
            return 0.100  # 成功输入后短观察窗；不能成为连续输入许可
        if getattr(self, "_failure_candidate_frames", 0) > 0:
            return 0.300  # FAIL/DISCONNECT 候选：安全检测优先，不放慢
        if self.phase == Phase.RECOVER_FAILURE:
            return 0.300  # 恢复：每步门闩确认，安全检测优先
        context = self._context_cache_value
        if context in ("UNKNOWN", "QUIT"):
            return 0.300  # UNKNOWN/退出候选：300ms 或更快
        if self.phase in (
            Phase.BOOT,
            Phase.WAIT_UI,
            Phase.ROOM_STARTING,
            Phase.STAGE_STARTING,
            Phase.HERO_SETUP,
        ):
            return 0.500  # loading / 窗口转场：无可动作证据
        health = self._last_health
        if health is not None and not health.is_healthy:
            return 0.500  # 非静态不健康等待
        return 0.300  # 稳定健康 HUD，无待确认动作
