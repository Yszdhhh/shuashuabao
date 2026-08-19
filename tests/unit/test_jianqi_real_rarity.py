from shuabao.choice_policy import PanelCandidates, PolicySettings, SlotCandidate, choose_action
from shuabao.skill_catalog import card_rarity

def test_jianqi_real_rarities():
    assert card_rarity("碎冰") == "紫"
    assert card_rarity("剑气爆发") == "蓝"
    assert card_rarity("湮灭斩") == "橙"

def test_jianqi_three_cards_choice():
    slots = (
        SlotCandidate(index=1, name="碎冰", confidence=0.95),
        SlotCandidate(index=2, name="剑气爆发", confidence=0.95),
        SlotCandidate(index=3, name="湮灭斩", confidence=0.95),
    )
    # skill_focus_families specifies the active skill families in play
    settings = PolicySettings(skill_focus_families=("剑气",), quality_order=["red", "orange", "purple", "blue", "white", "green"])
    candidates = PanelCandidates(panel_kind="skill", slots=slots, settings=settings, owned_skill_cards=("剑气",))
    decision = choose_action(candidates)
    # 湮灭斩 (橙色 SSR) is slot 3, should be chosen over 碎冰 (紫色 SR) and 剑气爆发 (蓝色 R)
    assert decision.target_slot == 3
    assert "湮灭斩" in decision.reason
