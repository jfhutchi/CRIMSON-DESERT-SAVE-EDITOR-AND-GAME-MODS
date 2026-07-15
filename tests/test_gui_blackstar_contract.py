from __future__ import annotations

import ast
from pathlib import Path

GUI_PATH = Path(__file__).resolve().parents[1] / "CrimsonSaveEditor" / "gui.py"


def _method_source(name: str) -> str:
    source = GUI_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Method {name} not found")


def test_no_quest_button_connects_only_to_safe_worker_entrypoint() -> None:
    source = _method_source("_build_mercenary_tab")
    full_source = GUI_PATH.read_text(encoding="utf-8")
    assert "Unlock Blackstar (No Quest Changes)" in source
    assert "self._blackstar_btn.clicked.connect(self._start_blackstar_unlock)" in source
    assert "_unlock_dragon_mount_no_quests" not in source
    assert "def _unlock_dragon_mount_no_quests" not in full_source


def test_blackstar_dry_run_defaults_on_and_uses_qthread() -> None:
    build_source = _method_source("_build_mercenary_tab")
    start_source = _method_source("_start_blackstar_unlock")
    assert 'QCheckBox("Dry run (no changes)")' in build_source
    assert "self._blackstar_dry_run.setChecked(True)" in build_source
    assert "QThread" in start_source
    assert "insert_quest_completed" not in start_source


def test_blackstar_completion_rejects_stale_results_and_supports_structural_undo() -> None:
    finish_source = _method_source("_finish_blackstar_unlock")
    undo_source = _method_source("_undo")
    assert "document_generation" in finish_source
    assert "hashlib.sha256(current).hexdigest()" in finish_source
    assert "self._blackstar_input_hash" in finish_source
    assert "self._loaded_path != worker.loaded_path" in finish_source
    assert "previous_blob=current" in finish_source
    assert "entry.previous_blob" in undo_source


def test_blackstar_completion_uses_worker_refresh_without_unreported_repairs() -> None:
    finish_source = _method_source("_finish_blackstar_unlock")
    refresh_source = _method_source("_apply_blackstar_refreshed_items")
    assert "_scan_and_populate" not in finish_source
    assert "_apply_blackstar_refreshed_items" in finish_source
    assert "_fix_duplicate_item_nos" not in refresh_source
    assert "_deferred_parc_enrich" not in refresh_source
