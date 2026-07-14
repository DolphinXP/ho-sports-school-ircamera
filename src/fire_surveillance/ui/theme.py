"""Dark theme — palette + Qt stylesheet.

Mirrors the reference Avalonia app's resource brushes (AppBackground, Surface,
SurfaceLight, Accent, Text*…). Centralising colours here lets every widget
reference the same tokens instead of hard-coding hex values.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# --- colour tokens --------------------------------------------------------
class C:
    app_background = "#16191f"
    surface = "#1f232b"
    surface_light = "#272c36"
    surface_dark = "#161a20"
    card = "#22262f"
    accent = "#3b82f6"
    accent_hover = "#2563eb"
    accent_pressed = "#1d4ed8"
    text_primary = "#e8eaed"
    text_secondary = "#9aa0a6"
    text_tertiary = "#5f6368"
    success = "#4caf50"
    warning = "#ffa726"
    danger = "#f44336"
    glass_border = "rgba(255,255,255,0.08)"
    image_bg = "#000000"


STYLESHEET = f"""
* {{
    font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", "Noto Sans CJK SC", sans-serif;
    font-size: 13px;
    color: {C.text_primary};
    outline: none;
}}

QMainWindow, QWidget#CentralWidget {{
    background-color: {C.app_background};
}}

/* ---- card / glass containers ---- */
QFrame#Card, QFrame#Glass {{
    background-color: {C.card};
    border: 1px solid {C.glass_border};
    border-radius: 10px;
}}
QFrame#Glass {{
    background-color: rgba(31,35,43,0.85);
}}

QFrame#Panel {{
    background-color: {C.surface_light};
    border: 1px solid {C.glass_border};
    border-radius: 6px;
}}

/* ---- title bar ---- */
QFrame#TitleBar, QFrame#Footer {{
    background-color: {C.surface};
    border: none;
}}
QFrame#TitleBar {{ border-bottom: 1px solid {C.glass_border}; }}
QFrame#Footer {{ border-top: 1px solid {C.glass_border}; }}

QLabel#AppTitle {{
    font-size: 20px;
    font-weight: 600;
    color: {C.text_primary};
}}
QLabel#SectionLabel {{
    font-size: 15px;
    font-weight: 600;
    color: {C.text_primary};
}}
QLabel#StatusCaption {{
    font-size: 10px;
    color: {C.text_tertiary};
}}
QLabel#StatusValue {{
    font-size: 13px;
    font-weight: 700;
    color: {C.text_primary};
}}
QLabel#StatusValueAccent {{
    font-size: 13px;
    font-weight: 700;
    color: {C.accent};
}}

/* ---- radio buttons: obvious filled indicator ---- */
QRadioButton {{ spacing: 8px; }}
QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 9px;
    background: transparent;
    border: 2px solid #6b7280;
}}
QRadioButton::indicator:hover {{ border-color: #b8bcc4; }}
QRadioButton::indicator:checked {{
    border: 2px solid {C.accent};
    background: {C.accent};
    image: none;
}}
QRadioButton::indicator:checked:hover {{
    border-color: {C.accent_hover};
    background: {C.accent_hover};
}}
QRadioButton:disabled::indicator {{ border-color: #3a3f48; }}

/* ---- buttons ---- */
QPushButton {{
    background-color: {C.surface_light};
    border: 1px solid {C.glass_border};
    border-radius: 6px;
    padding: 6px 12px;
    color: {C.text_primary};
}}
QPushButton:hover {{ background-color: #313742; }}
QPushButton:pressed {{ background-color: #1d2129; }}
QPushButton:disabled {{ color: {C.text_tertiary}; background-color: #1c2027; border-color: transparent; }}

QPushButton#AccentButton, QPushButton[cssClass="accent"] {{
    background-color: {C.accent};
    border: none;
    color: white;
    font-weight: 600;
}}
QPushButton#AccentButton:hover {{ background-color: {C.accent_hover}; }}
QPushButton#AccentButton:pressed {{ background-color: {C.accent_pressed}; }}
QPushButton#AccentButton:disabled {{ background-color: #2a3a55; color: #8aa6c9; }}

QPushButton#IconButton {{
    background-color: {C.surface_light};
    border: 1px solid {C.glass_border};
    border-radius: 6px;
    min-width: 34px; min-height: 34px; max-width: 34px; max-height: 34px;
    padding: 0px;
    font-size: 16px;
    font-weight: 700;
}}
QPushButton#IconButton:hover {{ background-color: #313742; }}

/* ---- inputs ---- */
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background-color: {C.surface_dark};
    border: 1px solid {C.glass_border};
    border-radius: 6px;
    padding: 5px 8px;
    min-height: 22px;
    color: {C.text_primary};
}}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover {{ border-color: {C.accent}; }}
QComboBox:disabled, QSpinBox:disabled, QLineEdit:disabled {{ color: {C.text_tertiary}; }}

QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow {{
    image: none;
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {C.text_secondary};
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {C.surface_light};
    border: 1px solid {C.glass_border};
    selection-background-color: {C.accent};
    outline: none;
}}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background-color: transparent;
    width: 16px;
}}

/* ---- sliders ---- */
QSlider::groove:horizontal {{
    height: 4px;
    background: {C.surface_dark};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{ background: {C.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: white;
    width: 14px; height: 14px;
    margin: -6px 0;
    border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{ background: {C.accent}; }}
QSlider:disabled::sub-page:horizontal {{ background: {C.text_tertiary}; }}
QSlider:disabled::handle:horizontal {{ background: {C.text_tertiary}; }}

/* ---- tabs ---- */
QTabWidget::pane {{ border: none; top: 0px; }}
QTabBar::tab {{
    background: transparent;
    color: {C.text_secondary};
    padding: 8px 14px 10px 0px;
    margin-right: 18px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 600;
}}
QTabBar::tab:hover {{ color: {C.text_primary}; }}
QTabBar::tab:selected {{
    color: {C.accent};
    border-bottom: 2px solid {C.accent};
}}

/* ---- scroll area ---- */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #3a404b; border-radius: 4px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: #4a515e; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent; height: 10px; margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: #3a404b; border-radius: 4px; min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{ background: #4a515e; }}

/* ---- image view overlay ---- */
QLabel#ImageInfoLabel {{
    background-color: rgba(20,23,28,0.78);
    color: {C.text_secondary};
    border: 1px solid {C.glass_border};
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 11px;
}}
QLabel#FireAlarmBanner {{
    background-color: rgba(238,0,0,0.93);
    color: white;
    border-radius: 4px;
    padding: 8px 18px;
    font-size: 15px;
    font-weight: 700;
}}

QLabel#ImageCanvas {{
    background-color: {C.image_bg};
}}

QSplitter::handle {{ background-color: transparent; }}
"""


def apply_theme(app: QApplication) -> None:
    """Apply the dark palette and stylesheet to the application."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(C.app_background))
    palette.setColor(QPalette.ColorRole.Base, QColor(C.surface))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(C.surface_light))
    palette.setColor(QPalette.ColorRole.Text, QColor(C.text_primary))
    palette.setColor(QPalette.ColorRole.Button, QColor(C.surface_light))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(C.text_primary))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(C.accent))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(C.surface_light))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(C.text_primary))
    disabled = QPalette.ColorGroup.Disabled
    palette.setColor(disabled, QPalette.ColorRole.WindowText, QColor(C.text_tertiary))
    palette.setColor(disabled, QPalette.ColorRole.Text, QColor(C.text_tertiary))
    palette.setColor(disabled, QPalette.ColorRole.ButtonText, QColor(C.text_tertiary))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
