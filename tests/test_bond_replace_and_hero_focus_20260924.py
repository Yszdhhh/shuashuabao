import numpy as np
from types import SimpleNamespace
import pytest
from pathlib import Path
from shuabao.mediator import Mediator, MatchResult
from shuabao.settings import Settings
from shuabao.vision.capture import Frame

ROOT = Path(__file__).resolve().parents[1]


def test_is_target_synthetic_bond():
    med = Mediator(Settings(), ROOT)
    
    # 目标合成卡组：大圣系列、封神系列、法宝、基础卡
    assert med._is_target_synthetic_bond("齐天大圣") is True
    assert med._is_target_synthetic_bond("大圣再临") is True
    assert med._is_target_synthetic_bond("大圣残躯") is True
    assert med._is_target_synthetic_bond("封神法宝") is True
    assert med._is_target_synthetic_bond("风雷双翅") is True
    assert med._is_target_synthetic_bond("哮天犬") is True
    assert med._is_target_synthetic_bond("力量") is True
    assert med._is_target_synthetic_bond("成长") is True

    # 非目标合成卡组（散卡/杂卡）
    assert med._is_target_synthetic_bond("屠戮者") is False
    assert med._is_target_synthetic_bond("敏捷") is False
    assert med._is_target_synthetic_bond("普通攻击") is False


class _FakeOcr:
    is_available = True

    def __init__(self, texts):
        self.texts = texts

    def shadow_predict(self, frame, panel_id, slot):
        text = self.texts[slot["index"]]
        return SimpleNamespace(status="ok" if text else "empty", raw_text=text, rec_score=0.9 if text else 0.0)


_FULL_BAR = [
    "大圣再临", "齐天大圣", "风雷双翅", "哮天犬", "力量",
    "成长", "经济", "祝福", "大圣残躯", "屠戮者",
]


def _replace_med(monkeypatch, texts, incoming=None):
    med = Mediator(Settings(), ROOT)
    med._ocr_client = _FakeOcr(texts) if texts is not None else None
    med._bond_replace_incoming = incoming
    clicked = []
    monkeypatch.setattr(med, "act_click", lambda hit, reason="": clicked.append((hit, reason)) or True)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8), left=0, top=0, hwnd=123)
    return med, frame, clicked


def test_bond_slot_replacement_clicks_only_an_ocr_identified_non_target(monkeypatch):
    med, frame, clicked = _replace_med(monkeypatch, _FULL_BAR)
    assert med._maybe_execute_bond_slot_replacement(frame) is True
    assert len(clicked) == 1
    hit, reason = clicked[0]
    assert reason == "ReplaceBondSlot-10"
    assert (hit.x, hit.y) == (1071, 658)


def test_bond_slot_replacement_is_zero_input_without_ocr(monkeypatch):
    med, frame, clicked = _replace_med(monkeypatch, None)
    monkeypatch.setattr(med, "_confirmed_bond_cards", lambda: tuple(_FULL_BAR))
    assert med._maybe_execute_bond_slot_replacement(frame) is False
    assert clicked == []


def test_bond_slot_replacement_never_guesses_unread_slots(monkeypatch):
    med, frame, clicked = _replace_med(monkeypatch, _FULL_BAR[:9] + [""])
    assert med._maybe_execute_bond_slot_replacement(frame) is False
    assert clicked == []


def test_bond_slot_replacement_skips_the_card_just_taken(monkeypatch):
    med, frame, clicked = _replace_med(monkeypatch, _FULL_BAR, incoming="屠戮者")
    assert med._maybe_execute_bond_slot_replacement(frame) is False
    assert clicked == []


def _select_hero_med(monkeypatch, *, hud: bool):
    med = Mediator(Settings(), ROOT)
    fake_hit = MatchResult("select_hero", 0.95, 800, 600, 50, 20, 800, 600)
    monkeypatch.setattr(med, "find", lambda f, names, **kw: fake_hit if "select_hero" in names else None)
    monkeypatch.setattr(med, "_is_in_game_hud", lambda f: hud)
    monkeypatch.setattr(
        "shuabao.input.keyboard_mouse.is_current_process_elevated", lambda: True
    )
    clicked, keys = [], []
    monkeypatch.setattr(med, "act_click", lambda hit, reason="": clicked.append((hit, reason)) or True)
    monkeypatch.setattr(med, "act_key", lambda key, reason="": keys.append((key, reason)) or True)
    return med, clicked, keys


def test_select_hero_button_detection_triggers_click_and_f1(monkeypatch):
    med, clicked, keys = _select_hero_med(monkeypatch, hud=True)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8), left=0, top=0, hwnd=123)

    res = med._maybe_ensure_hero_panel_focus(frame, now=100.0)
    assert res is not None
    assert [reason for _hit, reason in clicked] == ["ClickSelectHero"]
    assert keys == [("F1", "SelectHeroHotkey")]


def test_select_hero_button_is_ignored_off_hud(monkeypatch):
    """过渡帧/非 HUD 帧零输入（AGENTS.md 第 5 条）。"""
    med, clicked, keys = _select_hero_med(monkeypatch, hud=False)
    frame = Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8), left=0, top=0, hwnd=123)

    assert med._maybe_ensure_hero_panel_focus(frame, now=100.0) is None
    assert clicked == [] and keys == []
