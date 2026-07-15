from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

import crimson_rs
from dragon_wheel_patch import CURRENT_PROFILE, enable_dragon_category


class _NoOpCoordinator:
    @staticmethod
    def pre_write(game_path: str, group: str, owner: str):
        return True, "OK"

    @staticmethod
    def post_write(
        game_path: str,
        group: str,
        content: str,
        files: list[str],
        owner: str,
    ) -> None:
        return None

    @staticmethod
    def pre_restore(game_path: str, group: str, owner: str):
        return True, "OK"

    @staticmethod
    def post_restore(game_path: str, group: str) -> None:
        return None


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


@pytest.mark.skipif(
    not os.environ.get("CRIMSON_DESERT_GAME_PATH"),
    reason="Set CRIMSON_DESERT_GAME_PATH for copied-game transaction verification",
)
def test_real_crimson_rs_transaction_runs_only_in_copied_game_tree(
    tmp_path: Path,
) -> None:
    from dragon_wheel_deploy import deploy_dragon_wheel, restore_dragon_wheel

    installed_game = Path(os.environ["CRIMSON_DESERT_GAME_PATH"])
    copied_game = tmp_path / "copied-game-tree"
    (copied_game / "meta").mkdir(parents=True)
    shutil.copy2(installed_game / "meta" / "0.papgt", copied_game / "meta" / "0.papgt")

    original_document = crimson_rs.parse_papgt_file(
        str(copied_game / "meta" / "0.papgt")
    )
    original_groups = tuple(
        entry["group_name"] for entry in original_document.get("entries", [])
    )
    assert "0067" not in original_groups

    internal_dir = "gamedata/binary__/client/bin"
    pabgh = bytes(
        crimson_rs.extract_file(
            str(installed_game), "0008", internal_dir, "reserveslot.pabgh"
        )
    )
    pabgb = bytes(
        crimson_rs.extract_file(
            str(installed_game), "0008", internal_dir, "reserveslot.pabgb"
        )
    )
    candidate = enable_dragon_category(pabgh, pabgb)

    receipt = deploy_dragon_wheel(
        copied_game,
        "0067",
        candidate,
        tmp_path / "backups",
        crimson_rs,
        "20260715-transaction-test",
        _NoOpCoordinator(),
    )

    assert receipt.papgt_groups_before == original_groups
    assert receipt.papgt_groups_after.count("0067") == 1
    assert tuple(
        group for group in receipt.papgt_groups_after if group != "0067"
    ) == original_groups
    assert bytes(
        crimson_rs.extract_file(
            str(copied_game), "0067", internal_dir, "reserveslot.pabgh"
        )
    ) == candidate.pabgh
    assert bytes(
        crimson_rs.extract_file(
            str(copied_game), "0067", internal_dir, "reserveslot.pabgb"
        )
    ) == candidate.pabgb

    remaining = restore_dragon_wheel(
        copied_game,
        "0067",
        crimson_rs,
        _NoOpCoordinator(),
    )

    assert remaining == original_groups
    assert not (copied_game / "0067").exists()
