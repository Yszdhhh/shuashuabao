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
    activate_window,
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
    configured_stage_id,
    find_stage_in_range,
    find_stage_labels,
    find_unselected_old_world_tab,
    selected_stage_row,
    stage_list_scroll_point,
    visible_stage_rows,
)
from shuabao.vision.ocr_shadow.client import ShadowClient
from shuabao.log_sink import emit_print as print  # noqa: A001
from shuabao.lobby_hitch import (
    JOIN_ATTEMPTS,
    FollowPhase,
    FollowTeamSM,
    HitchAction,
    HitchSearchSM,
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
    assemble_policy_settings,
    choose_action,
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


class RoundOutcome(Enum):
    """S0 终局 outcome：一局只能记录一个（_outcome_recorded 守卫）。"""

    VICTORY = auto()
    FAILURE = auto()
    TIMEOUT = auto()
    DISCONNECT = auto()


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


class Mediator:
    _CREATE_ROOM_CONFIRM_WINDOW_S = 4.0
    _CREATE_ROOM_TOTAL_TIMEOUT_S = 60.0
    # Compatibility aliases retained for older tests/diagnostics.  They no
    # longer terminate a recoverable alignment loop by click count.
    _CREATE_ROOM_DOWNLOAD_WAIT_S = _CREATE_ROOM_TOTAL_TIMEOUT_S
    _CREATE_ROOM_MAX_ATTEMPTS = 3
    _L0_TRANSITION_TIMEOUT_S = 60.0
    _OCR_SLOT_ROIS = {
        "skill": ((0.286, 0.178, 0.421, 0.255), (0.433, 0.178, 0.568, 0.255), (0.579, 0.178, 0.714, 0.255)),
        "bond": ((0.254, 0.180, 0.410, 0.265), (0.425, 0.180, 0.581, 0.265), (0.596, 0.180, 0.752, 0.265)),
        "treasure": ((0.286, 0.190, 0.418, 0.265), (0.433, 0.190, 0.565, 0.265), (0.582, 0.190, 0.714, 0.265)),
    }
    _CHOICE_SLOT_CENTERS = {
        "skill": ((0.354, 0.42), (0.500, 0.42), (0.646, 0.42)),
        "bond": ((0.331, 0.44), (0.503, 0.44), (0.676, 0.44)),
        "treasure": ((0.352, 0.42), (0.500, 0.42), (0.648, 0.42)),
    }
    # 卡面效果描述 ROI（归一化）。宝物三槽 x 中心与品质色采样一致；
    # y/半宽按 fixtures/treasure_negative desc2_* 在整帧上的模板回投标定
    # （_panels/treasure_panel.png + 贪婪献祭 desc2；覆盖 DESCRIPTIONS.json 证据）。
    _OCR_DESC_ROIS = {
        "treasure": {
            "centers_x": (0.348, 0.497, 0.646),
            "half_w": 0.088,
            "y0": 0.275,
            "y1": 0.420,
        },
    }
    # 品质色采样中心（与 _rarity_choice / 描述 ROI 对齐）。
    _RARITY_SAMPLE_XS = {
        "treasure": (0.348, 0.497, 0.646),
        "bond": (0.331, 0.450, 0.569),
        "card": (0.331, 0.450, 0.569),
        "skill": (0.354, 0.500, 0.646),
    }
    _RARITY_SAMPLE_CY = {
        "treasure": 0.300,
        "bond": 0.333,
        "card": 0.333,
        "skill": 0.333,
    }

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
        # 旧世大陆页签切换尝试预算（上限 2 次）：防 UI 刷新延迟/模板残影导致的
        # livelock 连点，超限 Fail-Closed 停机。
        self._old_world_switch_attempts = 0
        self._missing_window_since: float | None = None
        self._last_frame: Frame | None = None
        self._prev_frame: Frame | None = None
        self._last_capture_role: str | None = None
        # N2.2：单帧感知证据（FrameEvidence.cache 取代旧 _scene_cache / 每 tick clear）
        self._evidence: FrameEvidence | None = None
        self._tick_evidence: FrameEvidence | None = None
        self._tick_gen: int | None = None
        # N2-REVIEW #3：独立输入序列号——每次成功输入（含 dry-run 观测）递增，
        # 用于动作授权（本 tick 至多一个输入、缓存命中不延续旧帧授权）；
        # 与 evidence.gen/缓存解耦：dry-run 不丢性能复用（benchmark exact-static）。
        self._input_seq = 0
        self._tick_input_seq: int | None = None
        # trace/incident 兼容镜像：_detect_context 每次计算后同步（evidence.context 是权威值）
        self._context_cache_value = "UNKNOWN"
        # 多窗口捕获：上次健康 hwnd 优先；连续 N=2 不健康/失配才枚举候选
        self._capture_miss_streak = 0
        self._capture_candidates = 0
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
        # trace 帧指纹缓存：(Frame 强引用, fingerprint)；用 is 判同，避免
        # id 复用导致同址新 Frame 误命中旧指纹。
        self._trace_fingerprint_cache: tuple | None = None
        self._interrupt_reason: str | None = None
        # Safety: L0 cycle counter — prevent infinite PLATFORM_MAP ↔ ROOM_WAITING loops
        self._l0_cycle_count = 0
        self._l0_cycle_limit = 5
        refresh_lo, refresh_hi = 3.0, 4.0
        try:
            from shuabao.shell.mode_catalog import hitch_refresh_window

            refresh_lo, refresh_hi = hitch_refresh_window()
        except Exception:
            pass
        self._hitch_sm = HitchSearchSM(
            prefix=normalize_prefix(getattr(settings, "hitch_stage_prefix", "3")),
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
        self._post_game_close_attempts: int = 0
        # Optional post-victory great-rift chain.  Every input has a dedicated
        # anchor and a bounded post-click observation window.
        self._secret_realm_request_pending: bool = False
        self._secret_realm_request_since: float | None = None
        self._secret_realm_request_attempts: int = 0
        self._secret_realm_next_observe_at: float = 0.0
        self._secret_realm_entering_since: float | None = None
        self._secret_realm_confirm_attempts: int = 0
        self._secret_realm_confirm_next_observe_at: float = 0.0
        self._secret_realm_active: bool = False
        self._exit_button_attempts: int = 0
        self._exit_confirm_attempts: int = 0
        self._exit_since: float | None = None
        self._awaiting_room_return: bool = False
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
        # L1 运行时技能卡归属：pending = 点击后等待 WAIT_MUTATION 确认（episode 级）；
        # owned = 已确认学得（round 级，set_phase(MAIN_LINE) 重置）。未确认点击
        # 超时只清 pending，绝不写入 owned（未知/未验证不记账）。
        # 使用列表保留同卡多次学习；目录里存在明确的 x2 前置。
        self._skill_cards_pending: list[str] = []
        self._skill_cards_owned: list[str] = []
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
        # WAIT_MUTATION proves a panel mutation/disappearance.
        self._panel_pending_choice_action: str | None = None  # select/close/refresh
        self._panel_pending_choice_fingerprint: tuple | None = None
        self._panel_f1_used_this_episode = False
        # P0-3（215302）：自然面板进入需同类型锚点连续 2 帧（或单帧 ≥0.85）。
        # 跨 tick 保留上一帧锚点类型；类型漂移/锚点消失即重置，防单帧贴阈值
        # （0.742/0.799）误入面板处理。
        self._panel_anchor_candidate: tuple[str, float] | None = None
        # One explicit L1 cycle owns the proactive G/F/V panels.  Per-panel
        # fingerprint guards remain the anti-loop safety boundary; a lifetime
        # "five panels per game" cap must not permanently starve later skill
        # points in a long round.
        self._l1_cycle_step = "skill"
        self._l1_cycle_owned_panel = False
        self._l1_cycle_selected = False
        # 三面板主动打开时间戳（G/F/V）：0.0 = 本局从未成功打开 → 首次立即允许；
        # 成功打开后按 settings.choice_interval 限制同 kind 重开。set_phase(MAIN_LINE)
        # 每局重置。
        self._last_skill_panel = 0.0
        self._last_bond_attempt = 0.0
        self._last_treasure_attempt = 0.0
        self._merchant_next_at = 0.0
        self._equipment_next_at = 0.0
        self._equipment_pending_until = 0.0
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
                timeout_ms=settings.ocr_timeout_ms,
                startup_timeout_ms=30000,
                trace_path=(Path(incident_dir) / "ocr_shadow.jsonl") if incident_dir else None,
            )

    # ---------- 感知 / 执行（Jobs 唯一入口）----------

    def _capture_title(self) -> str:
        """根据当前阶段返回截屏目标窗口关键字。
        L0（大厅/建房/房间等待）→ KK 对战平台窗口
        L1（进入游戏后的过渡/选关/局内）→ 英雄三国游戏窗口
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
            if self.find(frame, ["mainIdentifier"], threshold=th, scales=self._hot_scales()):
                return True
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
        elif self.find_scene(frame, "disconnect") or self.find_scene(frame, "fail"):
            value = "QUIT"
        elif self._is_in_game_hud(frame):
            # The task bar/Boss timer can parse as a stage row.  Strong HUD
            # anchors revoke STAGE_SELECT classification authority.
            value = "MAIN_LINE"
        elif self._find_stage_page(frame):
            # 选关页特征（关卡编号数字）优先于通用「开始游戏」按钮：
            # 选关页底部也有开始/扫荡/英雄模式按钮，room_start 模板会误匹配
            # （官方 1936x1066 选关截图实测 roomStart 0.84 / kk_start 0.92）。
            value = "STAGE_SELECT"
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
        targets = find_window_targets(title, role=role)
        create_dialog_probe = role == "l0" and (
            self._create_room_pending_since is not None
            or self.phase == Phase.CREATE_ROOM
        )
        self._capture_candidates = len(targets)
        if not targets:
            return capture(title, role=role, activate=False)
        # KK exposes the create-room form as a second same-title HWND.  The
        # sticky parent window still looks healthy, so the generic fast path
        # would otherwise starve the dialog forever.  Probe every candidate
        # only during this bounded episode and prefer the structurally
        # confirmed form.  No focus change or input is performed here.
        if create_dialog_probe:
            frames = [capture_target(target) for target in targets]
            for candidate in frames:
                if self._find_create_confirm(candidate):
                    self._capture_miss_streak = 0
                    return candidate
            # Dialog closed (Create accepted or dismissed). Prefer an already
            # open room over the larger platform map — max(size) would always
            # pick 1328x945 and starve room_start (r10 trace_20260812_102844).
            for candidate in frames:
                if self._find_room_start(candidate):
                    self._capture_miss_streak = 0
                    return candidate
            # Otherwise fall through to sticky / signal ranking.
        if len(targets) == 1:
            return capture_target(targets[0])
        prev = self._last_frame if self._last_capture_role == role else None
        if prev is not None and prev.hwnd is not None:
            prev_target = next((t for t in targets if t.hwnd == prev.hwnd), None)
            if prev_target is not None:
                frame = capture_target(prev_target)
                valid = frame.bgr is not None and frame.bgr.size > 0 and frame.is_valid and frame.width > 0
                if valid and self._sticky_frame_signal(frame, role):
                    self._capture_miss_streak = 0
                    return frame
                self._capture_miss_streak += 1
                if self._capture_miss_streak < 2:
                    # 连续第 1 帧失配：仍返回该 hwnd 帧，下一帧才重选
                    return frame
                # 连续 2 帧失配（无效或无信号）→ 候选枚举重排
        self._capture_miss_streak = 0
        frames = [capture_target(target) for target in targets]
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
        return max(
            top,
            key=lambda pair: (self._frame_signal(pair[1], role), int(pair[1].hwnd == previous_hwnd)),
        )[1]

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
        if self.phase == Phase.BOOT and self._frame_signal(frame, role) == 0:
            # BOOT is the only phase allowed to ask both windows which one is
            # already in the game.  Later phases stay role-bound.
            game_title = ",".join(L1_WINDOW_KEYWORDS)
            game_frame = self._capture_best(game_title, "l1")
            if self._frame_signal(game_frame, "l1") > 0:
                print("[med] BOOT 检测到游戏窗口，切换到 L1")
                frame = game_frame
                role = "l1"
        self._prev_frame = self._last_frame
        self._last_frame = frame
        self._last_capture_role = role
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
    _STAGE_ROWS_ROI = (0.45, 0.05, 0.85, 0.60)
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
        if res.success:
            self._tick_input_executed = True
            self._input_seq += 1
            if action_ms >= 800.0 and not self.settings.dry_run and self._tick_reason is None:
                self._tick_reason = "input_executor_wait"
            if not self.settings.dry_run:
                self.invalidate_evidence("input")
        return res.success

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
        return self._finish_input(res, reason, action_ms)

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
        return self._finish_input(res, reason, action_ms)

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

    def _classify_choice_panel(self, frame: Frame) -> str | None:
        """Distinguish skill / bond / treasure choice panels by their unique buttons."""
        opened = getattr(self, "_panel_opened_by_us", None)
        if opened in ("skill", "bond", "treasure"):
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
        # The generic hide anchor is near-perfect only on the treasure layout.
        # G 三选也有「暂时隐藏」，treasure_lock 会误匹配遮罩（13号 200601 tick9）。
        # 放弃钮是技能独有；锁模板单独命中不足以为宝物（与 bond 单锚点同纪律）。
        skill_hit = self.find(
            frame, ["skill_giveup_btn", "skill_refresh_btn"],
            threshold=threshold, scales=scales, roi=roi,
        )
        treasure_lock = self.find(frame, ["treasure_lock_btn"], threshold=threshold, scales=scales, roi=roi)
        treasure_hide = self.find(frame, ["hide"], threshold=0.95, scales=scales, roi=roi)
        if skill_hit is not None and skill_hit.name == "skill_giveup_btn":
            return "skill"
        if treasure_lock and treasure_hide and skill_hit is None:
            return "treasure"
        if skill_hit is not None:
            return "skill"
        if treasure_lock and treasure_hide:
            return "treasure"
        if self.find(frame, ["card_hide"], threshold=threshold, scales=scales, roi=roi):
            return "card"
        return None

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
        """Independent monotonic fuse. ``_main_line_since`` cannot postpone it."""
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
        if elapsed < timeout:
            return None
        note = (
            f"LivenessTimeout: auto_task UNKNOWN for {elapsed:.1f}s "
            f"(limit {timeout:.1f}s)"
        )
        print(f"[L1] {note}，Fail-Closed 停止运行")
        self.set_phase(Phase.ERROR, note)
        self.stop()
        return LoopAction.Break

    def _ensure_auto_task_enabled(self, frame: Frame) -> LoopAction | None:
        """Enable auto-task with a bounded post-click observation window."""
        now = time.time()
        state, hit = self._auto_task_state(frame)
        fuse = self._auto_task_unknown_fuse(state)
        if fuse is not None:
            return fuse
        if getattr(self, "_auto_task_done", False):
            if self._auto_task_recheck_at <= 0.0 or now < self._auto_task_recheck_at:
                return None
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


    # 卡牌品质色（用户规则）：红 > 橙 > 紫 > 蓝 > 白 > 绿（最低档）
    RARITY_BANDS = (
        ("red", 5),
        ("orange", 4),
        ("purple", 3),
        ("blue", 2),
        ("white", 1),
        ("green", 0),
    )

    def _card_rarity_score(
        self,
        frame: Frame,
        cx: int,
        cy: int,
        panel_kind: str = "card",
    ) -> tuple[int, str, int] | None:
        """Score a card's border-ring color by rarity band.

        Returns (score, band, saturated_pixels) or None when no rarity color.
        """
        try:
            import numpy as np
            import cv2 as _cv2
        except Exception:
            return None
        if panel_kind == "treasure":
            w, h = int(frame.width * 0.128), int(frame.height * 0.180)
            minimum = 400
        else:
            w, h = int(frame.width * 0.094), int(frame.height * 0.122)
            minimum = 30
        x0, y0 = max(0, cx - w // 2), max(0, cy - h // 2)
        roi = frame.bgr[y0 : y0 + h, x0 : x0 + w]
        if roi is None or roi.size == 0:
            return None
        ring = np.concatenate(
            [
                roi[:5, :].reshape(-1, 3),
                roi[-5:, :].reshape(-1, 3),
                roi[:, :5].reshape(-1, 3),
                roi[:, -5:].reshape(-1, 3),
            ]
        )
        hsv = _cv2.cvtColor(ring.reshape(-1, 1, 3), _cv2.COLOR_BGR2HSV)
        hues = hsv[:, 0, 0]
        sat = hsv[:, 0, 1]
        value = hsv[:, 0, 2]
        best: tuple[int, str, int] | None = None
        masks = {
            "red": (((hues <= 10) | (hues >= 170)) & (sat > 70) & (value > 60)),
            "orange": ((hues > 10) & (hues <= 30) & (sat > 70) & (value > 60)),
            # green：hue 约 35–90；夹在 orange 与 blue 之间，实机绿边卡（如双倍神符）
            "green": ((hues > 35) & (hues < 90) & (sat > 70) & (value > 60)),
            "purple": ((hues >= 125) & (hues < 170) & (sat > 60) & (value > 50)),
            "blue": ((hues >= 90) & (hues < 125) & (sat > 60) & (value > 50)),
            "white": ((sat < 45) & (value > 150)),
        }
        for band, score in self.RARITY_BANDS:
            count = int(masks[band].sum())
            if count >= minimum and (
                best is None or score > best[0] or (score == best[0] and count > best[2])
            ):
                best = (score, band, count)
        return best

    @staticmethod
    def _normalized_bbox(frame: Frame, roi: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
        x0, y0, x1, y1 = roi
        return (
            int(frame.width * x0), int(frame.height * y0),
            int(frame.width * x1), int(frame.height * y1),
        )

    def _ocr_panel_slots(self, frame: Frame, kind: str) -> list[dict]:
        """Read title (+ treasure description) lines. OCR supplies names only, never coordinates."""
        if self._ocr_client is None or not LayoutTransform.is_supported(frame.width, frame.height):
            return []
        rois = self._OCR_SLOT_ROIS.get(kind)
        if rois is None:
            return []
        panel_id = f"{kind}:{self._trace_frame_fingerprint(frame)}"
        panel_bbox = (
            int(frame.width * 0.24),
            int(frame.height * 0.14),
            int(frame.width * 0.76),
            int(frame.height * 0.58),
        )
        slots: list[dict] = []
        for index, roi in enumerate(rois):
            bbox = self._normalized_bbox(frame, roi)
            response = self._ocr_client.shadow_predict(
                frame,
                panel_id,
                {"index": index, "bbox": bbox, "kind": kind},
                panel_bbox=panel_bbox,
            )
            if response.elapsed_ms >= 1000 and self._tick_reason is None:
                self._tick_reason = "ocr_cold_start"
            top = response.candidates[0] if response.candidates else None
            slots.append({
                "index": index,
                "name": top.name if top else None,
                "confidence": float(top.confidence) if top else 0.0,
                "raw_text": response.raw_text or "",
                "rec_score": response.rec_score,
                "status": response.status,
                "reason": response.reason,
                "rarity": self._slot_rarity_band(frame, kind, index),
                "description": "",
            })
        # 描述 ROI：仅宝物需要（负面判定）；读不到留空，绝不猜测。
        desc_spec = self._OCR_DESC_ROIS.get(kind)
        if desc_spec is not None:
            half_w = float(desc_spec["half_w"])
            y0 = float(desc_spec["y0"])
            y1 = float(desc_spec["y1"])
            for slot, cx in zip(slots, desc_spec["centers_x"]):
                desc_roi = (float(cx) - half_w, y0, float(cx) + half_w, y1)
                bbox = self._normalized_bbox(frame, desc_roi)
                response = self._ocr_client.shadow_predict(
                    frame,
                    f"{panel_id}:desc",
                    {"index": slot["index"], "bbox": bbox, "kind": f"{kind}_desc"},
                    panel_bbox=panel_bbox,
                )
                text = (response.raw_text or "").strip()
                if not text and response.candidates:
                    text = (response.candidates[0].name or "").strip()
                slot["description"] = text
        self._trace_ocr_suggestion = {"kind": kind, "slots": slots}
        return slots

    def _slot_rarity_band(self, frame: Frame, kind: str, index: int) -> str | None:
        """Map slot index → rarity band via border color (includes green)."""
        xs = self._RARITY_SAMPLE_XS.get(kind) or self._RARITY_SAMPLE_XS.get("card")
        cy_ratio = self._RARITY_SAMPLE_CY.get(kind, 0.333)
        if xs is None or index < 0 or index >= len(xs):
            return None
        cx = int(frame.width * xs[index])
        cy = int(frame.height * cy_ratio)
        scored = self._card_rarity_score(frame, cx, cy, kind)
        return scored[1] if scored is not None else None

    def _slots_to_candidates(self, frame: Frame, kind: str, slots: list[dict]) -> tuple[SlotCandidate, ...]:
        """Map OCR slot dicts → SlotCandidate (rarity/description filled when present)."""
        out: list[SlotCandidate] = []
        for slot in slots:
            index = int(slot.get("index", 0))
            rarity = slot.get("rarity")
            if rarity is None and frame is not None:
                rarity = self._slot_rarity_band(frame, kind, index)
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
                    description=description,
                    family=family or (card_fact.family if card_fact else None),
                    prereq_marker=bool(slot.get("prereq_marker", False)),
                    is_new=bool(slot.get("is_new", False)),
                    skill_level=slot.get("skill_level"),
                    card_fact=card_fact,
                    family_source=str(family_source or "unknown"),
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
                mechanics_view=getattr(self, "_mechanics_view", None),
            )
        return self._cached_policy_settings

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

    def _confirmed_skill_cards(self) -> tuple[str, ...]:
        """已确认学得的技能卡名（含重复次数；传给 PanelCandidates）。"""
        return tuple(self._skill_cards_owned)

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

    def _find_panel_refresh(self, frame: Frame, kind: str) -> MatchResult | None:
        names = {
            "skill": ["skill_refresh_btn"],
            "bond": ["bond_refresh_btn"],
            "treasure": ["treasure_refresh_btn"],
        }.get(kind, ["skill_refresh_btn"])
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
            if decision.index is None:
                return None
            name = None
            selected_slot = None
            for slot in slots:
                if slot.index == decision.index:
                    selected_slot = slot
                    name = slot.name
                    break
            if kind == "skill" and name:
                # Prefer skill short-code for downstream cycle ownership checks.
                reverse = {v: k for k, v in self._skill_labels.items()}
                hit_name = reverse.get(name, name)
            elif name:
                hit_name = f"ocr_{kind}:{name}"
            else:
                hit_name = f"ocr_{kind}:slot{decision.index}"
            if decision.reason:
                print(f"[L1] 选卡策略：{decision.reason}")
            hit = self._choice_slot_hit(frame, kind, int(decision.index), hit_name)
            label = "技能" if kind == "skill" else kind
            return (label, hit)
        if decision.action == PolicyAction.REFRESH:
            self._choice_fp_before_refresh = slot_fingerprint(slots)
            refresh = self._find_panel_refresh(frame, kind)
            if refresh is None:
                # 找不到刷新按钮时，绝不能无限零输入死锁，必须降级为物理关闭
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
            if kind == "skill" and self._skill_giveup_blocked(slots):
                hide = self._find_skill_hide(frame)
                if hide is not None:
                    print(f"[L1] 选卡策略拦下放弃，改为隐藏：{decision.reason}")
                    return ("技能", hide)
                self._choice_policy_idle = True
                print(f"[L1] 选卡策略拦下放弃，零输入：{decision.reason}")
                return None
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

    def _choice_slot_hit(self, frame: Frame, kind: str, index: int, name: str) -> MatchResult:

        x_ratio, y_ratio = self._CHOICE_SLOT_CENTERS[kind][index]
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
        for cx in (603, 655, 707, 759, 811, 863, 915, 967, 1019, 1071):
            rx1, ry1, rx2, ry2 = transform.logical_roi(cx - 20, 635, cx + 20, 680)
            roi_bgr = frame.bgr[ry1:ry2, rx1:rx2]
            if roi_bgr.size == 0:
                continue
            hsv_roi = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
            colored = (hsv_roi[:, :, 1] > 70) & (hsv_roi[:, :, 2] > 60)
            min_pixels = int(250 * transform.scale * transform.scale)
            if int(colored.sum()) >= max(10, min_pixels):
                occupied += 1
        return occupied

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
        decision = choose_action(
            PanelCandidates(
                panel_kind=kind,
                slots=slots,
                set_progress=None,
                refresh_count=self._choice_session.refreshes,
                has_giveup=self._panel_has_giveup(frame, kind),
                owned_skill_cards=self._confirmed_skill_cards(),
                settings=self._policy_settings(),
            ),
            self._choice_session,
        )
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

    def _rarity_choice(self, frame: Frame, panel_kind: str) -> MatchResult | None:
        """Pick the highest-rarity card by border color. Treasure-only (A3).

        Bond/card must NOT call this as a whitelist bypass. Treasure may use it
        when OCR names are unavailable and choose_action cannot run.
        """
        if panel_kind not in ("treasure",):
            return None
        xs = self._RARITY_SAMPLE_XS.get(panel_kind, (0.348, 0.497, 0.646))
        cy_ratio = self._RARITY_SAMPLE_CY.get(panel_kind, 0.300)
        best: tuple[int, str, int, int, int] | None = None
        for x_ratio in xs:
            cx = int(frame.width * x_ratio)
            cy = int(frame.height * cy_ratio)
            r = self._card_rarity_score(frame, cx, cy, panel_kind)
            if r is None:
                continue
            score, band, count = r
            if best is None or score > best[0] or (score == best[0] and count > best[2]):
                best = (score, band, count, cx, cy)
        if best is None:
            return None
        _, band, count, cx, cy = best
        print(f"[L1] 按品质色选卡：{band} (饱和像素 {count}) @ ({cx},{cy})")
        return MatchResult(
            name=f"rarity_{band}",
            score=min(1.0, count / 200.0),
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
                if kind == "bond":
                    close_hit = self._close_current_panel(frame, "bond")
                    return ("bond", close_hit) if close_hit is not None else None
                if kind == "card":
                    return None
                # skill / treasure：无命中时落到下方刷新/放弃/品质收口
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
                            owned_skill_cards=self._confirmed_skill_cards(),
                            settings=self._policy_settings(),
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
            if kind == "bond" and ocr_mode == "live":
                # Live bond without policy SELECT already returned above.
                return None
            if kind == "card" and ocr_mode == "live":
                return None
            preferred = [v.strip() for v in self.settings.cards if v and v.strip()]
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
            # treasure：无 OCR 时品质色可作末位；禁止无脑第一张。
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

    _L1_CYCLE_ORDER = ("skill", "bond", "treasure", "evolve", "equipment", "pickup", "merchant", "artifact")

    def _advance_l1_cycle(self, completed: str | None = None) -> None:
        current = completed or self._l1_cycle_step
        try:
            index = self._L1_CYCLE_ORDER.index(current)
        except ValueError:
            index = -1
        nxt = self._L1_CYCLE_ORDER[(index + 1) % len(self._L1_CYCLE_ORDER)]
        if nxt == "evolve":
            self._evolve_ok_this_cycle = False
        if nxt == "equipment":
            self._inventory_clicks_this_visit = 0
            self._inventory_last_pt = None
            self._inventory_same_pt_hits = 0
            self._inventory_next_at = 0.0
            self._devour_dan_consecutive_clicks = 0
        self._l1_cycle_step = nxt

    def _maybe_open_choice_panel(self, frame: Frame, anchor: MatchResult | None = None) -> LoopAction | None:
        """Proactive skill (G) / bond (F) / treasure (V) panel opening.

        The owned cycle drains configured skills first, then bond and treasure.
        A panel kind advances only after an owned episode yields no selectable
        result (or reaches its per-cycle safety budget).  The next full cycle
        reopens skill instead of permanently starving it for the rest of a game.
        """
        if anchor is None:
            anchor = self._selection_anchor(frame)
        if anchor:
            return None
        if self._passive_choice_mode():
            return None
        if self._panel_state != PanelState.CLOSED:
            # 已有面板会话进行中（WAIT_VISIBLE/ACTIVE/…）：不再发起新打开
            return LoopAction.Continue
        now = time.time()
        # 显式循环：初始或无进行中面板时从当前步骤开始
        # Determine target step: explicit _choice_target override, or current _l1_cycle_step with fallback when earlier stages are on cooldown
        target = getattr(self, "_choice_target", None)
        target = target or self._l1_cycle_step
        if target in ("skill", "bond", "treasure"):
            reopen_at = self._panel_cooldown_until.get(target, 0.0)
            if now < reopen_at:
                remaining = reopen_at - now
                print(f"[L1] {target} 物理隐藏后主动重开冷却中（剩余 {remaining:.1f}s）")
                if target == self._l1_cycle_step:
                    self._advance_l1_cycle(target)
                return LoopAction.Continue

        # 技能 G：核心，持续到无可选项后才进入羁绊。
        if target == "skill":
            # 成功主动打开后按 choice_interval 限制重开；0.0 = 本局未开过 → 首次立即允许。
            if self._last_skill_panel > 0.0 and now - self._last_skill_panel < self.settings.choice_interval:
                return LoopAction.Continue
            if self._panel_episode_count.get("skill", 0) >= self.settings.panel_episode_limit_per_kind:
                self._panel_episode_count["skill"] = 0
                self._advance_l1_cycle("skill")
                print("[L1] 技能本轮安全预算已用完，转入羁绊；下一轮重新开放")
                return LoopAction.Continue
            if self.act_click(self._hud_button_hit(frame, "skill_button", self.CHOICE_BUTTON_RATIOS["skill"]), "OpenSkillPanel"):
                self._last_skill_panel = now
                self._panel_opened_by_us = "skill"
                self._panel_kind = "skill"
                self._panel_state = PanelState.OPEN_REQUESTED
                self._skill_refresh_attempts = 0
                self._l1_cycle_owned_panel = True
                self._l1_cycle_selected = False
                print("[L1] 主动点击 G 技能按钮（本轮持续至无可选项）")
            else:
                print("[L1] G 技能按钮点击被拒绝（不推进冷却）")
            return LoopAction.Continue
        # 羁绊 F / 宝物 V：按显式循环顺序执行。
        if target == "bond" and getattr(self.settings, "auto_bond", True):
            if self._last_bond_attempt > 0.0 and now - self._last_bond_attempt < self.settings.choice_interval:
                return LoopAction.Continue
            if self._panel_episode_count.get("bond", 0) >= self.settings.panel_episode_limit_per_kind:
                self._panel_episode_count["bond"] = 0
                self._advance_l1_cycle("bond")
                print("[L1] 羁绊本轮安全预算已用完，转入宝物；下一轮重新开放")
                return LoopAction.Continue
            if self.act_click(self._hud_button_hit(frame, "bond_button", self.CHOICE_BUTTON_RATIOS["bond"]), "OpenBondPanel"):
                self._last_bond_attempt = now
                self._panel_opened_by_us = "bond"
                self._panel_kind = "bond"
                self._panel_state = PanelState.OPEN_REQUESTED
                self._l1_cycle_owned_panel = True
                self._l1_cycle_selected = False
                print("[L1] 主动点击 F 羁绊按钮（本轮持续至无可选项）")
            else:
                print("[L1] F 羁绊按钮点击被拒绝（不推进循环）")
            return LoopAction.Continue
        if target == "treasure" and getattr(self.settings, "auto_treasure", True):
            if self._last_treasure_attempt > 0.0 and now - self._last_treasure_attempt < self.settings.choice_interval:
                return LoopAction.Continue
            if self._panel_episode_count.get("treasure", 0) >= self.settings.panel_episode_limit_per_kind:
                self._panel_episode_count["treasure"] = 0
                self._advance_l1_cycle("treasure")
                print("[L1] 宝物本轮安全预算已用完，转入进化；下一轮重新开放")
                return LoopAction.Continue
            if self.act_click(self._hud_button_hit(frame, "treasure_button", self.CHOICE_BUTTON_RATIOS["treasure"]), "OpenTreasurePanel"):
                self._last_treasure_attempt = now
                self._panel_opened_by_us = "treasure"
                self._panel_kind = "treasure"
                self._panel_state = PanelState.OPEN_REQUESTED
                self._l1_cycle_owned_panel = True
                self._l1_cycle_selected = False
                print("[L1] 主动点击 V 宝物按钮（本轮持续至无可选项）")
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
            min_text = int(450 * transform.scale * transform.scale)
            if int((gray[ry1:ry2, rx1:rx2] > 140).sum()) < max(15, min_text):
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
            min_mask = max(1, int(20 * transform.scale * transform.scale))
            for rank, mask in masks:
                if int(mask.sum()) >= min_mask:
                    return rank
            return 1

        index = max(range(4), key=lambda i: (row_rank(rows[i]), -i))
        px, py = transform.logical_point(800, rows[index] + 20)
        return MatchResult(f"equipment_affix_{index}", 1.0, px, py, 0, 0,
                           frame.left + px, frame.top + py)

    def _find_evolution_choice(self, frame: Frame, anchor: MatchResult | None) -> MatchResult | None:
        """Recognize the two-card hero-evolution modal and choose its best rarity."""
        if (
            anchor is None
            or anchor.name not in {"skill_giveup_btn", "skill_refresh_btn"}
            or frame.bgr is None
            or not LayoutTransform.is_supported(frame.width, frame.height)
        ):
            return None
        transform = LayoutTransform.from_frame(frame.width, frame.height)
        gray = cv2.cvtColor(frame.bgr, cv2.COLOR_BGR2GRAY)
        gradient = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))

        def edge_count(x: int) -> int:
            rx1, ry1, rx2, ry2 = transform.logical_roi(x - 4, 150, x + 5, 510)
            return int((gradient[ry1:ry2, rx1:rx2] > 80).sum())

        # Evolution uses two wide cards (x≈550..1050).  Skill/bond/treasure
        # use three narrower cards and have strong outer edges near x=408/1201.
        scale_area = transform.scale * transform.scale
        if not (
            edge_count(816) >= max(50, int(900 * scale_area))
            and edge_count(1050) >= max(40, int(700 * scale_area))
            and edge_count(408) < max(30, int(500 * scale_area))
            and edge_count(1201) < max(30, int(500 * scale_area))
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
                return 0  # unknown/grey card
            hue = roi[:, :, 0][colored]
            bands = (
                (6, (hue <= 8) | (hue >= 170)),   # UR/red
                (5, (hue >= 80) & (hue < 103)),   # EX/cyan
                (4, (hue >= 10) & (hue <= 30)),   # SSR/orange
                (3, (hue >= 125) & (hue < 170)),  # SR/purple
                (2, (hue >= 103) & (hue < 125)),  # R/blue
                (1, (hue >= 35) & (hue < 80)),    # N/green
            )
            return max(bands, key=lambda item: int(item[1].sum()))[0]

        ranks = (rarity_rank(540, 790), rarity_rank(810, 1060))
        index = max(range(2), key=lambda i: (ranks[i], -i))
        base_x, base_y = ((666, 300), (933, 300))[index]
        x, y = transform.logical_point(base_x, base_y)
        return MatchResult(
            f"evolution_card_{index}_rank_{ranks[index]}", 1.0,
            x, y, 0, 0, frame.left + x, frame.top + y,
        )

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

    def _maybe_use_inventory_item(self, frame: Frame) -> LoopAction | None:
        """Use inventory consumables in the verified bottom-right inventory ROI (HUD_ONLY)."""
        if self._pending_action is not None and not self._pending_action.is_confirmed(frame) and time.time() < self._pending_action.deadline:
            # 若处于同一帧模拟测试环境下直接放行后续调用
            pass
        if self._black_merchant_present(frame) or self._panel_state != PanelState.CLOSED:
            return None
        now = time.time()
        inventory_roi = (0.64, 0.77, 0.74, 0.98)
        if self.settings.auto_devour_dan and self._bond_bar_nonempty(frame):
            pill = self.find(
                frame, ["danGif"], threshold=0.55,
                scales=self._hot_scales(),
                roi=(0.64, 0.77, 0.74, 0.98),
            )
            if pill:
                if now >= self._devour_dan_next_at and self._devour_dan_consecutive_clicks < 5:
                    baseline_occ = getattr(self, "_bond_bar_occupancy", lambda f: None)(frame)
                    if self.act_click(pill, "UseInventory-swallow_pill"):
                        self._devour_dan_next_at = now + 1.0
                        self._devour_dan_consecutive_clicks += 1
                        self._inventory_next_at = now + 1.0
                        self._pending_action = PendingAction(
                            kind="WAIT_DEVOUR_DAN",
                            target_id="danGif",
                            deadline=now + 2.0,
                            verifier=lambda f: bool(
                                (baseline_occ is not None and getattr(self, "_bond_bar_occupancy", lambda _: None)(f) is not None and getattr(self, "_bond_bar_occupancy", lambda _: None)(f) < baseline_occ)
                                or (not self._bond_bar_nonempty(f))
                                or (self.find(f, ["danGif"], threshold=0.55, scales=self._hot_scales(), roi=(0.64, 0.77, 0.74, 0.98)) is None)
                            ),
                        )
                        return LoopAction.Continue
            else:
                self._devour_dan_consecutive_clicks = 0
        if now < self._inventory_next_at or self._inventory_clicks_this_visit >= 2:
            return None
        hero_card = self.find(
            frame, ["hero_card_item"], threshold=0.75,
            scales=(0.8, 0.9, 1.0, 1.1, 1.2),
            roi=inventory_roi,
        )
        if hero_card is None:
            return None
        pt = (int(hero_card.center[0]), int(hero_card.center[1]))
        if self._inventory_last_pt == pt:
            self._inventory_same_pt_hits += 1
            if self._inventory_same_pt_hits > 2:
                # 同点粘滞：超过2次视为静态误匹配，禁止本轮继续点卡。
                self._inventory_clicks_this_visit = 2
                return None
        else:
            self._inventory_last_pt = pt
            self._inventory_same_pt_hits = 1
        if self.act_click(hero_card, "UseInventory-hero-card"):
            self._inventory_clicks_this_visit += 1
            self._inventory_next_at = now + 1.0
            self._pending_action = PendingAction(
                kind="WAIT_HERO_CHOICE",
                target_id="hero_card_item",
                deadline=now + 3.0,
                verifier=lambda f: bool(self._selection_anchor(f) is not None and self._find_evolution_choice(f, self._selection_anchor(f))),
            )
            return LoopAction.Continue
        return LoopAction.Continue
    def _maybe_upgrade_equipment(self, frame: Frame) -> LoopAction:
        """Upgrade weapon/equipment in verified HUD_ONLY inventory ROI.

        Rules:
        - 1 号格：保留右键最大升级（最小间隔 8s）；
        - 2-6 号格：每 30 秒执行一轮巡检，每 tick 顺序左键一个格子（2→3→4→5→6）；
        - 门禁：仅在 InteractionSurface.HUD_ONLY 下执行，一旦有任何弹窗立即冻结整轮。
        """
        if self._pending_action is not None and not self._pending_action.is_confirmed(frame):
            return LoopAction.Continue
        if self._black_merchant_present(frame) or self._panel_state != PanelState.CLOSED:
            return LoopAction.Continue
        now = time.time()
        item = self._maybe_use_inventory_item(frame)
        if item is not None:
            return item
        if self._equipment_pending_until:
            if now < self._equipment_pending_until:
                return LoopAction.Continue
            self._equipment_pending_until = 0.0
            self._advance_l1_cycle("equipment")
            return LoopAction.Continue

        # 1号格升级 (右键最大升级，8s 间隔)
        if now >= self._equipment_next_at and self._equipment_slot_one_occupied(frame):
            hit = self._hud_button_hit(frame, "equipment_slot_1", (1087 / 1600, 737 / 900))
            if self.act_right_click(hit, "UpgradeEquipmentSlot1-max"):
                self._equipment_pending_until = now + self.settings.ui_action_interval_s
                self._equipment_next_at = now + 8.0
                return LoopAction.Continue

        # 2-6号格巡检 (每 30s 一轮，每 tick 左键一个格子 2->3->4->5->6)
        if now >= self._equipment_round_next_at:
            slot_idx = self._equipment_round_current_slot
            # 标准 6 格坐标 (1600x900)
            slot_coords = {
                2: (1145 / 1600, 737 / 900),
                3: (1087 / 1600, 785 / 900),
                4: (1145 / 1600, 785 / 900),
                5: (1087 / 1600, 833 / 900),
                6: (1145 / 1600, 833 / 900),
            }
            if slot_idx in slot_coords:
                hit_slot = self._hud_button_hit(frame, f"equipment_slot_{slot_idx}", slot_coords[slot_idx])
                if self.act_click(hit_slot, f"UpgradeEquipmentSlot{slot_idx}-check"):
                    self._equipment_round_current_slot += 1
                    if self._equipment_round_current_slot > 6:
                        self._equipment_round_current_slot = 2
                        self._equipment_round_next_at = now + 30.0
                    self._equipment_pending_until = now + float(self.settings.ui_action_interval_s)
                return LoopAction.Continue

        self._advance_l1_cycle("equipment")
        return LoopAction.Continue

    @staticmethod
    def _black_merchant_present(frame: Frame) -> bool:
        """Detect the five-card merchant strip above the bottom-right inventory."""
        if frame.bgr is None or not LayoutTransform.is_supported(frame.width, frame.height):
            return False
        transform = LayoutTransform.from_frame(frame.width, frame.height)
        rx1, ry1, rx2, ry2 = transform.logical_roi(
            int(1600 * 0.70), int(900 * 0.67), int(1600 * 0.94), int(900 * 0.79)
        )
        roi = frame.bgr[ry1:ry2, rx1:rx2]
        if roi.size == 0:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        green = (
            (hsv[:, :, 0] >= 35)
            & (hsv[:, :, 0] <= 90)
            & (hsv[:, :, 1] > 100)
            & (hsv[:, :, 2] > 80)
        )
        min_green = max(50, int(1000 * transform.scale * transform.scale))
        return int(green.sum()) >= min_green

    @staticmethod
    def _bond_bar_nonempty(frame: Frame) -> bool:
        """Conservative prerequisite for consuming a merchant swallow pill."""
        if frame.bgr is None or not LayoutTransform.is_supported(frame.width, frame.height):
            return False
        transform = LayoutTransform.from_frame(frame.width, frame.height)
        rx1, ry1, rx2, ry2 = transform.logical_roi(
            int(1600 * 0.35), int(900 * 0.68), int(1600 * 0.42), int(900 * 0.78)
        )
        roi = frame.bgr[ry1:ry2, rx1:rx2]
        if roi.size == 0:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        colored = (hsv[:, :, 1] > 85) & (hsv[:, :, 2] > 65)
        min_colored = max(20, int(250 * transform.scale * transform.scale))
        return int(colored.sum()) >= min_colored

    @staticmethod
    def _merchant_refresh_available(frame: Frame) -> bool:
        if frame.bgr is None or not LayoutTransform.is_supported(frame.width, frame.height):
            return False
        transform = LayoutTransform.from_frame(frame.width, frame.height)
        rx1, ry1, rx2, ry2 = transform.logical_roi(
            int(1600 * 0.89), int(900 * 0.67), int(1600 * 0.93), int(900 * 0.78)
        )
        roi = frame.bgr[ry1:ry2, rx1:rx2]
        if roi.size == 0:
            return False
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        gold = (
            (hsv[:, :, 0] >= 10)
            & (hsv[:, :, 0] <= 35)
            & (hsv[:, :, 1] > 80)
            & (hsv[:, :, 2] > 90)
        )
        min_gold = max(10, int(80 * transform.scale * transform.scale))
        return int(gold.sum()) >= min_gold

    def _maybe_black_merchant(self, frame: Frame) -> MatchResult | None:
        """Buy known safe merchant items according to 5-slot priority, otherwise perform guarded refresh.
        Priority:
        1. 命中 1折/2折/3折/4折/5折 等折扣小模板 -> 直接购买
        2. 命中 吞噬丹 icon 小模板 (danGif) -> 仅当羁绊栏非空时直接购买
        3. 命中 木材礼包 icon 小模板 (merchant_wood / woodgift) -> 直接购买
        4. 属性路线匹配 (智力 / 力量 / 敏捷)
        5. 偏好技能 / 羁绊卡片匹配
        6. 免费刷新 (仅在开启刷新时)
        7. 严格过滤负面宝物与负收益物品

        实验性/未验证：仅当显式配置 auto_gambling_time > 0 时本路径才可能产生 find/click；
        默认 0 -> 第一行直接零输入返回（falsy）。
        """
        if int(getattr(self.settings, "auto_gambling_time", 0) or 0) <= 0:
            return None
        now = time.time()
        if now < self._merchant_next_at or not self._black_merchant_present(frame):
            return None

        # 5 槽扫描与决策
        scanner = MerchantScanner(
            attr_routes=getattr(self.settings, "attr_route", None) or [],
            focus_skills=getattr(self.settings, "focus_skills", None) or [],
            focus_bonds=getattr(self.settings, "bonds", None) or [],
            auto_refresh=bool(getattr(self.settings, "auto_gambling", False)),
        )

        roi = (0.70, 0.67, 0.90, 0.79)
        detected_slots: list[MerchantSlotItem] = []

        # 1. 吞噬丹 (danGif) 探测
        if self._bond_bar_nonempty(frame):
            pill = self.find(
                frame,
                ["danGif"],
                threshold=0.50,
                scales=(0.5, 0.6, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5),
                roi=roi,
            )
            if pill is not None:
                # 估算归属哪个槽位 (0..4)
                rx = (pill.x - frame.width * 0.70) / (frame.width * 0.20)
                slot_idx = max(0, min(4, int(rx * 5.0)))
                detected_slots.append(
                    MerchantSlotItem(
                        slot_index=slot_idx,
                        center_ratio=(pill.x / frame.width, pill.y / frame.height),
                        item_type="devour_pill",
                        label="danGif",
                    )
                )

        # 2. 木材礼包探测
        wood = self.find(
            frame,
            ["merchant_wood", "woodgift"],
            threshold=0.72,
            scales=(0.75, 0.9, 1.0, 1.1, 1.25),
            roi=roi,
        )
        if wood is not None:
            rx = (wood.x - frame.width * 0.70) / (frame.width * 0.20)
            slot_idx = max(0, min(4, int(rx * 5.0)))
            detected_slots.append(
                MerchantSlotItem(
                    slot_index=slot_idx,
                    center_ratio=(wood.x / frame.width, wood.y / frame.height),
                    item_type="wood",
                    label="merchant_wood",
                )
            )

        # 排序购买候选
        ranked = scanner.rank_purchases(
            detected_slots,
            bond_bar_nonempty=self._bond_bar_nonempty(frame),
        )

        if ranked:
            target_item = ranked[0]
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
            if self.act_click(hit, action_name):
                self._merchant_next_at = now + 15.0
                return LoopAction.Continue

        # 若无匹配商品且允许刷新 (scanner.auto_refresh 或 settings.auto_gambling 为 True 时才点击刷新)
        if scanner.auto_refresh and self._merchant_refresh_available(frame):
            refresh = self._hud_button_hit(frame, "black_merchant_refresh", (0.91, 0.72))
            if self.act_click(refresh, "BlackMerchant-refresh"):
                self._merchant_next_at = now + self._control_recheck_interval_s
                return LoopAction.Continue
        self._merchant_next_at = now + 15.0
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
            names = ["card_hide", "treasure_hide_btn", "skill_hide", "hide"]
        elif kind in ("bond", "card"):
            names = ["card_hide", "bond_hide_btn", "skill_hide", "hide"]
        else:
            names = [
                "skill_hide", "card_hide", "bond_hide_btn",
                "treasure_hide_btn", "hide",
            ]
        hit = self.find(
            frame,
            names,
            threshold=min(0.70, self.settings.match_threshold),
            scales=self._hot_scales(),
            roi=self._PANEL_BUTTONS_ROI,
            early_stop=True,
        )
        if hit is None and self._scaled_up_frame(frame):
            hit = self.find(
                frame,
                names,
                threshold=min(0.70, self.settings.match_threshold),
                scales=self._wide_scales(),
                roi=self._PANEL_BUTTONS_ROI,
                early_stop=True,
            )
        return hit

    # ---------- 战后页面多锚点判别（P1-B0/B1）----------

    # 战后模板的已知位置 ROI（1600x900 基准比例，经 replay/postgame fixtures 验证）。
    _POST_GAME_ROIS = {
        "pauseGame": (0.30, 0.30, 0.70, 0.60),
        "continueGame": (0.40, 0.50, 0.65, 0.75),
        "cjbtiaozhan": (0.35, 0.15, 0.65, 0.40),
        "mijingOk": (0.30, 0.40, 0.60, 0.65),
        "ok": (0.30, 0.40, 0.60, 0.65),
        "archiveChallenge": (0.40, 0.00, 0.60, 0.08),
        "close": (0.55, 0.15, 0.70, 0.35),
        "damijing": (0.60, 0.15, 1.00, 0.55),
        "quit": (0.00, 0.00, 0.12, 0.15),
        "HeroChallenge": (0.00, 0.00, 0.30, 0.20),
    }

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
        """
        w, h = frame.width, frame.height
        if w < 480 or h < 270:
            return None
        key = ("post_game", round(self._ui_scale, 3))

        def compute() -> str | None:
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
            if paused and w * 0.35 <= paused.x <= w * 0.60 and h * 0.35 <= paused.y <= h * 0.55:
                return "PAUSED"

            # 选择面板存在时，战后独占页（胜利/传家宝/大秘境/存档/广场）不可能与
            # 局内选择面板同时出现：跳过剩余战后扫描（N2.4：提前到 victory 锚点
            # 之前，选择 tick 不再每 tick 扫战后库；PAUSED 已先行检查不受影响）。
            if self._selection_anchor(frame):
                return None

            # 1) Victory: continue button is unique to the victory modal.
            if find("continueGame", 0.80):
                return "POST_VICTORY"

            # 2) Heirloom: cjbtiaozhan banner is unique to the heirloom dialog.
            if find("cjbtiaozhan", 0.80):
                return "HEIRLOOM_DIALOG"

            # 3) Great rift confirm: ok/mijingOk in the dialog body (center), not the
            #    right-side rift NPC icon or the bottom action strip.
            for name, th in (("mijingOk", 0.75), ("ok", 0.85)):
                m = find(name, th)
                if m and w * 0.30 <= m.x <= w * 0.60 and h * 0.40 <= m.y <= h * 0.65:
                    return "GREAT_RIFT_CONFIRM"

            # 4) Archive panel: archive tab + a modal close button (right of center,
            #    upper half) and NO rift NPC icon on the right side.
            arch = find("archiveChallenge", 0.85)
            close_hit = find("close", 0.85)
            rift_npc = find("damijing", 0.80)
            rift_npc_right = rift_npc and rift_npc.x >= w * 0.60 and h * 0.15 <= rift_npc.y <= h * 0.55
            if arch and close_hit and close_hit.x >= w * 0.55 and close_hit.y <= h * 0.40 and not rift_npc_right:
                return "ARCHIVE_PANEL"

            # 5) NPC hub: quit button at the very top-left + rift NPC on the right +
            #    the hero challenge indicator.
            quit_hit = find("quit", 0.75)
            hero_hit = find("HeroChallenge", 0.85)
            if quit_hit and quit_hit.x <= w * 0.10 and quit_hit.y <= h * 0.15 and rift_npc_right and hero_hit:
                return "NPC_HUB"

            return None

        return self._memo(key, frame, compute)

    def _find_archive_panel_close(self, frame: Frame) -> MatchResult | None:
        hit = self.find(
            frame,
            ["lobby/archive_panel_close"],
            threshold=0.85,
            scales=self._hot_scales(),
            roi=(0.55, 0.15, 0.70, 0.35),
        )
        if not hit:
            return None
        if not (frame.width * 0.55 <= hit.x <= frame.width * 0.70):
            return None
        if not (frame.height * 0.15 <= hit.y <= frame.height * 0.35):
            return None
        return hit

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
        if not hit:
            return None
        if hit.x > frame.width * 0.12 or hit.y > frame.height * 0.15:
            return None
        return hit

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
        card = self.find(frame, [spec.unselected_template], threshold=0.90)
        xmin, xmax, ymin, ymax = spec.card_match_window
        if not card or not (xmin <= card.x <= xmax and ymin <= card.y <= ymax):
            return False
        roi = self._hero_roi(frame, spec.level_roi)
        template_path = resolve_template(self.images, "lobby/hero_level_zero")
        if roi is None or template_path is None:
            return False
        template = _load_template(template_path)
        if template is None:
            return False
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        if template_gray.shape != roi.shape:
            return False
        score = float(cv2.matchTemplate(roi, template_gray, cv2.TM_CCOEFF_NORMED)[0, 0])
        return score >= 0.95

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

    def _begin_hero_setup(self, frame: Frame) -> LoopAction:
        rep_type = int(getattr(self.settings, "reputation_type", 0) or 0)
        rep_level = int(getattr(self.settings, "reputation_level", 0) or 0)
        if not 1 <= rep_level <= 5:
            return self._hero_fail("英雄模式仅支持 1–5 级")
        spec = FACTION_SPECS.get(rep_type)
        if spec is None:
            return self._hero_fail(f"未知阵营类型 {rep_type}")
        if not spec.verified:
            return self._hero_fail(f"阵营{spec.name}缺少实机未选中模板")
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

    def _maybe_switch_to_archaeology(self, frame: Frame) -> LoopAction | None:
        """Challenge ticket exhausted → click 考古模式 → stop script.

        Confirms 3 consecutive frames before acting to avoid a flicker false
        positive. Returns LoopAction.Break after switching, None otherwise.
        """
        if not getattr(self.settings, "auto_archaeology", True):
            return None
        if self._ticket_exhausted(frame):
            count = getattr(self, "_ticket_zero_frames", 0) + 1
            self._ticket_zero_frames = count
            if count < 3:
                print(f"[L0] 挑战券剩余为 0（确认 {count}/3），等待稳定…")
                return LoopAction.Continue
            print("[L0] 挑战券已清空，点击考古模式并结束脚本")
            arch_hit = MatchResult(
                name="archaeology_switch",
                score=1.0,
                x=int(frame.width * 0.86),
                y=int(frame.height * 0.903),
                w=0,
                h=0,
                screen_x=frame.left + int(frame.width * 0.86),
                screen_y=frame.top + int(frame.height * 0.903),
            )
            result = self.act_click(arch_hit, "SwitchToArchaeology")
            self._ticket_zero_frames = 0
            if not result:
                self.set_phase(Phase.ERROR, "archaeology switch input rejected")
                self.stop()
                return LoopAction.Break
            self.set_phase(Phase.QUIT, "archaeology mode after challenge ticket exhausted")
            self.stop()
            return LoopAction.Break
        self._ticket_zero_frames = 0
        return None

    def _current_faction_spec(self) -> "FactionSpec":
        rep_type = int(getattr(self.settings, "reputation_type", 0) or 0)
        return FACTION_SPECS.get(rep_type, FACTION_SPECS[3])

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
        target_level = int(self.settings.reputation_level)

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
            if self._hero_verified_level == 1:
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

            start = buttons[0]
            if not self.act_click(start, "StartHeroModeChallenge"):
                return LoopAction.Continue
            self._hero_state = "WAIT_MODAL_CLOSE"
            self._hero_modal_missing_frames = 0
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

    def set_phase(self, phase: Phase, note: str = "") -> None:
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
        if phase == Phase.STAGE_SELECT:
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
            self._round_outcome = None
            # S0 ⑤：跨局每类面板会话计数清零（上限按"每局每类"计）
            self._panel_episode_count = {}
            self._panel_state = PanelState.CLOSED
            self._panel_opened_by_us = None
            self._panel_fingerprint = None
            self._panel_fingerprint_attempts = 0
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
        if phase == Phase.MAIN_LINE:
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
            self._challenge_done.clear()
            self._challenge_attempts.clear()
            self._challenge_unknown_since.clear()
            self._challenge_pending_since.clear()
            self._challenge_next_observe_at.clear()
            self._challenge_recheck_at.clear()
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
            self._auto_task_unknown_since = None
            self._victory_continue_attempts = 0
            self._victory_continue_since = None
            self._post_game_pending = False
            self._post_game_close_attempts = 0
            self._secret_realm_request_pending = False
            self._secret_realm_request_since = None
            self._secret_realm_request_attempts = 0
            self._secret_realm_next_observe_at = 0.0
            self._secret_realm_entering_since = None
            self._secret_realm_confirm_attempts = 0
            self._secret_realm_confirm_next_observe_at = 0.0
            self._secret_realm_active = False
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
            if self._round_deadline is None:
                self._round_started_at = time.time()
                self._round_deadline = self._round_started_at + self.settings.round_timeout_s
            # S0 ⑤ 跨局 L1 瞬态重置：主动面板标记/神器 CD/主动面板时间戳/进化冷却
            self._panel_state = PanelState.CLOSED
            self._panel_opened_by_us = None
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
            self._l1_cycle_step = "skill"
            self._l1_cycle_owned_panel = False
            self._l1_cycle_selected = False
            self._merchant_next_at = 0.0
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
        anchor plus a red/green sibling pair in its constrained bottom row.
        """
        fail = self.find_scene(frame, "fail")
        if fail is None or frame.bgr is None or frame.width < 1000 or frame.height < 600:
            return None
        x0, x1 = int(frame.width * 0.30), int(frame.width * 0.70)
        y0, y1 = int(frame.height * 0.55), int(frame.height * 0.74)
        roi = frame.bgr[y0:y1, x0:x1]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        def components(mask: np.ndarray) -> list[tuple[int, int, int, int, int]]:
            count, _labels, stats, _centers = cv2.connectedComponentsWithStats(
                mask.astype("uint8")
            )
            out = []
            for x, y, w, h, area in stats[1:count]:
                if 70 <= w <= 180 and 22 <= h <= 65 and area >= 1200:
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
            if any(gx > rx and abs((gy + gh // 2) - rcy) <= 15
                   for gx, gy, gw, gh, _area in green):
                x, y = x0 + rcx, y0 + rcy
                return MatchResult(
                    "failure_exit", min(1.0, area / 2500.0), x, y, rw, rh,
                    frame.left + x, frame.top + y,
                )
        return None

    def _recovery_post_confirmed(self, frame: Frame, rs: RecoveryState) -> bool:
        """WAIT_CONFIRM 后置确认：画面 mutation（模板消失）∨ 必需 post-anchor 出现。"""
        if rs.step == RecoveryStep.FAIL_CONFIRM:
            if rs.opening_exit_confirm:
                confirm = self._find_exit_confirm(frame)
                if confirm is not None:
                    rs.post_anchor_seen = True
                    return True
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
            self._hitch_after_exit(now)
            return LoopAction.Continue
        self._awaiting_room_return = True
        self.set_phase(Phase.PREPARE, "failure exit clicked; verify same room")
        self._room_action_deadline = now + min(self.settings.query_timeout, 30)
        return LoopAction.Continue

    def _recovery_failed(self, rs: RecoveryState, reason: str) -> LoopAction:
        """恢复重试耗尽/总预算到期：直接 ERROR、停止、写 incident；不能盲目 QUIT。"""
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
            rs.confirm_window = min(15.0, rs.deadline - now)
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

    def _passive_choice_mode(self) -> bool:
        return self._hitch_enabled() or self._follow_enabled()

    def _hitch_ocr_text(self) -> str:
        override = getattr(self, "_hitch_ocr_override", None)
        if override is not None:
            return str(override)
        return ""

    def _hitch_prefix_ok(self) -> bool:
        return has_prefix_evidence(self._hitch_ocr_text(), self._hitch_sm.prefix)

    def _hitch_room_matched(self) -> bool:
        if not self._hitch_prefix_ok():
            return False
        override = getattr(self, "_hitch_match_override", None)
        if override is not None:
            return bool(override)
        return True

    def _hitch_action_hit(self, frame: Frame, action: HitchAction):
        override = getattr(self, "_hitch_hit_override", None)
        if override is not None:
            return override
        keys = {
            HitchAction.REFRESH: ("lobby_refresh", "refresh"),
            HitchAction.JOIN: ("lobby_join", "room_list_row"),
            HitchAction.GO_HOME: ("lobby_home", "lobby_back"),
        }
        for key in keys.get(action, ()):
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

    def _new_hitch_sm(self) -> HitchSearchSM:
        return HitchSearchSM(
            prefix=self._hitch_sm.prefix,
            refresh_s_min=self._hitch_sm.refresh_s_min,
            refresh_s_max=self._hitch_sm.refresh_s_max,
        )

    def _hitch_after_exit(self, now: float) -> None:
        self._awaiting_room_return = False
        self._hitch_re_search = True
        self._hitch_sm = self._new_hitch_sm()
        self._hitch_status = "search"
        self.set_phase(Phase.LOBBY_ROOM, "hitch exit; re-search lobby")

    def _hitch_reset_lobby(self, evidence: str, now: float) -> LoopAction:
        print(f"[L0] hitch {evidence}，重置大厅状态机（不记战斗超时）")
        self._round_deadline = None
        self._round_started_at = None
        self._main_line_since = None
        self._hitch_sm.reset_lobby(now, evidence)
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

    def _tick_lobby_hitch(
        self,
        frame: Frame,
        context: str,
        room_start=None,
        stage_page: bool = False,
    ) -> LoopAction:
        now = time.time()
        event = classify_hitch_ocr(self._hitch_ocr_text())
        if event:
            return self._hitch_reset_lobby(event, now)
        if context in ("MAIN_LINE", "IN_GAME"):
            self._hitch_re_search = False
            self.set_phase(Phase.MAIN_LINE, "hitch already in game")
            return LoopAction.Continue
        if stage_page or context == "STAGE_SELECT":
            self._hitch_re_search = False
            self.set_phase(Phase.STAGE_SELECT, "hitch stage page wait")
            print("[L0] hitch 选关页可见，零输入等待进局（不点关卡）")
            return LoopAction.Continue
        in_room = room_start is not None or context == "ROOM_WAITING"
        if in_room and not self._hitch_re_search:
            if self._hitch_sm.pending_join:
                self._hitch_sm.complete_join()
                self._hitch_join_refresh_count = self._hitch_sm.attempts
            self.set_phase(Phase.ROOM_WAITING, "hitch in room waiting host")
            print("[L0] hitch 已进房，等待房主开始（不点 RoomStart）")
            return LoopAction.Continue
        if self._hitch_re_search and in_room:
            hit = self._hitch_action_hit(frame, HitchAction.GO_HOME)
            if hit is not None:
                self.act_click(hit, "HitchLeaveRoom")
            print("[L0] hitch 战后仍在房，尝试离房回大厅列表")
            return LoopAction.Continue
        if self._hitch_re_search and not in_room:
            self._hitch_re_search = False
        if self._hitch_sm.can_confirm_lobby_home(now, self._hitch_lobby_home_visible(frame)):
            self._hitch_sm.confirm_lobby_home()
            self._hitch_status = "大厅主页"
            print("[L0] hitch unmatched 后置确认大厅主页")
            self.set_phase(Phase.LOBBY_ROOM, "hitch 大厅主页")
            return LoopAction.Continue
        prefix_ok = self._hitch_prefix_ok()
        decision = self._hitch_sm.tick(
            now=now,
            matched=self._hitch_room_matched(),
            ocr_text=self._hitch_ocr_text(),
            prefix_ok=prefix_ok,
            in_room=in_room,
        )
        if decision.action == HitchAction.REFRESH:
            hit = self._hitch_action_hit(frame, HitchAction.REFRESH)
            if hit is None:
                print("[L0] hitch REFRESH 无大厅刷新锚点，零输入观察")
                self.set_phase(Phase.LOBBY_ROOM, "hitch search observe")
                return LoopAction.Continue
            if self.act_click(hit, "HitchRefresh"):
                self._hitch_sm.note_refresh(now)
                self._hitch_search_actions.append("refresh")
                self._hitch_join_refresh_count = self._hitch_sm.attempts
                self._hitch_status = "search"
                print(
                    f"[L0] hitch refresh attempt={self._hitch_sm.attempts}/"
                    f"{JOIN_ATTEMPTS} prefix={self._hitch_sm.prefix}"
                )
            self.set_phase(Phase.LOBBY_ROOM, "hitch refresh")
            return LoopAction.Continue
        if decision.action == HitchAction.JOIN:
            if not prefix_ok:
                print("[L0] hitch JOIN 无 3/4 前缀证据，拒绝进房")
                self.set_phase(Phase.LOBBY_ROOM, "hitch search")
                return LoopAction.Continue
            hit = self._hitch_action_hit(frame, HitchAction.JOIN)
            if hit is None:
                print("[L0] hitch JOIN 无房间行锚点，零输入观察")
                self.set_phase(Phase.LOBBY_ROOM, "hitch search observe")
                return LoopAction.Continue
            if self.act_click(hit, "HitchJoin"):
                self._hitch_sm.note_join_click(now)
                self._hitch_search_actions.append("join")
                self._hitch_status = "search"
                print(f"[L0] hitch join prefix={self._hitch_sm.prefix}（等待进房后置确认）")
            self.set_phase(Phase.LOBBY_ROOM, "hitch join")
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
                print("[L0] hitch GO_HOME 无导航锚点，零输入观察")
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
        if not self._find_stage_page(frame):
            return None
        hit = self.find_scene(frame, "stage_start", threshold=self._STAGE_START_THRESHOLD)
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

    def _find_stage_page(self, frame: Frame) -> bool:
        key = ("stage_page",)

        def compute() -> bool:
            if self._visible_stage_rows(frame):
                return True
            # The numbered-row parser above is the preferred detector.  The
            # legacy image fallback is only meaningful on the actual game window;
            # scanning it on a KK map page is both slow and prone to false hits.
            title = frame.window_title.lower()
            game_keywords = [keyword for keyword in L1_WINDOW_KEYWORDS if keyword.lower() != "kk"]
            if not title or not any(keyword.lower() in title for keyword in game_keywords):
                return False
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
        values = (self.settings.room_name, self.settings.room_password)
        target_hwnd = self._last_frame.hwnd if self._last_frame else None
        sent_any = False
        for box, value in zip(boxes[:2], values):
            if not self.act_click(box, "CreateRoom-focus-input"):
                return False
            res_hk = self.executor.hotkey("ctrl", "a", target_hwnd=target_hwnd, dry_run=self.settings.dry_run)
            if not res_hk.success:
                print(f"[L0] 建房弹窗 hotkey ctrl+a 失败/取消: {res_hk.message}")
                return False
            res_paste = self.executor.paste_text(value, target_hwnd=target_hwnd, dry_run=self.settings.dry_run)
            if not res_paste.success:
                print(f"[L0] 建房弹窗 paste_text 失败/取消: {res_paste.message}")
                return False
            sent_any = True
        if sent_any:
            self._tick_input_executed = True
            self._input_seq += 1  # N2-REVIEW #3：与 _finish_input 同语义
            if not self.settings.dry_run:
                # 填写是同一逻辑动作序列（目标来自本帧证据）；序列结束后统一失效，
                # 防止下一 tick 用填写前的旧证据授权动作。
                self.invalidate_evidence("input")
        print("[L0] 建房弹窗已填写房间名/密码")
        return True

    def _l0_transition_timeout(self) -> float:
        """Macro timeout for recoverable L0 alignment episodes."""
        try:
            configured = float(self.settings.query_timeout)
        except (TypeError, ValueError):
            configured = self._L0_TRANSITION_TIMEOUT_S
        return max(30.0, min(configured, self._L0_TRANSITION_TIMEOUT_S))

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
            self._challenge_start_attempts += 1  # telemetry only
            print(
                f"[L0] 选关后未进局，仍在选关页；回到状态对齐重选 "
                f"(telemetry={self._challenge_start_attempts})"
            )
            self._stage_selected = False
            self._stage_target_name = None
            self.set_phase(Phase.STAGE_SELECT, "challenge start realign")
            return LoopAction.Continue
        print("[L0] 选关后超时且选关页/英雄入口均消失（页面异变），停止运行")
        self.set_phase(Phase.ERROR, "challenge start page mutation")
        self.stop()
        return LoopAction.Break

    def _tick_l0(self, frame: Frame) -> LoopAction:
        """Handle map → create dialog → room → stage without guessing clicks."""
        # The hero modal has its own exact guards.  Skipping the generic L0
        # classifier here also avoids several full-screen template scans while
        # waiting for one small, time-sensitive digit change.
        if self.phase == Phase.HERO_SETUP:
            return self._tick_hero_setup(frame)

        context = self._detect_context(frame, "l0")
        print(f"[med] decision context={context} phase={self.phase.name}")
        # 选关页底部也会误匹配通用 room_start；沿用分类器的优先级，
        # 先确认编号关卡页，再查房间开始按钮。
        stage_page = context == "STAGE_SELECT"
        room_start = None if stage_page else self._find_room_start(frame)

        if self._awaiting_room_return and self._hitch_enabled():
            self._awaiting_room_return = False
            self._hitch_re_search = True

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
                # S0 ⑥：cycle_num>0 且已完成指定局数 → COMPLETE 停止，绝不点下一局开始
                if self.settings.cycle_num > 0 and self.game_count >= self.settings.cycle_num:
                    print(f"[med] 已完成 cycle_num={self.settings.cycle_num} 局，转 COMPLETE 停止（不点下一局开始）")
                    self.set_phase(Phase.COMPLETE, "cycle_num reached")
                    self.stop()
                    return LoopAction.Break
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
            return LoopAction.Continue

        if self.phase == Phase.ROOM_WAITING:
            if stage_page:
                self.set_phase(Phase.STAGE_SELECT, "stage page after room")
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
            if not stage_page:
                if self._action_timed_out():
                    print("[L0] 选关页消失但未出现局内 UI，回到房间等待")
                    self.set_phase(Phase.ROOM_WAITING, "stage page disappeared")
                return LoopAction.Continue
            # 黄色挑战券清空 → 自动进考古模式并结束脚本
            arch_res = self._maybe_switch_to_archaeology(frame)
            if arch_res is not None:
                return arch_res
            now = time.time()
            if self._action_timed_out():
                print("[L0] 选关状态对齐超过宏观期限，停止而不点击任意关卡")
                self.set_phase(Phase.ERROR, "configured stage alignment timeout")
                self.stop()
                return LoopAction.Break
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
                    res_scroll = self.executor.scroll(
                        x, y, -2,
                        target_hwnd=target_hwnd,
                        dry_run=self.settings.dry_run,
                    )
                    if res_scroll.success:
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
                stable_candidate = (
                    self._stage_candidate_name == target.name
                    and self._stage_candidate_position is not None
                    and abs(self._stage_candidate_position[0] - position[0]) <= 3
                    and abs(self._stage_candidate_position[1] - position[1]) <= 3
                )
                if stable_candidate:
                    self._stage_candidate_frames += 1
                else:
                    self._stage_candidate_name = target.name
                    self._stage_candidate_position = position
                    self._stage_candidate_frames = 1
                if self._stage_candidate_frames < 2:
                    print(f"[L0] 目标关卡 {target.name} 首帧命中，等待坐标稳定复核（零动作）")
                    return LoopAction.Continue
                print(f"[L0] 选关 SelectStage {target.name} @ {target.center}")
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
            # 正向证据优先：整圈奶白亮边的那一行才是选中行。高亮明确落在别的关卡时
            # 一律重点目标行，绝不靠「同名 + 相邻 + 有开始按钮」放行——20260814 实机
            # 就是高亮还留在 1-1（首次点击被窗口激活吞掉），脚本却按间接证据开了 1-1。
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
            if highlighted is None or wanted_id is None:
                print("[L0] 目标行无高亮，重点目标行，不开始游戏")
                self._stage_selected = False
                self._stage_target_name = None
                self._stage_target_position = None
                self._stage_candidate_name = None
                self._stage_candidate_position = None
                self._stage_candidate_frames = 0
                return LoopAction.Continue
            print(f"[L0] 目标关卡 {wanted_id} 高亮已确认")
            if self.settings.auto_reputation:
                return self._begin_hero_setup(frame)
            start = self._find_stage_start(frame)
            if not start:
                print("[L0] 已选关，但未找到棕色开始游戏按钮")
                return LoopAction.Continue
            print(f"[L0] 选关后点击开始 {start.name} score={start.score:.3f}")
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

    def stop(self) -> None:
        self._running = False
        self.stop_signal.trigger("Mediator.stop()")

    def tick(self) -> LoopAction:
        """单步：一帧截屏 → 按阶段决策 → 执行。"""
        self._tick_no += 1
        t0 = time.perf_counter()
        phase_before = self.phase.name
        phase_before_value = self.phase
        try:
            action = self._tick_impl()
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
        self._trace_fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._trace_fh.flush()

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

        现成确认点：失败恢复链完成（_recovery_step == "DONE"）说明
        FAIL→OK→CLOSE 三步点击均已被后续帧确认。B3/B4 的 OCR/选择
        后置确认在此阶段尚未实现。
        """
        if self._recovery_step == "DONE":
            return True
        return None

    def _tick_impl(self) -> LoopAction:
        self._trace_actions = []
        self._trace_scenes = []
        self._trace_controls = []
        self._trace_ocr_suggestion = None
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
                        print("[med] STAGE_SELECT 不健康帧超过宏观期限，停止运行")
                        self.set_phase(Phase.ERROR, "stage select unhealthy alignment timeout")
                        self.stop()
                        return LoopAction.Break
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

        # Target window foreground check: if target HWND lost foreground, pause business inputs
        # and invalidate cached evidence / OCR / coordinates.
        if not self.settings.dry_run and isinstance(self.executor, InputExecutor) and frame.hwnd and is_window_valid(frame.hwnd):
            fg = get_foreground_window()
            if not foreground_matches_target(frame.hwnd, fg):
                print(f"[med] target hwnd={frame.hwnd} lost foreground (fg={fg}), invalidating evidence and pausing inputs")
                self.invalidate_evidence("foreground-lost")
                if not self._reacquire_target_window(frame.hwnd):
                    print(f"[med] cannot reacquire foreground for hwnd={frame.hwnd}, waiting next tick")
                    return LoopAction.Continue

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

        disconnect_hit = self.find_scene(frame, "disconnect")
        strong_fail_hit = None if disconnect_hit else self.find_scene(frame, "fail")
        if disconnect_hit or strong_fail_hit:
            kind = "DISCONNECT" if disconnect_hit else "FAIL"
            if self._recovery_step == "DONE" and self.phase == Phase.QUIT:
                # 恢复完成后旧失败像素可能残留（QUIT 打开退出确认期间）：不重复恢复。
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
        if opened in ("skill", "bond", "treasure"):
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

    def _arm_panel_reopen_cooldown(self, kind: str | None, now: float) -> None:
        if kind not in ("skill", "bond", "treasure"):
            return
        delay = max(10.0, min(15.0, float(getattr(self.settings, "panel_reopen_cooldown_s", 12.0))))
        self._panel_cooldown_until[kind] = max(
            self._panel_cooldown_until.get(kind, 0.0), now + delay
        )

    def _stage_panel_choice_action(self, action: str, fingerprint: tuple | None) -> None:
        self._panel_pending_choice_action = action
        self._panel_pending_choice_fingerprint = fingerprint

    def _confirm_panel_choice_action(self, now: float) -> None:
        action = self._panel_pending_choice_action
        if action == "select":
            if (
                self._l1_cycle_owned_panel
                and self._panel_kind == self._l1_cycle_step
                and self._panel_kind in ("skill", "bond", "treasure")
            ):
                self._l1_cycle_selected = True
            if self._panel_kind == "skill":
                # Only a *confirmed* skill selection may bypass normal reopen cadence.
                self._last_skill_panel = 0.0
        elif action == "close":
            self._arm_panel_reopen_cooldown(self._panel_kind, now)
        self._panel_pending_choice_action = None
        self._panel_pending_choice_fingerprint = None

    def _expire_panel_choice_action(self) -> str | None:
        action = self._panel_pending_choice_action
        self._panel_pending_choice_action = None
        self._panel_pending_choice_fingerprint = None
        return action

    def _enter_panel_episode(self, frame: Frame, anchor: MatchResult, kind: str, opened: bool) -> None:
        """进入 ACTIVE 会话：记录 kind/指纹起点；主动打开的面板计 episode 数。"""
        now = time.time()
        self._panel_state = PanelState.ACTIVE
        self._panel_kind = kind
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
        self._clear_pending_skill_cards()
        self._reset_choice_session()
        if opened:
            self._panel_episode_count[kind] = self._panel_episode_count.get(kind, 0) + 1

    def _finish_panel_episode(self) -> None:
        cycle_kind = self._panel_kind
        cycle_owned = self._l1_cycle_owned_panel
        cycle_selected = self._l1_cycle_selected
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
        if (
            cycle_owned
            and cycle_kind == self._l1_cycle_step
            and not cycle_selected
            and cycle_kind in ("skill", "bond", "treasure")
        ):
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
        return self._hero_changed_pixels(baseline, roi) >= 2000

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
                self._panel_state = PanelState.COOLDOWN
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
                    self._panel_state = PanelState.COOLDOWN
                    kind = self._panel_kind or "unknown"
                    self._panel_cooldown_until[kind] = now + self.settings.ui_action_interval_s
                    self._panel_opened_by_us = None
                    self._skill_refresh_attempts = 0
                    return LoopAction.Continue

        if st == PanelState.CLOSED:
            if anchor is None:
                self._panel_anchor_candidate = None
                return None  # 无面板活动：落到无面板链（自动任务/挑战/主动开面板）
            if not self._panel_anchor_confirmed(anchor):
                # P0-3：锚点已见但未达双帧/高分确认 → 零输入等待，禁止盲点进化/
                # 开面板（215302：0.742/0.799 贴阈值单帧不得进入面板处理）。
                print(f"[L1] 面板锚点 {anchor.name} {anchor.score:.3f} 待双帧确认（零输入）")
                return LoopAction.Continue
            kind = self._panel_kind_of(frame, anchor)
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
                self._enter_panel_episode(frame, anchor, kind, opened=True)
                print(f"[L1] 主动面板 {kind} 已可见（{self.settings.panel_visible_timeout_s}s 窗内）")
            elif now >= self._panel_visible_deadline:
                # 2s 未出现：COOLDOWN，零盲点/盲关闭
                print(f"[L1] 主动面板 {self._panel_kind} 可见窗超时，进入 COOLDOWN（零输入）")
                self._panel_state = PanelState.COOLDOWN
                self._panel_cooldown_until[self._panel_kind] = now + self.settings.ui_action_interval_s
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
                if fingerprint == self._panel_fingerprint:
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
                    self._skill_refresh_attempts = 0
                    return LoopAction.Continue
                print(f"[L1] {kind}选择 {hit.name} score={hit.score:.3f} @ {hit.center}")
                clicked = self.act_click(hit, f"{kind}选择")
                if clicked:
                    # 成功执行的选卡/刷新/放弃/关闭动作才计入尝试预算（WAIT/被拒不加）。
                    self._bump_choice_attempts()
                    self._panel_executed_actions += 1
                    self._panel_last_progress_at = now
                    action_kind = self._panel_choice_action_kind(hit.name)
                    self._stage_panel_choice_action(action_kind, fingerprint)
                    # 技能选卡点击成功只暂存；必须等 mutation/面板消失后才记为已学。
                    if action_kind == "select" and kind == "技能" and self._is_skill_card_click(hit.name):
                        self._stage_skill_card(hit.name)
                    self._selection_click_cooldown_until = now + self.settings.ui_action_interval_s
                    self._panel_last_input_at = now
                    self._panel_mutation_baseline = self._panel_roi_region(frame)
                    self._panel_state = PanelState.WAIT_MUTATION
                    self._panel_confirm_window = max(
                        5.0, min(15.0, self.settings.recovery_timeout_s)
                    )
                    if "refresh" in (hit.name or "").lower():
                        self._skill_refresh_attempts += 1
                        self._sync_choice_session_refreshes()
                        if self._choice_fp_before_refresh:
                            self._choice_session = replace(
                                self._choice_session,
                                last_slot_fingerprint=self._choice_fp_before_refresh,
                            )
                        self._panel_opened_by_us = "skill" if kind == "skill" else None
                    else:
                        # Selection success is not known yet; WAIT_MUTATION owns
                        # both cycle success and the fast skill reopen permission.
                        self._panel_opened_by_us = None
                self._selection_unknown_attempts = 0
                self._selection_unknown_since = None
                self._main_line_since = now
                return LoopAction.Continue

            # 无候选：F1 兜底 shadow（每 episode ≤1 次，LIVE 门槛 20 正确/0 误触）
            if not self._panel_f1_used_this_episode:
                self._panel_f1_used_this_episode = True
                self._panel_f1_shadow_record(True, None)
                print("[L1] F1 兜底 shadow：记录候选（不产生输入）")
            self._selection_unknown_since = self._selection_unknown_since or now
            elapsed = now - self._selection_unknown_since
            # 尝试点关闭按钮安全退出（放弃/暂时隐藏）。主动打开的面板按 kind 查
            # 关闭按钮；自然面板（非我们打开）若分类明确（bond/card）且关闭按钮
            # 高置信命中（card_hide/bond_hide_btn ≥ match_threshold），也授权
            # 关闭——215302 面板 bond_hide 0.39 miss 但 card_hide 0.85 命中，
            # 点击"暂时隐藏"是锚点确认的有界动作（WAIT_MUTATION 后置确认），
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
            if elapsed >= 10.0:
                print("[L1] 未知选择面板无法识别，Fail-Closed 停止运行（零输入，不盲点隐藏）")
                self.set_phase(Phase.ERROR, "unknown selection panel timeout")
                self.stop()
                return LoopAction.Break
            print(f"[L1] 当前选择无配置命中（已等 {elapsed:.0f}s），保持零输入等待…")
            return LoopAction.Continue

        if st == PanelState.WAIT_MUTATION:
            if anchor is None:
                # 面板消失是最强消费/关闭证据；此时才确认 semantic action。
                self._panel_confirmed_actions += 1
                self._panel_last_progress_at = now
                self._confirm_panel_choice_action(now)
                self._commit_pending_skill_cards()
                self._finish_panel_episode()
                return LoopAction.Continue
            if self._panel_mutation_confirmed(frame):
                # 内容变化（新候选/选卡消费/关闭过渡）后才确认成功。
                self._panel_confirmed_actions += 1
                self._panel_last_progress_at = now
                self._confirm_panel_choice_action(now)
                self._commit_pending_skill_cards()
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
            if now >= self._panel_cooldown_until.get(self._panel_kind, 0):
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

    def _tick_main_line(self, frame: Frame) -> LoopAction:
        now = time.time()

        if self._hitch_enabled():
            event = classify_hitch_ocr(self._hitch_ocr_text())
            if event:
                return self._hitch_reset_lobby(event, now)

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
                elif self._pending_action.target_id == "danGif" or self._pending_action.kind == "WAIT_DEVOUR_DAN":
                    self._devour_dan_next_at = now + 1.0
                elif self._pending_action.target_id == "equipment_upgrade" or self._pending_action.kind == "EQUIPMENT_UPGRADE":
                    self._equipment_pending_until = now + 1.0
                self._pending_action = None
            else:
                return LoopAction.Continue

        # ---- S0 ④ round hard deadline：进入 MAIN_LINE 即固定，不可续期 ----
        # 技能/面板/神器/挑战/进化等任何动作都不得延期；到期先记录 TIMEOUT、
        # 清 input/evidence token，转 QUIT 由正常退出链处理（退出打开/确认失败才
        # ERROR）。idle watchdog（_main_line_since + game_timeout 分钟）与之分离。
        if self._round_deadline is not None and now >= self._round_deadline:
            print(f"[med] round hard deadline 到期（{self.settings.round_timeout_s}s），记录 TIMEOUT 并转 QUIT")
            self._record_round_outcome(RoundOutcome.TIMEOUT, "round deadline")
            self._record_round_timeout_incident()
            self.invalidate_evidence("round-deadline")
            self.set_phase(Phase.QUIT, "round deadline expired")
            return LoopAction.Continue
        fail_gift = self._find_failure_gift(frame)
        if fail_gift is not None:
            print(f"[med] 拦截到失败结算奖励弹窗 @ {fail_gift.center}，点击关闭")
            self.act_click(fail_gift, "DismissFailureReward")
            return LoopAction.Continue


        # 战后页面优先于一切局内动作。胜利后只允许以下专用链：
        # 继续游戏 → 关闭存档面板（如出现）→ NPC 广场 → 局内退出。
        post_game = self._post_game_state(frame)
        if (
            self.settings.auto_secret_realm
            and self._post_game_pending
            and self._secret_realm_request_pending
            and self._secret_realm_request_since is not None
            and now - self._secret_realm_request_since >= max(3.0, min(float(self.settings.query_timeout), 15.0))
        ):
            print("[med] 大秘境请求超时，Fail-Closed 停止运行")
            self.set_phase(Phase.ERROR, "secret realm request timeout")
            self.stop()
            return LoopAction.Break

        if not post_game and self._round_tail_checks_active():
            if self.find_scene(frame, "archive"):
                print("[med] 识别到未验证战后入口 archive，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "unverified archive entry")
                self.stop()
                return LoopAction.Break
            if self.find_scene(frame, "boss_entry"):
                print("[med] 识别到未验证战后入口 boss_entry，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "unverified boss_entry")
                self.stop()
                return LoopAction.Break
        for dialog in self._aux_dialog_attempts:
            if post_game != dialog:
                self._aux_dialog_attempts[dialog] = 0
        if post_game == "PAUSED":
            self._main_line_since = now
            print("[med] 游戏处于暂停界面，零动作等待恢复")
            return LoopAction.Continue
        if post_game == "POST_VICTORY":
            if self._post_game_pending:
                elapsed = now - self._victory_continue_since if self._victory_continue_since else 0.0
                if elapsed >= min(self.settings.query_timeout, 30):
                    print("[med] 继续游戏后胜利页未消失，Fail-Closed 停止运行")
                    self.set_phase(Phase.ERROR, "victory page did not close")
                    self.stop()
                    return LoopAction.Break
                print("[med] 已点击继续游戏，等待胜利页消失（零动作）")
                return LoopAction.Continue

            if self._victory_continue_attempts >= 3:
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
                self._post_game_pending = True
                self._victory_continue_since = now
                self._main_line_since = now
            return LoopAction.Continue

        if post_game == "ARCHIVE_PANEL":
            if not self._post_game_pending:
                print("[med] 非胜利链路进入存档面板，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "unexpected archive panel")
                self.stop()
                return LoopAction.Break
            if self._post_game_close_attempts >= 3:
                print("[med] 存档面板关闭重试已达上限，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "archive close attempts exhausted")
                self.stop()
                return LoopAction.Break
            close_hit = self._find_archive_panel_close(frame)
            if not close_hit:
                print("[med] 存档面板未找到专用关闭按钮，零动作等待")
                return LoopAction.Continue
            self._post_game_close_attempts += 1
            print(f"[med] 关闭存档面板 @ {close_hit.center} (尝试 {self._post_game_close_attempts}/3)")
            self.act_click(close_hit, "CloseArchivePanel")
            return LoopAction.Continue
        if post_game == "NPC_HUB":
            if not self._post_game_pending:
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
                    print("[med] 大秘境确认后仍停留挑战广场，Fail-Closed 停止运行")
                    self.set_phase(Phase.ERROR, "great rift entry remained on npc hub")
                    self.stop()
                    return LoopAction.Break
                print("[med] 大秘境确认后挑战广场过渡帧，零动作等待局内 HUD")
                return LoopAction.Continue
            if self.settings.auto_secret_realm:
                timeout = max(3.0, min(float(self.settings.query_timeout), 15.0))
                if self._secret_realm_request_since is None:
                    self._secret_realm_request_since = now
                elapsed = now - self._secret_realm_request_since
                if self._secret_realm_request_attempts >= 3 or elapsed >= timeout:
                    print("[med] 大秘境 NPC 未能打开确认框，Fail-Closed 停止运行")
                    self.set_phase(Phase.ERROR, "great rift npc request timeout")
                    self.stop()
                    return LoopAction.Break
                if now < self._secret_realm_next_observe_at:
                    print("[med] 已右键大秘境 NPC，等待确认框（零动作）")
                    return LoopAction.Continue
                rift_npc = self._find_secret_realm_npc(frame)
                if not rift_npc:
                    print("[med] 挑战广场未找到受锚定的大秘境 NPC，零动作等待")
                    return LoopAction.Continue
                self._secret_realm_request_attempts += 1
                print(
                    f"[med] 自动秘境开启，右键大秘境 NPC @ {rift_npc.center} "
                    f"(尝试 {self._secret_realm_request_attempts}/3)"
                )
                self._secret_realm_next_observe_at = now + self.settings.ui_action_interval_s
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
            attempts = self._aux_dialog_attempts[post_game]
            if attempts >= 3:
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
            self.act_click(close_hit, "DismissHeirloomDialog")
            self._main_line_since = now
            return LoopAction.Continue

        if post_game == "GREAT_RIFT_CONFIRM":
            if (
                self.settings.auto_secret_realm
                and self._post_game_pending
                and self._secret_realm_request_pending
            ):
                started = self._secret_realm_request_since or now
                timeout = max(3.0, min(float(self.settings.query_timeout), 15.0))
                if self._secret_realm_confirm_attempts >= 3 or now - started >= timeout:
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
                    self._main_line_since = now
                return LoopAction.Continue

            attempts = self._aux_dialog_attempts[post_game]
            if attempts >= 3:
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
            print(f"[med] 识别到尚未实现的战后页面 {post_game}，Fail-Closed 停止运行（零输入）")
            self.set_phase(Phase.ERROR, f"unverified post-game page {post_game}")
            self.stop()
            return LoopAction.Break

        # 点击“是”后只观察页面变化；确认框消失且重新检测到局内 HUD，才允许
        # 恢复 G/F/V 等局内循环。失败时仍由全局强失败抢占进入原有退出重开链。
        if self._secret_realm_entering_since is not None:
            elapsed = now - self._secret_realm_entering_since
            timeout = max(3.0, min(float(self.settings.query_timeout), 15.0))
            if now < self._secret_realm_confirm_next_observe_at:
                print("[med] 等待大秘境局内 HUD（零动作）")
                return LoopAction.Continue
            if self._is_in_game_hud(frame):
                self._secret_realm_active = True
                self._secret_realm_request_pending = False
                self._secret_realm_request_since = None
                self._secret_realm_request_attempts = 0
                self._secret_realm_next_observe_at = 0.0
                self._secret_realm_entering_since = None
                self._secret_realm_confirm_attempts = 0
                self._post_game_pending = False
                self._post_game_close_attempts = 0
                self._victory_continue_attempts = 0
                self._victory_continue_since = None
                self._round_started_at = now
                self._round_deadline = now + self.settings.round_timeout_s
                self._main_line_since = now
                print("[med] 大秘境局内 HUD 已确认，恢复局内循环；失败后沿原退出重开链处理")
                return LoopAction.Continue
            if elapsed >= timeout:
                print("[med] 大秘境确认后未出现局内 HUD，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "great rift entry verification timeout")
                self.stop()
                return LoopAction.Break
            print("[med] 大秘境载入中，等待局内 HUD（零动作）")
            return LoopAction.Continue

        # ---- 单界面交互仲裁 (InteractionSurface Arbitration) ----
        has_recovery = (self.phase == Phase.RECOVER_FAILURE) or bool(getattr(self, "_recovery_step", None) and self._recovery_step != "DONE")
        has_affix = self._find_equipment_affix_choice(frame) is not None
        anchor = self._selection_anchor(frame)
        has_hero = bool(anchor and self._find_evolution_choice(frame, anchor))
        has_card = (not has_hero) and (bool(anchor) or self._panel_state != PanelState.CLOSED)
        # 商店检测在存在中央选卡/进化/词条弹窗时被严格遮挡/抑制，不作为并发弹窗冲突
        has_merchant = False if (has_card or has_hero or has_affix) else self._black_merchant_present(frame)

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
            if conflict_duration >= 2.5:
                print(f"[med][surface] 互斥弹窗冲突持续超时 ({conflict_duration:.2f}s >= 2.5s)，记录 incident 并转 Phase.ERROR")
                self.set_phase(Phase.ERROR, f"interaction surface conflict timeout ({conflict_duration:.2f}s)")
                self.stop()
                return LoopAction.Break
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
            evolution_choice = self._find_evolution_choice(frame, anchor)
            if evolution_choice is not None:
                self._evolve_feedback_pending = False
                self._evolve_fail_count = 0
                self._evolve_baseline = None
                roi = frame.bgr[145:515, 540:1060].copy()
                if (
                    self._evolution_baseline is not None
                    and self._hero_changed_pixels(self._evolution_baseline, roi) >= 2000
                ):
                    self._evolution_attempts = 0
                    self._evolution_baseline = None
                if now < self._evolution_next_at:
                    return LoopAction.Continue
                if self._evolution_attempts >= 3:
                    self.set_phase(Phase.ERROR, "evolution choice did not mutate")
                    self.stop()
                    return LoopAction.Break
                if self.act_click(evolution_choice, "SelectEvolutionCard"):
                    self._evolution_attempts += 1
                    self._evolution_baseline = roi
                    self._evolution_next_at = now + self.settings.ui_action_interval_s
                    self._panel_state = PanelState.CLOSED
                    self._panel_opened_by_us = None
                    self._selection_unknown_attempts = 0
                    self._selection_unknown_since = None
                    self._main_line_since = now
                    self._evolve_ok_this_cycle = True
                    if self._l1_cycle_step == "evolve":
                        self._advance_l1_cycle("evolve")
                return LoopAction.Continue
        elif surface == InteractionSurface.CENTER_CARD_MODAL:
            res = self._tick_panel_fsm(frame, anchor, now)
            if res is not None:
                self._main_line_since = now
                return res
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
        # Fail-Closed 语义保留：局尾窗口内 archive/boss_entry 命中即 ERROR 零输入。
        # 本检查放在战后 pending 等待之前：继续游戏后出现未分类战后页时先 Fail-Closed，
        # 不得无限零动作等待。
        if not anchor and self._round_tail_checks_active():
            if getattr(self, "scenes", None) and "archive" in self.scenes and self.find_scene(frame, "archive"):
                print("[med] 识别到未验证战后入口 archive，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "unverified archive entry")
                self.stop()
                return LoopAction.Break
            if getattr(self, "scenes", None) and "boss_entry" in self.scenes and self.find_scene(frame, "boss_entry"):
                print("[med] 识别到未验证战后入口 boss_entry，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "unverified boss_entry")
                self.stop()
                return LoopAction.Break

        # 点击继续游戏后、页面确认前：不认识的页面一律零动作等待，绝不落到
        # 自动任务/挑战/选关分支（防止胜利→大厅过渡期误触）。
        if self._post_game_pending:
            elapsed = now - self._victory_continue_since if self._victory_continue_since else 0.0
            if elapsed >= min(self.settings.query_timeout, 30):
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

        # 右侧“自动任务”复选框（左键点击）
        auto_res = self._ensure_auto_task_enabled(frame)
        if auto_res is not None:
            self._main_line_since = now
            return auto_res
        if not self._auto_task_done and not self.settings.dry_run and getattr(self.settings, "auto_task", True) and not getattr(self, "_skip_auto_task_gate", False):
            if self._panel_state == PanelState.CLOSED:
                print("[L1] 尚未确认【自动任务】已开启，阻断四挑战和其他局内动作")
                return LoopAction.Continue

        # 挑战按钮有自己的模板和自动状态检测，避免固定坐标反复切换开关。
        ch_res = self._ensure_challenge_buttons(frame)
        if ch_res is not None:
            self._main_line_since = now
            return ch_res

        # Stage rows never grant click authority inside MAIN_LINE.  A genuine
        # stage page is handed back to the guarded L0 state; in-game HUD anchors
        # suppress glyph false positives from task text / Boss countdowns.
        if self._find_stage_page(frame) and not self._is_in_game_hud(frame):
            self.set_phase(Phase.STAGE_SELECT, "guarded stage page detected from MAIN_LINE")
            return LoopAction.Continue

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

        # 技能/羁绊/宝物优先于会重复出现的进化按钮，避免 G/F/V 饿死。
        opened = self._maybe_open_choice_panel(frame, anchor=anchor)
        if opened is not None:
            self._main_line_since = now
            return opened

        # 显式循环中的神器阶段；无到期槽位时推进到技能。
        if self._l1_cycle_step == "artifact":
            artifact_res = self._maybe_fire_artifacts(frame)
            if artifact_res is not None:
                self._main_line_since = now
                return artifact_res
            self._advance_l1_cycle("artifact")
            return LoopAction.Continue

        # 显式循环中的进化阶段（逻辑顺序在神器之前）。
        if self._l1_cycle_step == "evolve":
            # P0-2（164929/215302）：进化点击后置确认。点击后必须观察到面板/
            # 画面反馈才算成功；无反馈计失败并重试（5s 冷却保留），每轮 ≤3 次后
            # 放弃本轮进化，绝不连续空点。
            if getattr(self, "_evolve_feedback_pending", False):
                if self._evolve_feedback_seen(frame):
                    # 反馈出现（进化面板锚点 / 中央区域像素变化）→ 成功推进
                    self._evolve_feedback_pending = False
                    self._evolve_fail_count = 0
                    self._evolve_baseline = None
                    self._evolve_ok_this_cycle = True
                    self._advance_l1_cycle("evolve")
                    self._main_line_since = now
                    return LoopAction.Continue
                if now - self._evolve_click_at >= self._evolve_feedback_window_s:
                    # 反馈窗超时：无反馈计失败（等冷却后重试）
                    self._evolve_feedback_pending = False
                    self._evolve_baseline = None
                    self._evolve_fail_count += 1
                    print(f"[L1] 点击进化无反馈（第 {self._evolve_fail_count} 次失败），等待冷却后重试")
                    if self._evolve_fail_count >= 3:
                        print("[L1] 进化连续 3 次无反馈，放弃本轮进化（不连续空点）")
                        self._evolve_fail_count = 0
                        self._advance_l1_cycle("evolve")
                        return LoopAction.Continue
                return LoopAction.Continue
            if now < getattr(self, "_evolve_click_cooldown_until", 0.0):
                return LoopAction.Continue
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
            # 模板未命中或输入失败：本轮进化无事可做，推进循环
            self._advance_l1_cycle("evolve")
            return LoopAction.Continue

        if self._l1_cycle_step == "equipment":
            if not self.settings.auto_weapon:
                self._advance_l1_cycle("equipment")
                return LoopAction.Continue
            result = self._maybe_upgrade_equipment(frame)
            self._main_line_since = now
            return result

        if self._l1_cycle_step == "pickup":
            if now >= self._pickup_next_at and self.act_key("z", "Pickup-Z"):
                self._pickup_next_at = now + 10.0
                self._main_line_since = now
            self._advance_l1_cycle("pickup")
            return LoopAction.Continue

        if self._l1_cycle_step == "merchant":
            merchant_res = self._maybe_black_merchant(frame)
            self._advance_l1_cycle("merchant")
            if merchant_res is not None:
                self._main_line_since = now
                return merchant_res
            return LoopAction.Continue

        print("[med] 主线 idle（等待局内选择/挑战 UI）")
        if self._main_line_since is not None:
            idle_minutes = (now - self._main_line_since) / 60.0
            timeout_minutes = max(self.settings.game_timeout, 5)
            if idle_minutes >= timeout_minutes:
                print(f"[med] 主线阶段超过 {timeout_minutes} 分钟未识别到有效 UI，停止运行")
                self.set_phase(Phase.ERROR, "main_line idle timeout")
                self.stop()
                return LoopAction.Break
        return LoopAction.Continue

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
            if self._find_exit_confirm(frame):
                self.set_phase(Phase.NEXT, "exit confirmation already visible")
                return LoopAction.Continue
            if self._exit_button_attempts >= 3 or elapsed >= timeout:
                print("[med] 未能打开专用退出确认框，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "exit button timeout")
                self.stop()
                return LoopAction.Break
            exit_hit = self._find_game_exit(frame)
            if not exit_hit:
                print("[med] 等待局内左上角专用退出按钮（零动作）")
                return LoopAction.Continue
            self._exit_button_attempts += 1
            print(f"[med] 点击局内退出 @ {exit_hit.center} (尝试 {self._exit_button_attempts}/3)")
            if self.act_click(exit_hit, "QuitGame-open-confirm"):
                self.set_phase(Phase.NEXT, "exit button clicked")
            return LoopAction.Continue

        if self.phase == Phase.NEXT:
            if self._exit_confirm_attempts >= 3 or elapsed >= timeout:
                print("[med] 退出确认框未能安全确认，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, "exit confirmation timeout")
                self.stop()
                return LoopAction.Break
            confirm_hit = self._find_exit_confirm(frame)
            if not confirm_hit:
                print("[med] 等待专用退出确认按钮（零动作）")
                return LoopAction.Continue
            self._exit_confirm_attempts += 1
            print(f"[med] 确认退出当前游戏 @ {confirm_hit.center} (尝试 {self._exit_confirm_attempts}/3)")
            if not self.act_click(confirm_hit, "QuitGame-confirm"):
                return LoopAction.Continue
            if self._hitch_enabled():
                self._hitch_after_exit(time.time())
                return LoopAction.Continue
            self._awaiting_room_return = True
            self.set_phase(Phase.PREPARE, "exit confirmed; verify same room")
            self._room_action_deadline = time.time() + min(self.settings.query_timeout, 30)
            self._longzhu_deadline = None
            self._f1_fallback_done = False
            return LoopAction.Continue

        print(f"[med] unhandled phase {self.phase}")
        return LoopAction.Continue

    def run(self, max_steps: int | None = None) -> None:
        self._running = True
        self.stop_signal.reset()
        self.set_phase(Phase.BOOT)
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
                return
            print("[med] elevation OK — real SendInput path enabled")
        self.emergency_listener = EmergencyStopListener(self.stop_signal)
        self.emergency_listener.start()
        try:
            while self._running and not self.stop_signal.is_set():
                # N2.3：固定 cadence —— sleep = max(0, cadence - elapsed)，time.monotonic。
                # loop_sleep_ms 仅作兼容上限（默认 400ms 会盖住 loading 档的 500ms）。
                tick_started = time.monotonic()
                action = self.tick()
                steps += 1
                if action == LoopAction.Break:
                    break
                if max_steps is not None and steps >= max_steps:
                    print(f"[med] max_steps={max_steps}")
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
        print(f"[med] end steps={steps} games={self.game_count}")

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

