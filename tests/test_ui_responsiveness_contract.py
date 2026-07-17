from __future__ import annotations

import ast
from pathlib import Path


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
