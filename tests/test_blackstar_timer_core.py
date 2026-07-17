from __future__ import annotations

import json
from pathlib import Path

import crimson_rs
import pytest

from blackstar_timer_archive import make_timer_archive
from crimson_common.blackstar_timer import (
    BackupConflictError,
    BlackstarTimerService,
    StalePreviewError,
    TimerTransactionError,
    TimerProfile,
    TimerStatus,
)


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def test_detects_only_enrolled_vanilla(tmp_path: Path) -> None:
    archive = make_timer_archive(tmp_path)
    service = BlackstarTimerService(TimerProfile(**archive.profile_kwargs()))

    report = service.detect(archive.game_dir)

    assert report.status is TimerStatus.VANILLA
    assert report.cooldown_seconds == 3600
    assert report.duration_seconds == 600
    assert report.body_sha256 == service.profile.vanilla_body_sha256


def test_detects_exact_applied_body(tmp_path: Path) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    archive.rebuild(archive.applied_body)

    report = BlackstarTimerService(profile).detect(archive.game_dir)

    assert report.status is TimerStatus.APPLIED
    assert report.cooldown_seconds == 1
    assert report.duration_seconds == 1800


def test_refuses_unknown_body_even_when_timer_values_match(tmp_path: Path) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    body = bytearray(archive.vanilla_body)
    body[100] ^= 0xFF
    archive.rebuild(bytes(body))

    report = BlackstarTimerService(profile).detect(archive.game_dir)

    assert report.status is TimerStatus.UNKNOWN
    assert "hash" in report.reason.lower()


def test_classifies_mixed_timer_values_as_partial(tmp_path: Path) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    body = bytearray(archive.vanilla_body)
    start = archive.cooldown_offset
    body[start:start + 8] = (1).to_bytes(8, "little")
    archive.rebuild(bytes(body))

    report = BlackstarTimerService(profile).detect(archive.game_dir)

    assert report.status is TimerStatus.PARTIAL
    assert report.cooldown_seconds == 1
    assert report.duration_seconds == 600


def test_detection_is_strictly_read_only(tmp_path: Path) -> None:
    archive = make_timer_archive(tmp_path)
    service = BlackstarTimerService(TimerProfile(**archive.profile_kwargs()))
    before = _snapshot(archive.game_dir)

    service.detect(archive.game_dir)

    assert _snapshot(archive.game_dir) == before


def test_preview_builds_and_verifies_candidate_without_writes(tmp_path: Path) -> None:
    archive = make_timer_archive(tmp_path)
    service = BlackstarTimerService(TimerProfile(**archive.profile_kwargs()))
    before = _snapshot(archive.game_dir)

    preview = service.preview(archive.game_dir)

    assert preview.status is TimerStatus.VANILLA
    assert preview.token is not None
    assert preview.cooldown_before == 3600
    assert preview.cooldown_after == 1
    assert preview.duration_before == 600
    assert preview.duration_after == 1800
    assert preview.candidate_body_sha256 == service.profile.applied_body_sha256
    assert preview.candidate_compressed_size <= preview.slot_capacity
    assert _snapshot(archive.game_dir) == before


def test_preview_token_is_bound_to_all_source_files(tmp_path: Path) -> None:
    archive = make_timer_archive(tmp_path)
    service = BlackstarTimerService(TimerProfile(**archive.profile_kwargs()))
    preview = service.preview(archive.game_dir)
    assert preview.token is not None
    service.validate_preview_token(preview.token)
    paz = archive.game_dir / "0008" / "0.paz"
    paz.write_bytes(paz.read_bytes() + b"unrelated-change")

    try:
        service.validate_preview_token(preview.token)
    except StalePreviewError as exc:
        assert "changed after preview" in str(exc)
    else:
        raise AssertionError("Changed source archive was accepted")


def test_preview_refuses_unknown_schema_without_token(tmp_path: Path) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    body = bytearray(archive.vanilla_body)
    body[100] ^= 0xFF
    archive.rebuild(bytes(body))

    preview = BlackstarTimerService(profile).preview(archive.game_dir)

    assert preview.status is TimerStatus.UNKNOWN
    assert preview.token is None


def _target_entry(pamt: dict) -> dict:
    matches = [
        entry
        for directory in pamt["directories"]
        if directory["path"] == "gamedata"
        for entry in directory["files"]
        if entry["name"] == "characterinfo.pabgb"
    ]
    assert len(matches) == 1
    return matches[0]


def test_apply_updates_real_compressed_length_and_integrity_chain(
    tmp_path: Path,
) -> None:
    archive = make_timer_archive(tmp_path)
    service = BlackstarTimerService(TimerProfile(**archive.profile_kwargs()))
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    result = service.apply(preview.token)

    assert result.status is TimerStatus.APPLIED
    assert result.changed is True
    assert service.detect(archive.game_dir).status is TimerStatus.APPLIED
    pamt_path = archive.game_dir / "0008" / "0.pamt"
    paz_path = archive.game_dir / "0008" / "0.paz"
    papgt_path = archive.game_dir / "meta" / "0.papgt"
    pamt = crimson_rs.parse_pamt_file(str(pamt_path))
    entry = _target_entry(pamt)
    assert entry["compressed_size"] == preview.candidate_compressed_size
    paz_bytes = paz_path.read_bytes()
    compressed = paz_bytes[
        entry["chunk_offset"]:entry["chunk_offset"] + entry["compressed_size"]
    ]
    body = bytes(
        crimson_rs.decompress_data(
            compressed, entry["compression"], entry["uncompressed_size"]
        )
    )
    assert body == archive.applied_body
    assert pamt["chunks"][0]["checksum"] == crimson_rs.calculate_checksum(paz_bytes)
    assert pamt["chunks"][0]["size"] == len(paz_bytes)
    pamt_bytes = pamt_path.read_bytes()
    assert pamt["checksum"] == crimson_rs.calculate_checksum(pamt_bytes[12:])
    papgt = crimson_rs.parse_papgt_file(str(papgt_path))
    group = [entry for entry in papgt["entries"] if entry["group_name"] == "0008"]
    assert len(group) == 1
    assert group[0]["pack_meta_checksum"] == pamt["checksum"]
    papgt_bytes = papgt_path.read_bytes()
    assert papgt["checksum"] == crimson_rs.calculate_checksum(papgt_bytes[12:])


def test_apply_creates_verified_three_file_backup_manifest(tmp_path: Path) -> None:
    archive = make_timer_archive(tmp_path)
    service = BlackstarTimerService(TimerProfile(**archive.profile_kwargs()))
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    result = service.apply(preview.token)

    assert result.backup_dir is not None
    backup = result.backup_dir
    assert (backup / "0008" / "0.paz").is_file()
    assert (backup / "0008" / "0.pamt").is_file()
    assert (backup / "meta" / "0.papgt").is_file()
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["profile_id"] == service.profile.profile_id
    assert manifest["finalized"] is True
    assert set(manifest["source_hashes"]) == {
        "0008/0.paz",
        "0008/0.pamt",
        "meta/0.papgt",
    }
    assert set(manifest["post_apply_hashes"]) == set(manifest["source_hashes"])
    for relative, expected_hash in manifest["source_hashes"].items():
        assert service._hash_file(backup / Path(relative)) == expected_hash


def test_second_apply_is_idempotent_and_creates_no_second_backup(
    tmp_path: Path,
) -> None:
    archive = make_timer_archive(tmp_path)
    service = BlackstarTimerService(TimerProfile(**archive.profile_kwargs()))
    preview = service.preview(archive.game_dir)
    assert preview.token is not None
    first = service.apply(preview.token)

    second = service.apply(preview.token)

    assert first.changed is True
    assert second.changed is False
    assert second.status is TimerStatus.APPLIED
    backup_root = (
        archive.game_dir
        / "bin64"
        / "SEModLoad"
        / "Backups"
        / "BlackstarTimer"
    )
    assert len([path for path in backup_root.iterdir() if path.is_dir()]) == 1


@pytest.mark.parametrize(
    "failure_phase",
    ["after_paz_write", "after_pamt_write", "after_papgt_write"],
)
def test_apply_rolls_back_all_files_after_each_write_boundary(
    tmp_path: Path,
    failure_phase: str,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    paths = [
        archive.game_dir / "0008" / "0.paz",
        archive.game_dir / "0008" / "0.pamt",
        archive.game_dir / "meta" / "0.papgt",
    ]
    before = {path: path.read_bytes() for path in paths}

    def fail(phase: str) -> None:
        if phase == failure_phase:
            raise RuntimeError(f"injected failure: {phase}")

    service = BlackstarTimerService(profile, fault_injector=fail)
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    with pytest.raises(TimerTransactionError, match="rolled back"):
        service.apply(preview.token)

    assert {path: path.read_bytes() for path in paths} == before
    assert service.detect(archive.game_dir).status is TimerStatus.VANILLA


def test_restore_recovers_verified_vanilla_archive(tmp_path: Path) -> None:
    archive = make_timer_archive(tmp_path)
    service = BlackstarTimerService(TimerProfile(**archive.profile_kwargs()))
    preview = service.preview(archive.game_dir)
    assert preview.token is not None
    applied = service.apply(preview.token)

    restored = service.restore(archive.game_dir)

    assert restored.changed is True
    assert restored.status is TimerStatus.VANILLA
    assert restored.backup_dir == applied.backup_dir
    assert service.detect(archive.game_dir).status is TimerStatus.VANILLA


def test_restore_refuses_unrelated_post_apply_change_without_writing(
    tmp_path: Path,
) -> None:
    archive = make_timer_archive(tmp_path)
    service = BlackstarTimerService(TimerProfile(**archive.profile_kwargs()))
    preview = service.preview(archive.game_dir)
    assert preview.token is not None
    service.apply(preview.token)
    paz = archive.game_dir / "0008" / "0.paz"
    paz.write_bytes(paz.read_bytes() + b"another-mod")
    before = _snapshot(archive.game_dir)

    with pytest.raises(BackupConflictError, match="changed after"):
        service.restore(archive.game_dir)

    assert _snapshot(archive.game_dir) == before
