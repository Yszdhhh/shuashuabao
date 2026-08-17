"""看板保存是实验室的玩法来源：缺文件必须失败，不能回落出厂默认。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from gamescript.settings import Settings
from lab_run import (
    LabConfigError,
    apply_lab_preset,
    format_lab_config_report,
    load_lab_settings,
    missing_dashboard_message,
    resolve_lab_config,
)


class ResolveLabConfigTests(unittest.TestCase):
    def test_explicit_config_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "probe.json"
            probe.write_text("{}", encoding="utf-8")
            path, source = resolve_lab_config(str(probe))
            self.assertEqual(path, probe)
            self.assertEqual(source, "显式文件")

    def test_dashboard_when_no_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dash = Path(tmp) / "ShuaBao" / "user_settings.json"
            dash.parent.mkdir(parents=True)
            dash.write_text('{"stage_targets":["1-12"]}', encoding="utf-8")
            with patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
                path, source = resolve_lab_config("")
            self.assertEqual(path, dash)
            self.assertEqual(source, "看板")

    def test_missing_dashboard_does_not_use_factory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
                with self.assertRaises(LabConfigError) as ctx:
                    resolve_lab_config("")
            message = str(ctx.exception)
            self.assertIn("控制室", message)
            self.assertIn("user_settings.json", message)
            self.assertNotIn("default_settings.json", message.split("禁止")[0])
            self.assertEqual(ctx.exception.code, 2)
            self.assertIn("default_settings.json", missing_dashboard_message())

    def test_missing_explicit_config_does_not_fall_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.json"
            dash = Path(tmp) / "ShuaBao" / "user_settings.json"
            dash.parent.mkdir(parents=True)
            dash.write_text("{}", encoding="utf-8")
            with patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
                with self.assertRaises(LabConfigError) as ctx:
                    resolve_lab_config(str(missing))
            self.assertIn("--config", str(ctx.exception))


class ApplyLabPresetDashboardTests(unittest.TestCase):
    def test_keeps_hero_mode_on(self) -> None:
        settings = apply_lab_preset(
            Settings(auto_reputation=True, continue_reputation=True),
            "skill,bond,treasure,reenter",
            games=1,
        )
        self.assertTrue(settings.auto_reputation)
        self.assertTrue(settings.continue_reputation)

    def test_keeps_stage_without_override(self) -> None:
        settings = apply_lab_preset(
            Settings(stage_targets=["1-12"], auto_reputation=False),
            "skill,bond,treasure,reenter",
            games=1,
        )
        self.assertEqual(settings.stage_targets, ["1-12"])

    def test_stage_flag_overrides(self) -> None:
        settings = apply_lab_preset(
            Settings(stage_targets=["1-12"]),
            "skill,bond,treasure,reenter",
            games=1,
            stage="1-8",
        )
        self.assertEqual(settings.stage_targets, ["1-8"])

    def test_games_none_keeps_cycle_num(self) -> None:
        settings = apply_lab_preset(
            Settings(cycle_num=7),
            "skill,bond,treasure,reenter",
            games=None,
        )
        self.assertEqual(settings.cycle_num, 7)

    def test_catalogs_fills_ex_exit_only_when_field_exists(self) -> None:
        settings = apply_lab_preset(
            Settings(),
            "skill,bond,treasure,reenter",
            games=1,
        )
        if hasattr(settings, "lab_exit_on_bond"):
            self.assertIn("解放的圣剑", settings.lab_exit_on_bond)
            self.assertEqual(settings.lab_exit_on_bond_count, 1)

    def test_load_lab_settings_truncates_skills_over_four(self):
        """lab_run 读取看板 5+ 技能：解析边界截断为前 4 个。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "user_settings.json"
            path.write_text(
                json.dumps({
                    "stage_targets": ["1-12"],
                    "skills": ["asj", "asjg", "assx", "jq", "byj", "tl"],
                    "cards": [],
                }),
                encoding="utf-8",
            )
            settings = load_lab_settings(path)
        self.assertEqual(["asj", "asjg", "assx", "jq"], settings.skills)

    def test_report_matches_loaded_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "user_settings.json"
            path.write_text(
                json.dumps(
                    {
                        "_shell": {"selected_mode_id": "normal_farm"},
                        "stage_targets": ["1-12"],
                        "auto_reputation": False,
                        "skills": ["asj", "asjg", "assx", "jq"],
                        "cards": ["刀刀", "齐天大圣"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            settings = load_lab_settings(path)
            text = format_lab_config_report(settings, path, "看板")
        self.assertIn("config=看板", text)
        self.assertIn("1-12", text)
        self.assertIn("英雄模式=关", text)
        self.assertIn("asj", text)
        self.assertIn("齐天大圣", text)


if __name__ == "__main__":
    unittest.main()
