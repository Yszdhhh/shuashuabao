from shuabao.bond_capacity import CapacityAction, decide_bond_capacity


def test_full_bar_replaces_only_a_non_plan_card():
    decision = decide_bond_capacity(
        ("修仙", "异火", "路人", "路人甲", "路人乙", "路人丙", "路人丁", "路人戊", "路人己", "路人庚"),
        "修仙",
        on_replace_ui=True,
        merchant_exhausted=True,
        protected_names=("修仙", "异火"),
    )
    assert decision.action is CapacityAction.REPLACE_THEN_MERGE
    assert decision.replace_index == 2


def test_full_bar_abandons_when_every_card_belongs_to_the_plan():
    decision = decide_bond_capacity(
        ("修仙", "异火", "修仙", "异火", "修仙", "异火", "修仙", "异火", "修仙", "异火"),
        "修仙",
        on_replace_ui=True,
        merchant_exhausted=True,
        protected_names=("修仙", "异火"),
    )
    assert decision.action is CapacityAction.ABANDON
