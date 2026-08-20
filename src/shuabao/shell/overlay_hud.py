"""Lightweight, click-through runtime status HUD.

Pinned to the top centre of the game client. Never a light-on-light pill.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


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
    """Top-centred, always-on-top status pill that lets mouse input pass through."""

    STOPPED_HIDE_MS = 3500
    _HUD_QSS = (
        "QLabel { color: #FFFFFF; background: rgba(32, 24, 18, 240); "
        "border: 1px solid #D8A94A; border-radius: 14px; "
        "padding: 6px 16px; font: 700 13px 'Microsoft YaHei UI'; }"
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setObjectName("shuaBaoOverlayHud")
        self.setMinimumHeight(30)
        self.setMinimumWidth(220)
        self.setWindowOpacity(0.96)

        self.label = QLabel("刷刷宝: 空闲")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet(self._HUD_QSS)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(self.STOPPED_HIDE_MS)
        self._hide_timer.timeout.connect(self.hide)
        self._status_state = "idle"
        self._pinned_rect: QRect | None = None

    def apply_theme(self, theme: str = "light") -> None:
        self.label.setStyleSheet(self._HUD_QSS)

    def _paint_status(self) -> None:
        self.label.setStyleSheet(self._HUD_QSS)

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
        else:
            text = "刷刷宝: 已停止"
            if reason:
                text += f" (原因: {reason})"
            if count:
                text += f" | 局数 {count}"
            if last_action:
                self.setToolTip(f"最后动作：{last_action}")

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

    def _accept_rect(self, rect: QRect | None) -> None:
        if rect is None or not rect.isValid() or rect.width() < 200 or rect.height() < 200:
            return
        if rect.top() < -100:
            return
        self._pinned_rect = QRect(rect)

    def _move_pinned(self) -> None:
        area = self._pinned_rect
        screen = QGuiApplication.primaryScreen()
        if area is None or not area.isValid():
            if screen is None:
                return
            area = screen.availableGeometry()
        x = area.left() + max(0, (area.width() - self.width()) // 2)
        y = area.top() + 8
        self.move(QPoint(x, y))

    def anchor_to_target(self, target: Any = None) -> None:
        """Pin to the game client top-centre. Keep last good rect if capture flickers."""
        rect: QRect | None = None
        hwnd = getattr(target, "hwnd", None) if target is not None else None
        title = str(getattr(target, "window_title", "") or "")
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
                    left == 0 and top == 0 and "英雄三国" not in title
                ):
                    rect = QRect(left, top, width, height)
            except (TypeError, ValueError):
                rect = None
        if "刷刷宝" in title or "ShuaBao" in title:
            rect = None
        self._accept_rect(rect)
        self._move_pinned()


OverlayHUD = OverlayHud
StatusOverlay = OverlayHud

__all__ = ["OverlayHud", "OverlayHUD", "StatusOverlay"]
