from __future__ import annotations

import ast
from pathlib import Path

GUI_PATH = Path(__file__).resolve().parents[1] / "CrimsonSaveEditor" / "gui.py"


def _source() -> str:
    return GUI_PATH.read_text(encoding="utf-8")


def _methods(name: str) -> list[str]:
    source = _source()
    tree = ast.parse(source)
    return [
        ast.get_source_segment(source, node) or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]


def test_main_save_requires_known_schema_and_mandatory_transactional_backup() -> None:
    method = _methods("_do_save")[0]
    assert "is_schema_supported" in method
    assert "transactional_write_save(" in method
    assert "backup_source=self._loaded_path" in method
    assert "expected_identity=self._save_data.schema_identity" in method
    assert "verified backup is mandatory" in method
    assert '"Backup Save?"' not in method


def test_quest_editor_uses_the_same_safe_writer() -> None:
    quest_save, main_save = _methods("_save_file")
    assert "transactional_write_save(" in quest_save
    assert "backup_source=self._save_path" in quest_save
    assert "is_schema_supported" in quest_save
    assert "transactional_write_save(" not in main_save
    assert "write_save_file(" not in _source()


def test_load_applies_read_only_schema_controls() -> None:
    load_source = _methods("_load_save")[0]
    controls_source = _methods("_update_schema_write_controls")[0]
    assert "load_save_file(path)" in load_source
    assert "_update_schema_write_controls()" in load_source
    assert "is_schema_supported" in controls_source
    assert "_save_action" in controls_source
    assert "_save_as_action" in controls_source
    assert "_blackstar_btn" in controls_source


def test_unknown_full_schema_notice_is_non_blocking_and_feature_scoped() -> None:
    load_source = _methods("_load_save")[0]
    assert "QMessageBox.warning" not in load_source
    assert "General Save disabled" in load_source
    assert "Blackstar Preview uses its own compatibility check" in load_source
    assert "writing and Blackstar changes are disabled" not in load_source


def test_blackstar_has_preview_bound_atomic_apply() -> None:
    start = _methods("_start_blackstar_unlock")[0]
    finish = _methods("_finish_blackstar_unlock")[0]
    controls = _methods("_update_schema_write_controls")[0]
    assert "_blackstar_preview_token" in start
    assert "Apply is enabled only" in start
    assert "make_blackstar_apply_token" in finish
    assert "worker_result.write_result" in finish
    assert "not self._save_data.is_raw_stream" in controls
    assert "save with Ctrl+S" not in start + finish
    label = _methods("_update_blackstar_mode_label")[0]
    assert "Preview Blackstar" in label
    assert "Apply & Save Blackstar" in label
    assert "_blackstar_preview_token = None" in _methods("_load_save")[0]
