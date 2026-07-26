"""Both apps must extract identical items from the same save.

The Save Editor and Mod Editor carry parallel item_scanner copies. When they
drift, the Mod Editor silently shows fewer items or mislabels bags — which is
exactly how it shipped "Consumables" where the game says "Camp Warehouse".
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def gamemods_scanner():
    # Import the Save Editor modules first: both apps ship a `models` module,
    # and whichever loads first wins for the whole process.
    import models  # noqa: F401
    import save_crypto  # noqa: F401

    path = str(ROOT / "CrimsonGameMods")
    sys.path.insert(0, path)
    try:
        spec = importlib.util.spec_from_file_location(
            "gamemods_item_scanner", ROOT / "CrimsonGameMods" / "item_scanner.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(path)
    return module


def test_both_scanners_agree_on_a_real_save(
    current_patch_save_path, gamemods_scanner, tmp_path
):
    import save_crypto
    from item_scanner import scan_items_smart

    dest = tmp_path / "save.save"
    shutil.copy2(current_patch_save_path, dest)
    blob = save_crypto.load_save_file(str(dest)).decompressed_blob

    editor = scan_items_smart(blob)
    mods = gamemods_scanner.scan_items_smart(blob)

    assert len(editor) == len(mods)
    assert {i.offset for i in editor} == {i.offset for i in mods}
    assert Counter(i.bag for i in editor) == Counter(i.bag for i in mods)
    assert Counter(i.source for i in editor) == Counter(i.source for i in mods)


def test_bag_names_match_the_game_ui(gamemods_scanner):
    from item_scanner import BAG_KEY_NAMES

    assert gamemods_scanner._BAG_KEY_NAMES == BAG_KEY_NAMES
