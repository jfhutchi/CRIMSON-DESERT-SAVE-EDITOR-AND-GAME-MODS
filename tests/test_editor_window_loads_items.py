"""The real editor window must launch empty and fill every inventory tab.

Guards the two defects players actually reported: the editor reopening a stale
save on launch, and bag tabs (Camp Warehouse, Bank, Kuku, ...) sitting empty
while the items were present in the save all along.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "CrimsonSaveEditor", ROOT / "CrimsonGameMods", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

EXPECTED_TABS = {
    "All": 1416, "Equipment": 19, "Inventory": 204, "Quest": 122,
    "Camp Warehouse": 253, "Warehouse": 23, "Bank": 50, "Kuku": 165,
    "Money": 15, "Mercenary": 259,
}


@pytest.fixture(scope="module")
def editor_window(current_patch_save_path, tmp_path_factory):
    app = QApplication.instance() or QApplication([])
    QMessageBox.information = staticmethod(lambda *a, **k: 0)
    QMessageBox.question = staticmethod(lambda *a, **k: 0)
    QMessageBox.warning = staticmethod(lambda *a, **k: 0)
    QMessageBox.critical = staticmethod(lambda *a, **k: 0)
    QDialog.exec = lambda self: 0

    import gui

    work = tmp_path_factory.mktemp("editor-window")
    gui.MainWindow._get_config_path = lambda self: str(work / "cfg.json")
    slot = work / "slot104"
    slot.mkdir()
    shutil.copy2(current_patch_save_path, slot / "save.save")

    window = gui.MainWindow()
    window.show()
    assert window._save_data is None, (
        "the editor must not reopen the previous save at launch; after playing "
        "the game that file is stale"
    )

    window._load_save(str(slot / "save.save"))
    # The tabs carry "(loading…)" until population and PARC enrichment finish,
    # so their labels are the real settle signal.
    deadline = time.time() + 180
    while time.time() < deadline:
        app.processEvents()
        labels = [
            window._inv_subtabs.tabText(i)
            for i in range(window._inv_subtabs.count())
        ]
        if window._save_data is not None and not any(
            "loading" in label.lower() for label in labels
        ):
            break
        time.sleep(0.05)
    else:
        pytest.fail("inventory tabs never finished loading")
    app.processEvents()
    yield window
    # Tear the window down explicitly: leaving it alive with its worker
    # threads attached aborts the interpreter at Qt shutdown.
    window.close()
    window.deleteLater()
    app.processEvents()


def test_window_fills_every_inventory_tab(editor_window) -> None:
    labels = [
        editor_window._inv_subtabs.tabText(i)
        for i in range(editor_window._inv_subtabs.count())
    ]
    for name, count in EXPECTED_TABS.items():
        assert f"{name} ({count})" in labels, (
            f"tab '{name}' should report {count} items; got {labels}"
        )
    assert not any("loading" in label.lower() for label in labels), (
        "loading markers must be replaced by real counts once population ends"
    )


def test_window_shows_every_item_in_the_table(editor_window) -> None:
    assert len(editor_window._items) == 1416
    assert editor_window._inv_table.rowCount() == 1416
