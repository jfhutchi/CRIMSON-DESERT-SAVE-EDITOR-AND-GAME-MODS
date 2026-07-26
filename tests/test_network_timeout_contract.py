"""Downloads must never be able to hang the window forever.

urlretrieve accepts no timeout argument, so the language- and name-pack
downloads could block on a stalled server indefinitely. Both entry points set
a default socket timeout, which every urllib call inherits.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "entry", ["CrimsonSaveEditor/main.py", "CrimsonGameMods/main.py"]
)
def test_entry_point_sets_a_default_socket_timeout(entry: str) -> None:
    tree = ast.parse((ROOT / entry).read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "setdefaulttimeout"
            and node.args
        ):
            assert 0 < node.args[0].value <= 60
            return
    raise AssertionError(f"{entry} must set socket.setdefaulttimeout()")
