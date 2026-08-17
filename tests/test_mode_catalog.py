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


if __name__ == "__main__":
    unittest.main()
