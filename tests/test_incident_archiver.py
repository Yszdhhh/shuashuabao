"""B1-2 未知页面/未知选择自动归档单元测试（蓝图 §7 B1-2 验收标准）。

覆盖：
- 10 个相同帧（同指纹）→ 只产生 1 组 incident；
- 不同页面 → 各自留档 N 组，metadata 与图片一一对应；
- 黑帧/错误窗口 → 只记健康错误（health_error），不标成 UNKNOWN；
- metadata 与图片一一对应（文件名/目录可回溯）；
- 保留期/容量上限清理只删本模块创建的 incident 目录；
- Mediator 接线：set_phase(ERROR) Fail-Closed 前留档、context=UNKNOWN 连续 2 秒留档。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
_SRC = ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from gamescript.incidents import IncidentArchiver
from gamescript.loop_action import LoopAction
from gamescript.mediator import Mediator, Phase
from gamescript.settings import Settings
from gamescript.stop_signal import StopSignal
from gamescript.vision.capture import Frame
from gamescript.vision.matcher import MatchResult
from tests.test_scenario_replay import FakeClock, FakeInputExecutor


def _frame(seed: int, size: tuple[int, int] = (240, 160)) -> Frame:
    rng = np.random.default_rng(seed)
    return Frame(
        bgr=rng.integers(0, 255, (*size, 3), dtype=np.uint8),
        hwnd=1001,
        window_title="英雄三国KK",
    )


def _gradient_frame(seed: int, size: tuple[int, int] = (160, 90)) -> Frame:
    """平滑渐变帧：不同 seed → 不同指纹，且 jpg 体积小（容量测试用）。"""
    h, w = size
    y, x = np.mgrid[0:h, 0:w].astype(np.float64)
    phase = seed * 0.7
    r = (128 + 100 * np.sin(x / 9.0 + phase)).clip(0, 255).astype(np.uint8)
    g = (128 + 100 * np.cos(y / 6.0 + phase)).clip(0, 255).astype(np.uint8)
    b = (128 + 100 * np.sin((x + y) / 11.0 + phase)).clip(0, 255).astype(np.uint8)
    return Frame(bgr=np.stack([b, g, r], axis=-1), hwnd=1001, window_title="英雄三国KK")


def _black_frame(size: tuple[int, int] = (900, 1600)) -> Frame:
    return Frame(bgr=np.zeros((*size, 3), dtype=np.uint8), hwnd=1001, window_title="英雄三国KK")


def _meta(**kw: object) -> dict:
    base: dict = {
        "kind": "unknown_page",
        "phase": "MAIN_LINE",
        "hwnd": 1001,
        "size": [1600, 900],
        "score": 0.0,
        "candidate_actions": [],
        "final_action": "wait",
        "reason": "test",
    }
    base.update(kw)
    return base


class IncidentArchiverTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _groups(self) -> list[Path]:
        return sorted(p for p in self.root.rglob("incident_*") if p.is_dir())

    def _meta_of(self, group: Path) -> dict:
        return json.loads((group / "metadata.json").read_text(encoding="utf-8"))

    # ---- 1. 10 个相同帧（同指纹）→ 只产生 1 组 incident ----

    def test_ten_identical_frames_produce_one_group(self) -> None:
        arch = IncidentArchiver(self.root)
        frame = _frame(1)
        for _ in range(10):
            saved = arch.maybe_record(frame_before=None, frame_now=frame, metadata=_meta())
        groups = self._groups()
        self.assertEqual(len(groups), 1)
        meta = self._meta_of(groups[0])
        self.assertEqual(meta["kind"], "unknown_page")
        self.assertTrue((groups[0] / "frame_now.jpg").is_file())
        # 同指纹后续调用去重返回 None
        self.assertIsNone(
            arch.maybe_record(frame_before=None, frame_now=frame, metadata=_meta())
        )

    # ---- 2. 不同页面 → 各自留档 N 组，metadata 与图片一一对应 ----

    def test_different_pages_each_archived(self) -> None:
        arch = IncidentArchiver(self.root)
        for seed in range(5):
            fp = arch.maybe_record(
                frame_before=None, frame_now=_frame(seed), metadata=_meta(reason=f"page-{seed}")
            )
            self.assertIsNotNone(fp)
        groups = self._groups()
        self.assertEqual(len(groups), 5)
        fingerprints = set()
        for group in groups:
            meta = self._meta_of(group)
            fingerprints.add(meta["frame_fingerprint"])
            self.assertEqual(meta["frame_now"], "frame_now.jpg")
            self.assertTrue((group / "frame_now.jpg").is_file())
        self.assertEqual(len(fingerprints), 5)

    # ---- 3. 黑帧/错误窗口 → 只记健康错误，不标成 UNKNOWN ----

    def test_black_frame_is_health_error_not_unknown(self) -> None:
        arch = IncidentArchiver(self.root)
        arch.maybe_record(
            frame_before=None,
            frame_now=_black_frame(),
            metadata=_meta(kind="unknown_page"),
            healthy=False,
            health_issues=["black_frame"],
            health_details="black frame",
        )
        groups = self._groups()
        self.assertEqual(len(groups), 1)
        meta = self._meta_of(groups[0])
        self.assertEqual(meta["kind"], "health_error")
        self.assertEqual(meta["reported_kind"], "unknown_page")
        self.assertFalse(meta["health"]["healthy"])
        self.assertEqual(meta["health"]["issues"], ["black_frame"])

    def test_healthy_frames_keep_their_kind(self) -> None:
        arch = IncidentArchiver(self.root)
        arch.maybe_record(
            frame_before=None, frame_now=_frame(2), metadata=_meta(kind="unknown_page"), healthy=True
        )
        meta = self._meta_of(self._groups()[0])
        self.assertEqual(meta["kind"], "unknown_page")
        self.assertTrue(meta["health"]["healthy"])

    # ---- 4. metadata 与图片一一对应（含 frame_after 补齐、ROI） ----

    def test_metadata_maps_to_images_with_roi_and_after_fill(self) -> None:
        arch = IncidentArchiver(self.root)
        before = _frame(11)
        now = _frame(12)
        rois = [{"label": "panel", "x": 100, "y": 50, "w": 300, "h": 200}]
        fp = arch.maybe_record(
            frame_before=before, frame_now=now, metadata=_meta(rois=rois)
        )
        self.assertIsNotNone(fp)
        groups = self._groups()
        self.assertEqual(len(groups), 1)
        group = groups[0]
        meta = self._meta_of(group)
        self.assertEqual(meta["frame_before"], "frame_before.jpg")
        self.assertEqual(meta["frame_now"], "frame_now.jpg")
        self.assertIsNone(meta["frame_after"])
        self.assertTrue((group / "frame_before.jpg").is_file())
        self.assertTrue((group / "frame_now.jpg").is_file())
        self.assertTrue((group / "roi_panel.png").is_file())
        self.assertEqual(meta["rois"][0]["file"], "roi_panel.png")
        # frame_after 触发瞬间不存在 → 后续帧补齐
        self.assertTrue(arch.attach_frame_after(fp, _frame(13)))
        meta2 = self._meta_of(group)
        self.assertEqual(meta2["frame_after"], "frame_after.jpg")
        self.assertTrue((group / "frame_after.jpg").is_file())
        # 同一指纹只能补齐一次
        self.assertFalse(arch.attach_frame_after(fp, _frame(14)))

    def test_invalid_frame_not_recorded(self) -> None:
        arch = IncidentArchiver(self.root)
        empty = Frame(bgr=np.zeros((0, 0, 3), dtype=np.uint8), is_valid=False, error="capture failed")
        self.assertIsNone(arch.maybe_record(frame_before=None, frame_now=empty, metadata=_meta()))
        self.assertEqual(self._groups(), [])

    # ---- 5. 保留期 / 容量上限 ----

    def test_retention_deletes_only_old_incident_dirs(self) -> None:
        arch = IncidentArchiver(self.root, retention_days=7)
        fp = arch.maybe_record(frame_before=None, frame_now=_gradient_frame(21), metadata=_meta())
        self.assertIsNotNone(fp)
        group = self._groups()[0]
        old = time.time() - 8 * 86400
        for p in list(group.rglob("*")) + [group]:
            os.utime(p, (old, old))
        # 归档新 incident 时触发清理：旧目录被删，新目录保留
        fp2 = arch.maybe_record(frame_before=None, frame_now=_gradient_frame(22), metadata=_meta())
        self.assertIsNotNone(fp2)
        groups = self._groups()
        self.assertEqual(len(groups), 1)
        self.assertNotEqual(groups[0], group)
        # 官方日志（非 incident_* 文件）不受影响
        official = self.root / "20260810" / "trace_123.jsonl"
        official.parent.mkdir(parents=True, exist_ok=True)
        official.write_text('{"tick": 1}\n', encoding="utf-8")
        arch.cleanup()
        self.assertTrue(official.is_file())

    def test_capacity_keeps_newest_under_limit(self) -> None:
        # 平滑小帧 + 小上限：反复归档不同页面，总大小必须 ≤ 上限且最新组保留
        arch = IncidentArchiver(self.root, max_bytes=40_000)
        last_group: Path | None = None
        for seed in range(8):
            arch.maybe_record(frame_before=None, frame_now=_gradient_frame(seed), metadata=_meta())
            groups = self._groups()
            self.assertGreaterEqual(len(groups), 1)
            last_group = groups[-1]
        groups = self._groups()
        total = sum(f.stat().st_size for g in groups for f in g.rglob("*") if f.is_file())
        self.assertLessEqual(total, 40_000)
        # 刚归档的最新 incident 不被容量清理误删
        self.assertTrue(last_group is not None and last_group.is_dir())

    # ---- 6. Mediator 接线 ----

    def test_mediator_fail_closed_records_incident(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            med = Mediator(Settings(), ROOT, incident_dir=tmp)
            frame = _frame(31)
            med._last_frame = frame
            med._prev_frame = frame
            med.set_phase(Phase.MAIN_LINE, "wiring setup")
            med.set_phase(Phase.ERROR, "unknown selection panel timeout")
            groups = sorted(Path(tmp).rglob("incident_*"))
            self.assertEqual(len(groups), 1)
            meta = json.loads((groups[0] / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["kind"], "fail_closed")
            # phase 是 Fail-Closed 前的原阶段，而不是 ERROR
            self.assertEqual(meta["phase"], "MAIN_LINE")
            self.assertEqual(meta["reason"], "unknown selection panel timeout")

    def test_mediator_unknown_two_seconds_records_incident(self) -> None:
        clock = FakeClock(start=1000.0)
        stop_signal = StopSignal()
        with tempfile.TemporaryDirectory() as tmp:
            with clock.install():
                med = Mediator(Settings(), ROOT, stop_signal=stop_signal, incident_dir=tmp)
                med.executor = FakeInputExecutor(stop_signal, clock)
                frame = _frame(32)
                med.see = lambda reason="": frame
                med._context_cache_value = "UNKNOWN"
                med.set_phase(Phase.MAIN_LINE, "wiring setup")
                med.tick()
                clock.advance(2.5)
                med.tick()
            groups = sorted(Path(tmp).rglob("incident_*"))
            self.assertEqual(len(groups), 1)
            meta = json.loads((groups[0] / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["kind"], "unknown_page")
            self.assertEqual(meta["reason"], "context=UNKNOWN >= 2s")

    def test_mediator_default_no_archiver(self) -> None:
        med = Mediator(Settings(), ROOT)
        self.assertIsNone(med._archiver)
        med.set_phase(Phase.ERROR, "some failure")
        self.assertIsNone(med._archiver)

    def test_sample_panel_saves_frame_with_metadata(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="inc_panel_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        clock = FakeClock()
        arch = IncidentArchiver(root=tmp, now_fn=clock.now)
        frame = _gradient_frame(seed=42)
        fp = arch.sample_panel(frame, {"phase": "MAIN_LINE", "panel_kind": "bond"})
        self.assertIsNotNone(fp)
        panels = sorted(tmp.rglob("panel_*.jpg"))
        self.assertEqual(len(panels), 1)
        meta_path = panels[0].with_suffix(".json")
        self.assertTrue(meta_path.is_file())
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(meta["kind"], "panel_sample")
        self.assertEqual(meta["panel_kind"], "bond")
        self.assertEqual(meta["size"], [90, 160])

    def test_sample_panel_dedup_window(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="inc_panel_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        clock = FakeClock()
        arch = IncidentArchiver(root=tmp, now_fn=clock.now)
        frame = _gradient_frame(seed=7)
        self.assertIsNotNone(arch.sample_panel(frame, {"panel_kind": "skill"}))
        clock.advance(60)
        self.assertIsNone(arch.sample_panel(frame, {"panel_kind": "skill"}))  # 去重窗口内
        clock.advance(300)
        self.assertIsNotNone(arch.sample_panel(frame, {"panel_kind": "skill"}))  # 窗口外
        n = len(sorted(tmp.rglob("panel_*.jpg")))
        self.assertEqual(n, 2)

    def test_sample_panel_different_frames_both_saved(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="inc_panel_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        clock = FakeClock()
        arch = IncidentArchiver(root=tmp, now_fn=clock.now)
        a = arch.sample_panel(_gradient_frame(seed=1), {"panel_kind": "skill"})
        b = arch.sample_panel(_gradient_frame(seed=2), {"panel_kind": "treasure"})
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertNotEqual(a, b)
        n = len(sorted(tmp.rglob("panel_*.jpg")))
        self.assertEqual(n, 2)

    # ---- 7. S0.5 生产 incident：metadata 完整性 / 触发点 / 不泄露密码 ----

    def test_mediator_fail_closed_metadata_s0_fields_no_password(self) -> None:
        """Fail-Closed incident 含 phase/context/evidence/action/attempt/deadline/
        outcome/rois，且绝不归档 room_password。"""
        with tempfile.TemporaryDirectory() as tmp:
            med = Mediator(Settings(), ROOT, incident_dir=tmp)
            med.settings.room_password = "top-secret-pw"
            frame = _frame(41, size=(900, 1600))
            med._last_frame = frame
            med._prev_frame = frame
            med._context_cache_value = "MAIN_LINE"
            med.set_phase(Phase.MAIN_LINE, "wiring setup")
            med.set_phase(Phase.ERROR, "probe fail closed")
            groups = sorted(Path(tmp).rglob("incident_*"))
            self.assertEqual(len(groups), 1)
            meta = json.loads((groups[0] / "metadata.json").read_text(encoding="utf-8"))
            for field in ("phase", "context", "evidence", "action", "attempt", "deadline", "outcome", "rois"):
                self.assertIn(field, meta, f"metadata 必须含 {field}")
            self.assertIsInstance(meta["evidence"], dict)
            self.assertIsInstance(meta["rois"], list)
            raw = (groups[0] / "metadata.json").read_text(encoding="utf-8")
            self.assertNotIn("top-secret-pw", raw, "密码不得归档")
            # frame_before / frame_now 已保存
            self.assertTrue((groups[0] / "frame_before.jpg").is_file())
            self.assertTrue((groups[0] / "frame_now.jpg").is_file())

    def test_round_timeout_records_incident_with_deadline_outcome(self) -> None:
        """round hard deadline 到期产生完整 incident（round_timeout + deadline/outcome）。"""
        clock = FakeClock(start=100.0)
        stop_signal = StopSignal()
        with tempfile.TemporaryDirectory() as tmp:
            with clock.install():
                med = Mediator(Settings(dry_run=False, round_timeout_s=60), ROOT,
                               stop_signal=stop_signal, incident_dir=tmp)
                med.executor = FakeInputExecutor(stop_signal, clock)
                frame = _frame(42, size=(900, 1600))
                med.see = lambda reason="": frame
                med._last_frame = frame
                med._prev_frame = frame
                med.set_phase(Phase.MAIN_LINE, "round start")
                clock.set(161.0)
                self.assertEqual(med.tick(), LoopAction.Continue)
                self.assertIs(med.phase, Phase.QUIT)
            groups = sorted(Path(tmp).rglob("incident_*"))
            self.assertEqual(len(groups), 1)
            meta = json.loads((groups[0] / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["kind"], "round_timeout")
            self.assertEqual(meta["outcome"], "TIMEOUT")
            self.assertIsNotNone(meta["deadline"])
            self.assertEqual(meta["phase"], "MAIN_LINE")

    def test_recovery_start_records_incident(self) -> None:
        """恢复 episode 起点产生 incident（recovery_start + recovery_kind/step）。"""
        clock = FakeClock(start=100.0)
        stop_signal = StopSignal()
        with tempfile.TemporaryDirectory() as tmp:
            with clock.install():
                med = Mediator(Settings(dry_run=False), ROOT,
                               stop_signal=stop_signal, incident_dir=tmp)
                med.executor = FakeInputExecutor(stop_signal, clock)
                frame = _frame(43, size=(900, 1600))
                med.see = lambda reason="": frame
                med._last_frame = frame
                med._prev_frame = frame
                med.set_phase(Phase.MAIN_LINE, "recovery incident")
                with patch.object(
                    med, "find_scene",
                    side_effect=lambda _f, s, **_k: MatchResult("fail", 0.95, 100, 100, 20, 20, 100, 100)
                    if s == "fail" else None,
                ), patch.object(med, "_selection_anchor", return_value=None):
                    clock.set(100.5)
                    med.tick()
                    clock.set(100.9)
                    med.tick()
                self.assertIs(med.phase, Phase.RECOVER_FAILURE)
            groups = sorted(Path(tmp).rglob("incident_*"))
            self.assertEqual(len(groups), 1)
            meta = json.loads((groups[0] / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["kind"], "recovery_recovery_start")
            self.assertEqual(meta["recovery_kind"], "FAIL")
            self.assertEqual(meta["recovery_step"], "FAIL_CONFIRM")

    def test_normal_ticks_do_not_write_incidents(self) -> None:
        """正常 HUD 每 tick 不得写图（10 tick 零 incident）。"""
        clock = FakeClock(start=100.0)
        stop_signal = StopSignal()
        with tempfile.TemporaryDirectory() as tmp:
            with clock.install():
                med = Mediator(Settings(dry_run=True), ROOT,
                               stop_signal=stop_signal, incident_dir=tmp)
                med.executor = FakeInputExecutor(stop_signal, clock)
                frame = _frame(44, size=(900, 1600))
                med.see = lambda reason="": frame
                med._last_frame = frame
                med._prev_frame = frame
                med._context_cache_value = "MAIN_LINE"  # 正常 HUD 上下文
                med.set_phase(Phase.MAIN_LINE, "normal ticks")
                with patch.object(med, "_post_game_state", return_value=None), \
                        patch.object(med, "find_scene", return_value=None), \
                        patch.object(med, "_selection_anchor", return_value=None), \
                        patch.object(med, "_find_reward_choice", return_value=None), \
                        patch.object(med, "_ensure_auto_task_enabled", return_value=None), \
                        patch.object(med, "_ensure_challenge_buttons", return_value=None), \
                        patch.object(med, "_find_stage_page", return_value=False), \
                        patch.object(med, "_maybe_open_choice_panel", return_value=None), \
                        patch.object(med, "_maybe_fire_artifacts", return_value=None):
                    for i in range(10):
                        clock.set(101.0 + i * 0.3)
                        self.assertEqual(med.tick(), LoopAction.Continue)
            groups = sorted(Path(tmp).rglob("incident_*"))
            self.assertEqual(len(groups), 0, "正常 HUD 每 tick 不得落图")

    def test_frame_after_attached_only_once(self) -> None:
        """frame_after 仅补一次：第二次 attach 返回 False。"""
        arch = IncidentArchiver(self.root)
        now = _frame(45)
        fp = arch.maybe_record(frame_before=None, frame_now=now, metadata=_meta())
        self.assertIsNotNone(fp)
        after = _frame(46)
        self.assertTrue(arch.attach_frame_after(fp, after))
        self.assertFalse(arch.attach_frame_after(fp, after), "frame_after 只补一次")
        groups = sorted(self.root.rglob("incident_*"))
        self.assertTrue((groups[0] / "frame_after.jpg").is_file())


if __name__ == "__main__":
    unittest.main()
