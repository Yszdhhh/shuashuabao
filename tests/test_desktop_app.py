from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QGroupBox,
    QLabel,
    QPushButton,
)

import desktop_app  # noqa: E402


class DesktopPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = desktop_app.MainWindow()

    def tearDown(self):
        self.window.close()

    def test_panel_contains_only_core_controls(self):
        text_widgets = (QLabel, QPushButton, QCheckBox, QGroupBox)
        panel_text = "\n".join(
            widget.text() if hasattr(widget, "text") else widget.title()
            for kind in text_widgets
            for widget in self.window.findChildren(kind)
        )
        for removed_text in (
            "认证状态",
            "官方 Settings",
            "保存本地配置",
            "测试步数",
            "窗口侦测",
            "高级设置",
        ):
            self.assertNotIn(removed_text, panel_text)

    def test_skill_buttons_show_chinese_names_and_fold_at_four(self):
        for code, button in self.window.skill_grid.cards.items():
            self.assertNotIn(code, button.text())
            self.assertNotIn("(", button.text())

        # 选满 4 个：自动折叠（保持面板简洁），标题显示已选技能
        self.window.grp_skill.setChecked(True)
        self.window.skill_grid.set_skills(["asj", "asjg", "assx", "jq"])
        self.assertFalse(self.window.grp_skill.isChecked())
        self.assertTrue(self.window.skill_grid.isHidden())
        self.assertIn("奥数箭", self.window.grp_skill.title())
        # 点勾可重新展开
        self.window.grp_skill.setChecked(True)
        self.assertFalse(self.window.skill_grid.isHidden())

    def test_exact_stage_and_solo_defaults_are_fixed(self):
        self.window.txt_stage_target.setText("2-7")
        self.window.cmb_mode.setCurrentIndex(self.window.cmb_mode.findData(False))
        settings = self.window.collect_settings_from_ui()

        self.assertEqual(["2-7"], settings.stage_targets)
        self.assertEqual(7, settings.stage1)
        self.assertEqual(7, settings.stage2)
        self.assertEqual(0, settings.game_mode)
        self.assertTrue(settings.auto_create_room)
        self.assertFalse(settings.new_room_every_times)
        self.assertFalse(settings.auto_reputation)

    def test_hero_mode_maps_faction_and_difficulty(self):
        self.window.cmb_mode.setCurrentIndex(self.window.cmb_mode.findData(True))
        self.window.cmb_reputation.setCurrentIndex(
            self.window.cmb_reputation.findData(3)
        )
        self.window.spn_reputation_level.setValue(5)
        settings = self.window.collect_settings_from_ui()

        self.assertTrue(settings.auto_reputation)
        self.assertEqual(1, self.window.cmb_reputation.count())
        self.assertEqual(3, settings.reputation_type)
        self.assertEqual(5, settings.reputation_level)
        self.assertEqual(5, self.window.spn_reputation_level.maximum())
        self.assertFalse(self.window.hero_options.isHidden())

    def test_rejects_invalid_or_empty_core_configuration(self):
        self.window.txt_stage_target.setText("第十关")
        with self.assertRaisesRegex(ValueError, "章节-关卡"):
            self.window.collect_settings_from_ui()

        # 技能可选：空技能不拦截，但运行时只刷新并放弃，不学习配置外技能。
        self.window.txt_stage_target.setText("1-10")
        self.window.skill_grid.set_skills([])
        settings = self.window.collect_settings_from_ui()
        self.assertEqual([], settings.skills)


if __name__ == "__main__":
    unittest.main()
