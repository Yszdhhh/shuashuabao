"""
中介层：串起 Settings / 场景表 / 截屏找图 / 键鼠 / 阶段状态机。

对齐实机日志（SUCCESS_FLOW.md）：
  环境 → 准备 → 等进入UI → 主线 → 选卡循环
  → 提前挑战 → 锚点Boss → 龙珠 → 退出 → 下一局

Jobs 不直接碰 OpenCV/输入；只通过本中介 see / act。
"""

from __future__ import annotations

import math
import time
from enum import Enum, auto
from pathlib import Path

import cv2
import numpy as np

from gamescript.input.emergency_stop import EmergencyStopListener
from gamescript.input.keyboard_mouse import InputExecutor
from gamescript.loop_action import LoopAction
from gamescript.scenes import load_scenes, scene_templates
from gamescript.settings import Settings
from gamescript.stop_signal import StopSignal
from gamescript.vision.capture import (
    Frame,
    FrameHealthIssue,
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
    def __init__(self, settings: Settings, project_root: Path, stop_signal: StopSignal | None = None):
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
        self._wait_ui_since: float | None = None
        self._longzhu_deadline: float | None = None
        self._f1_fallback_done = False
        self._boss_clicked = False  # ANCHOR_BOSS 是否已尝试点击
        self._stage_click_cooldown_until = 0.0
        self._stage_selected = False
        self._stage_target_name: str | None = None
        self._stage_target_position: tuple[int, int] | None = None
        self._room_dialog_filled = False
        self._room_action_deadline: float | None = None
        self._room_action_attempts = 0
        self._stage_scroll_attempts = 0
        self._missing_window_since: float | None = None
        self._last_frame: Frame | None = None
        self._prev_frame: Frame | None = None
        self._last_capture_role: str | None = None
        self._context_cache_frame: Frame | None = None
        self._context_cache_role: str | None = None
        self._context_cache_value = "UNKNOWN"
        self._scene_cache: dict[int, tuple[Frame, dict[tuple[str, float | None], MatchResult | None]]] = {}
        # Safety: L0 cycle counter — prevent infinite PLATFORM_MAP ↔ ROOM_WAITING loops
        self._l0_cycle_count = 0
        self._l0_cycle_limit = 5
        # Safety: MAIN_LINE idle deadline — prevent infinite idle on unexpected screens
        self._main_line_since: float | None = None
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
        # Hero-mode automation is intentionally limited to the one complete
        # recorded path: Kenrito, level 1..5, 1600x900 client capture.
        self._hero_state = "IDLE"
        self._hero_verified_level = 0
        self._hero_level_baseline: np.ndarray | None = None
        self._hero_level_candidate: np.ndarray | None = None
        self._hero_card_baseline: np.ndarray | None = None
        self._hero_step_deadline: float | None = None
        self._hero_modal_missing_frames = 0

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
        if self._selection_anchor(frame) or self.find_scene(frame, "card_panel") or self.find_scene(frame, "skill_panel"):
            return True
        for sc in ("coin_challenge", "wood_challenge", "experience_challenge", "treasure_challenge"):
            if self.find_scene(frame, sc):
                return True
        if self.find_scene(frame, "env_anchor"):
            return True
        return False

    def _detect_context(self, frame: Frame, role: str | None = None) -> str:
        """Classify the visible page before taking a state-machine action."""
        # Classification does not depend on role. Reuse it for both L0/L1
        # handlers when they inspect the same frame.
        if self._context_cache_frame is frame:
            return self._context_cache_value

        if self._selection_anchor(frame):
            value = "MAIN_LINE"
        elif self.find_scene(frame, "disconnect") or self.find_scene(frame, "fail"):
            value = "QUIT"
        elif self._find_stage_page(frame):
            # 选关页特征（关卡编号数字）优先于通用「开始游戏」按钮：
            # 选关页底部也有开始/扫荡/英雄模式按钮，room_start 模板会误匹配
            # （官方 1936x1066 选关截图实测 roomStart 0.84 / kk_start 0.92）。
            value = "STAGE_SELECT"
        elif self._find_room_start(frame):
            value = "ROOM_WAITING"
        elif self._is_in_game_hud(frame):
            value = "MAIN_LINE"
        elif self._find_create_confirm(frame):
            value = "CREATE_ROOM"
        elif self._auto_room_enabled() and self._find_map_create_room(frame):
            value = "PLATFORM_MAP"
        else:
            value = "UNKNOWN"

        self._context_cache_frame = frame
        self._context_cache_role = role
        self._context_cache_value = value
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
        """Capture all matching windows without focusing, then use scene pixels."""
        targets = find_window_targets(title, role=role)
        if not targets:
            return capture(title, role=role, activate=False)
        if len(targets) == 1:
            return capture_target(targets[0])
        frames = [capture_target(target) for target in targets]
        previous_hwnd = self._last_frame.hwnd if self._last_capture_role == role and self._last_frame else None
        return max(
            frames,
            key=lambda frame: (
                self._frame_signal(frame, role),
                int(frame.hwnd == previous_hwnd),
            ),
        )

    def see(self, reason: str = "") -> Frame:
        # A single tick asks the same scene questions from capture ranking,
        # context classification and the phase handler.  Reuse those results
        # for this frame; template matching is the dominant hot path.
        # Static frames (identical pixels AND same window position) reuse the
        # previous Frame object so the per-tick scene cache hits instead of
        # re-scanning every template.
        self._scene_cache.clear()
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

    def find(
        self,
        frame: Frame,
        names: list[str],
        threshold: float | None = None,
        scales: tuple[float, ...] = (1.0,),
        roi: tuple[float, float, float, float] | None = None,
    ) -> MatchResult | None:
        if not names:
            return None
        th = threshold if threshold is not None else self.settings.match_threshold
        return match_any(frame, self.images, names, threshold=th, scales=scales, roi=roi)

    def find_scene(self, frame: Frame, scene_key: str, threshold: float | None = None) -> MatchResult | None:
        frame_key = id(frame)
        cached = self._scene_cache.get(frame_key)
        if cached is None or cached[0] is not frame:
            cached_results: dict[tuple[str, float | None], MatchResult | None] = {}
            self._scene_cache[frame_key] = (frame, cached_results)
        else:
            cached_results = cached[1]
        cache_key = (scene_key, threshold)
        if cache_key in cached_results:
            return cached_results[cache_key]
        # 官方截图常见 1600x900；窗口/系统缩放会让当前帧达到 1936x1066。
        # 只对 L0 门闩和选关标识做多尺度，避免卡牌/技能全库扫描变慢。
        scales = (0.9, 1.0, 1.1, 1.15, 1.2) if scene_key in {
            "lobby_start",
            "lobby_room",
            "room_start",
            "stage_start",
            "start",
            "stage",
            "stage_page",
            "coin_challenge",
            "wood_challenge",
            "experience_challenge",
            "treasure_challenge",
        } else (1.0,)
        result = self.find(frame, self.templates(scene_key), threshold=threshold, scales=scales)
        cached_results[cache_key] = result
        return result

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

    def act_click(self, hit: MatchResult, reason: str = "") -> bool:
        print(f"[med] click {hit.name} score={hit.score:.3f} @ {hit.center} ({reason})")
        target_hwnd = self._last_frame.hwnd if self._last_frame else None
        res = self.executor.click(
            hit.screen_x,
            hit.screen_y,
            target_hwnd=target_hwnd,
            dry_run=self.settings.dry_run,
            delay_ms=self.settings.click_delay_ms,
        )
        return res.success

    def act_right_click(self, hit: MatchResult, reason: str = "") -> bool:
        print(f"[med] right_click {hit.name} score={hit.score:.3f} @ {hit.center} ({reason})")
        target_hwnd = self._last_frame.hwnd if self._last_frame else None
        res = self.executor.right_click(
            hit.screen_x,
            hit.screen_y,
            target_hwnd=target_hwnd,
            dry_run=self.settings.dry_run,
            delay_ms=self.settings.click_delay_ms,
        )
        return res.success

    def act_key(self, key: str, reason: str = "") -> bool:
        print(f"[med] key {key!r} ({reason})")
        target_hwnd = self._last_frame.hwnd if self._last_frame else None
        res = self.executor.press_key(
            key,
            target_hwnd=target_hwnd,
            dry_run=self.settings.dry_run,
        )
        return res.success

    def click_scene(self, frame: Frame, scene_key: str, reason: str = "", threshold: float | None = None) -> bool:
        hit = self.find_scene(frame, scene_key, threshold=threshold)
        if not hit:
            print(f"[med] miss scene={scene_key} th={threshold or self.settings.match_threshold} ({reason})")
            return False
        return self.act_click(hit, reason or scene_key)

    # ---------- 局内选择 / 挑战 ----------

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
        """
        threshold = min(0.70, self.settings.match_threshold)
        hit = self.find(
            frame,
            [
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
            ],
            threshold=threshold,
            scales=(0.85, 0.9, 1.0, 1.1, 1.15, 1.2),
            roi=(0.20, 0.45, 0.80, 0.80),
        )
        if not hit:
            return None
        # hit.x/y 在 ROI 裁剪后是 ROI 内坐标；用屏幕坐标换算回帧坐标做位置校验
        fx = hit.screen_x - frame.left
        fy = hit.screen_y - frame.top
        if fx < frame.width * 0.20 or fx > frame.width * 0.80:
            return None
        if fy < frame.height * 0.50:
            return None
        return hit

    def _classify_choice_panel(self, frame: Frame) -> str | None:
        """Distinguish skill / bond / treasure choice panels by their unique buttons."""
        threshold = min(0.70, self.settings.match_threshold)
        scales = (0.9, 1.0, 1.1)
        if self.find(frame, ["skill_giveup_btn", "skill_refresh_btn"], threshold=threshold, scales=scales):
            return "skill"
        if self.find(frame, ["treasure_lock_btn"], threshold=threshold, scales=scales):
            return "treasure"
        if self.find(frame, ["bond_hide_btn", "bond_refresh_btn"], threshold=threshold, scales=scales):
            return "bond"
        if self.find(frame, ["card_hide"], threshold=threshold, scales=scales):
            return "card"
        return None

    @staticmethod
    def _preferred_choice(hits: list[MatchResult], preferred: list[str]) -> MatchResult | None:
        wanted = {Path(value).stem for value in preferred if value}
        return next((hit for hit in hits if hit.name in wanted), None)

    def _auto_task_roi_frame(self, frame: Frame) -> Frame | None:
        if frame.bgr is None or frame.bgr.size == 0 or frame.width < 1000 or frame.height < 600:
            return None
        h, w = frame.height, frame.width
        x1, x2 = int(0.85 * w), int(0.95 * w)
        y1, y2 = int(0.50 * h), int(0.65 * h)
        roi_bgr = frame.bgr[y1:y2, x1:x2]
        if roi_bgr.size == 0:
            return None
        return Frame(bgr=roi_bgr, left=frame.left + x1, top=frame.top + y1)

    def _is_auto_task_enabled(self, frame: Frame) -> bool:
        """Check if the right task panel '自动任务' checkbox is explicitly ON using auto_task_on template match."""
        roi_frame = self._auto_task_roi_frame(frame)
        if roi_frame is None:
            return False
        tmpl_on = resolve_template(self.images, "auto_task_on")
        if tmpl_on is None or not tmpl_on.is_file():
            return False
        hit = match_one(roi_frame, tmpl_on, threshold=0.85, name="auto_task_on", scales=(0.9, 1.0, 1.1))
        return hit is not None

    def _find_auto_task_toggle(self, frame: Frame) -> MatchResult | None:
        """Return a left-click candidate for the right-side auto task checkbox ONLY if explicitly OFF via auto_task_off template match."""
        if self._selection_anchor(frame):
            return None
        if self._is_auto_task_enabled(frame):
            return None
        roi_frame = self._auto_task_roi_frame(frame)
        if roi_frame is None:
            return None
        tmpl_off = resolve_template(self.images, "auto_task_off")
        if tmpl_off is None or not tmpl_off.is_file():
            return None
        hit = match_one(roi_frame, tmpl_off, threshold=0.85, name="auto_task_toggle", scales=(0.9, 1.0, 1.1))
        return hit

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

    # 卡牌品质色（用户规则）：蓝EX > 红UR > 橙SSR > 紫SR > 浅蓝R；绿=选中框排除
    RARITY_BANDS = (
        ("ex", 55, 75, 5),
        ("ur", 0, 15, 4),
        ("ssr", 15, 25, 3),
        ("sr", 100, 125, 2),
        ("r", 75, 95, 1),
    )

    def _card_rarity_score(self, frame: Frame, cx: int, cy: int) -> tuple[int, str, int] | None:
        """Score a card's border-ring color by rarity band.

        Returns (score, band, saturated_pixels) or None when no rarity color.
        """
        try:
            import numpy as np
            import cv2 as _cv2
        except Exception:
            return None
        w, h = int(frame.width * 0.094), int(frame.height * 0.122)
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
        saturated = sat > 60
        if int(saturated.sum()) < 30:
            return None
        hue_vals = hues[saturated]
        best: tuple[int, str, int] | None = None
        for band, lo, hi, score in self.RARITY_BANDS:
            if band == "ur":
                count = int(((hue_vals >= 0) & (hue_vals <= 15)).sum()) + int(
                    ((hue_vals >= 165) & (hue_vals <= 180)).sum()
                )
            else:
                count = int(((hue_vals >= lo) & (hue_vals <= hi)).sum())
            if count >= 30 and (best is None or count > best[2]):
                best = (score, band, count)
        return best

    def _rarity_choice(self, frame: Frame, panel_kind: str) -> MatchResult | None:
        """Pick the highest-rarity card in a 3-choice panel by border color."""
        if panel_kind == "treasure":
            xs = (0.234, 0.363, 0.491)
            cy_ratio = 0.367
        else:
            xs = (0.331, 0.450, 0.569)
            cy_ratio = 0.333
        best: tuple[int, str, int, int, int] | None = None
        for x_ratio in xs:
            cx = int(frame.width * x_ratio)
            cy = int(frame.height * cy_ratio)
            r = self._card_rarity_score(frame, cx, cy)
            if r is None:
                continue
            score, band, count = r
            if best is None or score > best[0] or (score == best[0] and count > best[3]):
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

    def _find_reward_choice(self, frame: Frame, anchor: MatchResult | None = None) -> tuple[str, MatchResult] | None:
        """Decision layer for an open reward-choice panel.

        Policy (one action max, preferred-only):
        1. classify panel kind; UNKNOWN → None (caller handles: close if we
           opened it, else zero-input)
        2. match ONLY user-preferred templates (skills/cards); a preferred hit
           is chosen directly
        3. no preferred hit → rarity color pick
        4. still nothing → safe close button (暂时隐藏/放弃)
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
            return None

        if kind in ("bond", "treasure", "card"):
            preferred = [v.strip() for v in self.settings.cards if v and v.strip()]
            if preferred:
                names = [v if "/" in v else f"cards/{v}" for v in preferred]
                hits = match_all(
                    frame,
                    self.images,
                    names,
                    threshold=min(0.70, self.settings.match_threshold),
                    roi=self._selection_roi(),
                    max_results=12,
                    scales=(0.90, 1.0, 1.05, 1.10),
                )
                hits = sorted(hits, key=lambda h: h.score, reverse=True)
                candidates: list[MatchResult] = []
                for h in hits:
                    if not any(math.hypot(h.x - c.x, h.y - c.y) < 40.0 for c in candidates):
                        candidates.append(h)
                if candidates:
                    wanted = {Path(v).stem for v in preferred}
                    for c in candidates:
                        if Path(c.name).stem in wanted:
                            return (kind, c)
            # 无偏好命中 → 按品质色选最高稀有度
            rarity_hit = self._rarity_choice(frame, kind)
            if rarity_hit is not None:
                return (kind, rarity_hit)
            # 无匹配 → 点「暂时隐藏」关闭面板
            hide = self.find(
                frame,
                ["bond_hide_btn", "treasure_hide_btn", "card_hide"],
                threshold=min(0.70, self.settings.match_threshold),
                scales=(0.9, 1.0, 1.1),
            )
            if hide:
                print(f"[L1] {kind}面板无配置匹配，点击暂时隐藏关闭")
                return (kind, hide)
            return None

        # skill panel: preferred-only
        preferred = [v.strip() for v in self.settings.skills if v and v.strip()]
        if preferred:
            names = [v if "/" in v else f"skills/{v}" for v in preferred]
            hits = match_all(
                frame,
                self.images,
                names,
                threshold=min(0.70, self.settings.match_threshold),
                roi=self._selection_roi(),
                max_results=8,
                scales=(0.90, 1.0, 1.05, 1.10),
            )
            hits = sorted(hits, key=lambda h: h.score, reverse=True)
            candidates: list[MatchResult] = []
            for h in hits:
                if not any(math.hypot(h.x - c.x, h.y - c.y) < 40.0 for c in candidates):
                    candidates.append(h)
            if candidates:
                wanted = {Path(v).stem for v in preferred}
                for c in candidates:
                    if Path(c.name).stem in wanted:
                        return ("技能", c)
        # 无偏好命中 → 按品质色选最高稀有度
        rarity_hit = self._rarity_choice(frame, "skill")
        if rarity_hit is not None:
            return ("技能", rarity_hit)
        # 无匹配 → 点「放弃/暂时隐藏」关闭
        close_hit = self._close_current_panel(frame)
        if close_hit is not None:
            self._panel_opened_by_us = None
            print(f"[L1] 技能面板无配置匹配，点击关闭 {close_hit.name}")
            return ("技能", close_hit)
        return None

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
        """Periodic Q/W/E artifact release (fixed 180s cooldown per slot).

        Slots = artifact_slots (1-3) mapping to Q/W/E keys; a slot is skipped
        when its icon is absent (unlocked but empty, or fewer slots). First
        fire deferred ~30s after entering MAIN_LINE.
        """
        if not getattr(self.settings, "auto_artifact", True):
            return None
        if not self._main_line_since:
            return None
        now = time.time()
        if now - self._main_line_since < 30:
            return None
        cd = max(30, int(getattr(self.settings, "artifact_cd", 180)))
        slots = max(1, min(3, int(getattr(self.settings, "artifact_slots", 2))))
        keys = ("q", "w", "e")[:slots]
        acted = False
        target_hwnd = self._last_frame.hwnd if self._last_frame else None
        for idx, key in enumerate(keys):
            next_at = getattr(self, f"_artifact_next_{key}", 0.0)
            if now < next_at:
                continue
            if frame is not None and not self._slot_has_artifact(frame, idx):
                print(f"[L1] 神器槽{idx + 1}({key.upper()})为空，跳过释放")
                setattr(self, f"_artifact_next_{key}", now + cd)
                continue
            res = self.executor.press_key(key, target_hwnd=target_hwnd, dry_run=self.settings.dry_run)
            if not res.success:
                # 输入被拒（前台/急停/遮挡）：不推进 CD，下轮重试
                print(f"[L1] 神器 {key.upper()} 释放被拒绝: {res.message}（不推进冷却）")
                continue
            setattr(self, f"_artifact_next_{key}", now + cd)
            print(f"[L1] 释放神器 {key.upper()}（冷却 {cd}s）")
            acted = True
        return LoopAction.Continue if acted else None

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
        target_hwnd = self._last_frame.hwnd if self._last_frame else None
        # 技能 G：核心，60s
        if now - getattr(self, "_last_skill_panel", 0.0) >= 60:
            res = self.executor.press_key("g", target_hwnd=target_hwnd, dry_run=self.settings.dry_run)
            if res.success:
                self._last_skill_panel = now
                self._panel_opened_by_us = "skill"
                print("[L1] 主动按 G 打开技能面板（核心，60s 一次）")
            else:
                print(f"[L1] 按 G 被拒绝: {res.message}（不推进冷却）")
            return LoopAction.Continue
        interval = max(30, getattr(self.settings, "choice_interval", 120))
        # 羁绊 F / 宝物 V：低频
        if getattr(self.settings, "auto_bond", True):
            if now - getattr(self, "_last_bond_attempt", 0.0) >= interval:
                res = self.executor.press_key("f", target_hwnd=target_hwnd, dry_run=self.settings.dry_run)
                if res.success:
                    self._last_bond_attempt = now
                    self._panel_opened_by_us = "bond"
                    print("[L1] 主动按 F 打开羁绊面板（低频）")
                else:
                    print(f"[L1] 按 F 被拒绝: {res.message}（不推进冷却）")
                return LoopAction.Continue
        if getattr(self.settings, "auto_treasure", True):
            if now - getattr(self, "_last_treasure_attempt", 0.0) >= interval:
                res = self.executor.press_key("v", target_hwnd=target_hwnd, dry_run=self.settings.dry_run)
                if res.success:
                    self._last_treasure_attempt = now
                    self._panel_opened_by_us = "treasure"
                    print("[L1] 主动按 V 打开宝物面板（低频）")
                else:
                    print(f"[L1] 按 V 被拒绝: {res.message}（不推进冷却）")
                return LoopAction.Continue
        return None

    def _close_current_panel(self, frame: Frame) -> MatchResult | None:
        """Find the close button (放弃/暂时隐藏) for the currently open panel.

        Used as a safe fallback when a panel we proactively opened cannot be
        matched to any card choice.
        """
        kind = getattr(self, "_panel_opened_by_us", None)
        if kind == "skill":
            names = ["skill_giveup_btn", "skill_refresh_btn"]
        elif kind == "treasure":
            names = ["treasure_hide_btn", "treasure_lock_btn"]
        elif kind == "bond":
            names = ["bond_hide_btn", "bond_refresh_btn"]
        else:
            names = ["skill_giveup_btn", "bond_hide_btn", "treasure_hide_btn", "card_hide"]
        return self.find(
            frame,
            names,
            threshold=min(0.70, self.settings.match_threshold),
            scales=(0.9, 1.0, 1.1),
        )

    # ---------- 战后页面多锚点判别（P1-B0/B1）----------

    def _post_game_state(self, frame: Frame) -> str | None:
        """Multi-anchor post-game page classifier.

        Combines legacy-template anchors with normalized position checks. The
        legacy anchors alone are NOT page-specific (archiveChallenge/cjb/ok/close
        all hit shared post-game HUD elements), so position disambiguation is
        required. Thresholds validated against fixtures/reborn_wow/endgame/*.

        Returns one of:
          POST_VICTORY        victory modal + continue button
          HEIRLOOM_DIALOG     heirloom boss dialog (cjbtiaozhan banner)
          GREAT_RIFT_CONFIRM  great-rift confirm dialog (center ok/mijingOk)
          ARCHIVE_PANEL       archive challenge panel (modal close, no rift NPC)
          NPC_HUB             post-victory world lobby (quit top-left + rift NPC right)
        or None when no post-game page is recognized.
        """
        w, h = frame.width, frame.height
        if w < 800 or h < 600:
            return None

        def find(name: str, threshold: float) -> MatchResult | None:
            return self.find(frame, [name], threshold=threshold, scales=(0.9, 1.0, 1.1))

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

    def _find_archive_panel_close(self, frame: Frame) -> MatchResult | None:
        hit = self.find(
            frame,
            ["lobby/archive_panel_close"],
            threshold=0.85,
            scales=(0.9, 1.0, 1.1),
        )
        if not hit:
            return None
        if not (frame.width * 0.55 <= hit.x <= frame.width * 0.70):
            return None
        if not (frame.height * 0.15 <= hit.y <= frame.height * 0.35):
            return None
        return hit

    def _find_game_exit(self, frame: Frame) -> MatchResult | None:
        hit = self.find(frame, ["quit"], threshold=0.78, scales=(0.9, 1.0, 1.1))
        if not hit:
            return None
        if hit.x > frame.width * 0.12 or hit.y > frame.height * 0.15:
            return None
        return hit

    def _find_exit_confirm(self, frame: Frame) -> MatchResult | None:
        hit = self.find(
            frame,
            ["lobby/exit_confirm_btn"],
            threshold=0.88,
            scales=(0.9, 1.0, 1.1),
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
        """True when the sweep-ticket remainder shows 0 on the stage-select page.

        Ticket number sits below the 扫荡 button: (862,850,985,888) in the
        1600x900 window; the remainder digit(s) occupy the left part
        (862..920). A '0' glyph template matched inside that ROI means the
        remainder is zero (ticket_zero template sourced from live UI).
        """
        if not getattr(self.settings, "auto_archaeology", True):
            return False
        hit = self.find(
            frame,
            ["lobby/ticket_zero"],
            threshold=0.72,
            scales=(0.9, 1.0, 1.1, 1.2),
            roi=(862 / 1600.0, 850 / 900.0, 920 / 1600.0, 888 / 900.0),
        )
        return hit is not None

    def _maybe_switch_to_archaeology(self, frame: Frame) -> LoopAction | None:
        """Ticket exhausted -> click 考古模式 (1376,813) -> stop script.

        Confirms 3 consecutive frames before acting to avoid a flicker false
        positive. Returns LoopAction.Break after switching, None otherwise.
        """
        if not getattr(self.settings, "auto_archaeology", True):
            return None
        if self._ticket_exhausted(frame):
            count = getattr(self, "_ticket_zero_frames", 0) + 1
            self._ticket_zero_frames = count
            if count < 3:
                print(f"[L0] 扫荡券剩余为 0（确认 {count}/3），等待稳定…")
                return LoopAction.Continue
            print("[L0] 扫荡券已清空，点击考古模式并结束脚本")
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
            self.act_click(arch_hit, "SwitchToArchaeology")
            self._ticket_zero_frames = 0
            self.set_phase(Phase.QUIT, "archaeology mode after ticket exhausted")
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
        if phase == Phase.STAGE_SELECT:
            self._stage_scroll_attempts = 0
            # 跨局重置：次局进入选关页必须重新选关（上一局残留会跳过选关/点错关）
            self._stage_selected = False
            self._stage_target_name = None
            self._stage_target_position = None
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
        self.phase = phase
        if phase == Phase.WAIT_UI:
            self._wait_ui_since = time.time()
        if phase == Phase.MAIN_LINE:
            self._main_line_since = time.time()
            self._selection_click_cooldown_until = 0.0
            self._selection_unknown_attempts = 0
            self._selection_unknown_since = None
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

    def wait_ui_timed_out(self) -> bool:
        if self._wait_ui_since is None:
            return False
        return (time.time() - self._wait_ui_since) >= self.settings.query_timeout

    def longzhu_timed_out(self) -> bool:
        if self._longzhu_deadline is None:
            return False
        return time.time() >= self._longzhu_deadline

    # ---------- L0 显式页面链 ----------

    def _auto_room_enabled(self) -> bool:
        return self.settings.auto_create_room or self.settings.game_mode == 1

    def _find_room_start(self, frame: Frame) -> MatchResult | None:
        return self.find_scene(frame, "room_start")

    def _find_stage_start(self, frame: Frame) -> MatchResult | None:
        if not self._find_stage_page(frame):
            return None
        return self.find_scene(frame, "stage_start")

    def _find_stage_page(self, frame: Frame) -> bool:
        if visible_stage_rows(frame, self.images):
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
        hit = self.find(frame, names, scales=(0.9, 1.0, 1.1, 1.15, 1.2))
        # stage.png is the large map card; toHero/HeroChallenge are hero icons.
        # They are not sufficient to prove that the numbered stage list is open.
        return bool(
            hit
            and hit.name not in ("stage", "toHero", "HeroChallenge")
            and hit.x >= int(frame.width * 0.55)
        )


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

    def _fill_room_dialog(self, frame: Frame, confirm: MatchResult) -> bool:
        if not self.settings.room_name and not self.settings.room_password:
            return True
        boxes = find_input_boxes(frame, anchor=confirm)
        if len(boxes) < 2:
            print("[L0] 建房弹窗未安全识别到房间名/密码输入框，拒绝盲填")
            return False
        values = (self.settings.room_name, self.settings.room_password)
        target_hwnd = self._last_frame.hwnd if self._last_frame else None
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
        print("[L0] 建房弹窗已填写房间名/密码")
        return True

    def _action_timed_out(self) -> bool:
        return self._room_action_deadline is not None and time.time() >= self._room_action_deadline

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

        if context in ("MAIN_LINE", "IN_GAME"):
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
            # 扫荡券清空 → 自动进考古模式并结束脚本
            arch_res = self._maybe_switch_to_archaeology(frame)
            if arch_res is not None:
                return arch_res
            now = time.time()
            if not self._stage_selected:
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
                        res_scroll = self.executor.scroll(x, y, -5, target_hwnd=target_hwnd, dry_run=self.settings.dry_run)
                        if res_scroll.success:
                            self._stage_scroll_attempts += 1
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
                print(f"[L0] 选关 SelectStage {target.name} @ {target.center}")
                if not self.act_click(target, "SelectStage-target"):
                    return LoopAction.Continue
                self._stage_selected = True
                self._stage_target_name = target.name
                self._stage_target_position = (target.x, target.y)
                self._stage_click_cooldown_until = now + 1.5
                self._room_action_deadline = now + max(10, min(self.settings.query_timeout, 30))
                return LoopAction.Continue
            if now < self._stage_click_cooldown_until:
                print("[L0] 等待关卡选中状态稳定…")
                return LoopAction.Continue
            target_spec = self.settings.stage_targets[0] if self.settings.stage_targets else self.settings.stage1
            if not verify_stage_selection(frame, target=target_spec, images_dir=self.images):
                # The live stage list does not render a reliable persistent
                # row highlight.  Confirm the exact same target label remains
                # at the clicked client coordinate and require the dedicated
                # start button before advancing.  This avoids the old endless
                # re-click loop without allowing an arbitrary visible stage.
                current_target = self._find_stage_target(frame)
                # The live list can move the selected row; the exact label is
                # unique, so position persistence is not a useful guard.
                same_target = bool(current_target and current_target.name == self._stage_target_name)
                ready = self._find_hero_entry(frame) if self.settings.auto_reputation else self._find_stage_start(frame)
                if not same_target or not ready:
                    print("[L0] 关卡选中态未确认，等待精确目标与专用开始按钮同时稳定")
                    if self._action_timed_out():
                        self._stage_selected = False
                        self._stage_target_name = None
                        self._stage_target_position = None
                    return LoopAction.Continue
                print("[L0] 目标行无持久高亮；已用精确目标位置 + 专用开始按钮完成复合确认")
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
            self.set_phase(Phase.STAGE_STARTING, "stage start clicked")
            return LoopAction.Continue

        if self.phase == Phase.STAGE_STARTING:
            # 统一"已进局"定义：选择面板/四挑战/环境锚点任一可信证据即可
            if self._is_in_game_hud(frame) or self._detect_context(frame, role="l1") == "MAIN_LINE":
                print("[L1] 开始主线 / phase=MAIN_LINE")
                self.set_phase(Phase.MAIN_LINE, "stage start verified")
                return LoopAction.Continue
            if stage_page and self._action_timed_out():
                start = self._find_stage_start(frame)
                if start and self._room_action_attempts < 2:
                    print("[L0] 选关后页面未变化，重试点击开始")
                    if not self.act_click(start, "StageStart-retry"):
                        return LoopAction.Continue
                    self._room_action_attempts += 1
                    self._room_action_deadline = time.time() + min(self.settings.query_timeout, 15)
                else:
                    print("[L0] 选关开始重试耗尽，回到选关页")
                    self._stage_selected = False
                    self.set_phase(Phase.STAGE_SELECT, "stage start retries exhausted")
            elif self._action_timed_out():
                print("[L0] 选关后未出现局内 UI，回到选关页")
                self._stage_selected = False
                self.set_phase(Phase.STAGE_SELECT, "stage start verify timeout")
            else:
                print("[L0] 等待局内卡牌/技能 UI…")
            return LoopAction.Continue

        return LoopAction.Continue

    # ---------- 主循环（中介调度）----------

    def stop(self) -> None:
        self._running = False
        self.stop_signal.trigger("Mediator.stop()")

    def tick(self) -> LoopAction:
        """单步：一帧截屏 → 按阶段决策 → 执行。"""
        if self.stop_signal.is_set():
            print(f"[med] Stop signal active ({self.stop_signal.reason}), breaking loop")
            self._running = False
            return LoopAction.Break

        frame = self.see("tick")

        health = check_frame_health(frame, prev_frame=self._prev_frame)
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
                elif elapsed >= min(self.settings.query_timeout, 15):
                    self.set_phase(Phase.ERROR, "unhealthy frame timeout")
                    self.stop()
                    return LoopAction.Break
                return LoopAction.Continue

        self._missing_window_since = None

        # 全局：断线/失败优先（一帧最多一个改变 UI 的动作）
        if self.find_scene(frame, "disconnect") or self.find_scene(frame, "fail"):
            if self.phase != Phase.QUIT:
                self.set_phase(Phase.QUIT, "fail/disconnect")
            # RecoveryState 状态机：每次动作后重新抓帧，防止旧帧连点
            recovery = getattr(self, "_recovery_step", "FAIL_VISIBLE")
            if recovery == "FAIL_VISIBLE":
                hit = self.find_scene(frame, "fail")
                if hit:
                    self.click_scene(frame, "fail", "recover")
                    self._recovery_step = "WAIT_OK"
                else:
                    self._recovery_step = "WAIT_OK"
                return LoopAction.Continue
            if recovery == "WAIT_OK":
                hit = self.find_scene(frame, "ok")
                if hit:
                    self.click_scene(frame, "ok", "ok")
                    self._recovery_step = "WAIT_CLOSE"
                else:
                    self._recovery_step = "WAIT_CLOSE"
                return LoopAction.Continue
            if recovery == "WAIT_CLOSE":
                hit = self.find_scene(frame, "close")
                if hit:
                    self.click_scene(frame, "close", "close")
                self._recovery_step = "DONE"
                return LoopAction.Continue
            # DONE：等待画面恢复（QUIT 相位处理退出）
            return LoopAction.Continue

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

            hit = self.find(frame, ["continueGame"], threshold=0.80, scales=(0.9, 1.0, 1.1))
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

        # 提前挑战 / Boss / 龙珠入口：未验证战后入口，Fail-Closed（最高优先，必须在任何选择、自动任务、挑战或选关之前）
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
        if self.find_scene(frame, "longzhu"):
            print("[med] 识别到未验证战后入口 longzhu，Fail-Closed 停止运行")
            self.set_phase(Phase.ERROR, "unverified longzhu entry")
            self.stop()
            return LoopAction.Break

        # 选择面板优先；面板存在时禁止把刷新计数或快捷键当成按钮。
        selection_anchor = self._selection_anchor(frame)
        if selection_anchor:
            if now < self._selection_click_cooldown_until:
                print("[L1] 选择面板等待点击结果…")
                return LoopAction.Continue
            choice = self._find_reward_choice(frame, anchor=selection_anchor)
            if choice:
                kind, hit = choice
                print(f"[L1] {kind}选择 {hit.name} score={hit.score:.3f} @ {hit.center}")
                if self.act_click(hit, f"{kind}选择"):
                    self._selection_click_cooldown_until = now + 1.5
                self._selection_unknown_attempts = 0
                self._selection_unknown_since = None
                self._panel_opened_by_us = None
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

        # 右侧“自动任务”复选框（左键点击）
        auto_res = self._ensure_auto_task_enabled(frame)
        if auto_res is not None:
            self._main_line_since = now
            return auto_res

        # 挑战按钮有自己的模板和自动状态检测，避免固定坐标反复切换开关。
        ch_res = self._ensure_challenge_buttons(frame)
        if ch_res is not None:
            self._main_line_since = now
            return ch_res

        # 关卡选关：只点击右侧编号行，不能把 stage.png 地图卡片当按钮。
        if now >= self._stage_click_cooldown_until:
            hit_stage = (
                find_stage_labels(frame, self.images, self.settings.stage_targets)
                if self.settings.stage_targets
                else find_stage_in_range(
                    frame,
                    self.images,
                    self.settings.stage1,
                    self.settings.stage2,
                )
            )
            if hit_stage:
                print(f"[L1] 局内选关 SelectStage {hit_stage.name}")
                if self.act_click(hit_stage, "SelectStage-InGame-target"):
                    self._stage_click_cooldown_until = now + 2.0
                    self._main_line_since = now
                    return LoopAction.Continue

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

        # 神器 Q/W/E 定时释放（180s CD，进局 30s 后开始，空槽跳过）
        artifact_res = self._maybe_fire_artifacts(frame)
        if artifact_res is not None:
            self._main_line_since = now
            return artifact_res

        # 主动羁绊/宝物（快捷键 F/V，低频防烧资源；配置开启才动作）
        if self.settings.auto_bond or self.settings.auto_treasure:
            opened = self._maybe_open_choice_panel(frame, anchor=selection_anchor)
            if opened is not None:
                self._main_line_since = now
                return opened

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
            self._wait_ui_since = None
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
                action = self.tick()
                steps += 1
                if action == LoopAction.Break:
                    break
                if max_steps is not None and steps >= max_steps:
                    print(f"[med] max_steps={max_steps}")
                    break
                time.sleep(self.settings.loop_sleep_ms / 1000.0)
        finally:
            if self.emergency_listener:
                self.emergency_listener.stop()
                self.emergency_listener = None
        print(f"[med] end steps={steps} games={self.game_count}")

