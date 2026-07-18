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


def test_both_save_load_paths_run_decrypt_and_scan_on_qthread() -> None:
    paths = (
        ROOT / "CrimsonSaveEditor" / "gui.py",
        ROOT / "CrimsonGameMods" / "gui" / "main_window.py",
    )
    for path in paths:
        method = _method_source(path, "MainWindow", "_load_save")
        assert "GuiTaskWorker" in method
        assert "QThread" in method
        assert "worker.moveToThread(thread)" in method
        assert "thread.started.connect(worker.run)" in method
        assert "QApplication.processEvents" not in method


def test_paz_status_scan_returns_to_gui_via_signal_not_worker_timer() -> None:
    path = ROOT / "CrimsonGameMods" / "gui" / "tabs" / "patches.py"
    source = path.read_text(encoding="utf-8")
    method = _method_source(path, "GamePatchesTab", "_paz_refresh_status")
    assert "status_scan_ready = Signal(object)" in source
    assert "self.status_scan_ready.emit(results)" in method
    assert "QTimer.singleShot(0" not in method


def test_save_editor_parc_enrichment_runs_on_qthread() -> None:
    path = ROOT / "CrimsonSaveEditor" / "gui.py"
    method = _method_source(path, "MainWindow", "_deferred_parc_enrich")
    assert "GuiTaskWorker" in method
    assert "QThread" in method
    assert "worker.moveToThread(thread)" in method
    assert "thread.started.connect(worker.run)" in method
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
