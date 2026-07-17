from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

import crimson_rs


@dataclass
class TimerArchive:
    game_dir: Path
    vanilla_body: bytes
    applied_body: bytes
    entry_offset: int
    vanilla_compressed_size: int
    body_size: int
    cooldown_offset: int
    duration_offset: int

    def rebuild(self, body: bytes) -> None:
        group = self.game_dir / "0008"
        if group.exists():
            shutil.rmtree(group)
        group.mkdir(parents=True)
        builder = crimson_rs.PackGroupBuilder(
            str(group), compression=2, crypto=0
        )
        builder.add_file("gamedata", "characterinfo.pabgb", body)
        pamt_bytes = bytes(builder.finish())
        pamt = crimson_rs.parse_pamt_bytes(pamt_bytes)
        checksum = int(pamt["checksum"])
        papgt = {
            "unknown0": 0,
            "checksum": 0,
            "unknown1": 0,
            "unknown2": 0,
            "entries": [],
        }
        papgt = crimson_rs.add_papgt_entry(
            papgt, "0008", checksum, 0, 0x3FFF
        )
        meta = self.game_dir / "meta"
        meta.mkdir(exist_ok=True)
        crimson_rs.write_papgt_file(papgt, str(meta / "0.papgt"))

    def profile_kwargs(self) -> dict[str, object]:
        return {
            "profile_id": "test-blackstar-timer-v1",
            "group_name": "0008",
            "directory": "gamedata",
            "file_name": "characterinfo.pabgb",
            "entry_offset": self.entry_offset,
            "vanilla_compressed_size": self.vanilla_compressed_size,
            "uncompressed_size": self.body_size,
            "vanilla_body_sha256": hashlib.sha256(self.vanilla_body).hexdigest(),
            "applied_body_sha256": hashlib.sha256(self.applied_body).hexdigest(),
            "cooldown_offset": self.cooldown_offset,
            "duration_offset": self.duration_offset,
            "vanilla_cooldown_seconds": 3600,
            "vanilla_duration_seconds": 600,
            "preset_cooldown_seconds": 1,
            "preset_duration_seconds": 1800,
        }


def make_timer_archive(tmp_path: Path) -> TimerArchive:
    body_size = 4096
    cooldown_offset = 3072
    duration_offset = 3080
    body = bytearray((index * 37 + index // 11) % 256 for index in range(body_size))
    body[cooldown_offset:cooldown_offset + 8] = (3600).to_bytes(8, "little")
    body[duration_offset:duration_offset + 8] = (600).to_bytes(8, "little")
    vanilla = bytes(body)
    body[cooldown_offset:cooldown_offset + 8] = (1).to_bytes(8, "little")
    body[duration_offset:duration_offset + 8] = (1800).to_bytes(8, "little")
    applied = bytes(body)

    game_dir = tmp_path / "synthetic-game"
    archive = TimerArchive(
        game_dir=game_dir,
        vanilla_body=vanilla,
        applied_body=applied,
        entry_offset=0,
        vanilla_compressed_size=0,
        body_size=body_size,
        cooldown_offset=cooldown_offset,
        duration_offset=duration_offset,
    )
    archive.rebuild(vanilla)
    pamt = crimson_rs.parse_pamt_file(str(game_dir / "0008" / "0.pamt"))
    entry = pamt["directories"][0]["files"][0]
    archive.entry_offset = int(entry["chunk_offset"])
    archive.vanilla_compressed_size = int(entry["compressed_size"])
    return archive
