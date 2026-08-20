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

def get_qss(theme: str = "dark") -> str:
    t = ThemeTokens.DARK if theme == "dark" else ThemeTokens.LIGHT
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
    QFrame#customTitleBar {{
        background-color: {t["bg_surface"]};
        border-bottom: 1px solid {t["border_subtle"]};
        padding: 6px 14px;
    }}
    QLabel#appBrandTitle {{
        font-size: 16px;
        font-weight: 800;
        color: {t["text_primary"]};
    }}
    QFrame#cardContainer {{
        background-color: {t["bg_surface"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 12px;
        padding: 16px;
    }}
    QPushButton {{
        background-color: {t["bg_subtle"]};
        border: 1px solid {t["border_subtle"]};
        border-radius: 6px;
        color: {t["text_primary"]};
        padding: 8px 16px;
        font-size: 13px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: {t["bg_hover"]};
        border-color: {t["border_focus"]};
    }}
    QPushButton#btnSoloLaunch {{
        background-color: {t["accent_solo"]};
        border: 1px solid {t["accent_solo"]};
        border-radius: 8px;
        color: #ffffff;
        font-size: 14px;
        font-weight: 700;
        padding: 12px 20px;
    }}
    QPushButton#btnHitchLaunch {{
        background-color: {t["accent_hitch"]};
        border: 1px solid {t["accent_hitch"]};
        border-radius: 8px;
        color: #ffffff;
        font-size: 14px;
        font-weight: 700;
        padding: 12px 20px;
    }}
    """
