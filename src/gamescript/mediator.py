"""
中介层：串起 Settings / 场景表 / 截屏找图 / 键鼠 / 阶段状态机。

对齐实机日志（SUCCESS_FLOW.md）：
  环境 → 准备 → 等进入UI → 主线 → 选卡循环
  → 提前挑战 → 锚点Boss → 龙珠 → 退出 → 下一局

Jobs 不直接碰 OpenCV/输入；只通过本中介 see / act。
"""

from __future__ import annotations

import time
from enum import Enum, auto
from pathlib import Path

import cv2

from gamescript.input.keyboard_mouse import click, hotkey, paste_text, press_key, scroll
from gamescript.loop_action import LoopAction
from gamescript.scenes import load_scenes, scene_templates
from gamescript.settings import Settings
from gamescript.vision.capture import (
    Frame,
    L0_WINDOW_KEYWORDS,
    L1_WINDOW_KEYWORDS,
    activate_window,
    capture,
    capture_target,
    find_window_targets,
)
from gamescript.vision.matcher import (
    MatchResult,
    find_blue_button,
    find_blue_buttons,
    find_input_boxes,
    match_all,
    match_any,
)
from gamescript.vision.stage_selector import (
    find_stage_in_range,
    find_stage_labels,
    stage_list_scroll_point,
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


class Mediator:
    def __init__(self, settings: Settings, project_root: Path):
        self.settings = settings
        self.root = project_root
        self.images = settings.images_path(project_root)
        self.scenes_doc = load_scenes(project_root)
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

    def _detect_context(self, frame: Frame, role: str | None = None) -> str:
        """Classify the visible page before taking a state-machine action."""
        if self._context_cache_frame is frame and self._context_cache_role == role:
            return self._context_cache_value

        # L0 does not need to scan the whole card/skill library.  L1 starts
        # with the in-game anchors, then checks the numbered stage list.
        if role != "l0" and (
            self.find_scene(frame, "card_panel") or self.find_scene(frame, "skill_panel")
        ):
            value = "IN_GAME"
        elif role == "l1":
            value = "STAGE_SELECT" if self._find_stage_page(frame) else "UNKNOWN"
        elif self._find_room_start(frame):
            value = "ROOM_WAITING"
        elif self._find_stage_page(frame):
            value = "STAGE_SELECT"
        elif self._find_create_confirm(frame):
            value = "CREATE_ROOM"
        elif self._auto_room_enabled() and self._find_map_create_room(frame):
            value = "PLATFORM_MAP"
        elif role == "l0" and (
            self.find_scene(frame, "card_panel") or self.find_scene(frame, "skill_panel")
        ):
            value = "IN_GAME"
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
        if not self._focus_last_window():
            return False
        click(
            hit.screen_x,
            hit.screen_y,
            dry_run=self.settings.dry_run,
            delay_ms=self.settings.click_delay_ms,
        )
        return True

    def act_key(self, key: str, reason: str = "") -> bool:
        print(f"[med] key {key!r} ({reason})")
        if not self._focus_last_window():
            return False
        press_key(key, dry_run=self.settings.dry_run)
        return True

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
        """Find the bottom ``暂时隐藏`` anchor of a reward-choice panel.

        The old ``skill_panel`` scene also contains refresh counters which
        are always visible in combat.  Only the central hide button is a
        safe signal that a selectable panel is actually open.
        """
        threshold = max(0.80, self.settings.match_threshold)
        hit = self.find(
            frame,
            ["skill_hide", "card_hide", "hide"],
            threshold=threshold,
            scales=(0.9, 1.0, 1.1, 1.15, 1.2),
        )
        if not hit:
            return None
        if hit.x < frame.width * 0.25 or hit.x > frame.width * 0.70:
            return None
        if hit.y < frame.height * 0.62:
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
            "threshold": max(0.82, self.settings.match_threshold),
            "roi": self._selection_roi(),
            "max_results": 12,
        }
        hits = match_all(frame, self.images, names, scales=(1.0,), **kwargs)
        if hits:
            return hits
        return match_all(frame, self.images, names, scales=(0.9, 1.1, 1.15), **kwargs)

    @staticmethod
    def _preferred_choice(hits: list[MatchResult], preferred: list[str]) -> MatchResult | None:
        wanted = {Path(value).stem for value in preferred if value}
        return next((hit for hit in hits if hit.name in wanted), None)

    def _generic_choice_slot(self, frame: Frame, index: int = 0) -> MatchResult | None:
        """Return a conservative slot center when a panel has no item asset.

        Treasure icons are not present in the recovered image pack.  The game
        still uses the fixed three-card layout, so this fallback is only
        allowed after ``_selection_anchor`` proves that the modal is open.
        """
        if frame.width < 800 or frame.height < 500 or not 0 <= index <= 2:
            return None
        x = int(frame.width * (0.355 + index * 0.145))
        y = int(frame.height * 0.42)
        return MatchResult(
            name=f"choice_slot_{index + 1}",
            score=0.0,
            x=x,
            y=y,
            w=0,
            h=0,
            screen_x=frame.left + x,
            screen_y=frame.top + y,
        )

    def _find_reward_choice(self, frame: Frame) -> tuple[str, MatchResult] | None:
        if not self._selection_anchor(frame):
            return None

        skills = self._choice_hits(frame, "skills", self.settings.skills)
        if skills:
            hit = self._preferred_choice(skills, self.settings.skills) or skills[0]
            return "技能", hit

        cards = self._choice_hits(frame, "cards", self.settings.cards)
        if cards and self.settings.auto_card:
            hit = self._preferred_choice(cards, self.settings.cards) or cards[0]
            return "羁绊", hit

        # No treasure image set was recovered from the original package.  A
        # verified three-card modal is safer than clicking refresh/hide, so
        # choose its first card and leave a grep-able diagnostic line.
        hit = self._generic_choice_slot(frame)
        return ("宝物/未标注奖励", hit) if hit else None

    def _find_challenge_button(self, frame: Frame, scene_key: str) -> tuple[MatchResult, MatchResult] | None:
        """Return (label hit, icon click hit) for one bottom challenge toggle."""
        label = self.find_scene(frame, scene_key)
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
    def _challenge_is_auto(frame: Frame, label: MatchResult) -> bool:
        x1 = max(0, label.x - 12)
        x2 = min(frame.width, label.x + label.w + 12)
        y1 = max(0, label.y - 74)
        y2 = max(y1, min(frame.height, label.y - 42))
        roi = frame.bgr[y1:y2, x1:x2]
        if roi.size == 0:
            return False
        b, g, r = cv2.split(roi)
        green = (g > 100) & (g > r + 25) & (g > b + 10)
        return int(green.sum()) >= 8

    def _ensure_challenge_buttons(self, frame: Frame) -> bool:
        for scene_key, label in (
            ("coin_challenge", "金币"),
            ("wood_challenge", "木材"),
            ("experience_challenge", "经验"),
            ("treasure_challenge", "宝物"),
        ):
            if scene_key in self._challenge_done:
                continue
            found = self._find_challenge_button(frame, scene_key)
            if not found:
                continue
            label_hit, click_hit = found
            if self._challenge_is_auto(frame, label_hit):
                print(f"[L1] {label}挑战已是自动模式")
                self._challenge_done.add(scene_key)
                continue
            print(f"[L1] 开启{label}挑战 {click_hit.center}")
            if self.act_click(click_hit, f"{label}Challenge"):
                self._challenge_done.add(scene_key)
                return True
        return False

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
        names = [name for name in self.templates("stage_page") if Path(name).stem != "stage"]
        hit = self.find(frame, names, scales=(0.9, 1.0, 1.1, 1.15, 1.2))
        # stage.png is the large map card; it is not sufficient to prove that
        # the numbered stage list is open.
        return bool(
            hit
            and hit.name != "stage"
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
        for box, value in zip(boxes[:2], values):
            if not self.act_click(box, "CreateRoom-focus-input"):
                return False
            hotkey("ctrl", "a", dry_run=self.settings.dry_run)
            paste_text(value, dry_run=self.settings.dry_run)
        print("[L0] 建房弹窗已填写房间名/密码")
        return True

    def _action_timed_out(self) -> bool:
        return self._room_action_deadline is not None and time.time() >= self._room_action_deadline

    def _tick_l0(self, frame: Frame) -> LoopAction:
        """Handle map → create dialog → room → stage without guessing clicks."""
        context = self._detect_context(frame, "l0")
        print(f"[med] decision context={context} phase={self.phase.name}")
        if context == "IN_GAME":
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
                        if not self._focus_last_window():
                            return LoopAction.Continue
                        scroll(x, y, 5, dry_run=self.settings.dry_run)
                        self._stage_scroll_attempts += 1
                        print(f"[L0] 目标关卡不在当前列表，滚动寻找 ({self._stage_scroll_attempts}/3)")
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

    def tick(self) -> LoopAction:
        """单步：一帧截屏 → 按阶段决策 → 执行。"""
        frame = self.see("tick")

        if frame.hwnd is None and not frame.window_title:
            now = time.time()
            self._missing_window_since = self._missing_window_since or now
            elapsed = now - self._missing_window_since
            print(f"[med] 未找到目标窗口，等待 {elapsed:.1f}s phase={self.phase.name}")
            # After clicking room start the game window can take a few
            # seconds to appear.  Let ROOM_STARTING use its normal retry
            # deadline.  In-game phases get a longer tolerance (60s) since
            # the game may be briefly minimized or obscured by system popups.
            # L0 phases fail closed after 15s to avoid looping on a black frame.
            in_game_phases = {Phase.MAIN_LINE, Phase.EARLY_CHALLENGE, Phase.ANCHOR_BOSS, Phase.LONGZHU}
            if self.phase == Phase.ROOM_STARTING:
                pass  # Use normal retry deadline
            elif self.phase in in_game_phases:
                if elapsed >= 60:
                    print("[med] 局内阶段窗口消失超过 60s，停止运行")
                    self.set_phase(Phase.ERROR, "game window disappeared")
                    self.stop()
                    return LoopAction.Break
            elif elapsed >= min(self.settings.query_timeout, 15):
                self.set_phase(Phase.ERROR, "target window unavailable")
                self.stop()
                return LoopAction.Break
        else:
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

        # 挑战按钮有自己的模板和自动状态检测，避免固定坐标反复切换开关。
        if self._ensure_challenge_buttons(frame):
            self._main_line_since = now
            return LoopAction.Continue

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

        # 提前挑战 / Boss / 龙珠入口。
        if self.find_scene(frame, "archive"):
            print("[med] 提前挑战/无需发育")
            self.set_phase(Phase.ANCHOR_BOSS, "early challenge")
            return LoopAction.Continue
        if self.find_scene(frame, "longzhu"):
            self.set_phase(Phase.LONGZHU, "see longzhu")
            return LoopAction.Continue
        if self.find_scene(frame, "boss_entry"):
            self.set_phase(Phase.ANCHOR_BOSS, "see boss")
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
        if self.phase == Phase.EARLY_CHALLENGE:
            self.set_phase(Phase.ANCHOR_BOSS)
            return LoopAction.Continue

        if self.phase == Phase.ANCHOR_BOSS:
            bosses: list[str] = []
            for boss in (self.settings.cjb_boss, self.settings.sgzx_boss):
                if boss:
                    bosses.extend([boss, f"boss/{boss}", f"chuanjiaobao/{boss}"])
            hit = self.find(frame, bosses) if bosses else None
            if hit:
                print(f"[med] 锚点BOSS名称为{hit.name}")
                if self.act_click(hit, "找到锚点Boss了"):
                    self._boss_clicked = True
                return LoopAction.Continue
            if self.click_scene(frame, "boss_entry", "boss_entry"):
                self._boss_clicked = True
                return LoopAction.Continue
            if self._boss_clicked:
                print(f"[med] Boss 已处理，开始查找龙珠{self.settings.dragon_ball_count}")
            else:
                print("[med] 锚点 Boss 未命中，直接进入龙珠阶段")
            self._boss_clicked = False
            self.set_phase(Phase.LONGZHU)
            return LoopAction.Continue

        if self.phase == Phase.LONGZHU:
            if self.longzhu_timed_out():
                print("[med] 龙珠阶段超时 → 退出")
                self.set_phase(Phase.QUIT)
                return LoopAction.Continue
            left = int(self._longzhu_deadline - time.time()) if self._longzhu_deadline else 0
            if left >= 0 and left % 30 == 0:
                print(f"[med] 退出游戏时间还剩下{left}秒；找龙珠，需要判断是否有战斗画面")
            if self.click_scene(frame, "longzhu", "longzhu"):
                return LoopAction.Continue
            if self.click_scene(frame, "card_panel", "longzhu-card"):
                return LoopAction.Continue
            if not self._f1_fallback_done:
                self.act_key("f1", "龙珠阶段 F1")
                self._f1_fallback_done = True
            return LoopAction.Continue

        if self.phase in (Phase.QUIT, Phase.NEXT):
            self.click_scene(frame, "close", "QuitGame")
            self.click_scene(frame, "ok", "QuitGame-ok")
            if self.settings.auto_secret_realm:
                self.click_scene(frame, "secret", "AutoSecretRealm")
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
        while self._running:
            action = self.tick()
            steps += 1
            if action == LoopAction.Break:
                break
            if max_steps is not None and steps >= max_steps:
                print(f"[med] max_steps={max_steps}")
                break
            time.sleep(self.settings.loop_sleep_ms / 1000.0)
        print(f"[med] end steps={steps} games={self.game_count}")

