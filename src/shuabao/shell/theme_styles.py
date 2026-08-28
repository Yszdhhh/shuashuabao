"""ShuaBao 控制中心主题：深色工业风，单一金色强调。"""

from __future__ import annotations


class ThemeTokens:
    DARK = {
        "bg_app": "#23272f",
        "bg_canvas_gradient": "#23272f",
        "bg_surface": "#2b303a",
        "bg_surface_hi": "#333947",
        "bg_surface_solid": "#2b303a",
        "bg_card": "#2b303a",
        "bg_card_hover": "#363c48",
        "bg_subtle": "#262b34",
        "bg_hover": "#363c48",
        "bg_active": "#363c48",
        "bg_launch": "#383426",
        "chrome_bg": "#20252d",
        "chrome_bg_hi": "#2b313c",
        "chrome_border": "#454c59",
        "chrome_text": "#eceef2",
        "chrome_muted": "#bcc3cd",
        "border_subtle": "#454c59",
        "border_strong": "#586173",
        "border_glass": "#454c59",
        "border_glass_top": "#525a69",
        "border_focus": "#828fff",
        "border_glow": "#dfae4e",
        "text_primary": "#eceef2",
        "text_secondary": "#bcc3cd",
        "text_muted": "#98a1af",
        "text_on_accent": "#221a04",
        "accent_gold": "#dfae4e",
        "accent_gold_light": "#efc06a",
        "accent_gold_dark": "#a97f33",
        "accent_solo": "#dfae4e",
        "accent_solo_hover": "#efc06a",
        "accent_hitch": "#5e6ad2",
        "accent_hitch_hover": "#828fff",
        "neon_success": "#3ba55c",
        "neon_success_bg": "rgba(59, 165, 92, 0.14)",
        "neon_warning": "#eab308",
        "neon_warning_bg": "rgba(234, 179, 8, 0.14)",
        "neon_danger": "#e0565c",
        "neon_danger_bg": "rgba(224, 86, 92, 0.14)",
        "accent_warning": "#eab308",
        "accent_danger": "#e0565c",
        "accent_danger_hover": "#ea7378",
    }
    LIGHT = {
        "bg_app": "#eef0f4",
        "bg_canvas_gradient": "#eef0f4",
        "bg_surface": "#fcfdff",
        "bg_surface_hi": "#ffffff",
        "bg_surface_solid": "#fcfdff",
        "bg_card": "#fcfdff",
        "bg_card_hover": "#eceef3",
        "bg_subtle": "#eceef3",
        "bg_hover": "#e4e7ed",
        "bg_active": "#e4e7ed",
        "bg_launch": "#fbf7ec",
        "chrome_bg": "#20252d",
        "chrome_bg_hi": "#2b313c",
        "chrome_border": "#454c59",
        "chrome_text": "#f2f4f7",
        "chrome_muted": "#c2c9d3",
        "border_subtle": "#dde1e8",
        "border_strong": "#c3c9d4",
        "border_glass": "#d6dae2",
        "border_glass_top": "#eaedf2",
        "border_focus": "#4753ce",
        "border_glow": "#c9963f",
        "text_primary": "#2b3442",
        "text_secondary": "#5c6a80",
        "text_muted": "#8a93a3",
        "text_on_accent": "#3a2c08",
        "accent_gold": "#c9963f",
        "accent_gold_light": "#dbad57",
        "accent_gold_dark": "#8f6a24",
        "accent_solo": "#c9963f",
        "accent_solo_hover": "#dbad57",
        "accent_hitch": "#4753ce",
        "accent_hitch_hover": "#7b87e8",
        "neon_success": "#2f7d43",
        "neon_success_bg": "rgba(47, 125, 67, 0.10)",
        "neon_warning": "#9e6a03",
        "neon_warning_bg": "rgba(158, 106, 3, 0.10)",
        "neon_danger": "#cc3d44",
        "neon_danger_bg": "rgba(204, 61, 68, 0.10)",
        "accent_warning": "#9e6a03",
        "accent_danger": "#cc3d44",
        "accent_danger_hover": "#e05a60",
    }


def tokens(theme: str = "dark") -> dict[str, str]:
    return ThemeTokens.LIGHT if str(theme).lower() == "light" else ThemeTokens.DARK

def _resolve_font_family() -> str:
    """探测候选字体，取第一个存在者 + CJK 回退；模块级缓存一次。"""
    global _FONT_STACK_CACHE
    if _FONT_STACK_CACHE is None:
        stack = '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif'
        try:
            from PySide6.QtGui import QFontDatabase
            from PySide6.QtWidgets import QApplication

            # 无 QApplication 时 QFontDatabase 探测会原生崩溃，直接走回退栈。
            if QApplication.instance() is not None:
                installed = set(QFontDatabase.families())
                for cand in (
                    "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
                    "HarmonyOS Sans SC", "MiSans", "Segoe UI Variable", "Segoe UI",
                ):
                    if cand in installed:
                        ui = ', "Segoe UI"' if cand != "Segoe UI" and "Segoe UI" in installed else ""
                        stack = f'"{cand}"{ui}, sans-serif'
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
        f" stop:0 {t['chrome_bg_hi']}, stop:1 {t['chrome_bg']})"
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
        font-size: 14px;
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
        background: {t["bg_surface_hi"]};
        border-bottom: 1px solid {t["border_subtle"]};
    }}
    QFrame#customTitleBar QLabel, QFrame#footerBar QLabel {{
        color: {t["text_primary"]};
    }}
    QFrame#customTitleBar QLabel#versionPill,
    QFrame#customTitleBar QLabel#statusPill {{
        background: transparent;
        border-color: transparent;
        color: {t["text_secondary"]};
        padding: 0px;
    }}
    QFrame#customTitleBar QPushButton,
    QFrame#footerBar QPushButton {{
        background: {t["bg_surface_hi"]};
        border-color: {t["border_subtle"]};
        color: {t["text_primary"]};
    }}
    QFrame#customTitleBar QPushButton {{
        min-height: 28px;
        padding: 0px 8px;
        border: none;
        background: transparent;
        font-size: 12px;
    }}
    QFrame#customTitleBar QPushButton:hover,
    QFrame#footerBar QPushButton:hover {{
        background: {t["bg_hover"]};
        color: {t["text_primary"]};
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
        background: {t["bg_surface_hi"]};
        border-top: 1px solid {t["border_subtle"]};
        min-height: 48px;
    }}
    QWidget#prototype12Dashboard {{
        background: transparent;
        border: none;
    }}
    QWidget#prototype12Rail {{
        min-width: 204px;
        max-width: 204px;
        background: {t["bg_surface_hi"]};
        border-right: 1px solid {t["border_subtle"]};
    }}
    QWidget#prototype12Workspace {{
        background: transparent;
        border: none;
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
    QFrame#prototype12LaunchCheck {{
        background: {t["bg_launch"]};
        border: 1px solid {t["accent_gold_dark"]};
        border-radius: 6px;
        min-width: 196px;
        max-width: 196px;
    }}
    QLabel#launchCheckTitle {{
        font-size: 13px;
        font-weight: 700;
        color: {t["text_primary"]};
        padding-bottom: 5px;
    }}
    QLabel#launchCheckReady {{
        color: {t["neon_success"]};
        font-size: 11px;
        font-weight: 700;
        padding-bottom: 3px;
    }}
    QFrame#launchCheckSection {{
        background: transparent;
        border: none;
        border-top: 1px solid {t["border_subtle"]};
    }}
    QLabel#launchCheckCaption, QLabel#bondCaption {{
        color: {t["text_secondary"]};
        font-size: 11px;
        font-weight: 600;
    }}
    QLabel#launchCheckValue {{
        color: {t["text_primary"]};
        font-size: 12px;
        font-weight: 600;
    }}
    QLabel#launchSkillRank {{
        background: {t["accent_gold"]};
        color: {t["text_on_accent"]};
        border-radius: 9px;
        font-size: 10px;
        font-weight: 800;
    }}
    QLabel#launchSkillIcon {{
        border-radius: 4px;
    }}
    QGroupBox#od12FlatSection {{
        background: transparent;
        border: none;
        border-top: 1px solid {t["border_subtle"]};
        border-radius: 0px;
        margin-top: 0px;
        padding: 31px 8px 5px 8px;
        font-size: 13px;
        font-weight: 650;
    }}
    QGroupBox#od12FlatSection::title {{
        subcontrol-origin: padding;
        subcontrol-position: top left;
        left: 8px;
        top: 9px;
        padding: 0px;
        color: {t["text_primary"]};
        font-size: 13px;
        font-weight: 650;
        background: transparent;
    }}
    QFrame#reputationCard {{
        background: {t["bg_surface_hi"]};
        border: 1px solid {t["accent_gold"]};
        border-radius: 5px;
    }}
    QLabel#reputationArt {{
        background: {t["bg_subtle"]};
        border-radius: 4px;
    }}
    QLabel#reputationCardTitle {{
        color: {t["text_primary"]};
        font-size: 11px;
        font-weight: 700;
    }}
    QPushButton#reputationAdjust {{
        min-height: 24px;
        padding: 1px 7px;
        font-size: 11px;
    }}
    QCheckBox#bondChip {{
        spacing: 0px;
        background: {t["bg_surface_hi"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 5px;
        padding: 5px 8px;
        color: {t["text_primary"]};
        font-size: 12px;
        font-weight: 600;
    }}
    QCheckBox#bondChip::indicator {{
        width: 0px;
        height: 0px;
        border: none;
        background: transparent;
    }}
    QCheckBox#bondChip:checked {{
        border-color: {t["accent_gold"]};
        background: {t["bg_surface_hi"]};
    }}
    QPushButton#buildAddCustom {{
        background: transparent;
        border: 1px dashed {t["border_strong"]};
        border-radius: 5px;
        min-height: 32px;
        max-height: 34px;
        padding: 0px 8px;
        color: {t["text_secondary"]};
        font-size: 12px;
    }}
    QCheckBox#od12Switch {{
        min-height: 32px;
        spacing: 10px;
        font-size: 13px;
        font-weight: 650;
    }}
    QCheckBox#od12Switch::indicator {{
        width: 30px;
        height: 18px;
        border-radius: 9px;
        border: 1px solid {t["border_strong"]};
        background: {t["bg_subtle"]};
    }}
    QCheckBox#od12Switch::indicator:checked {{
        border-color: {t["accent_gold"]};
        background: {t["accent_gold"]};
    }}
    QLabel#teamPageTitle {{
        font-size: 20px;
        font-weight: 700;
    }}
    QLabel#teamPageIntro {{
        color: {t["text_secondary"]};
        font-size: 14px;
    }}
    QLabel#teamStatusPill, QLabel#teamRulesState {{
        background: {t["bg_subtle"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 9px;
        padding: 3px 9px;
        color: {t["text_secondary"]};
        font-size: 11px;
        font-weight: 700;
    }}
    QFrame#teamRulesPanel {{
        background: {t["bg_surface_hi"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 8px;
    }}
    QLabel#teamRulesTitle {{
        font-size: 15px;
        font-weight: 700;
    }}
    QLabel#teamSafetyHint {{
        color: {t["text_secondary"]};
        font-size: 11px;
        padding-top: 2px;
    }}
    QFrame#teamRoute {{
        background: transparent;
        border: 1px solid {t["border_subtle"]};
        border-radius: 6px;
    }}
    QLabel#teamRouteStep {{
        min-height: 54px;
        padding: 8px 12px;
        border-right: 1px solid {t["border_subtle"]};
        color: {t["text_secondary"]};
        font-size: 12px;
        font-weight: 650;
    }}
    QFrame#teamPairPanel {{
        background: {t["bg_app"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 6px;
    }}
    QLabel#teamPairTitle {{
        font-size: 13px;
        font-weight: 700;
    }}
    QPushButton#teamSecondaryAction {{
        min-height: 34px;
        padding: 4px 12px;
    }}
    QPushButton#challengePickRow, QPushButton#inlinePickRow {{
        min-height: 38px;
        max-height: 40px;
        padding: 0px 10px;
        text-align: left;
        background: {t["bg_surface_hi"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 6px;
        font-size: 12px;
        font-weight: 650;
    }}
    QPushButton#challengePickRow:hover, QPushButton#inlinePickRow:hover {{
        background: {t["bg_hover"]};
        border-color: {t["accent_gold"]};
    }}
    QFrame#inlineOverlay {{
        background: {t["bg_surface_hi"]};
        border: 1px solid {t["border_strong"]};
        border-radius: 8px;
    }}
    QLabel#inlineOverlayTitle {{
        font-size: 14px;
        font-weight: 700;
    }}
    QPushButton#inlineOverlayClose {{
        min-height: 26px;
        max-height: 28px;
        padding: 0px 8px;
        font-size: 12px;
    }}
    QPushButton#inlineOverlayChoice {{
        min-height: 30px;
        text-align: left;
        padding: 4px 8px;
        border: 1px solid {t["border_subtle"]};
        border-radius: 6px;
        background: {t["bg_surface"]};
        font-size: 12px;
        font-weight: 600;
    }}
    QPushButton#inlineOverlayChoice:hover {{
        background: {t["bg_hover"]};
        border-color: {t["accent_gold"]};
    }}
    QPushButton#inlineOverlayChoice:checked {{
        background: {t["bg_launch"]};
        border-color: {t["accent_gold"]};
    }}
    QPushButton#inlineOverlayChoice:disabled {{
        color: {t["text_muted"]};
        background: {t["bg_subtle"]};
    }}
    QFrame#skillRankCard {{
        background: transparent;
        border: none;
        border-bottom: 1px solid {t["border_subtle"]};
    }}
    QLabel#skillRankCaption {{
        font-size: 12px;
        font-weight: 650;
    }}
    QLabel#skillRankNo {{
        background: {t["bg_subtle"]};
        border-radius: 4px;
        font-size: 11px;
        font-weight: 800;
    }}
    QLabel#skillRankName {{
        font-size: 12px;
        font-weight: 650;
    }}
    QPushButton#skillRouteBtn {{
        min-height: 28px;
        max-height: 28px;
        padding: 0px 8px;
        font-size: 11px;
    }}
    QPushButton#skillRouteOption {{
        min-height: 26px;
        text-align: left;
        padding: 0px 8px;
        font-size: 11px;
    }}
    QPushButton#skillRankMove, QPushButton#skillRankRemove {{
        min-height: 20px;
        max-height: 20px;
        padding: 0px;
        font-size: 10px;
        border: 1px solid {t["border_subtle"]};
        background: {t["bg_subtle"]};
    }}
    QPushButton#skillRankMove:hover, QPushButton#skillRankRemove:hover {{
        background: {t["bg_launch"]};
        border-color: {t["accent_gold"]};
    }}
    QPushButton#skillRankMove:disabled {{
        color: {t["text_muted"]};
    }}
    QGroupBox#prototype12AdvancedDrawer {{
        background: {t["bg_surface"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 10px;
        font-weight: 600;
        padding-top: 8px;
    }}
    QGroupBox#prototype12AdvancedDrawer::indicator {{
        width: 14px;
        height: 14px;
    }}
    QPushButton#btnMoreSettings {{
        background: {t["chrome_bg_hi"]};
        border: 1px solid {t["accent_hitch"]};
        border-radius: 9px;
        color: {t["chrome_text"]};
        padding: 6px 14px;
        font-weight: 600;
    }}
    QPushButton#btnMoreSettings:hover {{
        background: {t["accent_hitch"]};
        color: #ffffff;
    }}
    QFrame#footerBar QPushButton#btnStart {{
        background: {t["accent_gold"]};
        border-color: {t["accent_gold"]};
        color: {t["text_on_accent"]};
    }}
    QFrame#footerBar QPushButton#btnStart:hover {{
        background: {t["accent_gold_light"]};
        border-color: {t["accent_gold_light"]};
        color: {t["text_on_accent"]};
    }}
    QFrame#footerBar QPushButton#btnStop {{
        background: {t["accent_danger"]};
        border-color: {t["accent_danger"]};
        color: #ffffff;
    }}
    QFrame#customTitleBar QPushButton#btnWinMin,
    QFrame#customTitleBar QPushButton#btnWinClose {{
        background: transparent;
        border: none;
        color: {t["chrome_muted"]};
    }}
    QFrame#customTitleBar QPushButton#btnWinMin:hover {{
        background: {t["chrome_bg_hi"]};
        color: {t["chrome_text"]};
    }}
    QFrame#customTitleBar QPushButton#btnWinClose:hover {{
        background: {t["accent_danger"]};
        color: #ffffff;
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
        f"QPushButton[dimmed=\"true\"] {{"
        f"  color: {t['text_muted']};"
        f"  background: {t['bg_subtle']};"
        f"  border-color: {t['border_subtle']};"
        f"}}"
    )


def mode_button_qss(theme: str = "dark") -> str:
    t = tokens(theme)
    return f"""
        QPushButton {{
            background: {t["bg_surface_hi"]};
            color: {t["text_primary"]};
            border: 1px solid {t["border_subtle"]};
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            padding: 9px 12px;
            min-width: 0px;
            max-width: 440px;
            min-height: 60px;
            max-height: 62px;
            text-align: left;
        }}
        QPushButton:hover {{
            border-color: {t["border_strong"]};
            background: {t["bg_card_hover"]};
        }}
        QPushButton:checked {{
            border: 1px solid {t["accent_gold"]};
            background: {t["bg_launch"]};
            font-weight: 700;
        }}
    """


def official_build_qss(theme: str = "dark") -> str:
    t = tokens(theme)
    return f"""
        QPushButton {{
            font-size: 13px;
            font-weight: 600;
            padding: 0px;
            border: none;
            border-bottom: 1px solid {t["border_subtle"]};
            border-radius: 0px;
            text-align: left;
            background: transparent;
            color: {t["text_primary"]};
            min-height: 38px;
            max-height: 38px;
        }}
        QPushButton:hover {{
            background: {t["bg_hover"]};
        }}
        QPushButton:checked {{
            background: {t["bg_subtle"]};
        }}
        QPushButton QLabel {{
            background: transparent;
        }}
        QPushButton QLabel#buildTitle {{
            font-size: 13px;
            font-weight: 600;
            color: {t["text_primary"]};
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
