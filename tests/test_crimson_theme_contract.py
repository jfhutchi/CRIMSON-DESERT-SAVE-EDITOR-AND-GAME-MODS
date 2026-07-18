from __future__ import annotations

from pathlib import Path

from crimson_common.crimson_theme import (
    BODY_FONT,
    BODY_FONT_STYLE,
    CRIMSON_DARK_TOKENS,
    CRIMSON_LIGHT_TOKENS,
    DISPLAY_FONT,
    MONO_FONT,
    build_stylesheet,
    install_crimson_shell,
    legacy_colors,
)


ROOT = Path(__file__).resolve().parents[1]


def test_crimson_token_vocabulary_and_typography_are_complete() -> None:
    required = {
        "ink",
        "obsidian",
        "charcoal",
        "ember",
        "bronze",
        "bronze_bright",
        "parchment",
        "ash",
        "crimson",
        "moss",
        "amber",
        "iron_red",
        "surface",
        "surface_warm",
        "divider",
        "accent_red",
        "text_bright",
    }
    assert required <= set(CRIMSON_DARK_TOKENS)
    assert required <= set(CRIMSON_LIGHT_TOKENS)
    assert DISPLAY_FONT.startswith("Georgia")
    assert BODY_FONT.startswith("Bahnschrift,")
    assert BODY_FONT_STYLE == "SemiCondensed"
    assert "Consolas" in MONO_FONT
    assert CRIMSON_DARK_TOKENS["accent_red"] == "#B63A32"
    assert CRIMSON_DARK_TOKENS["divider"] == "#29302B"

    colors = legacy_colors(CRIMSON_DARK_TOKENS)
    assert {
        "bg",
        "panel",
        "header",
        "accent",
        "text",
        "text_dim",
        "selected",
        "border",
        "input_bg",
        "success",
        "warning",
        "error",
        "scope_save",
        "scope_game",
    } <= set(colors)


def test_stylesheet_encodes_game_shell_focus_and_accessibility_roles() -> None:
    stylesheet = build_stylesheet(CRIMSON_DARK_TOKENS)
    for required in (
        "QMainWindow#crimsonWindow",
        "QWidget#crimsonApplicationShell",
        "QFrame#commandHeader",
        "QWidget#destinationNavigation",
        "QToolButton#destinationButton",
        "QFrame#contextNavigation",
        "QAbstractButton#routeButton",
        "QFrame#editorialWorkspace",
        "QFrame#routeHeader",
        "QToolButton#shellUtilityButton",
        "QTabWidget#primaryNav",
        "QTabWidget#sectionNav",
        "QWidget#contextStrip",
        "QStatusBar#statusRail",
        "QWidget#brandBlock",
        "QLabel#brandMark",
        "QWidget#shellIdentity",
        "QFrame#blackstarTimerPanel",
        "QFrame#blackstarMetricRow",
        "QFrame#changeRecord",
        'QPushButton[primaryAction="true"]',
        'QPushButton[dangerAction="true"]',
        "QPushButton:focus",
        "QLineEdit:focus",
        "QComboBox:focus",
        "min-height: 30px",
        "Georgia",
        "border-radius: 0px",
    ):
        assert required in stylesheet
    assert "purple" not in stylesheet.lower()
    assert "Inter" not in stylesheet


def test_stylesheet_matches_the_approved_flat_crimson_desert_direction() -> None:
    stylesheet = build_stylesheet(CRIMSON_DARK_TOKENS)
    accent = CRIMSON_DARK_TOKENS["accent_red"]
    divider = CRIMSON_DARK_TOKENS["divider"]

    assert f"border-bottom: 2px solid {accent}" in stylesheet
    assert f"border-top: 1px solid {divider}" in stylesheet
    assert "QPushButton, QToolButton {\n    min-height: 30px;\n    background: qlineargradient" in stylesheet
    assert "QGroupBox {\n    color:" in stylesheet
    assert "QGroupBox {\n    color:" + f" {accent};" in stylesheet
    assert "QGroupBox {\n    color:" + f" {accent};\n    border: 0px;" in stylesheet
    assert "QTabBar#primaryTabBar::tab {\n    min-height: 40px;" in stylesheet
    assert "QTabBar#primaryTabBar::tab:selected {\n    color:" in stylesheet
    assert 'QPushButton[primaryAction="true"]:disabled' in stylesheet
    assert "border-top: 3px solid" not in stylesheet
    assert "border: 1px solid #9C743B" not in stylesheet


def test_shared_shell_installer_is_used_by_both_main_windows() -> None:
    assert callable(install_crimson_shell)
    for relative in (
        "CrimsonSaveEditor/gui.py",
        "CrimsonGameMods/gui/main_window.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "install_crimson_application_shell(" in source
        assert "self._shell_destinations()" in source


def test_structural_shell_is_editorial_instead_of_boxed_tab_chrome() -> None:
    stylesheet = build_stylesheet(CRIMSON_DARK_TOKENS)
    assert "QFrame#commandHeader {" in stylesheet
    assert "min-height: 76px" in stylesheet
    assert "QToolButton#destinationButton:checked" in stylesheet
    assert "border-bottom: 2px solid" in stylesheet
    assert "QFrame#contextNavigation {" in stylesheet
    assert "border-right: 1px solid" in stylesheet
    assert "QAbstractButton#routeButton {" in stylesheet
    assert "border: 0px" in stylesheet
    assert "QAbstractButton#routeButton:checked" in stylesheet
    assert "border-left: 2px solid" in stylesheet
    assert "QFrame#routeHeader {" in stylesheet
    assert "font-family: Georgia" in stylesheet
    assert "QFrame#routeArtHalo" in stylesheet
    assert "QFrame#shellFooter" in stylesheet
    assert "QPushButton, QToolButton {\n    min-height: 30px;\n    background:" in stylesheet
    assert "QPushButton, QToolButton {\n    min-height: 30px;\n    background:" + f" transparent;\n    color:" not in stylesheet


def test_frozen_builds_bundle_the_blackstar_game_portrait() -> None:
    for relative in (
        "CrimsonSaveEditor/CrimsonSaveEditor.spec",
        "CrimsonGameMods/CrimsonGameMods.spec",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "1000799.webp" in source
        assert "crimson_assets" in source
        assert "crimson_common.crimson_icons" in source


def test_save_editor_mount_workspace_keeps_the_blackstar_surface_visible() -> None:
    source = (ROOT / "CrimsonSaveEditor" / "gui.py").read_text(encoding="utf-8")
    assert 'tab.setObjectName("mercenaryScroll")' in source
    assert "tab.setWidgetResizable(True)" in source
    assert "layout.insertWidget(1, self._blackstar_timer_panel)" in source


def test_both_application_theme_entrypoints_share_one_vocabulary() -> None:
    for relative in (
        "CrimsonSaveEditor/crimson_theme.py",
        "CrimsonGameMods/gui/crimson_theme.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "from crimson_common.crimson_theme import" in source
        assert "apply_crimson_theme" in source
        assert "CRIMSON_DARK_TOKENS" in source


def test_both_main_windows_assign_stable_shell_roles() -> None:
    for relative in (
        "CrimsonSaveEditor/gui.py",
        "CrimsonGameMods/gui/main_window.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert 'self.setObjectName("crimsonWindow")' in source
        assert 'self._tabs.setObjectName("primaryNav")' in source
        assert 'setObjectName("sectionNav")' in source
        assert 'self._global_info_widget.setObjectName("contextStrip")' in source
        assert 'setObjectName("statusRail")' in source


def test_ui_scale_and_compact_mode_keep_the_crimson_theme() -> None:
    save_editor = (ROOT / "CrimsonSaveEditor" / "gui.py").read_text(encoding="utf-8")
    game_mods = (ROOT / "CrimsonGameMods" / "gui" / "main_window.py").read_text(
        encoding="utf-8"
    )
    assert "apply_crimson_theme(" in save_editor
    assert "scale=scale" in save_editor
    assert "compact=compact" in save_editor
    assert "apply_theme(" in game_mods
    assert "scale=scale" in game_mods
    assert "compact=compact" in game_mods
