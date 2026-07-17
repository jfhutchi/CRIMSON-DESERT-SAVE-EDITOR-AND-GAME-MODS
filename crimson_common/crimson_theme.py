from __future__ import annotations

import re
from typing import Mapping


DISPLAY_FONT = 'Georgia, Cambria, "Times New Roman", serif'
BODY_FONT = 'Bahnschrift, "Segoe UI", sans-serif'
BODY_FONT_STYLE = "SemiCondensed"
MONO_FONT = '"Cascadia Mono", Consolas, monospace'

CRIMSON_DARK_TOKENS = {
    "ink": "#0A0907",
    "obsidian": "#12100D",
    "charcoal": "#201A14",
    "ember": "#2C2118",
    "bronze": "#9C743B",
    "bronze_bright": "#C6A15F",
    "parchment": "#E7DCC5",
    "ash": "#A89B87",
    "crimson": "#87352D",
    "moss": "#758B5C",
    "amber": "#C28A3C",
    "iron_red": "#A94A3E",
    "selection": "#44301D",
    "scope_save": "#789B96",
    "scope_game": "#C28A3C",
}

CRIMSON_LIGHT_TOKENS = {
    "ink": "#EEE5D5",
    "obsidian": "#F6F0E5",
    "charcoal": "#E3D7C4",
    "ember": "#D3C1A6",
    "bronze": "#7B5425",
    "bronze_bright": "#9A6D32",
    "parchment": "#271E15",
    "ash": "#66594A",
    "crimson": "#7E2D28",
    "moss": "#4E6C3D",
    "amber": "#955F19",
    "iron_red": "#8D302B",
    "selection": "#D5BA8E",
    "scope_save": "#356D6A",
    "scope_game": "#955F19",
}


def legacy_colors(tokens: Mapping[str, str]) -> dict[str, str]:
    """Map the shared vocabulary to keys used throughout both legacy UIs."""
    return {
        "bg": tokens["obsidian"],
        "panel": tokens["charcoal"],
        "header": tokens["ember"],
        "accent": tokens["bronze_bright"],
        "text": tokens["parchment"],
        "text_dim": tokens["ash"],
        "selected": tokens["selection"],
        "border": tokens["bronze"],
        "input_bg": tokens["ink"],
        "success": tokens["moss"],
        "warning": tokens["amber"],
        "error": tokens["iron_red"],
        "scope_save": tokens["scope_save"],
        "scope_game": tokens["scope_game"],
    }


def build_stylesheet(tokens: Mapping[str, str]) -> str:
    c = tokens
    return f"""
QMainWindow#crimsonWindow, QDialog {{
    background-color: {c['obsidian']};
    color: {c['parchment']};
}}
QWidget {{
    background-color: {c['obsidian']};
    color: {c['parchment']};
    font-family: {BODY_FONT};
    font-size: 10pt;
}}
QWidget:disabled {{ color: {c['ash']}; }}

QMenuBar {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {c['ember']}, stop:1 {c['charcoal']});
    color: {c['parchment']};
    border-top: 1px solid {c['bronze']};
    border-bottom: 1px solid {c['bronze']};
    padding: 3px 10px;
    font-family: {DISPLAY_FONT};
    font-size: 10pt;
}}
QMenuBar::item {{
    background: transparent;
    padding: 5px 12px;
    border-radius: 0px;
}}
QMenuBar::item:selected, QMenuBar::item:pressed {{
    background-color: {c['selection']};
    color: {c['bronze_bright']};
}}
QMenu {{
    background-color: {c['charcoal']};
    color: {c['parchment']};
    border: 1px solid {c['bronze']};
    padding: 4px;
}}
QMenu::item {{ padding: 6px 26px 6px 12px; }}
QMenu::item:selected {{
    background-color: {c['selection']};
    color: {c['bronze_bright']};
}}
QMenu::separator {{
    height: 1px;
    background-color: {c['bronze']};
    margin: 4px 8px;
}}

QTabWidget#primaryNav::pane {{
    border: 1px solid {c['bronze']};
    border-top: 2px solid {c['bronze_bright']};
    background-color: {c['obsidian']};
}}
QTabBar#primaryTabBar {{
    background-color: {c['ink']};
}}
QTabBar#primaryTabBar::tab {{
    min-height: 32px;
    min-width: 112px;
    padding: 6px 24px;
    margin: 0px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {c['ember']}, stop:1 {c['charcoal']});
    color: {c['ash']};
    border: 1px solid {c['bronze']};
    border-bottom: 0px;
    border-radius: 0px;
    font-family: {DISPLAY_FONT};
    font-size: 11pt;
    font-weight: 600;
}}
QTabBar#primaryTabBar::tab:selected {{
    background-color: {c['selection']};
    color: {c['parchment']};
    border-top: 3px solid {c['bronze_bright']};
}}
QTabBar#primaryTabBar::tab:hover:!selected {{
    color: {c['bronze_bright']};
    background-color: {c['ember']};
}}

QTabWidget#sectionNav::pane {{
    border: 0px;
    border-top: 1px solid {c['bronze']};
    background-color: {c['obsidian']};
}}
QTabBar#sectionTabBar {{ background-color: {c['ink']}; }}
QTabBar#sectionTabBar::tab {{
    min-height: 28px;
    padding: 4px 14px;
    margin: 0px;
    background-color: {c['charcoal']};
    color: {c['ash']};
    border: 0px;
    border-right: 1px solid {c['bronze']};
    border-bottom: 1px solid {c['bronze']};
    border-radius: 0px;
    font-weight: 600;
}}
QTabBar#sectionTabBar::tab:selected {{
    background-color: {c['selection']};
    color: {c['parchment']};
    border-bottom: 3px solid {c['bronze_bright']};
}}
QTabBar#sectionTabBar::tab:hover:!selected {{
    color: {c['bronze_bright']};
    background-color: {c['ember']};
}}

QWidget#contextStrip {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {c['ink']}, stop:0.55 {c['charcoal']}, stop:1 {c['ink']});
    border-top: 1px solid {c['bronze']};
    border-bottom: 1px solid {c['bronze']};
}}
QFrame#saveBrowser, QFrame#packBrowser {{
    background-color: {c['charcoal']};
    border: 0px;
}}

QLabel {{ background: transparent; }}
QLabel[heading="true"] {{
    color: {c['bronze_bright']};
    font-family: {DISPLAY_FONT};
    font-size: 12pt;
    font-weight: 600;
}}
QLabel[muted="true"] {{ color: {c['ash']}; }}

QPushButton, QToolButton {{
    min-height: 28px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {c['ember']}, stop:1 {c['charcoal']});
    color: {c['parchment']};
    border: 1px solid {c['bronze']};
    border-radius: 0px;
    padding: 3px 12px;
    font-weight: 600;
}}
QPushButton:hover, QToolButton:hover {{
    color: {c['bronze_bright']};
    border-color: {c['bronze_bright']};
    background-color: {c['selection']};
}}
QPushButton:pressed, QToolButton:pressed {{
    color: {c['ink']};
    background-color: {c['bronze_bright']};
}}
QPushButton:focus, QToolButton:focus {{
    outline: none;
    border: 2px solid {c['bronze_bright']};
}}
QPushButton:disabled, QToolButton:disabled {{
    color: {c['ash']};
    background-color: {c['ink']};
    border-color: {c['charcoal']};
}}
QPushButton#accentBtn,
QPushButton[primaryAction="true"] {{
    background-color: {c['bronze']};
    color: {c['ink']};
    border: 1px solid {c['bronze_bright']};
}}
QPushButton#accentBtn:hover,
QPushButton[primaryAction="true"]:hover {{
    background-color: {c['bronze_bright']};
    color: {c['ink']};
}}
QPushButton[dangerAction="true"] {{
    background-color: {c['crimson']};
    color: {c['parchment']};
    border: 1px solid {c['iron_red']};
}}
QPushButton[quietAction="true"] {{
    background: transparent;
    color: {c['ash']};
}}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit, QTimeEdit {{
    min-height: 28px;
    background-color: {c['ink']};
    color: {c['parchment']};
    border: 1px solid {c['bronze']};
    border-radius: 0px;
    padding: 2px 7px;
    selection-background-color: {c['selection']};
    selection-color: {c['parchment']};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 2px solid {c['bronze_bright']};
}}
QComboBox::drop-down {{
    width: 22px;
    border: 0px;
    border-left: 1px solid {c['bronze']};
    background-color: {c['charcoal']};
}}
QComboBox QAbstractItemView {{
    background-color: {c['charcoal']};
    color: {c['parchment']};
    border: 1px solid {c['bronze']};
    selection-background-color: {c['selection']};
}}

QGroupBox {{
    color: {c['bronze_bright']};
    border: 1px solid {c['bronze']};
    border-radius: 0px;
    margin-top: 14px;
    padding: 14px 8px 8px 8px;
    font-family: {DISPLAY_FONT};
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0px 7px;
    color: {c['bronze_bright']};
    background-color: {c['obsidian']};
}}

QTableWidget, QTableView, QTreeWidget, QTreeView, QListWidget, QListView,
QTextEdit, QPlainTextEdit {{
    background-color: {c['ink']};
    alternate-background-color: {c['obsidian']};
    color: {c['parchment']};
    border: 1px solid {c['bronze']};
    border-radius: 0px;
    gridline-color: {c['charcoal']};
    selection-background-color: {c['selection']};
    selection-color: {c['parchment']};
}}
QTableWidget, QTableView, QTreeWidget, QTreeView {{
    font-family: {BODY_FONT};
    font-size: 9.5pt;
}}
QTableWidget::item, QTableView::item {{ padding: 3px 6px; }}
QTreeWidget::item, QTreeView::item, QListWidget::item, QListView::item {{
    min-height: 24px;
    padding: 2px 5px;
}}
QTreeWidget::item:hover, QTreeView::item:hover,
QListWidget::item:hover, QListView::item:hover {{
    background-color: {c['charcoal']};
    color: {c['bronze_bright']};
}}
QHeaderView::section {{
    min-height: 26px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {c['ember']}, stop:1 {c['charcoal']});
    color: {c['bronze_bright']};
    border: 0px;
    border-right: 1px solid {c['bronze']};
    border-bottom: 1px solid {c['bronze']};
    padding: 3px 7px;
    font-family: {DISPLAY_FONT};
    font-weight: 600;
}}
QTableCornerButton::section {{
    background-color: {c['ember']};
    border: 1px solid {c['bronze']};
}}

QCheckBox, QRadioButton {{
    min-height: 24px;
    spacing: 7px;
    color: {c['parchment']};
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 15px;
    height: 15px;
    background-color: {c['ink']};
    border: 1px solid {c['bronze']};
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {c['bronze_bright']};
    border: 2px solid {c['parchment']};
}}

QStatusBar#statusRail {{
    min-height: 28px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {c['ink']}, stop:0.5 {c['charcoal']}, stop:1 {c['ink']});
    color: {c['ash']};
    border-top: 1px solid {c['bronze_bright']};
    font-size: 9pt;
}}
QStatusBar#statusRail::item {{ border: 0px; }}

QProgressBar {{
    min-height: 16px;
    background-color: {c['ink']};
    color: {c['parchment']};
    border: 1px solid {c['bronze']};
    border-radius: 0px;
    text-align: center;
}}
QProgressBar::chunk {{ background-color: {c['bronze_bright']}; }}

QSplitter::handle, QMainWindow::separator {{ background-color: {c['bronze']}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}
QSplitter::handle:hover, QMainWindow::separator:hover {{
    background-color: {c['bronze_bright']};
}}
QDockWidget {{
    color: {c['parchment']};
    border: 1px solid {c['bronze']};
}}
QDockWidget::title {{
    min-height: 26px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {c['ember']}, stop:1 {c['charcoal']});
    color: {c['bronze_bright']};
    border-bottom: 1px solid {c['bronze_bright']};
    padding: 4px 8px;
    font-family: {DISPLAY_FONT};
    font-weight: 600;
}}

QScrollBar:vertical {{
    width: 12px;
    margin: 0px;
    background-color: {c['ink']};
}}
QScrollBar:horizontal {{
    height: 12px;
    margin: 0px;
    background-color: {c['ink']};
}}
QScrollBar::handle {{
    min-height: 28px;
    min-width: 28px;
    background-color: {c['bronze']};
    border-radius: 0px;
}}
QScrollBar::handle:hover {{ background-color: {c['bronze_bright']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; }}

QToolTip {{
    background-color: {c['charcoal']};
    color: {c['parchment']};
    border: 1px solid {c['bronze_bright']};
    padding: 5px;
}}
"""


def scaled_stylesheet(
    tokens: Mapping[str, str],
    scale: float = 1.0,
    compact: bool = False,
) -> str:
    factor = max(0.5, min(2.0, scale)) * (0.86 if compact else 1.0)
    stylesheet = build_stylesheet(tokens)
    if abs(factor - 1.0) < 0.001:
        return stylesheet

    def scale_pixels(match: re.Match[str]) -> str:
        value = max(1, round(int(match.group(1)) * factor))
        return f"{value}px"

    return re.sub(r"(\d+)px", scale_pixels, stylesheet)


def apply_crimson_theme(
    app,
    mode: str = "dark",
    *,
    scale: float = 1.0,
    compact: bool = False,
) -> str:
    tokens = CRIMSON_LIGHT_TOKENS if mode == "light" else CRIMSON_DARK_TOKENS
    stylesheet = scaled_stylesheet(tokens, scale=scale, compact=compact)
    if app is not None:
        from PySide6.QtGui import QFont

        font = QFont()
        font.setFamilies(["Bahnschrift", "Segoe UI"])
        font.setStyleName(BODY_FONT_STYLE)
        font.setPointSize(10)
        app.setFont(font)
        app.setStyleSheet(stylesheet)
    return stylesheet
