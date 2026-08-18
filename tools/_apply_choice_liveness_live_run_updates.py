from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    path = ROOT / "tests/test_live_run_205044_regressions.py"
    replace_once(
        path,
        '''    def test_skill_ocr_never_authorizes_nonconfigured_same_icon(self) -> None:
        med = Mediator(Settings(skills=["assx"]), ROOT)
        slots = [
            {"index": 0, "name": "电磁网", "confidence": 0.99, "raw_text": "电磁网", "family_source": "badge"},
            {"index": 1, "name": "重创", "confidence": 0.99, "raw_text": "重创", "family_source": "badge"},
            {"index": 2, "name": None, "confidence": 0.0, "raw_text": "多重射线", "family_source": "badge"},
        ]
        with patch.object(med, "_ocr_panel_slots", return_value=slots):
            self.assertIsNone(med._ocr_reward_choice(frame(), "skill"))

        slots[2] = {"index": 2, "name": "奥数射线", "confidence": 0.99, "raw_text": "奥数射线", "family_source": "badge"}
        with patch.object(med, "_ocr_panel_slots", return_value=slots):
            hit = med._ocr_reward_choice(frame(), "skill")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "assx")
        self.assertEqual(hit.x, int(1600 * 0.646))
''',
        '''    def test_skill_ocr_safe_fill_never_masquerades_same_icon_as_configured(self) -> None:
        med = Mediator(Settings(skills=["assx"]), ROOT)
        slots = [
            {"index": 0, "name": "电磁网", "confidence": 0.99, "raw_text": "电磁网", "family_source": "badge"},
            {"index": 1, "name": "重创", "confidence": 0.99, "raw_text": "重创", "family_source": "badge"},
            {"index": 2, "name": None, "confidence": 0.0, "raw_text": "多重射线", "family_source": "badge"},
        ]
        with patch.object(med, "_ocr_panel_slots", return_value=slots):
            fill_hit = med._ocr_reward_choice(frame(), "skill")
        # 未读成奥数射线时，同图标/原始文本不得冒充配置技能 assx；
        # 但四技能槽未满允许从已验证目录中的合法技能安全补位。
        self.assertIsNotNone(fill_hit)
        self.assertEqual(fill_hit.name, "重创")
        self.assertNotEqual(fill_hit.name, "assx")

        slots[2] = {"index": 2, "name": "奥数射线", "confidence": 0.99, "raw_text": "奥数射线", "family_source": "badge"}
        with patch.object(med, "_ocr_panel_slots", return_value=slots):
            hit = med._ocr_reward_choice(frame(), "skill")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "assx")
        self.assertEqual(hit.x, int(1600 * 0.646))
''',
        "pre-four-slot safe fill keeps exact preset identity boundary",
    )
    replace_once(
        path,
        'med = Mediator(Settings(cards=["祝福"]), ROOT)',
        'med = Mediator(Settings(cards=["祝福"], bond_whitelist_mode="hard"), ROOT)',
        "full bar historical hard whitelist",
    )
    replace_once(
        path,
        'med = Mediator(Settings(cards=["法术"]), ROOT)',
        'med = Mediator(Settings(cards=["法术"], bond_whitelist_mode="hard"), ROOT)',
        "basic bond historical hard whitelist",
    )
    replace_once(
        path,
        '''    def test_early_bond_does_not_start_pirate_or_undead_variants(self) -> None:
        med = Mediator(Settings(), ROOT)
''',
        '''    def test_early_bond_does_not_start_pirate_or_undead_variants(self) -> None:
        med = Mediator(Settings(bond_whitelist_mode="hard"), ROOT)
''',
        "early bond historical hard whitelist",
    )
    replace_once(
        path,
        'med = Mediator(Settings(cards=["亡灵天灾"]), ROOT)',
        'med = Mediator(Settings(cards=["亡灵天灾"], bond_whitelist_mode="hard"), ROOT)',
        "advanced bond historical hard whitelist",
    )
    print("legacy live-run choice regressions aligned")


if __name__ == "__main__":
    main()
