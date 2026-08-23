"""Runtime HUD pinned to the game client: status + clickable stop.

Not click-through — the stop button must receive mouse events.
"""

from __future__ import annotations

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
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from shuabao.shell.theme_styles import tokens


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
    """Top-centred always-on-top bar with a stop button. Does not steal game focus."""

    stop_requested = Signal()
    STOPPED_HIDE_MS = 3500

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
        self.setObjectName("shuaBaoOverlayHud")
        self.setFixedHeight(36)
        self.setMinimumWidth(280)
        self.setWindowOpacity(0.96)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 8, 4)
        layout.setSpacing(8)

        self.logo_lbl = QLabel()
        self.logo_lbl.setFixedSize(20, 20)
        logo_path = Path(__file__).resolve().parents[3] / "assets" / "branding" / "app_logo.png"
        if logo_path.exists():
            pix = QPixmap(str(logo_path)).scaled(
                20, 20,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.logo_lbl.setPixmap(pix)
            self.setWindowIcon(QIcon(str(logo_path)))
        layout.addWidget(self.logo_lbl, 0)

        self.label = QLabel("刷刷宝: 空闲")
        self.label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self.label.setObjectName("hudStatus")

        self.btn_stop = QPushButton("停止")
        self.btn_stop.setObjectName("hudStop")
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.setToolTip("立即结束脚本（F12 或 Shift+F12）")
        self.btn_stop.setFixedHeight(22)
        self.btn_stop.setMinimumWidth(52)
        self.btn_stop.clicked.connect(self._emit_stop)
        self.btn_stop.hide()

        layout.addWidget(self.label, 1)
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
        self._theme = "light"
        self._palette = tokens("light")
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
        if state in ("paused", "recovering"):
            return QColor(t["neon_warning"])
        return QColor(t["accent_gold"])

    def apply_theme(self, theme: str = "light") -> None:
        t = tokens(theme)
        self._theme = theme
        self._palette = t
        # 强制使用纯黑高透底 + 荧光高对比文本，确保在任何游戏背景下清晰可见
        self.label.setStyleSheet(
            "QLabel#hudStatus { "
            "color: #FFFFFF; background: transparent; border: none; "
            "padding: 0 4px; font: 700 13px 'Microsoft YaHei UI', sans-serif; }"
        )
        self.btn_stop.setStyleSheet(
            "QPushButton#hudStop { "
            "background: #E54D2E; color: #FFFFFF; border: none; border-radius: 4px; "
            "padding: 2px 10px; font: 700 12px 'Microsoft YaHei UI', sans-serif; }"
            "QPushButton#hudStop:hover { background: #FF6E67; }"
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
        bg = QColor(15, 18, 24, 245)
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
        self.apply_theme("light")

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
    ) -> None:
        phase_text = str(phase or "").strip()
        ocr_text = str(ocr_status or "").strip()
        count = max(0, int(game_count or 0))
        cycle = max(0, int(cycle_num or 0))
        reason = str(terminal_reason or "").strip()
        if running:
            details = ["刷刷宝: 运行中"]
            if ocr_text:
                details.append(ocr_text)
            if cycle:
                details.append(f"局数 {count}/{cycle}")
            else:
                details.append(f"局数 {count}")
            if phase_text:
                details.append(phase_text)
            text = " | ".join(details)
            self.btn_stop.show()
        else:
            text = "刷刷宝: 已停止"
            if reason:
                text += f" (原因: {reason})"
            if count:
                text += f" | 局数 {count}"
            if last_action:
                self.setToolTip(f"最后动作：{last_action}")
            self.btn_stop.hide()

        self.label.setText(text)
        self._status_state = self._state_for(running, phase_text, reason)
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
        # 已经吸附过游戏窗口后直接永久锁定，不再随帧浮动
        if self._has_game_window:
            return
        if is_game:
            self._has_game_window = True
            self._pinned_rect = QRect(rect)
        elif self._pinned_rect is None:
            self._pinned_rect = QRect(rect)
        area = self._pinned_rect
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
        else:
            y = area.top() + 4
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
        else:
            y = area.top() + 4
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
