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
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import desktop_app  # noqa: E402
from shuabao.mediator import Mediator as RealMediator  # noqa: E402
from shuabao.mediator import Phase  # noqa: E402
from shuabao.settings import Settings  # noqa: E402
from shuabao.shell import main_window as shell_window  # noqa: E402
from shuabao.shell.test_profiles import (  # noqa: E402
    TestProfileError,
    export_profile,
    load_test_profiles,
    validate_profile_document,
)
from shuabao.vision.capture import Frame  # noqa: E402


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

    def test_skill_buttons_show_chinese_names_and_enforce_max_four(self):
        for code, button in self.window.skill_grid.cards.items():
            self.assertNotIn(code, button.text())
            self.assertNotIn("(", button.text())

        # 选 4 个：严格模式标题与提示
        self.window.skill_grid.set_skills(["asj", "asjg", "assx", "jq"])
        self.assertIn("奥术箭", self.window.grp_skill.title())
        self.assertIn("严格模式", self.window.grp_skill.title())
        self.assertIn("严格模式", self.window.skill_grid.hint.text())

        # 选 0 个：未选模式提示
        self.window.skill_grid.set_skills([])
        self.assertIn("未选", self.window.grp_skill.title())
        self.assertIn("不自动学习任何技能", self.window.skill_grid.hint.text())

    def test_skill_max_four_fifth_toggle_rejected(self):
        """第 5 个技能勾选被拒：按钮复位、计数仍为 4、无全能/all_round 文案。"""
        grid = self.window.skill_grid
        grid.set_skills(["asj", "asjg", "assx", "jq"])
        self.assertEqual(4, len(grid.get_skills()))
        with patch("shuabao.shell.main_window.QMessageBox.information") as info:
            grid._toggle("tl", True)
        info.assert_called_once()
        self.assertEqual(4, len(grid.get_skills()))
        self.assertFalse(grid.cards["tl"].isChecked())
        panel_text = self._panel_text()
        self.assertNotIn("全能", panel_text)
        self.assertNotIn("all_round", panel_text)

    def test_skill_max_four_truncates_on_set(self):
        """set_skills 传入 5+ 只保留前 4 个（确定性，未知码丢弃）。"""
        grid = self.window.skill_grid
        grid.set_skills(["asj", "asjg", "assx", "jq", "byj", "tl", "nonexistent"])
        self.assertEqual(["asj", "asjg", "assx", "jq"], grid.get_skills())
        self.assertEqual(4, grid.MAX_SKILLS)
        self.assertNotIn("全能", self.window.skill_grid.hint.text())

    def test_skill_persisted_five_plus_loads_first_four_and_warns(self):
        """已保存 5+ 技能：加载确定性截断为前 4 个，并输出一条用户可见警告（不泄露技能名）。"""
        self.window.user_settings_path().write_text(
            json.dumps({
                "_shell_schema": 2,
                "stage_targets": ["1-10"],
                "skills": ["asj", "asjg", "assx", "jq", "byj", "tl"],
                "cards": [],
                "_shell": {"selected_mode_id": "normal_farm"},
            }),
            encoding="utf-8",
        )
        restored = desktop_app.MainWindow(app_data=Path(self.tmp.name))
        try:
            self.assertEqual(["asj", "asjg", "assx", "jq"], restored.skill_grid.get_skills())
            self.assertEqual(["asj", "asjg", "assx", "jq"], restored.collect_settings_from_ui().skills)
            self.assertIn("超过上限", restored.txt_log.toPlainText())
            self.assertNotIn("byj", restored.txt_log.toPlainText())
        finally:
            restored.close()

    def test_factory_default_bonds_exactly_five_round1_must(self):
        """factory/no-user-scheme：基础羁绊默认恰为 祝福/成长/经济/贪婪/挑战。"""
        cards = self.window.collect_settings_from_ui().cards
        self.assertEqual(
            {"zhufu", "chengzhang", "经济", "tanlan", "挑战"},
            set(cards),
        )
        self.assertEqual(5, len(cards))

    def test_each_default_bond_can_be_deselected(self):
        """五个默认羁绊任选取消/恢复：取消一个不得连带取消其余默认。"""
        defaults = ["zhufu", "chengzhang", "经济", "tanlan", "挑战"]
        for code in defaults:
            self.window._on_plan_toggled(code, False)
            cards = self.window.collect_settings_from_ui().cards
            self.assertNotIn(code, cards)
            self.assertEqual(
                set(defaults) - {code}, set(cards),
                "取消一个默认不得连带取消其余默认",
            )
            self.window._on_plan_toggled(code, True)
            self.assertEqual(
                set(defaults), set(self.window.collect_settings_from_ui().cards)
            )

    def test_factory_defaults_all_deselected_persist_empty(self):
        """全取消默认五羁绊 = 显式空：保存重载后仍严格为空。"""
        for code in ("zhufu", "chengzhang", "经济", "tanlan", "挑战"):
            self.window._on_plan_toggled(code, False)
        self.assertEqual([], self.window.collect_settings_from_ui().cards)
        self.window._on_save_settings_clicked()
        restored = desktop_app.MainWindow(app_data=Path(self.tmp.name))
        try:
            self.assertEqual([], restored.collect_settings_from_ui().cards)
            self.assertEqual([], restored.assemble_whitelist_cards())
        finally:
            restored.close()

    def test_user_json_no_scheme_empty_cards_defaults_to_five(self):
        """用户 JSON 无权威 bond_scheme 且 cards 为空 = 无方案数据 → 默认五张。"""
        self.window.user_settings_path().write_text(
            json.dumps({
                "_shell_schema": 2,
                "stage_targets": ["1-10"],
                "skills": ["asj"],
                "cards": [],
                "_shell": {"selected_mode_id": "normal_farm"},
            }),
            encoding="utf-8",
        )
        restored = desktop_app.MainWindow(app_data=Path(self.tmp.name))
        try:
            self.assertEqual(
                {"zhufu", "chengzhang", "经济", "tanlan", "挑战"},
                set(restored.collect_settings_from_ui().cards),
            )
        finally:
            restored.close()

    def test_user_json_no_scheme_nonempty_cards_preserved_as_explicit(self):
        """缺 bond_scheme 但 cards 非空 = 旧版显式历史选择，原样保留。"""
        self.window.user_settings_path().write_text(
            json.dumps({
                "_shell_schema": 2,
                "stage_targets": ["1-10"],
                "skills": ["asj"],
                "cards": ["zhufu", "chengzhang"],
                "_shell": {"selected_mode_id": "normal_farm"},
            }),
            encoding="utf-8",
        )
        restored = desktop_app.MainWindow(app_data=Path(self.tmp.name))
        try:
            self.assertEqual(
                ["zhufu", "chengzhang"], restored.collect_settings_from_ui().cards
            )
        finally:
            restored.close()

    def test_user_json_explicit_empty_scheme_stays_empty(self):
        """显式 _shell.bond_scheme=[] → 显式空卡组，保持空。"""
        self.window.user_settings_path().write_text(
            json.dumps({
                "_shell_schema": 2,
                "stage_targets": ["1-10"],
                "skills": ["asj"],
                "cards": [],
                "_shell": {
                    "selected_mode_id": "normal_farm",
                    "bond_scheme": [],
                    "bond_inverted": [],
                },
            }),
            encoding="utf-8",
        )
        restored = desktop_app.MainWindow(app_data=Path(self.tmp.name))
        try:
            self.assertEqual([], restored.collect_settings_from_ui().cards)
        finally:
            restored.close()

    def test_two_attr_routes_still_expand_and_persist(self):
        """智力+力量两条属性线同时勾选：各自展开进白名单，保存重载后仍生效。"""
        self.window.route_buttons["intelligence"].setChecked(True)
        self.window.route_buttons["strength"].setChecked(True)
        self.window._on_attr_route_clicked()
        cards = self.window.collect_settings_from_ui().cards
        for token in ("zhili", "yanmiezhe", "tuluzhe", "xueshi"):
            self.assertIn(token, cards)
        self.window._on_save_settings_clicked()
        restored = desktop_app.MainWindow(app_data=Path(self.tmp.name))
        try:
            self.assertEqual(["intelligence", "strength"], restored._shell_extras.get("attr_route"))
            collected = restored.collect_settings_from_ui().cards
            for token in ("zhili", "yanmiezhe", "tuluzhe", "xueshi"):
                self.assertIn(token, collected)
        finally:
            restored.close()

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
        from shuabao.choice_policy import DEFAULT_NEGATIVE_NAMES

        self.assertEqual(
            sorted(DEFAULT_NEGATIVE_NAMES),
            sorted(self.window.grp_negative._boxes),
        )

    def test_solo_room_fields_round_trip(self):
        self.window.settings.lab_focus = "skill,reenter"
        self.window.txt_stage_target.setText("2-7")
        self.window.cmb_mode.setCurrentIndex(self.window.cmb_mode.findData(False))
        self.window.chk_auto_create_room.setChecked(True)
        self.window.txt_room_name.setText("test-room")
        self.window.txt_room_password.setText("top-secret-pw")
        self.window.cmb_room_reuse.setCurrentIndex(self.window.cmb_room_reuse.findData(True))
        settings = self.window.collect_settings_from_ui()

        self.assertEqual(["2-7"], settings.stage_targets)
        self.assertEqual(7, settings.stage1)
        self.assertEqual(7, settings.stage2)
        self.assertEqual(0, settings.game_mode)
        self.assertTrue(settings.auto_create_room)
        self.assertTrue(settings.new_room_every_times)
        self.assertFalse(settings.auto_reputation)
        self.assertEqual("test-room", settings.room_name)
        self.assertEqual("top-secret-pw", settings.room_password)
        self.assertEqual("", settings.lab_focus)
        self.window.apply_settings_to_ui(settings)
        self.assertEqual("test-room", self.window.txt_room_name.text())
        self.assertEqual("top-secret-pw", self.window.txt_room_password.text())
        self.assertEqual(QLineEdit.Password, self.window.txt_room_password.echoMode())
        self.window._on_save_settings_clicked()
        saved = json.loads(self.window.user_settings_path().read_text(encoding="utf-8"))
        self.assertTrue(saved["auto_create_room"])
        self.assertTrue(saved["new_room_every_times"])
        self.assertEqual("test-room", saved["room_name"])

    def test_hero_settings_visibility_toggles_with_mode(self):
        # 默认普通模式：hero_options 隐藏
        self.window.cmb_mode.setCurrentIndex(self.window.cmb_mode.findData(False))
        self.assertTrue(self.window.hero_options.isHidden())

        # 切换到英雄模式：hero_options 展开显示
        self.window.cmb_mode.setCurrentIndex(self.window.cmb_mode.findData(True))
        self.assertFalse(self.window.hero_options.isHidden())
        self.window.cmb_reputation.setCurrentIndex(
            self.window.cmb_reputation.findData(3)
        )
        self.window.spn_reputation_level.setValue(5)
        settings = self.window.collect_settings_from_ui()

        self.assertTrue(settings.auto_reputation)
        self.assertEqual(3, settings.reputation_type)
        self.assertEqual(5, settings.reputation_level)
        self.assertEqual(5, self.window.spn_reputation_level.maximum())

        # 切回普通模式：hero_options 再次隐藏
        self.window.cmb_mode.setCurrentIndex(self.window.cmb_mode.findData(False))
        self.assertTrue(self.window.hero_options.isHidden())

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

        # 技能可选：空技能不拦截；运行时直接关闭/隐藏，不刷新、不放弃技能点。
        self.window.txt_stage_target.setText("1-10")
        self.window.skill_grid.set_skills([])
        settings = self.window.collect_settings_from_ui()
        self.assertEqual([], settings.skills)

    def test_empty_skills_collect_logs_close_hide_not_refresh_or_giveup(self):
        """空技能 collect 必须经真实 log surface 声明关闭/隐藏，而不是刷新并放弃。"""
        self.window.txt_stage_target.setText("1-10")
        self.window.skill_grid.set_skills([])
        self.window.txt_log.clear()
        settings = self.window.collect_settings_from_ui()
        self.assertEqual([], settings.skills)
        logged = self.window.txt_log.toPlainText()
        self.assertIn("直接关闭/隐藏", logged)
        self.assertIn("不刷新", logged)
        self.assertIn("不放弃", logged)
        self.assertNotIn("只刷新并放弃", logged)

    def test_empty_skills_hint_and_clear_tooltip_match_close_hide_policy(self):
        """0 选时 hint/清空 tooltip 必须声明关闭/隐藏，而不是刷新并放弃。"""
        self.window.skill_grid.set_skills([])
        hint = self.window.skill_grid.hint.text()
        self.assertIn("直接关闭/隐藏", hint)
        self.assertIn("不刷新", hint)
        self.assertIn("不放弃技能点", hint)
        self.assertNotIn("只刷新并放弃", hint)

        clear_btns = [
            widget
            for widget in self.window.skill_grid.findChildren(QPushButton)
            if widget.text() == "清空"
        ]
        self.assertEqual(1, len(clear_btns))
        tip = clear_btns[0].toolTip()
        self.assertIn("直接关闭/隐藏", tip)
        self.assertIn("不刷新", tip)
        self.assertIn("不放弃技能点", tip)
        self.assertNotIn("只刷新并放弃", tip)

    def test_desktop_worker_writes_fail_closed_incident(self):
        """S0.5：desktop worker 的 Mediator 构造路径传 temp incident_dir，触发
        Fail-Closed 后 incident 组含 3 帧（before/now/after）+ 完整 S0 metadata
        （phase/context/evidence/action/attempt/deadline/outcome），密码不泄露。"""
        import shuabao.mediator as mediator_mod

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

    def test_streamlined_stage_picker_exposes_mode_and_cycle_and_hides_raw_target(self):
        text = self._panel_text()
        self.assertIn("先选运行方式", text)
        self.assertFalse(self.window.cmb_mode.isHidden())
        self.assertFalse(self.window.spn_cycle_num.isHidden())
        self.assertTrue(self.window.txt_stage_target.isHidden())
        chapters = [self.window.cmb_chapter.itemText(i) for i in range(self.window.cmb_chapter.count())]
        self.assertEqual(["旧世界大陆（一阶段）", "熔火之心（二阶段）", "黑翼之潮（三阶段）", "安琪拉（四阶段）"], chapters)
        self.assertNotIn("多少关", "\n".join(chapters))

    def test_load_legacy_settings_shows_real_values_in_ui(self):
        legacy = Settings(
            cycle_num=99,
            auto_reputation=True,
            reputation_type=3,
            reputation_level=5,
        )
        self.window.apply_settings_to_ui(legacy)
        self.assertEqual(99, self.window.spn_cycle_num.value())
        self.assertTrue(self.window.cmb_mode.currentData())
        self.assertEqual(3, self.window.cmb_reputation.currentData())
        self.assertEqual(5, self.window.spn_reputation_level.value())
        self.assertFalse(self.window.hero_options.isHidden())
        self.assertFalse(self.window.cmb_mode.isHidden())
        self.assertFalse(self.window.spn_cycle_num.isHidden())

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
        from shuabao.shell.runner_service import ModeNotEnabled, RunnerService

        svc = RunnerService(Path(self.tmp.name), ROOT)
        with patch("shuabao.shell.runner_service.MediatorWorker") as worker_cls:
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
        for code in ("tishu", "chengzhang", "zhufu", "zhili", "yanmiezhe", "fs"):
            self.assertIn(code, collected.cards)
        self.assertEqual(3, collected.reputation_type)

    def test_bond_invert_writes_scheme_minus_inverted(self):
        self.window.set_bond_scheme(["tishu", "chengzhang", "zhufu"], inverted=["chengzhang"])
        self.assertEqual(["tishu", "zhufu"], self.window.effective_bond_codes())
        cards = self.window.collect_settings_from_ui().cards
        self.assertIn("tishu", cards)
        self.assertNotIn("chengzhang", cards)

    def test_mainline_stage_picker_covers_current_chapters(self):
        expected = {1: 23, 2: 7, 3: 9, 4: 3}
        actual = {int(self.window.cmb_chapter.itemData(i)): None for i in range(self.window.cmb_chapter.count())}
        self.assertEqual(set(expected), set(actual))
        self.window.cmb_chapter.setCurrentIndex(self.window.cmb_chapter.findData(1))
        self.assertEqual(23, self.window.cmb_stage.count())
        self.window.cmb_chapter.setCurrentIndex(self.window.cmb_chapter.findData(4))
        self.assertEqual(3, self.window.cmb_stage.count())
        self.window._apply_stage_target("4-3")
        self.assertEqual("4-3", self.window.collect_settings_from_ui().stage_targets[0])
        self.window.txt_stage_target.setText("4-4")
        with self.assertRaisesRegex(ValueError, "主线"):
            self.window.collect_settings_from_ui()

    def test_attr_route_consumes_chain_and_support_in_order(self):
        # 智力线按 attr_routes 顺序消费 chain（智力/秘法师/法神/湮灭者）
        # + support（法术/魔能/魔术/魔法师/元素师），去重；可解析短码用短码。
        self.window.route_buttons["intelligence"].setChecked(True)
        cards = self.window.collect_settings_from_ui().cards
        self.assertIn("秘法师", cards)
        self.assertIn("法神", cards)
        self.assertIn("魔能", cards)
        self.assertIn("魔术", cards)
        self.assertIn("元素师", cards)
        self.assertIn("mfs", cards)  # 魔法师 → 短码
        self.assertEqual(cards.count("yanmiezhe"), 1, "chain 与 fetter_code 去重")
        # 顺序：chain 逐环在前，support 在后；support 内部保持 attr_routes 顺序。
        self.assertLess(cards.index("秘法师"), cards.index("法神"))
        self.assertLess(cards.index("法神"), cards.index("fs"))
        self.assertLess(cards.index("fs"), cards.index("魔能"))
        self.assertLess(cards.index("魔能"), cards.index("魔术"))
        self.assertLess(cards.index("魔术"), cards.index("mfs"))
        self.assertLess(cards.index("mfs"), cards.index("元素师"))

    def test_attr_route_multi_route_chain_support_dedup(self):
        # 力量线 chain+support（血誓）与智力线同时勾选：各自去重且都在白名单。
        self.window.route_buttons["intelligence"].setChecked(True)
        self.window.route_buttons["strength"].setChecked(True)
        cards = self.window.collect_settings_from_ui().cards
        self.assertIn("yemanren", cards)   # 野蛮人
        self.assertIn("zhanshen", cards)   # 战神
        self.assertIn("xueshi", cards)     # 血誓（support）
        self.assertEqual(cards.count("tuluzhe"), 1)
        self.assertEqual(cards.count("zhili"), 1)

    def test_attr_line_tokens_never_falls_back_to_attr_line_options(self):
        # 配置漂移时（route 在 ATTR_LINE_OPTIONS 但不在 attr_routes）：必须贡献
        # 零 token，不得退回旧 gate+ur 摘要（第二事实源）。
        with patch.object(shell_window, "ATTR_LINE_OPTIONS", [
            {"id": "ghost_route", "label": "幽灵线", "gate": "幽灵", "ur": "幽灵王"},
        ]):
            self.window._shell_extras["attr_route"] = ["ghost_route"]
            self.assertEqual(self.window._attr_line_tokens(), [])

    def test_attr_line_tokens_is_single_chain_source(self):
        # 唯一链路：只从 official_strategy_defaults attr_routes 读 chain+support，
        # 配置顺序去重；可解析短码用短码，无法解析保留中文名。
        self.window._shell_extras["attr_route"] = ["intelligence"]
        self.assertEqual(
            self.window._attr_line_tokens(),
            ["zhili", "秘法师", "法神", "yanmiezhe", "fs", "魔能", "魔术", "mfs", "元素师"],
        )

    def test_factory_empty_cards_do_not_inject_attr_route(self):
        # 工厂 Settings.cards=[]：不得从 cards 内容猜测/默认注入属性路线。
        # 属性线 checkbox 必须全不勾选，_attr_line_tokens() 必须为空，
        # 且收集到的 cards 不得自动注入整条智力路线。
        self.window.apply_settings_to_ui(Settings(cards=[]))
        self.assertEqual(self.window._shell_extras.get("attr_route") or [], [])
        self.assertFalse(any(b.isChecked() for b in self.window.route_buttons.values()))
        self.assertEqual(self.window._attr_line_tokens(), [])
        cards = self.window.collect_settings_from_ui().cards
        for token in ("秘法师", "fs", "yanmiezhe", "法术", "魔能", "魔术", "mfs", "元素师"):
            self.assertNotIn(token, cards)
    def test_attr_line_is_summary_and_advanced_packs_optional(self):
        text = self._panel_text()
        self.assertIn("属性线", text)
        self.assertIn("刀刀", text)
        self.assertIn("异火", text)
        self.assertIn("大圣", text)
        self.assertNotIn("属性链", text)
        self.assertNotIn("round1 必做", text)
        self.window._advanced_pack_boxes["daodao"].setChecked(True)
        cards = self.window.collect_settings_from_ui().cards
        self.assertIn("刀刀", cards)
        self.assertIn("幽灵系带", cards)
        self.assertNotIn("解放的圣剑", cards)
        self.window._advanced_pack_boxes["yihuo"].setChecked(True)
        cards = self.window.collect_settings_from_ui().cards
        self.assertIn("阴阳双炎", cards)
        self.assertNotIn("帝炎", cards)
        self.window._advanced_pack_boxes["dasheng"].setChecked(True)
        cards = self.window.collect_settings_from_ui().cards
        self.assertIn("齐天大圣", cards)
        self.assertNotIn("法天象地", cards)

    def test_basic_pack_invert_toggles_whitelist(self):
        before = list(self.window.assemble_whitelist_cards())
        self.assertIn("zhufu", before)
        self.window._invert_basic_pack()
        after = self.window.assemble_whitelist_cards()
        self.assertNotIn("zhufu", after)

    def test_factory_default_keeps_five_round1_must_selected(self):
        """默认 profile（工厂加载、无用户方案数据）：基础卡组默认勾选 round1_must 五张。"""
        cards = self.window.collect_settings_from_ui().cards
        self.assertIn("zhufu", cards)
        self.assertIn("chengzhang", cards)
        self.assertIn("经济", cards)
        self.assertIn("tanlan", cards)
        self.assertIn("挑战", cards)
        self.assertEqual(5, len(cards))

    def test_empty_cards_round_trip_stays_strictly_empty(self):
        """Settings(cards=[]) 经 apply_settings_to_ui→collect_settings_from_ui 后必须仍严格 []。

        空卡组是显式"一张不选"，不得被 _rebuild_bond_plan 的空 scheme 语义
        解释成"全选基础包"。
        """
        self.window.apply_settings_to_ui(Settings(cards=[]))
        self.assertEqual([], self.window.collect_settings_from_ui().cards)

    def test_empty_cards_bundle_restores_empty(self):
        """cards=[] 的 bundle 保存→重载后 collect 仍为 []（往返保留，不膨胀成基础包）。"""
        self.window.apply_settings_to_ui(Settings(cards=[]))
        self.window._on_save_settings_clicked()
        restored = desktop_app.MainWindow(app_data=Path(self.tmp.name))
        try:
            self.assertEqual([], restored.collect_settings_from_ui().cards)
        finally:
            restored.close()

    def test_explicit_basic_scheme_round_trip_unchanged(self):
        """显式 basic scheme 行为保持：非空 cards 往返不变，反选方案仍然生效。"""
        self.window.apply_settings_to_ui(Settings(cards=["zhufu", "chengzhang"]))
        self.assertEqual(["zhufu", "chengzhang"], self.window.collect_settings_from_ui().cards)
        self.window.set_bond_scheme(["tishu", "chengzhang", "zhufu"], inverted=["chengzhang"])
        self.assertEqual(["tishu", "zhufu"], self.window.effective_bond_codes())
        cards = self.window.collect_settings_from_ui().cards
        self.assertIn("tishu", cards)
        self.assertNotIn("chengzhang", cards)


    def test_explicit_empty_scheme_keeps_effective_and_collect_empty_despite_cards(self):
        """Settings(cards=['zhufu']) 后 set_bond_scheme([]) 的 effective/collect 基础卡为空，
        且缺失 bond_scheme 键时保持 factory default (回落 cards)。
        """
        self.window.apply_settings_to_ui(Settings(cards=["zhufu"]))
        self.window.set_bond_scheme([])
        self.assertEqual([], self.window.effective_bond_codes())
        self.assertNotIn("zhufu", self.window.collect_settings_from_ui().cards)

        # 缺失 scheme 键时回落 settings.cards
        self.window._shell_extras.pop("bond_scheme", None)
        self.assertEqual(["zhufu"], self.window._effective_scheme_codes())

    def test_explicit_empty_scheme_with_attr_route_or_advanced_pack_survives_save_reload(self):
        """显式空 scheme + attr_route 或 advanced pack 保存/重载不得重新引入基础包。"""
        self.window.apply_settings_to_ui(Settings(cards=["zhufu"]))
        self.window.set_bond_scheme([])
        self.window.route_buttons["intelligence"].setChecked(True)
        self.window._on_attr_route_clicked()
        self.window._on_save_settings_clicked()

        restored = desktop_app.MainWindow(app_data=Path(self.tmp.name))
        try:
            collected = restored.collect_settings_from_ui().cards
            self.assertNotIn("zhufu", collected)
            self.assertIn("zhili", collected)
        finally:
            restored.close()

        # 高级包同理
        self.window.apply_settings_to_ui(Settings(cards=["zhufu"]))
        self.window.set_bond_scheme([])
        self.window._on_advanced_pack_toggled("daodao", True)
        self.window._on_save_settings_clicked()

        restored2 = desktop_app.MainWindow(app_data=Path(self.tmp.name))
        try:
            collected2 = restored2.collect_settings_from_ui().cards
            self.assertNotIn("zhufu", collected2)
            self.assertIn("刀刀", collected2)
        finally:
            restored2.close()

    def test_select_all_recovers_all_basic_packs_and_deselect_round_trips_accurately(self):
        """全选从空方案恢复所有基础包；反选后保存重载集合准确。"""
        self.window.apply_settings_to_ui(Settings(cards=["zhufu"]))
        self.window.set_bond_scheme([])
        self.window._select_all_basic_pack()
        all_codes = set(self.window._bond_plan_boxes.keys())
        self.assertEqual(all_codes, set(self.window.assemble_whitelist_cards()))
        self.assertEqual(all_codes, set(self.window.effective_bond_codes()))
        # 反选特定卡并保存重载
        self.window.set_bond_scheme(list(all_codes), inverted=["zhufu", "chengzhang"])
        self.window._on_save_settings_clicked()

        restored = desktop_app.MainWindow(app_data=Path(self.tmp.name))
        try:
            cards = restored.collect_settings_from_ui().cards
            self.assertNotIn("zhufu", cards)
            self.assertNotIn("chengzhang", cards)
            self.assertIn("tishu", cards)
        finally:
            restored.close()
    def test_legacy_string_attr_route_is_treated_as_implicit_default(self):
        """旧 schema（无 _shell_schema 标记）的 string attr_route 是旧版默认/推断值，
        不是用户显式选择：加载即清空，不勾选任何属性线，也不贡献 token。"""
        self.window.user_settings_path().write_text(
            json.dumps({
                "stage_targets": ["1-12"],
                "_shell": {"attr_route": "intelligence", "selected_mode_id": "normal_farm"},
            }),
            encoding="utf-8",
        )
        restored = desktop_app.MainWindow(app_data=Path(self.tmp.name))
        try:
            self.assertEqual([], restored._shell_extras.get("attr_route") or [])
            self.assertFalse(any(b.isChecked() for b in restored.route_buttons.values()))
            self.assertEqual([], restored._attr_line_tokens())
        finally:
            restored.close()

    def test_marked_bundle_explicit_attr_route_is_preserved(self):
        """新版 bundle（含 _shell_schema 标记）的显式 attr_route 必须原样保留，
        不得被迁移逻辑抹掉。"""
        self.window.user_settings_path().write_text(
            json.dumps({
                "_shell_schema": 2,
                "stage_targets": ["1-12"],
                "_shell": {"attr_route": ["intelligence"], "selected_mode_id": "normal_farm"},
            }),
            encoding="utf-8",
        )
        restored = desktop_app.MainWindow(app_data=Path(self.tmp.name))
        try:
            self.assertEqual(["intelligence"], restored._shell_extras.get("attr_route"))
            self.assertTrue(restored.route_buttons["intelligence"].isChecked())
            self.assertIn("zhili", restored._attr_line_tokens())
        finally:
            restored.close()

    def test_saved_bundle_carries_shell_schema_marker_and_round_trips_route(self):
        """保存必须写入 _shell_schema 标记；显式勾选属性线后保存→重载往返保留。"""
        self.window.route_buttons["strength"].setChecked(True)
        self.window._on_save_settings_clicked()
        saved = json.loads(self.window.user_settings_path().read_text(encoding="utf-8"))
        self.assertEqual(2, saved.get("_shell_schema"))
        self.assertEqual(["strength"], saved["_shell"]["attr_route"])
        restored = desktop_app.MainWindow(app_data=Path(self.tmp.name))
        try:
            self.assertEqual(["strength"], restored._shell_extras.get("attr_route"))
            self.assertTrue(restored.route_buttons["strength"].isChecked())
        finally:
            restored.close()

    def test_resource_page_hides_backend_must_take_and_wood_thresholds(self):
        text = self._panel_text()
        self.assertIn("待验证", text)
        self.assertNotIn("策略必拿", text)
        self.assertNotIn("不开 F", text)
        self.assertNotIn("不刷新", text)
        self.assertFalse(self.window.txt_hitch_exact.isEnabled())
        self.assertIn("后续拓展", self.window.txt_hitch_exact.placeholderText())

    def test_cycle_num_zero_does_not_draw_a_bar(self):
        self.window.spn_cycle_num.setValue(0)
        self.window.update_status(False, "空闲", 3)
        self.assertEqual([], self.window.findChildren(QProgressBar))
        self.assertIn("已完成", self.window.lbl_games_cap.text())

    def test_save_settings_writes_user_settings_for_lab(self):
        text = self._panel_text()
        self.assertIn("测试夹 bat 会读这份保存", text)
        self.assertEqual("保存设置", self.window.btn_save_settings.text())
        self.assertNotIn("保存本地配置", text)
        self.window.txt_stage_target.setText("1-12")
        self.window.cmb_mode.setCurrentIndex(self.window.cmb_mode.findData(False))
        self.window.skill_grid.set_skills(["asj", "asjg", "assx", "jq"])
        self.window._on_save_settings_clicked()
        path = self.window.user_settings_path()
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(["1-12"], data["stage_targets"])
        self.assertFalse(data["auto_reputation"])
        self.assertEqual(["asj", "asjg", "assx", "jq"], data["skills"])
        self.assertNotIn("lab_focus", data)

    def test_hitch_copy_has_no_lock_button_and_corrected_f_keys(self):
        text = self._panel_text()
        self.assertIn("只认 准备 / 已准备 / 取消准备", text)
        self.assertIn("无「锁定」按钮", text)
        self.assertIn("F1 = 操作切回自身英雄", text)
        self.assertIn("F2 = 回基地", text)
        self.assertNotIn("hitch_reject_list", text)

    def test_primary_modes_route_to_hitch_submodes_and_keep_them_disabled(self):
        self.assertIn("单人刷图", self._panel_text())
        self.assertIn("蹭车 / 跟车", self._panel_text())
        for mode_id in ("lobby_hitch", "follow_team"):
            with self.subTest(mode_id=mode_id):
                self.window._select_mode(mode_id)
                self.assertEqual(mode_id, self.window.selected_mode_id())
                self.assertFalse(self.window.btn_main.isEnabled())
                self.assertEqual("待验证 · 不可启动", self.window.btn_main.text())

    def test_test_profiles_apply_without_start_or_dry_run_change(self):
        profiles = load_test_profiles(ROOT / "config" / "dashboard_test_profiles.json")
        self.window.chk_learn.setChecked(True)
        for profile, expected_cycles in zip(profiles[:2], (1, 2)):
            with self.subTest(profile=profile["name"]):
                self.assertTrue(self.window._apply_test_profile_document(profile, confirm=False))
                settings = self.window.collect_settings_from_ui()
                self.assertEqual(["1-12"], settings.stage_targets)
                self.assertEqual(expected_cycles, settings.cycle_num)
                self.assertTrue(settings.dry_run)
        self.assertIsNone(self.window.worker_thread)

    def test_v0_profile_applies_exact_settings_on_legacy_state(self):
        legacy = Settings(
            stage_targets=["1-15"],
            cycle_num=99,
            auto_create_room=False,
            new_room_every_times=True,
            auto_reputation=True,
            reputation_type=3,
            reputation_level=5,
            auto_secret_realm=True,
            skills=["tl"],
            cards=["fs"],
            treasure_allow_negative=["some_negative"],
        )
        self.window.apply_settings_to_ui(legacy)
        self.window.chk_learn.setChecked(True)

        v0_doc = load_test_profiles(ROOT / "config" / "dashboard_test_profiles.json")[0]
        self.assertEqual("V0 单局闭环（普通模式）", v0_doc["name"])
        self.assertTrue(self.window._apply_test_profile_document(v0_doc, confirm=False))

        applied = self.window.collect_settings_from_ui()
        self.assertEqual(["1-12"], applied.stage_targets)
        self.assertEqual(1, applied.cycle_num)
        self.assertTrue(applied.auto_create_room)
        self.assertFalse(applied.new_room_every_times)
        self.assertFalse(applied.auto_reputation)
        self.assertFalse(applied.auto_secret_realm)
        self.assertEqual(["asj", "assx", "jq", "bsxx"], applied.skills)
        self.assertEqual(
            [
                "zhufu", "chengzhang", "tishu", "liliang", "tuluzhe", "zhili", "yanmiezhe", "fs",
            ],
            applied.cards,
        )
        self.assertEqual([], applied.treasure_allow_negative)
        self.assertTrue(applied.dry_run)
        self.assertIsNone(self.window.worker_thread)

        # dry_run=False 时应用 V0 仍保持 False
        self.window.chk_learn.setChecked(False)
        self.assertTrue(self.window._apply_test_profile_document(v0_doc, confirm=False))
        self.assertFalse(self.window.collect_settings_from_ui().dry_run)
        self.assertIsNone(self.window.worker_thread)

        # 保存后重新构造 MainWindow，V0 字段保持一致且无遗留 .tmp 文件
        self.window._on_save_settings_clicked()
        user_path = self.window.user_settings_path()
        self.assertTrue(user_path.is_file())
        self.assertFalse(user_path.with_suffix(user_path.suffix + ".tmp").exists())

        restored = desktop_app.MainWindow(app_data=Path(self.tmp.name))
        try:
            c = restored.collect_settings_from_ui()
            self.assertEqual(["1-12"], c.stage_targets)
            self.assertEqual(1, c.cycle_num)
            self.assertTrue(c.auto_create_room)
            self.assertFalse(c.new_room_every_times)
            self.assertFalse(c.auto_reputation)
            self.assertFalse(c.auto_secret_realm)
            self.assertEqual(["asj", "assx", "jq", "bsxx"], c.skills)
            self.assertEqual(
                [
                    "zhufu", "chengzhang", "tishu", "liliang", "tuluzhe", "zhili", "yanmiezhe", "fs",
                ],
                c.cards,
            )
            self.assertEqual([], c.treasure_allow_negative)
        finally:
            restored.close()

    def test_test_profiles_reject_non_empty_treasure_allow_negative(self):
        doc_bad = {
            "schema_version": 1,
            "name": "bad_negative",
            "mode_id": "normal_farm",
            "settings": {"stage_targets": ["1-12"], "treasure_allow_negative": ["any_item"]},
        }
        with self.assertRaises(TestProfileError):
            validate_profile_document(doc_bad)

        before = self.window.collect_settings_from_ui()
        with patch.object(desktop_app.QMessageBox, "warning"):
            self.assertFalse(self.window._apply_test_profile_document(doc_bad, confirm=False))
        after = self.window.collect_settings_from_ui()
        self.assertEqual(before.stage_targets, after.stage_targets)
        self.assertEqual(before.cards, after.cards)

        doc_good = {
            "schema_version": 1,
            "name": "good_negative",
            "mode_id": "normal_farm",
            "settings": {"stage_targets": ["1-12"], "treasure_allow_negative": []},
        }
        validated = validate_profile_document(doc_good)
        self.assertEqual([], validated["settings"]["treasure_allow_negative"])

    def test_test_profiles_reject_unknown_and_sensitive_fields(self):
        document = {
            "schema_version": 1,
            "name": "bad",
            "mode_id": "normal_farm",
            "settings": {"stage_targets": ["1-12"], "ocr_repo_root": "C:/unsafe"},
        }
        with self.assertRaises(TestProfileError):
            validate_profile_document(document)
        document["settings"] = {"stage_targets": ["1-12"], "room_password": "secret"}
        with self.assertRaises(TestProfileError):
            validate_profile_document(document)
        document["settings"] = {"stage_targets": ["1-12"], "dry_run": True}
        with self.assertRaises(TestProfileError):
            validate_profile_document(document)
        document["schema_version"] = 99
        document["settings"] = {"stage_targets": ["1-12"]}
        with self.assertRaises(TestProfileError):
            validate_profile_document(document)

    def test_test_profiles_reject_invalid_stage_and_numeric_ranges(self):
        base = {
            "schema_version": 1,
            "name": "bad",
            "mode_id": "normal_farm",
            "settings": {"stage_targets": ["1-12"]},
        }
        for targets in ([], ["1-12", "1-13"], [""], ["garbage"], ["1-x"], ["0-1"], ["1-24"], ["5-1"]):
            with self.subTest(targets=targets):
                document = json.loads(json.dumps(base))
                document["settings"]["stage_targets"] = targets
                with self.assertRaises(TestProfileError):
                    validate_profile_document(document)
        for key, value in (("cycle_num", -1), ("cycle_num", 1000), ("reputation_type", 0), ("reputation_type", 7), ("reputation_level", 0), ("reputation_level", 6)):
            with self.subTest(key=key, value=value):
                document = json.loads(json.dumps(base))
                document["settings"][key] = value
                with self.assertRaises(TestProfileError):
                    validate_profile_document(document)

    def test_invalid_profile_does_not_change_ui_learning_or_runner(self):
        self.window.chk_learn.setChecked(True)
        before = self.window.collect_settings_from_ui()
        invalid = {
            "schema_version": 1,
            "name": "bad",
            "mode_id": "normal_farm",
            "settings": {"stage_targets": ["1-12", "1-13"]},
        }
        with patch.object(desktop_app.QMessageBox, "warning"):
            self.assertFalse(self.window._apply_test_profile_document(invalid, confirm=False))
        after = self.window.collect_settings_from_ui()
        self.assertEqual(before.stage_targets, after.stage_targets)
        self.assertTrue(after.dry_run)
        self.assertIsNone(self.window.worker_thread)

    def test_missing_corrupt_or_invalid_builtin_profiles_keep_window_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = {
                "missing": root / "missing.json",
                "corrupt": root / "corrupt.json",
                "invalid": root / "invalid.json",
            }
            cases["corrupt"].write_text("{", encoding="utf-8")
            cases["invalid"].write_text('{"profiles":[{"schema_version":1}]}', encoding="utf-8")
            for name, profile_path in cases.items():
                with self.subTest(name=name), patch.object(shell_window, "TEST_PROFILES_PATH", profile_path):
                    window = desktop_app.MainWindow(app_data=root / name)
                    try:
                        self.assertFalse(window.btn_apply_test_profile.isEnabled())
                        self.assertIn("内置方案不可用", window.cmb_test_profile.itemText(1))
                    finally:
                        window.close()

    def test_saved_follow_team_mode_restores_and_remains_disabled(self):
        self.window._select_mode("follow_team")
        self.window._on_save_settings_clicked()
        restored = desktop_app.MainWindow(app_data=Path(self.tmp.name))
        try:
            self.assertEqual("follow_team", restored.selected_mode_id())
            self.assertFalse(restored.btn_main.isEnabled())
            self.assertEqual("待验证 · 不可启动", restored.btn_main.text())
        finally:
            restored.close()

    def test_invalid_saved_mode_falls_back_to_normal_farm(self):
        self.window.user_settings_path().write_text(
            json.dumps({"stage_targets": ["1-12"], "_shell": {"selected_mode_id": "not-a-mode"}}),
            encoding="utf-8",
        )
        restored = desktop_app.MainWindow(app_data=Path(self.tmp.name))
        try:
            self.assertEqual("normal_farm", restored.selected_mode_id())
        finally:
            restored.close()

    def test_mode_choice_is_two_large_entries_without_top_switching(self):
        self.window.resize(720, 600)
        self.window.show()
        self.app.processEvents()
        self.assertTrue(self.window.mode_box.isVisible())
        self.assertFalse(self.window.right_stack.isVisible())
        self.assertGreaterEqual(self.window.btn_solo_mode.width(), 300)
        self.assertGreaterEqual(self.window.btn_hitch_mode.width(), 300)
        self.window.btn_solo_mode.click()
        self.assertFalse(self.window.mode_box.isVisible())
        self.assertTrue(self.window.right_stack.isVisible())

    def test_solo_hides_room_by_default_and_supports_secret_and_multi_attr_lines(self):
        self.window._select_mode("normal_farm")
        self.assertFalse(self.window.grp_room_settings.isChecked())
        self.assertFalse(self.window.grp_bond_basic.isChecked())
        self.assertFalse(self.window.chk_secret_realm.isChecked())
        self.assertTrue(self.window.secret_options.isHidden())
        self.window.chk_secret_realm.setChecked(True)
        self.assertFalse(self.window.secret_options.isHidden())
        self.window.route_buttons["intelligence"].setChecked(True)
        self.window.route_buttons["strength"].setChecked(True)
        cards = self.window.collect_settings_from_ui().cards
        self.assertIn("zhili", cards)
        self.assertIn("liliang", cards)

    def test_test_profile_export_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            with patch.object(shell_window.QFileDialog, "getSaveFileName", return_value=(str(path), "JSON 文件 (*.json)")):
                self.window._on_export_test_profile()
            self.assertTrue(path.is_file())
            self.assertFalse(path.with_suffix(path.suffix + ".tmp").exists())
            self.assertNotIn("room_password", path.read_text(encoding="utf-8"))

    def test_profile_export_and_logs_do_not_contain_room_password(self):
        self.window.txt_room_password.setText("top-secret-pw")
        document = export_profile(self.window.collect_settings_from_ui())
        self.assertNotIn("room_password", json.dumps(document, ensure_ascii=False))
        self.window._on_save_settings_clicked()
        self.assertNotIn("top-secret-pw", self.window.txt_log.toPlainText())

    def test_user_settings_save_leaves_no_partial_file(self):
        self.window._on_save_settings_clicked()
        path = self.window.user_settings_path()
        self.assertTrue(path.is_file())
        self.assertFalse(path.with_suffix(path.suffix + ".tmp").exists())
        self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)

    def test_start_run_keeps_dashboard_visible(self):
        """CORE02：点火后看板不再自隐藏——窗口保持可见、状态栏「运行中」、
        主按钮切换为停止；用户随时可中断，不必找回窗口。"""
        from shuabao.shell.runner_service import MediatorWorker

        self.window.show()
        self.app.processEvents()
        self.assertTrue(self.window.isVisible())
        self.window.chk_learn.setChecked(True)  # 学习模式：免管理员/确认弹窗

        try:
            with patch.object(MediatorWorker, "start", lambda self: None), \
                 patch.object(MediatorWorker, "isRunning", lambda self: True):
                self.window.toggle_run()
                self.assertIsNotNone(self.window.worker_thread)
                self.assertTrue(self.window.isVisible(), "点火后看板必须保持可见")
                self.assertIn("看板保持显示", self.window.txt_log.toPlainText())
                # worker 上报运行态：状态栏与主按钮同步切换
                self.window.worker_thread.signals.status_changed.emit(True, "就绪", 0)
                self.assertEqual("运行中", self.window.lbl_run_status.text())
                self.assertIn("停止", self.window.btn_main.text())
        finally:
            self.window._status_timer.stop()
            self.window.worker_thread = None
            self.window.runner.release_after_finish()


    def test_progressive_disclosure_and_advanced_group_defaults(self):
        """验证渐进展开：默认精简首屏，高级配置默认折叠且可展开，配置不丢失。"""
        self.window._select_mode("normal_farm")
        self.assertTrue(hasattr(self.window, "grp_advanced"))
        self.assertFalse(self.window.grp_advanced.isChecked())
        self.assertFalse(self.window.cmb_mode.isHidden())
        self.assertFalse(self.window.spn_cycle_num.isHidden())
        self.assertFalse(self.window.btn_apply_build.isHidden())

        # 展开高级配置
        self.window.grp_advanced.setChecked(True)
        self.assertTrue(self.window.grp_advanced.isChecked())
        self.assertFalse(self.window.grp_skill.isChecked())
        self.assertTrue(self.window.skill_grid.isHidden())
        self.assertFalse(self.window.grp_archive.isChecked())
        self.assertTrue(self.window.archive_grid.isHidden())
        self.assertFalse(self.window.grp_details.isChecked())
        self.assertTrue(self.window.txt_log.isHidden())

        # 快速流派套用即使折叠也生效
        self.window.grp_advanced.setChecked(False)
        self.window.cmb_build.setCurrentIndex(1)
        with patch.object(
            shell_window.QMessageBox,
            "question",
            return_value=shell_window.QMessageBox.Yes,
        ):
            self.window._on_apply_build_clicked()
        collected = self.window.collect_settings_from_ui()
        self.assertTrue(len(collected.skills) > 0 or len(collected.cards) > 0)

    def test_stage_difficulty_label_and_four_skill_roundtrip(self):
        """关卡难度标签存在；5+ 技能往返截断为前 4 个且无全能文案。"""
        panel_text = self._panel_text()
        self.assertIn("关卡难度", panel_text)

        skills_7 = ["asj", "asjg", "assx", "jq", "byj", "tl", "dz"]
        self.window.skill_grid.set_skills(skills_7)
        collected = self.window.collect_settings_from_ui()
        self.assertEqual(skills_7[:4], collected.skills)

        self.window.skill_grid.set_skills([])
        self.window.apply_settings_to_ui(collected)
        self.assertEqual(skills_7[:4], self.window.skill_grid.get_skills())
        self.assertIn("严格模式", self.window.grp_skill.title())
        self.assertNotIn("全能", self.window.grp_skill.title())
        self.assertNotIn("全能", self.window.skill_grid.hint.text())

if __name__ == "__main__":
    unittest.main()
