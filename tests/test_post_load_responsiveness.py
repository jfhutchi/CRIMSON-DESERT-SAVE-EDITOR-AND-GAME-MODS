"""Regression contracts for the post-load freeze and broken PARC enrichment.

Defects covered:
1. Both GUIs pass a progress callable to ``enrich_items_with_parc`` but only
   the Game Mods copy of ``item_scanner`` accepted it, so Save Editor
   background enrichment failed with ``TypeError`` on every load and silently
   fell back to legacy scanning.
2. ``MainWindow._populate_faction_tab`` ran three full ``build_result_from_raw``
   parses synchronously on the GUI thread (factions, bonds, sublevels), freezing
   the event loop for many seconds immediately after a save finished loading.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _function_args(path: Path, function_name: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return [arg.arg for arg in node.args.args]
    raise AssertionError(f"Missing {function_name} in {path}")


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


def test_enrich_items_with_parc_accepts_the_gui_progress_callable() -> None:
    from item_scanner import enrich_items_with_parc

    calls: list[tuple[int, int]] = []
    enriched, status = enrich_items_with_parc(
        b"\x00" * 64, [], lambda step, total: calls.append((step, total))
    )
    assert enriched == 0
    assert isinstance(status, str)

    enriched, status = enrich_items_with_parc(b"\x00" * 64, [])
    assert enriched == 0
    assert isinstance(status, str)


def test_both_item_scanner_copies_share_the_enrichment_signature() -> None:
    editor_args = _function_args(
        ROOT / "CrimsonSaveEditor" / "item_scanner.py", "enrich_items_with_parc"
    )
    mods_args = _function_args(
        ROOT / "CrimsonGameMods" / "item_scanner.py", "enrich_items_with_parc"
    )
    assert editor_args == mods_args
    assert len(editor_args) == 3, (
        "enrich_items_with_parc must accept (data, items, progress) because both "
        "GUIs pass a positional progress callable from the background worker"
    )


def test_faction_tab_population_parses_off_the_gui_thread() -> None:
    path = ROOT / "CrimsonSaveEditor" / "gui.py"
    method = _method_source(path, "MainWindow", "_populate_faction_tab")

    assert "start_gui_task" in method, (
        "_populate_faction_tab must run build_result_from_raw on a background "
        "worker; running it synchronously froze the GUI thread for the length "
        "of three full save parses right after every load"
    )
    assert "QApplication.processEvents" not in method


def test_faction_worker_parses_the_save_once_for_all_three_tables() -> None:
    path = ROOT / "CrimsonSaveEditor" / "gui.py"
    method = _method_source(path, "MainWindow", "_populate_faction_tab")

    assert method.count("build_result_from_raw(") == 1, (
        "the faction, bond, and sublevel tables must share one parsed result "
        "instead of decoding the whole save three times"
    )
    assert "_populate_bonds()" not in method
    assert "_populate_sublevels()" not in method
