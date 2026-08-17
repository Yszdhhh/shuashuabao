"""mode_catalog 应用模式叠加层单测。

apply_mode_overlay 只消费 mode_specs.json 中真实 Settings 字段：
hidden_defaults 与 budgets 都要生效；未知键一律忽略；冲突时
hidden_defaults 优先（显式默认压过预算推导）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gamescript.settings import Settings  # noqa: E402
from gamescript.shell.mode_catalog import (  # noqa: E402
    ModeSpec,
    apply_mode_overlay,
)


def _spec(**kw) -> ModeSpec:
    base = dict(
        id="test",
        label="t",
        live_enabled=False,
        desktop_start=False,
        flow="",
        visible_settings=(),
        hidden_defaults={},
        forbidden_actions=(),
        budgets={},
        evidence_status="",
        notes="",
    )
    base.update(kw)
    return ModeSpec(**base)


class ApplyModeOverlayTests(unittest.TestCase):
    def test_budgets_round_timeout_applied(self):
        # normal_farm.budgets.round_timeout_s=900 是真实 Settings 字段 → 必须生效。
        out = apply_mode_overlay(Settings(round_timeout_s=123), "normal_farm")
        self.assertEqual(out.round_timeout_s, 900)
        self.assertEqual(out.game_mode, 0)
        self.assertTrue(out.auto_create_room)

    def test_unknown_budget_keys_ignored(self):
        # follow_team.budgets.wait_room_start_s 不是 Settings 字段 → 忽略不崩。
        out = apply_mode_overlay(Settings(round_timeout_s=900), "follow_team")
        self.assertEqual(out.round_timeout_s, 900)
        self.assertFalse(out.auto_create_room)

    def test_unknown_hidden_defaults_ignored(self):
        # lobby_hitch.hidden_defaults.hitch_reject_list（dict）不是 Settings 字段 → 忽略。
        out = apply_mode_overlay(Settings(), "lobby_hitch")
        self.assertEqual(out.game_mode, 0)

    def test_hidden_defaults_win_on_conflict(self):
        # 同一键同时出现在 budgets 与 hidden_defaults → hidden_defaults 优先。
        spec = _spec(
            hidden_defaults={"round_timeout_s": 60},
            budgets={"round_timeout_s": 3600},
        )
        with patch("gamescript.shell.mode_catalog.get_spec", return_value=spec):
            out = apply_mode_overlay(Settings(round_timeout_s=900), "test")
        self.assertEqual(out.round_timeout_s, 60)

    def test_bad_string_budget_falls_back_to_base_value(self):
        # 损坏的非数字字符串预算不得进入 runtime：round_timeout_s="bad" 回落到 base 值 900。
        spec = _spec(budgets={"round_timeout_s": "bad"})
        with patch("gamescript.shell.mode_catalog.get_spec", return_value=spec):
            out = apply_mode_overlay(Settings(round_timeout_s=900), "test")
        self.assertEqual(out.round_timeout_s, 900)

    def test_out_of_range_budget_clamped_by_settings_validation(self):
        # 越界 budget 值被 Settings._from_dict 集中清洗钳制到 safe 区间。
        spec = _spec(budgets={"round_timeout_s": 1, "recovery_action_limit": 999})
        with patch("gamescript.shell.mode_catalog.get_spec", return_value=spec):
            out = apply_mode_overlay(Settings(), "test")
        self.assertEqual(out.round_timeout_s, 60)        # <60 → 60
        self.assertEqual(out.recovery_action_limit, 10)  # >10 → 10

    def test_numeric_string_budget_coerced_to_int(self):
        # 数字字符串预算被 Settings._from_dict 清洗强制转为 int。
        spec = _spec(budgets={"round_timeout_s": "900"})
        with patch("gamescript.shell.mode_catalog.get_spec", return_value=spec):
            out = apply_mode_overlay(Settings(round_timeout_s=123), "test")
        self.assertEqual(out.round_timeout_s, 900)
        self.assertIsInstance(out.round_timeout_s, int)

    def test_invalid_hidden_default_falls_back_to_base(self):
        # 损坏的 hidden_default 回落到 base 值，不会崩溃或赋予非法类型。
        spec = _spec(hidden_defaults={"auto_create_room": "invalid_bool"})
        with patch("gamescript.shell.mode_catalog.get_spec", return_value=spec):
            out = apply_mode_overlay(Settings(auto_create_room=True), "test")
        self.assertTrue(out.auto_create_room)

    def test_overlay_does_not_reclean_unrelated_fields(self):
        # overlay 只允许改变命名字段：stage1=0 是 base 用户值，overlay 没碰它，
        # 不得被全量 asdict 重清洗成 1（_from_dict 的 stage1 区间钳制下限是 1）。
        spec = _spec(budgets={"round_timeout_s": 900})
        with patch("gamescript.shell.mode_catalog.get_spec", return_value=spec):
            out = apply_mode_overlay(Settings(stage1=0, round_timeout_s=123), "test")
        self.assertEqual(0, out.stage1)
        self.assertEqual(900, out.round_timeout_s)

    def test_real_mode_overlay_preserves_unrelated_stage1(self):
        # 真实模式叠加同样只改命名字段：normal_farm 只消费 round_timeout_s /
        # game_mode / auto_create_room，stage1=0 必须保留。
        out = apply_mode_overlay(Settings(stage1=0), "normal_farm")
        self.assertEqual(0, out.stage1)
        self.assertEqual(900, out.round_timeout_s)
        self.assertEqual(0, out.game_mode)
        self.assertTrue(out.auto_create_room)


if __name__ == "__main__":
    unittest.main()
