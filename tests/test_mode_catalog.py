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

from shuabao.settings import Settings  # noqa: E402
from shuabao.shell.mode_catalog import (  # noqa: E402
    ModeSpec,
    apply_mode_overlay,
    get_spec,
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
        # normal_farm.budgets.round_timeout_s=3600 是真实 Settings 字段 → 必须生效。
        # 20260822：900→3600，长线程刷图以打完 Boss 为界，15 分钟硬上限会在局中强退。
        out = apply_mode_overlay(Settings(round_timeout_s=123), "normal_farm")
        self.assertEqual(out.round_timeout_s, 3600)
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
        self.assertEqual(out.mode_id, "lobby_hitch")
        self.assertFalse(out.auto_create_room)

    def test_hidden_defaults_win_on_conflict(self):
        # 同一键同时出现在 budgets 与 hidden_defaults → hidden_defaults 优先。
        spec = _spec(
            hidden_defaults={"round_timeout_s": 60},
            budgets={"round_timeout_s": 3600},
        )
        with patch("shuabao.shell.mode_catalog.get_spec", return_value=spec):
            out = apply_mode_overlay(Settings(round_timeout_s=900), "test")
        self.assertEqual(out.round_timeout_s, 60)

    def test_bad_string_budget_falls_back_to_base_value(self):
        # 损坏的非数字字符串预算不得进入 runtime：round_timeout_s="bad" 回落到 base 值 900。
        spec = _spec(budgets={"round_timeout_s": "bad"})
        with patch("shuabao.shell.mode_catalog.get_spec", return_value=spec):
            out = apply_mode_overlay(Settings(round_timeout_s=900), "test")
        self.assertEqual(out.round_timeout_s, 900)

    def test_out_of_range_budget_clamped_by_settings_validation(self):
        # 越界 budget 值被 Settings._from_dict 集中清洗钳制到 safe 区间。
        spec = _spec(budgets={"round_timeout_s": 1, "recovery_action_limit": 999})
        with patch("shuabao.shell.mode_catalog.get_spec", return_value=spec):
            out = apply_mode_overlay(Settings(), "test")
        self.assertEqual(out.round_timeout_s, 60)        # <60 → 60
        self.assertEqual(out.recovery_action_limit, 10)  # >10 → 10

    def test_numeric_string_budget_coerced_to_int(self):
        # 数字字符串预算被 Settings._from_dict 清洗强制转为 int。
        spec = _spec(budgets={"round_timeout_s": "900"})
        with patch("shuabao.shell.mode_catalog.get_spec", return_value=spec):
            out = apply_mode_overlay(Settings(round_timeout_s=123), "test")
        self.assertEqual(out.round_timeout_s, 900)
        self.assertIsInstance(out.round_timeout_s, int)

    def test_invalid_hidden_default_falls_back_to_base(self):
        # 损坏的 hidden_default 回落到 base 值，不会崩溃或以 dataclass 默认值覆盖用户 base。
        # 覆盖 invalid [] / {} / None / bad_string。这是 fallback 保留 base 的覆盖，
        # 不是声称 32633f4 无 fallback 下所有 invalid bool 都会红：未知字符串回落
        # dataclass default True，只有 [] / {} / None 经 bool(v) 变成 False。
        for invalid in ([], {}, None, "invalid_bool"):
            with self.subTest(invalid=invalid):
                spec = _spec(hidden_defaults={"auto_create_room": invalid})
                with patch("shuabao.shell.mode_catalog.get_spec", return_value=spec):
                    out = apply_mode_overlay(Settings(auto_create_room=False), "test")
                self.assertFalse(out.auto_create_room)

        # 同时保留合法 False 与 True 叠加
        spec_false = _spec(hidden_defaults={"auto_create_room": False})
        with patch("shuabao.shell.mode_catalog.get_spec", return_value=spec_false):
            out_false = apply_mode_overlay(Settings(auto_create_room=True), "test")
        self.assertFalse(out_false.auto_create_room)

        spec_true = _spec(hidden_defaults={"auto_create_room": True})
        with patch("shuabao.shell.mode_catalog.get_spec", return_value=spec_true):
            out_true = apply_mode_overlay(Settings(auto_create_room=False), "test")
        self.assertTrue(out_true.auto_create_room)

    def test_invalid_overlay_types_fall_back_to_base(self):
        # 验证 bool/int/string/dict/ocr 在 overlay 为 invalid [] / {} / None / bad types 时均保留 base
        base = Settings(
            auto_create_room=False,
            round_timeout_s=123,
            room_name="base_room",
            skill_archive_levels={"asj": 10},
            ocr_mode="live",
        )
        # 1. invalid [] / {} / None / bad string for bool
        for bad_bool in ([], {}, None, "not_a_bool"):
            with self.subTest(bad_bool=bad_bool):
                spec = _spec(hidden_defaults={"auto_create_room": bad_bool})
                with patch("shuabao.shell.mode_catalog.get_spec", return_value=spec):
                    out = apply_mode_overlay(base, "test")
                self.assertFalse(out.auto_create_room)

        # 2. invalid [] / {} / None / bad string for int
        for bad_int in ([], {}, None, "bad_int"):
            with self.subTest(bad_int=bad_int):
                spec = _spec(budgets={"round_timeout_s": bad_int})
                with patch("shuabao.shell.mode_catalog.get_spec", return_value=spec):
                    out = apply_mode_overlay(base, "test")
                self.assertEqual(out.round_timeout_s, 123)

        # 3. invalid [] / {} / None / numeric for string
        for bad_str in ([], {}, None, 12345):
            with self.subTest(bad_str=bad_str):
                spec = _spec(hidden_defaults={"room_name": bad_str})
                with patch("shuabao.shell.mode_catalog.get_spec", return_value=spec):
                    out = apply_mode_overlay(base, "test")
                self.assertEqual(out.room_name, "base_room")

        # 4. invalid [] / None / bad type for dict (skill_archive_levels)
        for bad_dict in ([], None, "not_a_dict", 123):
            with self.subTest(bad_dict=bad_dict):
                spec = _spec(hidden_defaults={"skill_archive_levels": bad_dict})
                with patch("shuabao.shell.mode_catalog.get_spec", return_value=spec):
                    out = apply_mode_overlay(base, "test")
                self.assertEqual(out.skill_archive_levels, {"asj": 10})

        # 5. invalid [] / {} / None / bad string for ocr_mode
        for bad_ocr in ([], {}, None, "invalid_ocr_mode", 123):
            with self.subTest(bad_ocr=bad_ocr):
                spec = _spec(hidden_defaults={"ocr_mode": bad_ocr})
                with patch("shuabao.shell.mode_catalog.get_spec", return_value=spec):
                    out = apply_mode_overlay(base, "test")
                self.assertEqual(out.ocr_mode, "live")

    def test_invalid_overlay_keeps_true_auto_create_room(self):
        # 32633f4 无 fallback：[] / {} / None 经 bool(v) 把 auto_create_room=True 盖成 False。
        # apply_mode_overlay 必须走 fallback，invalid 值不得改写用户 True。
        for invalid in ([], {}, None):
            with self.subTest(invalid=invalid):
                spec = _spec(hidden_defaults={"auto_create_room": invalid})
                with patch("shuabao.shell.mode_catalog.get_spec", return_value=spec):
                    out = apply_mode_overlay(Settings(auto_create_room=True), "test")
                self.assertTrue(out.auto_create_room)

    def test_overlay_does_not_reclean_unrelated_fields(self):
        # overlay 只允许改变命名字段：stage1=0 是 base 用户值，overlay 没碰它，
        # 不得被全量 asdict 重清洗成 1（_from_dict 的 stage1 区间钳制下限是 1）。
        spec = _spec(budgets={"round_timeout_s": 900})
        with patch("shuabao.shell.mode_catalog.get_spec", return_value=spec):
            out = apply_mode_overlay(Settings(stage1=0, round_timeout_s=123), "test")
        self.assertEqual(0, out.stage1)
        self.assertEqual(900, out.round_timeout_s)

    def test_real_mode_overlay_preserves_unrelated_stage1(self):
        # 真实模式叠加同样只改命名字段：normal_farm 只消费 round_timeout_s /
        # game_mode / auto_create_room，stage1=0 必须保留。
        out = apply_mode_overlay(Settings(stage1=0), "normal_farm")
        self.assertEqual(0, out.stage1)
        self.assertEqual(3600, out.round_timeout_s)
        self.assertEqual(0, out.game_mode)
        self.assertTrue(out.auto_create_room)

    def test_hitch_dashboard_contract_exposes_bosses_and_search_terms(self):
        spec = get_spec("lobby_hitch")
        self.assertEqual(Settings().hitch_stage_prefix, "4,3,速")
        self.assertTrue({"hitch_stage_prefix", "cjb_boss", "sgzx_boss"}.issubset(spec.visible_settings))
        selected = apply_mode_overlay(
            Settings(hitch_stage_prefix="自定义主搜,自定义副搜", cjb_boss="01暴掠龙", sgzx_boss="08巨形缝合怪"),
            "lobby_hitch",
        )
        self.assertEqual(selected.hitch_stage_prefix, "自定义主搜,自定义副搜")
        self.assertEqual(selected.cjb_boss, "01暴掠龙")
        self.assertEqual(selected.sgzx_boss, "08巨形缝合怪")


if __name__ == "__main__":
    unittest.main()
