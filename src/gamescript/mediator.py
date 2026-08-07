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
    ERROR = auto()  # 目标窗口不可用
    MAIN_LINE = auto()  # 开始主线 / 选卡
    EARLY_CHALLENGE = auto()  # 提前挑战
    ANCHOR_BOSS = auto()  # 锚点 Boss
    LONGZHU = auto()  # 找龙珠
    QUIT = auto()  # 退出
    NEXT = auto()  # 下一局


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
        self._challenge_states: dict[str, ChallengeState] = {
            "coin_challenge": ChallengeState.PENDING,
            "wood_challenge": ChallengeState.PENDING,
            "experience_challenge": ChallengeState.PENDING,
            "treasure_challenge": ChallengeState.PENDING,
        }
        self._auto_task_done: bool = False
        self._auto_task_attempts: int = 0

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
        if self._context_cache_frame is frame and self._context_cache_role == role:
            return self._context_cache_value

        if self._selection_anchor(frame):
            value = "MAIN_LINE"
        elif self.find_scene(frame, "disconnect") or self.find_scene(frame, "fail"):
            value = "QUIT"
        elif role == "l1" and self._find_stage_page(frame):
            value = "STAGE_SELECT"
        elif self._find_room_start(frame):
            value = "ROOM_WAITING"
        elif self._find_stage_page(frame):
            value = "STAGE_SELECT"
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
        context = "NO_WINDOW" if frame.hwnd is None and not frame.window_title else self._detect_context(frame, role)
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
    ) -> MatchResult | None:
        if not names:
            return None
        th = threshold if threshold is not None else self.settings.match_threshold
        return match_any(frame, self.images, names, threshold=th, scales=scales)

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
        """Find the bottom ``暂时隐藏`` anchor of a reward-choice panel."""
        threshold = min(0.70, self.settings.match_threshold)
        hit = self.find(
            frame,
            ["skill_hide", "card_hide", "hide"],
            threshold=threshold,
            scales=(0.85, 0.9, 1.0, 1.1, 1.15, 1.2),
        )
        if not hit:
            return None
        if hit.x < frame.width * 0.20 or hit.x > frame.width * 0.80:
            return None
        if hit.y < frame.height * 0.50:
            return None
        return hit

    def _choice_hits(self, frame: Frame, directory: str, preferred: list[str]) -> list[MatchResult]:
        folder = self.images / directory
        names: list[str] = []
        for value in preferred:
            value = (value or "").strip()
            if not value:
                continue
            names.append(value if "/" in value else f"{directory}/{value}")
        if folder.is_dir():
            names.extend(f"{directory}/{path.stem}" for path in sorted(folder.glob("*.png")))
        names = list(dict.fromkeys(names))
        kwargs = {
            "threshold": min(0.70, self.settings.match_threshold),
            "roi": self._selection_roi(),
            "max_results": 12,
        }
        hits = match_all(frame, self.images, names, scales=(0.85, 0.95, 1.0, 1.05, 1.1), **kwargs)
        return hits

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

    def _find_reward_choice(self, frame: Frame) -> tuple[str, MatchResult] | None:
        if not self._selection_anchor(frame):
            return None

        skills_dir = self.images / "skills"
        if not skills_dir.is_dir():
            return None

        names = [f"skills/{p.stem}" for p in sorted(skills_dir.glob("*.png"))]
        kwargs = {
            "threshold": min(0.70, self.settings.match_threshold),
            "roi": self._selection_roi(),
            "max_results": 16,
        }
        all_hits = match_all(frame, self.images, names, scales=(0.90, 1.0, 1.05, 1.10), **kwargs)

        hits_sorted = sorted(all_hits, key=lambda h: h.score, reverse=True)
        candidates: list[MatchResult] = []
        for h in hits_sorted:
            if not any(math.hypot(h.x - c.x, h.y - c.y) < 40.0 for c in candidates):
                candidates.append(h)

        count = len(candidates)
        if count not in (3, 4):
            print(f"[L1] 发现选择面板，但技能候选数量 ({count}) 不属于 3 或 4 选一，返回无动作")
            return None

        configured_candidates: list[tuple[int, MatchResult]] = []
        for c in candidates:
            stem = Path(c.name).stem
            if stem in self.settings.skills:
                idx = self.settings.skills.index(stem)
                configured_candidates.append((idx, c))

        if not configured_candidates:
            print(f"[L1] 发现 {count}选一 技能面板，但画面中无配置匹配技能，保持无动作")
            return None

        configured_candidates.sort(key=lambda item: item[0])
        _, best_hit = configured_candidates[0]
        return ("技能", best_hit)

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
                continue

            attempts = self._challenge_attempts.get(scene_key, 0)
            if attempts >= 3:
                print(f"[L1] {label}挑战重试次数已达上限 ({attempts}) 且未确认开启，Fail-Closed 停止运行")
                self.set_phase(Phase.ERROR, f"{scene_key} attempt limit reached")
                self.stop()
                return LoopAction.Break

            found = self._find_challenge_button(frame, scene_key)
            label_hit = found[0] if found else None
            state = self._resolve_challenge_state(frame, label_hit)

            if state == ChallengeState.ON:
                print(f"[L1] {label}挑战已是自动模式")
                self._challenge_states[scene_key] = ChallengeState.ON
                self._challenge_done.add(scene_key)
                continue

            elif state == ChallengeState.UNKNOWN:
                print(f"[L1] {label}挑战状态为 UNKNOWN（未发现/模糊/低置信），零动作等待")
                self._challenge_states[scene_key] = ChallengeState.UNKNOWN
                # End this tick immediately, preventing downstream stage select or other inputs
                return LoopAction.Continue

            elif state == ChallengeState.OFF:
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

    def _handle_hero_mode_reputation(self, frame: Frame) -> bool:
        """开启并配置英雄模式（声望挑战）: 1:黑锋骑士团, 2:银色北伐军, 3:肯瑞托, 4:探险者协会, 5:元素领主, 6:守护巨龙"""
        hero_btn = self.find(frame, ["toHero", "HeroChallenge"], threshold=0.70)
        if not hero_btn:
            x = int(frame.width * 0.79)
            y = int(frame.height * 0.94)
            hero_btn = MatchResult(
                name="hero_mode_fallback",
                score=0.0,
                x=x, y=y, w=0, h=0,
                screen_x=frame.left + x,
                screen_y=frame.top + y
            )

        cancel_btn = self.find(frame, ["cancelChallenge", "quxiao"], threshold=0.70)
        confirm_btn = self.find(frame, ["startChallenge", "kaishiChallenge"], threshold=0.70)

        if not (cancel_btn or confirm_btn):
            print(f"[L0] 点击右下角【英雄模式】按钮 @ {hero_btn.center}")
            self.act_click(hero_btn, "OpenHeroModeModal")
            time.sleep(0.6)
            return False

        rep_type = max(1, min(6, getattr(self.settings, "reputation_type", 1)))
        rep_level = max(1, min(10, getattr(self.settings, "reputation_level", 1)))

        names_map = {
            1: "黑锋骑士团",
            2: "银色北伐军",
            3: "肯瑞托",
            4: "探险者协会",
            5: "元素领主",
            6: "守护巨龙"
        }
        rep_name = names_map.get(rep_type, "黑锋骑士团")
        print(f"[L0] 英雄模式配置：选择声望【{rep_name}】(序号{rep_type})，难度【{rep_level}级】")

        card_coords = {
            1: (0.17, 0.20),
            2: (0.33, 0.20),
            3: (0.49, 0.20),
            4: (0.65, 0.20),
            5: (0.17, 0.60),
            6: (0.33, 0.60),
        }

        zero_x_map = {1: 0.09, 2: 0.25, 3: 0.41, 4: 0.57, 5: 0.09, 6: 0.25}
        plus_x_map = {1: 0.18, 2: 0.34, 3: 0.50, 4: 0.66, 5: 0.18, 6: 0.34}

        cx, cy = card_coords[rep_type]
        self.act_click(MatchResult("rep_card", 0.0, int(frame.width*cx), int(frame.height*cy), 0, 0, frame.left + int(frame.width*cx), frame.top + int(frame.height*cy)), f"SelectReputation-{rep_name}")
        time.sleep(0.25)

        zx = zero_x_map[rep_type]
        zy = 0.34 if rep_type <= 4 else 0.74
        self.act_click(MatchResult("rep_zero", 0.0, int(frame.width*zx), int(frame.height*zy), 0, 0, frame.left + int(frame.width*zx), frame.top + int(frame.height*zy)), "ReputationLevelZero")
        time.sleep(0.2)

        px = plus_x_map[rep_type]
        py = zy
        for i in range(rep_level):
            self.act_click(MatchResult("rep_plus", 0.0, int(frame.width*px), int(frame.height*py), 0, 0, frame.left + int(frame.width*px), frame.top + int(frame.height*py)), f"ReputationLevelPlus-{i+1}")
            time.sleep(0.12)

        start_x = int(frame.width * 0.41)
        start_y = int(frame.height * 0.95)
        click_start = MatchResult("rep_start_challenge", 0.0, start_x, start_y, 0, 0, frame.left + start_x, frame.top + start_y)
        print(f"[L0] 点击【开启挑战】英雄模式声望挑战 @ {click_start.center}")
        return self.act_click(click_start, "StartHeroModeChallenge")

    # ---------- 阶段推进 ----------

    def set_phase(self, phase: Phase, note: str = "") -> None:
        if phase != self.phase:
            print(f"[med] phase {self.phase.name} → {phase.name} {note}")
        if phase in (Phase.LOBBY_ROOM, Phase.PLATFORM_MAP) and self.phase not in (Phase.LOBBY_ROOM, Phase.PLATFORM_MAP):
            self._stage_selected = False
            self._room_dialog_filled = False
        if phase in (Phase.PLATFORM_MAP, Phase.CREATE_ROOM):
            self._room_action_deadline = time.time() + self.settings.query_timeout
        if phase == Phase.CREATE_ROOM:
            self._room_dialog_filled = False
        if phase in (Phase.ROOM_STARTING, Phase.STAGE_STARTING):
            self._room_action_deadline = time.time() + self.settings.query_timeout
            self._room_action_attempts = 0
        if phase == Phase.STAGE_SELECT:
            self._stage_scroll_attempts = 0
            self._room_action_deadline = time.time() + self.settings.query_timeout
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
            self._challenge_done.clear()
            self._challenge_attempts.clear()
            self._challenge_states = {
                "coin_challenge": ChallengeState.PENDING,
                "wood_challenge": ChallengeState.PENDING,
                "experience_challenge": ChallengeState.PENDING,
                "treasure_challenge": ChallengeState.PENDING,
            }
            self._auto_task_done = False
            self._auto_task_attempts = 0
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
        context = self._detect_context(frame, "l0")
        print(f"[med] decision context={context} phase={self.phase.name}")
        if context in ("MAIN_LINE", "IN_GAME"):
            print("[L1] 开始主线 / phase=MAIN_LINE")
            self.set_phase(Phase.MAIN_LINE, "already in game")
            return LoopAction.Continue
        room_start = self._find_room_start(frame)
        stage_page = False if room_start else self._find_stage_page(frame)

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
            now = time.time()
            if not self._stage_selected:
                target = self._find_stage_target(frame)
                if not target:
                    if self.settings.stage_targets and self._stage_scroll_attempts < 3:
                        x, y = stage_list_scroll_point(frame)
                        target_hwnd = self._last_frame.hwnd if self._last_frame else None
                        res_scroll = self.executor.scroll(x, y, 5, target_hwnd=target_hwnd, dry_run=self.settings.dry_run)
                        if res_scroll.success:
                            self._stage_scroll_attempts += 1
                            print(f"[L0] 目标关卡不在当前列表，滚动寻找 ({self._stage_scroll_attempts}/3)")
                        else:
                            print(f"[L0] 关卡列表滚动取消/失败: {res_scroll.message}")
                    else:
                        print("[L0] 未找到配置目标关卡，拒绝点击任意可见关卡")
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
                self._stage_click_cooldown_until = now + 1.5
                return LoopAction.Continue
            if now < self._stage_click_cooldown_until:
                print("[L0] 等待关卡选中状态稳定…")
                return LoopAction.Continue
            target_spec = self.settings.stage_targets[0] if self.settings.stage_targets else self.settings.stage1
            if not verify_stage_selection(frame, target=target_spec, images_dir=self.images):
                print("[L0] 关卡选中态未通过验证，等待或重新选关")
                if self._action_timed_out():
                    self._stage_selected = False
                return LoopAction.Continue
            if self.settings.auto_reputation:
                if not self._handle_hero_mode_reputation(frame):
                    return LoopAction.Continue
                self._room_action_attempts = 1
                self._room_action_deadline = time.time() + min(self.settings.query_timeout, 15)
                self.set_phase(Phase.STAGE_STARTING, "hero mode reputation challenge clicked")
                return LoopAction.Continue
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
            if self.find_scene(frame, "card_panel") or self.find_scene(frame, "skill_panel"):
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
            print(f"[med] Frame health check failed ({health.details}), skipping decision and input")
            now = time.time()
            self._missing_window_since = self._missing_window_since or now
            elapsed = now - self._missing_window_since
            print(f"[med] Unhealthy frame ({health.details}), waiting {elapsed:.1f}s phase={self.phase.name}")
            in_game_phases = {Phase.MAIN_LINE, Phase.EARLY_CHALLENGE, Phase.ANCHOR_BOSS, Phase.LONGZHU}
            if self.phase == Phase.ROOM_STARTING:
                pass  # Use normal retry deadline
            elif self.phase in in_game_phases:
                if elapsed >= 60:
                    print("[med] 局内阶段不健康帧持续超过 60s，停止运行")
                    self.set_phase(Phase.ERROR, "unhealthy frame timeout")
                    self.stop()
                    return LoopAction.Break
            elif elapsed >= min(self.settings.query_timeout, 15):
                self.set_phase(Phase.ERROR, "unhealthy frame timeout")
                self.stop()
                return LoopAction.Break
            return LoopAction.Continue

        self._missing_window_since = None

        # 全局：断线/失败优先
        if self.find_scene(frame, "disconnect") or self.find_scene(frame, "fail"):
            self.set_phase(Phase.QUIT, "fail/disconnect")
            self.click_scene(frame, "fail", "recover")
            self.click_scene(frame, "ok", "ok")
            self.click_scene(frame, "close", "close")
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
        if self._selection_anchor(frame):
            if now < self._selection_click_cooldown_until:
                print("[L1] 选择面板等待点击结果…")
                return LoopAction.Continue
            choice = self._find_reward_choice(frame)
            if choice:
                kind, hit = choice
                print(f"[L1] {kind}选择 {hit.name} score={hit.score:.3f} @ {hit.center}")
                if self.act_click(hit, f"{kind}选择"):
                    self._selection_click_cooldown_until = now + 1.5
                self._main_line_since = now
                return LoopAction.Continue
            print("[L1] 发现选择面板但没有安全选项，保持等待")
            return LoopAction.Continue

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

        if self.phase in (Phase.QUIT, Phase.NEXT):
            self.click_scene(frame, "close", "QuitGame")
            self.click_scene(frame, "ok", "QuitGame-ok")
            if self.settings.auto_secret_realm:
                print("[med] 当前版本大秘境未完成前置校验，拒绝自动执行")
            self.game_count += 1
            print(f"[med] 局结束 count={self.game_count} → 下一局")
            self.set_phase(Phase.PREPARE, "next")
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

