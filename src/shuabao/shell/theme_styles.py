"""ShuaBao 游戏大厅主题：深色底 + 金边按钮（对齐英雄三国KK 开始游戏）。"""
from __future__ import annotations


class ThemeTokens:
    DARK = {
        "bg_app": "#0D1117",
        "bg_surface": "#161B22",
        "bg_subtle": "#21262D",
        "bg_hover": "#30363D",
        "border_subtle": "#30363D",
        "border_focus": "#D29922",
        "text_primary": "#F0F6FC",
        "text_secondary": "#8B949E",
        "text_muted": "#6E7681",
        "accent_solo": "#D29922",
        "accent_solo_hover": "#E3B341",
        "accent_hitch": "#BB8009",
        "accent_hitch_hover": "#D29922",
        "accent_warning": "#D29922",
        "accent_danger": "#F85149",
        "text_on_accent": "#0D1117",
    }
    LIGHT = {
        "bg_app": "#0D1117",
        "bg_surface": "#161B22",
        "bg_subtle": "#21262D",
        "bg_hover": "#30363D",
        "border_subtle": "#30363D",
        "border_focus": "#D29922",
        "text_primary": "#F0F6FC",
        "text_secondary": "#8B949E",
        "text_muted": "#6E7681",
        "accent_solo": "#D29922",
        "accent_solo_hover": "#E3B341",
        "accent_hitch": "#BB8009",
        "accent_hitch_hover": "#D29922",
        "accent_warning": "#D29922",
        "accent_danger": "#F85149",
        "text_on_accent": "#0D1117",
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
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(t["text_on_accent"]))
    app.setPalette(pal)


def get_qss(theme: str = "dark") -> str:
    t = tokens(theme)
    return f"""
    QMainWindow, QDialog {{
        background-color: {t["bg_app"]};
        color: {t["text_primary"]};
    }}
    QWidget {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
        font-size: 14px;
        color: {t["text_primary"]};
    }}
    QGroupBox {{
        font-weight: 700;
        font-size: 15px;
        border: 1px solid {t["border_subtle"]};
        border-radius: 10px;
        margin-top: 14px;
        padding: 18px 14px 14px 14px;
        background-color: {t["bg_surface"]};
        color: {t["text_primary"]};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 14px;
        padding: 0 8px;
        color: {t["border_focus"]};
    }}
    QLineEdit, QComboBox, QSpinBox, QAbstractSpinBox, QPlainTextEdit {{
        background-color: {t["bg_subtle"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 8px;
        padding: 6px 12px;
        color: {t["text_primary"]};
        min-height: 28px;
        font-size: 14px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {t["bg_surface"]};
        color: {t["text_primary"]};
        selection-background-color: {t["accent_solo"]};
        selection-color: {t["text_on_accent"]};
    }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QScrollArea {{ border: none; background: transparent; }}
    QCheckBox {{ spacing: 8px; color: {t["text_primary"]}; font-size: 14px; }}
    QLabel {{ color: {t["text_primary"]}; font-size: 14px; }}
    QFrame#customTitleBar {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #161B22, stop:0.5 #1B222D, stop:1 #161B22);
        border-bottom: 1px solid rgba(210, 153, 34, 0.45);
        border-top-left-radius: 12px;
        border-top-right-radius: 12px;
        padding: 8px 16px;
    }}
    QLabel#appBrandTitle, QLabel#brandTitle {{
        font-size: 19px;
        font-weight: 800;
        color: {t["border_focus"]};
        letter-spacing: 0.5px;
    }}
    QLabel#brandSub {{ color: {t["text_secondary"]}; font-size: 13px; font-weight: 500; }}
    QLabel#statusPill {{
        background-color: rgba(22, 27, 34, 0.85);
        border: 1px solid rgba(210, 153, 34, 0.6);
        border-radius: 8px;
        padding: 5px 14px;
        color: {t["text_primary"]};
        font-weight: 700;
        font-size: 13px;
    }}
    QFrame#cardContainer {{
        background-color: {t["bg_surface"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 8px;
        padding: 16px;
    }}
    QPushButton {{
        background-color: {t["bg_subtle"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 6px;
        color: {t["text_primary"]};
        padding: 8px 16px;
        font-size: 14px;
        font-weight: 700;
        min-height: 32px;
    }}
    QPushButton:hover {{
        background-color: {t["bg_hover"]};
        border-color: {t["border_focus"]};
        color: {t["text_primary"]};
    }}
    QPushButton:pressed {{
        padding-top: 9px;
        padding-bottom: 7px;
    }}
    QPushButton#btnSoloLaunch {{
        background-color: {t["accent_solo"]};
        border: 1px solid {t["accent_solo_hover"]};
        border-radius: 6px;
        color: {t["text_on_accent"]};
        font-size: 15px;
        font-weight: 800;
        padding: 12px 20px;
    }}
    QPushButton#btnHitchLaunch {{
        background-color: {t["accent_hitch"]};
        border: 1px solid {t["accent_hitch_hover"]};
        border-radius: 6px;
        color: {t["text_on_accent"]};
        font-size: 15px;
        font-weight: 800;
        padding: 12px 20px;
    }}
    QPushButton#btnStart {{
        background-color: {t["accent_solo"]};
        color: {t["text_on_accent"]};
        border: 1px solid {t["accent_solo_hover"]};
        border-radius: 6px;
        font-size: 15px;
        font-weight: 800;
        min-height: 44px;
    }}
    QPushButton#btnStart:hover {{
        background-color: {t["accent_solo_hover"]};
        color: {t["text_on_accent"]};
    }}
    QPushButton#btnStop {{
        background-color: {t["accent_danger"]};
        color: {t["text_primary"]};
        border: 1px solid #E85D5D;
        border-radius: 6px;
        font-size: 15px;
        font-weight: 800;
        min-height: 44px;
    }}
    QFrame#footerBar {{
        background-color: {t["bg_surface"]};
        border-top: 1px solid {t["border_focus"]};
    }}
    QLabel#statusLine {{ color: {t["text_primary"]}; font-size: 13px; }}
    """


def wizard_qss(theme: str = "light") -> str:
    t = tokens(theme)
    return get_qss(theme) + f"""
    QDialog {{
        background-color: {t["bg_app"]};
        color: {t["text_primary"]};
        font-family: 'Microsoft YaHei UI', 'Segoe UI';
        border: 1px solid {t["border_focus"]};
        border-radius: 8px;
    }}
    QLabel#wizardTitle {{ font-size: 20px; font-weight: 800; color: {t["border_focus"]}; }}
    QLabel#wizardSub {{ font-size: 13px; color: {t["text_secondary"]}; }}
    QPushButton#goldBtn {{
        background: {t["accent_solo"]};
        border: 1px solid {t["accent_solo_hover"]};
        border-radius: 6px;
        color: {t["text_on_accent"]};
        font-size: 15px;
        font-weight: 800;
        padding: 10px 22px;
        min-height: 36px;
        min-width: 108px;
    }}
    QPushButton#goldBtn:hover {{ background: {t["accent_solo_hover"]}; color: {t["text_on_accent"]}; }}
    QPushButton#secondaryBtn {{
        background-color: {t["bg_subtle"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 6px;
        color: {t["text_primary"]};
        padding: 10px 16px;
        min-height: 36px;
    }}
    QPushButton#choiceCard {{
        background-color: {t["bg_surface"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 8px;
        color: {t["text_primary"]};
        font-size: 15px;
        font-weight: 700;
        padding: 18px 14px;
        text-align: center;
    }}
    QPushButton#choiceCard:hover {{
        border: 1px solid {t["border_focus"]};
        background-color: {t["bg_subtle"]};
        color: {t["text_primary"]};
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
        f"QPushButton {{ background:{t['bg_surface']}; border:1px solid {t['border_subtle']}; border-radius:6px;"
        f" color:{t['text_primary']}; font-size:13px; padding:8px 6px; text-align:center; }}"
        f"QPushButton:hover {{ border:1px solid {t['border_focus']}; color:{t['text_primary']}; background:{t['bg_hover']}; }}"
        f"QPushButton:checked {{ background:{t['accent_solo']};"
        f" border:2px solid {t['border_focus']}; color:{t['text_on_accent']}; font-weight:bold; }}"
    )


def mode_button_qss(theme: str = "light") -> str:
    t = tokens(theme)
    return f"""
        QPushButton {{
            background-color: {t["bg_surface"]};
            color: {t["text_primary"]};
            border: 1px solid {t["border_subtle"]};
            border-radius: 8px;
            font-size: 15px;
            font-weight: 700;
        }}
        QPushButton:hover {{
            border: 1px solid {t["border_focus"]};
            color: {t["text_primary"]};
        }}
        QPushButton:checked {{
            background-color: {t["bg_hover"]};
            border: 2px solid {t["border_focus"]};
            color: {t["text_primary"]};
        }}
    """


def official_build_qss(theme: str = "light") -> str:
    t = tokens(theme)
    return f"""
        QPushButton {{
            font-size: 13px;
            font-weight: 500;
            padding: 8px 12px;
            border-radius: 6px;
            text-align: left;
            background-color: {t["bg_subtle"]};
            color: {t["text_primary"]};
            border: 1px solid {t["border_subtle"]};
        }}
        QPushButton:checked {{
            background-color: {t["accent_solo"]};
            color: {t["text_on_accent"]};
            font-weight: bold;
            border: 2px solid {t["border_focus"]};
        }}
    """
