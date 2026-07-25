"""UI feedback contracts from hands-on testing of the redesigned editor.

1. The editor must never auto-load the previous save at startup: a stale save
   silently reopened can lead to editing and writing outdated data. The user
   opens a save explicitly each session.
2. The inventory sub-tabs (All / Equipment / Quest / Camp Warehouse / ...)
   fill in the background after a load; each tab label must read
   "(loading...)" until real counts replace it, so switching tabs during
   population is never a guessing game.
3. The upper-right shell command buttons must show text labels under their
   icons — icon-only buttons proved undiscoverable.
"""
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


def test_startup_never_auto_loads_a_save() -> None:
    segment = _method_source(
        ROOT / "CrimsonSaveEditor" / "gui.py", "MainWindow", "__init__"
    )
    assert "self._load_save(" not in segment, (
        "the editor must not reopen the previous save automatically; the "
        "user opens a save fresh each session so stale data is never edited"
    )


def test_inventory_subtabs_show_loading_state() -> None:
    path = ROOT / "CrimsonSaveEditor" / "gui.py"
    setter = _method_source(path, "MainWindow", "_set_inv_subtabs_loading")
    assert "loading" in setter.lower()

    populate = _method_source(path, "MainWindow", "_populate_scanned_items")
    assert "_set_inv_subtabs_loading(" in populate, (
        "background population must mark the sub-tabs as loading"
    )

    counts = _method_source(path, "MainWindow", "_update_inv_subtab_counts")
    assert "not self._items" not in counts, (
        "the count refresh must always rewrite tab labels, otherwise a "
        "zero-item save would leave '(loading...)' stuck on every tab"
    )


def test_dye_swatch_cell_shows_color_not_hex_text() -> None:
    segment = _method_source(
        ROOT / "CrimsonSaveEditor" / "gui.py", "MainWindow", "_dye_refresh_parts"
    )
    assert "swatch.setBackground(" in segment
    assert "swatch.setText(" not in segment, (
        "hex text painted over the swatch hides the actual color (near-black "
        "dyes read as empty cells); the cell must be the color itself with "
        "the hex in a tooltip"
    )
    assert "swatch.setToolTip(" in segment


def test_shell_utility_buttons_show_labels_under_icons() -> None:
    source = (ROOT / "crimson_common" / "crimson_shell.py").read_text(
        encoding="utf-8-sig"
    )
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_utility_button":
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            assert "ToolButtonTextUnderIcon" in segment, (
                "the upper-right command buttons must label their icons"
            )
            assert "ToolButtonIconOnly" not in segment
            return
    raise AssertionError("_utility_button not found in crimson_shell.py")
