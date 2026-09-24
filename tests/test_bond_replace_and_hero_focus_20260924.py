import numpy as np
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


def test_maybe_execute_bond_slot_replacement_picks_victim(monkeypatch):
    med = Mediator(Settings(), ROOT)
    
    # 模拟 1600x900 画面
    dummy_bgr = np.zeros((900, 1600, 3), dtype=np.uint8)
    frame = Frame(bgr=dummy_bgr, left=0, top=0, hwnd=123)

    # 模拟已有 10 张卡，前 9 张为大圣/封神/力量，第 10 张为屠戮者
    mock_owned = [
        "大圣再临", "齐天大圣", "风雷双翅", "哮天犬", "力量",
        "成长", "经济", "祝福", "大圣残躯", "屠戮者"
    ]
    monkeypatch.setattr(med, "_confirmed_bond_cards", lambda: tuple(mock_owned))

    clicked_actions = []
    def mock_act_click(hit, reason=""):
        clicked_actions.append((hit, reason))
        return True

    monkeypatch.setattr(med, "act_click", mock_act_click)

    ok = med._maybe_execute_bond_slot_replacement(frame)
    assert ok is True
    assert len(clicked_actions) == 1
    hit, reason = clicked_actions[0]
    
    # 第 10 张卡（index=9，即第 10 格）是非目标卡，必须命中第 10 格
    assert "ReplaceBondSlot-10" in reason or "10" in hit.name
    # 验证点击坐标对应第 10 格（cx=1071, cy=658）
    assert hit.x == 1071
    assert hit.y == 658


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
