import struct
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import QTimer

from gui_method_loader import load_method
import importlib
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "CrimsonGameMods" / "item_scanner.py"

def _load_item_scanner():
    module_name = "_test_gamemods_item_scanner"
    previous_models = sys.modules.pop("models", None)
    sys.path.insert(0, str(MODULE_PATH.parent))
    try:
        spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)
        sys.modules.pop("models", None)
        if previous_models is not None:
            sys.modules["models"] = previous_models





def test_loading_duplicate_item_numbers_preserves_blob_and_dirty_state(monkeypatch):
    scanner = _load_item_scanner()
    blob = bytearray(128)
    struct.pack_into("<q", blob, 4, 10)
    struct.pack_into("<q", blob, 68, 10)
    original = bytes(blob)
    items = [scanner.SaveItem(offset=0, item_no=10), scanner.SaveItem(offset=64, item_no=10)]
    namespace = {
        "scan_items": lambda data: items,
        "apply_itemno_edit": scanner.apply_itemno_edit,
        "get_max_itemno": scanner.get_max_itemno,
    }
    source = "CrimsonGameMods/gui/main_window.py"
    repair = load_method(source, "MainWindow", "_fix_duplicate_item_nos", namespace)
    scan = load_method(source, "MainWindow", "_scan_and_populate", namespace)
    owner = SimpleNamespace(
        _save_data=SimpleNamespace(decompressed_blob=blob), _items=[],
        _name_db=Mock(), _dirty=False, _update_status=Mock(),
        _loaded_tabs=set(), _status_parc_label=Mock(), _parc_progress=Mock(),
        _deferred_parc_enrich=Mock(),
    )
    owner._fix_duplicate_item_nos = lambda: repair(owner)
    monkeypatch.setattr(QTimer, "singleShot", lambda *args: None)
    scan(owner)
    assert bytes(blob) == original
    assert [item.item_no for item in owner._items] == [10, 10]
    assert owner._dirty is False
