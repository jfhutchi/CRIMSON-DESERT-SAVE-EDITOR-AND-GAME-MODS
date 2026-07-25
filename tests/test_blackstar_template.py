from __future__ import annotations

import hashlib

from blackstar_template import (
    DYNAMIC_SLICES,
    NORMALIZED_BLACKSTAR_TEMPLATE,
    BlackstarDynamicValues,
    materialize_blackstar_template,
)
from parc_inserter3 import build_insert_context
from save_crypto import load_save_file


def test_normalized_template_contract() -> None:
    assert len(NORMALIZED_BLACKSTAR_TEMPLATE) == 437
    assert hashlib.sha256(NORMALIZED_BLACKSTAR_TEMPLATE).hexdigest() == (
        "a65b7d3bc22b1c83dc1eb30be85263def6dd682af8023851f1056ec7ea5841b2"
    )
    assert set(DYNAMIC_SLICES) == {
        "mercenary_no", "owner_key", "last_paid_time", "last_breeding_time",
        "spawn_position", "spawn_yaw", "spawn_field_key", "item_no",
    }


def test_materializer_patches_target_values(early_114_save_path) -> None:
    save = load_save_file(str(early_114_save_path))
    context = build_insert_context(save.decompressed_blob)
    record = materialize_blackstar_template(
        context,
        123456,
        BlackstarDynamicValues(
            mercenary_no=1000003, owner_key=1,
            last_paid_time=7, last_breeding_time=7,
            spawn_position=bytes(range(12)), spawn_yaw=b"\x01\x02\x03\x04",
            spawn_field_key=1, item_no=1000004,
        ),
    )
    assert int.from_bytes(record[31:39], "little") == 1000003
    assert int.from_bytes(record[232:240], "little") == 1000004
    assert record[163:175] == bytes(range(12))
