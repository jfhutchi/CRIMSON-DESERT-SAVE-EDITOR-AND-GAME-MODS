from __future__ import annotations

import os

import pytest

import crimson_rs
from dragon_wheel_patch import CURRENT_PROFILE, enable_dragon_category


@pytest.mark.skipif(
    not os.environ.get("CRIMSON_DESERT_GAME_PATH"),
    reason="Set CRIMSON_DESERT_GAME_PATH for read-only installed-file verification",
)
def test_installed_reserveslot_builds_expected_candidate_without_writing() -> None:
    game_path = os.environ["CRIMSON_DESERT_GAME_PATH"]
    internal_dir = "gamedata/binary__/client/bin"

    pabgh = bytes(
        crimson_rs.extract_file(
            game_path,
            "0008",
            internal_dir,
            "reserveslot.pabgh",
        )
    )
    pabgb = bytes(
        crimson_rs.extract_file(
            game_path,
            "0008",
            internal_dir,
            "reserveslot.pabgb",
        )
    )

    result = enable_dragon_category(pabgh, pabgb)

    assert result.report.schema_id == CURRENT_PROFILE.schema_id
    assert result.report.before_categories == (0x4E, 0x51)
    assert result.report.after_categories == (0x4E, 0x4F, 0x51)
    assert result.report.output_pabgh_sha256 == CURRENT_PROFILE.patched_pabgh_sha256
    assert result.report.output_pabgb_sha256 == CURRENT_PROFILE.patched_pabgb_sha256
