from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
GAME_MODS = ROOT / "CrimsonGameMods"
if str(GAME_MODS) not in sys.path:
    sys.path.insert(0, str(GAME_MODS))

from PySide6.QtWidgets import QApplication

from crimson_common.crimson_icons import game_art_icon, resolve_game_art, symbol_icon


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_blackstar_game_art_resolves_from_the_checked_in_portrait_library() -> None:
    art = resolve_game_art(1000799)

    assert art == ROOT / "icons_mercenary" / "1000799.webp"
    assert art.is_file()


def test_shared_symbol_and_game_art_icons_render_in_offscreen_qt() -> None:
    _application()

    for name in ("save", "mounts", "inventory", "world", "mods", "menu", "path"):
        assert not symbol_icon(name).isNull()
    assert not game_art_icon(1000799).isNull()
