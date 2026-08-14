from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QGroupBox,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import desktop_app  # noqa: E402
from gamescript.mediator import Mediator as RealMediator  # noqa: E402
from gamescript.mediator import Phase  # noqa: E402
from gamescript.settings import Settings  # noqa: E402
from gamescript.vision.capture import Frame  # noqa: E402


class DesktopPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # The real window persists settings on close.  Unit tests must never
        # rewrite the production config with whichever value a case last used.
        self.tmp = tempfile.TemporaryDirectory()
        self.save_patch = patch.object(Settings, "save", lambda *a, **k: None)
        self.save_patch.start()
        self.window = desktop_app.MainWindow(app_data=Path(self.tmp.name))

    def tearDown(self):
        try:
            self.window.close()
        finally:
            self.save_patch.stop()
            self.tmp.cleanup()

    def _panel_text(self) -> str:
        text_widgets = (QLabel, QPushButton, QCheckBox, QGroupBox)
        return "\n".join(
            widget.text() if hasattr(widget, "text") else widget.title()
            for kind in text_widgets
            for widget in self.window.findChildren(kind)
        )

    def test_panel_contains_only_core_controls(self):
        panel_text = self._panel_text()
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

    def test_home_page_keeps_optional_sections_collapsed(self):
        """首页默认不展开「深入设置」这类umbrella；技能/宝物/日志各自独立折叠。"""
        self.assertFalse(hasattr(self.window, "grp_deep"))
        self.assertFalse(self.window.grp_skill.isChecked())
        self.assertTrue(self.window.skill_grid.isHidden())
        self.assertFalse(self.window.grp_negative.isChecked())
        self.assertTrue(self.window.grp_negative.body.isHidden())
        self.assertFalse(self.window.grp_details.isChecked())
        self.assertTrue(self.window.txt_log.isHidden())

    def test_skill_cards_carry_icon_and_hover_description(self):
        """技能卡要有图标和悬停说明；没有实机证据的必须写『待补』而不是编数值。"""
        grid = self.window.skill_grid
        for code, button in grid.cards.items():
            with self.subTest(code=code):
                self.assertFalse(button.icon().isNull(), f"{code} 缺技能图标")
                tip = button.toolTip()
                self.assertIn(code, tip)
                self.assertTrue(tip.strip())

        # 有实机卡面证据的：显示原文
        self.assertIn("麻痹", grid.cards["tl"].toolTip())
        # 没有证据的：显式标注待补，不得出现伪造的数值说明
        asj_tip = grid.cards["asj"].toolTip()
        self.assertIn("待补", asj_tip)
        self.assertNotIn("%", asj_tip)

    def test_skill_archive_levels_default_unknown_and_round_trip(self):
        """存档等级默认全 0=未知（策略走保守前置）；填了要能往返。"""
        grid = self.window.archive_grid
        self.assertFalse(self.window.grp_archive.isChecked())
        self.assertTrue(grid.isHidden())
        self.assertEqual({}, grid.get_levels())
        self.assertEqual({}, self.window.collect_settings_from_ui().skill_archive_levels)

        grid.set_levels({"asj": 47, "byj": 8, "jq": 13})
        collected = self.window.collect_settings_from_ui()
        self.assertEqual({"asj": 47, "byj": 8, "jq": 13}, collected.skill_archive_levels)
        self.window.apply_settings_to_ui(collected)
        self.assertEqual(47, grid.boxes["asj"].value())
        self.assertEqual(0, grid.boxes["tl"].value())

    def test_skill_archive_levels_clamp_and_drop_zeros(self):
        grid = self.window.archive_grid
        grid.set_levels({"asj": 999, "tl": -5, "hq": 0})
        self.assertEqual(grid.MAX_LEVEL, grid.boxes["asj"].value())
        self.assertEqual(0, grid.boxes["tl"].value())
        self.assertEqual({"asj": grid.MAX_LEVEL}, grid.get_levels())
        grid.set_levels({})

    def test_negative_treasures_default_to_none_allowed(self):
        """负面宝物默认一张都不放行，且分区默认收起。"""
        group = self.window.grp_negative
        self.assertEqual([], group.get_allowed())
        self.assertFalse(group.isChecked())
        self.assertTrue(group.body.isHidden())
        self.assertEqual([], self.window.collect_settings_from_ui().treasure_allow_negative)

    def test_negative_treasure_opt_in_round_trips_through_settings(self):
        """勾选 → collect → apply 往返一致；放行是逐卡的，不牵连其它卡。"""
        group = self.window.grp_negative
        self.assertIn("金转木", group._boxes, "配置里的负面宝物应出现在面板上")
        group.set_allowed(["金转木"])
        collected = self.window.collect_settings_from_ui()
        self.assertEqual(["金转木"], collected.treasure_allow_negative)

        self.window.apply_settings_to_ui(collected)
        self.assertEqual(["金转木"], self.window.grp_negative.get_allowed())
        self.assertFalse(
            self.window.grp_negative._boxes["等级优势"].isChecked(),
            "放行一张不得连带放行其它负面宝物",
        )

    def test_negative_group_keeps_title_stable_on_refresh(self):
        """分组自己刷新标题时语义仍在（曾因两处写标题而丢前缀）。

        2026-08-13 改名：负面宝物放行 → 特殊宝物选择（用户可见措辞），
        契约不变——刷新标题不得丢掉「特殊宝物」语义前缀。
        """
        group = self.window.grp_negative
        for action in (
            lambda: group.set_allowed(["金转木"]),
            lambda: group.setChecked(True),
            lambda: group.setChecked(False),
            lambda: group.set_allowed([]),
        ):
            action()
            self.assertIn(
                "特殊宝物",
                group.title(),
                f"标题丢了特殊宝物语义：{group.title()!r}",
            )

    def test_negative_treasure_list_matches_policy_config(self):
        """面板展示的负面宝物必须与策略配置同源，避免 UI 与判定脱节。"""
        from gamescript.choice_policy import DEFAULT_NEGATIVE_NAMES

        self.assertEqual(
            sorted(DEFAULT_NEGATIVE_NAMES),
            sorted(self.window.grp_negative._boxes),
        )

    def test_exact_stage_and_solo_defaults_are_fixed(self):
        # Stale values from the removed room-name/password controls must not
        # affect the direct-create path.
        self.window.settings.room_name = "old-room"
        self.window.settings.room_password = "old-password"
        self.window.settings.lab_focus = "skill,reenter"
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
        self.assertEqual("", settings.room_name)
        self.assertEqual("", settings.room_password)
        self.assertEqual("", settings.lab_focus)

    def test_hero_mode_maps_faction_and_difficulty(self):
        self.window.cmb_mode.setCurrentIndex(self.window.cmb_mode.findData(True))
        self.window.cmb_reputation.setCurrentIndex(
            self.window.cmb_reputation.findData(3)
        )
        self.window.spn_reputation_level.setValue(5)
        settings = self.window.collect_settings_from_ui()

        self.assertTrue(settings.auto_reputation)
        self.assertEqual(3, settings.reputation_type)
        self.assertEqual(5, settings.reputation_level)
        self.assertEqual(5, self.window.spn_reputation_level.maximum())
        self.assertFalse(self.window.hero_options.isHidden())

    def test_reputation_combo_exposes_all_six_factions(self):
        """六大声望阵营都应可选（mediator 侧的门控是另一回事）。"""
        expected = {
            1: "黑锋骑士团",
            2: "银色北伐军",
            3: "肯瑞托",
            4: "探险者协会",
            5: "元素领主",
            6: "守护巨龙",
        }
        combo = self.window.cmb_reputation
        self.assertEqual(6, combo.count())
        actual = {combo.itemData(i): combo.itemText(i) for i in range(combo.count())}
        self.assertEqual(expected, actual)

        for faction_id in expected:
            combo.setCurrentIndex(combo.findData(faction_id))
            settings = self.window.collect_settings_from_ui()
            self.assertEqual(faction_id, settings.reputation_type)

    def test_secret_realm_checkbox_round_trips_settings(self):
        settings = Settings(auto_secret_realm=True)
        self.window.apply_settings_to_ui(settings)
        self.assertTrue(self.window.chk_secret_realm.isChecked())
        self.assertTrue(self.window.collect_settings_from_ui().auto_secret_realm)

        self.window.chk_secret_realm.setChecked(False)
        self.assertFalse(self.window.collect_settings_from_ui().auto_secret_realm)

    def test_learning_mode_checkbox_is_visible_and_maps_to_dry_run(self):
        """学习模式必须挂在首页运行区；底层仍写 settings.dry_run。"""
        self.assertTrue(hasattr(self.window, "chk_learn"))
        self.assertIn("学习模式", self.window.chk_learn.text())
        # 控件必须进布局，否则用户看不见（V0.2 曾漏挂 chk_dry）
        self.assertIsNotNone(self.window.chk_learn.parent())

        self.window.chk_learn.setChecked(True)
        self.assertTrue(self.window.collect_settings_from_ui().dry_run)
        self.window.chk_learn.setChecked(False)
        self.assertFalse(self.window.collect_settings_from_ui().dry_run)

        self.window.apply_settings_to_ui(Settings(dry_run=True))
        self.assertTrue(self.window.chk_learn.isChecked())

    def test_rejects_invalid_or_empty_core_configuration(self):
        self.window.txt_stage_target.setText("第十关")
        with self.assertRaisesRegex(ValueError, "章节-关卡"):
            self.window.collect_settings_from_ui()

        # 技能可选：空技能不拦截，但运行时只刷新并放弃，不学习配置外技能。
        self.window.txt_stage_target.setText("1-10")
        self.window.skill_grid.set_skills([])
        settings = self.window.collect_settings_from_ui()
        self.assertEqual([], settings.skills)

    def test_desktop_worker_writes_fail_closed_incident(self):
        """S0.5：desktop worker 的 Mediator 构造路径传 temp incident_dir，触发
        Fail-Closed 后 incident 组含 3 帧（before/now/after）+ 完整 S0 metadata
        （phase/context/evidence/action/attempt/deadline/outcome），密码不泄露。"""
        import gamescript.mediator as mediator_mod

        class FailClosedProbeMediator(RealMediator):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.probe_incident_dir = kwargs.get("incident_dir")

            @staticmethod
            def _probe_frame() -> Frame:
                rng = np.random.default_rng(99)
                return Frame(
                    bgr=rng.integers(0, 255, (900, 1600, 3), dtype=np.uint8),
                    window_title="英雄三国KK",
                    hwnd=10001,
                )

            def run(self, max_steps=None):
                frame = self._probe_frame()
                self._last_frame = frame
                self._prev_frame = frame
                self.settings.room_password = "top-secret-pw"
                self._context_cache_value = "MAIN_LINE"
                # Fail-Closed 归档路径（与生产 set_phase(ERROR) 同一入口）
                self.set_phase(Phase.ERROR, "probe fail closed")
                fp = self._incident_pending_fp
                if fp is not None:
                    self._archiver.attach_frame_after(fp, self._probe_frame())

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mediator_mod, "Mediator", FailClosedProbeMediator):
                worker = desktop_app.MediatorWorker(
                    Settings(dry_run=True), ROOT, max_steps=1, incident_dir=tmp
                )
                worker._start_trace = lambda: None  # 测试不写 APP_DATA trace
                worker.run()
            groups = sorted(Path(tmp).rglob("incident_*"))
            self.assertEqual(len(groups), 1, "Fail-Closed 必须产生 incident 组")
            group = groups[0]
            for frame_name in ("frame_before.jpg", "frame_now.jpg", "frame_after.jpg"):
                self.assertTrue((group / frame_name).is_file(), f"incident 必须含 {frame_name}")
            meta = json.loads((group / "metadata.json").read_text(encoding="utf-8"))
            for field in ("phase", "context", "evidence", "action", "attempt", "deadline", "outcome"):
                self.assertIn(field, meta, f"metadata 必须含 {field}")
            raw = (group / "metadata.json").read_text(encoding="utf-8")
            self.assertNotIn("top-secret-pw", raw, "密码不得归档")

    def test_run_mode_and_stage_difficulty_are_not_mixed(self):
        text = self._panel_text()
        self.assertIn("运行方式", text)
        self.assertIn("关卡难度", text)
        self.assertEqual("普通", self.window.cmb_mode.itemText(0))
        self.assertEqual("英雄", self.window.cmb_mode.itemText(1))

    def test_start_button_lives_on_pinned_footer(self):
        self.assertTrue(self.window.footer.isAncestorOf(self.window.btn_main))
        parent = self.window.btn_main.parentWidget()
        while parent is not None:
            self.assertNotIsInstance(parent, QScrollArea)
            parent = parent.parentWidget()

    def test_collect_returns_detached_settings_copy(self):
        first = self.window.collect_settings_from_ui()
        second = self.window.collect_settings_from_ui()
        self.assertIsNot(first, self.window.settings)
        self.assertIsNot(first, second)
        first.skills = ["changed-in-test"]
        self.assertNotEqual(first.skills, second.skills)

    def test_user_settings_path_is_under_app_data(self):
        path = self.window.user_settings_path()
        self.assertEqual(path.parent, Path(self.tmp.name))
        self.assertEqual(path.name, "user_settings.json")
        self.assertNotIn("config", path.parts[-2:])

    def test_unverified_mode_start_is_zero_input(self):
        from gamescript.shell.runner_service import ModeNotEnabled, RunnerService

        svc = RunnerService(Path(self.tmp.name), ROOT)
        with patch("gamescript.shell.runner_service.MediatorWorker") as worker_cls:
            for mode_id in ("follow_team", "gambling_wood", "raid_wait", "lobby_hitch", "lab"):
                with self.subTest(mode_id=mode_id):
                    with self.assertRaises(ModeNotEnabled):
                        svc.start(mode_id, Settings(dry_run=True))
            worker_cls.assert_not_called()
        self.assertIsNone(svc.worker)

    def test_tray_menu_has_no_unverified_start(self):
        texts = [action.text() for action in self.window.tray_menu.actions()]
        joined = "\n".join(texts)
        self.assertIn("打开控制中心", joined)
        self.assertIn("停止运行", joined)
        for banned in ("跟车", "赌木", "站团本", "大厅找房", "开始运行", "lobby_hitch"):
            self.assertNotIn(banned, joined)

    def test_apply_official_build_fills_skills_bonds_reputation(self):
        ok = self.window.apply_official_build("arcane_open", confirm=False)
        self.assertTrue(ok)
        collected = self.window.collect_settings_from_ui()
        self.assertEqual(["asj", "asjg", "assx", "jq"], collected.skills)
        self.assertEqual(["tishu", "chengzhang", "zhufu", "zhili", "yanmiezhe", "fs"], collected.cards)
        self.assertEqual(3, collected.reputation_type)

    def test_bond_invert_writes_scheme_minus_inverted(self):
        self.window.set_bond_scheme(["tishu", "chengzhang", "zhufu"], inverted=["chengzhang"])
        self.assertEqual(["tishu", "zhufu"], self.window.effective_bond_codes())
        self.assertEqual(["tishu", "zhufu"], self.window.collect_settings_from_ui().cards)

    def test_treasure_and_wood_controls_are_labeled_or_disabled(self):
        text = self._panel_text()
        self.assertIn("待接线", text)
        self.assertIn("待验证", text)
        self.assertIn("策略必拿", text)
        self.assertFalse(self.window.spn_wood_open_f.isEnabled())
        self.assertFalse(self.window.spn_wood_refresh.isEnabled())
        self.assertFalse(self.window.txt_hitch_exact.isEnabled())
        self.assertIn("后续拓展", self.window.txt_hitch_exact.placeholderText())

    def test_cycle_num_zero_does_not_draw_a_bar(self):
        self.window.spn_cycle_num.setValue(0)
        self.window.update_status(False, "空闲", 3)
        self.assertEqual([], self.window.findChildren(QProgressBar))
        self.assertIn("已完成", self.window.lbl_games_cap.text())

    def test_hitch_copy_has_no_lock_button_and_corrected_f_keys(self):
        text = self._panel_text()
        self.assertIn("只认 准备 / 已准备 / 取消准备", text)
        self.assertIn("无「锁定」按钮", text)
        self.assertIn("F1 = 操作切回自身英雄", text)
        self.assertIn("F2 = 回基地", text)
        self.assertNotIn("hitch_reject_list", text)


if __name__ == "__main__":
    unittest.main()
