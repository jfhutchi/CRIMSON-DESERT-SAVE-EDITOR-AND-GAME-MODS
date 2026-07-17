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
    }
    assert required <= set(CRIMSON_DARK_TOKENS)
    assert required <= set(CRIMSON_LIGHT_TOKENS)
    assert DISPLAY_FONT.startswith("Georgia")
    assert BODY_FONT.startswith("Bahnschrift,")
    assert BODY_FONT_STYLE == "SemiCondensed"
    assert "Consolas" in MONO_FONT

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
        "QTabWidget#primaryNav",
        "QTabWidget#sectionNav",
        "QWidget#contextStrip",
        "QStatusBar#statusRail",
        'QPushButton[primaryAction="true"]',
        'QPushButton[dangerAction="true"]',
        "QPushButton:focus",
        "QLineEdit:focus",
        "QComboBox:focus",
        "min-height: 28px",
        "Georgia",
        "Bahnschrift,",
        "border-radius: 0px",
    ):
        assert required in stylesheet
    assert "purple" not in stylesheet.lower()
    assert "Inter" not in stylesheet


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
