"""Silver crystal assets and the solo inventory confirmation transaction."""

from pathlib import Path
import time

import cv2
import numpy as np

from shuabao.loop_action import LoopAction
from shuabao.mediator import Mediator
from shuabao.runtime_mediator import Mediator as RuntimeMediator
from shuabao.settings import Settings
from shuabao.vision.capture import Frame
from shuabao.vision.matcher import MatchResult


ROOT = Path(__file__).resolve().parents[1]


def _frame() -> Frame:
    return Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))


def _hit(name: str, x: int, y: int, w: int, h: int) -> MatchResult:
    return MatchResult(name, 0.99, x, y, w, h, x + w // 2, y + h // 2)


def test_supplied_yinyue_images_match_restored_runtime_assets() -> None:
    cases = (
        ("yinyue_confirm_20260923.jpg", "yinyue_confirm_title.png"),
        ("yinyue_confirm_20260923.jpg", "yinyue_confirm_yes.png"),
        ("yinyue_item_20260923.jpg", "yinyue_crystal.png"),
    )
    for screenshot, template in cases:
        image = cv2.imdecode(np.frombuffer((ROOT / "tests" / "fixtures" / screenshot).read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
        asset = cv2.imdecode(np.frombuffer((ROOT / "assets" / "Images" / template).read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
        assert image is not None and asset is not None
        assert cv2.matchTemplate(image, asset, cv2.TM_CCOEFF_NORMED).max() > 0.95


def test_solo_uses_yinyue_before_inventory_fills_and_confirms_yes(monkeypatch) -> None:
    med = Mediator(Settings(mode_id="normal_farm"), ROOT)
    frame = _frame()
    crystal = _hit("yinyue_crystal", 1090, 710, 36, 33)
    title = _hit("yinyue_confirm_title", 650, 380, 260, 25)
    yes = _hit("yinyue_confirm_yes", 680, 448, 45, 30)
    clicked = []
    monkeypatch.setattr(med, "_has_active_transaction", lambda _f: False)
    monkeypatch.setattr(med, "_is_in_game_hud", lambda _f: True)
    monkeypatch.setattr(med, "_selection_anchor", lambda _f: None)
    monkeypatch.setattr(
        med, "find",
        lambda _f, names, **_kw: {
            "yinyue_crystal": crystal,
            "yinyue_confirm_title": title,
            "yinyue_confirm_yes": yes,
        }.get(names[0]),
    )
    monkeypatch.setattr(med, "act_click", lambda hit, reason: (clicked.append((hit, reason)), True)[1])

    assert med._maybe_opportunistic_yinyue_crystal(frame, 100.0) is LoopAction.Continue
    assert med._pending_action is not None
    assert med._pending_action.kind == "WAIT_YINYUE_CONFIRM"
    assert med._handle_yinyue_confirm_dialog(frame) is LoopAction.Continue
    assert [reason for _, reason in clicked] == ["UseInventory-yinyue_crystal", "YinyueConfirm-Yes"]
    assert med._pending_action is None


def test_yinyue_title_fallback_uses_title_center_geometry(monkeypatch) -> None:
    med = Mediator(Settings(mode_id="normal_farm"), ROOT)
    title = _hit("yinyue_confirm_title", 650, 380, 260, 25)
    clicked = []
    monkeypatch.setattr(med, "find", lambda _f, names, **_kw: title if names == ["yinyue_confirm_title"] else None)
    monkeypatch.setattr(med, "act_click", lambda hit, reason: (clicked.append((hit, reason)), True)[1])

    assert med._handle_yinyue_confirm_dialog(_frame()) is LoopAction.Continue
    hit, reason = clicked[0]
    assert reason == "YinyueConfirm-Yes"
    assert hit.center == (702, 463)


def test_yinyue_does_not_auto_use_in_hitch_mode(monkeypatch) -> None:
    med = Mediator(Settings(mode_id="lobby_hitch"), ROOT)
    monkeypatch.setattr(med, "find", lambda *_args, **_kwargs: _hit("yinyue_crystal", 1090, 710, 36, 33))
    assert med._maybe_opportunistic_yinyue_crystal(_frame(), 100.0) is None


def test_unknown_hero_card_modal_reuses_evolution_choice_path(monkeypatch) -> None:
    """A clicked 神赐英雄卡 uses the same modal ranker as a normal hero card."""
    med = RuntimeMediator(Settings(mode_id="normal_farm"), ROOT)
    choice = _hit("evolution_card_0_rank_4", 650, 360, 180, 230)
    monkeypatch.setattr(med, "_classify_choice_panel", lambda _f: "treasure")
    monkeypatch.setattr(Mediator, "_find_evolution_choice", lambda _self, _f, _anchor=None: choice)

    assert med._find_evolution_choice(_frame()) is None
    med._inventory_modal_until = time.time() + 3.0
    assert med._find_evolution_choice(_frame()) is choice
