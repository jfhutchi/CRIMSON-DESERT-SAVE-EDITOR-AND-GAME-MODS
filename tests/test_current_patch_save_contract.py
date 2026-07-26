"""End-to-end contracts against a real current-patch (2026-07) player save.

The slot104 fixture is a contributed save from the live 2026-07 game patch —
the schema generation that shipped after every other fixture. It pins the
behavior players actually hit today: the enrolled community-2026-07-patch
profile, parse-tree item extraction across all thirteen bags, exact-offset
editing, byte-identical serialization, PARC enrichment, and Blackstar
classification. Every test operates on temporary copies.
"""
from __future__ import annotations

import shutil
import struct

import pytest

import save_crypto
from item_scanner import apply_stack_edit, enrich_items_with_parc, scan_items_smart
from save_parser import build_result_from_raw

EXPECTED_BAGS = {
    'Money': 15, 'Character': 204, 'Quest': 122, 'CampWarehouse': 253,
    'Warehouse': 23, 'Bank': 50, 'CampStraw': 4, 'Kuku': 165, 'Invisible': 3,
    'Bag_15': 92, 'Bag_16': 27, 'Bag_18': 91, 'Bag_19': 89,
}


@pytest.fixture(scope="module")
def loaded(current_patch_save_path, tmp_path_factory):
    dest = tmp_path_factory.mktemp("current-patch") / "save.save"
    shutil.copy2(current_patch_save_path, dest)
    return save_crypto.load_save_file(str(dest))


@pytest.fixture(scope="module")
def parse_result(loaded):
    return build_result_from_raw(
        bytes(loaded.decompressed_blob), {'input_kind': 'raw_blob'}
    )


@pytest.fixture(scope="module")
def smart_items(loaded, parse_result):
    return scan_items_smart(loaded.decompressed_blob, parse_result)


def test_current_patch_save_is_supported_and_writable(loaded) -> None:
    assert loaded.is_schema_supported, (
        "the community-2026-07-patch profile must keep current-patch saves "
        "writable"
    )
    assert loaded.compatibility_profile_id == "community-2026-07-patch"
    assert loaded.schema_identity.container_version == 2


def test_smart_scan_extracts_the_complete_inventory(smart_items) -> None:
    assert len(smart_items) == 1416, (
        "the pattern scanner alone surfaced 375 of these items"
    )
    assert all(i.parc_parsed for i in smart_items), (
        "every item comes from the parse tree, not signature guessing"
    )
    from collections import Counter

    sources = Counter(i.source for i in smart_items)
    assert sources["Equipment"] == 19
    assert sources["Mercenary"] == 259
    bags = dict(Counter(i.bag for i in smart_items if i.bag))
    assert bags == EXPECTED_BAGS


def test_every_parsed_item_keeps_the_editor_offset_contract(
    loaded, smart_items
) -> None:
    raw = bytes(loaded.decompressed_blob)
    parsed = [i for i in smart_items if i.parc_parsed and i.field_offsets]
    assert len(parsed) >= 1157
    for item in parsed:
        assert struct.unpack_from("<I", raw, item.offset + 12)[0] == item.item_key
        assert item.field_offsets.get("_itemKey") == item.offset + 12


def test_serialization_round_trip_is_byte_identical(loaded, tmp_path) -> None:
    original = bytes(loaded.decompressed_blob)
    serialized = save_crypto.serialize_save_bytes(
        original, loaded.raw_header, "current-patch-roundtrip"
    )
    out = tmp_path / "roundtrip.save"
    out.write_bytes(serialized)
    reloaded = save_crypto.load_save_file(str(out))
    assert bytes(reloaded.decompressed_blob) == original
    assert reloaded.is_schema_supported


def test_stack_edits_hit_previously_invisible_items(loaded, smart_items) -> None:
    original = bytes(loaded.decompressed_blob)
    for bag_name in ("CampWarehouse", "Bank", "Kuku"):
        item = next(
            i for i in smart_items
            if i.bag == bag_name and i.parc_parsed and i.stack_count >= 1
        )
        working = bytearray(original)
        old_bytes = apply_stack_edit(working, item, item.stack_count + 7)
        assert struct.unpack_from("<q", working, item.offset + 18)[0] == (
            item.stack_count
        ), "apply_stack_edit updates the item in place"
        working[item.offset + 18:item.offset + 26] = old_bytes
        item.stack_count -= 7
        assert bytes(working) == original, (
            f"{bag_name}: reverting the edit must restore the exact save"
        )


def test_parc_enrichment_completes_with_progress(loaded, smart_items) -> None:
    calls: list[tuple[int, int]] = []
    enriched, status = enrich_items_with_parc(
        loaded.decompressed_blob, list(smart_items), lambda s, t: calls.append((s, t))
    )
    assert status.startswith("PARC mode")
    assert calls, "the GUI progress callable must be invoked"


def test_root_data_blocks_parse_with_expected_shapes(parse_result) -> None:
    by_class = {}
    for obj in parse_result['objects']:
        for f in obj.fields:
            if f.list_elements:
                by_class[f"{obj.class_name}.{f.name}"] = len(f.list_elements)

    assert by_class["KnowledgeSaveData._list"] == 4151
    assert by_class["FactionSaveData._factionElementSaveDataList"] == 135
    assert by_class["FactionSaveData._factionNodeElementSaveDataList"] == 1119
    assert by_class["EquipmentSaveData._list"] == 19
    assert by_class["MercenaryClanSaveData._mercenaryDataList"] == 160


def test_blackstar_classification_recognizes_the_save(loaded) -> None:
    from blackstar_unlock import _classify
    from parc_inserter3 import build_insert_context

    context = build_insert_context(bytearray(loaded.decompressed_blob))
    status, _found = _classify(context)
    assert status in {"absent", "legitimate_idle", "legitimate_active", "legacy"}
