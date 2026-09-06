"""Runtime HUD pinned to the game client: status + clickable stop.

Not click-through — the stop button must receive mouse events.
"""

from __future__ import annotations

import sys
from typing import Any

from pathlib import Path
from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from shuabao.shell.theme_styles import tokens


_HUD_MODE_LABELS = {
    "solo": "单人模式",
    "lead": "组队带车模式",
    "follow": "组队跟车模式",
    "hitch": "组队蹭车模式",
}
_HUD_MODE_HEADLINES = {
    "solo": "自动推进",
    "lead": "房间自动开局",
    "follow": "房间内自动准备",
    "hitch": "大厅搜房",
}
_HUD_MODE_ALIASES = {
    "normal_farm": "solo",
    "单人": "solo",
    "单人刷图": "solo",
    "单人模式": "solo",
    "自己刷图": "solo",
    "lead_team": "lead",
    "带车": "lead",
    "组队带车": "lead",
    "组队 · 带车": "lead",
    "组队  带车": "lead",
    "组队带车模式": "lead",
    "follow_team": "follow",
    "跟车": "follow",
    "组队跟车": "follow",
    "组队 · 跟车": "follow",
    "组队  跟车": "follow",
    "组队跟车模式": "follow",
    "lobby_hitch": "hitch",
    "蹭车": "hitch",
    "组队蹭车": "hitch",
    "组队 · 蹭车": "hitch",
    "组队  蹭车": "hitch",
    "组队蹭车模式": "hitch",
}


def _normalize_hud_mode(value: str) -> tuple[str, str, str]:
    raw = str(value or "").strip()
    key = _HUD_MODE_ALIASES.get(raw, raw if raw in _HUD_MODE_LABELS else "solo")
    return key, _HUD_MODE_LABELS[key], _HUD_MODE_HEADLINES[key]


def _hwnd_client_rect(hwnd: int) -> QRect | None:
    if not hwnd:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetClientRect(int(hwnd), ctypes.byref(rect)):
            return None
        pt = wintypes.POINT(0, 0)
        if not ctypes.windll.user32.ClientToScreen(int(hwnd), ctypes.byref(pt)):
            return None
        w = int(rect.right - rect.left)
        h = int(rect.bottom - rect.top)
        if w < 200 or h < 200:
            return None
        return QRect(int(pt.x), int(pt.y), w, h)
    except Exception:
        return None


class OverlayHud(QWidget):
    """External game-status bar with a stop button. Does not steal game focus."""

    stop_requested = Signal()
    STOPPED_HIDE_MS = 3500
    # 全量内容（品牌 + 三枚 chip）约需 890px；低于该宽度只保留主状态/细节/停止。
    _COMPACT_WIDTH = 800

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setObjectName("prototype12Hud")
        self.setFixedHeight(58)
        self.setMinimumWidth(620)
        self.setWindowOpacity(0.96)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 10, 7)
        layout.setSpacing(10)

        brand = QWidget()
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(0, 0, 10, 0)
        brand_layout.setSpacing(6)
        self.logo_lbl = QLabel()
        self.logo_lbl.setFixedSize(20, 20)
        # 打包后 assets 在 _MEIPASS（_internal）下；源码模式才按源树回溯仓库根。
        # 旧写法只用 parents[3]，冻结包内 __file__ 少 src/ 一层 → 指到应用根，
        # logo 静默丢失（20260828 用户反馈：局内 title HUD 不再显示 logo）。
        logo_path = (
            Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
            / "assets" / "branding" / "app_logo.png"
        )
        if logo_path.exists():
            pix = QPixmap(str(logo_path)).scaled(
                20, 20,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.logo_lbl.setPixmap(pix)
            self.setWindowIcon(QIcon(str(logo_path)))
        brand_layout.addWidget(self.logo_lbl)
        brand_copy = QVBoxLayout()
        brand_copy.setContentsMargins(0, 0, 0, 0)
        brand_copy.setSpacing(0)
        self.brand_label = QLabel("刷刷宝")
        self.brand_label.setObjectName("hudBrand")
        self.live_label = QLabel("● 运行中")
        self.live_label.setObjectName("hudLive")
        brand_copy.addWidget(self.brand_label)
        brand_copy.addWidget(self.live_label)
        brand_layout.addLayout(brand_copy)
        layout.addWidget(brand, 0)

        message = QWidget()
        message_layout = QVBoxLayout(message)
        message_layout.setContentsMargins(0, 0, 0, 0)
        message_layout.setSpacing(1)
        self.label = QLabel("已停止，等待下一次指令")
        self.label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.label.setObjectName("hudHeadline")
        self.detail_label = QLabel("目标待确认")
        self.detail_label.setObjectName("hudDetail")
        message_layout.addWidget(self.label)
        message_layout.addWidget(self.detail_label)
        layout.addWidget(message, 1)

        self.target_chip = QLabel("目标 待确认")
        self.target_chip.setObjectName("hudChip")
        self.round_chip = QLabel("第 0 局")
        self.round_chip.setObjectName("hudChip")
        self.strategy_chip = QLabel("自动推进")
        self.strategy_chip.setObjectName("hudStrategyChip")
        for chip in (self.target_chip, self.round_chip, self.strategy_chip):
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(chip, 0)

        self.btn_stop = QPushButton("停止")
        self.btn_stop.setObjectName("hudStop")
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.setToolTip("立即结束脚本（F12 或 Shift+F12）")
        self.btn_stop.setFixedHeight(22)
        self.btn_stop.setMinimumWidth(52)
        self.btn_stop.clicked.connect(self._emit_stop)
        self.btn_stop.hide()

        layout.addWidget(self.btn_stop, 0)
        for seq in ("F12", "Shift+F12"):
            shortcut = QShortcut(QKeySequence(seq), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(self._emit_stop)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(self.STOPPED_HIDE_MS)
        self._hide_timer.timeout.connect(self.hide)
        self._status_state = "idle"
        self._pinned_rect: QRect | None = None
        self._drag_pos: QPoint | None = None
        self._user_moved = False
        self._has_game_window = False
        self._compact_layout = False
        self.apply_theme("light")

    def _emit_stop(self) -> None:
        self.stop_requested.emit()

    def _status_accent(self) -> QColor:
        t = self._palette
        state = getattr(self, "_status_state", "idle")
        if state == "running":
            return QColor(t["neon_success"])
        if state == "error":
            return QColor(t["neon_danger"])
        if state == "preview":
            return QColor(t["accent_gold"])
        if state in ("paused", "recovering"):
            return QColor(t["neon_warning"])
        return QColor(t["accent_gold"])

    def apply_theme(self, theme: str = "light") -> None:
        t = tokens(theme)
        self._theme = theme
        self._palette = t
        accent = self._status_accent().name()
        headline_color = t["neon_danger"] if self._status_state == "preview" else t["text_primary"]
        self.label.setStyleSheet(
            f"QLabel#hudHeadline {{ color: {headline_color}; background: transparent; border: none; "
            "font: 700 13px 'Microsoft YaHei UI', sans-serif; }"
        )
        self.detail_label.setStyleSheet(
            f"QLabel#hudDetail {{ color: {t['text_secondary']}; background: transparent; border: none; "
            "font: 600 11px 'Microsoft YaHei UI', sans-serif; }"
        )
        self.brand_label.setStyleSheet(
            f"QLabel#hudBrand {{ color: {t['text_primary']}; font: 700 12px 'Microsoft YaHei UI', sans-serif; }}"
        )
        self.live_label.setStyleSheet(
            f"QLabel#hudLive {{ color: {accent}; font: 700 10px 'Microsoft YaHei UI', sans-serif; }}"
        )
        chip_qss = (
            f"background: {t['bg_subtle']}; color: {t['text_secondary']}; "
            f"border: 1px solid {t['border_subtle']}; border-radius: 5px; padding: 4px 8px; "
            "font: 700 11px 'Microsoft YaHei UI', sans-serif;"
        )
        self.target_chip.setStyleSheet(chip_qss)
        self.round_chip.setStyleSheet(chip_qss)
        self.strategy_chip.setStyleSheet(
            f"background: {t['neon_warning_bg']}; color: {t['accent_gold_light']}; "
            f"border: 1px solid {t['accent_gold_dark']}; border-radius: 5px; padding: 4px 8px; "
            "font: 700 11px 'Microsoft YaHei UI', sans-serif;"
        )
        self.btn_stop.setStyleSheet(
            f"QPushButton#hudStop {{ background: {t['accent_danger']}; color: {t['text_primary']}; border: none; border-radius: 5px; "
            "padding: 2px 10px; font: 700 12px 'Microsoft YaHei UI', sans-serif; }"
            f"QPushButton#hudStop:hover {{ background: {t['accent_danger_hover']}; }}"
            "QPushButton#hudStop:pressed { padding-top: 1px; }"
        )
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(float(rect.x()), float(rect.y()), float(rect.width()), float(rect.height()), 8, 8)
        # 纯黑高对比底色 (95% 不透明度)
        bg = QColor(self._palette["bg_surface"])
        bg.setAlpha(245)
        painter.fillPath(path, bg)
        # 顶部高亮细边
        accent = self._status_accent()
        painter.setPen(QPen(accent, 1.5))
        painter.drawPath(path)
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            self._user_moved = True
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def _paint_status(self) -> None:
        self.apply_theme(self._theme)

    def _set_compact_layout(self, compact: bool) -> None:
        """窄宽度下只隐藏可选品牌文案与三枚摘要 chip；状态数据与停止按钮保留。"""
        if compact == self._compact_layout:
            return
        self._compact_layout = compact
        for widget in (
            self.brand_label,
            self.live_label,
            self.target_chip,
            self.round_chip,
            self.strategy_chip,
        ):
            widget.setHidden(compact)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 未锚定游戏区（独立预览）时用自身宽度决定紧凑度；
        # 已锚定时由 _accept_rect 依据游戏区宽度控制。
        if self._pinned_rect is None:
            self._set_compact_layout(self.width() < self._COMPACT_WIDTH)

    @property
    def status_state(self) -> str:
        return self._status_state

    @property
    def status_text(self) -> str:
        return self.label.text()

    def _state_for(self, running: bool, phase: str, terminal_reason: str) -> str:
        if running:
            text = str(phase or "").upper()
            if "RECOVER" in text or "PAUSE" in text or "WAIT" in text:
                return "recovering" if "RECOVER" in text else "paused"
            return "running"
        if terminal_reason and any(
            token in terminal_reason.lower() for token in ("error", "fail", "异常", "失败", "不可用")
        ):
            return "error"
        return "stopped"

    def update_status(
        self,
        running: bool,
        phase: str = "",
        ocr_status: str = "",
        game_count: int = 0,
        cycle_num: int = 0,
        terminal_reason: str = "",
        last_action: str = "",
        target: str = "",
        mode: str = "",
        strategy: str = "",
    ) -> None:
        phase_text = str(phase or "").strip()
        ocr_text = str(ocr_status or "").strip()
        count = max(0, int(game_count or 0))
        cycle = max(0, int(cycle_num or 0))
        reason = str(terminal_reason or "").strip()
        target_text = str(target or "待确认").strip()
        mode_key, mode_label, headline = _normalize_hud_mode(mode)
        strategy_text = str(strategy or "自动推进").strip()
        round_text = f"第 {count} / {cycle} 局" if cycle else f"第 {count} 局"
        preview = running and mode_key == "hitch"
        if running:
            text = headline
            self.detail_label.setText(f"{mode_label} · {round_text} · 目标 {target_text}")
            self.live_label.setText("● 预览中" if preview else "● 运行中")
            self.btn_stop.show()
        else:
            text = "已停止，等待下一次指令"
            detail = round_text
            if reason:
                detail = f"{detail} · {reason}"
            if last_action:
                self.setToolTip(f"最后动作：{last_action}")
            self.detail_label.setText(detail)
            self.live_label.setText("● 已停止")
            self.btn_stop.hide()

        self.label.setText(text)
        self.target_chip.setText(f"关卡 {target_text}")
        self.round_chip.setText(round_text)
        self.strategy_chip.setText(strategy_text)
        self._status_state = self._state_for(running, phase_text, reason)
        if preview:
            self._status_state = "preview"
        self._paint_status()
        self.adjustSize()
        self._move_pinned()
        self.show()
        self.raise_()
        self._hide_timer.stop()
        if not running:
            self.setWindowOpacity(0.82)
            self._hide_timer.start()
        else:
            self.setWindowOpacity(0.96)

    def _accept_rect(self, rect: QRect | None, is_game: bool) -> None:
        if rect is None or not rect.isValid() or rect.width() < 200 or rect.height() < 200:
            return
        if rect.top() < -100:
            return
        # 锚定游戏区宽度决定运行时紧凑度：窄区隐藏可选组件、宽区恢复；
        # 位置仍走下方原有锁定逻辑，不随宽度变化。
        self._set_compact_layout(rect.width() < self._COMPACT_WIDTH)
        # 已经吸附过游戏窗口后直接永久锁定，不再随帧浮动
        if self._has_game_window:
            return
        if is_game:
            self._has_game_window = True
            self._pinned_rect = QRect(rect)
        elif self._pinned_rect is None:
            self._pinned_rect = QRect(rect)
        elif not self._has_game_window:
            # 若两者均非游戏窗（如平台窗口），且位移小于 16 像素，视为同一个窗口不抖动
            dx = abs(self._pinned_rect.x() - rect.x())
            dy = abs(self._pinned_rect.y() - rect.y())
            dw = abs(self._pinned_rect.width() - rect.width())
            dh = abs(self._pinned_rect.height() - rect.height())
            if dx > 16 or dy > 16 or dw > 16 or dh > 16:
                self._pinned_rect = QRect(rect)
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        screen_geo = screen.availableGeometry()
        area = self._pinned_rect
        if area is None or not area.isValid():
            area = screen_geo

        x = area.left() + max(0, (area.width() - self.width()) // 2)
        hud_h = max(self.height(), 36)
        if area.top() - screen_geo.top() >= hud_h + 4:
            y = area.top() - hud_h - 4
        elif screen_geo.bottom() - area.bottom() >= hud_h + 4:
            y = area.bottom() + 4
        else:
            y = screen_geo.top() + 4
        self.move(QPoint(x, y))

    def _move_pinned(self) -> None:
        if self._user_moved:
            return
        if self._pinned_rect is not None:
            self._move_to_rect(self._pinned_rect)
        else:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                x = geo.left() + max(0, (geo.width() - self.width()) // 2)
                self.move(QPoint(x, geo.top() + 8))

    def _move_default(self) -> None:
        self._move_pinned()
    def _move_to_rect(self, area: QRect) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        screen_geo = screen.availableGeometry()
        if area is None or not area.isValid():
            area = screen_geo
        x = area.left() + max(0, (area.width() - self.width()) // 2)
        hud_h = max(self.height(), 36)
        if area.top() - screen_geo.top() >= hud_h + 4:
            y = area.top() - hud_h - 4
        elif screen_geo.bottom() - area.bottom() >= hud_h + 4:
            y = area.bottom() + 4
        else:
            y = screen_geo.top() + 4
        self.move(QPoint(x, y))

    def anchor_to_target(self, target: Any = None) -> None:
        """Pin to the game client top-centre. Keep last good rect if capture flickers."""
        rect: QRect | None = None
        hwnd = getattr(target, "hwnd", None) if target is not None else None
        title = str(getattr(target, "window_title", "") or "")
        if "刷刷宝" in title or "ShuaBao" in title:
            return
        is_game = "英雄三国" in title or "yhzg" in title.lower()
        if hwnd:
            rect = _hwnd_client_rect(int(hwnd))
        if rect is None and isinstance(target, QRect):
            rect = QRect(target)
        elif rect is None and target is not None and hasattr(target, "geometry"):
            try:
                candidate = target.geometry()
                if isinstance(candidate, QRect):
                    rect = QRect(candidate)
            except Exception:
                rect = None
        elif rect is None and target is not None:
            try:
                width = int(getattr(target, "width"))
                height = int(getattr(target, "height"))
                left = int(getattr(target, "left", 0) or 0)
                top = int(getattr(target, "top", 0) or 0)
                if width >= 200 and height >= 200 and not (
                    left == 0 and top == 0 and not is_game
                ):
                    rect = QRect(left, top, width, height)
            except (TypeError, ValueError):
                rect = None
        self._accept_rect(rect, is_game)
        self._move_pinned()

OverlayHUD = OverlayHud
StatusOverlay = OverlayHud

__all__ = ["OverlayHud", "OverlayHUD", "StatusOverlay"]
