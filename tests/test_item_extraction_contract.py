"""Contracts for parse-based item extraction.

The legacy pattern scanner recognizes item records by byte signature and has
always under-reported: slot100 holds 1,329 nested inventory/equipment records
but the scanner surfaced 1,026; on 1.14+ saves it degrades to ~32%, leaving
bag tabs (Camp Warehouse, Bank, ...) empty even though the items exist. The
save's parse tree lists every container (`InventorySaveData._inventorylist ->
_itemList`) and equipped piece (`EquipmentSaveData._list`) with exact field
offsets, and every record keeps the classic fixed deltas (_itemNo at +4,
_itemKey at +12, _slotNo at +16, _stackCount at +18) that the editing code
depends on — verified across 3,687 records in three save generations.
"""
from __future__ import annotations

import ast
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "CrimsonSaveEditor") not in sys.path:
    sys.path.insert(0, str(ROOT / "CrimsonSaveEditor"))


@pytest.fixture(scope="module")
def loaded_slot100(copied_save_module):
    return copied_save_module


@pytest.fixture(scope="module")
def copied_save_module(tmp_path_factory):
    import shutil

    import save_crypto

    source = ROOT / "tests" / "fixtures" / "slot100" / "save.save"
    dest = tmp_path_factory.mktemp("smart-scan") / "save.save"
    shutil.copy2(source, dest)
    return save_crypto.load_save_file(str(dest))


def test_smart_scan_finds_the_nested_container_items(copied_save_module) -> None:
    from item_scanner import scan_items, scan_items_smart

    blob = copied_save_module.decompressed_blob
    legacy = scan_items(blob)
    smart = scan_items_smart(blob)

    assert len(smart) > len(legacy), (
        "parse-based extraction must surface the nested _itemList records "
        "the pattern scanner misses"
    )
    assert len(smart) >= 1300, "slot100 holds 1,329 nested records plus extras"

    bags = {i.bag for i in smart if i.bag}
    assert "CampWarehouse" in bags
    assert "Bank" in bags
    equipment = [i for i in smart if i.source == "Equipment"]
    assert len(equipment) >= 10
    assert any(i.source == "Mercenary" for i in smart), (
        "legacy-only sources outside the parsed containers must be kept"
    )


def test_smart_scan_items_keep_editor_offset_contract(copied_save_module) -> None:
    from item_scanner import scan_items_smart

    blob = copied_save_module.decompressed_blob
    raw = bytes(blob)
    smart = scan_items_smart(blob)

    parsed = [i for i in smart if i.parc_parsed and i.field_offsets]
    assert len(parsed) >= 1300

    for item in parsed[:400]:
        assert struct.unpack_from("<I", raw, item.offset + 12)[0] == item.item_key, (
            "editors write _itemKey at offset+12; record start must preserve "
            "the fixed-delta layout"
        )
        assert item.field_offsets.get("_itemKey") == item.offset + 12
        assert item.field_offsets.get("_stackCount") == item.offset + 18


def test_load_path_uses_smart_scan_with_shared_parse() -> None:
    source = (ROOT / "CrimsonSaveEditor" / "gui.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "MainWindow":
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == "_load_save":
                    segment = ast.get_source_segment(source, child)
                    assert segment is not None
                    assert "scan_items_smart(" in segment, (
                        "loading must extract items from the parse tree, not "
                        "the lossy pattern scan"
                    )
                    assert "_parse_cache.store(" in segment, (
                        "the load-time parse must seed the shared cache so "
                        "the faction worker and handlers reuse it"
                    )
                    return
    raise AssertionError("MainWindow._load_save not found")
