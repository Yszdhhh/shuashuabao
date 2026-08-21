"""Runtime HUD pinned to the game client: status + clickable stop.

Not click-through — the stop button must receive mouse events.
"""

from __future__ import annotations

from typing import Any

from pathlib import Path
from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QIcon, QKeySequence, QPixmap, QShortcut
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
        self.setMinimumHeight(36)
        self.setMinimumWidth(320)
        self.setWindowOpacity(0.96)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        self.logo_lbl = QLabel()
        logo_path = Path(__file__).resolve().parents[3] / "assets" / "branding" / "app_logo.png"
        if logo_path.exists():
            pix = QPixmap(str(logo_path)).scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
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
        self.btn_stop.setFixedHeight(28)
        self.btn_stop.setMinimumWidth(64)
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
        self.apply_theme("light")
    def _emit_stop(self) -> None:
        self.stop_requested.emit()

    def apply_theme(self, theme: str = "light") -> None:
        t = tokens(theme)
        self.label.setStyleSheet(
            "QLabel#hudStatus { "
            f"color: {t['text_primary']}; background: {t['bg_surface']}; "
            f"border: 1px solid {t['border_focus']}; border-right: none; "
            "border-top-left-radius: 8px; border-bottom-left-radius: 8px; "
            "padding: 6px 14px; font: 700 13px 'Microsoft YaHei UI'; }"
        )
        self.btn_stop.setStyleSheet(
            "QPushButton#hudStop { "
            f"color: {t['text_primary']}; background: {t['accent_danger']}; "
            f"border: 1px solid {t['border_focus']}; border-left: none; "
            "border-top-right-radius: 8px; border-bottom-right-radius: 8px; "
            "padding: 6px 16px; font: 700 13px 'Microsoft YaHei UI'; }"
            "QPushButton#hudStop:hover { background: #E23D3D; }"
            "QPushButton#hudStop:pressed { padding-top: 7px; padding-bottom: 5px; }"
        )
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

    set_status = update_status

    def _accept_rect(self, rect: QRect | None, is_game: bool) -> None:
        if rect is None or not rect.isValid() or rect.width() < 200 or rect.height() < 200:
            return
        if rect.top() < -100:
            return
        # 如果当前已经锁定了游戏窗口，不再被非游戏的临时框切走
        if self._has_game_window and not is_game:
            return
        if is_game:
            self._has_game_window = True
        self._pinned_rect = QRect(rect)

    def _move_pinned(self) -> None:
        if self._user_moved:
            return  # 用户手动拖拽过位置后，不再自动吸附移动
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
