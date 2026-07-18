from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton

from crimson_common.blackstar_timer_ui import BlackstarTimerPanel


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module", autouse=True)
def qt_application():
    return QApplication.instance() or QApplication([])


def test_shared_panel_exposes_fixed_preset_and_safe_initial_state() -> None:
    panel = BlackstarTimerPanel(title="Blackstar Timer")
    text = " ".join(label.text() for label in panel.findChildren(type(panel._status)))
    buttons = {
        button.text(): button for button in panel.findChildren(QPushButton)
    }

    assert "30 minutes" in text
    assert "1 second" in text
    assert "affects every save" in text
    assert "does not change the loaded save" in text
    assert "quest" in text.lower()
    assert set(buttons) >= {
        "Preview 30m / 1s",
        "Apply Preset",
        "Restore Original",
    }
    assert buttons["Preview 30m / 1s"].isEnabled()
    assert not buttons["Apply Preset"].isEnabled()
    assert buttons["Preview 30m / 1s"].property("quietAction") is True
    assert buttons["Apply Preset"].property("primaryAction") is True
    assert buttons["Restore Original"].property("quietAction") is True


def test_shared_panel_matches_the_approved_blackstar_editorial_layout() -> None:
    panel = BlackstarTimerPanel(title="Blackstar Timer")

    assert isinstance(panel, QFrame)
    assert panel.objectName() == "blackstarTimerPanel"
    assert panel.findChild(QLabel, "blackstarTimerEyebrow").text() == "GAME ARCHIVE SETTING"
    assert panel.findChild(QLabel, "blackstarTimerTitle").text() == "Blackstar"
    assert panel.findChild(QLabel, "blackstarTimerSectionTitle").text() == "Extended Flight"
    assert panel.findChild(QLabel, "blackstarDurationBefore").text() == "10 min"
    assert panel.findChild(QLabel, "blackstarDurationAfter").text() == "30 min"
    assert panel.findChild(QLabel, "blackstarCooldownBefore").text() == "60 min"
    assert panel.findChild(QLabel, "blackstarCooldownAfter").text() == "1 sec"
    assert panel.findChild(QFrame, "changeRecord") is not None
    assert panel.findChild(QLabel, "blackstarSaveChanges").text() == "None"
    assert panel.findChild(QLabel, "blackstarQuestChanges").text() == "None"
    assert panel.findChild(QLabel, "blackstarFieldsChanged").text() == "2"


def test_both_applications_use_the_shared_timer_panel() -> None:
    save_editor = (ROOT / "CrimsonSaveEditor" / "gui.py").read_text(
        encoding="utf-8"
    )
    game_mods = (
        ROOT / "CrimsonGameMods" / "gui" / "tabs" / "patches.py"
    ).read_text(encoding="utf-8")

    assert "BlackstarTimerPanel" in save_editor
    assert 'title="Blackstar Game Settings"' in save_editor
    assert "BlackstarTimerPanel" in game_mods
    assert 'title="Blackstar Timer"' in game_mods


def test_game_mods_exposes_game_patches_as_a_visible_tab() -> None:
    source = (ROOT / "CrimsonGameMods" / "gui" / "main_window.py").read_text(
        encoding="utf-8"
    )
    assert 'self._mods_tabs.addTab(self._patches_tab, "Game Patches")' in source


def test_timer_panel_runs_archive_operations_on_qthread() -> None:
    source = (
        ROOT / "crimson_common" / "blackstar_timer_ui.py"
    ).read_text(encoding="utf-8")
    assert "QThread" in source
    assert "worker.moveToThread(thread)" in source
    assert "thread.started.connect(worker.run)" in source
    assert "worker.finished.connect(thread.quit)" in source
    assert "progress.canceled.connect(worker.request_cancel, Qt.DirectConnection)" in source
