"""ShuaBao 现代化双主题 (Dark / Light) QSS 样式引擎."""
from __future__ import annotations


class ThemeTokens:
    DARK = {
        "bg_app": "#0d1117",
        "bg_surface": "#161b22",
        "bg_subtle": "#21262d",
        "bg_hover": "#30363d",
        "border_subtle": "#30363d",
        "border_focus": "#388bfd",
        "text_primary": "#f0f6fc",
        "text_secondary": "#8b949e",
        "text_muted": "#6e7681",
        "accent_solo": "#2563eb",
        "accent_solo_hover": "#1d4ed8",
        "accent_hitch": "#059669",
        "accent_hitch_hover": "#047857",
        "accent_warning": "#d97706",
        "accent_danger": "#dc2626",
    }
    LIGHT = {
        "bg_app": "#F6F1E7",
        "bg_surface": "#FBF8F1",
        "bg_subtle": "#EFE8DA",
        "bg_hover": "#F1D48A",
        "border_subtle": "#CDBA93",
        "border_focus": "#D8A94A",
        "text_primary": "#2F2A24",
        "text_secondary": "#6A6257",
        "text_muted": "#8C6A3B",
        "accent_solo": "#D8A94A",
        "accent_solo_hover": "#A97822",
        "accent_hitch": "#5B9B63",
        "accent_hitch_hover": "#477A4D",
        "accent_warning": "#C97A2B",
        "accent_danger": "#B5554F",
    }


def tokens(theme: str = "light") -> dict[str, str]:
    return ThemeTokens.DARK if str(theme).lower() == "dark" else ThemeTokens.LIGHT


def apply_app_palette(theme: str = "light") -> None:
    """Force Qt palette to match tokens so Windows dark-mode doesn't invert text."""
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
    surface = QColor(t["bg_surface"])
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, bg)
    pal.setColor(QPalette.ColorRole.WindowText, fg)
    pal.setColor(QPalette.ColorRole.Base, surface)
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(t["bg_subtle"]))
    pal.setColor(QPalette.ColorRole.Text, fg)
    pal.setColor(QPalette.ColorRole.Button, QColor(t["bg_subtle"]))
    pal.setColor(QPalette.ColorRole.ButtonText, fg)
    pal.setColor(QPalette.ColorRole.ToolTipBase, surface)
    pal.setColor(QPalette.ColorRole.ToolTipText, fg)
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(t["text_secondary"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(t["border_focus"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(pal)


def get_qss(theme: str = "dark") -> str:
    t = tokens(theme)
    return f"""
    QMainWindow, QDialog {{
        background-color: {t["bg_app"]};
        color: {t["text_primary"]};
        font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
        font-size: 13px;
    }}
    QWidget {{
        background-color: transparent;
        color: {t["text_primary"]};
    }}
    QGroupBox {{
        background-color: {t["bg_surface"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 12px;
        margin-top: 12px;
        padding: 12px 10px 10px 10px;
        font-weight: 700;
        color: {t["text_primary"]};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
        color: {t["text_secondary"]};
    }}
    QLineEdit, QComboBox, QSpinBox, QAbstractSpinBox, QPlainTextEdit {{
        background-color: {t["bg_surface"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 8px;
        padding: 6px 8px;
        color: {t["text_primary"]};
        min-height: 24px;
    }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QScrollArea {{ border: none; background: transparent; }}
    QCheckBox {{ spacing: 8px; color: {t["text_primary"]}; }}
    QLabel {{ color: {t["text_primary"]}; }}
    QFrame#customTitleBar {{
        background-color: {t["bg_surface"]};
        border-bottom: 1px solid {t["border_subtle"]};
        padding: 6px 14px;
    }}
    QLabel#appBrandTitle, QLabel#brandTitle {{
        font-size: 16px;
        font-weight: 800;
        color: {t["text_primary"]};
    }}
    QLabel#brandSub {{ color: {t["text_secondary"]}; font-size: 12px; }}
    QFrame#cardContainer {{
        background-color: {t["bg_surface"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 12px;
        padding: 16px;
    }}
    QPushButton {{
        background-color: {t["bg_subtle"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 8px;
        color: {t["text_primary"]};
        padding: 8px 16px;
        font-size: 13px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: {t["bg_hover"]};
        border-color: {t["border_focus"]};
    }}
    QPushButton:pressed {{
        padding-top: 9px;
        padding-bottom: 7px;
    }}
    QPushButton#btnSoloLaunch {{
        background-color: {t["accent_solo"]};
        border: 1px solid {t["accent_solo"]};
        border-radius: 10px;
        color: #ffffff;
        font-size: 14px;
        font-weight: 700;
        padding: 12px 20px;
    }}
    QPushButton#btnHitchLaunch {{
        background-color: {t["accent_hitch"]};
        border: 1px solid {t["accent_hitch"]};
        border-radius: 10px;
        color: #ffffff;
        font-size: 14px;
        font-weight: 700;
        padding: 12px 20px;
    }}
    QPushButton#btnStart {{
        background-color: {t["accent_solo"]};
        color: #ffffff;
        border: 1px solid {t["accent_solo_hover"]};
        border-radius: 10px;
        font-weight: 700;
    }}
    QFrame#footerBar {{
        background-color: {t["bg_surface"]};
        border-top: 1px solid {t["border_subtle"]};
    }}
    """


def wizard_qss(theme: str = "light") -> str:
    t = tokens(theme)
    return get_qss(theme) + f"""
    QDialog {{
        background-color: {t["bg_app"]};
        color: {t["text_primary"]};
        font-family: 'Segoe UI', 'Microsoft YaHei UI';
        border: 1px solid {t["border_subtle"]};
        border-radius: 16px;
    }}
    QLabel#wizardTitle {{ font-size: 18px; font-weight: 800; color: {t["text_primary"]}; }}
    QLabel#wizardSub {{ font-size: 12px; color: {t["text_secondary"]}; }}
    QPushButton#goldBtn {{
        background: {t["accent_solo"]};
        border: 1px solid {t["accent_solo_hover"]};
        border-radius: 10px;
        color: #FFFFFF;
        font-weight: 700;
        padding: 8px 18px;
        min-height: 28px;
        min-width: 96px;
    }}
    QPushButton#goldBtn:hover {{ background: {t["accent_solo_hover"]}; }}
    QPushButton#secondaryBtn {{
        background-color: {t["bg_subtle"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 10px;
        color: {t["text_primary"]};
        padding: 8px 16px;
        min-height: 28px;
    }}
    QPushButton#choiceCard {{
        background-color: {t["bg_surface"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 16px;
        color: {t["text_primary"]};
        font-size: 14px;
        font-weight: 700;
        padding: 16px 14px;
        text-align: center;
    }}
    QPushButton#choiceCard:hover {{
        border: 1px solid {t["border_focus"]};
        background-color: {t["bg_subtle"]};
    }}
    QPushButton#choiceCard:checked {{
        background-color: {t["bg_hover"]};
        border: 2px solid {t["border_focus"]};
        color: {t["text_primary"]};
    }}
    """


def skill_card_qss(theme: str = "light") -> str:
    t = tokens(theme)
    return (
        f"QPushButton {{ background:{t['bg_surface']}; border:1px solid {t['border_subtle']}; border-radius:8px;"
        f" color:{t['text_primary']}; font-size:12px; padding:6px 4px; text-align:center; }}"
        f"QPushButton:hover {{ border:1px solid {t['border_focus']}; color:{t['text_primary']}; background:{t['bg_hover']}; }}"
        f"QPushButton:checked {{ background:{t['accent_solo']};"
        f" border:2px solid {t['border_focus']}; color:#FFFFFF; font-weight:bold; }}"
    )


def mode_button_qss(theme: str = "light") -> str:
    t = tokens(theme)
    return f"""
        QPushButton {{
            background-color: {t["bg_surface"]};
            color: {t["text_primary"]};
            border: 1px solid {t["border_subtle"]};
            border-radius: 12px;
            font-weight: 700;
        }}
        QPushButton:checked {{
            background-color: {t["bg_hover"]};
            border: 2px solid {t["border_focus"]};
        }}
    """


def official_build_qss(theme: str = "light") -> str:
    t = tokens(theme)
    return f"""
        QPushButton {{
            font-size: 13px;
            font-weight: 500;
            padding: 6px 12px;
            border-radius: 6px;
            text-align: left;
            background-color: {t["bg_subtle"]};
            color: {t["text_primary"]};
            border: 1px solid {t["border_subtle"]};
        }}
        QPushButton:checked {{
            background-color: {t["accent_hitch"]};
            color: white;
            font-weight: bold;
            border: 2px solid {t["accent_hitch_hover"]};
        }}
    """
