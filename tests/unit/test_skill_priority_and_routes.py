"""skill_priority / skill_custom_routes 集成单测。

覆盖：
1. 用户技能族优先级排序生效；
2. priority 为空时与现状完全一致（回归保护）；
3. 路线偏好 prefer/avoid 标签加减分生效；
4. Settings → PolicySettings 往返持久化；
5. smart_route CARRY 优先级覆盖与缺省回退。
"""

from __future__ import annotations

from types import SimpleNamespace

from shuabao.choice_policy import (
    PolicySettings,
    SlotCandidate,
    _rank_skill_candidates,
    assemble_policy_settings,
)
from shuabao.settings import Settings
from shuabao.smart_route import SkillRole, assign_skill_roles

FOCUS = ("主炮", "光线", "射线", "剑气")


def _slots() -> tuple[SlotCandidate, ...]:
    """同品质/同等级/无名候选，仅族不同 → 排序完全由新增键决定。"""
    return tuple(
        SlotCandidate(index=i, family=fam, confidence=0.99) for i, fam in enumerate(FOCUS)
    )


def test_user_family_priority_orders_candidates():
    settings = PolicySettings(
        skill_focus_families=FOCUS,
        skill_priority=("光线", "剑气"),
    )
    assert _rank_skill_candidates(_slots(), settings, ()) == [1, 3, 0, 2]


def test_empty_priority_keeps_baseline_order():
    baseline = PolicySettings(skill_focus_families=FOCUS)
    empty = PolicySettings(
        skill_focus_families=FOCUS,
        skill_priority=(),
        skill_custom_routes=(("主炮", "damage"),),  # 无 prefer 表时不影响排序
    )
    assert _rank_skill_candidates(_slots(), baseline, ()) == [0, 1, 2, 3]
    assert _rank_skill_candidates(_slots(), empty, ()) == [0, 1, 2, 3]


def test_route_preference_tags_reweight_same_family():
    slots = (
        SlotCandidate(index=0, family="主炮", confidence=0.99, description="眩晕控制"),
        SlotCandidate(index=1, family="主炮", confidence=0.99),
        SlotCandidate(index=2, family="主炮", confidence=0.99, description="附带易伤"),
    )
    base = PolicySettings(skill_focus_families=FOCUS)
    tuned = PolicySettings(
        skill_focus_families=FOCUS,
        skill_route_preferences=(("主炮", "control", ("控制",), ("易伤",)),),
    )
    assert _rank_skill_candidates(slots, base, ()) == [0, 1, 2]
    assert _rank_skill_candidates(slots, tuned, ()) == [0, 1, 2]
    # avoid 命中必须排到无标签之后：换索引验证减分方向。
    flipped = (
        SlotCandidate(index=0, family="主炮", confidence=0.99),
        SlotCandidate(index=1, family="主炮", confidence=0.99, description="附带易伤"),
    )
    assert _rank_skill_candidates(flipped, tuned, ()) == [0, 1]


LABELS = {"zj": "主炮", "gd": "光弹"}
ROUTES_DOC = {
    "version": 2,
    "routes": {},
    "families": {
        "zj": {
            "name": "主炮",
            "routes": [
                {"id": "control", "label": "优先控制", "prefer": ["控制"], "avoid": ["易伤"]}
            ],
        }
    },
}


def _fake_settings(**extra) -> SimpleNamespace:
    base = dict(
        skills=["zj"],
        cards=[],
        treasure_allow_negative=[],
        skill_archive_levels={},
        smart_route_disabled_amplifiers=[],
        skill_priority=["gd", "zj"],
        skill_custom_routes={"zj": "control"},
    )
    base.update(extra)
    return SimpleNamespace(**base)


def test_assemble_maps_settings_fields_to_policy_settings():
    ps = assemble_policy_settings(
        settings=_fake_settings(),
        skill_labels=LABELS,
        fetter_labels={},
        policy_doc={},
        skill_routes_doc=ROUTES_DOC,
    )
    assert ps.skill_priority == ("光弹", "主炮")
    assert ps.skill_custom_routes == (("主炮", "control"),)
    assert ps.skill_route_preferences == (("主炮", "control", ("控制",), ("易伤",)),)


def test_assemble_without_doc_or_fields_is_inert():
    ps = assemble_policy_settings(
        settings=_fake_settings(skill_priority=[], skill_custom_routes={}),
        skill_labels=LABELS,
        fetter_labels={},
        policy_doc={},
    )
    assert ps.skill_priority == ()
    assert ps.skill_custom_routes == ()
    assert ps.skill_route_preferences == ()


def test_settings_roundtrip_persists_new_fields(tmp_path):
    s = Settings(skill_priority=["jq", "pg"], skill_custom_routes={"jq": "damage"})
    path = tmp_path / "settings.json"
    s.save(path)
    loaded = Settings.load(path)
    assert loaded.skill_priority == ["jq", "pg"]
    assert loaded.skill_custom_routes == {"jq": "damage"}
    ps = assemble_policy_settings(
        settings=loaded,
        skill_labels={"jq": "剑气", "pg": "普攻"},
        fetter_labels={},
        policy_doc={},
    )
    assert ps.skill_priority == ("剑气", "普攻")
    assert ps.skill_custom_routes == (("剑气", "damage"),)


def test_from_dict_cleans_corrupt_new_fields():
    assert Settings._from_dict({"skill_priority": "bad"}).skill_priority == []
    assert Settings._from_dict({"skill_custom_routes": ["x"]}).skill_custom_routes == {}
    cleaned = Settings._from_dict(
        {"skill_priority": ["jq", "", "jq", "pg", "asjg", "hbj"],
         "skill_custom_routes": {"jq": "damage", "pg": 5}}
    )
    # 去重保序、截断至 4；非字符串路线值剔除。
    assert cleaned.skill_priority == ["jq", "pg", "asjg", "hbj"]
    assert cleaned.skill_custom_routes == {"jq": "damage"}


_CARRY_LABELS = {"carry": "主炮", "amp1": "光线", "amp2": "射线", "amp3": "剑气"}
_CARRY_KNOWLEDGE = {
    "family_to_code": {value: key for key, value in _CARRY_LABELS.items()},
    "cards": [
        {"name": "主炮终极", "family": "主炮", "effect": "主炮伤害+80%，进化为终极大招"},
        {"name": "光线易伤", "family": "光线", "effect": "被光线命中的敌人受伤+25%"},
    ],
}
_LEVELS = {"carry": 47, "amp1": 12, "amp2": 30, "amp3": 8}


def test_carry_priority_overrides_highest_archive_rule():
    roles = assign_skill_roles(
        ["carry", "amp1", "amp2", "amp3"],
        _LEVELS,
        skill_labels=_CARRY_LABELS,
        knowledge_doc=_CARRY_KNOWLEDGE,
        carry_priority="光线",
    )
    carry = next(r for r in roles if r.role is SkillRole.CARRY)
    assert carry.code == "amp1"


def test_missing_carry_priority_keeps_archive_rule():
    roles = assign_skill_roles(
        ["carry", "amp1", "amp2", "amp3"],
        _LEVELS,
        skill_labels=_CARRY_LABELS,
        knowledge_doc=_CARRY_KNOWLEDGE,
        carry_priority="不存在的系",
    )
    carry = next(r for r in roles if r.role is SkillRole.CARRY)
    assert carry.code == "carry"


# ---- 偏好中性 oracle：偏好空 vs 非空，决策流除候选顺序外逐字节一致 ----

from dataclasses import replace as _dc_replace

from shuabao.choice_policy import (
    PolicyAction,
    PanelCandidates,
    SessionState,
    choose_action,
    slot_fingerprint,
)

_BASE_SETTINGS = PolicySettings(
    skill_focus_families=FOCUS,
    skill_fill_empty_slots=True,
)
# 非空偏好：族优先级 + 路线 prefer/avoid（同时激活 4 系时的角色桶 carry_priority）。
_LOADED_SETTINGS = PolicySettings(
    skill_focus_families=FOCUS,
    skill_fill_empty_slots=True,
    skill_priority=("光线", "剑气"),
    skill_route_preferences=(("剑气", "damage", ("伤害+",), ("易伤",)),),
)


def _panel(step: int, refresh_count: int = 0) -> PanelCandidates:
    """确定性面板序列：覆盖 SELECT / WAIT×2→CLOSE / 非焦点 CLOSE / 低置信跳过。"""
    if step % 4 == 0:
        slots = tuple(
            SlotCandidate(index=i, family=fam, confidence=0.99)
            for i, fam in enumerate(FOCUS)
        )
    elif step % 4 == 1:
        # 全部卡名未读出 → WAIT, WAIT, CLOSE。
        slots = tuple(SlotCandidate(index=i, confidence=0.95) for i in range(3))
    elif step % 4 == 2:
        # 可读但全部非焦点系 → CLOSE。
        slots = (
            SlotCandidate(index=0, family="碎冰", name="碎冰·壹", confidence=0.99),
            SlotCandidate(index=1, family="湮灭斩", name="湮灭斩·贰", confidence=0.99),
        )
    else:
        # 一个低置信 + 一个焦点系 → 只允许从合法焦点系里选。
        slots = (
            SlotCandidate(index=0, family="碎冰", confidence=0.30),
            SlotCandidate(index=1, family="剑气", confidence=0.99),
        )
    return PanelCandidates(
        panel_kind="skill",
        slots=slots,
        settings=_BASE_SETTINGS,
        refresh_count=refresh_count,
    )


def _drive_episode(steps: int, settings: PolicySettings):
    """按执行层语义推进状态机，返回 (动作迹, 终态)。"""
    state = SessionState()
    trace: list[tuple[str, int | None, str]] = []
    for step in range(steps):
        cands = _panel(step, refresh_count=state.refreshes)
        slots = cands.slots
        decision = choose_action(cands, state)
        is_select = decision.action is PolicyAction.SELECT_SLOT
        trace.append((
            decision.action.value,
            decision.index if is_select else None,
            "" if is_select else decision.reason,
        ))
        if is_select:
            state = _dc_replace(
                state,
                attempts=state.attempts + 1,
                last_slot_fingerprint=slot_fingerprint(slots),
            )
        elif decision.action is PolicyAction.REFRESH:
            state = _dc_replace(state, refreshes=state.refreshes + 1)
        elif decision.action is PolicyAction.WAIT:
            state = _dc_replace(state, waits=state.waits + 1)
        else:
            break
    return trace, state


def test_preference_neutral_decision_stream():
    """铁律：偏好非空只改 SELECT 槽位序；动作种类/理由/预算逐字节一致。"""
    empty_trace, empty_state = _drive_episode(12, _BASE_SETTINGS)
    loaded_trace, loaded_state = _drive_episode(12, _LOADED_SETTINGS)
    assert len(empty_trace) == len(loaded_trace)
    for step, ((e_act, e_idx, e_why), (l_act, l_idx, l_why)) in enumerate(
        zip(empty_trace, loaded_trace)
    ):
        assert e_act == l_act
        if e_act == PolicyAction.SELECT_SLOT.value:
            # 槽位可不同，但两者都必须是该面板的合法候选序。
            legal = set(_rank_skill_candidates(_panel(step).slots, _BASE_SETTINGS, ()))
            assert e_idx in legal and l_idx in legal
        else:
            assert (e_idx, e_why) == (l_idx, l_why)
    assert (empty_state.attempts, empty_state.waits, empty_state.refreshes) == (
        loaded_state.attempts,
        loaded_state.waits,
        loaded_state.refreshes,
    )


def test_preference_neutral_single_step_grid():
    """单步矩阵：任意 (面板, 会话态) 组合下，偏好只影响 SELECT 的槽位。"""
    session_variants = [
        SessionState(),
        SessionState(waits=2),
        SessionState(attempts=SessionState.max_attempts),
        SessionState(deadline_exceeded=True),
        SessionState(refreshes=2),
    ]
    for step in range(8):
        cands = _panel(step)
        for session in session_variants:
            base = choose_action(cands, session)
            loaded_cands = PanelCandidates(
                panel_kind=cands.panel_kind,
                slots=cands.slots,
                settings=_LOADED_SETTINGS,
                owned_skill_cards=cands.owned_skill_cards,
            )
            loaded = choose_action(loaded_cands, session)
            assert base.action == loaded.action
            if base.action is not PolicyAction.SELECT_SLOT:
                assert (base.index, base.reason) == (loaded.index, loaded.reason)


def test_preferences_never_touch_non_skill_panels():
    """宝物/羁绊面板对偏好完全无感：含 reason 在内逐字节一致。"""
    treasure_slots = (
        SlotCandidate(index=0, name="宝物甲", rarity="purple", confidence=0.99),
        SlotCandidate(index=1, name="宝物乙", rarity="blue", confidence=0.99),
    )
    bond_slots = (
        SlotCandidate(index=0, name="羁绊甲", confidence=0.99),
        SlotCandidate(index=1, name="羁绊乙", confidence=0.99),
    )
    for kind, slots in (("treasure", treasure_slots), ("bond", bond_slots)):
        for session in (SessionState(), SessionState(waits=1)):
            a = choose_action(
                PanelCandidates(panel_kind=kind, slots=slots, settings=_BASE_SETTINGS),
                session,
            )
            b = choose_action(
                PanelCandidates(panel_kind=kind, slots=slots, settings=_LOADED_SETTINGS),
                session,
            )
            assert (a.action, a.index, a.reason) == (b.action, b.index, b.reason)
