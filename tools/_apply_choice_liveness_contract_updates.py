from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_regression_import_and_default() -> None:
    path = ROOT / "tests/test_choice_liveness_20260818.py"
    replace_once(
        path,
        "from shuabao.vision import Frame",
        "from shuabao.vision.capture import Frame",
        "choice liveness Frame import",
    )

    path = ROOT / "tests/test_choice_policy.py"
    replace_once(
        path,
        "self.assertEqual(ps.bond_whitelist_mode, WHITELIST_HARD)",
        'self.assertEqual(ps.bond_whitelist_mode, "soft")',
        "runtime default whitelist is soft",
    )


def patch_semantics_contract() -> None:
    path = ROOT / "tests/contract/test_choice_semantics_contract.py"
    replace_once(
        path,
        '''class S2BondWhitelistIsHard(unittest.TestCase):
    """S2：羁绊未勾选 = 硬禁用；必须同时封住套装与品质两条旁路。"""
''',
        '''class S2BondWhitelistModes(unittest.TestCase):
    """S2：长程默认 soft；用户显式 hard 时仍封住套装与品质旁路。"""
''',
        "contract class documents soft default",
    )
    replace_once(
        path,
        '''                has_giveup=True,
                settings=PolicySettings(bond_presets=("暴击", "法术")),
''',
        '''                has_giveup=True,
                settings=PolicySettings(
                    bond_presets=("暴击", "法术"), bond_whitelist_mode="hard"
                ),
''',
        "explicit hard unchecked bond",
    )
    replace_once(
        path,
        '''            settings=PolicySettings(bond_presets=("暴击",)),
        ))
        self.assertIn(decision.action, NO_PICK_ACTIONS)

    def test_hard_ban_blocks_quality_bypass(self):
''',
        '''            settings=PolicySettings(
                bond_presets=("暴击",), bond_whitelist_mode="hard"
            ),
        ))
        self.assertIn(decision.action, NO_PICK_ACTIONS)

    def test_hard_ban_blocks_quality_bypass(self):
''',
        "explicit hard synthesis bypass",
    )
    replace_once(
        path,
        '''            [_slot(0, "海盗", rarity="red")],
            settings=PolicySettings(bond_presets=("暴击",)),
        ))
        self.assertIn(decision.action, NO_PICK_ACTIONS)

    def test_whitelisted_bond_is_still_selected(self):
''',
        '''            [_slot(0, "海盗", rarity="red")],
            settings=PolicySettings(
                bond_presets=("暴击",), bond_whitelist_mode="hard"
            ),
        ))
        self.assertIn(decision.action, NO_PICK_ACTIONS)

    def test_whitelisted_bond_is_still_selected(self):
''',
        "explicit hard quality bypass",
    )
    replace_once(
        path,
        '''            [_slot(0, "海盗", rarity="red"), _slot(1, "暴击", rarity="white")],
            settings=PolicySettings(bond_presets=("暴击",)),
        ))
''',
        '''            [_slot(0, "海盗", rarity="red"), _slot(1, "暴击", rarity="white")],
            settings=PolicySettings(
                bond_presets=("暴击",), bond_whitelist_mode="hard"
            ),
        ))
''',
        "explicit hard still selects whitelisted",
    )
    replace_once(
        path,
        '''    def test_soft_mode_still_available_for_explicit_opt_out(self):
        """soft 模式仍保留（宝物在用），但必须显式声明才生效。"""
        hard = PolicySettings(bond_presets=())
        self.assertEqual(hard.bond_whitelist_mode, "hard", "默认必须是硬禁用")
        decision = choose_action(_panel(
            PANEL_BOND,
            [_slot(0, "海盗", rarity="red")],
            settings=PolicySettings(bond_presets=(), bond_whitelist_mode="soft"),
        ))
        self.assertEqual(decision.action, PolicyAction.SELECT_SLOT)
''',
        '''    def test_soft_is_default_and_explicit_hard_still_available(self):
        """长程默认 soft 保进度；用户显式 hard 时仍可禁止预设外羁绊。"""
        default = PolicySettings(bond_presets=())
        self.assertEqual(default.bond_whitelist_mode, "soft")
        soft_decision = choose_action(_panel(
            PANEL_BOND,
            [_slot(0, "海盗", rarity="red")],
            settings=default,
        ))
        self.assertEqual(soft_decision.action, PolicyAction.SELECT_SLOT)
        hard_decision = choose_action(_panel(
            PANEL_BOND,
            [_slot(0, "海盗", rarity="red")],
            settings=PolicySettings(bond_presets=(), bond_whitelist_mode="hard"),
        ))
        self.assertIn(hard_decision.action, NO_PICK_ACTIONS)
''',
        "contract soft default and explicit hard",
    )


def patch_wiring_contract() -> None:
    path = ROOT / "tests/contract/test_choice_policy_wiring_contract.py"
    replace_once(
        path,
        "- 羁绊硬禁用切断品质色/第一张旁路",
        "- 羁绊显式 hard 时切断品质色/第一张旁路；默认 soft 由语义契约覆盖",
        "wiring contract doc",
    )
    replace_once(
        path,
        "class A3BondHardDisableCutsBypass(unittest.TestCase):",
        "class A3ExplicitBondHardDisableCutsBypass(unittest.TestCase):",
        "wiring contract class name",
    )
    replace_once(
        path,
        'med = Mediator(Settings(ocr_mode="live", cards=[]), ROOT)',
        'med = Mediator(Settings(ocr_mode="live", cards=[], bond_whitelist_mode="hard"), ROOT)',
        "wiring contract explicit hard",
    )


def main() -> None:
    patch_regression_import_and_default()
    patch_semantics_contract()
    patch_wiring_contract()
    print("choice liveness test contracts aligned")


if __name__ == "__main__":
    main()
