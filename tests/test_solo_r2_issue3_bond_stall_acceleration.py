from pathlib import Path
import cv2
import numpy as np
import pytest

from shuabao.mediator import Mediator, Frame, Settings

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "solo_r2_20260925" / "bond_choice_f0342.png"


def test_stalled_bond_choice_selects_target_greed_without_hiding() -> None:
    assert FIXTURE_PATH.is_file(), f"Fixture missing: {FIXTURE_PATH}"
    bgr = cv2.imdecode(np.fromfile(str(FIXTURE_PATH), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert bgr is not None, "Failed to load fixture"
    frame = Frame(bgr=bgr)

    settings = Settings(dry_run=True, ocr_mode="live", bonds=["贪婪", "大圣"])
    med = Mediator(settings, ROOT)
    # Simulate main line stall condition
    med._main_line_stalled = lambda: True

    # 1. OCR choice recognizes greed at slot 3
    choice = med._ocr_reward_choice(frame, "bond")
    assert choice is not None
    # Must NOT be card_hide
    assert choice.name != "card_hide"
    # Must select greed on first frame
    assert "贪婪" in choice.name
    assert choice.x == 1152 and choice.y == 396


def test_single_frame_acceleration_confined_to_presets() -> None:
    """0.85 single-frame pick acceleration only applies to presets, not generic choices."""
    from shuabao.mediator import PolicyDecision, PolicyAction, SlotCandidate

    slots = (
        SlotCandidate(index=0, name="测试预设卡", confidence=0.88),
        SlotCandidate(index=1, name="其它卡1", confidence=0.80),
        SlotCandidate(index=2, name="其它卡2", confidence=0.80),
        SlotCandidate(index=3, name="其它卡3", confidence=0.80),
    )

    # 1. Preset / target / synthesis matches with 0.85 <= confidence < 0.95 -> accelerates (skips 2nd frame)
    d_preset = PolicyDecision(action=PolicyAction.SELECT_SLOT, index=0, reason="bond 预设命中：测试预设卡")
    assert Mediator._is_unambiguous_high_confidence_pick(d_preset, slots, d_preset.reason) is True

    d_synth = PolicyDecision(action=PolicyAction.SELECT_SLOT, index=0, reason="差一张合成：测试预设卡")
    assert Mediator._is_unambiguous_high_confidence_pick(d_synth, slots, d_synth.reason) is True

    duplicate_slots = (
        SlotCandidate(index=0, name="法术", confidence=0.94),
        SlotCandidate(index=1, name="藏宝图", confidence=0.99),
        SlotCandidate(index=2, name="法术", confidence=0.95),
        SlotCandidate(index=3, name="奇技", confidence=0.91),
    )
    assert Mediator._is_unambiguous_high_confidence_pick(d_preset, duplicate_slots, d_preset.reason) is False

    # 2. Non-preset / fallback with 0.85 <= confidence < 0.95 -> does NOT accelerate
    d_fallback = PolicyDecision(action=PolicyAction.SELECT_SLOT, index=0, reason="品质降级兜底：测试预设卡")
    assert Mediator._is_unambiguous_high_confidence_pick(d_fallback, slots, d_fallback.reason) is False

    # 3. Generic threshold remains strictly at 0.95
    assert Mediator._SINGLE_FRAME_PICK_CONFIDENCE == 0.95
