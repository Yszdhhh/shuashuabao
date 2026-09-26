"""F9 owner-mark hotkey: trace owner_mark plus marks bundle, e-stop intact.

Offline only: the hotkey callback is simulated, no game input is sent, and no
live PASS is claimed.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np

import tools.live_scenario_capture as live_capture
from shuabao.input import emergency_stop as emergency_stop_module
from shuabao.input.emergency_stop import VK_F12, VK_SHIFT, EmergencyStopListener
from shuabao.input.keyboard_mouse import ActionResult
from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.stop_signal import StopSignal
from shuabao.vision.capture import Frame
from tools.live_scenario_capture import (
    OWNER_MARK_POST_S,
    OWNER_MARK_PRE_S,
    VK_F9,
    BundleRecorder,
    OwnerMarkListener,
)


ROOT = Path(__file__).resolve().parents[1]


def _fixture_frame(variant: int = 0) -> Frame:
    path = ROOT / "fixtures" / "replay" / "main_line_auto_on.png"
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    if variant:
        image = image.copy()
        image[0, 0] = [(variant * 60) % 256, 0, 0]
    return Frame(image, window_title="英雄三国KK", hwnd=10001, role="l1")


def _recorder(tmp_path: Path) -> BundleRecorder:
    return BundleRecorder(
        tmp_path / "bundle",
        repo_root=ROOT,
        target="black_merchant",
        settings=Settings(dry_run=True, ocr_mode="off"),
        initial_phase="MAIN_LINE",
        execution_mode="mediator_tick",
    )


def _mediator() -> Mediator:
    med = Mediator(Settings(dry_run=True, ocr_mode="off"), ROOT, stop_signal=StopSignal())
    med.set_phase(Phase.MAIN_LINE, "owner mark unit test")
    return med


def _tick(recorder: BundleRecorder, med: Mediator, frame: Frame, at_s: float) -> None:
    # Ticks without in-tick state change or input are intentionally not saved
    # (event-driven bundle), so record a synthetic input to persist the frame.
    recorder.begin_tick()
    recorder.record_input("click", (10, 20), {}, ActionResult(True, "SUCCESS", "ok"))
    recorder.record_tick(
        med,
        phase_before="MAIN_LINE",
        before_state=live_capture._state_snapshot(med),
        before_frame=frame,
        after_frame=None,
        loop_action=LoopAction.Continue,
        at_s=at_s,
    )
    recorder.begin_tick()


def test_owner_mark_writes_trace_and_packages_pre_post_frames(tmp_path: Path, capsys) -> None:
    recorder = _recorder(tmp_path)
    med = _mediator()

    _tick(recorder, med, _fixture_frame(0), 2.0)
    _tick(recorder, med, _fixture_frame(1), 11.5)
    events_before = len(recorder.manifest["events"])

    mark = recorder.record_owner_mark(med, _fixture_frame(1), at_s=12.0, wall_ts=1700000000.0)

    assert mark["n"] == 1
    assert mark["tick"] == med._tick_no
    assert mark["window_end_at_s"] == round(12.0 + OWNER_MARK_POST_S, 3)
    assert OWNER_MARK_PRE_S == 10.0 and OWNER_MARK_POST_S == 5.0
    assert "[mark] 已标记第 1 处问题" in capsys.readouterr().out

    rows = [
        json.loads(line)
        for line in (recorder.bundle_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows[-1]["owner_mark"] == {"ts": 1700000000.0, "n": 1}
    assert rows[-1]["tick"] == med._tick_no

    assert recorder.manifest["marks"] == [mark]
    assert recorder.inputs_this_tick == []
    assert len(recorder.manifest["events"]) == events_before

    mark_dir = recorder.bundle_dir / mark["dir"]
    assert (mark_dir / "state_snapshot.json").is_file()
    snapshot = json.loads((mark_dir / "state_snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["phase"] == "MAIN_LINE"
    trace_slice = json.loads((mark_dir / "trace_slice.json").read_text(encoding="utf-8"))
    assert trace_slice[-1]["owner_mark"] == {"ts": 1700000000.0, "n": 1}
    # Press-minus-10s window covers both pre-press frames.
    assert len(mark["frames"]) >= 2
    for relative in mark["frames"]:
        assert (recorder.bundle_dir / relative).is_file()

    # A later tick inside press-plus-5s is backfilled without any game input.
    pre_count = len(recorder.manifest["marks"][0]["frames"])
    _tick(recorder, med, _fixture_frame(2), 14.0)
    assert len(recorder.manifest["marks"][0]["frames"]) == pre_count + 1

    recorder.finalize()
    payload = json.loads((tmp_path / "bundle" / "manifest.json").read_text(encoding="utf-8"))
    assert len(payload["marks"]) == 1
    assert payload["marks"][0]["closed"] is True
    assert payload["marks"][0]["dir"] == mark["dir"]
    assert (recorder.bundle_dir / payload["marks"][0]["state_snapshot_file"]).is_file()


def test_owner_mark_uses_f9_only_and_is_edge_triggered() -> None:
    assert VK_F9 == 0x78
    assert VK_F9 not in {VK_SHIFT, VK_F12}

    presses: list[float] = []
    states = iter([False, True, True, False, True, False])
    seen_keys: list[int] = []

    def fake_key(vk: int) -> bool:
        seen_keys.append(vk)
        return next(states)

    listener = OwnerMarkListener(on_press=presses.append, poll_interval=0.001, key_check=fake_key)
    for _ in range(6):
        listener._poll_once()

    assert seen_keys and all(key == VK_F9 for key in seen_keys)
    assert len(presses) == 2


def test_shift_f12_emergency_stop_still_effective_alongside_mark_listener(monkeypatch) -> None:
    monkeypatch.setattr(emergency_stop_module, "check_key_pressed_win32", lambda _vk: True)
    signal = StopSignal()
    stopper = EmergencyStopListener(signal, poll_interval=0.01)
    marks: list[float] = []
    marker = OwnerMarkListener(on_press=marks.append, poll_interval=0.01, key_check=lambda _vk: False)
    stopper.start()
    marker.start()
    try:
        deadline = time.time() + 2.0
        while not signal.is_set() and time.time() < deadline:
            time.sleep(0.02)
    finally:
        stopper.stop()
        marker.stop()

    assert signal.is_set()
    assert marks == []


def test_launcher_run_notes_mention_f9_mark_for_12_and_13() -> None:
    script = (ROOT / "live_scenario_launcher.ps1").read_text(encoding="utf-8")
    solo = script.split("function Invoke-SoloIngameChainCapture", 1)[1].split("\nfunction ", 1)[0]
    hitch = script.split("function Invoke-HitchLobbyChainCapture", 1)[1].split("\nfunction ", 1)[0]
    for body in (solo, hitch):
        assert "F9" in body
        assert "Shift+F12" in body
    assert "Shift+F12" in script
