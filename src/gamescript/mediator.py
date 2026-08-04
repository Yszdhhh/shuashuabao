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

from gamescript.input.keyboard_mouse import click, press_key
from gamescript.loop_action import LoopAction
from gamescript.scenes import load_scenes, priority_keys, scene_templates
from gamescript.settings import Settings
from gamescript.vision.capture import Frame, capture, L0_WINDOW_KEYWORDS, L1_WINDOW_KEYWORDS
from gamescript.vision.matcher import MatchResult, match_any


class Phase(Enum):
    """与官方日志阶段大致对应。"""

    BOOT = auto()  # 验证环境
    WAIT_EXIT = auto()  # 等待所有人退出
    LOBBY_ROOM = auto()  # L0 大厅/房间态
    PREPARE = auto()  # 开始/准备游戏
    WAIT_UI = auto()  # 等待进入游戏UI
    MAIN_LINE = auto()  # 开始主线 / 选卡
    EARLY_CHALLENGE = auto()  # 提前挑战
    ANCHOR_BOSS = auto()  # 锚点 Boss
    LONGZHU = auto()  # 找龙珠
    QUIT = auto()  # 退出
    NEXT = auto()  # 下一局


# 场景 key → 优先阶段（命中时切换/执行）
_SCENE_PHASE = {
    "disconnect": Phase.QUIT,
    "fail": Phase.QUIT,
    "lobby_start": Phase.LOBBY_ROOM,
    "lobby_room": Phase.LOBBY_ROOM,
    "start": Phase.LOBBY_ROOM,
    "stage": Phase.WAIT_UI,
    "card_panel": Phase.MAIN_LINE,
    "skill_panel": Phase.MAIN_LINE,
    "treasure": Phase.MAIN_LINE,
    "wood": Phase.MAIN_LINE,
    "longzhu": Phase.LONGZHU,
    "secret": Phase.QUIT,
    "boss_entry": Phase.ANCHOR_BOSS,
    "archive": Phase.MAIN_LINE,
    "ok": Phase.MAIN_LINE,
    "close": Phase.QUIT,
    "pause": Phase.MAIN_LINE,
}


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

    # ---------- 感知 / 执行（Jobs 唯一入口）----------

    def _capture_title(self) -> str:
        """根据当前阶段返回截屏目标窗口关键字。
        L0（BOOT/LOBBY_ROOM/PREPARE）→ KK对战平台房间窗口
        L1（WAIT_UI 及之后）→ 英雄三国游戏窗口
        """
        user_title = self.settings.window_title_contains
        if self.phase in (Phase.BOOT, Phase.WAIT_EXIT, Phase.LOBBY_ROOM, Phase.PREPARE):
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

    def see(self, reason: str = "") -> Frame:
        title = self._capture_title()
        frame = capture(title)
        print(
            f"[med] capture {reason or '-'} "
            f"{frame.width}x{frame.height} @({frame.left},{frame.top}) "
            f"phase={self.phase.name} target='{title}'"
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
        # 官方截图常见 1600x900；窗口/系统缩放会让当前帧达到 1936x1066。
        # 只对 L0 门闩和选关标识做多尺度，避免卡牌/技能全库扫描变慢。
        scales = (0.9, 1.0, 1.1, 1.15, 1.2) if scene_key in {"lobby_start", "lobby_room", "start", "stage"} else (1.0,)
        return self.find(frame, self.templates(scene_key), threshold=threshold, scales=scales)

    def act_click(self, hit: MatchResult, reason: str = "") -> None:
        print(f"[med] click {hit.name} score={hit.score:.3f} @ {hit.center} ({reason})")
        click(
            hit.screen_x,
            hit.screen_y,
            dry_run=self.settings.dry_run,
            delay_ms=self.settings.click_delay_ms,
        )

    def act_key(self, key: str, reason: str = "") -> None:
        print(f"[med] key {key!r} ({reason})")
        press_key(key, dry_run=self.settings.dry_run)

    def click_scene(self, frame: Frame, scene_key: str, reason: str = "", threshold: float | None = None) -> bool:
        hit = self.find_scene(frame, scene_key, threshold=threshold)
        if not hit:
            print(f"[med] miss scene={scene_key} th={threshold or self.settings.match_threshold} ({reason})")
            return False
        self.act_click(hit, reason or scene_key)
        return True

    # ---------- 阶段推进 ----------

    def set_phase(self, phase: Phase, note: str = "") -> None:
        if phase != self.phase:
            print(f"[med] phase {self.phase.name} → {phase.name} {note}")
        self.phase = phase
        if phase == Phase.WAIT_UI:
            self._wait_ui_since = time.time()
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

    # ---------- 主循环（中介调度）----------

    def stop(self) -> None:
        self._running = False

    def tick(self) -> LoopAction:
        """单步：一帧截屏 → 按阶段决策 → 执行。"""
        frame = self.see("tick")

        # 全局：断线/失败优先
        if self.find_scene(frame, "disconnect") or self.find_scene(frame, "fail"):
            self.set_phase(Phase.QUIT, "fail/disconnect")
            self.click_scene(frame, "fail", "recover")
            self.click_scene(frame, "ok", "ok")
            self.click_scene(frame, "close", "close")
            return LoopAction.Continue

        # 按 scenes priority 扫一帧，更新阶段线索
        for key in priority_keys(self.scenes_doc):
            if key in ("rarity", "quality", "env_anchor", "wave_markers"):
                continue
            hit = self.find_scene(frame, key)
            if not hit:
                continue
            ph = _SCENE_PHASE.get(key)
            if ph and self.phase in (Phase.BOOT, Phase.WAIT_EXIT, Phase.LOBBY_ROOM, Phase.PREPARE, Phase.WAIT_UI):
                if key == "stage":
                    self.set_phase(Phase.WAIT_UI, "see stage")
                elif key == "card_panel":
                    self.set_phase(Phase.MAIN_LINE, "see cards")
                elif key in ("lobby_start", "lobby_room", "start") and self.phase not in (Phase.WAIT_UI, Phase.MAIN_LINE):
                    self.set_phase(Phase.LOBBY_ROOM, "see lobby start")
            break

        # 阶段行为
        if self.phase in (Phase.BOOT, Phase.WAIT_EXIT, Phase.LOBBY_ROOM, Phase.PREPARE):
            if self.phase in (Phase.BOOT, Phase.WAIT_EXIT):
                self.set_phase(Phase.LOBBY_ROOM, "init L0 lobby")

            print(f"[L0] phase=LOBBY_ROOM")

            # 1. 已在选关页或已在局内（游戏已成功进入）
            if self.find_scene(frame, "stage"):
                print("[L0] see stage → WAIT_UI")
                self.set_phase(Phase.WAIT_UI, "already stage")
                return LoopAction.Continue
            if self.find_scene(frame, "card_panel") or self.find_scene(frame, "skill_panel"):
                print("[L1] 开始主线 / phase=MAIN_LINE (already in game)")
                self.set_phase(Phase.MAIN_LINE, "already in game")
                return LoopAction.Continue

            # 2. 尝试标准阈值匹配 L0 大厅/房间开始按钮 (lobby_start / start)
            hit = self.find_scene(frame, "lobby_start") or self.find_scene(frame, "start")
            if hit:
                print(f"[L0] match {hit.name} score={hit.score:.3f} @ {hit.center}")
                print(f"[L0] click start")
                self.act_click(hit, "[L0] lobby start click")
                print("[L0] → WAIT_UI")
                self.set_phase(Phase.WAIT_UI, "clicked lobby start")
                return LoopAction.Continue

            # 3. 尝试低阈值 (0.65) 匹配房间开始按钮
            hit_low = self.find_scene(frame, "lobby_start", threshold=0.65) or self.find_scene(frame, "start", threshold=0.65)
            if hit_low:
                print(f"[L0] match {hit_low.name} score={hit_low.score:.3f} @ {hit_low.center} (lowThresh)")
                print(f"[L0] click start (lowThresh)")
                self.act_click(hit_low, "[L0] lobby start click (lowThresh)")
                print("[L0] → WAIT_UI")
                self.set_phase(Phase.WAIT_UI, "clicked lobby start lowThresh")
                return LoopAction.Continue

            # 4. EntryF1 快捷键尝试，但保持在 LOBBY_ROOM 持续匹配，直到识别到 stage / card_panel
            print(f"[L0] EntryF1 按键尝试 (target='{self._capture_title()}')")
            self.act_key("f1", "EntryF1-F1热键")
            self.click_scene(frame, "close", "clear dialog")
            self.click_scene(frame, "ok", "clear dialog")
            return LoopAction.Continue

        if self.phase == Phase.WAIT_UI:
            # 1. 若画面已呈现局内选卡/技能面板，说明实际上已进入局内
            if self.find_scene(frame, "card_panel") or self.find_scene(frame, "skill_panel"):
                print("[L1] 开始主线 / phase=MAIN_LINE")
                self.set_phase(Phase.MAIN_LINE, "开始主线(in-panel)")
                return LoopAction.Continue

            # 2. 定位并点击关卡/主线 SelectStage 按钮
            hit_stage = None
            if time.time() >= self._stage_click_cooldown_until:
                hit_stage = self.find_scene(frame, "stage") or self.find_scene(frame, "stage", threshold=0.70)
            if hit_stage:
                print(f"[L0] 选关 SelectStage {hit_stage.name} score={hit_stage.score:.3f} @ {hit_stage.center}")
                self.act_click(hit_stage, "SelectStage")
                self._stage_click_cooldown_until = time.time() + 2.0
                return LoopAction.Continue

            # 3. 不在 WAIT_UI 盲点大厅按钮；点击失败交给超时后的 LOBBY_ROOM 重试。

            if self.wait_ui_timed_out():
                print("[L0] WAIT_UI timeout → 回退到 LOBBY_ROOM 重试")
                self.set_phase(Phase.LOBBY_ROOM, "soft fail timeout")
                self._wait_ui_since = None
            else:
                print("[L0] 等待进入游戏UI…")
            return LoopAction.Continue

        if self.phase == Phase.MAIN_LINE:
            # 选卡 / 技能
            if self.click_scene(frame, "card_panel", "卡都找完了?"):
                print("[med] 卡面板处理")
                return LoopAction.Continue
            if self.click_scene(frame, "skill_panel", "skill"):
                # 集火类找不到时 F1（对齐日志）
                if not self._f1_fallback_done:
                    self.act_key("f1", "未找到集火，点击F1")
                    self._f1_fallback_done = True
                return LoopAction.Continue
            # 关卡选关：若局内呈现关卡选关 UI，点击 SelectStage 推进
            hit_stage = None
            if time.time() >= self._stage_click_cooldown_until:
                hit_stage = self.find_scene(frame, "stage")
            if hit_stage:
                print(f"[L1] 局内选关 SelectStage {hit_stage.name} score={hit_stage.score:.3f} @ {hit_stage.center}")
                self.act_click(hit_stage, "SelectStage-InGame")
                self._stage_click_cooldown_until = time.time() + 2.0
                return LoopAction.Continue
            # 提前挑战：有 archive 节点则跳过发育
            if self.find_scene(frame, "archive"):
                if self.settings.develop_time == 0 or self.find_scene(frame, "archive"):
                    print("[med] 提前挑战/无需发育")
                    self.set_phase(Phase.ANCHOR_BOSS, "early challenge")
                    return LoopAction.Continue
            if self.find_scene(frame, "longzhu"):
                self.set_phase(Phase.LONGZHU, "see longzhu")
                return LoopAction.Continue
            if self.find_scene(frame, "boss_entry"):
                self.set_phase(Phase.ANCHOR_BOSS, "see boss")
                return LoopAction.Continue
            print("[med] 主线 idle（选卡循环中）")
            return LoopAction.Continue

        if self.phase == Phase.EARLY_CHALLENGE:
            self.set_phase(Phase.ANCHOR_BOSS)
            return LoopAction.Continue

        if self.phase == Phase.ANCHOR_BOSS:
            bosses = []
            for b in (self.settings.cjb_boss, self.settings.sgzx_boss):
                if b:
                    bosses.extend([b, f"boss/{b}", f"chuanjiaobao/{b}"])
            hit = self.find(frame, bosses) if bosses else None
            if hit:
                print(f"[med] 锚点BOSS名称为{hit.name}")
                self.act_click(hit, "找到锚点Boss了")
                self._boss_clicked = True
                return LoopAction.Continue
            if self.click_scene(frame, "boss_entry", "boss_entry"):
                self._boss_clicked = True
                return LoopAction.Continue
            # P1 Fix: Boss 已点击过或本 tick 找不到 → 进龙珠（不再无条件立即跳走）
            if self._boss_clicked:
                n = self.settings.dragon_ball_count
                print(f"[med] Boss 已处理，开始查找龙珠{n}")
                self._boss_clicked = False
                self.set_phase(Phase.LONGZHU)
            else:
                print("[med] 锚点 Boss 未命中，直接进入龙珠阶段")
                self.set_phase(Phase.LONGZHU)
            return LoopAction.Continue

        if self.phase == Phase.LONGZHU:
            if self.longzhu_timed_out():
                print("[med] 龙珠阶段超时 → 退出")
                self.set_phase(Phase.QUIT)
                return LoopAction.Continue
            left = int(self._longzhu_deadline - time.time()) if self._longzhu_deadline else 0
            if left % 30 == 0:
                print(f"[med] 退出游戏时间还剩下{left}秒；找龙珠，需要判断是否有战斗画面")
            if self.click_scene(frame, "longzhu", "longzhu"):
                return LoopAction.Continue
            # 战斗中仍可能弹卡
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
            f"stage={self.settings.stage1}/{self.settings.stage2} "
            f"threshold={self.settings.match_threshold} images={self.images}"
        )
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

