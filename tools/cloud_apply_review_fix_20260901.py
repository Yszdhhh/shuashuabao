from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"expected block not found in {path}: {old[:100]!r}")
    if text.count(old) != 1:
        raise RuntimeError(f"expected unique block in {path}, found {text.count(old)}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


# 1) UNKNOWN/frozen frames must never gain F1 authority.  The hero-focus
# recovery now requires a positively recognized in-game HUD, two distinct
# captures with the hero panel missing, and successful elevation gating.
replace_once(
    "src/shuabao/mediator.py",
    '''    def _maybe_ensure_hero_panel_focus(self, frame: Frame, now: float) -> LoopAction | None:\n        """局内常态（无中央选卡弹窗时）若右下角未检测到英雄技能/操作面板，按 F1 切回英雄。"""\n        if self._panel_state != PanelState.CLOSED:\n            return None\n        if getattr(self, "_post_game_pending", False):\n            return None\n        if now < getattr(self, "_hero_focus_next_check_at", 0.0):\n            return None\n\n        # 测试/离线回放不可抢占正常状态机；真机以管理员 SendInput 路径为准。\n        from shuabao.input.keyboard_mouse import is_current_process_elevated\n        if not is_current_process_elevated():\n            return None\n\n        self._hero_focus_next_check_at = now + 1.0\n        hero_indicators = ["jihuo", "shortKey", "hc", "artifact_slot_e", "pingfu1"]\n        hit = self.find(frame, hero_indicators, threshold=0.75, roi=(0.60, 0.60, 0.98, 0.98))\n        if hit is not None:\n            self._hero_focus_lost_count = 0\n            return None\n\n        self._hero_focus_lost_count = getattr(self, "_hero_focus_lost_count", 0) + 1\n        print(f"[med] 右下角未检测到英雄操作面板（计数 {self._hero_focus_lost_count}/2），发送 F1 切回英雄")\n        if not getattr(self.settings, "dry_run", False):\n            self.act_key("F1", "HeroFocusFallback")\n        self._hero_focus_next_check_at = now + 1.5\n        return LoopAction.Continue\n''',
    '''    def _maybe_ensure_hero_panel_focus(self, frame: Frame, now: float) -> LoopAction | None:\n        """Only recover hero focus from two distinct, positively identified HUD frames."""\n        if self._panel_state != PanelState.CLOSED:\n            return None\n        if getattr(self, "_post_game_pending", False):\n            return None\n        if now < getattr(self, "_hero_focus_next_check_at", 0.0):\n            return None\n\n        # UNKNOWN/transition/black frames have zero input authority.  This is\n        # deliberately checked before elevation and before the hero ROI: a\n        # missing hero indicator is not evidence that the current page is HUD.\n        if not self._is_in_game_hud(frame):\n            self._hero_focus_lost_count = 0\n            self._hero_focus_last_frame_id = None\n            return None\n\n        # Tests/offline replay cannot pre-empt the state machine; real input\n        # still goes through the administrator/UIPI SendInput guard.\n        from shuabao.input.keyboard_mouse import is_current_process_elevated\n        if not is_current_process_elevated():\n            return None\n\n        self._hero_focus_next_check_at = now + 1.0\n        hero_indicators = ["jihuo", "shortKey", "hc", "artifact_slot_e", "pingfu1"]\n        hit = self.find(frame, hero_indicators, threshold=0.75, roi=(0.60, 0.60, 0.98, 0.98))\n        if hit is not None:\n            self._hero_focus_lost_count = 0\n            self._hero_focus_last_frame_id = None\n            return None\n\n        frame_id = id(frame)\n        if frame_id == getattr(self, "_hero_focus_last_frame_id", None):\n            # capture() deliberately reuses the same Frame object for identical\n            # frozen content.  Never convert repeated ticks of that object into\n            # a two-frame authorization.\n            return None\n        self._hero_focus_last_frame_id = frame_id\n        self._hero_focus_lost_count = getattr(self, "_hero_focus_lost_count", 0) + 1\n        if self._hero_focus_lost_count < 2:\n            print("[med] 英雄面板缺失候选第 1 帧，等待不同 HUD 帧确认（零动作）")\n            return None\n\n        print("[med] 连续两个不同 HUD 帧均缺英雄面板，发送 F1 切回英雄")\n        if not getattr(self.settings, "dry_run", False):\n            self.act_key("F1", "HeroFocusFallback")\n        self._hero_focus_lost_count = 0\n        self._hero_focus_last_frame_id = None\n        self._hero_focus_next_check_at = now + 1.5\n        return LoopAction.Continue\n''',
)

# The unknown-panel branch previously sent an unanchored physical F1.  Keep
# its shadow evidence, but UNKNOWN itself is observation-only.
replace_once(
    "src/shuabao/mediator.py",
    '''            # 无候选：F1 兜底与 shadow 记录\n            if not self._panel_f1_used_this_episode:\n                self._panel_f1_used_this_episode = True\n                self._panel_f1_shadow_record(True, None)\n                # 当面板未被识别为合法选卡面板（例如无主类型/锚点异常），发送物理 F1 键切回英雄\n                if not getattr(self.settings, "dry_run", False) and self._panel_kind is None:\n                    self.act_key("F1", "PanelF1Fallback")\n                    print("[L1] F1 兜底：发送 F1 键切回英雄面板")\n''',
    '''            # 无候选：只记录 shadow。未分类面板属于 UNKNOWN，必须零输入；\n            # 不能用物理 F1 把“识别失败”变成点击/按键权限。\n            if not self._panel_f1_used_this_episode:\n                self._panel_f1_used_this_episode = True\n                self._panel_f1_shadow_record(True, None)\n                print("[L1] 未分类面板：记录 F1 shadow，保持零输入")\n''',
)

# 2) Archive/heirloom gates must be two distinct captures, not merely two
# event-loop ticks.  Identical captures are collapsed to the same Frame object
# by the capture layer, so `frame is _prev_frame` is the production freshness
# boundary and does not introduce another cross-layer FSM.
replace_once(
    "src/shuabao/mediator.py",
    '''        if post_game == "ARCHIVE_PANEL" and self._post_game_archive_pending_only:\n            self._pending_archive_panel_frames += 1\n            if self._pending_archive_panel_frames < 2:\n                print("[med] 存档面板仅有 pending+X 候选第 1 帧，等待连续证据（零动作）")\n                return LoopAction.Continue\n        else:\n            self._pending_archive_panel_frames = 0\n''',
    '''        if post_game == "ARCHIVE_PANEL" and self._post_game_archive_pending_only:\n            if frame is getattr(self, "_prev_frame", None):\n                print("[med] 存档 pending+X 捕获未变化，不计入第二帧（零动作）")\n                return LoopAction.Continue\n            self._pending_archive_panel_frames += 1\n            if self._pending_archive_panel_frames < 2:\n                print("[med] 存档面板仅有 pending+X 候选第 1 帧，等待不同捕获证据（零动作）")\n                return LoopAction.Continue\n        else:\n            self._pending_archive_panel_frames = 0\n''',
)
replace_once(
    "src/shuabao/mediator.py",
    '''        challenge_hud = awaiting_challenge_hud and self._is_in_game_hud(frame)\n        if challenge_hud:\n            self._post_game_hud_confirmations += 1\n            if self._post_game_hud_confirmations < 2:\n                print("[med] 战后挑战目的地 HUD 候选第 1 帧，等待连续证据（零动作）")\n                return LoopAction.Continue\n''',
    '''        challenge_hud = awaiting_challenge_hud and self._is_in_game_hud(frame)\n        if challenge_hud:\n            if frame is getattr(self, "_prev_frame", None):\n                print("[med] 战后挑战 HUD 捕获未变化，不计入第二帧（零动作）")\n                return LoopAction.Continue\n            self._post_game_hud_confirmations += 1\n            if self._post_game_hud_confirmations < 2:\n                print("[med] 战后挑战目的地 HUD 候选第 1 帧，等待不同捕获证据（零动作）")\n                return LoopAction.Continue\n''',
)

# 3) A legitimate L0 start must look for an L0 title, not reuse the configured
# L1 title (typically “英雄三国”) for the KK lobby.
replace_once(
    "src/shuabao/shell/dashboard_facade.py",
    '''        title = str(getattr(settings, "window_title_contains", "") or "英雄三国")\n        roles = ("l0",) if mode_id in {"follow_team", "lobby_hitch"} else ("l1", "l0")\n        targets = []\n        for role in roles:\n            targets.extend(find_window_targets(title, role=role, allow_fallback=False))\n''',
    '''        l1_title = str(getattr(settings, "window_title_contains", "") or "英雄三国")\n        roles = ("l0",) if mode_id in {"follow_team", "lobby_hitch"} else ("l1", "l0")\n        targets = []\n        for role in roles:\n            # Empty L0 query intentionally selects capture.py's verified KK\n            # fallback vocabulary and role scoring.  Reusing the L1 title here\n            # made a clean “KK lobby only” start fail preflight.\n            title = l1_title if role == "l1" else ""\n            targets.extend(find_window_targets(title, role=role, allow_fallback=False))\n''',
)

# 4) The legacy root CLI must not be a second real-input entry that skips the
# subscription/readiness/build-identity boundary.  Keep dry-run diagnostics,
# but force real execution through the desktop/RunnerService path.
replace_once(
    "main.py",
    '''import argparse\nimport sys\nfrom pathlib import Path\n''',
    '''import argparse\nimport sys\nimport time\nfrom pathlib import Path\n''',
)
replace_once(
    "main.py",
    '''def cmd_run(args: argparse.Namespace) -> int:\n    s = load_settings(Path(args.config) if args.config else None)\n    s.dry_run = False\n    if args.legacy:\n        print("[SECURITY ERROR] --legacy mode does not support real input (dry_run=False) because it bypasses P0 security chain. Use Mediator runner instead.")\n        return 1\n    print("WARNING: will move mouse / click. Ctrl+C to stop.")\n    try:\n        # S0.5：CLI 生产入口也传入 incident 目录（默认 %LocalAppData%/ShuaBao/incidents）\n        med = Mediator(s, ROOT, incident_dir=default_incident_dir())\n        med.set_trace(str(ROOT / "logs" / f"trace_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"))\n        med.run(max_steps=args.steps)\n    except KeyboardInterrupt:\n        print("stopped by user")\n    return 0\n''',
    '''def cmd_run(args: argparse.Namespace) -> int:\n    # Real input has one supported desktop boundary: DashboardFacade ->\n    # RunnerService -> live_execute -> RuntimeMediator.  The historical root\n    # CLI instantiated CoreMediator directly and therefore skipped entitlement,\n    # readiness and frozen build-identity checks.  Do not preserve that bypass.\n    print(\n        "[SECURITY ERROR] main.py run is disabled for real input. "\n        "Start ShuaBao through desktop_app.py / the packaged desktop shortcut "\n        "so subscription, preflight, build identity and RunnerService gates run."\n    )\n    return 2\n''',
)

# 5) Logging must never crash automation/benchmarks merely because the host
# console cannot encode a Unicode character (Windows runners can expose cp1252).
replace_once(
    "src/shuabao/log_sink.py",
    '''import builtins\nimport logging\nimport threading\n''',
    '''import builtins\nimport logging\nimport sys\nimport threading\n''',
)
replace_once(
    "src/shuabao/log_sink.py",
    '''    builtins.print(*args, **kwargs)\n''',
    '''    try:\n        builtins.print(*args, **kwargs)\n    except UnicodeEncodeError:\n        stream = kwargs.get("file") or sys.stdout\n        encoding = getattr(stream, "encoding", None) or "utf-8"\n        safe_args = tuple(\n            str(value).encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")\n            for value in args\n        )\n        builtins.print(*safe_args, **kwargs)\n''',
)

# CI portability corrections: these tests are about fail-closed incident
# archiving and AppData location, not availability of a local OCR venv or the
# spelling of a Windows 8.3 temp path.
replace_once(
    "tests/test_desktop_app.py",
    '''                    Settings(dry_run=True), ROOT, max_steps=1, incident_dir=tmp\n''',
    '''                    Settings(dry_run=True, ocr_mode="off"), ROOT, max_steps=1, incident_dir=tmp\n''',
)
replace_once(
    "tests/test_desktop_app.py",
    '''        self.assertEqual(path.parent, Path(self.tmp.name))\n''',
    '''        self.assertEqual(path.parent.resolve(), Path(self.tmp.name).resolve())\n''',
)

# Temporary applicator/workflow are removed by the workflow before committing
# the actual source fix, so the resulting branch contains only product/test
# changes rather than a permanent self-modifying release path.
print("cloud review fixes applied")
