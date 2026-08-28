"""habit_preference + choice_policy 习惯分 tie-break。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.choice_policy import (  # noqa: E402
    PANEL_SKILL,
    PanelCandidates,
    PolicyAction,
    PolicySettings,
    SessionState,
    SlotCandidate,
    choose_action,
)
from shuabao.habit_preference import (  # noqa: E402
    append_learning_observation,
    default_habit_path,
    habit_scores_for_panel,
    load_habit_preference,
    merge_habit_into_mapping,
    observations_to_name_scores,
)


class HabitLoadTests(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        missing = Path(tempfile.gettempdir()) / "shuabao_habit_missing.json"
        if missing.exists():
            missing.unlink()
        data = load_habit_preference(missing)
        self.assertEqual(data.get("version"), 1)
        self.assertEqual(data.get("panels"), {})

    def test_scores_for_panel(self):
        habit = {
            "version": 1,
            "panels": {"skill": {"name_scores": {"奥数箭": 3, "剑气": 1}}},
        }
        scores = dict(habit_scores_for_panel(habit, "skill"))
        self.assertEqual(scores["奥数箭"], 3.0)
        self.assertEqual(habit_scores_for_panel(habit, "bond"), ())


class HabitTieBreakTests(unittest.TestCase):
    def test_empty_habit_same_as_before(self):
        slots = (
            SlotCandidate(0, "奥数箭", 0.9, rarity="blue"),
            SlotCandidate(1, "剑气", 0.9, rarity="blue"),
        )
        base = PolicySettings(skill_presets=("奥数箭", "剑气"))
        with_habit = PolicySettings(
            skill_presets=("奥数箭", "剑气"),
            habit_name_scores=(),
        )
        panel = PanelCandidates(panel_kind=PANEL_SKILL, slots=slots, settings=base)
        a = choose_action(panel, SessionState())
        panel2 = PanelCandidates(panel_kind=PANEL_SKILL, slots=slots, settings=with_habit)
        b = choose_action(panel2, SessionState())
        self.assertEqual(a, b)
        self.assertEqual(a.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(a.index, 0)

    def test_habit_breaks_tie_within_preset(self):
        """同稀有度时，习惯分更高的预设技能优先（仍必须在 presets 内）。"""
        slots = (
            SlotCandidate(0, "奥数箭", 0.9, rarity="blue"),
            SlotCandidate(1, "剑气", 0.9, rarity="blue"),
        )
        settings = PolicySettings(
            skill_presets=("奥数箭", "剑气"),
            habit_name_scores=(("剑气", 10.0), ("奥数箭", 1.0)),
        )
        panel = PanelCandidates(panel_kind=PANEL_SKILL, slots=slots, settings=settings)
        decision = choose_action(panel, SessionState())
        self.assertEqual(decision.action, PolicyAction.SELECT_SLOT)
        self.assertEqual(decision.index, 1)

    def test_habit_cannot_select_outside_presets(self):
        slots = (
            SlotCandidate(0, "天雷", 0.99, rarity="red"),
            SlotCandidate(1, "奥数箭", 0.9, rarity="blue"),
        )
        settings = PolicySettings(
            skill_presets=("奥数箭",),
            habit_name_scores=(("天雷", 999.0),),
        )
        panel = PanelCandidates(panel_kind=PANEL_SKILL, slots=slots, settings=settings)
        decision = choose_action(panel, SessionState())
        self.assertEqual(decision.index, 1)

    def test_merge_helper(self):
        merged = merge_habit_into_mapping(
            {"skill_presets": ["奥数箭"]},
            {"panels": {"skill": {"name_scores": {"奥数箭": 2}}}},
            "skill",
        )
        self.assertEqual(merged["habit_name_scores"]["奥数箭"], 2.0)

    def test_habit_path_uses_shuabao_appdata(self):
        self.assertTrue(str(default_habit_path()).replace("\\", "/").endswith("ShuaBao/habit_preference.json"))

    def test_append_learning_observation_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "obs.jsonl"
            written = append_learning_observation(
                {
                    "panel_kind": "skill",
                    "event": "choice_decision",
                    "slots": [{"index": 0, "name": "奥数箭"}],
                    "decision": {"action": "SELECT_SLOT", "index": 0},
                },
                path=path,
            )
            self.assertEqual(written, path)
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(1, len(rows))
            self.assertEqual("learning", rows[0]["mode"])
            self.assertEqual("skill", rows[0]["panel_kind"])
            self.assertIn("ts", rows[0])

    def test_observations_to_name_scores(self):
        records = [
            {
                "panel_kind": "skill",
                "slots": [{"index": 0, "name": "奥数箭"}, {"index": 1, "name": "剑气"}],
                "decision": {"action": "SELECT_SLOT", "index": 1},
            },
            {
                "panel_kind": "skill",
                "slots": [{"index": 0, "name": "剑气"}],
                "decision": {"action": "SELECT_SLOT", "index": 0},
            },
            {
                "panel_kind": "bond",
                "slots": [{"index": 0, "name": "海盗"}],
                "decision": {"action": "SELECT_SLOT", "index": 0},
            },
        ]
        scores = observations_to_name_scores(records, "skill")
        self.assertEqual(scores["剑气"], 2.0)
        self.assertNotIn("奥数箭", scores)
        self.assertEqual(observations_to_name_scores(records, "bond")["海盗"], 1.0)


if __name__ == "__main__":
    unittest.main()
