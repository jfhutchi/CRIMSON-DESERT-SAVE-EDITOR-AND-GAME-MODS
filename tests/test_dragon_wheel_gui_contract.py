from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]


def test_main_window_registers_dragon_wheel_tab() -> None:
    source = (ROOT / "CrimsonGameMods" / "gui" / "main_window.py").read_text(
        encoding="utf-8"
    )

    assert "from gui.tabs.reserveslot import ReserveSlotTab" in source
    assert 'self._mods_tabs.addTab(self._reserve_slot_tab, "Dragon Wheel")' in source
    assert "self._reserve_slot_tab.set_game_path(path)" in source


def test_tab_exposes_only_the_focused_dragon_workflow() -> None:
    source = (ROOT / "CrimsonGameMods" / "gui" / "tabs" / "reserveslot.py").read_text(
        encoding="utf-8"
    )

    assert "All Mounts Everywhere" not in source
    assert "reserveslot_parser" not in source
    assert "Preview Dragon Wheel Patch" in source
    assert "Apply Dragon Wheel Patch" in source
    assert "Restore Dragon Wheel Patch" in source
    assert "Does not edit save files or quest flags" in source


def test_dragon_overlay_does_not_collide_with_itembuffs() -> None:
    tab_source = (
        ROOT / "CrimsonGameMods" / "gui" / "tabs" / "reserveslot.py"
    ).read_text(encoding="utf-8")
    coordinator_source = (
        ROOT / "CrimsonGameMods" / "overlay_coordinator.py"
    ).read_text(encoding="utf-8")

    assert "OVERLAY_GROUP = DRAGON_OVERLAY_GROUP" in tab_source
    assert '"0066": "ItemBuffs (index files)"' in coordinator_source
    assert '"0067": "Dragon Wheel (reserveslot)"' in coordinator_source


def test_apply_starts_disabled_and_path_change_invalidates_preview() -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "CrimsonGameMods")
    environment["QT_QPA_PLATFORM"] = "offscreen"
    script = r"""
from PySide6.QtWidgets import QApplication
from gui.tabs.reserveslot import ReserveSlotTab

app = QApplication.instance() or QApplication([])
tab = ReserveSlotTab({}, lambda: "")
assert tab._apply_btn.isEnabled() is False
tab._source_hashes = ("old-h", "old-b")
tab._preview_result = object()
tab._apply_btn.setEnabled(True)
tab.set_game_path(r"D:\Games\Crimson Desert")
assert tab._apply_btn.isEnabled() is False
assert tab._source_hashes is None
assert tab._preview_result is None
tab.deleteLater()
app.processEvents()
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
