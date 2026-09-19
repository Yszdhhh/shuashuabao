#!/usr/bin/env python3
"""Check the real profile/Settings/policy contract without importing the game runtime."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.choice_policy import assemble_policy_settings
from shuabao.settings import Settings
from shuabao.shell.test_profiles import apply_profile, load_test_profiles


def main() -> int:
    report = {
        "offline_contract": "FAIL",
        "dashboard_readiness": "BLOCKED",
        "gt_readiness": "BLOCKED",
        "scope": "Settings/policy only; no Dashboard roundtrip, game capture or input",
    }
    try:
        profile = next(
            item for item in load_test_profiles(ROOT / "config/dashboard_test_profiles.json")
            if item["name"] == "海盗+亡灵机制GT"
        )
        policy_doc = json.loads((ROOT / "config/choice_policy.json").read_text(encoding="utf-8"))
        labels = {
            name: json.loads((ROOT / "config" / f"{name}.json").read_text(encoding="utf-8"))
            for name in ("skill_labels", "fetter_labels")
        }
        before = Settings(bonds=["贪婪"], attributes=["力量"], skills=["jq", "pg"])
        applied = apply_profile(before, profile)
        settings = Settings._from_dict(asdict(applied))
        policy = assemble_policy_settings(settings=settings, policy_doc=policy_doc, **labels)
        defaults = assemble_policy_settings(settings=Settings(), policy_doc=policy_doc, **labels)
        expected_groups = tuple(
            tuple(next(group for group in policy_doc["bond"]["advanced_groups"] if name in group))
            for name in ("海盗", "宝藏", "亡灵")
        )
        assert settings.bonds == ["祝福", "成长", "经济", "挑战"] and settings.attributes == [], "Old selections survived apply/persistence"
        assert before.bonds == ["贪婪"] and before.attributes == ["力量"], "Profile mutated caller Settings"
        assert settings.skills == before.skills, "Profile replaced the user's skills"
        # 同一局覆盖战后自动大秘境正式链路，仍走 Settings.auto_secret_realm。
        assert settings.cycle_num == 1 and settings.auto_secret_realm is True, "GT did not enable same-run post-battle auto secret realm"
        assert policy.bond_advanced_groups == expected_groups, "Existing advanced group order changed"
        assert set(policy.bond_base_presets) == {"祝福", "成长", "经济", "挑战", "藏宝图(三)"}, "Unexpected base selection"
        assert policy.bond_base_presets[:4] == ("祝福", "成长", "经济", "挑战"), "Bond base order violates priority"
        assert not policy.bond_chain_presets, "Old attribute chain leaked into policy"
        assert "藏宝图(三)" in policy.bond_must_take, "Starter lost must-take priority"
        assert (defaults.bond_base_completion_ratio, defaults.bond_advanced_unlock_s) == (0.8, 480.0), "Production defaults changed"
        assert (policy.bond_base_completion_ratio, policy.bond_advanced_unlock_s) == (0.0, 60.0), "Profile override not assembled"
        assert policy.min_confidence == defaults.min_confidence and policy.bond_whitelist_mode == defaults.bond_whitelist_mode == "hard", "Safety policy weakened"
        fields = (
            "bond_base_presets", "bond_advanced_groups", "bond_chain_presets", "bond_must_take",
            "bond_base_completion_ratio", "bond_advanced_unlock_s", "min_confidence", "bond_whitelist_mode",
        )
        report.update({
            "offline_contract": "PASS",
            "profile": profile["name"],
            "settings": {key: getattr(settings, key) for key in profile["settings"]},
            "skills_preserved": settings.skills,
            "inherited_selections": {
                "before": {"bonds": before.bonds, "attributes": before.attributes},
                "after": {"bonds": settings.bonds, "attributes": settings.attributes},
            },
            "policy": {key: {"value": getattr(policy, key), "type": type(getattr(policy, key)).__name__} for key in fields},
            "production_defaults": {
                "bond_base_completion_ratio": defaults.bond_base_completion_ratio,
                "bond_advanced_unlock_s": defaults.bond_advanced_unlock_s,
            },
            "starter": {"canonical": "藏宝图(三)", "classification": "base", "must_take": True},
        })
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["offline_contract"] == "PASS" else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
