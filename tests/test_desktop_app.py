from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QGroupBox,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
)
from PySide6.QtCore import QEvent, QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QKeyEvent  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import desktop_app  # noqa: E402
from shuabao.shell.overlay_hud import OverlayHud  # noqa: E402
from shuabao.mediator import Mediator as RealMediator  # noqa: E402
from shuabao.mediator import Phase  # noqa: E402
from shuabao.settings import Settings  # noqa: E402
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

    def test_native_dashboard_keeps_subscription_status_and_key_entry_visible(self):
        self.assertEqual(self.window.btn_activate_subscription.text(), "输入卡密")
        self.assertEqual(self.window.lbl_subscription.text(), "订阅：未激活")
        self.window._apply_subscription_result({
            "valid": True,
            "can_start_runner": True,
            "status": "ACTIVE",
            "expires_at": "2027-08-31T14:56:58Z",
        })
        self.assertEqual(self.window.lbl_subscription.text(), "订阅至 2027-08-31")

    def test_external_hud_uses_status_context_and_stays_outside_game_frame(self):
        hud = OverlayHud()
        try:
            hud.update_status(
                True,
                "MAIN_LINE",
                "就绪",
                3,
                100,
                target="1-10",
                mode="单人刷图",
                strategy="声望挑战",
            )
            self.assertEqual("自动推进", hud.status_text)
            self.assertEqual("关卡 1-10", hud.target_chip.text())
            self.assertEqual("第 3 / 100 局", hud.round_chip.text())
            self.assertEqual("声望挑战", hud.strategy_chip.text())
            self.assertFalse(hud.btn_stop.isHidden())
            self.assertGreaterEqual(hud.height(), 58)

            hud._move_to_rect(QRect(100, 200, 900, 540))
            self.assertLess(hud.y(), 200)

            screen = QGuiApplication.primaryScreen().availableGeometry()
            top_area = QRect(screen.left() + 20, screen.top(), 900, 400)
            hud._move_to_rect(top_area)
            self.assertGreater(hud.y(), top_area.bottom())

            hud.update_status(False, game_count=3, cycle_num=100, target="1-10")
            self.assertIn("已停止", hud.status_text)
            self.assertTrue(hud.btn_stop.isHidden())
        finally:
            hud.close()

    def test_hud_uses_mode_specific_gold_copy_and_hitch_preview(self):
        hud = OverlayHud()
        try:
            for mode, headline, label in (
                ("单人模式", "自动推进", "单人模式"),
                ("组队带车模式", "房间自动开局", "组队带车模式"),
                ("组队跟车模式", "房间内自动准备", "组队跟车模式"),
                ("组队蹭车模式", "大厅搜房", "组队蹭车模式"),
            ):
                hud.update_status(
                    True, "MAIN_LINE", "就绪", 3, 100,
                    target="1-10", mode=mode, strategy="声望挑战",
                )
                self.assertEqual(headline, hud.status_text)
                self.assertEqual(
                    f"{label} · 第 3 / 100 局 · 目标 1-10",
                    hud.detail_label.text(),
                )
                self.assertEqual(
                    "● 预览中" if mode == "组队蹭车模式" else "● 运行中",
                    hud.live_label.text(),
                )
                if mode == "组队蹭车模式":
                    self.assertEqual("preview", hud.status_state)
        finally:
            hud.close()

    def test_hud_stop_signal_enters_existing_real_stop_path(self):
        """HUD 停止按钮只发既有信号，并由 MainWindow._hud_stop 调 RunnerService.stop。"""
        w = self.window
        w.worker_thread = SimpleNamespace(isRunning=lambda: True)
        try:
            with patch.object(w.runner, "stop") as stop:
                w.overlay_hud.stop_requested.emit()
                stop.assert_called_once_with()
        finally:
            w.worker_thread = None


    def test_prototype12_hud_mirrors_bar_composition(self):
        """HUD 挂原型12对象名，保留真实标题/目标 chip 与停止按钮可见性语义。"""
        hud = OverlayHud()
        try:
            self.assertEqual("prototype12Hud", hud.objectName())
            self.assertEqual("hudHeadline", hud.label.objectName())
            self.assertEqual("hudDetail", hud.detail_label.objectName())
            self.assertEqual("hudChip", hud.target_chip.objectName())
            # 停止前隐藏、运行中可见（沿用既有 stop 语义，不新增停止机制）
            self.assertTrue(hud.btn_stop.isHidden())
            hud.update_status(
                True,
                "MAIN_LINE",
                "就绪",
                1,
                100,
                target="1-10",
                strategy="声望挑战",
                mode="单人",
            )
            self.assertFalse(hud.btn_stop.isHidden())
            self.assertEqual("关卡 1-10", hud.target_chip.text())
        finally:
            hud.close()

    def test_hud_compact_layout_hides_optional_meta_without_losing_status(self):
        """窄布局只隐藏可选品牌文案/摘要 chip，保留主状态、细节与停止按钮。"""
        hud = OverlayHud()
        try:
            hud.update_status(
                True,
                "MAIN_LINE",
                "就绪",
                3,
                100,
                target="1-10",
                mode="自己刷图",
                strategy="声望挑战",
            )
            hud._set_compact_layout(True)
            self.assertEqual("自动推进", hud.status_text)
            self.assertTrue(hud.btn_stop.isVisible())
            self.assertTrue(hud.target_chip.isHidden())
            self.assertTrue(hud.round_chip.isHidden())
            self.assertTrue(hud.strategy_chip.isHidden())
            self.assertTrue(hud.brand_label.isHidden())
            self.assertTrue(hud.live_label.isHidden())
            self.assertFalse(hud.logo_lbl.isHidden())
            self.assertFalse(hud.label.isHidden())
            self.assertFalse(hud.detail_label.isHidden())
            # 状态数据只改可见性，绝不重写
            self.assertEqual("关卡 1-10", hud.target_chip.text())
            self.assertEqual("第 3 / 100 局", hud.round_chip.text())
            self.assertEqual("声望挑战", hud.strategy_chip.text())
            hud._set_compact_layout(False)
            self.assertFalse(hud.target_chip.isHidden())
            self.assertFalse(hud.brand_label.isHidden())
        finally:
            hud.close()

    def test_hud_status_refresh_keeps_applied_dark_theme(self):
        """状态刷新只能重绘当前主题，不得把深色主题重置回浅色。"""
        hud = OverlayHud()
        try:
            hud.apply_theme("dark")
            hud.update_status(
                True,
                "MAIN_LINE",
                "就绪",
                1,
                2,
                target="1-10",
                mode="自己刷图",
                strategy="自动推进",
            )
            self.assertEqual("dark", hud._theme)
            self.assertIn("text_primary", hud._palette)
        finally:
            hud.close()

    def test_hud_resize_driven_compact_survives_status_refresh(self):
        """窄宽度由 resizeEvent 驱动：update_status 的 adjustSize 不得把
        可选组件重新显示出来，主状态/细节/停止与状态数据保持不变。"""
        hud = OverlayHud()
        try:
            hud.resize(OverlayHud._COMPACT_WIDTH - 100, 58)
            self.app.processEvents()
            hud.update_status(
                True,
                "MAIN_LINE",
                "就绪",
                3,
                100,
                target="1-10",
                mode="自己刷图",
                strategy="声望挑战",
            )
            self.app.processEvents()
            for widget in (hud.brand_label, hud.live_label,
                           hud.target_chip, hud.round_chip, hud.strategy_chip):
                self.assertTrue(widget.isHidden(), f"{widget.objectName()} 窄宽度应隐藏")
            self.assertFalse(hud.logo_lbl.isHidden())
            self.assertFalse(hud.label.isHidden())
            self.assertFalse(hud.detail_label.isHidden())
            self.assertTrue(hud.btn_stop.isVisible())
            self.assertEqual("自动推进", hud.status_text)
            self.assertEqual("关卡 1-10", hud.target_chip.text())
            self.assertEqual("第 3 / 100 局", hud.round_chip.text())
            self.assertEqual("声望挑战", hud.strategy_chip.text())
        finally:
            hud.close()

    def test_hud_anchor_based_compact_follows_game_area_width(self):
        """锚定到窄区紧凑隐藏可选组件；锚定到宽区恢复。"""
        hud = OverlayHud()
        try:
            # 窄游戏区 → 紧凑
            hud.anchor_to_target(QRect(0, 0, OverlayHud._COMPACT_WIDTH - 100, 400))
            hud.update_status(
                True,
                "MAIN_LINE",
                "就绪",
                3,
                100,
                target="1-10",
                mode="自己刷图",
                strategy="声望挑战",
            )
            self.app.processEvents()
            self.assertTrue(hud.target_chip.isHidden())
            self.assertTrue(hud.brand_label.isHidden())
            self.assertTrue(hud.btn_stop.isVisible())
            self.assertEqual("自动推进", hud.status_text)
            # 宽游戏区 → 恢复
            hud.anchor_to_target(QRect(0, 0, OverlayHud._COMPACT_WIDTH + 200, 400))
            hud.update_status(
                True,
                "MAIN_LINE",
                "就绪",
                3,
                100,
                target="1-10",
                mode="自己刷图",
                strategy="声望挑战",
            )
            self.app.processEvents()
            self.assertFalse(hud.target_chip.isHidden())
            self.assertFalse(hud.brand_label.isHidden())
            self.assertTrue(hud.btn_stop.isVisible())
        finally:
            hud.close()

    def test_window_status_feeds_external_hud_context(self):
        self.window.txt_stage_target.setText("1-10")
        self.window.chk_secret_realm.setChecked(True)
        self.window.update_status(True, "MAIN_LINE", 2, ocr_status="就绪")
        hud = self.window.overlay_hud
        self.assertIsNotNone(hud)
        self.assertEqual("关卡 1-10", hud.target_chip.text())
        self.assertEqual("自动秘境", hud.strategy_chip.text())
        self.assertNotIn("技能", hud.status_text)

    def test_runtime_poll_feeds_external_hud_context(self):
        self.window.txt_stage_target.setText("1-10")
        self.window.chk_secret_realm.setChecked(True)
        self.window.worker_thread = SimpleNamespace(
            mediator=SimpleNamespace(
                game_count=4,
                phase="MAIN_LINE",
                _ocr_bootstrap_health={"healthy": True},
                _trace_actions=(),
                _last_frame=None,
            ),
            isRunning=lambda: True,
        )
        try:
            self.window._poll_runtime()
            hud = self.window.overlay_hud
            self.assertEqual("关卡 1-10", hud.target_chip.text())
            self.assertEqual("自动秘境", hud.strategy_chip.text())
        finally:
            self.window.worker_thread = None

    def test_real_entry_window_exposes_live_launch_check_and_more_settings(self):
        """启动前核对只投影真实控件与现有预检结论；更多设置真实存在且可见。"""
        self.assertIsInstance(self.window, desktop_app.MainWindow)
        self.window._select_mode("normal_farm")
        self.window.show()
        try:
            self.app.processEvents()
            self.assertTrue(self.window.launch_check.isVisible())
            self.window.txt_stage_target.setText("1-10")
            self.window.skill_grid.set_skills(["asj", "asjg", "assx", "jq"])
            self.window._refresh_chrome()
            check_text = self.window.launch_check.text()
            self.assertIn("自己刷图", check_text)
            self.assertIn("1-10", check_text)
            self.assertIn("奥术箭", check_text)
            # 核对栏复用 lbl_precheck 的既有结论，不二次判定启动权限
            self.assertIn(self.window.lbl_precheck.text(), check_text)
            self.assertTrue(self.window.btn_more_settings.isVisible())

            # 真实控件变化后核对必须自动刷新（不手动调 _refresh_chrome）
            self.window.txt_stage_target.setText("2-3")
            self.app.processEvents()
            self.assertIn("2-3", self.window.launch_check.text())
        finally:
            self.window.hide()

    def test_desktop_main_preserves_theme_loaded_by_real_window(self):
        """desktop_app.main 不得在 MainWindow 已恢复设置后强制改回深色。"""
        fake_app = MagicMock()
        fake_app.exec.return_value = 0
        fake_lock = MagicMock()
        fake_lock.tryLock.return_value = True
        fake_window = MagicMock()
        fake_window.current_theme = "light"
        with (
            patch.object(desktop_app, "QApplication", return_value=fake_app),
            patch.object(desktop_app, "QLockFile", return_value=fake_lock),
            patch.object(desktop_app, "MainWindow", return_value=fake_window),
            patch.object(desktop_app, "APP_DATA", Path(self.tmp.name)),
            patch.object(desktop_app.sys, "exit"),
        ):
            desktop_app.main()
        self.assertEqual("light", fake_window.current_theme)
        fake_window.show.assert_called_once_with()

    def test_default_light_workspace_and_theme_switch_keep_hud_in_sync(self):
        """OD12 默认浅色纸面；深浅切换同步正文与 HUD，不重置 HUD 主题。"""
        w = self.window
        self.assertEqual("light", w.current_theme)
        self.assertEqual("light", w.overlay_hud._theme)
        w.toggle_theme()
        self.assertEqual("dark", w.current_theme)
        self.assertEqual("dark", w.overlay_hud._theme)
        w.toggle_theme()
        self.assertEqual("light", w.current_theme)
        self.assertEqual("light", w.overlay_hud._theme)

    def test_more_settings_toggles_advanced_group_without_changing_collected_settings(self):
        """更多设置只切换 grp_advanced 可见性，收集到的 Settings 必须逐字段不变。"""
        self.window._select_mode("normal_farm")
        before = self.window.collect_settings_from_ui()
        self.assertFalse(self.window.grp_advanced.isChecked())
        self.window.btn_more_settings.click()
        self.assertTrue(self.window.grp_advanced.isChecked())
        self.assertEqual("收起设置", self.window.btn_more_settings.text())
        after = self.window.collect_settings_from_ui()
        self.assertEqual(before, after)
        self.window.btn_more_settings.click()
        self.assertFalse(self.window.grp_advanced.isChecked())
        self.assertEqual("更多设置", self.window.btn_more_settings.text())

    def test_collapsed_advanced_settings_does_not_expand_into_blank_panel(self):
        """折叠低频设置只保留自身标题高度，不能吃掉中央列的剩余高度。"""
        w = self.window
        w._select_mode("normal_farm")
        w.show()
        try:
            self.app.processEvents()
            self.assertFalse(w.grp_advanced.isChecked())
            self.assertLessEqual(w.grp_advanced.height(), w.grp_advanced.sizeHint().height() + 8)
        finally:
            w.hide()

    def test_smart_route_panel_stays_in_workspace_before_advanced_settings(self):
        """真实入口的智能路线面板必须留在工作区，并紧挨低频高级设置之前。"""
        self.window._select_mode("normal_farm")
        workspace_layout = self.window.right_main.layout()
        route_index = workspace_layout.indexOf(self.window.smart_route_panel)
        advanced_index = workspace_layout.indexOf(self.window.grp_advanced)
        self.assertGreaterEqual(route_index, 0)
        self.assertGreater(advanced_index, route_index)

    def test_dashboard_reflows_without_horizontal_clip_at_compact_width(self):
        """窄于 920px 三段纵向堆叠且全部可见；恢复宽度回到三列布局。"""
        self.window._select_mode("normal_farm")
        self.window.show()
        try:
            self.window.resize(860, 760)
            self.app.processEvents()
            self.assertTrue(self.window.dashboard_compact)
            for section in (self.window.left_rail, self.window.right_main, self.window.launch_check):
                self.assertFalse(section.isHidden(), f"{section.objectName()} 被隐藏")
                self.assertGreater(section.width(), 0)
            # 堆叠：核对栏在左栏/工作区下方，无水平裁剪
            self.assertGreaterEqual(
                self.window.launch_check.geometry().top(),
                self.window.right_main.geometry().bottom(),
            )

            self.window.resize(1100, 780)
            self.app.processEvents()
            self.assertFalse(self.window.dashboard_compact)
            self.assertLess(self.window.left_rail.geometry().right(), self.window.right_main.geometry().left())
            self.assertLess(self.window.right_main.geometry().right(), self.window.launch_check.geometry().left())
            for section in (self.window.left_rail, self.window.right_main, self.window.launch_check):
                self.assertFalse(section.isHidden())
            self.assertLessEqual(
                self.window.launch_check.height(),
                self.window.launch_check.sizeHint().height() + 8,
            )
        finally:
            self.window.hide()

    def test_run_target_controls_stay_inside_rail_in_wide_and_compact_layouts(self):
        """运行目标栏不能只让外壳存在；真实输入控件也必须完整落在栏内。"""
        w = self.window
        w._select_mode("normal_farm")
        w.show()
        controls = (
            w.btn_chapter_picker,
            w.btn_stage_picker,
            w.chk_reputation_mode,
            w.spn_cycle_num,
            w.btn_cjb_picker,
            w.btn_boss_picker,
            w.chk_secret_realm,
            w.chk_auto_close_main_line,
            w.chk_auto_archaeology,
        )
        try:
            for width in (1000, 860):
                w.resize(width, 780)
                self.app.processEvents()
                if width < 920:
                    self.assertGreater(w.left_rail.width(), 600)
                for control in controls:
                    top_left = control.mapTo(w.left_rail, QPoint(0, 0))
                    rect = QRect(top_left, control.size())
                    self.assertTrue(
                        w.left_rail.rect().contains(rect),
                        f"{control.objectName() or type(control).__name__} 越出运行目标栏: "
                        f"control={rect.getRect()} rail={w.left_rail.rect().getRect()}",
                    )
        finally:
            w.hide()

    def test_lead_room_controls_reuse_real_normal_farm_settings_in_run_rail(self):
        """仓库无 lead ModeSpec：带车只能投影 normal_farm 的真实房间字段与 cycle_num。"""
        w = self.window
        self.assertTrue(w.left_rail.isAncestorOf(w.grp_room_settings))
        room_text = "\n".join(
            label.text() for label in w.grp_room_settings.findChildren(QLabel)
        )
        self.assertIn("带车目标局数", room_text)
        self.assertFalse(hasattr(w, "spn_lead_cycle_num"))
        before = w.collect_settings_from_ui()
        w.txt_room_name.setText("刷刷宝车队")
        w.txt_room_password.setText("2468")
        w.chk_auto_create_room.setChecked(True)
        after = w.collect_settings_from_ui()
        self.assertEqual("刷刷宝车队", after.room_name)
        self.assertEqual("2468", after.room_password)
        self.assertTrue(after.auto_create_room)
        self.assertEqual(before.cycle_num, after.cycle_num)

    def test_team_pages_match_od12_without_duplicate_launch_check(self):
        """OD12 跟车/蹭车页以主控和 footer 为准，不再追加一块重复的黄色核对栏。"""
        w = self.window
        w.show()
        try:
            for mode_id in ("follow_team", "lobby_hitch"):
                w._select_mode(mode_id)
                w.resize(860, 760)
                self.app.processEvents()
                main = w.team_page_mains[mode_id]
                check = w.team_launch_checks[mode_id]
                self.assertTrue(check.isHidden())
                self.assertGreater(main.width(), 600)
        finally:
            w.hide()

    def test_prototype12_chooser_has_solo_and_team_hierarchy(self):
        """选择页按原型12分层：单人/组队分段，组队按带车/跟车/蹭车紧凑纵列呈现。"""
        from shuabao.shell.mode_catalog import badge_text, desktop_may_start, get_spec

        w = self.window
        self.assertEqual("chooser", w._window_role)
        self.assertEqual((520, 360), (w.width(), w.height()))

        # 单人/组队分段
        self.assertEqual("单人", w.btn_seg_solo.text())
        self.assertEqual("组队", w.btn_seg_team.text())
        self.assertTrue(w.btn_seg_solo.isChecked())
        self.assertFalse(w.btn_seg_team.isChecked())

        # 初始：单人卡可见，组队行隐藏
        self.assertFalse(w.btn_solo_mode.isHidden())
        self.assertTrue(w.row_team.isHidden())

        # 切到组队：显示带车/跟车/蹭车，卡片不回退为 128px 大块旧按钮。
        w.btn_seg_team.setChecked(True)
        self.assertFalse(w.btn_seg_solo.isChecked())
        self.assertFalse(w.row_team.isHidden())
        for card in (w.btn_lead_mode, w.btn_follow_mode, w.btn_hitch_mode):
            self.assertFalse(card.isHidden())
            self.assertLessEqual(card.maximumHeight(), 72)

        # 带车是 normal_farm 的原生房间配置投影，不创造第二套运行模式。
        w.btn_lead_mode.click()
        self.assertEqual("normal_farm", w.selected_mode_id())
        self.assertEqual("lead", w.selected_mode_variant())
        self.assertFalse(w.grp_room_settings.isHidden())
        self.assertIn("带车", w.selected_mode_label())
        w._show_mode_choice()
        self.assertTrue(w.btn_seg_team.isChecked())
        self.assertTrue(w.btn_lead_mode.isChecked())

        # 蹭车文案由当前 desktop_may_start 推导，不得硬编码旧政策
        expected_badge = badge_text(get_spec("lobby_hitch"))
        self.assertEqual(
            expected_badge,
            "可启动" if desktop_may_start("lobby_hitch") else "待验证 · 不可启动",
        )
        self.assertIn(expected_badge, w.btn_hitch_mode.text())

        # 选择 / 已保存状态必须回显到相同真实卡片及所属分段，不能把跟车画成蹭车。
        w.btn_follow_mode.click()
        self.assertEqual("follow_team", w.selected_mode_id())
        self.assertTrue(w.btn_follow_mode.isChecked())
        self.assertFalse(w.btn_hitch_mode.isChecked())
        self.assertTrue(w.btn_seg_team.isChecked())
        w._show_mode_choice()
        self.assertFalse(w.row_team.isHidden())
        self.assertTrue(w.btn_follow_mode.isChecked())

        w.btn_hitch_mode.click()
        self.assertEqual("lobby_hitch", w.selected_mode_id())
        self.assertTrue(w.btn_hitch_mode.isChecked())
        self.assertFalse(w.btn_follow_mode.isChecked())

        w._select_mode("normal_farm")
        self.assertTrue(w.btn_seg_solo.isChecked())
        self.assertFalse(w.btn_seg_team.isChecked())
        w._show_mode_choice()
        self.assertFalse(w.btn_solo_mode.isHidden())
        self.assertTrue(w.row_team.isHidden())

    def test_header_quick_start_reuses_inline_chooser_without_dialog(self):
        """快速开局与切换运行方式共用主窗口内选择页，不再弹第二套向导。"""
        w = self.window
        w._select_mode("normal_farm")
        with patch("shuabao.shell.main_window.GameStyleWizardDialog.exec") as dialog_exec:
            w.btn_wizard.click()
        dialog_exec.assert_not_called()
        self.assertEqual("chooser", w._window_role)
        self.assertFalse(w.mode_box.isHidden())
        self.assertTrue(w.right_stack.isHidden())

    def test_reputation_challenge_is_visible_switch_not_difficulty_dropdown(self):
        """OD12 用“声望挑战”开关表达策略；旧普通/英雄组合框只保留为兼容状态源。"""
        w = self.window
        w._select_mode("normal_farm")
        self.assertTrue(w.cmb_mode.isHidden())
        self.assertFalse(w.chk_reputation_mode.isHidden())
        self.assertEqual("声望挑战", w.chk_reputation_mode.text())

        w.chk_reputation_mode.setChecked(True)
        self.assertTrue(bool(w.cmb_mode.currentData()))
        self.assertFalse(w.hero_options.isHidden())
        w.chk_reputation_mode.setChecked(False)
        self.assertFalse(bool(w.cmb_mode.currentData()))
        self.assertTrue(w.hero_options.isHidden())

    def test_challenge_targets_use_od12_picker_rows_with_existing_combos_as_state(self):
        """传家宝/Boss 显示为 OD12 选择行，原组合框只保留数据、图标和保存接线。"""
        w = self.window
        w._select_mode("normal_farm")
        self.assertTrue(w.cmb_cjb_boss.isHidden())
        self.assertTrue(w.cmb_sgzx_boss.isHidden())
        self.assertFalse(w.btn_cjb_picker.isHidden())
        self.assertFalse(w.btn_boss_picker.isHidden())
        self.assertIn(w.cmb_cjb_boss.currentText(), w.btn_cjb_picker.text())
        self.assertIn(w.cmb_sgzx_boss.currentText(), w.btn_boss_picker.text())

        if w.cmb_cjb_boss.count() > 1:
            w.cmb_cjb_boss.setCurrentIndex(0)
            self.assertIn(w.cmb_cjb_boss.currentText(), w.btn_cjb_picker.text())

    def test_quick_wizard_apply_only_updates_dashboard(self):
        """向导是 480px 带头部的卡片：应用只写设置并经 apply_quick_start_selection，绝不点火。"""
        from shuabao.shell.wizard_dialog import GameStyleWizardDialog

        w = self.window
        wizard = GameStyleWizardDialog(w, settings=w.settings)
        self.addCleanup(wizard.close)

        # 480px 头部卡片：眉题 + 标题 + 单人/组队分段 + 真实选项
        self.assertEqual(480, wizard.width())
        labels = [lbl.text() for lbl in wizard.findChildren(QLabel)]
        self.assertIn("刷刷宝 · 运行设置", labels)
        self.assertIn("选择运行方式", labels)
        self.assertEqual("单人", wizard.btn_seg_solo.text())
        self.assertEqual("组队", wizard.btn_seg_team.text())
        for card in (wizard.card_solo, wizard.card_follow, wizard.card_ride):
            self.assertFalse(card.isHidden())

        # 组队 → 跟车 payload 使用既有 mode id follow_team
        wizard.btn_seg_team.setChecked(True)
        wizard.card_follow.setChecked(True)
        payload = wizard._collect_payload()
        self.assertEqual("follow_team", payload["mode"])

        # 应用路径只更新看板设置，永不调用 toggle_run
        with patch.object(w, "toggle_run") as start:
            w._on_wizard_advanced(payload)
            start.assert_not_called()
        self.assertEqual("follow_team", w.settings.mode_id)

    def test_quick_wizard_restores_exact_skill_payload(self):
        """已保存的少量技能不得因预设控件残值在向导应用时被扩增。"""
        from shuabao.shell.wizard_dialog import GameStyleWizardDialog

        settings = self.window.collect_settings_from_ui()
        settings.skills = ["asj"]
        wizard = GameStyleWizardDialog(self.window, settings=settings)
        self.addCleanup(wizard.close)
        self.assertEqual(["asj"], wizard._collect_payload()["skills"])

    def test_quick_wizard_restores_team_mode_into_visible_segment(self):
        """已保存跟车必须恢复到可见组队分段和同一张模式卡。"""
        from shuabao.shell.wizard_dialog import GameStyleWizardDialog

        settings = self.window.collect_settings_from_ui()
        settings.mode_id = "follow_team"
        wizard = GameStyleWizardDialog(self.window, settings=settings)
        self.addCleanup(wizard.close)
        self.assertTrue(wizard.btn_seg_team.isChecked())
        self.assertFalse(wizard.row_team.isHidden())
        self.assertTrue(wizard.card_follow.isChecked())
        self.assertEqual("follow_team", wizard._collect_payload()["mode"])

    def test_launch_check_does_not_stretch_to_dashboard_scroll_height(self):
        """核对栏只应包裹自身文本，不能被高内容列拉成整页空白。"""
        self.window._select_mode("normal_farm")
        self.window.show()
        try:
            self.app.processEvents()
            self.assertLessEqual(
                self.window.launch_check.height(),
                self.window.launch_check.sizeHint().height() + 8,
            )
        finally:
            self.window.hide()

    def test_prototype12_shell_uses_product_regions(self):
        """原型12外壳：仪表板三段必须挂产品对象名，桌面宽度不低于 920。"""
        self.window._select_mode("normal_farm")
        self.window.show()
        try:
            self.app.processEvents()
            self.assertEqual("prototype12Dashboard", self.window.dashboard_shell.objectName())
            self.assertEqual("prototype12Rail", self.window.left_rail.objectName())
            self.assertEqual("prototype12Workspace", self.window.right_main.objectName())
            self.assertEqual("prototype12LaunchCheck", self.window.launch_check.objectName())
            self.assertGreaterEqual(self.window.width(), 920)
        finally:
            self.window.hide()

    def test_prototype12_reflow_keeps_regions_and_top_aligned_check(self):
        """860→1000 往返：三段始终可见，恢复宽窗后核对栏保持顶对齐不拉伸。"""
        self.window._select_mode("normal_farm")
        self.window.show()
        try:
            self.window.resize(860, 760)
            self.app.processEvents()
            self.assertTrue(self.window.dashboard_compact)
            for section in (self.window.left_rail, self.window.right_main, self.window.launch_check):
                self.assertFalse(section.isHidden())
                self.assertGreater(section.width(), 0)
            self.window.resize(1000, 780)
            self.app.processEvents()
            self.assertFalse(self.window.dashboard_compact)
            for section in (self.window.left_rail, self.window.right_main, self.window.launch_check):
                self.assertFalse(section.isHidden())
            self.assertEqual(
                self.window.left_rail.geometry().top(),
                self.window.launch_check.geometry().top(),
            )
            self.assertLessEqual(
                self.window.launch_check.height(),
                self.window.launch_check.sizeHint().height() + 8,
            )
        finally:
            self.window.hide()

    def test_prototype12_launch_check_has_real_configuration_sections(self):
        """核对栏按原型12分区投影真实控件值，不自行判定能否启动。"""
        self.window._select_mode("normal_farm")
        self.window.show()
        try:
            self.app.processEvents()
            self.window.txt_stage_target.setText("1-10")
            self.window.skill_grid.set_skills(["asj"])
            self.window._refresh_chrome()
            text = self.window.launch_check.text()
            for heading in (
                "启动前核对",
                "目标关卡",
                "运行方式",
                "已选技能",
                "声望挑战",
                "传家宝 / Boss",
                "细节设置",
                "基础卡组",
                "高级卡组",
            ):
                self.assertIn(heading, text)
            # 只投影：readiness 来自 lbl_precheck，其余来自真实控件当前值
            self.assertIn(self.window.lbl_precheck.text(), text)
            self.assertIn("1-10", text)
            self.assertIn("奥术箭", text)
            self.assertIn(self.window.cmb_cjb_boss.currentText(), text)
            self.assertIn(self.window.cmb_sgzx_boss.currentText(), text)
        finally:
            self.window.hide()

    def test_od12_official_builds_are_compact_icon_rows(self):
        """OD12 官方流派是 88px 名称 + 四枚图标的分隔行，不是大号技能卡。"""
        from shuabao.shell.main_window import OFFICIAL_BUILDS

        self.window._shell_extras["selected_build_id"] = ""
        self.window._rebuild_build_picker()
        self.window._rebuild_build_picker()
        official_rows = [
            self.window._build_btn_map[str(item["id"])]
            for item in OFFICIAL_BUILDS
        ]
        self.assertEqual(5, len(official_rows))
        self.assertEqual(5, len(self.window._build_btn_map))
        self.assertEqual(5, len(self.window.grp_builds.findChildren(QLabel, "buildTitle")))
        for row in official_rows:
            self.assertLessEqual(row.sizeHint().height(), 44)
            self.assertEqual(4, len(row.findChildren(QLabel, "buildSkillIcon")))
            self.assertEqual([], row.findChildren(QLabel, "buildSkillName"))
            self.assertEqual([], row.findChildren(QLabel, "buildRoute"))

    def test_od12_bond_editor_is_visible_in_main_workspace(self):
        """属性、发育、基础和高级卡组必须直接出现在中央工作区。"""
        self.window._select_mode("normal_farm")
        self.window.show()
        try:
            self.app.processEvents()
            self.assertTrue(self.window.right_main.isAncestorOf(self.window.bond_editor))
            self.assertFalse(self.window.bond_editor.isHidden())
            captions = {
                label.text()
                for label in self.window.bond_editor.findChildren(QLabel)
            }
            for caption in ("属性", "发育卡组", "基础卡组", "高级卡组候选"):
                self.assertIn(caption, captions)
        finally:
            self.window.hide()

    def test_od12_launch_check_uses_structured_rows_and_ranked_skill_icons(self):
        """右侧核对栏保留 text() 证据，同时按 OD12 分区并显示四技能编号与图标。"""
        self.window._select_mode("normal_farm")
        self.window.skill_grid.set_skills(["asj", "asjg", "assx", "jq"])
        self.window._refresh_launch_check()
        sections = self.window.launch_check.findChildren(QFrame, "launchCheckSection")
        ranks = self.window.launch_check.findChildren(QLabel, "launchSkillRank")
        icons = self.window.launch_check.findChildren(QLabel, "launchSkillIcon")
        self.assertGreaterEqual(len(sections), 8)
        self.assertEqual(["1", "2", "3", "4"], [label.text() for label in ranks])
        self.assertEqual(4, len(icons))

    def test_od12_reputation_summary_uses_selected_faction_art_cards(self):
        """声望启用时先显示当前阵营卡片，六阵营微调器由“调整”展开。"""
        self.window.cmb_mode.setCurrentIndex(self.window.cmb_mode.findData(True))
        self.window.rep_alloc_spins[3].setValue(5)
        self.window.rep_alloc_spins[4].setValue(3)
        self.window._refresh_reputation_cards()
        cards = self.window.rep_cards_host.findChildren(QFrame, "reputationCard")
        self.assertEqual(2, len(cards))
        self.assertTrue(all(card.findChild(QLabel, "reputationArt") is not None for card in cards))
        self.assertTrue(self.window.rep_alloc_editor.isHidden())
        self.window.btn_adjust_reputation.click()
        self.assertFalse(self.window.rep_alloc_editor.isHidden())

    def test_precheck_color_uses_current_theme_tokens(self):
        """预检结论复用既有判定，显示颜色必须来自当前主题而非固定深色。"""
        from shuabao.shell.theme_styles import tokens

        w = self.window
        w.current_theme = "light"
        w._apply_component_theme()
        with patch("shuabao.shell.main_window._is_admin", return_value=True):
            w._refresh_precheck()
        self.assertIn(tokens("light")["neon_success"], w.lbl_precheck.styleSheet())

    def test_native_qss_prefers_a_cjk_font_before_segoe_ui(self):
        """Qt QSS 的字体回退弱于浏览器，中文字体必须排在 Segoe UI 前避免方框。"""
        from shuabao.shell.theme_styles import get_qss

        qss = get_qss("light")
        self.assertLess(qss.index("Microsoft YaHei UI"), qss.index("Segoe UI"))

    def test_prototype12_advanced_drawer_preserves_settings(self):
        """更多设置抽屉只切换 grp_advanced 勾选与展开，不改任何收集到的设置。"""
        self.window._select_mode("normal_farm")
        before = self.window.collect_settings_from_ui()
        self.window.btn_more_settings.click()
        self.assertTrue(self.window.grp_advanced.isChecked())
        self.assertEqual("收起设置", self.window.btn_more_settings.text())
        after = self.window.collect_settings_from_ui()
        self.assertEqual(before, after)
        self.window.btn_more_settings.click()
        self.assertFalse(self.window.grp_advanced.isChecked())

    def test_prototype12_advanced_drawer_closes_on_escape(self):
        """抽屉展开时 Escape 收起，保持键盘可达。"""
        from PySide6.QtCore import Qt, QEvent
        from PySide6.QtGui import QKeyEvent

        self.window.keyPressEvent(
            QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        )
        self.window.btn_more_settings.click()
        self.assertTrue(self.window.grp_advanced.isChecked())
        self.window.keyPressEvent(
            QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        )
        self.assertFalse(self.window.grp_advanced.isChecked())

    def _launch_check_bond_line(self) -> str:
        line = next(
            (ln for ln in self.window.launch_check.text().splitlines() if ln.startswith("羁绊：")),
            "",
        )
        self.assertTrue(line, "启动前核对缺少羁绊投影行")
        return line

    def test_launch_check_tracks_bond_panel_actions(self):
        """全选/反选/添加自定义羁绊后，核对栏羁绊行必须实时跟随。"""
        self.window._select_mode("normal_farm")
        buttons = {
            btn.text(): btn
            for btn in self.window.bond_plan_host.findChildren(QPushButton)
            if btn.text() in ("全选", "反选", "添加")
        }
        before = self._launch_check_bond_line()

        buttons["全选"].click()
        after_all = self._launch_check_bond_line()
        self.assertNotEqual(before, after_all)
        self.assertIn("挑战", after_all)

        buttons["反选"].click()
        after_invert = self._launch_check_bond_line()
        self.assertNotEqual(after_all, after_invert)
        self.assertNotIn("挑战", after_invert)

        self.window.txt_custom_bond.setText("自定义测试羁绊")
        buttons["添加"].click()
        self.assertIn("自定义测试羁绊", self._launch_check_bond_line())

    def test_title_chrome_is_one_row_and_roles_flip_visibility(self):
        """单行标题栏顺序固定；chooser 收起状态/局数/版本/主题但保留快速开局与窗口控制。"""
        w = self.window
        header = w._header_frame
        order = [w.lbl_run_status, w.lbl_games, w.btn_theme, w.btn_wizard, w.btn_win_min, w.btn_win_close]
        for widget in order:
            self.assertIs(widget.parentWidget(), header)
        separators = [
            child for child in header.findChildren(QFrame) if child.frameShape() == QFrame.Shape.HLine
        ]
        self.assertEqual([], separators)

        # chooser 角色（构造后初始态）
        for hidden in (w.lbl_run_status, w.lbl_games, w.lbl_games_cap, w.lbl_version, w.btn_theme):
            self.assertTrue(hidden.isHidden(), f"{hidden.objectName()} 在选择页应为隐藏")
        for kept in (w.btn_wizard, w.btn_win_min, w.btn_win_close):
            self.assertFalse(kept.isHidden(), f"{kept.objectName()} 在选择页必须保留")
        self.assertEqual((520, 360), (w.width(), w.height()))
        self.assertEqual(w.minimumSize(), w.maximumSize())

        w._select_mode("normal_farm")
        w.show()
        try:
            self.app.processEvents()
            for shown in (
                w.lbl_run_status,
                w.lbl_games,
                w.lbl_games_cap,
                w.lbl_version,
                w.btn_theme,
                w.btn_wizard,
            ):
                self.assertFalse(shown.isHidden(), f"{shown.objectName()} 在仪表板应可见")
            # 单行：x 严格递增，垂直中心落在同一行带内
            xs = [widget.geometry().x() for widget in order]
            self.assertEqual(xs, sorted(xs))
            self.assertEqual(len(set(xs)), len(xs), f"标题栏控件 x 重叠: {xs}")
            centers = [widget.geometry().y() + widget.geometry().height() / 2 for widget in order]
            self.assertLess(max(centers) - min(centers), 40)
            # 仪表板角色可缩放契约
            self.assertGreaterEqual(w.minimumSize().width(), 680)
            self.assertGreater(w.maximumSize().width(), 100000)
        finally:
            w.hide()

    def test_saved_dashboard_mode_skips_chooser_on_next_launch(self):
        """已有本地设置的桌面启动必须恢复已保存的仪表板，而非重置到 chooser。"""
        self.window.close()
        (Path(self.tmp.name) / "user_settings.json").write_text(
            json.dumps({"_shell_schema": 2, "_shell": {"selected_mode_id": "normal_farm"}}),
            encoding="utf-8",
        )
        self.window = desktop_app.MainWindow(app_data=Path(self.tmp.name))
        self.assertEqual("dashboard", self.window._window_role)
        self.assertEqual("normal_farm", self.window.selected_mode_id())
        self.assertFalse(self.window.right_stack.isHidden())
        self.assertTrue(self.window.mode_box.isHidden())
        self.assertGreaterEqual(self.window.width(), 680)

    def test_mode_reentry_preserves_user_resized_dashboard(self):
        """再次进入仪表板（如快速开局套用）不得把用户调整过的尺寸打回 1000x780。"""
        w = self.window
        w._select_mode("normal_farm")
        w.show()
        try:
            self.app.processEvents()
            w.resize(860, 760)
            self.app.processEvents()
            self.assertTrue(w.dashboard_compact)

            w._select_mode("normal_farm")
            self.app.processEvents()
            self.assertEqual(860, w.width())
            self.assertEqual(760, w.height())
            self.assertTrue(w.dashboard_compact)
        finally:
            w.hide()

    def test_chooser_detour_restores_user_dashboard_size(self):
        """切换运行方式往返后，仪表板必须恢复用户调整过的尺寸与紧凑状态。"""
        w = self.window
        w._select_mode("normal_farm")
        w.show()
        try:
            self.app.processEvents()
            w.resize(860, 760)
            self.app.processEvents()
            self.assertTrue(w.dashboard_compact)

            w._show_mode_choice()
            self.app.processEvents()
            self.assertEqual((520, 360), (w.width(), w.height()))
            self.assertTrue(w.lbl_run_status.isHidden())

            w._select_mode("normal_farm")
            self.app.processEvents()
            self.assertEqual(860, w.width())
            self.assertEqual(760, w.height())
            self.assertTrue(w.dashboard_compact)
        finally:
            w.hide()

    def test_skill_buttons_show_chinese_names_and_fold_at_four(self):
        for code, button in self.window.skill_grid.cards.items():
            self.assertNotIn(code, button.text())
            self.assertNotIn("(", button.text())

        # 选满 4 个：保持展开以展示拖拽优先级条与专属路线下拉
        self.window.skill_grid.set_skills(["asj", "asjg", "assx", "jq"])
        self.assertTrue(self.window.grp_skill.isChecked())
        # 点勾可收起
        self.window.grp_skill.setChecked(False)
        self.assertFalse(self.window.grp_skill.isChecked())

    def test_home_page_keeps_optional_sections_collapsed(self):
        """首页默认不展开「深入设置」这类umbrella；宝物独立折叠。"""
        self.assertFalse(hasattr(self.window, "grp_deep"))
        self.assertFalse(self.window.grp_negative.isChecked())
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
        self.assertNotIn("金转木", group._boxes, "金转木由后台策略处理，不在面板勾选")
        self.assertIn("等级优势", group._boxes)
        group.set_allowed(["等级优势"])
        collected = self.window.collect_settings_from_ui()
        self.assertEqual(["等级优势"], collected.treasure_allow_negative)

        self.window.apply_settings_to_ui(collected)
        self.assertEqual(["等级优势"], self.window.grp_negative.get_allowed())
        self.assertFalse(
            self.window.grp_negative._boxes["透支力量"].isChecked(),
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
        from shuabao.shell.main_window import TREASURE_UI_HIDDEN

        self.assertEqual(
            sorted((set(DEFAULT_NEGATIVE_NAMES) | {"压制"}) - TREASURE_UI_HIDDEN),
            sorted(self.window.grp_negative._boxes),
        )

    def test_special_treasure_tooltips_do_not_claim_unverified_penalties(self):
        """特殊宝物 tooltip 不得包含无证据的负面声明，且默认阻断保持为空。"""
        group = self.window.grp_negative
        self.assertIn("收益待验证", group._boxes["贪婪献祭"].toolTip())
        self.assertNotIn("长期期望为负", group._boxes["贪婪献祭"].toolTip())
        self.assertIn("卡面未见副作用", group._boxes["等级优势"].toolTip())
        self.assertNotIn("之后不再升级", group._boxes["等级优势"].toolTip())
        self.assertEqual([], self.window.collect_settings_from_ui().treasure_allow_negative)

    def test_exact_stage_and_solo_defaults_are_fixed(self):
        # Stale in-memory fields must not leak: collection reads the visible
        # room controls, which supply the direct-create solo defaults.
        self.window.settings.room_name = "old-room"
        self.window.settings.room_password = "old-password"
        self.window.settings.lab_focus = "skill,reenter"
        self.window.txt_stage_target.setText("2-7")
        self.window.cmb_mode.setCurrentIndex(self.window.cmb_mode.findData(False))
        self.window.chk_auto_create_room.setChecked(True)
        self.window.txt_room_name.clear()
        self.window.txt_room_password.clear()
        self.window.cmb_room_reuse.setCurrentIndex(
            self.window.cmb_room_reuse.findData(False)
        )
        settings = self.window.collect_settings_from_ui()

        self.assertEqual(["2-7"], settings.stage_targets)
        self.assertEqual(7, settings.stage1)
        self.assertEqual(7, settings.stage2)
        self.assertEqual(0, settings.game_mode)
        self.assertTrue(settings.auto_create_room)
        self.assertFalse(settings.new_room_every_times)
        self.assertFalse(settings.auto_reputation)
        self.assertNotEqual("old-room", settings.room_name)
        self.assertNotEqual("old-password", settings.room_password)
        self.assertEqual("", settings.lab_focus)

    def test_room_controls_round_trip_through_collected_settings(self):
        """房间控件的真实值必须原样进入收集结果，不得被强制默认覆盖。"""
        self.window.chk_auto_create_room.setChecked(False)
        self.window.txt_room_name.setText("测试车队")
        self.window.txt_room_password.setText("pw")
        self.window.cmb_room_reuse.setCurrentIndex(
            self.window.cmb_room_reuse.findData(True)
        )
        settings = self.window.collect_settings_from_ui()

        self.assertFalse(settings.auto_create_room)
        self.assertEqual("测试车队", settings.room_name)
        self.assertEqual("pw", settings.room_password)
        self.assertTrue(settings.new_room_every_times)

    def test_applied_room_settings_survive_apply_collect_cycle(self):
        """apply → collect 往返：四个房间字段都必须保持一致。"""
        collected = self.window.collect_settings_from_ui()
        collected.auto_create_room = False
        collected.room_name = "测试车队"
        collected.room_password = "pw"
        collected.new_room_every_times = True
        self.window.apply_settings_to_ui(collected)

        self.assertFalse(self.window.chk_auto_create_room.isChecked())
        self.assertEqual("测试车队", self.window.txt_room_name.text())
        self.assertEqual("pw", self.window.txt_room_password.text())
        self.assertTrue(bool(self.window.cmb_room_reuse.currentData()))

        recollected = self.window.collect_settings_from_ui()
        self.assertFalse(recollected.auto_create_room)
        self.assertEqual("测试车队", recollected.room_name)
        self.assertEqual("pw", recollected.room_password)
        self.assertTrue(recollected.new_room_every_times)

    def test_hero_mode_maps_faction_and_difficulty(self):
        self.window.txt_stage_target.setText("1-10")
        self.window.cmb_mode.setCurrentIndex(self.window.cmb_mode.findData(True))
        self.window.rep_alloc_spins[3].setValue(5)
        settings = self.window.collect_settings_from_ui()

        self.assertTrue(settings.auto_reputation)
        self.assertEqual(3, settings.reputation_type)
        self.assertEqual(5, settings.reputation_level)
        self.assertEqual({"3": 5}, getattr(settings, "reputation_allocations", {}))
        saved = {k: v for k, v in self.window._shell_extras["rep_alloc"].items() if k != "_progress"}
        self.assertEqual({"3": 5}, saved)
        self.assertFalse(self.window.hero_options.isHidden())

    def test_rep_budget_validation_blocks_over_allocation(self):
        self.window.txt_stage_target.setText("1-8")
        self.window.cmb_mode.setCurrentIndex(self.window.cmb_mode.findData(True))
        self.window.rep_alloc_spins[3].setValue(9)
        with self.assertRaises(ValueError):
            self.window.collect_settings_from_ui()

    def test_rep_points_follow_cumulative_chapter_progress(self):
        """2-1 应为 24 点、2-2 为 25 点（累计关数），4-3 封顶 42。"""
        self.window.txt_stage_target.setText("1-23")
        self.assertEqual(23, self.window._rep_available_points())
        self.window.txt_stage_target.setText("2-1")
        self.assertEqual(24, self.window._rep_available_points())
        self.window.txt_stage_target.setText("2-2")
        self.assertEqual(25, self.window._rep_available_points())
        self.window.txt_stage_target.setText("4-3")
        self.assertEqual(42, self.window._rep_available_points())

    def test_all_six_factions_have_allocators_capped_at_ten(self):
        """六大声望阵营都应有独立分配格（单阵营上限 10 点）。"""
        expected = {
            1: "黑锋骑士团",
            2: "银色北伐军",
            3: "肯瑞托",
            4: "探险者协会",
            5: "元素领主",
            6: "守护巨龙",
        }
        spins = self.window.rep_alloc_spins
        self.assertEqual(set(expected), set(spins))
        from PySide6.QtWidgets import QLabel as _QLabel

        for fid, name in expected.items():
            spin = spins[fid]
            self.assertEqual(10, spin.maximum())
            labels = spin.parentWidget().findChildren(_QLabel)
            self.assertTrue(
                any(label.text() == name for label in labels),
                f"阵营 {name} 的分配格缺少名称标签",
            )

    def test_secret_realm_checkbox_round_trips_settings(self):
        settings = Settings(auto_secret_realm=True, stage_targets=["1-10"])
        self.window.apply_settings_to_ui(settings)
        self.assertTrue(self.window.chk_secret_realm.isChecked())
        self.assertTrue(self.window.collect_settings_from_ui().auto_secret_realm)
        self.window.chk_secret_realm.setChecked(False)

    def test_learning_mode_removed_and_dry_run_always_false(self):
        """学习模式已按需求移除：面板无该控件，dry_run 恒为 False。"""
        self.assertFalse(hasattr(self.window, "chk_learn"))
        text = self._panel_text()
        self.assertNotIn("学习模式", text)
        self.assertFalse(self.window.collect_settings_from_ui().dry_run)

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
        import shuabao.mediator as mediator_mod
        import shuabao.runtime_mediator as runtime_mediator_mod

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

        # 生产 worker 经 live_execute 延迟导入 shuabao.runtime_mediator.Mediator
        # （Mediator(CoreMediator) 子类）。若本进程已有人导入过该模块（如
        # test_bond_completion_runtime），仅 patch 基类无法生效——测试顺序依赖
        # 会让 probe 静默失效。两个模块一起 patch，保证任何导入顺序下都走 probe。
        class RuntimeFailClosedProbeMediator(runtime_mediator_mod.Mediator, FailClosedProbeMediator):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mediator_mod, "Mediator", FailClosedProbeMediator),                     patch.object(runtime_mediator_mod, "Mediator", RuntimeFailClosedProbeMediator):
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
        self.assertIn("声望挑战", text)
        self.assertNotIn("关卡难度", text)
        self.assertFalse(self.window.chk_reputation_mode.isHidden())
        self.assertTrue(self.window.cmb_mode.isHidden())
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
        from shuabao.shell.runner_service import ModeNotEnabled, RunnerService

        svc = RunnerService(Path(self.tmp.name), ROOT)
        with patch("shuabao.shell.runner_service.MediatorWorker") as worker_cls:
            # 产品真值：normal_farm/follow_team/lobby_hitch 已放开桌面启动；
            # 仅 gambling_wood/raid_wait/lab 仍禁止（mode_specs.json desktop_start=false）。
            for mode_id in ("gambling_wood", "raid_wait", "lab"):
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
        self.assertIn("zhufu", after, "祝福三张系统必拿，反选不得拿掉")
        self.assertNotIn("chengzhang", after)

    def test_treasure_and_wood_controls_are_labeled_or_disabled(self):
        text = self._panel_text()
        self.assertIn("待接线", text)
        self.assertIn("待验证", text)
        self.assertNotIn("策略必拿", text)
        self.assertFalse(self.window.spn_wood_open_f.isEnabled())
        self.assertFalse(self.window.spn_wood_refresh.isEnabled())
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

    def test_auto_archaeology_and_auto_close_main_line_persisted(self):
        self.window.chk_auto_archaeology.setChecked(False)
        self.window.chk_auto_close_main_line.setChecked(True)
        settings = self.window.collect_settings_from_ui()
        self.assertFalse(settings.auto_archaeology)
        self.assertTrue(settings.auto_close_main_line)

        self.window.chk_auto_archaeology.setChecked(True)
        self.window.chk_auto_close_main_line.setChecked(False)
        settings2 = self.window.collect_settings_from_ui()
        self.assertTrue(settings2.auto_archaeology)
        self.assertFalse(settings2.auto_close_main_line)

    def test_team_targets_and_handoff_plans_round_trip(self):
        self.window.spn_cycle_num.setValue(7)
        self.window.spn_follow_cycle_num.setValue(12)
        self.window.spn_hitch_cycle_num.setValue(18)
        self.window.cmb_follow_after_room.setCurrentIndex(
            self.window.cmb_follow_after_room.findData("hitch")
        )
        self.window.cmb_hitch_after_goal.setCurrentIndex(
            self.window.cmb_hitch_after_goal.findData("arch")
        )
        self.window.txt_follow_pair_code.setText("  双端-01  ")
        settings = self.window.collect_settings_from_ui()
        self.assertEqual(7, settings.cycle_num)
        self.assertEqual(12, settings.follow_cycle_num)
        self.assertEqual(18, settings.hitch_cycle_num)
        self.assertEqual("hitch", settings.follow_after_room)
        self.assertEqual("arch", settings.hitch_after_goal)
        self.assertEqual("双端-01", settings.follow_pair_code)

        self.window.apply_settings_to_ui(settings)
        self.assertEqual(12, self.window.spn_follow_cycle_num.value())
        self.assertEqual(18, self.window.spn_hitch_cycle_num.value())
        self.assertEqual("hitch", self.window.cmb_follow_after_room.currentData())
        self.assertEqual("arch", self.window.cmb_hitch_after_goal.currentData())
        self.assertEqual("双端-01", self.window.txt_follow_pair_code.text())

    def test_team_mode_projects_its_own_target_into_runner_snapshot(self):
        from shuabao.shell.runner_service import RunnerService

        service = RunnerService(Path(self.tmp.name), ROOT)
        worker = service.start(
            "follow_team",
            Settings(cycle_num=7, follow_cycle_num=12, hitch_cycle_num=18),
        )
        self.assertEqual(12, worker.settings.cycle_num)
        service.release_after_finish()
        worker = service.start(
            "lobby_hitch",
            Settings(cycle_num=7, follow_cycle_num=12, hitch_cycle_num=18),
        )
        self.assertEqual(18, worker.settings.cycle_num)
        service.release_after_finish()

    def test_team_settings_are_sanitized_fail_closed(self):
        settings = Settings._from_dict({
            "follow_cycle_num": 5000,
            "hitch_cycle_num": -4,
            "follow_after_room": "unknown",
            "hitch_after_goal": "hitch",
            "follow_pair_code": " x " * 20,
        })
        self.assertEqual(999, settings.follow_cycle_num)
        self.assertEqual(0, settings.hitch_cycle_num)
        self.assertEqual("solo", settings.follow_after_room)
        self.assertEqual("solo", settings.hitch_after_goal)
        self.assertLessEqual(len(settings.follow_pair_code), 24)

    def test_desktop_exposes_current_opendesign_revision(self):
        self.assertIn("OD12 · 87853C96", self.window.windowTitle())
        self.assertIn("OD12 · 87853C96", self.window.lbl_version.text())

    def _visible_dialogs(self):
        return [
            widget
            for widget in QApplication.topLevelWidgets()
            if isinstance(widget, QDialog) and widget.isVisible()
        ]

    def _select_custom_skills(self, codes):
        w = self.window
        w._select_mode("normal_farm")
        w._add_custom_build()
        w.skill_grid.set_skills(codes)
        w._refresh_launch_check()
        return w

    def test_skill_select_does_not_open_order_dialog(self):
        """选技能后不得再弹出独立“顺序调整”窗口。"""
        w = self._select_custom_skills(["asj", "asjg"])
        titles = [dlg.windowTitle() for dlg in self._visible_dialogs()]
        self.assertEqual([], titles)
        self.assertFalse(w.skill_priority_bar.isHidden())
        self.assertEqual(["asj", "asjg"], w.skill_priority_bar.order())
        self.assertTrue(w.right_main.isAncestorOf(w.skill_priority_bar))

    def test_selected_skills_reorder_and_remove_write_settings(self):
        w = self._select_custom_skills(["asj", "asjg", "assx", "jq"])
        cards = w.skill_priority_bar.findChildren(QFrame, "skillRankCard")
        self.assertEqual(4, len(cards))
        down = [
            btn for btn in cards[0].findChildren(QPushButton, "skillRankMove")
            if btn.text() == "▼"
        ][0]
        down.click()
        self.assertEqual(["asjg", "asj", "assx", "jq"], w.skill_priority_bar.order())
        collected = w.collect_settings_from_ui()
        self.assertEqual(["asjg", "asj", "assx", "jq"], collected.skills)
        self.assertEqual(["asjg", "asj", "assx", "jq"], collected.skill_priority)

        cards = w.skill_priority_bar.findChildren(QFrame, "skillRankCard")
        remove = cards[0].findChild(QPushButton, "skillRankRemove")
        remove.click()
        self.assertEqual(["asj", "assx", "jq"], w.skill_priority_bar.order())
        self.assertEqual(["asj", "assx", "jq"], w.collect_settings_from_ui().skills)

    def test_launch_check_skills_follow_inline_rank_order(self):
        w = self._select_custom_skills(["asj", "asjg", "assx", "jq"])
        cards = w.skill_priority_bar.findChildren(QFrame, "skillRankCard")
        down = [
            btn for btn in cards[0].findChildren(QPushButton, "skillRankMove")
            if btn.text() == "▼"
        ][0]
        down.click()
        w._refresh_launch_check()
        ranks = [label.text() for label in w.launch_check.findChildren(QLabel, "launchSkillRank")]
        self.assertEqual(["1", "2", "3", "4"], ranks)
        self.assertEqual(["asjg", "asj", "assx", "jq"], w.launch_check._skill_codes)

    def test_skill_route_expands_in_page_and_writes_settings(self):
        w = self._select_custom_skills(["asj", "jq"])
        self.assertEqual([], self._visible_dialogs())
        route_btn = w.skill_priority_bar.findChild(QPushButton, "skillRouteBtn")
        self.assertIsNotNone(route_btn)
        route_btn.click()
        self.assertTrue(w.skill_priority_bar.route_expanded())
        self.assertEqual([], self._visible_dialogs())
        options = w.skill_priority_bar.findChildren(QPushButton, "skillRouteOption")
        self.assertGreaterEqual(len(options), 2)
        options[1].click()
        self.assertFalse(w.skill_priority_bar.route_expanded())
        routes = w.collect_settings_from_ui().skill_custom_routes
        self.assertIn("asj", routes)
        self.assertTrue(routes["asj"])

        route_btn = w.skill_priority_bar.findChild(QPushButton, "skillRouteBtn")
        route_btn.click()
        self.assertTrue(w.skill_priority_bar.route_expanded())
        w.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.assertFalse(w.skill_priority_bar.route_expanded())

    def test_reputation_and_stage_pickers_are_inline_not_dropdowns(self):
        w = self.window
        w._select_mode("normal_farm")
        w.show()
        try:
            self.app.processEvents()
            self.assertTrue(w.cmb_mode.isHidden())
            self.assertTrue(w.cmb_chapter.isHidden())
            self.assertTrue(w.cmb_stage.isHidden())
            self.assertFalse(w.chk_reputation_mode.isHidden())
            self.assertFalse(w.btn_chapter_picker.isHidden())
            self.assertFalse(w.btn_stage_picker.isHidden())

            w.chk_reputation_mode.setChecked(True)
            self.assertTrue(bool(w.cmb_mode.currentData()))
            self.assertFalse(w.hero_options.isHidden())
            w.btn_adjust_reputation.click()
            self.assertFalse(w.rep_alloc_editor.isHidden())
            self.assertEqual([], self._visible_dialogs())

            w.btn_stage_picker.click()
            self.app.processEvents()
            self.assertFalse(w.inline_overlay.isHidden())
            self.assertEqual([], self._visible_dialogs())
            choices = w.inline_overlay.findChildren(QPushButton, "inlineOverlayChoice")
            self.assertGreaterEqual(len(choices), 2)
            target = next(btn for btn in choices if btn.text() == "1-12")
            target.click()
            self.app.processEvents()
            self.assertTrue(w.inline_overlay.isHidden())
            self.assertEqual("1-12", w.txt_stage_target.text())
            self.assertIn("1-12", w.launch_check.text())
            self.assertEqual("1-12", w.collect_settings_from_ui().stage_targets[0])
        finally:
            w.hide()

    def test_challenge_and_boss_pickers_use_inline_overlay(self):
        w = self.window
        w._select_mode("normal_farm")
        w.show()
        try:
            self.app.processEvents()
            if w.cmb_cjb_boss.count() < 2:
                self.skipTest("no heirloom icons in this checkout")
            before = w.cmb_cjb_boss.currentIndex()
            w.btn_cjb_picker.click()
            self.app.processEvents()
            self.assertFalse(w.inline_overlay.isHidden())
            self.assertEqual([], self._visible_dialogs())
            self.assertIs(w.btn_cjb_picker, w.inline_overlay.trigger())
            choices = w.inline_overlay.findChildren(QPushButton, "inlineOverlayChoice")
            self.assertGreaterEqual(len(choices), 2)
            pick = 0 if before != 0 else 1
            choices[pick].click()
            self.app.processEvents()
            self.assertTrue(w.inline_overlay.isHidden())
            self.assertEqual(pick, w.cmb_cjb_boss.currentIndex())
            self.assertIn(w.cmb_cjb_boss.currentText(), w.launch_check.text())
            self.assertEqual(w.cmb_cjb_boss.currentData(), w.collect_settings_from_ui().cjb_boss)

            w.btn_boss_picker.click()
            self.app.processEvents()
            self.assertFalse(w.inline_overlay.isHidden())
            w.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
            self.app.processEvents()
            self.assertTrue(w.inline_overlay.isHidden())
            self.assertIs(w.btn_boss_picker, w.focusWidget())
        finally:
            w.hide()

    def test_mode_switch_does_not_open_wizard_dialog(self):
        w = self.window
        w._select_mode("follow_team")
        self.assertEqual([], self._visible_dialogs())
        with patch("shuabao.shell.main_window.GameStyleWizardDialog.exec") as dialog_exec:
            w.btn_wizard.click()
            w.btn_solo_mode.click()
        dialog_exec.assert_not_called()
        self.assertEqual([], self._visible_dialogs())
        self.assertEqual("normal_farm", w.selected_mode_id())

    def test_inline_overlays_stay_inside_window_at_860(self):
        w = self.window
        w._select_mode("normal_farm")
        w.show()
        try:
            w.resize(860, 760)
            self.app.processEvents()
            self.assertTrue(w.dashboard_compact)
            for opener in (w.btn_chapter_picker, w.btn_stage_picker, w.btn_cjb_picker, w.btn_boss_picker):
                opener.click()
                self.app.processEvents()
                self.assertTrue(w.inline_overlay.isVisible(), opener.objectName())
                geo = w.inline_overlay.geometry()
                host = w.centralWidget().rect()
                self.assertGreaterEqual(geo.left(), host.left())
                self.assertGreaterEqual(geo.top(), host.top())
                self.assertLessEqual(geo.right(), host.right())
                self.assertLessEqual(geo.bottom(), host.bottom())
                self.assertFalse(w.horizontalScrollBar().isVisible() if hasattr(w, "horizontalScrollBar") else False)
                w.inline_overlay.dismiss()
            for area in w.findChildren(QScrollArea):
                bar = area.horizontalScrollBar()
                self.assertFalse(bar.isVisible() and bar.maximum() > 0)
            self.assertLessEqual(w.centralWidget().width(), w.width())
        finally:
            w.hide()

    def test_overlay_outside_click_and_reduce_motion_keep_behavior(self):
        w = self.window
        w._select_mode("normal_farm")
        w.show()
        try:
            os.environ["SHUABAO_REDUCE_MOTION"] = "1"
            w.btn_chapter_picker.click()
            self.assertTrue(w.inline_overlay.isVisible())
            self.assertIsNone(w.inline_overlay.graphicsEffect())
            press = QEvent(QEvent.Type.MouseButtonPress)
            w.inline_overlay.eventFilter(w.left_rail, press)
            self.assertTrue(w.inline_overlay.isHidden())
            self.assertIs(w.btn_chapter_picker, w.focusWidget())
        finally:
            os.environ.pop("SHUABAO_REDUCE_MOTION", None)
            w.hide()

    def test_skill_limit_feedback_is_inline_not_message_box(self):
        w = self._select_custom_skills(["asj", "asjg", "assx", "jq"])
        extra = next(code for code in w.skill_grid.cards if code not in w.skill_grid.get_skills())
        with patch("shuabao.shell.main_window.QMessageBox.information") as boxed:
            w.skill_grid._toggle(extra, True)
        boxed.assert_not_called()
        self.assertEqual(4, len(w.skill_grid.get_skills()))
        self.assertTrue(w.skill_grid.cards[extra].property("dimmed"))
        self.assertIn("已满", w.skill_grid.hint.text())

    def test_hud_still_omits_skill_configuration(self):
        hud = OverlayHud()
        try:
            hud.update_status(
                True, "MAIN_LINE", "就绪", 2, 100,
                target="1-10", mode="单人刷图", strategy="声望挑战",
            )
            blob = " ".join([hud.status_text, hud.detail_label.text(), hud.target_chip.text(), hud.strategy_chip.text()])
            self.assertNotIn("奥术箭", blob)
            self.assertNotIn("asj", blob)
            self.assertIn("声望挑战", blob)
            self.assertIn("1-10", blob)
        finally:
            hud.close()

if __name__ == "__main__":
    unittest.main()
