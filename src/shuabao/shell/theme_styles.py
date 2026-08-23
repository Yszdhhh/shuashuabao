"""ShuaBao 控制中心主题：深色工业风，单一金色强调。"""

from __future__ import annotations


class ThemeTokens:
    DARK = {
        "bg_app": "#12161C",
        "bg_canvas_gradient": "#12161C",
        "bg_surface": "#191F27",
        "bg_surface_hi": "#1E252E",
        "bg_surface_solid": "#191F27",
        "bg_card": "#1B222B",
        "bg_card_hover": "#232B35",
        "bg_subtle": "#222933",
        "bg_hover": "#2A333E",
        "bg_active": "#2A333E",
        "border_subtle": "#2C3540",
        "border_strong": "#3D4854",
        "border_glass": "#3D4854",
        "border_glass_top": "#46525F",
        "border_focus": "#E0AC4A",
        "border_glow": "#E0AC4A",
        "text_primary": "#E6EDF5",
        "text_secondary": "#9DAAB8",
        "text_muted": "#7A8794",
        "text_on_accent": "#171207",
        "accent_gold": "#DCA94E",
        "accent_gold_light": "#E7BC66",
        "accent_gold_dark": "#8F6A24",
        "accent_solo": "#DCA94E",
        "accent_solo_hover": "#E7BC66",
        "accent_hitch": "#9DAAB8",
        "accent_hitch_hover": "#C6D0DA",
        "neon_success": "#4CC38A",
        "neon_success_bg": "rgba(76, 195, 138, 0.12)",
        "neon_warning": "#D29922",
        "neon_warning_bg": "rgba(210, 153, 34, 0.12)",
        "neon_danger": "#F26D65",
        "neon_danger_bg": "rgba(242, 109, 101, 0.12)",
        "accent_warning": "#D29922",
        "accent_danger": "#F26D65",
        "accent_danger_hover": "#FF857D",
    }
    LIGHT = {
        "bg_app": "#FBF3E2",
        "bg_canvas_gradient": "#FBF3E2",
        "bg_surface": "#FFF8EA",
        "bg_surface_hi": "#FFFDF6",
        "bg_surface_solid": "#FFFDF6",
        "bg_card": "#FFFDF6",
        "bg_card_hover": "#F7EBD3",
        "bg_subtle": "#F4E8CE",
        "bg_hover": "#EDDDBB",
        "bg_active": "#EDDDBB",
        "border_subtle": "#E6D6B0",
        "border_strong": "#CBB284",
        "border_glass": "#D9C69C",
        "border_glass_top": "#F2E7CB",
        "border_focus": "#9A6B15",
        "border_glow": "#C99536",
        "text_primary": "#4A331A",
        "text_secondary": "#7C6438",
        "text_muted": "#A68F66",
        "text_on_accent": "#171207",
        "accent_gold": "#C99536",
        "accent_gold_light": "#D9A84F",
        "accent_gold_dark": "#8F6A24",
        "accent_solo": "#C99536",
        "accent_solo_hover": "#D9A84F",
        "accent_hitch": "#7C6438",
        "accent_hitch_hover": "#5C4726",
        "neon_success": "#1A7F37",
        "neon_success_bg": "rgba(26, 127, 55, 0.10)",
        "neon_warning": "#9E6A03",
        "neon_warning_bg": "rgba(158, 106, 3, 0.10)",
        "neon_danger": "#CF222E",
        "neon_danger_bg": "rgba(207, 34, 46, 0.10)",
        "accent_warning": "#9E6A03",
        "accent_danger": "#CF222E",
        "accent_danger_hover": "#E13B36",
    }


def tokens(theme: str = "dark") -> dict[str, str]:
    return ThemeTokens.LIGHT if str(theme).lower() == "light" else ThemeTokens.DARK

def _resolve_font_family() -> str:
    """探测候选字体，取第一个存在者 + CJK 回退；模块级缓存一次。"""
    global _FONT_STACK_CACHE
    if _FONT_STACK_CACHE is None:
        stack = '"Segoe UI", "PingFang SC", "Microsoft YaHei UI", sans-serif'
        try:
            from PySide6.QtGui import QFontDatabase
            from PySide6.QtWidgets import QApplication

            # 无 QApplication 时 QFontDatabase 探测会原生崩溃，直接走回退栈。
            if QApplication.instance() is not None:
                installed = set(QFontDatabase.families())
                for cand in ("Inter", "MiSans", "HarmonyOS Sans SC", "Segoe UI Variable", "Segoe UI"):
                    if cand in installed:
                        cjk = ', "Microsoft YaHei UI"' if "Microsoft YaHei UI" in installed else ""
                        stack = f'"{cand}"{cjk}, sans-serif'
                        break
        except Exception:
            pass
        _FONT_STACK_CACHE = stack
    return _FONT_STACK_CACHE


_FONT_STACK_CACHE: str | None = None


def apply_app_palette(theme: str = "dark") -> None:
    """强制 Qt 调色板对齐设计系统 Token，防止系统浅色模式反色。"""
    try:
        from PySide6.QtGui import QColor, QPalette
        from PySide6.QtWidgets import QApplication
    except Exception:
        return
    app = QApplication.instance()
    if app is None:
        return
    t = tokens(theme)
    bg = QColor(t["bg_app"])
    fg = QColor(t["text_primary"])
    surface = QColor(t["bg_surface_solid"])
    subtle = QColor(t["bg_subtle"])
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, bg)
    pal.setColor(QPalette.ColorRole.WindowText, fg)
    pal.setColor(QPalette.ColorRole.Base, surface)
    pal.setColor(QPalette.ColorRole.AlternateBase, subtle)
    pal.setColor(QPalette.ColorRole.Text, fg)
    pal.setColor(QPalette.ColorRole.Button, subtle)
    pal.setColor(QPalette.ColorRole.ButtonText, fg)
    pal.setColor(QPalette.ColorRole.ToolTipBase, surface)
    pal.setColor(QPalette.ColorRole.ToolTipText, fg)
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(t["text_secondary"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(t["border_focus"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(t["text_on_accent"]))
    app.setPalette(pal)

def get_qss(theme: str = "dark") -> str:
    t = tokens(theme)
    card_bg = (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        f" stop:0 {t['bg_surface_hi']}, stop:1 {t['bg_surface']})"
    )
    band_bg = (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        f" stop:0 {t['bg_surface_hi']}, stop:1 {t['bg_surface']})"
    )
    return f"""
    QMainWindow, QDialog {{
        background-color: {t["bg_app"]};
        color: {t["text_primary"]};
    }}
    QWidget {{
        font-family: {_resolve_font_family()};
        font-size: 14px;
        color: {t["text_primary"]};
        outline: none;
    }}
    QToolTip {{
        background-color: {t["bg_surface_hi"]};
        color: {t["text_primary"]};
        border: 1px solid {t["border_strong"]};
        border-radius: 4px;
        padding: 5px 8px;
        font-size: 13px;
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollArea > QWidget > QWidget {{
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: {t["border_strong"]};
        min-height: 24px;
        border-radius: 4px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QFrame#customTitleBar {{
        background: transparent;
        border: none;
    }}
    QGroupBox {{
        font-weight: 700;
        font-size: 15px;
        background: {card_bg};
        border: 1px solid {t["border_subtle"]};
        border-radius: 10px;
        margin-top: 0px;
        padding: 42px 16px 14px 16px;
    }}
    QGroupBox::title {{
        subcontrol-origin: padding;
        subcontrol-position: top left;
        left: 16px;
        top: 12px;
        padding: 0;
        color: {t["text_primary"]};
        font-size: 15px;
        font-weight: 700;
    }}
    QSpinBox {{
        min-height: 32px;
        min-width: 62px;
        padding-right: 26px;
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        subcontrol-origin: border;
        width: 20px;
        border: 1px solid {t["border_subtle"]};
        background: {t["bg_subtle"]};
    }}
    QSpinBox::up-button {{
        subcontrol-position: top right;
        border-radius: 0px 8px 0px 0px;
    }}
    QSpinBox::down-button {{
        subcontrol-position: bottom right;
        border-radius: 0px 0px 8px 0px;
    }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
        background: {t["bg_hover"]};
        border-color: {t["border_strong"]};
    }}
    QSpinBox::up-arrow {{
        width: 0;
        height: 0;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-bottom: 5px solid {t["text_secondary"]};
    }}
    QSpinBox::down-arrow {{
        width: 0;
        height: 0;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {t["text_secondary"]};
    }}
    QLineEdit, QComboBox, QSpinBox, QAbstractSpinBox, QPlainTextEdit {{
        background-color: {t["bg_app"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 8px;
        padding: 5px 12px;
        color: {t["text_primary"]};
        min-height: 30px;
        font-size: 14px;
        selection-background-color: {t["accent_gold"]};
        selection-color: {t["text_on_accent"]};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{
        border: 1px solid {t["border_focus"]};
    }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
        color: {t["text_muted"]};
        border-color: {t["border_subtle"]};
    }}
    QComboBox::drop-down {{
        width: 24px;
        border: none;
    }}
    QComboBox QAbstractItemView {{
        background-color: {t["bg_surface_hi"]};
        border: 1px solid {t["border_strong"]};
        border-radius: 6px;
        color: {t["text_primary"]};
        selection-background-color: {t["accent_gold"]};
        selection-color: {t["text_on_accent"]};
        padding: 4px;
    }}
    QCheckBox, QRadioButton {{
        spacing: 8px;
        color: {t["text_primary"]};
        font-size: 14px;
    }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 4px;
        border: 1px solid {t["border_strong"]};
        background-color: {t["bg_app"]};
    }}
    QRadioButton::indicator {{
        border-radius: 8px;
    }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background-color: {t["accent_gold"]};
        border-color: {t["accent_gold"]};
    }}
    QCheckBox::indicator:focus, QRadioButton::indicator:focus {{
        border: 1px solid {t["border_focus"]};
    }}
    QCheckBox:focus, QRadioButton:focus {{
        color: {t["text_primary"]};
    }}
    QLabel {{
        color: {t["text_primary"]};
        font-size: 14px;
    }}
    QLabel#brandTitle {{
        font-size: 20px;
        font-weight: 700;
        color: {t["text_primary"]};
    }}
    QLabel#brandSub {{
        color: {t["text_secondary"]};
        font-size: 13px;
    }}
    QLabel#sectionCap {{
        color: {t["text_secondary"]};
        font-size: 13px;
    }}
    QLabel#hintLabel {{
        color: {t["text_secondary"]};
        font-size: 13px;
    }}
    QLabel#warnHint {{
        color: {t["accent_warning"]};
        font-size: 13px;
    }}
    QLabel#statusPill {{
        background: {t["bg_subtle"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 9px;
        padding: 4px 12px;
        color: {t["text_secondary"]};
        font-weight: 600;
        font-size: 13px;
    }}
    QLabel#versionPill {{
        background: {t["bg_subtle"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 6px;
        padding: 2px 7px;
        color: {t["text_secondary"]};
        font-weight: 600;
        font-size: 12px;
    }}
    QLabel#gamesCap {{
        color: {t["text_muted"]};
        font-size: 13px;
    }}
    QPushButton {{
        background: {t["bg_subtle"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 8px;
        color: {t["text_primary"]};
        padding: 7px 16px;
        font-size: 14px;
        font-weight: 600;
        min-height: 30px;
    }}
    QPushButton:hover {{
        background: {t["bg_hover"]};
        border-color: {t["border_strong"]};
    }}
    QPushButton:pressed {{
        padding-top: 8px;
        padding-bottom: 6px;
    }}
    QPushButton:disabled {{
        color: {t["text_muted"]};
        background: {t["bg_app"]};
    }}
    QPushButton:focus {{
        border: 1px solid {t["border_focus"]};
    }}
    QPushButton#btnWinMin, QPushButton#btnWinClose {{
        background: transparent;
        border: none;
        border-radius: 6px;
        color: {t["text_secondary"]};
        font-size: 13px;
        font-weight: 400;
        padding: 0px;
    }}
    QPushButton#btnWinMin:hover {{
        background: {t["bg_hover"]};
        color: {t["text_primary"]};
    }}
    QPushButton#btnWinClose:hover {{
        background: {t["accent_danger"]};
        color: #FFFFFF;
    }}
    QPushButton#btnStart, QPushButton#btnPrimary {{
        background: {t["accent_gold"]};
        color: {t["text_on_accent"]};
        font-weight: 700;
        font-size: 14px;
        border: 1px solid {t["accent_gold"]};
        border-radius: 8px;
        padding: 8px 20px;
        min-height: 38px;
    }}
    QPushButton#btnStart:hover, QPushButton#btnPrimary:hover {{
        background: {t["accent_gold_light"]};
        border-color: {t["accent_gold_light"]};
        color: {t["text_on_accent"]};
    }}
    QPushButton#btnStart:pressed, QPushButton#btnPrimary:pressed {{
        padding-top: 9px;
        padding-bottom: 7px;
    }}
    QPushButton#btnStart:disabled, QPushButton#btnPrimary:disabled {{
        background: {t["bg_subtle"]};
        border-color: {t["border_subtle"]};
        color: {t["text_muted"]};
    }}
    QPushButton#btnStop {{
        background: {t["accent_danger"]};
        color: #FFFFFF;
        font-weight: 700;
        font-size: 14px;
        border: 1px solid {t["accent_danger"]};
        border-radius: 8px;
        padding: 8px 20px;
        min-height: 38px;
    }}
    QPushButton#btnStop:hover {{
        background: {t["accent_danger_hover"]};
        border-color: {t["accent_danger_hover"]};
    }}
    QWidget#modeChooser {{
        background: transparent;
        border: none;
    }}
    QFrame#customTitleBar {{
        background: {band_bg};
        border-bottom: 1px solid {t["border_subtle"]};
    }}
    QFrame#headerSeparator {{
        background: {t["border_subtle"]};
        border: none;
        max-height: 1px;
    }}
    QFrame#repSummaryCard {{
        background: {t["bg_app"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 8px;
    }}
    QFrame#footerBar {{
        background: {band_bg};
        border-top: 1px solid {t["border_subtle"]};
    }}
    QLabel#statusPill[state="running"] {{
        background: {t["neon_success_bg"]};
        border: 1px solid {t["neon_success"]};
        color: {t["neon_success"]};
    }}
    QGroupBox#subGroup {{
        background: transparent;
        border: none;
        border-top: 1px solid {t["border_subtle"]};
        border-radius: 0px;
        margin-top: 10px;
        padding: 30px 2px 4px 2px;
        font-size: 13px;
        font-weight: 600;
    }}
    QGroupBox#subGroup::title {{
        subcontrol-origin: padding;
        subcontrol-position: top left;
        left: 2px;
        top: 8px;
        padding: 0;
        color: {t["text_secondary"]};
        font-size: 13px;
        font-weight: 600;
        background: transparent;
    }}
    QLabel#statusLine {{
        color: {t["text_secondary"]};
        font-size: 14px;
    }}
    """


def wizard_qss(theme: str = "dark") -> str:
    t = tokens(theme)
    card_bg = (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        f" stop:0 {t['bg_surface_hi']}, stop:1 {t['bg_surface']})"
    )
    return get_qss(theme) + f"""
    QDialog {{
        background-color: {t["bg_app"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 10px;
    }}
    QLabel#wizardTitle {{
        font-size: 17px;
        font-weight: 700;
        color: {t["text_primary"]};
    }}
    QLabel#wizardSub {{
        font-size: 14px;
        color: {t["text_secondary"]};
    }}
    QLabel#wizardStep {{
        font-size: 13px;
        font-weight: 600;
        color: {t["text_secondary"]};
        background: {t["bg_subtle"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 6px;
        padding: 3px 9px;
    }}
    QPushButton#goldBtn {{
        background: {t["accent_gold"]};
        border: 1px solid {t["accent_gold"]};
        border-radius: 8px;
        color: {t["text_on_accent"]};
        font-size: 14px;
        font-weight: 700;
        padding: 8px 20px;
        min-height: 38px;
        min-width: 100px;
    }}
    QPushButton#goldBtn:hover {{
        background: {t["accent_gold_light"]};
        border-color: {t["accent_gold_light"]};
    }}
    QPushButton#goldBtn:pressed {{
        padding-top: 9px;
        padding-bottom: 7px;
    }}
    QPushButton#secondaryBtn {{
        background: {t["bg_subtle"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 8px;
        color: {t["text_primary"]};
        padding: 8px 18px;
        min-height: 38px;
        font-size: 14px;
        font-weight: 600;
    }}
    QPushButton#choiceCard {{
        background: {card_bg};
        border: 1px solid {t["border_subtle"]};
        border-radius: 10px;
        color: {t["text_primary"]};
        font-size: 14px;
        font-weight: 600;
        padding: 16px 14px;
        text-align: center;
    }}
    QPushButton#choiceCard:hover {{
        border-color: {t["border_strong"]};
        background: {t["bg_card_hover"]};
    }}
    QPushButton#choiceCard:checked {{
        border: 1px solid {t["accent_gold"]};
        color: {t["text_primary"]};
        font-weight: 700;
    }}
    """


def skill_card_qss(theme: str = "dark") -> str:
    t = tokens(theme)
    return (
        f"QPushButton {{"
        f"  background: {t['bg_card']};"
        f"  border: 1px solid {t['border_subtle']};"
        f"  border-radius: 8px;"
        f"  color: {t['text_primary']};"
        f"  font-size: 13px;"
        f"  font-weight: 600;"
        f"  padding: 6px 4px;"
        f"  text-align: center;"
        f"}}"
        f"QPushButton:hover {{"
        f"  border-color: {t['border_strong']};"
        f"  background: {t['bg_card_hover']};"
        f"}}"
        f"QPushButton:checked {{"
        f"  background: {t['bg_subtle']};"
        f"  border: 1px solid {t['accent_gold']};"
        f"  font-weight: 700;"
        f"}}"
    )


def mode_button_qss(theme: str = "dark") -> str:
    t = tokens(theme)
    card_bg = (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        f" stop:0 {t['bg_surface_hi']}, stop:1 {t['bg_surface']})"
    )
    return f"""
        QPushButton {{
            background: {card_bg};
            color: {t["text_primary"]};
            border: 1px solid {t["border_subtle"]};
            border-radius: 10px;
            font-size: 14px;
            font-weight: 600;
            padding: 16px 12px;
            min-width: 220px;
            max-width: 220px;
            min-height: 128px;
            max-height: 128px;
        }}
        QPushButton:hover {{
            border-color: {t["border_strong"]};
            background: {t["bg_card_hover"]};
        }}
        QPushButton:checked {{
            border: 1px solid {t["accent_gold"]};
            font-weight: 700;
        }}
    """


def official_build_qss(theme: str = "dark") -> str:
    t = tokens(theme)
    card_bg = (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        f" stop:0 {t['bg_surface_hi']}, stop:1 {t['bg_surface']})"
    )
    return f"""
        QPushButton {{
            font-size: 14px;
            font-weight: 600;
            padding: 10px 14px;
            border-radius: 10px;
            text-align: left;
            background: {card_bg};
            color: {t["text_primary"]};
            border: 1px solid {t["border_subtle"]};
            min-height: 64px;
        }}
        QPushButton:hover {{
            border-color: {t["border_strong"]};
        }}
        QPushButton:checked {{
            border: 1px solid {t["accent_gold"]};
        }}
        QPushButton QLabel {{
            background: transparent;
        }}
        QPushButton QLabel#buildTitle {{
            font-size: 14px;
            font-weight: 600;
            color: {t["text_primary"]};
        }}
        QPushButton QLabel#buildSkillName {{
            font-size: 13px;
            color: {t["text_secondary"]};
        }}
        QPushButton QLabel#buildRoute {{
            font-size: 11px;
            color: {t["text_muted"]};
        }}
        QPushButton QLabel#buildSlot {{
            border: 1px dashed {t["border_strong"]};
            border-radius: 4px;
            background: transparent;
        }}
        QPushButton QPushButton#buildDelete {{
            background: transparent;
            border: none;
            color: {t["text_muted"]};
            font-size: 12px;
            font-weight: 600;
            padding: 2px 8px;
            min-height: 0px;
        }}
        QPushButton QPushButton#buildDelete:hover {{
            color: {t["accent_danger"]};
        }}
    """
