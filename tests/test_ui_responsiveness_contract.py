from __future__ import annotations

import ast
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

GAME_MODS = Path(__file__).resolve().parents[1] / "CrimsonGameMods"
if str(GAME_MODS) not in sys.path:
    sys.path.insert(0, str(GAME_MODS))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from crimson_common.gui_population import IncrementalGuiJob
from crimson_common.gui_task_worker import start_gui_task


ROOT = Path(__file__).resolve().parents[1]


def _method_source(path: Path, class_name: str, method_name: str) -> str:
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method_name:
                    segment = ast.get_source_segment(source, child)
                    assert segment is not None
                    return segment
    raise AssertionError(f"Missing {class_name}.{method_name} in {path}")


def test_both_save_load_paths_use_gui_owned_background_callbacks() -> None:
    paths = (
        ROOT / "CrimsonSaveEditor" / "gui.py",
        ROOT / "CrimsonGameMods" / "gui" / "main_window.py",
    )
    for path in paths:
        method = _method_source(path, "MainWindow", "_load_save")
        assert "start_gui_task" in method
        assert "GuiTaskWorker" not in method
        assert "worker.moveToThread" not in method
        assert "QApplication.processEvents" not in method


def test_paz_status_scan_returns_to_gui_via_signal_not_worker_timer() -> None:
    path = ROOT / "CrimsonGameMods" / "gui" / "tabs" / "patches.py"
    source = path.read_text(encoding="utf-8")
    method = _method_source(path, "GamePatchesTab", "_paz_refresh_status")
    assert "status_scan_ready = Signal(object)" in source
    assert "self.status_scan_ready.emit(results)" in method
    assert "QTimer.singleShot(0" not in method


def test_save_editor_parc_enrichment_uses_gui_owned_background_callbacks() -> None:
    path = ROOT / "CrimsonSaveEditor" / "gui.py"
    method = _method_source(path, "MainWindow", "_deferred_parc_enrich")
    assert "start_gui_task" in method
    assert "GuiTaskWorker" not in method
    assert "worker.moveToThread" not in method
    assert "QApplication.processEvents" not in method


def test_skill_archive_extraction_and_deep_parse_run_on_qthread() -> None:
    path = ROOT / "CrimsonGameMods" / "gui" / "tabs" / "patches.py"
    method = _method_source(path, "SkillsTab", "_skill_extract")
    assert "GuiTaskWorker" in method
    assert "QThread" in method
    assert "worker.moveToThread(thread)" in method
    assert "thread.started.connect(worker.run)" in method
    assert "QApplication.processEvents" not in method


def test_blackstar_timer_cancel_reaches_busy_worker_immediately() -> None:
    source = (ROOT / "crimson_common" / "blackstar_timer_ui.py").read_text(
        encoding="utf-8"
    )
    assert "progress.canceled.connect(worker.request_cancel, Qt.DirectConnection)" in source


def test_shared_long_task_worker_is_bundled_in_both_executables() -> None:
    for relative in (
        "CrimsonSaveEditor/CrimsonSaveEditor.spec",
        "CrimsonGameMods/CrimsonGameMods.spec",
    ):
        spec = (ROOT / relative).read_text(encoding="utf-8")
        assert "crimson_common.gui_task_worker" in spec
        assert "crimson_common.gui_population" in spec


def test_shared_task_launcher_keeps_the_gui_event_loop_responsive() -> None:
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    loop = QEventLoop()
    ticks: list[int] = []
    results: list[str] = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(len(ticks)))
    timer.start()

    handle = start_gui_task(
        owner,
        task=lambda report: (time.sleep(0.08), report("Done", 95), "complete")[-1],
        completed=results.append,
        failed=lambda message, _details: (_ for _ in ()).throw(AssertionError(message)),
        finished=loop.quit,
    )
    QTimer.singleShot(2000, loop.quit)
    loop.exec()
    timer.stop()

    assert handle.is_running is False
    assert results == ["complete"]
    assert len(ticks) >= 3
    app.processEvents()


def test_incremental_gui_population_yields_between_row_batches() -> None:
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    loop = QEventLoop()
    ticks: list[int] = []
    consumed: list[int] = []
    timer = QTimer()
    timer.setInterval(1)
    timer.timeout.connect(lambda: ticks.append(len(ticks)))
    timer.start()
    job = IncrementalGuiJob(
        owner,
        items=tuple(range(600)),
        consume=lambda _index, value: consumed.append(value),
        batch_size=20,
        time_budget_ms=2,
    )
    job.completed.connect(loop.quit)
    QTimer.singleShot(2000, loop.quit)
    job.start()
    loop.exec()
    timer.stop()

    assert consumed == list(range(600))
    assert len(ticks) >= 2
    app.processEvents()


def test_disk_scans_and_long_exports_use_the_shared_background_launcher() -> None:
    method_specs = (
        (ROOT / "CrimsonSaveEditor" / "gui.py", "MainWindow", "_global_auto_detect_path"),
        (ROOT / "CrimsonSaveEditor" / "gui.py", "MainWindow", "_paz_auto_detect_path"),
        (ROOT / "CrimsonSaveEditor" / "gui.py", "MainWindow", "_auto_find_save"),
        (ROOT / "CrimsonSaveEditor" / "gui.py", "MainWindow", "_export_mod_json"),
        (ROOT / "CrimsonSaveEditor" / "gui.py", "MainWindow", "_export_mod_zip"),
        (ROOT / "CrimsonGameMods" / "gui" / "main_window.py", "MainWindow", "_global_auto_detect_path"),
        (ROOT / "CrimsonGameMods" / "gui" / "main_window.py", "MainWindow", "_auto_find_save"),
        (ROOT / "CrimsonGameMods" / "gui" / "tabs" / "patches.py", "GamePatchesTab", "_paz_auto_detect_path"),
    )
    for path, class_name, method_name in method_specs:
        method = _method_source(path, class_name, method_name)
        assert "start_gui_task" in method, f"{path.name}:{method_name}"
        assert "QApplication.processEvents" not in method


def test_save_editor_load_completion_populates_tables_incrementally() -> None:
    for path in (
        ROOT / "CrimsonSaveEditor" / "gui.py",
        ROOT / "CrimsonGameMods" / "gui" / "main_window.py",
    ):
        method = _method_source(path, "MainWindow", "_load_save")
        populate = _method_source(path, "MainWindow", "_populate_scanned_items")

        assert "incremental=True" in method
        assert "IncrementalGuiJob" in populate
        assert "QApplication.processEvents" not in method
        if path.name == "gui.py" and path.parent.name == "CrimsonSaveEditor":
            assert "_inv_count_label.setText(str(len(self._items)))" in populate


def test_save_editor_parc_refresh_does_not_rebuild_tables_in_one_callback() -> None:
    path = ROOT / "CrimsonSaveEditor" / "gui.py"
    method = _method_source(path, "MainWindow", "_finish_parc_enrich")

    assert "incremental=True" in method
    assert "schedule_enrichment=False" in method
    assert "self._populate_inventory()" not in method
    assert "self._populate_equipment()" not in method


def test_game_mods_itembuff_inventory_results_are_populated_incrementally() -> None:
    path = ROOT / "CrimsonGameMods" / "gui" / "tabs" / "buffs_v319.py"
    method = _method_source(path, "ItemBuffsTab", "_buff_show_my_inventory")

    assert "IncrementalGuiJob" in method
    assert "QApplication.processEvents" not in method


def test_rescans_do_not_rebuild_all_visible_rows_in_one_callback() -> None:
    for path in (
        ROOT / "CrimsonSaveEditor" / "gui.py",
        ROOT / "CrimsonGameMods" / "gui" / "main_window.py",
    ):
        method = _method_source(path, "MainWindow", "_scan_and_populate")
        assert "incremental=True" in method
