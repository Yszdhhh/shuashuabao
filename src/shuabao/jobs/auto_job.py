"""
对齐原 GameScript.Jobs.AutoJob。

legacy 模块：仅 dry-run/离线使用，真机输入一律走 InputExecutor 安全链。

场景表：config/scenes.json
每步只截屏一次，再按 priority 匹配。
"""

from __future__ import annotations

import time
from pathlib import Path

from shuabao.input.keyboard_mouse import click as _click, press_key as _press_key
from shuabao.loop_action import LoopAction
from shuabao.scenes import load_scenes, priority_keys, scene_templates
from shuabao.settings import Settings
from shuabao.vision.capture import capture
from shuabao.vision.matcher import MatchResult, match_any, match_one, resolve_template
from shuabao.vision.stage_selector import find_stage_in_range, find_stage_labels


class AutoJob:
    def __init__(self, settings: Settings, project_root: Path):
        self.settings = settings
        self.root = project_root
        self.images = settings.images_path(project_root)
        self.scenes_doc = load_scenes(project_root)
        self.game_count = 0
        self._running = False
        self._f4_done = False

    def stop(self) -> None:
        self._running = False

    def templates(self, key: str) -> list[str]:
        names = list(scene_templates(self.scenes_doc, key))
        sc = (self.scenes_doc.get("scenes") or {}).get(key) or {}
        if sc.get("prefer_settings_skills"):
            extra = list(self.settings.skills)
            names = extra + [f"skills/{s}" for s in extra] + names
        if sc.get("also_scan_dir") == "cards" and self.settings.cards:
            names = list(self.settings.cards) + [f"cards/{c}" for c in self.settings.cards] + names
        return names

    def capture_win(self, reason: str = ""):
        frame = capture(self.settings.window_title_contains)
        print(f"[capture] {reason or '-'} {frame.width}x{frame.height} @({frame.left},{frame.top})")
        return frame

    def _match_names(self, frame, names: list[str]) -> MatchResult | None:
        return match_any(frame, self.images, names, threshold=self.settings.match_threshold)

    def _click_hit(self, hit: MatchResult, reason: str) -> None:
        print(f"[auto] hit {hit.name} score={hit.score:.3f} @ {hit.center} ({reason})")
        _click(
            hit.screen_x,
            hit.screen_y,
            dry_run=self.settings.dry_run,
            delay_ms=self.settings.click_delay_ms,
        )

    def click_names(self, names: list[str], reason: str = "", frame=None) -> bool:
        if frame is None:
            frame = self.capture_win(reason)
        hit = self._match_names(frame, names)
        if not hit:
            print(f"[auto] miss {reason or names[:3]}")
            return False
        self._click_hit(hit, reason)
        return True

    def click_scene(self, key: str, reason: str | None = None, frame=None) -> bool:
        return self.click_names(self.templates(key), reason or key, frame=frame)

    def entry_f1(self, frame=None) -> LoopAction:
        self.click_scene("room_start", "EntryF1", frame=frame)
        return LoopAction.Continue

    def select_stage(self, frame=None) -> LoopAction:
        if frame is None:
            frame = self.capture_win("stage")
        hit = (
            find_stage_labels(frame, self.images, self.settings.stage_targets)
            if self.settings.stage_targets
            else find_stage_in_range(frame, self.images, self.settings.stage1, self.settings.stage2)
        )
        if hit:
            self._click_hit(hit, "SelectStage-target")
        else:
            print("[auto] miss configured stage target")
        return LoopAction.Continue

    def close_card_panel(self, frame=None) -> LoopAction:
        self.click_scene("card_panel", "CloseCardPanel", frame=frame)
        return LoopAction.Continue

    def close_skill_panel(self, frame=None) -> LoopAction:
        self.click_scene("skill_panel", "CloseSkillPanel", frame=frame)
        return LoopAction.Continue

    def click_ok_btn(self, frame=None) -> LoopAction:
        self.click_scene("ok", "ClickOKBtn", frame=frame)
        return LoopAction.Continue

    def change_main_line_status(self, frame=None) -> LoopAction:
        if self.settings.auto_close_main_line and not self._f4_done:
            if frame is None:
                frame = self.capture_win("wave")
            if self._match_names(frame, self.templates("wave_markers")):
                print("[auto] ChangeMainLineStatus: wave → F4")
                _press_key("f4", dry_run=self.settings.dry_run)
                self._f4_done = True
        return LoopAction.Continue

    def monitor_game_over(self, frame=None) -> LoopAction:
        if frame is None:
            frame = self.capture_win("over")
        if self._match_names(frame, self.templates("disconnect")):
            self.click_scene("disconnect", "MonitorGameOver/disconnect", frame=frame)
            return LoopAction.Continue
        if self._match_names(frame, self.templates("fail")):
            self.click_scene("fail", "MonitorGameOver/fail", frame=frame)
            self.click_scene("ok", "MonitorGameOver/ok", frame=frame)
            return LoopAction.Continue
        return LoopAction.Continue

    def quit_game(self, frame=None) -> LoopAction:
        self.game_count += 1
        self._f4_done = False
        print(f"[auto] QuitGame count={self.game_count}")
        self.click_scene("close", "QuitGame", frame=frame)
        if self.settings.auto_secret_realm:
            self.click_scene("secret", "AutoSecretRealm")
        n = self.settings.auto_clean_interval
        if n > 0 and self.game_count % n == 0:
            self.click_scene("clean", "AutoClean")
        return LoopAction.Continue

    def create_room(self) -> LoopAction:
        if self.settings.game_mode != 0 and (self.settings.room_name or self.settings.room_password):
            print(
                f"[auto] CreateRoom placeholder name={self.settings.room_name!r} "
                f"pwd={bool(self.settings.room_password)}"
            )
        return LoopAction.Continue

    def step(self) -> LoopAction:
        frame = self.capture_win("step")
        skip = {"rarity", "quality", "env_anchor", "wave_markers"}

        for key in priority_keys(self.scenes_doc):
            if key in skip:
                continue
            names = self.templates(key)
            hit = self._match_names(frame, names)
            if not hit:
                continue
            print(f"[auto] scene={key}")
            if key in ("disconnect", "fail"):
                return self.monitor_game_over(frame)
            if key == "pause":
                print("[auto] pauseGame (notify TODO)")
                return LoopAction.Continue
            if key == "ok":
                self._click_hit(hit, "ClickOKBtn")
                return LoopAction.Continue
            if key in ("room_start", "lobby_start", "start"):
                if self.settings.game_mode == 0:
                    self._click_hit(hit, "EntryF1")
                else:
                    print("[auto] start visible, game_mode!=0 skip click")
                return LoopAction.Continue
            if key == "stage_start":
                self._click_hit(hit, "StageStart")
                return LoopAction.Continue
            if key == "card_panel":
                self._click_hit(hit, "CloseCardPanel")
                return LoopAction.Continue
            if key == "skill_panel":
                self._click_hit(hit, "CloseSkillPanel")
                return LoopAction.Continue
            if key in ("stage", "stage_page"):
                self.select_stage(frame)
                return LoopAction.Continue
            if key in ("map_create_room", "create_room_confirm"):
                print("[auto] CreateRoom requires Mediator; use the non-legacy runner")
                return LoopAction.Continue
            if key in ("longzhu", "treasure", "wood", "secret", "archive", "clean", "boss_entry"):
                if key == "boss_entry":
                    bosses = [b for b in (self.settings.cjb_boss, self.settings.sgzx_boss) if b]
                    if bosses:
                        bh = self._match_names(frame, bosses)
                        if bh:
                            self._click_hit(bh, "BossConfigured")
                            return LoopAction.Continue
                self._click_hit(hit, key)
                return LoopAction.Continue
            if key == "close":
                return self.quit_game(frame)

        self.change_main_line_status(frame)
        print("[auto] idle")
        return LoopAction.Continue

    def run(self, max_steps: int | None = None) -> None:
        self._running = True
        steps = 0
        print(
            f"[auto] Run dry_run={self.settings.dry_run} images={self.images} "
            f"threshold={self.settings.match_threshold} mode={self.settings.game_mode}"
        )
        self.create_room()
        while self._running:
            action = self.step()
            steps += 1
            if action == LoopAction.Break:
                break
            if max_steps is not None and steps >= max_steps:
                print(f"[auto] max_steps={max_steps}")
                break
            time.sleep(self.settings.loop_sleep_ms / 1000.0)
        print(f"[auto] end steps={steps} games={self.game_count}")
