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
    print("legacy live-run bond hard scenarios made explicit")


if __name__ == "__main__":
    main()
