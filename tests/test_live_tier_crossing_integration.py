import unittest
from shuabao.choice_policy import (
    choose_action,
    PolicySettings,
    SessionState,
    SlotCandidate,
    PanelCandidates,
    PolicyAction,
    PANEL_BOND,
)

def slot(index, name=None, confidence=0.95, rarity=None, description=""):
    return SlotCandidate(
        index=index,
        name=name,
        confidence=confidence,
        rarity=rarity,
        description=description,
    )

class TestLiveTierCrossingIntegration(unittest.TestCase):
    """Verify live Mediator passes set_progress and free_slots to ChoicePolicy."""

    def test_mediator_live_tier_crossing_and_slot_pressure_integration(self):
        st = PolicySettings.from_mapping({
            "cards": ["祝福", "成长"],
            "bonds": ["祝福", "成长"],
            "bond_must_take": ["祝福"],
        })
        sess = SessionState()

        # 祝福 is at 3 (tier-crossing to 4)
        cands = PanelCandidates(
            panel_kind=PANEL_BOND,
            slots=(
                slot(0, name="祝福之灵", rarity="white", confidence=0.95),
                slot(1, name="普通智力卡", rarity="purple", confidence=0.95),
            ),
            set_progress={"祝福": 3, "成长": 1},
            free_slots=1,
            settings=st,
        )

        decision = choose_action(cands, sess)
        self.assertEqual(decision.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(decision.index, 0)

    def test_mediator_slot_capped_zero_free_slots_refusal(self):
        st = PolicySettings.from_mapping({
            "cards": ["祝福"],
            "bonds": ["祝福"],
        })
        sess = SessionState(refreshes=3, max_refreshes=3)

        cands = PanelCandidates(
            panel_kind=PANEL_BOND,
            slots=(
                slot(0, name="陌生散卡A", rarity="purple", confidence=0.95),
                slot(1, name="陌生散卡B", rarity="blue", confidence=0.95),
            ),
            set_progress={"祝福": 2},
            free_slots=0,
            settings=st,
        )

        decision = choose_action(cands, sess)
        self.assertIn(decision.action, (PolicyAction.GIVEUP, PolicyAction.CLOSE, PolicyAction.WAIT))
        self.assertNotEqual(decision.action, PolicyAction.SELECT_SLOT)

if __name__ == "__main__":
    unittest.main()
