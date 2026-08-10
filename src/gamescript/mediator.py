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
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

import cv2
import numpy as np

from gamescript.incidents import IncidentArchiver
from gamescript.input.emergency_stop import EmergencyStopListener
from gamescript.input.keyboard_mouse import InputExecutor
from gamescript.loop_action import LoopAction
from gamescript.scenes import load_scenes, scene_templates
from gamescript.settings import Settings
from gamescript.stop_signal import StopSignal
from gamescript.vision.capture import (
    Frame,
    FrameHealthIssue,
    FrameHealthResult,
    L0_WINDOW_KEYWORDS,
    L1_WINDOW_KEYWORDS,
    activate_window,
    capture,
    capture_target,
    check_frame_health,
    find_window_targets,
)
from gamescript.vision.matcher import (
    MatchResult,
    _load_template,
    find_blue_button,
    find_blue_buttons,
    find_input_boxes,
    match_all,
    match_any,
    match_any_with_margin,
    match_one,
    resolve_template,
)
from gamescript.vision.stage_selector import (
    find_stage_in_range,
    find_stage_labels,
    stage_list_scroll_point,
    verify_stage_selection,
    visible_stage_rows,
)

# 构建标识：写入 JSONL tick trace（B1-1），用于区分版本/里程碑来源。
# 每次发布里程碑时更新；配合 git 提交哈希可精确定位产生该日志的代码。
BUILD_ID = "ocr-hybrid-dev"


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
    QUIT = auto()  # 点击局内专用退出按钮
    NEXT = auto()  # 确认退出并返回原 KK 房间


class ChallengeState(Enum):
    PENDING = auto()
    OFF = auto()
    ON = auto()
    UNKNOWN = auto()


class Mediator:
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
        # startChallenge 显式子状态机（STAGE_STARTING 分支内部状态，枚举不变）：
        # WAIT_TRANSITION → VERIFY_INGAME → DONE，带超时/失败分支/有界重试
        self._challenge_start_state: str | None = None   # WAIT_TRANSITION/VERIFY_INGAME/DONE
        self._challenge_start_source: str = "stage"      # stage / hero
        self._challenge_start_attempts: int = 0
        self._challenge_start_deadline: float | None = None
        self._challenge_start_hud_frames: int = 0        # VERIFY_INGAME 连续锚点帧计数
        self._challenge_start_hero_modal_frames: int = 0 # hero 弹窗消失计数
        self._stage_scroll_attempts = 0
        self._missing_window_since: float | None = None
        self._last_frame: Frame | None = None
        self._prev_frame: Frame | None = None
        self._last_capture_role: str | None = None
        # N2.2：单帧感知证据（FrameEvidence.cache 取代旧 _scene_cache / 每 tick clear）
        self._evidence: FrameEvidence | None = None
        self._tick_evidence: FrameEvidence | None = None
        self._tick_gen: int | None = None
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
        self._interrupt_reason: str | None = None
        # Safety: L0 cycle counter — prevent infinite PLATFORM_MAP ↔ ROOM_WAITING loops
        self._l0_cycle_count = 0
        self._l0_cycle_limit = 5
        # Safety: MAIN_LINE idle deadline — prevent infinite idle on unexpected screens
        self._main_line_since: float | None = None
        self._main_line_started_at: float | None = None
        # L1 reward/challenge actions are one-shot until the next game.
        self._selection_click_cooldown_until = 0.0
        self._challenge_done: set[str] = set()
        self._challenge_attempts: dict[str, int] = {}
        self._challenge_unknown_since: dict[str, float] = {}
        self._challenge_states: dict[str, ChallengeState] = {
            "coin_challenge": ChallengeState.PENDING,
            "wood_challenge": ChallengeState.PENDING,
            "experience_challenge": ChallengeState.PENDING,
            "treasure_challenge": ChallengeState.PENDING,
        }
        self._auto_task_done: bool = False
        self._auto_task_attempts: int = 0
        # P1-B1: victory-continue flow (multi-anchor post-game classification).
        self._victory_continue_attempts: int = 0
        self._victory_continue_since: float | None = None
        # While True, frames that no classifier recognizes must yield ZERO input
        # (no auto-task / challenge / stage actions) until timeout -> ERROR.
        self._post_game_pending: bool = False
        self._post_game_close_attempts: int = 0
        self._exit_button_attempts: int = 0
        self._exit_confirm_attempts: int = 0
        self._exit_since: float | None = None
        self._awaiting_room_return: bool = False
        self._selection_unknown_attempts: int = 0
        self._selection_unknown_since: float | None = None
        self._selection_repeat_key: tuple[str, str, int, int] | None = None
        self._selection_repeat_attempts = 0
        self._skill_refresh_attempts = 0
        self._failure_candidate_frames: int = 0
        self._recovery_step: str | None = None
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
        # 测试/回放零副作用）；桌面/LIVE 接入时传入 %LocalAppData%\GameScript-Local。
        self._incident_dir = incident_dir
        self._archiver: IncidentArchiver | None = IncidentArchiver(root=incident_dir) if incident_dir else None
        self._incident_pending_fp: str | None = None  # 待补齐 frame_after 的 incident 指纹
        self._unknown_since: float | None = None      # context=UNKNOWN 连续计时起点
        self._unknown_recorded_fp: str | None = None  # 本 UNKNOWN episode 已归档的页面指纹
        self._last_health: FrameHealthResult | None = None  # 最近一帧健康结果（Fail-Closed 归档用）

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
        """
        def compute() -> bool:
            if self._selection_anchor(frame):
                return True
            for sc in ("env_anchor", "skill_panel", "card_panel"):
                if self.find_scene(frame, sc):
                    return True
            for sc in ("coin_challenge", "wood_challenge", "experience_challenge", "treasure_challenge"):
                if self.find_scene(frame, sc):
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

    def _capture_best(self, title: str, role: str) -> Frame:
        """Capture all matching windows without focusing, then use scene pixels.

        N2.2：上次健康 hwnd 优先抓取；仅连续 N=2 不健康/失配后才枚举候选。
        候选枚举先用廉价固定锚点筛出最高分，再对最高分做完整 context 分类。
        """
        targets = find_window_targets(title, role=role)
        self._capture_candidates = len(targets)
        if not targets:
            return capture(title, role=role, activate=False)
        if len(targets) == 1:
            return capture_target(targets[0])
        prev = self._last_frame if self._last_capture_role == role else None
        if prev is not None and prev.hwnd is not None:
            prev_target = next((t for t in targets if t.hwnd == prev.hwnd), None)
            if prev_target is not None:
                frame = capture_target(prev_target)
                if frame.bgr is not None and frame.bgr.size > 0 and frame.is_valid and frame.width > 0:
                    self._capture_miss_streak = 0
                    return frame
                self._capture_miss_streak += 1
                if self._capture_miss_streak < 2:
                    # 连续第 1 帧失配：仍返回该 hwnd 帧，下一帧才重选
                    return frame
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
        """
        us = getattr(self, "_ui_scale", 1.0)
        if abs(us - 1.0) < 0.05 or not scales:
            return scales
        out = list(scales)
        for s in (us * 0.94, us, us * 1.06):
            if not any(abs(s - x) < 0.03 for x in out):
                out.append(round(s, 3))
        return tuple(sorted(out))

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
        """宽尺度（仅主尺度 miss 回退用）：覆盖 DPI 缩放窗口（如 2348x1080≈1.47x）。

        N2.1 设计原则 4：宽尺度只保留给 hwnd/尺寸变化、UNKNOWN 恢复和离线校准，
        不作为正常 HUD/面板每 tick 默认（与旧 0.85-1.2 档一致）。
        """
        if abs(self._ui_scale - 1.0) < 0.05:
            return (1.0, 1.06, 1.1, 1.15, 1.2)
        us = round(self._ui_scale, 3)
        return tuple(sorted({us, round(us * 0.94, 3), round(us * 1.06, 3), round(us * 1.1, 3), round(us * 1.15, 3)}))

    def _action_gate_ok(self, reason: str = "") -> bool:
        """动作授权断言：``self._evidence is tick_evidence`` 且 generation 未变。

        任一成功输入后 generation 推进 → 同控制流后续动作被拒（每 tick≤1 输入；
        缓存命中不得延续旧帧动作授权）。未处于 tick 控制流（如 benchmark 直调）
        或未建立证据时不额外拒绝。
        """
        ev = self._evidence
        if ev is None or self._tick_gen is None:
            return True
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

    def find_scene(self, frame: Frame, scene_key: str, threshold: float | None = None) -> MatchResult | None:
        """场景模板找图（evidence 级 memo；热路径只试主/邻尺度）。"""
        th = threshold if threshold is not None else self.settings.match_threshold
        names = self.templates(scene_key)
        if not names:
            return None
        scales = self._hot_scales()
        key = ("scene", scene_key, th)

        def compute():
            hit = self.find(frame, names, threshold=th, scales=scales, mode=f"scene:{scene_key}")
            if hit is not None and len(self._trace_scenes) < 12:
                self._trace_scenes.append({
                    "scene": scene_key,
                    "name": hit.name,
                    "score": round(hit.score, 3),
                    "early_stop": False,
                    "compared_all": True,
                })
            return hit

        return self._memo(key, frame, compute)

    def _focus_last_window(self) -> bool:
        if self.settings.dry_run:
            return True
        if not self._last_frame or not self._last_frame.hwnd:
            print("[med] real input skipped: no target HWND")
            return False
        if not activate_window(self._last_frame.hwnd):
            print(f"[med] real input skipped: cannot focus hwnd={self._last_frame.hwnd}")
            return False
        return True

    def _finish_input(self, res, reason: str) -> bool:
        """输入返回后的统一收尾：输入标记、白名单 reason、证据失效。

        任一输入成功后（真实注入）在同一控制流立即 ``invalidate_evidence``：
        gen+1、丢弃缓存，缓存命中不得延续旧帧动作授权。输入失败不推进状态。
        """
        if res.success:
            self._tick_input_executed = True
            if self._tick_reason is None:
                self._tick_reason = "input_executor_wait"
            if not self.settings.dry_run:
                self.invalidate_evidence("input")
        return res.success

    def act_click(self, hit: MatchResult, reason: str = "") -> bool:
        if not self._action_gate_ok(reason):
            return False
        print(f"[med] click {hit.name} score={hit.score:.3f} @ {hit.center} ({reason})")
        target_hwnd = self._last_frame.hwnd if self._last_frame else None
        t0 = time.perf_counter()
        res = self.executor.click(
            hit.screen_x,
            hit.screen_y,
            target_hwnd=target_hwnd,
            dry_run=self.settings.dry_run,
            delay_ms=self.settings.click_delay_ms,
        )
        action_ms = (time.perf_counter() - t0) * 1000.0
        self._trace_actions.append({"intent": f"click:{hit.name}", "at": [hit.screen_x, hit.screen_y], "reason": reason, "ok": res.success})
        if action_ms >= 800.0 and self._tick_reason is None:
            self._tick_reason = "input_executor_wait"
        return self._finish_input(res, reason)

    def act_right_click(self, hit: MatchResult, reason: str = "") -> bool:
        if not self._action_gate_ok(reason):
            return False
        print(f"[med] right_click {hit.name} score={hit.score:.3f} @ {hit.center} ({reason})")
        target_hwnd = self._last_frame.hwnd if self._last_frame else None
        res = self.executor.right_click(
            hit.screen_x,
            hit.screen_y,
            target_hwnd=target_hwnd,
            dry_run=self.settings.dry_run,
            delay_ms=self.settings.click_delay_ms,
        )
        self._trace_actions.append({"intent": f"right_click:{hit.name}", "at": [hit.screen_x, hit.screen_y], "reason": reason, "ok": res.success})
        return self._finish_input(res, reason)

    def act_key(self, key: str, reason: str = "") -> bool:
        if not self._action_gate_ok(reason):
            return False
        print(f"[med] key {key!r} ({reason})")
        target_hwnd = self._last_frame.hwnd if self._last_frame else None
        res = self.executor.press_key(
            key,
            target_hwnd=target_hwnd,
            dry_run=self.settings.dry_run,
        )
        self._trace_actions.append({"intent": f"key:{key}", "reason": reason, "ok": res.success})
        return self._finish_input(res, reason)

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
        roi = (0.20, 0.45, 0.80, 0.80)
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
            # 主尺度全 miss → 宽尺度回退（DPI 缩放窗口；仅 miss 时发生）
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
        if kind is None:
            # 主尺度无法归类 → 宽尺度回退（DPI 缩放窗口）
            kind = self._classify_choice_panel_at(frame, threshold, self._wide_scales())
        return kind

    def _classify_choice_panel_at(self, frame: Frame, threshold: float, scales: tuple[float, ...]) -> str | None:
        if self.find(frame, ["bond_hide_btn", "bond_refresh_btn"], threshold=0.75, scales=scales):
            return "bond"
        # Current treasure and skill panels share refresh/give-up artwork.
        # The generic hide anchor is near-perfect only on the treasure layout.
        treasure_lock = self.find(frame, ["treasure_lock_btn"], threshold=threshold, scales=scales)
        treasure_hide = self.find(frame, ["hide"], threshold=0.95, scales=scales)
        if treasure_lock and treasure_hide:
            return "treasure"
        if self.find(frame, ["skill_giveup_btn", "skill_refresh_btn"], threshold=threshold, scales=scales):
            return "skill"
        if treasure_lock:
            return "treasure"
        if self.find(frame, ["card_hide"], threshold=threshold, scales=scales):
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

    def _auto_task_state(self, frame: Frame) -> tuple[str, MatchResult | None]:
        """Return ON/OFF/UNKNOWN for the right-side auto-task checkbox.

        Live 1600x900 recording compression lowers the OFF template to about
        0.75 while the wrong ON template stays around 0.59.  Comparing both
        scores inside the narrow task ROI is more stable than one 0.85 cutoff.
        """
        key = ("auto_task", round(self._ui_scale, 3))

        def compute() -> tuple[str, MatchResult | None]:
            roi_frame = self._auto_task_roi_frame(frame)
            if roi_frame is None:
                return "UNKNOWN", None
            tmpl_on = resolve_template(self.images, "auto_task_on")
            tmpl_off = resolve_template(self.images, "auto_task_off")
            if not tmpl_on or not tmpl_off or not tmpl_on.is_file() or not tmpl_off.is_file():
                return "UNKNOWN", None
            scales = self._adapt_scales((0.9, 1.0, 1.1))
            on = match_one(roi_frame, tmpl_on, threshold=0.50, name="auto_task_on", scales=scales)
            off = match_one(roi_frame, tmpl_off, threshold=0.50, name="auto_task_toggle", scales=scales)
            on_score = on.score if on else 0.0
            off_score = off.score if off else 0.0
            if max(on_score, off_score) < 0.72 or abs(on_score - off_score) < 0.06:
                return "UNKNOWN", None
            return ("ON", on) if on_score > off_score else ("OFF", off)

        return self._memo(key, frame, compute)

    def _find_auto_task_toggle(self, frame: Frame) -> MatchResult | None:
        """Return a left-click candidate for the right-side auto task checkbox ONLY if explicitly OFF via auto_task_off template match."""
        if self._selection_anchor(frame):
            return None
        state, hit = self._auto_task_state(frame)
        return hit if state == "OFF" else None

    def _ensure_auto_task_enabled(self, frame: Frame) -> LoopAction | None:
        """Ensure right-side auto task checkbox is clicked ON via left click."""
        if getattr(self, "_auto_task_done", False):
            return None
        if self._is_auto_task_enabled(frame):
            print("[L1] 自动任务开启模式已验证（已勾选）")
            self._auto_task_done = True
            return None
        if not hasattr(self, "_auto_task_attempts"):
            self._auto_task_attempts = 0
        if self._auto_task_attempts >= 3:
            print(f"[L1] 自动任务点击重试已达上限 ({self._auto_task_attempts})，Fail-Closed 停止运行")
            self.set_phase(Phase.ERROR, "auto_task attempt limit reached")
            self.stop()
            return LoopAction.Break

        toggle = self._find_auto_task_toggle(frame)
        if not toggle:
            return None

        self._auto_task_attempts += 1
        print(f"[L1] 自动开启【自动任务】左键 @ {toggle.center} (尝试 {self._auto_task_attempts}/3)")
        if self.act_click(toggle, "EnableAutoTask"):
            return LoopAction.Continue

        if self._auto_task_attempts >= 3:
            print(f"[L1] 自动任务点击失败且重试已达上限 ({self._auto_task_attempts})，Fail-Closed 停止运行")
            self.set_phase(Phase.ERROR, "EnableAutoTask click failed")
            self.stop()
            return LoopAction.Break
        return LoopAction.Continue

    # 卡牌品质色（用户规则）：红 > 橙 > 紫 > 蓝 > 白；绿=面板装饰色排除
    RARITY_BANDS = (
        ("red", 5),
        ("orange", 4),
        ("purple", 3),
        ("blue", 2),
        ("white", 1),
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

    def _rarity_choice(self, frame: Frame, panel_kind: str) -> MatchResult | None:
        """Pick the highest-rarity card in a 3-choice panel by border color."""
        if panel_kind == "treasure":
            xs = (0.348, 0.497, 0.646)
            cy_ratio = 0.300
        else:
            xs = (0.331, 0.450, 0.569)
            cy_ratio = 0.333
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

    def _fallback_choice(self, frame: Frame, panel_kind: str) -> MatchResult:
        """Choose the first real card when bond/treasure has no configured or rarity hit."""
        if panel_kind == "treasure":
            x_ratio, y_ratio = 0.348, 0.300
        else:
            x_ratio, y_ratio = 0.331, 0.333
        x, y = int(frame.width * x_ratio), int(frame.height * y_ratio)
        return MatchResult("fallback_first", 1.0, x, y, 0, 0, frame.left + x, frame.top + y)

    def _find_reward_choice(self, frame: Frame, anchor: MatchResult | None = None) -> tuple[str, MatchResult] | None:
        """Decision layer for an open reward-choice panel.

        Policy (one action max):
        1. classify panel kind; UNKNOWN → None (caller handles: close if we
           opened it, else zero-input)
        2. match ONLY user-preferred templates (skills/cards); a preferred hit
           is chosen directly
        3. bond/treasure: no preferred hit → rarity pick → first card
        4. skill: no preferred hit → refresh up to 3 times → give up
        The full skills/cards library is NOT scanned online; it is only used
        for offline diagnostics/template maintenance.
        """
        if anchor is None:
            anchor = self._selection_anchor(frame)
        if not anchor:
            return None

        kind = self._classify_choice_panel(frame)
        if kind is None:
            # 分类失败：绝不假装 skill（旧行为会把 UNKNOWN 当技能面板扫全库）
            self._record_selection_unknown(frame, anchor, "panel classification failed")
            return None

        # B1-2 扩展：正常选择面板抽样（数据集收集；无 incident_dir 时空转）
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

        if kind in ("bond", "treasure", "card"):
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
                    # 尊重用户配置顺序（settings.cards），不按视觉分数排序
                    by_stem = {Path(c.name).stem: c for c in candidates}
                    for pref in preferred:
                        hit = by_stem.get(Path(pref).stem)
                        if hit is not None:
                            return (kind, hit)
            # 无偏好命中 → 按品质色选最高稀有度
            rarity_hit = self._rarity_choice(frame, kind)
            if rarity_hit is not None:
                return (kind, rarity_hit)
            # 无品质色也不阻塞：羁绊/宝物可以任选一张。
            return (kind, self._fallback_choice(frame, kind))

        # skill panel: preferred-only
        preferred = [v.strip() for v in self.settings.skills if v and v.strip()]
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
                # 尊重用户配置顺序（settings.skills），不按视觉分数排序
                by_stem = {Path(c.name).stem: c for c in candidates}
                for pref in preferred:
                    hit = by_stem.get(Path(pref).stem)
                    if hit is not None:
                        return ("技能", hit)
        # 技能格有上限：绝不选未配置技能。先用完 3 次免费刷新，再放弃。
        if self._skill_refresh_attempts < 3:
            refresh = self.find(
                frame,
                ["skill_refresh_btn"],
                threshold=min(0.70, self.settings.match_threshold),
                scales=self._hot_scales(),
            )
            if refresh is None:
                refresh = self.find(
                    frame,
                    ["skill_refresh_btn"],
                    threshold=min(0.70, self.settings.match_threshold),
                    scales=self._wide_scales(),
                )
            if refresh is not None:
                return ("技能刷新", refresh)
        give_up = self.find(
            frame,
            ["skill_giveup_btn", "giveUp"],
            threshold=min(0.70, self.settings.match_threshold),
            scales=self._hot_scales(),
        )
        if give_up is None:
            give_up = self.find(
                frame,
                ["skill_giveup_btn", "giveUp"],
                threshold=min(0.70, self.settings.match_threshold),
                scales=self._wide_scales(),
            )
        if give_up is not None:
            return ("技能放弃", give_up)
        return None

    def _match_all_preferred(self, frame: Frame, names: list[str], max_results: int) -> list:
        """偏好模板多命中收集：先主尺度；配置顺序内的偏好未集齐时宽尺度回退。

        主尺度（基准窗口）通常一次命中全部偏好卡，回退仅在 DPI 缩放窗口
        （如 2348x1080≈1.47x）等主尺度漏检时发生，保证配置序第一的偏好不被吞。
        """
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

        hits = collect(self._hot_scales())
        if not hits:
            return collect(self._wide_scales())
        hit_stems = {Path(h.name).stem for h in hits}
        preferred_stems = [Path(n).stem for n in names]
        if any(ps not in hit_stems for ps in preferred_stems):
            wide = collect(self._wide_scales())
            if wide:
                return wide
        return hits

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

    def _maybe_open_choice_panel(self, frame: Frame, anchor: MatchResult | None = None) -> LoopAction | None:
        """Proactive skill (G) / bond (F) / treasure (V) panel opening.

        Skill panel is the priority (60s interval): configured skills are the
        core power source. Bond/treasure run at the longer interval. Panels
        opened here are remembered so the close-button fallback may close them
        safely instead of Fail-Closed.
        """
        if anchor is None:
            anchor = self._selection_anchor(frame)
        if anchor:
            return None
        now = time.time()
        # 技能 G：核心，60s
        if now - getattr(self, "_last_skill_panel", 0.0) >= 60:
            if self.act_click(self._hud_button_hit(frame, "skill_button", self.CHOICE_BUTTON_RATIOS["skill"]), "OpenSkillPanel"):
                self._last_skill_panel = now
                self._panel_opened_by_us = "skill"
                self._skill_refresh_attempts = 0
                print("[L1] 主动点击 G 技能按钮（核心，60s 一次）")
            else:
                print("[L1] G 技能按钮点击被拒绝（不推进冷却）")
            return LoopAction.Continue
        interval = max(30, getattr(self.settings, "choice_interval", 120))
        # 羁绊 F / 宝物 V：低频
        if getattr(self.settings, "auto_bond", True):
            if now - getattr(self, "_last_bond_attempt", 0.0) >= interval:
                if self.act_click(self._hud_button_hit(frame, "bond_button", self.CHOICE_BUTTON_RATIOS["bond"]), "OpenBondPanel"):
                    self._last_bond_attempt = now
                    self._panel_opened_by_us = "bond"
                    print("[L1] 主动点击 F 羁绊按钮（低频）")
                else:
                    print("[L1] F 羁绊按钮点击被拒绝（不推进冷却）")
                return LoopAction.Continue
        if getattr(self.settings, "auto_treasure", True):
            if now - getattr(self, "_last_treasure_attempt", 0.0) >= interval:
                if self.act_click(self._hud_button_hit(frame, "treasure_button", self.CHOICE_BUTTON_RATIOS["treasure"]), "OpenTreasurePanel"):
                    self._last_treasure_attempt = now
                    self._panel_opened_by_us = "treasure"
                    print("[L1] 主动点击 V 宝物按钮（低频）")
                else:
                    print("[L1] V 宝物按钮点击被拒绝（不推进冷却）")
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
        """Find the close button (放弃/暂时隐藏) for the currently open panel.

        Used as a safe fallback when a panel we proactively opened cannot be
        matched to any card choice.
        """
        kind = panel_kind or getattr(self, "_panel_opened_by_us", None)
        if kind in ("技能", "技能刷新", "技能放弃"):
            kind = "skill"
        if kind == "skill":
            names = ["skill_giveup_btn", "giveUp"]
        elif kind == "treasure":
            names = ["treasure_hide_btn", "hide"]
        elif kind == "bond":
            names = ["bond_hide_btn", "hide"]
        else:
            names = ["skill_giveup_btn", "bond_hide_btn", "treasure_hide_btn", "card_hide", "hide"]
        return self.find(
            frame,
            names,
            threshold=min(0.70, self.settings.match_threshold),
            scales=self._hot_scales(),
            early_stop=True,
        )

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

            # 选择面板存在时，ARCHIVE_PANEL/NPC_HUB（战后独占页）不可能同时出现：
            # 跳过剩余战后扫描，正常局内面板 tick 不再每 tick 扫全战后库。
            if self._selection_anchor(frame):
                return None

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
    def _resolve_challenge_state(frame: Frame, label_hit: MatchResult | None) -> ChallengeState:
        """Explicitly resolve ChallengeState (ON/OFF/UNKNOWN) for a bottom challenge toggle.

        Rules:
        - ON: Explicit green '自动' text detected above label (green_count >= 30).
        - OFF: Explicit OFF evidence (label_hit score >= 0.70 AND green_count < 10).
        - UNKNOWN: Label missing, score < 0.70, ROI size 0, or ambiguous green text (10 <= green_count < 30).
        """
        if not label_hit or label_hit.score < 0.70:
            return ChallengeState.UNKNOWN

        x1 = max(0, label_hit.x - 5)
        x2 = min(frame.width, label_hit.x + label_hit.w + 5)
        y1 = max(0, label_hit.y - 60)
        y2 = max(y1, label_hit.y - 25)
        roi = frame.bgr[y1:y2, x1:x2]
        if roi.size == 0:
            return ChallengeState.UNKNOWN

        b, g, r = cv2.split(roi)
        green = (g > 120) & (g.astype(int) - r.astype(int) > 30) & (g.astype(int) - b.astype(int) > 20)
        green_count = int(green.sum())

        if green_count >= 30:
            return ChallengeState.ON
        elif green_count < 10:
            return ChallengeState.OFF
        else:
            return ChallengeState.UNKNOWN

    @staticmethod
    def _challenge_is_auto(frame: Frame, label: MatchResult) -> bool:
        """Backward compatibility wrapper returning True if challenge state is ON."""
        return Mediator._resolve_challenge_state(frame, label) == ChallengeState.ON

    def _ensure_challenge_buttons(self, frame: Frame) -> LoopAction | None:
        """Process bottom challenge buttons in strict fixed order: coin -> wood -> experience -> treasure.
        Each tick processes at most ONE challenge.
        Returns:
          - LoopAction.Continue: If right-click attempted (success/failed) OR state is UNKNOWN (ends tick, blocks downstream input).
          - LoopAction.Break: If Phase.ERROR or StopSignal triggered (breaks main loop).
          - None: ONLY when all 4 challenges are confirmed ON/done (allows downstream non-input logic).
        """
        for scene_key, label in (
            ("coin_challenge", "金币"),
            ("wood_challenge", "木材"),
            ("experience_challenge", "经验"),
            ("treasure_challenge", "宝物"),
        ):
            if scene_key in self._challenge_done:
                self._challenge_states[scene_key] = ChallengeState.ON
                self._challenge_unknown_since.pop(scene_key, None)
                continue

            attempts = self._challenge_attempts.get(scene_key, 0)
            if attempts >= 3:
                print(f"[L1] {label}挑战重试次数已达上限 ({attempts}) 且未确认开启，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, f"{scene_key} attempt limit reached")
                self.stop()
                return LoopAction.Break

            found = self._find_challenge_button(frame, scene_key)
            label_hit = found[0] if found else None

            if label_hit is None:
                # 按钮缺失（开局 HUD 未刷出/未解锁）：不占 Fail-Closed 计时，
                # 不阻断下游（选关/进化/神器），仅记录。
                self._challenge_unknown_since.pop(scene_key, None)
                print(f"[L1] {label}挑战按钮未出现（MISSING），跳过本 tick 继续")
                continue

            state = self._resolve_challenge_state(frame, label_hit)

            if state == ChallengeState.ON:
                print(f"[L1] {label}挑战已是自动模式")
                self._challenge_states[scene_key] = ChallengeState.ON
                self._challenge_done.add(scene_key)
                self._challenge_unknown_since.pop(scene_key, None)
                continue

            elif state == ChallengeState.UNKNOWN:
                now = time.time()
                unknown_since = self._challenge_unknown_since.setdefault(scene_key, now)
                unknown_timeout = max(3, min(self.settings.query_timeout, 30))
                unknown_elapsed = now - unknown_since
                self._challenge_states[scene_key] = ChallengeState.UNKNOWN
                if unknown_elapsed >= unknown_timeout:
                    # 有按钮但绿字长期模糊：降级为跳过该挑战，不再整机停机
                    print(f"[L1] {label}挑战状态连续 UNKNOWN {unknown_elapsed:.1f}s，跳过该挑战继续")
                    self._challenge_done.add(scene_key)
                    self._challenge_unknown_since.pop(scene_key, None)
                    continue
                print(
                    f"[L1] {label}挑战状态为 UNKNOWN（模糊/低置信），"
                    f"零动作等待 {unknown_elapsed:.1f}/{unknown_timeout}s"
                )
                # End this tick immediately, preventing downstream stage select or other inputs
                return LoopAction.Continue

            elif state == ChallengeState.OFF:
                self._challenge_unknown_since.pop(scene_key, None)
                click_hit = found[1]
                self._challenge_attempts[scene_key] = attempts + 1
                current_attempts = self._challenge_attempts[scene_key]
                print(f"[L1] 自动开启【{label}挑战】右键 @ {click_hit.center} (尝试 {current_attempts}/3)")
                act_res = self.act_right_click(click_hit, f"{label}Challenge-right_click")
                # Right-click sent -> transition state to PENDING (waiting for confirmation in subsequent frames)
                self._challenge_states[scene_key] = ChallengeState.PENDING

                if self.phase == Phase.ERROR or self.stop_signal.is_set():
                    return LoopAction.Break

                if not act_res and current_attempts >= 3:
                    print(f"[L1] {label}挑战右键发送失败且重试已达上限 ({current_attempts})，Fail-Closed 停止运行")
                    self.set_phase(Phase.ERROR, f"{scene_key} right_click failed limit reached")
                    self.stop()
                    return LoopAction.Break

                # Right-click attempted (succeeded or failed with attempts < 3) -> end this tick!
                return LoopAction.Continue

        return None

    @staticmethod
    def _hero_reference_frame(frame: Frame) -> bool:
        """The recorded hero controls are only proven on a 1600x900 client frame."""
        return frame.width == 1600 and frame.height == 900

    @staticmethod
    def _hero_roi(frame: Frame, box: tuple[int, int, int, int]) -> np.ndarray | None:
        if not Mediator._hero_reference_frame(frame):
            return None
        x1, y1, x2, y2 = box
        roi = frame.bgr[y1:y2, x1:x2]
        if roi.shape[:2] != (y2 - y1, x2 - x1):
            return None
        return cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    @staticmethod
    def _hero_changed_pixels(before: np.ndarray, after: np.ndarray) -> int:
        if before.shape != after.shape:
            return 0
        difference = cv2.absdiff(before, after)
        _, changed = cv2.threshold(difference, 15, 255, cv2.THRESH_BINARY)
        return int(cv2.countNonZero(changed))

    @staticmethod
    def _hero_point(frame: Frame, name: str, x: int, y: int) -> MatchResult:
        return MatchResult(
            name=name,
            score=1.0,
            x=x,
            y=y,
            w=0,
            h=0,
            screen_x=frame.left + x,
            screen_y=frame.top + y,
        )

    def _find_hero_entry(self, frame: Frame) -> MatchResult | None:
        if not self._hero_reference_frame(frame):
            return None
        hit = self.find(frame, ["lobby/stage_hero_mode_btn"], threshold=0.90)
        if not hit or not (1170 <= hit.x <= 1270 and 790 <= hit.y <= 840):
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

    def _hero_initial_zero_confirmed(self, frame: Frame) -> bool:
        card = self.find(frame, ["lobby/hero_kenrito_unselected"], threshold=0.90)
        if not card or not (650 <= card.x <= 675 and 110 <= card.y <= 130):
            return False
        roi = self._hero_roi(frame, (724, 314, 752, 342))
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
        if rep_type != 3 or not 1 <= rep_level <= 5:
            return self._hero_fail("当前仅有肯瑞托 1–5 级的完整实机证据")
        if not self._hero_reference_frame(frame):
            return self._hero_fail(
                f"英雄模式要求 1600x900 游戏客户区，当前为 {frame.width}x{frame.height}"
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

    def _tick_hero_setup(self, frame: Frame) -> LoopAction:
        now = time.time()
        if not self._hero_reference_frame(frame):
            return self._hero_fail(
                f"英雄模式过程中客户区尺寸改变为 {frame.width}x{frame.height}"
            )
        if self._hero_step_deadline is not None and now >= self._hero_step_deadline:
            return self._hero_fail(f"英雄模式步骤 {self._hero_state} 超时")

        buttons = self._hero_modal_buttons(frame)
        level_roi = self._hero_roi(frame, (724, 314, 752, 342))
        card_roi = self._hero_roi(frame, (662, 118, 815, 286))
        target_level = int(self.settings.reputation_level)

        if self._hero_state == "WAIT_MODAL":
            if not buttons or level_roi is None or card_roi is None:
                print("[英雄模式] 等待开启/取消双按钮同时出现（零动作）")
                return LoopAction.Continue
            if not self._hero_initial_zero_confirmed(frame):
                print("[英雄模式] 弹窗已出现，但肯瑞托未选中卡和初始 0 级未同时确认（零动作）")
                return LoopAction.Continue
            self._hero_level_baseline = level_roi.copy()
            self._hero_card_baseline = card_roi.copy()
            plus = self._hero_point(frame, "hero_kenrito_plus", 772, 327)
            if not self.act_click(plus, "HeroKenritoPlus-1"):
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
                    return self._hero_fail("无法确认肯瑞托选中态")
                selected_delta = self._hero_changed_pixels(self._hero_card_baseline, card_roi)
                if selected_delta < 10000:
                    return self._hero_fail(
                        f"第一次加级后肯瑞托卡片未切换为选中态（{selected_delta}/10000 像素）"
                    )

            print(f"[英雄模式] 已确认肯瑞托难度 {self._hero_verified_level}/{target_level}")
            if self._hero_verified_level < target_level:
                self._hero_level_baseline = level_roi.copy()
                plus = self._hero_point(frame, "hero_kenrito_plus", 772, 327)
                next_level = self._hero_verified_level + 1
                if not self.act_click(plus, f"HeroKenritoPlus-{next_level}"):
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
        if phase in (Phase.LOBBY_ROOM, Phase.PLATFORM_MAP) and self.phase not in (Phase.LOBBY_ROOM, Phase.PLATFORM_MAP):
            self._stage_selected = False
            self._stage_target_name = None
            self._stage_target_position = None
            self._room_dialog_filled = False
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
            # 跨局重置：次局进入选关页必须重新选关（上一局残留会跳过选关/点错关）
            self._stage_selected = False
            self._stage_target_name = None
            self._stage_target_position = None
            self._stage_candidate_name = None
            self._stage_candidate_position = None
            self._stage_candidate_frames = 0
            self._stage_select_attempts = 0
            self._stage_scroll_cooldown_until = 0.0
            self._room_action_deadline = time.time() + self.settings.query_timeout
            self._hero_state = "IDLE"
            self._hero_verified_level = 0
            self._hero_level_baseline = None
            self._hero_level_candidate = None
            self._hero_card_baseline = None
            self._hero_step_deadline = None
            self._hero_modal_missing_frames = 0
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
            self._challenge_done.clear()
            self._challenge_attempts.clear()
            self._challenge_unknown_since.clear()
            self._challenge_states = {
                "coin_challenge": ChallengeState.PENDING,
                "wood_challenge": ChallengeState.PENDING,
                "experience_challenge": ChallengeState.PENDING,
                "treasure_challenge": ChallengeState.PENDING,
            }
            self._auto_task_done = False
            self._auto_task_attempts = 0
            self._victory_continue_attempts = 0
            self._victory_continue_since = None
            self._post_game_pending = False
            self._post_game_close_attempts = 0
            self._aux_dialog_attempts = {"HEIRLOOM_DIALOG": 0, "GREAT_RIFT_CONFIRM": 0}
            # A verified game start owns a fresh retry/recovery episode.  A
            # timeout retry keeps its budget until this transition succeeds.
            self._challenge_start_attempts = 0
            self._failure_candidate_frames = 0
            self._recovery_step = None
            # 跨局 L1 瞬态重置：主动面板标记/神器 CD/主动面板时间戳/进化冷却
            self._panel_opened_by_us = None
            self._last_skill_panel = 0.0
            self._last_bond_attempt = 0.0
            self._last_treasure_attempt = 0.0
            self._artifact_next_q = 0.0
            self._artifact_next_w = 0.0
            self._artifact_next_e = 0.0
            self._evolve_click_cooldown_until = 0.0
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

    # ---------- B1-2 incident 归档辅助（无 incident_dir 时全部空转）----------

    def _record_fail_closed_incident(self, note: str) -> None:
        """B1-2：进入 Phase.ERROR（LIVE Fail-Closed / dry-run OBSERVE）前归档当前帧证据。

        事件来源：所有 Fail-Closed 停机分支统一经 set_phase(Phase.ERROR, ...)
        汇合；在此留档可覆盖未知页超时、重试耗尽、页面异变、不健康帧超时等
        全部场景，无需逐个分支埋点。调用发生在 self.phase 赋值之前，
        metadata.phase 因此是发生错误的原阶段而非 ERROR。
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
            metadata={
                "kind": "fail_closed",
                "phase": self.phase.name,
                "hwnd": frame.hwnd,
                "window_title": frame.window_title,
                "size": [frame.width, frame.height],
                "score": None,
                "candidate_actions": list(self._trace_actions),
                "final_action": "stop",
                "reason": note or "unspecified",
            },
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
            metadata={
                "kind": "selection_unknown",
                "phase": self.phase.name,
                "hwnd": frame.hwnd,
                "window_title": frame.window_title,
                "size": [frame.width, frame.height],
                "score": anchor.score if anchor is not None else None,
                "candidate_actions": list(self._trace_actions),
                "final_action": "wait",
                "reason": reason,
                "rois": self._panel_roi(frame),
            },
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
            metadata={
                "kind": "repeat_click_no_change",
                "phase": self.phase.name,
                "hwnd": frame.hwnd,
                "window_title": frame.window_title,
                "size": [frame.width, frame.height],
                "score": hit.score,
                "candidate_actions": [
                    {
                        "intent": f"click:{hit.name}",
                        "at": [hit.screen_x, hit.screen_y],
                        "reason": f"{kind}选择",
                        "repeat_attempts": attempts,
                    }
                ],
                "final_action": "close_panel",
                "reason": f"{kind}选择 {hit.name} 连续 {attempts} 次点击无页面变化",
                "rois": self._panel_roi(frame),
            },
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

    def _find_room_start(self, frame: Frame) -> MatchResult | None:
        return self.find_scene(frame, "room_start")

    def _find_stage_start(self, frame: Frame) -> MatchResult | None:
        if not self._find_stage_page(frame):
            return None
        return self.find_scene(frame, "stage_start")

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
            hit = self.find(frame, names, scales=self._hot_scales())
            # stage.png is the large map card; toHero/HeroChallenge are hero icons.
            # They are not sufficient to prove that the numbered stage list is open.
            return bool(
                hit
                and hit.name not in ("stage", "toHero", "HeroChallenge")
                and hit.x >= int(frame.width * 0.55)
            )

        return bool(self._memo(key, frame, compute))


    def _find_map_create_room(self, frame: Frame) -> MatchResult | None:
        hit = self.find_scene(frame, "map_create_room")
        if hit:
            return hit
        # The map page has multiple blue actions.  Only the configured side
        # of the bottom action strip is eligible; quick-join is never global.
        hit = find_blue_button(
            frame,
            (0.45, 0.88, 0.99, 0.99),
            side=self.settings.room_create_side,
        )
        if hit:
            return hit
        # Older layouts place the action farther left.  Keep this as a
        # second, still bottom-strip-bound probe rather than a full-screen
        # blue fallback.
        return find_blue_button(
            frame,
            (0.12, 0.88, 0.64, 0.99),
            side=self.settings.room_create_side,
        )

    def _find_create_confirm(self, frame: Frame) -> MatchResult | None:
        hit = self.find_scene(frame, "create_room_confirm")
        if hit:
            return hit
        # KK opens the create form as a small ~584x488 child window.  Do not
        # run the relatively expensive edge/contour fallback on the full
        # platform page every tick.
        if frame.width > 800 or frame.height > 700:
            return None
        # The real KK dialog is a separate ~584x488 window; its two inputs
        # are in the upper half and the Create/Cancel buttons are at the
        # bottom.  The old center ROI never saw this button.
        candidates = find_blue_buttons(frame, roi=(0.25, 0.72, 0.90, 0.99))
        for candidate in reversed(candidates):
            if len(find_input_boxes(frame, anchor=candidate)) >= 2:
                return candidate
        return None

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
            if not self.settings.dry_run:
                # 填写是同一逻辑动作序列（目标来自本帧证据）；序列结束后统一失效，
                # 防止下一 tick 用填写前的旧证据授权动作。
                self.invalidate_evidence("input")
        print("[L0] 建房弹窗已填写房间名/密码")
        return True

    def _action_timed_out(self) -> bool:
        return self._room_action_deadline is not None and time.time() >= self._room_action_deadline

    def _challenge_start_timeout(self, stage_page: bool) -> LoopAction:
        """startChallenge 超时与失败分支：Fail-Closed，不猜测点击。

        有界重试：source=stage 且选关页仍在时回选关页重选（attempts 预算 +1，
        达到 2 次仍无局内锚点 → ERROR 停机）；其余情况一律 ERROR 停机。
        """
        if self._challenge_start_source == "hero":
            # 英雄链严格证据：不做未验证回退
            print("[L0] 英雄挑战开始超时（无局内锚点），停止运行")
            self.set_phase(Phase.ERROR, "hero challenge start timeout")
            self.stop()
            return LoopAction.Break
        if stage_page:
            self._challenge_start_attempts += 1
            if self._challenge_start_attempts >= 2:
                print("[L0] 选关开始重试耗尽（2 次均未出现局内 UI），停止运行")
                self.set_phase(Phase.ERROR, "challenge start retries exhausted")
                self.stop()
                return LoopAction.Break
            print(f"[L0] 选关后超时未进局（attempts={self._challenge_start_attempts}/2），回到选关页重选")
            self._stage_selected = False
            self._stage_target_name = None
            self.set_phase(Phase.STAGE_SELECT, "challenge start verify timeout")
            return LoopAction.Continue
        # 选关页/英雄入口都消失：页面异变 → 不识别=不动作，Fail-Closed
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

        if self._awaiting_room_return:
            if room_start:
                self._awaiting_room_return = False
                self.game_count += 1
                print(f"[med] 已返回原 KK 房间 count={self.game_count} → 准备下一局")
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
                self.set_phase(Phase.STAGE_SELECT, "stage page detected")
                return LoopAction.Continue
            if room_start:
                self.set_phase(Phase.ROOM_WAITING, "room already exists")
                return LoopAction.Continue
            confirm = self._find_create_confirm(frame)
            if confirm:
                self.set_phase(Phase.CREATE_ROOM, "create dialog detected")
                return LoopAction.Continue
            create = self._find_map_create_room(frame)
            if create:
                print(f"[L0] 检测到创建房间按钮 {create.name} @ {create.center}")
                if not self.act_click(create, "CreateRoom-open"):
                    return LoopAction.Continue
                self.set_phase(Phase.CREATE_ROOM, "clicked map create room")
                return LoopAction.Continue
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
                self._room_action_attempts = 1
                self._room_action_deadline = time.time() + min(self.settings.query_timeout, 15)
                self.set_phase(Phase.ROOM_STARTING, "room start clicked")
                return LoopAction.Continue
            if self._action_timed_out():
                if self._auto_room_enabled():
                    if self._l0_cycle_count >= self._l0_cycle_limit:
                        print(f"[L0] L0 循环次数达到上限 ({self._l0_cycle_limit})，停止运行")
                        self.set_phase(Phase.ERROR, "L0 cycle limit reached")
                        self.stop()
                        return LoopAction.Break
                    print("[L0] 房间等待超时；返回地图页重试建房")
                    self.set_phase(Phase.PLATFORM_MAP, "room wait timeout")
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
            if room_start and self._action_timed_out():
                if self._room_action_attempts < 2:
                    print("[L0] 房间页面未变化，重试点击开始")
                    if not self.act_click(room_start, "RoomStart-retry"):
                        return LoopAction.Continue
                    self._room_action_attempts += 1
                    self._room_action_deadline = time.time() + min(self.settings.query_timeout, 15)
                elif self._l0_cycle_count >= self._l0_cycle_limit:
                    print(f"[L0] L0 循环次数达到上限 ({self._l0_cycle_limit})，停止运行")
                    self.set_phase(Phase.ERROR, "L0 cycle limit reached")
                    self.stop()
                    return LoopAction.Break
                else:
                    print("[L0] 房间开始重试耗尽，回到房间等待，不假报进入游戏")
                    self.set_phase(Phase.ROOM_WAITING, "room start retries exhausted")
            elif self._action_timed_out():
                # 游戏窗口已出现（如 960x540 加载中）：不应回退到已消失的平台房间页，
                # 继续等待选关/局内 UI；只有窗口仍不存在时才回退。
                if frame.hwnd is not None and frame.bgr is not None and frame.bgr.size > 0:
                    print("[L0] 房间开始后游戏窗口已出现，等待选关/局内 UI（不回退）")
                    self._room_action_deadline = time.time() + min(self.settings.query_timeout, 15)
                else:
                    print("[L0] 房间开始后未出现选关/局内 UI")
                    self.set_phase(Phase.ROOM_WAITING, "room start verify timeout")
            else:
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
                    if self._stage_scroll_attempts < 8:
                        x, y = stage_list_scroll_point(frame)
                        target_hwnd = self._last_frame.hwnd if self._last_frame else None
                        # 向下滚动：正值=上滚（更早关卡），负值=下滚（更高关卡）
                        res_scroll = self.executor.scroll(x, y, -1, target_hwnd=target_hwnd, dry_run=self.settings.dry_run)
                        if res_scroll.success:
                            self._stage_scroll_attempts += 1
                            self._stage_scroll_cooldown_until = now + 0.8
                            self._tick_input_executed = True
                            if not self.settings.dry_run:
                                self.invalidate_evidence("input")  # 滚轮成功 → 本帧证据失效
                            self._stage_candidate_name = None
                            self._stage_candidate_position = None
                            self._stage_candidate_frames = 0
                            print(f"[L0] 目标关卡不在当前列表，向下滚动寻找 ({self._stage_scroll_attempts}/8)")
                        else:
                            print(f"[L0] 关卡列表滚动取消/失败: {res_scroll.message}")
                    else:
                        print("[L0] 滚动 8 次仍未找到目标关卡，拒绝点击任意可见关卡")
                    if self._action_timed_out():
                        print("[L0] 选关页超时仍未找到配置目标，停止而不是点击任意关卡")
                        self.set_phase(Phase.ERROR, "configured stage not found")
                        self.stop()
                        return LoopAction.Break
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
                self._room_action_deadline = now + max(10, min(self.settings.query_timeout, 30))
                return LoopAction.Continue
            if now < self._stage_click_cooldown_until:
                print("[L0] 等待关卡选中状态稳定…")
                return LoopAction.Continue
            target_spec = self.settings.stage_targets[0] if self.settings.stage_targets else self.settings.stage1
            if not verify_stage_selection(frame, target=target_spec, images_dir=self.images):
                # The live stage list does not render a reliable persistent
                # row highlight.  Confirm the exact same target label is
                # still visible and require the dedicated start button before
                # advancing.  This avoids the old endless re-click loop
                # without allowing an arbitrary visible stage.
                current_target = self._find_stage_target(frame)
                same_target = bool(current_target and current_target.name == self._stage_target_name)
                same_position = bool(
                    current_target
                    and self._stage_target_position is not None
                    and abs(current_target.x - self._stage_target_position[0]) <= 6
                    and abs(current_target.y - self._stage_target_position[1]) <= 6
                )
                ready = self._find_hero_entry(frame) if self.settings.auto_reputation else self._find_stage_start(frame)
                consistent = bool(current_target and self._stage_target_has_consistent_neighbor(frame, current_target))
                if not same_target or not same_position or not consistent or not ready:
                    print("[L0] 关卡点击后名称/坐标/相邻关卡未保持稳定，拒绝开始游戏")
                    if self._stage_select_attempts >= 3:
                        print("[L0] 目标关卡稳定确认连续失败 3 次，停止而不进入错误关卡")
                        self.set_phase(Phase.ERROR, "configured stage selection unstable")
                        self.stop()
                        return LoopAction.Break
                    self._stage_selected = False
                    self._stage_target_name = None
                    self._stage_target_position = None
                    self._stage_candidate_name = None
                    self._stage_candidate_position = None
                    self._stage_candidate_frames = 0
                    return LoopAction.Continue
                print("[L0] 目标行无持久高亮；已用点击前后同一坐标 + 连续相邻关卡 + 专用开始按钮完成复合确认")
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
            "scenes": self._trace_scenes,
            # N2：无法解释 tick>1s 白名单 reason + evidence generation
            "reason": self._tick_reason,
            "evidence_gen": self._evidence.gen if self._evidence is not None else None,
            # B1-1 证据与遥测扩展
            "build_id": BUILD_ID,
            "settings_summary": self._trace_settings_summary(),
            "frame_fingerprint": self._trace_frame_fingerprint(frame),
            "panel": self._trace_panel_candidates(),
            "ocr_suggestion": None,  # B3 shadow 阶段填充；当前无运行时 OCR
            "decision": self._trace_decision(),
            "post_confirm": self._trace_post_confirm(),
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
        """
        if frame is None or frame.bgr is None:
            return None
        cached = getattr(self, "_trace_fingerprint_cache", None)
        if cached is not None and cached[0] is id(frame):
            return cached[1]
        try:
            digest = hashlib.md5(frame.bgr.tobytes()).hexdigest()
        except Exception:
            return None
        fingerprint = f"{frame.width}x{frame.height}:{digest}"
        self._trace_fingerprint_cache = (id(frame), fingerprint)
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
        """单步：一帧截屏 → 按阶段决策 → 执行。"""
        self._trace_actions = []
        self._trace_scenes = []
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
                    # 房间点开始后的黑屏/捕获失败：用正常重试 deadline 兜底，避免永久挂起
                    if self._action_timed_out():
                        print("[med] ROOM_STARTING 不健康帧超过动作期限，回退房间等待")
                        self.set_phase(Phase.ROOM_WAITING, "room start unhealthy timeout")
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
                elif self.phase in (Phase.CREATE_ROOM, Phase.PLATFORM_MAP):
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
        # 任一成功输入会推进 evidence.gen；act_* 前置断言 gen 未变，stale → 零输入。
        tick_ev = self._evidence
        self._tick_evidence = tick_ev
        self._tick_gen = tick_ev.gen if tick_ev is not None else None

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

        # 全局：断线/失败优先。单帧相似只算候选；连续两帧才取得
        # QUIT 动作权限。恢复 episode 一旦开始，后续步骤不再依赖 fail
        # 模板持续可见（点击后页面本来就应变化）。
        failure_hit = self.find_scene(frame, "disconnect") or self.find_scene(frame, "fail")
        if self._recovery_step and self._recovery_step != "DONE":
            recovery = self._recovery_step
            if recovery == "FAIL_VISIBLE":
                hit = self.find_scene(frame, "fail")
                if hit:
                    self.click_scene(frame, "fail", "recover")
                self._recovery_step = "WAIT_OK"
                return LoopAction.Continue
            if recovery == "WAIT_OK":
                hit = self.find_scene(frame, "ok")
                if hit:
                    self.click_scene(frame, "ok", "ok")
                self._recovery_step = "WAIT_CLOSE"
                return LoopAction.Continue
            if recovery == "WAIT_CLOSE":
                hit = self.find_scene(frame, "close")
                if hit:
                    self.click_scene(frame, "close", "close")
                self._recovery_step = "DONE"
                return LoopAction.Continue

        if failure_hit:
            # 选择面板的"放弃"按钮与失败弹窗 giveUp 模板同源（实机 2026-08-09
            # 证据：局内 bond/card 选择面板弹出时 giveUp 0.945 误命中 → 误判失败）。
            # 真实失败弹窗会遮挡面板，两者互斥；面板存在时跳过 fail 检测。
            if self._selection_anchor(frame):
                self._failure_candidate_frames = 0
                print("[med] 选择面板存在，忽略 giveUp/fail 误检（面板放弃按钮非失败弹窗）")
            elif self._recovery_step == "DONE":
                # The old failure pixels may remain while QUIT opens the exit
                # dialog; do not let a completed episode swallow the tail.
                pass
            else:
                self._failure_candidate_frames += 1
                if self._failure_candidate_frames < 2:
                    print("[med] fail/disconnect 候选第 1 帧，等待连续证据（零动作）")
                    return LoopAction.Continue
                if self.phase != Phase.QUIT:
                    self.set_phase(Phase.QUIT, "fail/disconnect")
                self._recovery_step = "FAIL_VISIBLE"
                return LoopAction.Continue
        else:
            self._failure_candidate_frames = 0
            if self._recovery_step == "DONE":
                self._recovery_step = None

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

        if self.phase in {
            Phase.EARLY_CHALLENGE,
            Phase.ANCHOR_BOSS,
            Phase.LONGZHU,
            Phase.QUIT,
            Phase.NEXT,
        }:
            return self._tick_l1_tail(frame)

        print(f"[med] unhandled phase {self.phase}")
        return LoopAction.Continue

    def _tick_main_line(self, frame: Frame) -> LoopAction:
        now = time.time()

        # 战后页面优先于一切局内动作。胜利后只允许以下专用链：
        # 继续游戏 → 关闭存档面板（如出现）→ NPC 广场 → 局内退出。
        post_game = self._post_game_state(frame)
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
            self._post_game_pending = False
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

        # 中央选择面板比 archive/boss/longzhu 泛模板更具体；龙珠宝物卡
        # 本身可能命中 longzhu，不能因此抢占选卡并误停。
        selection_anchor = self._selection_anchor(frame)

        # 提前挑战 / Boss / 龙珠入口：仅在不存在选择面板时 Fail-Closed。
        if not selection_anchor and self.find_scene(frame, "archive"):
            print("[med] 识别到未验证战后入口 archive，Fail-Closed 停止运行")
            self.set_phase(Phase.ERROR, "unverified archive entry")
            self.stop()
            return LoopAction.Break
        if not selection_anchor and self.find_scene(frame, "boss_entry"):
            print("[med] 识别到未验证战后入口 boss_entry，Fail-Closed 停止运行")
            self.set_phase(Phase.ERROR, "unverified boss_entry")
            self.stop()
            return LoopAction.Break
        if not selection_anchor and self.find_scene(frame, "longzhu"):
            print("[med] 识别到未验证战后入口 longzhu，Fail-Closed 停止运行")
            self.set_phase(Phase.ERROR, "unverified longzhu entry")
            self.stop()
            return LoopAction.Break

        # 选择面板优先；面板存在时禁止把刷新计数或快捷键当成按钮。
        if selection_anchor:
            if now < self._selection_click_cooldown_until:
                print("[L1] 选择面板等待点击结果…")
                return LoopAction.Continue
            choice = self._find_reward_choice(frame, anchor=selection_anchor)
            if choice:
                kind, hit = choice
                repeat_key = (kind, hit.name, hit.screen_x // 8, hit.screen_y // 8)
                if repeat_key == self._selection_repeat_key:
                    self._selection_repeat_attempts += 1
                else:
                    self._selection_repeat_key = repeat_key
                    self._selection_repeat_attempts = 1
                if self._selection_repeat_attempts == 3:
                    # B1-2：同一选择连续 2 次点击无页面变化 → 归档证据
                    # （attempts==3 = 第 1、2 次点击后页面均未变化）
                    self._record_repeat_click(frame, choice, self._selection_repeat_attempts)
                if self._selection_repeat_attempts > 3:
                    close_hit = self._close_current_panel(frame, kind)
                    if close_hit is not None:
                        print(f"[L1] 同一选择连续 3 次无画面变化，关闭面板避免活锁")
                        if self.act_click(close_hit, "CloseRepeatedChoicePanel"):
                            self._selection_click_cooldown_until = now + 1.5
                        self._panel_opened_by_us = None
                        self._selection_repeat_key = None
                        self._selection_repeat_attempts = 0
                        self._skill_refresh_attempts = 0
                        return LoopAction.Continue
                print(f"[L1] {kind}选择 {hit.name} score={hit.score:.3f} @ {hit.center}")
                clicked = self.act_click(hit, f"{kind}选择")
                if clicked:
                    self._selection_click_cooldown_until = now + 1.5
                    if hit.name == "skill_refresh_btn":
                        self._skill_refresh_attempts += 1
                        self._panel_opened_by_us = "skill"
                    else:
                        if kind == "技能":
                            # 配置技能成功后立即再开 G，直到没有可学点数。
                            self._last_skill_panel = 0.0
                        self._panel_opened_by_us = None
                self._selection_unknown_attempts = 0
                self._selection_unknown_since = None
                self._main_line_since = now
                return LoopAction.Continue

            self._selection_unknown_since = self._selection_unknown_since or now
            elapsed = now - self._selection_unknown_since
            # 主动打开的面板：尝试点关闭按钮安全退出（放弃/暂时隐藏）
            if getattr(self, "_panel_opened_by_us", None):
                close_hit = self._close_current_panel(frame)
                if close_hit is not None:
                    print(f"[L1] 主动面板无法匹配卡牌，点击关闭 {close_hit.name}")
                    if self.act_click(close_hit, "CloseSelfOpenedPanel"):
                        self._selection_click_cooldown_until = now + 1.5
                    self._panel_opened_by_us = None
                    self._selection_unknown_attempts = 0
                    self._selection_unknown_since = None
                    return LoopAction.Continue
            if elapsed >= 10:
                print("[L1] 未知选择面板无法识别，Fail-Closed 停止运行（零输入，不盲点隐藏）")
                self.set_phase(Phase.ERROR, "unknown selection panel timeout")
                self.stop()
                return LoopAction.Break
            print(
                f"[L1] 当前选择无配置命中（已等 {elapsed:.0f}s），保持零输入等待…"
            )
            return LoopAction.Continue

        self._selection_unknown_attempts = 0
        self._selection_unknown_since = None
        self._selection_repeat_key = None
        self._selection_repeat_attempts = 0
        self._skill_refresh_attempts = 0

        # 右侧“自动任务”复选框（左键点击）
        auto_res = self._ensure_auto_task_enabled(frame)
        if auto_res is not None:
            self._main_line_since = now
            return auto_res
        if not self._auto_task_done:
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

        # 我们主动打开的 G/F/V 候选条可能没有中央面板锚点。
        compact_res = self._handle_self_opened_compact_panel(frame)
        if compact_res is not None:
            self._main_line_since = now
            return compact_res

        # 技能/羁绊/宝物优先于会重复出现的进化按钮，避免 G/F/V 饿饿。
        opened = self._maybe_open_choice_panel(frame, anchor=selection_anchor)
        if opened is not None:
            self._main_line_since = now
            return opened

        # 神器优先于会反复出现的进化按钮，避免 Q/W/E 饿饿。
        artifact_res = self._maybe_fire_artifacts(frame)
        if artifact_res is not None:
            self._main_line_since = now
            return artifact_res

        # 点击进化（未满5级时中下方出现，实机坐标 1600x900 内 (525,778)）
        if now >= getattr(self, "_evolve_click_cooldown_until", 0.0):
            evolve_hit = self.find(
                frame,
                ["click_evolve"],
                threshold=0.75,
                scales=(0.9, 1.0, 1.1),
            )
            if evolve_hit:
                print(f"[L1] 点击进化 @ {evolve_hit.center}")
                if self.act_click(evolve_hit, "ClickEvolve"):
                    self._evolve_click_cooldown_until = now + 5.0
                    self._main_line_since = now
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
            f"[med] Run dry_run={self.settings.dry_run} mode={self.settings.game_mode} "
            f"auto_room={self._auto_room_enabled()} "
            f"stage={self.settings.stage1}/{self.settings.stage2} "
            f"targets={self.settings.stage_targets or '-'} "
            f"threshold={self.settings.match_threshold} images={self.images}"
        )
        if self.settings.dry_run:
            print("[med] DRY-RUN 仅识别/打印坐标，不会真的点击；要跑全链路请关闭 Dry-run")
        else:
            from gamescript.input.keyboard_mouse import is_current_process_elevated

            if not is_current_process_elevated():
                print(
                    "[med] FATAL: dry_run=False 但当前进程不是管理员。"
                    "原版 GameScript 与 KK 平台均以管理员运行；"
                    "非提权进程的 SendInput 会被 Windows UIPI 静默丢弃（返回成功但游戏无响应）。"
                    "请右键 GameScript.exe，以管理员身份重新启动。"
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
                time.sleep(max(0.0, min(cadence, cap) - elapsed))
        finally:
            if self.emergency_listener:
                self.emergency_listener.stop()
                self.emergency_listener = None
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

