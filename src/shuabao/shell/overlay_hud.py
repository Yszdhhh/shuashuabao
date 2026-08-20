"""Lightweight, click-through runtime status HUD.

The HUD is deliberately independent from :class:`MainWindow`: it can be shown
while the control centre is covered by the game and never receives input.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from shuabao.shell.theme_styles import tokens


class OverlayHud(QWidget):
    """Top-centred, always-on-top status pill that lets mouse input pass through."""

    STOPPED_HIDE_MS = 3500

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

        self._theme = "light"
        self._palette = tokens("light")
        self.label = QLabel("刷刷宝: 空闲")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(self.STOPPED_HIDE_MS)
        self._hide_timer.timeout.connect(self.hide)
        self._status_state = "idle"
        self._target_rect: QRect | None = None
        self.apply_theme("light")

    def apply_theme(self, theme: str = "light") -> None:
        self._theme = theme
        self._palette = tokens(theme)
        self._paint_status()

    def _status_colors(self) -> dict[str, QColor]:
        t = self._palette
        return {
            "running": QColor(t["accent_hitch"]),
            "paused": QColor(t["accent_warning"]),
            "recovering": QColor(t["accent_warning"]),
            "error": QColor(t["accent_danger"]),
            "idle": QColor(t["text_secondary"]),
            "stopped": QColor(t["text_secondary"]),
        }

    def _paint_status(self) -> None:
        t = self._palette
        color = self._status_colors()[self._status_state].name()
        self.label.setStyleSheet(
            "QLabel { color: %s; background: %s; "
            "border: 1px solid %s; border-radius: 14px; padding: 5px 14px; "
            "font: 600 12px 'Microsoft YaHei UI'; }"
            % (color, t["bg_surface"], t["border_subtle"])
        )

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
        """Update the pill and (re)anchor it to the target/screen top centre."""
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
        self.anchor_to_target(self._target_rect)
        self.show()
        self.raise_()
        self._hide_timer.stop()
        if not running:
            self.setWindowOpacity(0.82)
            self._hide_timer.start()
        else:
            self.setWindowOpacity(0.96)

    # Compatibility aliases used by small integrations/tests.
    set_status = update_status

    def anchor_to_target(self, target: Any = None) -> None:
        """Anchor to a QRect, QWidget, or frame-like object; fallback to screen."""
        rect: QRect | None = None
        if isinstance(target, QRect):
            rect = QRect(target)
        elif target is not None and hasattr(target, "geometry"):
            try:
                candidate = target.geometry()
                if isinstance(candidate, QRect):
                    rect = QRect(candidate)
            except Exception:
                rect = None
        elif target is not None:
            try:
                width = int(getattr(target, "width"))
                height = int(getattr(target, "height"))
                left = int(getattr(target, "left", 0))
                top = int(getattr(target, "top", 0))
                rect = QRect(left, top, width, height)
            except (TypeError, ValueError):
                rect = None
        self._target_rect = rect
        screen = QGuiApplication.screenAt(rect.center()) if rect else QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = rect if rect and rect.isValid() else screen.availableGeometry()
        x = area.left() + max(0, (area.width() - self.width()) // 2)
        y = area.top() + 8
        self.move(QPoint(x, y))
OverlayHUD = OverlayHud
StatusOverlay = OverlayHud

__all__ = ["OverlayHud", "OverlayHUD", "StatusOverlay"]



