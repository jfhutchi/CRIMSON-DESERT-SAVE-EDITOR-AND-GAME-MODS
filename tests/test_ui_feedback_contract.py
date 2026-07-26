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


def test_already_unlocked_blackstar_offers_the_cooldown_panel() -> None:
    path = ROOT / "CrimsonSaveEditor" / "gui.py"
    segment = _method_source(path, "MainWindow", "_finish_blackstar_unlock")
    assert "classification_before" in segment
    assert "_focus_blackstar_timer_panel(" in segment, (
        "an already-unlocked save must be offered the reduced-cooldown "
        "(Blackstar Game Settings) panel instead of dead-ending"
    )
    helper = _method_source(path, "MainWindow", "_focus_blackstar_timer_panel")
    assert "ensureWidgetVisible" in helper


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


def test_mod_editor_parity_with_save_editor() -> None:
    gm_root = ROOT / "CrimsonGameMods"
    window = (gm_root / "gui" / "main_window.py").read_text(encoding="utf-8-sig")

    assert "scan_items_smart(" in window, (
        "Mod Editor item views must use parse-tree extraction, not the lossy "
        "pattern scan that leaves bag tabs empty"
    )
    assert "QTimer.singleShot(0, lambda: self._load_save(last_path))" not in window, (
        "never auto-load the previous save at launch; it is stale after play"
    )
    assert 'self._config.get("show_icons", False)' in window, (
        "icons are opt-in; the remembered config key turns them back on"
    )
    assert "_start_icon_warm(" in window

    scanner = (gm_root / "item_scanner.py").read_text(encoding="utf-8-sig")
    assert "def scan_items_smart(" in scanner
    assert "def scan_items_from_parse(" in scanner

    # One shared icon cache, not per-app copies: drift between duplicates is
    # what caused the stale has_icon and thread-safety bugs.
    assert (ROOT / "crimson_common" / "icon_cache.py").is_file()
    assert not (gm_root / "icon_cache.py").exists()
    assert not (ROOT / "CrimsonSaveEditor" / "icon_cache.py").exists()


def test_repopulates_cancel_superseded_row_jobs() -> None:
    path = ROOT / "CrimsonSaveEditor" / "gui.py"
    for method_name in (
        "_populate_scanned_items",
        "_populate_inventory",
        "_populate_equipment",
    ):
        segment = _method_source(path, "MainWindow", method_name)
        assert "_cancel_population_job(" in segment, (
            f"{method_name}: a superseded incremental job kept writing rows "
            "by index into a freshly refilled table, dropping or mixing items"
        )

    enrich = _method_source(path, "MainWindow", "_finish_parc_enrich")
    assert "completed=_after_refresh" not in enrich, (
        "post-enrich refresh work must not ride on a population completion "
        "callback that a superseding populate can cancel"
    )


def test_blocking_task_helper_pairs_worker_with_modal_progress() -> None:
    # The implementation is shared by both apps from crimson_common.
    shared = (ROOT / "crimson_common" / "progress_ui.py").read_text(
        encoding="utf-8-sig"
    )
    assert "start_gui_task" in shared, "the work must leave the GUI thread"
    assert "QProgressDialog" in shared, "the user must see a busy dialog"
    assert "WindowModal" in shared, (
        "interaction must be blocked while save bytes are being rewritten"
    )
    gm = (ROOT / "CrimsonGameMods" / "gui" / "main_window.py").read_text(
        encoding="utf-8-sig"
    )
    assert "download_icons_with_progress(" in gm, (
        "the Mod Editor icon download must show the shared progress bar"
    )


def test_long_mutations_and_scans_show_progress_dialogs() -> None:
    path = ROOT / "CrimsonSaveEditor" / "gui.py"
    for method_name in ("_know_inject_keys", "_qe_scan_slots"):
        segment = _method_source(path, "MainWindow", method_name)
        assert "run_blocking_task(" in segment, (
            f"{method_name} froze the GUI with no feedback; long operations "
            "run behind the shared modal progress helper"
        )
        assert "QApplication.processEvents" not in segment, method_name


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
            break
    else:
        raise AssertionError("_utility_button not found in crimson_shell.py")

    theme = (ROOT / "crimson_common" / "crimson_theme.py").read_text(
        encoding="utf-8-sig"
    )
    rule = theme.split("QToolButton#shellUtilityButton", 1)[1][:400]
    assert "max-width: 34px" not in rule, (
        "a 34px width cap elides the labels to 'S...S'; the buttons must be "
        "wide enough for their full text"
    )
    assert "min-width: 52px" in rule
