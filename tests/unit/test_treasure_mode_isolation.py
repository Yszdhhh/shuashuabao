"""模式隔离测试：普通模式宝物品质优先裁决 vs 蹭车模式绿色神符专项获取。

普通模式产品裁决（2026-09）：负面过滤后只按现有品质顺序选择，
treasure_must_take / treasure_presets / synthesis 不再压过更高品质。
蹭车模式（mode_id="lobby_hitch"）：专项获取绿色神符（吞噬丹）。
"""

from shuabao.choice_policy import (
    choose_action,
    PanelCandidates,
    PolicyAction,
    PolicySettings,
    SessionState,
    SlotCandidate,
    assemble_policy_settings,
    PANEL_TREASURE,
)
from shuabao.settings import Settings


def _treasure_settings(mode_id: str = "normal_farm", **overrides):
    if overrides:
        return PolicySettings.from_mapping({"mode_id": mode_id, **overrides})
    return assemble_policy_settings(
        settings=Settings(mode_id=mode_id),
        skill_labels={},
        fetter_labels={},
        policy_doc={},
    )


def _decide(slots, mode_id: str = "normal_farm", **cand_kwargs):
    setting_kwargs = cand_kwargs.pop("setting_kwargs", {})
    cands = PanelCandidates(
        panel_kind=PANEL_TREASURE,
        slots=slots,
        refresh_count=0,
        has_giveup=True,
        can_refresh=False,
        owned_skill_cards=(),
        settings=_treasure_settings(mode_id, **setting_kwargs),
        **cand_kwargs,
    )
    return choose_action(cands, SessionState())


def _select(dec, expected_index: int, reason_frag: str | None = None):
    assert dec.action == PolicyAction.SELECT_SLOT, dec
    assert dec.index == expected_index, dec
    if reason_frag:
        assert reason_frag in dec.reason


# ---------------------------------------------------------------------------
# 普通模式：品质优先裁决
# ---------------------------------------------------------------------------


def test_normal_mode_orange_beats_lower_quality_must_take():
    """更高品质（橙）胜过更低品质（蓝/绿）必拿。"""
    dec = _decide((
        SlotCandidate(index=0, name="卡牌大师", rarity="blue", confidence=0.90),
        SlotCandidate(index=1, name="全都要", rarity="green", confidence=0.90),
        SlotCandidate(index=2, name="普通宝物", rarity="orange", confidence=0.90),
    ))
    _select(dec, 2)


def test_normal_mode_red_beats_white_synthesis():
    """更高品质（红）胜过更低品质（白）的龙珠合成进度。"""
    dec = _decide(
        (
            SlotCandidate(index=0, name="七龙珠", rarity="white", confidence=0.95),
            SlotCandidate(index=1, name="红宝珠", rarity="red", confidence=0.95),
        ),
        set_progress={"七龙珠": {"have": 2, "need": 3, "members": ["七龙珠"], "owned": []}},
        owned_bond_cards=(),
    )
    _select(dec, 1)


def test_normal_mode_orange_beats_green_talisman():
    """更高品质（橙）胜过更低品质（绿）神符。"""
    dec = _decide((
        SlotCandidate(index=0, name="恢复神符", rarity="green", confidence=0.90),
        SlotCandidate(index=1, name="高级宝物", rarity="orange", confidence=0.90),
    ))
    _select(dec, 1)


def test_normal_mode_same_quality_must_take_beats_preset():
    """同品质平级：必拿 > 预设。"""
    dec = _decide(
        (
            SlotCandidate(index=0, name="风暴之眼", rarity="orange", confidence=0.90),
            SlotCandidate(index=1, name="卡牌大师", rarity="orange", confidence=0.90),
        ),
        setting_kwargs={"treasure_presets": ("风暴之眼",), "min_confidence": 0.6},
    )
    _select(dec, 1, "必拿")


def test_normal_mode_same_quality_preset_beats_synthesis():
    """同品质平级：预设 > 合成。"""
    dec = _decide(
        (
            SlotCandidate(index=0, name="风暴之眼", rarity="orange", confidence=0.90),
            SlotCandidate(index=1, name="龙珠碎片", rarity="orange", confidence=0.90),
        ),
        setting_kwargs={"treasure_presets": ("风暴之眼",), "min_confidence": 0.6},
        set_progress={"龙珠": {"have": 2, "need": 3, "members": ["龙珠碎片"], "owned": []}},
        owned_bond_cards=(),
    )
    _select(dec, 0, "预设命中")


def test_normal_mode_same_quality_synthesis_beats_default():
    """同品质平级：合成 > 默认品质兜底。"""
    dec = _decide(
        (
            SlotCandidate(index=0, name="普通宝物", rarity="orange", confidence=0.90),
            SlotCandidate(index=1, name="龙珠碎片", rarity="orange", confidence=0.90),
        ),
        set_progress={"龙珠": {"have": 2, "need": 3, "members": ["龙珠碎片"], "owned": []}},
        owned_bond_cards=(),
    )
    _select(dec, 1, "套装进度优先")


def test_normal_mode_negative_treasure_dropped():
    """负面宝物（黑名单名字/负面描述）被过滤，剩余按品质选择。"""
    dec = _decide((
        SlotCandidate(index=0, name="贪婪献祭", rarity="red", confidence=0.95),
        SlotCandidate(index=1, name="断金符", rarity="orange", confidence=0.95,
                      description="获得后不再获得金币"),
        SlotCandidate(index=2, name="普通宝物", rarity="blue", confidence=0.90),
    ))
    _select(dec, 2)


# ---------------------------------------------------------------------------
# 蹭车模式：绿色神符专项获取
# ---------------------------------------------------------------------------


def test_hitch_mode_talisman_beats_higher_quality():
    """蹭车模式：神符优先于其他非负面宝物（含更高品质）。"""
    dec = _decide(
        (
            SlotCandidate(index=0, name="恢复神符", rarity="green", confidence=0.90),
            SlotCandidate(index=1, name="高级宝物", rarity="red", confidence=0.90),
        ),
        mode_id="lobby_hitch",
    )
    _select(dec, 0, "蹭车共享道具·神符")


def test_hitch_mode_talisman_is_taken_at_any_rarity():
    """Owner ruling 20260910：神符是共享道具，品质色不再是门槛。

    旧契约只认绿色神符，蓝色神符会被更高品质的自用宝物顶掉。蹭车是打辅助，
    能交给车队的只有共享道具，颜色无关。
    """
    dec = _decide(
        (
            SlotCandidate(index=0, name="奥术神符", rarity="blue", confidence=0.90),
            SlotCandidate(index=1, name="高级宝物", rarity="orange", confidence=0.90),
        ),
        mode_id="lobby_hitch",
    )
    _select(dec, 0, "蹭车共享道具·神符")


def test_hitch_mode_takes_devour_pill_then_hero_card():
    """神符 > 吞噬丹 > 英雄卡：车主定的共享道具顺序。"""
    dec = _decide(
        (
            SlotCandidate(index=0, name="英雄卡·希女王", rarity="blue", confidence=0.90),
            SlotCandidate(index=1, name="吞噬丹", rarity="purple", confidence=0.90),
        ),
        mode_id="lobby_hitch",
    )
    _select(dec, 1, "蹭车共享道具·吞噬丹")


def test_hitch_mode_falls_back_to_the_top_rarity_band():
    """没有命名共享道具时，预算够就拿最高品质（EX/传说），拿完也进公共背包。"""
    dec = _decide(
        (
            SlotCandidate(index=0, name="普通木剑", rarity="white", confidence=0.90),
            SlotCandidate(index=1, name="天火燎原", rarity="red", confidence=0.90),
        ),
        mode_id="lobby_hitch",
    )
    _select(dec, 1, "蹭车共享道具·最高品质")


def test_hitch_mode_negative_talisman_dropped():
    """蹭车模式：负面神符先被黑名单过滤，不触发专项获取。"""
    dec = _decide(
        (
            SlotCandidate(index=0, name="诅咒神符", rarity="green", confidence=0.95,
                          description="获得后不再增长攻击力"),
            SlotCandidate(index=1, name="普通宝物", rarity="blue", confidence=0.90),
        ),
        mode_id="lobby_hitch",
    )
    _select(dec, 1)


def test_hitch_mode_without_green_talisman_falls_back_to_quality():
    """蹭车模式：无绿色神符时回落普通品质顺序选择。"""
    dec = _decide(
        (
            SlotCandidate(index=0, name="卡牌大师", rarity="blue", confidence=0.90),
            SlotCandidate(index=1, name="高级宝物", rarity="orange", confidence=0.90),
        ),
        mode_id="lobby_hitch",
    )
    _select(dec, 1, "品质降级")
