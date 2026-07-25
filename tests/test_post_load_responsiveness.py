"""Regression contracts for broken PARC enrichment in the Save Editor.

Both GUIs pass a progress callable to ``enrich_items_with_parc`` from their
background load workers, but only the Game Mods copy of ``item_scanner``
accepted it. Every Save Editor load raised ``TypeError`` inside the worker and
silently fell back to legacy pattern scanning.
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
