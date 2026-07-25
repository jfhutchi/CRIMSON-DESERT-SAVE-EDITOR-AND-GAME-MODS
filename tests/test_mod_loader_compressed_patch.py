from __future__ import annotations

import random
from pathlib import Path

import crimson_rs
import lz4.block

from blackstar_timer_archive import make_timer_archive
from mod_loader import CommunityModLoader, ModChange, ModPatch


def _entry(pamt: dict) -> dict:
    matches = [
        entry
        for directory in pamt["directories"]
        for entry in directory["files"]
        if directory["path"] == "gamedata"
        and entry["name"] == "characterinfo.pabgb"
    ]
    assert len(matches) == 1
    return matches[0]


def test_generic_compressed_patch_persists_actual_stream_length(
    tmp_path: Path,
) -> None:
    archive = make_timer_archive(tmp_path)
    random_body = random.Random(114).randbytes(archive.body_size)
    archive.rebuild(random_body)
    pamt_path = archive.game_dir / "0008" / "0.pamt"
    paz_path = archive.game_dir / "0008" / "0.paz"
    before_pamt = crimson_rs.parse_pamt_file(str(pamt_path))
    before_entry = _entry(before_pamt)
    offset = 512
    old = random_body[offset:offset + 2048]
    new = b"\x00" * len(old)
    candidate = bytearray(random_body)
    candidate[offset:offset + len(new)] = new
    expected_stream = lz4.block.compress(
        bytes(candidate), mode="high_compression", store_size=False
    )
    assert len(expected_stream) < before_entry["compressed_size"]
    patch = ModPatch(
        game_file="gamedata/characterinfo.pabgb",
        changes=[ModChange(offset, old.hex(), new.hex(), "test change")],
        paz_path=str(paz_path),
        paz_base_offset=before_entry["chunk_offset"],
        compressed=True,
        comp_size=before_entry["compressed_size"],
        orig_size=before_entry["uncompressed_size"],
    )

    applied, message = CommunityModLoader(str(archive.game_dir))._apply_compressed_patch(
        patch
    )

    assert applied == 1, message
    after_pamt = crimson_rs.parse_pamt_file(str(pamt_path))
    after_entry = _entry(after_pamt)
    assert after_entry["compressed_size"] == len(expected_stream)
    paz_bytes = paz_path.read_bytes()
    declared = paz_bytes[
        after_entry["chunk_offset"]:
        after_entry["chunk_offset"] + after_entry["compressed_size"]
    ]
    assert lz4.block.decompress(
        declared, uncompressed_size=after_entry["uncompressed_size"]
    ) == bytes(candidate)
    assert after_pamt["chunks"][0]["checksum"] == crimson_rs.calculate_checksum(
        paz_bytes
    )
    pamt_bytes = pamt_path.read_bytes()
    assert after_pamt["checksum"] == crimson_rs.calculate_checksum(pamt_bytes[12:])
    papgt_path = archive.game_dir / "meta" / "0.papgt"
    papgt = crimson_rs.parse_papgt_file(str(papgt_path))
    group = [item for item in papgt["entries"] if item["group_name"] == "0008"]
    assert len(group) == 1
    assert group[0]["pack_meta_checksum"] == after_pamt["checksum"]
