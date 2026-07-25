"""Contracts for reusing one full save parse across Save Editor handlers.

A full ``build_result_from_raw`` pass over the 6.4 MB decompressed blob costs
about five seconds. Before these contracts, ~18 button and tab handlers each
re-ran it on the GUI thread against the unchanged blob. The parsed result only
carries structure (offsets); values are always re-read from the current blob,
so one parse stays valid until ``decompressed_blob`` is wholesale replaced —
which every structural edit in gui.py does by assignment.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CONVERTED_HANDLERS = {
    "_populate_bonds",
    "_populate_sublevels",
    "_preparse_quests",
    "_qe_load",
    "_qe_diagnose",
    "_qe_health_check",
    "_community_scan_loaded",
    "_background_template_scan",
    "_next_merc_no",
    "_view_entitlements",
}


def _method_sources(path: Path, class_name: str, method_names: set[str]) -> dict[str, str]:
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    found: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name in method_names:
                    segment = ast.get_source_segment(source, child)
                    assert segment is not None
                    found[child.name] = segment
    return found


def test_savedata_bumps_parse_epoch_on_blob_replacement() -> None:
    from models import SaveData

    sd = SaveData(source_file_sha256="x", decompressed_blob=bytearray(b"abc"))
    start = sd.parse_epoch

    sd.decompressed_blob[0:1] = b"z"
    assert sd.parse_epoch == start, "in-place edits keep offsets valid"

    sd.decompressed_blob = bytearray(b"structurally different")
    assert sd.parse_epoch == start + 1, "replacement must invalidate parses"


def test_parsed_result_cache_hits_until_blob_replaced() -> None:
    from models import SaveData
    from parse_reuse import ParsedResultCache

    sd = SaveData(source_file_sha256="x", decompressed_blob=bytearray(b"abc"))
    cache = ParsedResultCache()
    assert cache.get(sd) is None

    sentinel = {"objects": []}
    cache.store(sd, sentinel)
    assert cache.get(sd) is sentinel

    sd.decompressed_blob[0] = 0x7A
    assert cache.get(sd) is sentinel, "in-place edit must not evict"

    sd.decompressed_blob = bytearray(b"other")
    assert cache.get(sd) is None, "replacement must evict"

    cache.store(sd, sentinel)
    other = SaveData(source_file_sha256="y", decompressed_blob=bytearray(b"abc"))
    assert cache.get(other) is None, "a different save never hits"
    assert cache.get(None) is None


def test_game_map_names_parse_only_once() -> None:
    from parse_reuse import load_game_map_names

    first = load_game_map_names()
    assert first is load_game_map_names(), (
        "game_map.json is ~22 MB; it must be parsed once per process"
    )
    assert set(first) == {"factions", "factionnodes", "characters", "sublevels"}
    assert first["factions"], "known game data must actually load"


def test_common_handlers_reuse_the_shared_parse() -> None:
    path = ROOT / "CrimsonSaveEditor" / "gui.py"
    sources = _method_sources(path, "MainWindow", CONVERTED_HANDLERS)
    assert set(sources) == CONVERTED_HANDLERS

    for name, segment in sources.items():
        assert "_get_parse_result(" in segment, (
            f"{name} must reuse the shared parse instead of re-decoding the "
            "whole save on the GUI thread"
        )
        assert "build_result_from_raw(" not in segment, name


def test_faction_worker_populates_the_shared_parse_cache() -> None:
    path = ROOT / "CrimsonSaveEditor" / "gui.py"
    sources = _method_sources(path, "MainWindow", {"_populate_faction_tab"})
    segment = sources["_populate_faction_tab"]
    assert "_parse_cache" in segment, (
        "the post-load background parse must seed the shared cache so the "
        "first user action after load is instant"
    )


def test_offset_position_lookups_avoid_quadratic_index() -> None:
    path = ROOT / "CrimsonSaveEditor" / "gui.py"
    sources = _method_sources(
        path, "MainWindow", {"_field_edit_load", "_spawn_extract"}
    )
    assert set(sources) == {"_field_edit_load", "_spawn_extract"}
    for name, segment in sources.items():
        assert "sorted_offs.index(" not in segment, (
            f"{name}: list.index inside the entry loop is O(n^2); "
            "precompute an offset->position dict"
        )
        assert "vsorted.index(" not in segment, name
