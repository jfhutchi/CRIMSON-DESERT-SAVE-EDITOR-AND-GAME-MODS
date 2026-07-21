from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import BinaryIO, Callable

import crimson_rs
import pytest

from blackstar_timer_archive import make_timer_archive
import crimson_common.blackstar_timer as timer_module
from crimson_common.blackstar_timer import (
    ArchiveFileHash,
    BackupConflictError,
    BlackstarTimerService,
    GameRunningError,
    StalePreviewError,
    TimerTransactionError,
    TimerProfile,
    TimerStatus,
)


@pytest.fixture(autouse=True)
def _never_query_live_game_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(timer_module, "is_crimson_desert_running", lambda: False)


class _CountingInspectionService(BlackstarTimerService):
    def __init__(
        self,
        profile: TimerProfile,
        process_checker: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(profile, process_checker=process_checker)
        self.entry_lookup_count = 0
        self.body_read_count = 0
        self.hash_call_count = 0
        self.decompress_call_count = 0

    def _find_entry(self, game: Path) -> dict:
        self.entry_lookup_count += 1
        return super()._find_entry(game)

    def _read_body(self, game: Path, entry: dict) -> bytes:
        self.body_read_count += 1
        return super()._read_body(game, entry)

    def _hash_file(self, path: Path) -> str:
        self.hash_call_count += 1
        return super()._hash_file(path)

    def _decompress_stream(
        self,
        compressed: bytes,
        compression: int,
        uncompressed_size: int,
    ) -> bytes:
        self.decompress_call_count += 1
        return super()._decompress_stream(
            compressed,
            compression,
            uncompressed_size,
        )

    def reset_counts(self) -> None:
        self.entry_lookup_count = 0
        self.body_read_count = 0
        self.hash_call_count = 0
        self.decompress_call_count = 0


class _EntryOwnershipService(BlackstarTimerService):
    def __init__(self, profile: TimerProfile) -> None:
        super().__init__(profile)
        self.source_entry: dict | None = None

    def _find_entry(self, game: Path) -> dict:
        entry = super()._find_entry(game)
        self.source_entry = entry
        return entry


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


def test_detect_translates_missing_archive_source_to_unknown(tmp_path: Path) -> None:
    archive = make_timer_archive(tmp_path)
    service = _CountingInspectionService(TimerProfile(**archive.profile_kwargs()))

    report = service.detect(tmp_path / "missing")

    assert report.status is TimerStatus.UNKNOWN
    assert "PAMT not found" in report.reason
    assert service.entry_lookup_count == 1
    assert service.body_read_count == 0


def test_detect_translates_entry_validation_failure_to_unknown(
    tmp_path: Path,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    service = _CountingInspectionService(
        replace(profile, entry_offset=profile.entry_offset + 1)
    )

    report = service.detect(archive.game_dir)

    assert report.status is TimerStatus.UNKNOWN
    assert "Unexpected entry offset" in report.reason
    assert service.entry_lookup_count == 1
    assert service.body_read_count == 0


def test_detect_translates_native_decompression_failure_to_unknown(
    tmp_path: Path,
) -> None:
    archive = make_timer_archive(tmp_path)
    service = _CountingInspectionService(TimerProfile(**archive.profile_kwargs()))
    paz = archive.game_dir / "0008" / "0.paz"
    paz_bytes = bytearray(paz.read_bytes())
    paz_bytes[archive.entry_offset] ^= 0xFF
    compressed = bytes(
        paz_bytes[
            archive.entry_offset:
            archive.entry_offset + archive.vanilla_compressed_size
        ]
    )
    with pytest.raises(OSError):
        crimson_rs.decompress_data(compressed, 2, archive.body_size)
    paz.write_bytes(paz_bytes)

    report = service.detect(archive.game_dir)

    assert report.status is TimerStatus.UNKNOWN
    assert "compatibility check failed" in report.reason
    assert service.entry_lookup_count == 1
    assert service.body_read_count == 1


@pytest.mark.parametrize("operation", ["detect", "preview", "token"])
def test_timer_offset_classification_errors_propagate(
    tmp_path: Path,
    operation: str,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    valid_service = BlackstarTimerService(profile)
    preview = valid_service.preview(archive.game_dir)
    assert preview.token is not None
    invalid_service = _CountingInspectionService(
        replace(profile, cooldown_offset=profile.uncompressed_size)
    )

    with pytest.raises(ValueError, match="Timer field offset"):
        if operation == "detect":
            invalid_service.detect(archive.game_dir)
        elif operation == "preview":
            invalid_service.preview(archive.game_dir)
        else:
            invalid_service.validate_preview_token(preview.token)
    assert invalid_service.entry_lookup_count == 1
    assert invalid_service.body_read_count == 1


def test_archive_inspection_owns_an_immutable_entry_snapshot(tmp_path: Path) -> None:
    archive = make_timer_archive(tmp_path)
    service = _EntryOwnershipService(TimerProfile(**archive.profile_kwargs()))

    inspection = service._inspect(archive.game_dir)

    assert service.source_entry is not None
    assert not isinstance(inspection.entry, dict)
    assert inspection.entry.compressed_size == inspection.report.compressed_size
    service.source_entry["compressed_size"] = -1
    assert inspection.entry.compressed_size == inspection.report.compressed_size
    with pytest.raises(FrozenInstanceError):
        inspection.entry.compressed_size = -1


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
    service = _CountingInspectionService(TimerProfile(**archive.profile_kwargs()))
    before = _snapshot(archive.game_dir)

    service.detect(archive.game_dir)

    assert service.entry_lookup_count == 1
    assert service.body_read_count == 1
    assert _snapshot(archive.game_dir) == before


def test_preview_builds_and_verifies_candidate_without_writes(tmp_path: Path) -> None:
    archive = make_timer_archive(tmp_path)
    service = _CountingInspectionService(TimerProfile(**archive.profile_kwargs()))
    before = _snapshot(archive.game_dir)

    preview = service.preview(archive.game_dir)

    assert service.body_read_count == 1
    assert service.entry_lookup_count == 1
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
    service = _CountingInspectionService(TimerProfile(**archive.profile_kwargs()))
    preview = service.preview(archive.game_dir)
    assert preview.token is not None
    service.reset_counts()

    service.validate_preview_token(preview.token)

    assert service.entry_lookup_count == 1
    assert service.body_read_count == 1
    paz = archive.game_dir / "0008" / "0.paz"
    paz.write_bytes(paz.read_bytes() + b"unrelated-change")
    service.reset_counts()

    with pytest.raises(StalePreviewError, match="changed after preview"):
        service.validate_preview_token(preview.token)
    assert service.entry_lookup_count == 1
    assert service.body_read_count == 1


@pytest.mark.parametrize(
    "source_state",
    ["valid", "running", "process_error", "missing", "corrupt"],
)
def test_preview_token_rejects_unsafe_path_before_source_inspection(
    tmp_path: Path,
    source_state: str,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    preview = BlackstarTimerService(profile).preview(archive.game_dir)
    assert preview.token is not None
    unsafe = replace(
        preview.token,
        archive_hashes=(ArchiveFileHash("../outside.bin", "0" * 64),),
    )
    process_calls = {"count": 0}

    def check_process() -> bool:
        process_calls["count"] += 1
        if source_state == "process_error":
            raise OSError("process unavailable")
        return source_state == "running"

    if source_state == "missing":
        (archive.game_dir / "0008" / "0.pamt").unlink()
    elif source_state == "corrupt":
        paz = archive.game_dir / "0008" / "0.paz"
        paz_bytes = bytearray(paz.read_bytes())
        paz_bytes[archive.entry_offset] ^= 0xFF
        paz.write_bytes(paz_bytes)
    service = _CountingInspectionService(profile, process_checker=check_process)

    with pytest.raises(
        StalePreviewError,
        match=r"^Unsafe backup path: \.\./outside\.bin$",
    ):
        service.validate_preview_token(unsafe)

    assert process_calls["count"] == 0
    assert service.entry_lookup_count == 0
    assert service.body_read_count == 0


def test_preview_token_rejects_duplicate_paths_before_source_inspection(
    tmp_path: Path,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    preview = BlackstarTimerService(profile).preview(archive.game_dir)
    assert preview.token is not None
    duplicate = replace(
        preview.token,
        archive_hashes=(
            preview.token.archive_hashes[0],
            preview.token.archive_hashes[0],
        ),
    )
    process_calls = {"count": 0}

    def check_process() -> bool:
        process_calls["count"] += 1
        return False

    service = _CountingInspectionService(profile, process_checker=check_process)

    with pytest.raises(StalePreviewError, match="changed after preview"):
        service.validate_preview_token(duplicate)

    assert process_calls["count"] == 0
    assert service.entry_lookup_count == 0
    assert service.body_read_count == 0


def test_preview_token_requires_all_source_archive_hashes(tmp_path: Path) -> None:
    archive = make_timer_archive(tmp_path)
    service = _CountingInspectionService(TimerProfile(**archive.profile_kwargs()))
    preview = service.preview(archive.game_dir)
    assert preview.token is not None
    incomplete = replace(
        preview.token,
        archive_hashes=preview.token.archive_hashes[:-1],
    )
    service.reset_counts()

    with pytest.raises(StalePreviewError, match="changed after preview"):
        service.validate_preview_token(incomplete)
    assert service.entry_lookup_count == 1
    assert service.body_read_count == 1


@pytest.mark.parametrize(
    "field_name",
    ["source_body_sha256", "entry_offset", "source_compressed_size"],
)
def test_preview_token_rejects_stale_inspection_metadata(
    tmp_path: Path,
    field_name: str,
) -> None:
    archive = make_timer_archive(tmp_path)
    service = _CountingInspectionService(TimerProfile(**archive.profile_kwargs()))
    preview = service.preview(archive.game_dir)
    assert preview.token is not None
    current = getattr(preview.token, field_name)
    stale_value = "0" * 64 if isinstance(current, str) else current + 1
    stale = replace(preview.token, **{field_name: stale_value})
    service.reset_counts()

    with pytest.raises(StalePreviewError, match="changed after preview"):
        service.validate_preview_token(stale)
    assert service.entry_lookup_count == 1
    assert service.body_read_count == 1


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


def _timer_archive_paths(game: Path) -> tuple[Path, Path, Path]:
    return (
        game / "0008" / "0.paz",
        game / "0008" / "0.pamt",
        game / "meta" / "0.papgt",
    )


def _archive_contents(paths: tuple[Path, Path, Path]) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in paths}


def _only_backup_manifest(game: Path) -> tuple[Path, dict]:
    backup_root = (
        game / "bin64" / "SEModLoad" / "Backups" / "BlackstarTimer"
    )
    backups = [path for path in backup_root.iterdir() if path.is_dir()]
    assert len(backups) == 1
    manifest_path = backups[0] / "manifest.json"
    return manifest_path, json.loads(manifest_path.read_text(encoding="utf-8"))


def _assert_unfinalized_rollback_manifest(game: Path) -> None:
    _manifest_path, manifest = _only_backup_manifest(game)
    assert manifest["post_apply_hashes"] == {}
    assert manifest["finalized"] is False
    assert manifest["rolled_back"] is True
    assert set(manifest["source_hashes"]) == {
        "0008/0.paz",
        "0008/0.pamt",
        "meta/0.papgt",
    }


@pytest.mark.parametrize("failure_stage", ["write", "flush", "fsync"])
@pytest.mark.parametrize("failed_operation", ["paz-slot", "pamt", "papgt"])
def test_apply_rolls_back_archive_io_failures(
    tmp_path: Path,
    failure_stage: str,
    failed_operation: str,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    paths = _timer_archive_paths(archive.game_dir)
    before = _archive_contents(paths)

    class PazIoFailureService(BlackstarTimerService):
        failed = False

        def _write_all(
            self,
            handle: BinaryIO,
            data: bytes,
            operation: str,
        ) -> None:
            if (
                failure_stage == "write"
                and operation == failed_operation
                and not self.failed
            ):
                self.failed = True
                handle.write(data[:max(1, len(data) // 2)])
                raise OSError("injected paz write failure")
            return super()._write_all(handle, data, operation)

        def _flush_file(self, handle: BinaryIO, operation: str) -> None:
            if (
                failure_stage == "flush"
                and operation == failed_operation
                and not self.failed
            ):
                self.failed = True
                raise OSError("injected paz flush failure")
            return super()._flush_file(handle, operation)

        def _fsync_file(self, handle: BinaryIO, operation: str) -> None:
            if (
                failure_stage == "fsync"
                and operation == failed_operation
                and not self.failed
            ):
                self.failed = True
                raise OSError("injected paz fsync failure")
            return super()._fsync_file(handle, operation)

    service = PazIoFailureService(profile)
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    with pytest.raises(TimerTransactionError, match="rolled back"):
        service.apply(preview.token)

    assert service.failed is True
    assert _archive_contents(paths) == before
    _assert_unfinalized_rollback_manifest(archive.game_dir)


def test_apply_rolls_back_when_paz_open_for_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    paths = _timer_archive_paths(archive.game_dir)
    before = _archive_contents(paths)
    paz_path = paths[0]
    native_open = Path.open
    failed = False

    def fail_paz_open(path: Path, mode: str = "r", *args: object, **kwargs: object):
        nonlocal failed
        if path == paz_path and mode == "r+b" and not failed:
            failed = True
            raise OSError("injected paz open-for-write failure")
        return native_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_paz_open)
    service = BlackstarTimerService(profile)
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    with pytest.raises(TimerTransactionError, match="rolled back"):
        service.apply(preview.token)

    assert failed is True
    assert _archive_contents(paths) == before
    _assert_unfinalized_rollback_manifest(archive.game_dir)


@pytest.mark.parametrize(
    ("failure_stage", "target_relative"),
    [
        (stage, relative)
        for stage in (
            "backup_write",
            "backup_flush",
            "backup_fsync",
            "backup_directory",
        )
        for relative in (
            "0008/0.paz",
            "0008/0.pamt",
            "meta/0.papgt",
        )
    ] + [
        ("manifest_fsync", None),
        ("manifest_directory", None),
    ],
)
def test_backup_durability_failure_prevents_source_mutation(
    tmp_path: Path,
    failure_stage: str,
    target_relative: str | None,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    paths = _timer_archive_paths(archive.game_dir)
    before = _archive_contents(paths)

    class BackupDurabilityFailureService(BlackstarTimerService):
        failed = False
        mutation_attempted = False

        def _write_all(
            self,
            handle: BinaryIO,
            data: bytes,
            operation: str,
        ) -> None:
            if (
                failure_stage == "backup_write"
                and operation == f"backup:{target_relative}"
                and not self.failed
            ):
                self.failed = True
                handle.write(data[:max(1, len(data) // 2)])
                raise OSError("injected backup write failure")
            return super()._write_all(handle, data, operation)

        def _flush_file(self, handle: BinaryIO, operation: str) -> None:
            if (
                failure_stage == "backup_flush"
                and operation.startswith("backup:")
                and not self.failed
            ):
                self.failed = True
                raise OSError("injected backup flush failure")
            return super()._flush_file(handle, operation)

        def _fsync_file(self, handle: BinaryIO, operation: str) -> None:
            should_fail = (
                failure_stage == "backup_fsync"
                and operation.startswith("backup:")
            ) or (
                failure_stage == "manifest_fsync"
                and operation == "manifest"
            )
            if should_fail and not self.failed:
                self.failed = True
                raise OSError(f"injected {failure_stage} failure")
            return super()._fsync_file(handle, operation)

        def _sync_directory(self, path: Path, operation: str) -> None:
            should_fail = (
                failure_stage == "backup_directory"
                and operation == f"backup-directory:{target_relative}"
            ) or (
                failure_stage == "manifest_directory"
                and operation == "manifest-directory"
            )
            if should_fail and not self.failed:
                self.failed = True
                raise OSError(f"injected {failure_stage} failure")
            return super()._sync_directory(path, operation)

        def _patch_paz_slot(self, *args: object, **kwargs: object) -> None:
            self.mutation_attempted = True
            return super()._patch_paz_slot(*args, **kwargs)

    service = BackupDurabilityFailureService(profile)
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    with pytest.raises(OSError, match="injected"):
        service.apply(preview.token)

    assert service.failed is True
    assert service.mutation_attempted is False
    assert _archive_contents(paths) == before


def test_backup_and_manifest_are_durable_before_paz_mutation(
    tmp_path: Path,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())

    class DurabilityOrderService(BlackstarTimerService):
        def __init__(self) -> None:
            super().__init__(profile)
            self.synced_files: set[str] = set()
            self.synced_directories: set[str] = set()
            self.mutation_prerequisites: tuple[set[str], set[str]] | None = None

        def _fsync_file(self, handle: BinaryIO, operation: str) -> None:
            super()._fsync_file(handle, operation)
            self.synced_files.add(operation)

        def _sync_directory(self, path: Path, operation: str) -> None:
            super()._sync_directory(path, operation)
            self.synced_directories.add(operation)

        def _patch_paz_slot(self, *args: object, **kwargs: object) -> None:
            self.mutation_prerequisites = (
                set(self.synced_files),
                set(self.synced_directories),
            )
            return super()._patch_paz_slot(*args, **kwargs)

    service = DurabilityOrderService()
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    service.apply(preview.token)

    assert service.mutation_prerequisites is not None
    synced_files, synced_directories = service.mutation_prerequisites
    assert {
        "backup:0008/0.paz",
        "backup:0008/0.pamt",
        "backup:meta/0.papgt",
        "manifest",
    } <= synced_files
    assert {
        "backup-directory:0008/0.paz",
        "backup-directory:0008/0.pamt",
        "backup-directory:meta/0.papgt",
        "manifest-directory",
    } <= synced_directories


@pytest.mark.parametrize("window", ["before", "during"])
@pytest.mark.parametrize("region", ["outside", "inside"])
def test_apply_rejects_paz_tampering_against_backup_snapshot(
    tmp_path: Path,
    window: str,
    region: str,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    paths = _timer_archive_paths(archive.game_dir)
    paz_path = paths[0]
    before = _archive_contents(paths)
    tampered = False

    def tamper_handle(handle: BinaryIO, offset: int) -> None:
        position = handle.tell()
        handle.seek(offset)
        original = handle.read(1)
        assert len(original) == 1
        handle.seek(offset)
        handle.write(bytes([original[0] ^ 0xFF]))
        handle.flush()
        handle.seek(position)

    class TamperingService(BlackstarTimerService):
        def _patch_paz_slot(self, *args: object, **kwargs: object) -> None:
            nonlocal tampered
            if window == "before":
                offset = 0 if region == "outside" else self.profile.entry_offset
                with paz_path.open("r+b") as handle:
                    tamper_handle(handle, offset)
                tampered = True
            return super()._patch_paz_slot(*args, **kwargs)

        def _fsync_file(self, handle: BinaryIO, operation: str) -> None:
            nonlocal tampered
            if window == "during" and operation == "paz-slot" and not tampered:
                offset = 0 if region == "outside" else self.profile.entry_offset
                tamper_handle(handle, offset)
                tampered = True
            return super()._fsync_file(handle, operation)

    service = TamperingService(profile)
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    with pytest.raises(TimerTransactionError, match="rolled back"):
        service.apply(preview.token)

    assert tampered is True
    assert _archive_contents(paths) == before
    _assert_unfinalized_rollback_manifest(archive.game_dir)


def test_apply_rolls_back_appended_paz_bytes_after_write(
    tmp_path: Path,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    paths = _timer_archive_paths(archive.game_dir)
    before = _archive_contents(paths)

    def append_after_paz_write(phase: str) -> None:
        if phase == "after_paz_write":
            with paths[0].open("ab") as handle:
                handle.write(b"out-of-band append")

    service = BlackstarTimerService(
        profile,
        fault_injector=append_after_paz_write,
    )
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    with pytest.raises(TimerTransactionError, match="rolled back"):
        service.apply(preview.token)

    assert _archive_contents(paths) == before
    _assert_unfinalized_rollback_manifest(archive.game_dir)


def _rewrite_metadata_checksums(
    pamt_bytes: bytes,
    papgt_bytes: bytes,
    mutate: Callable[[dict, dict], None],
) -> tuple[bytes, bytes]:
    pamt = crimson_rs.parse_pamt_bytes(pamt_bytes)
    entry = _target_entry(pamt)
    mutate(pamt, entry)
    repaired_pamt = bytearray(crimson_rs.serialize_pamt(pamt))
    repaired_pamt[:4] = crimson_rs.calculate_checksum(
        bytes(repaired_pamt[12:])
    ).to_bytes(4, "little")
    verified_pamt = crimson_rs.parse_pamt_bytes(bytes(repaired_pamt))

    papgt = crimson_rs.parse_papgt_bytes(papgt_bytes)
    groups = [
        item for item in papgt["entries"] if item["group_name"] == "0008"
    ]
    assert len(groups) == 1
    groups[0]["pack_meta_checksum"] = verified_pamt["checksum"]
    repaired_papgt = bytearray(crimson_rs.serialize_papgt(papgt))
    repaired_papgt[4:8] = crimson_rs.calculate_checksum(
        bytes(repaired_papgt[12:])
    ).to_bytes(4, "little")
    return bytes(repaired_pamt), bytes(repaired_papgt)


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("entry_offset", "Unexpected entry offset"),
        ("chunk_size", "PAZ chunk size mismatch"),
        ("uncompressed_size", "Unexpected uncompressed size"),
    ],
)
def test_apply_rejects_repaired_checksum_invalid_metadata(
    tmp_path: Path,
    mutation: str,
    error: str,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    paths = _timer_archive_paths(archive.game_dir)
    before = _archive_contents(paths)

    class InvalidMetadataService(BlackstarTimerService):
        def _build_metadata_bytes(
            self,
            *args: object,
            **kwargs: object,
        ) -> tuple[bytes, bytes]:
            pamt_bytes, papgt_bytes = super()._build_metadata_bytes(
                *args, **kwargs
            )

            def mutate(pamt: dict, entry: dict) -> None:
                if mutation == "entry_offset":
                    entry["chunk_offset"] = int(entry["chunk_offset"]) + 1
                elif mutation == "chunk_size":
                    pamt["chunks"][0]["size"] = (
                        int(pamt["chunks"][0]["size"]) + 1
                    )
                else:
                    entry["uncompressed_size"] = (
                        int(entry["uncompressed_size"]) + 1
                    )

            return _rewrite_metadata_checksums(
                pamt_bytes,
                papgt_bytes,
                mutate,
            )

    service = InvalidMetadataService(profile)
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    with pytest.raises(TimerTransactionError, match=error):
        service.apply(preview.token)

    assert _archive_contents(paths) == before
    _assert_unfinalized_rollback_manifest(archive.game_dir)


def test_apply_streams_paz_identity_without_full_file_buffers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = make_timer_archive(tmp_path)

    class StreamingIdentityService(_CountingInspectionService):
        def __init__(self) -> None:
            super().__init__(TimerProfile(**archive.profile_kwargs()))
            self.identity_stream_calls = 0
            self.active_identity_streams = 0
            self.peak_identity_streams = 0
            self.backup_copy_passes = 0

        def _copy_backup_file(
            self,
            source: Path,
            destination: Path,
            operation: str,
        ) -> None:
            self.backup_copy_passes += 1
            return super()._copy_backup_file(
                source,
                destination,
                operation,
            )

        def _stream_paz_identity(
            self,
            *args: object,
            **kwargs: object,
        ) -> object:
            self.identity_stream_calls += 1
            self.active_identity_streams += 1
            self.peak_identity_streams = max(
                self.peak_identity_streams,
                self.active_identity_streams,
            )
            try:
                return super()._stream_paz_identity(*args, **kwargs)
            finally:
                self.active_identity_streams -= 1

    service = StreamingIdentityService()
    preview = service.preview(archive.game_dir)
    assert preview.token is not None
    service.reset_counts()
    full_paz_reads: list[Path] = []
    native_read_bytes = Path.read_bytes

    def reject_full_paz_read(path: Path) -> bytes:
        if path.suffix == ".paz":
            full_paz_reads.append(path)
            raise AssertionError("Apply must not materialize a full PAZ buffer")
        return native_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", reject_full_paz_read)

    service.apply(preview.token)

    assert full_paz_reads == []
    assert service.identity_stream_calls == 2
    assert service.peak_identity_streams == 1
    assert service.backup_copy_passes == 3
    assert service.hash_call_count == 5
    assert (
        service.hash_call_count
        + service.identity_stream_calls
        + service.backup_copy_passes
    ) == 10
    assert service.decompress_call_count == 2
    assert not hasattr(service, "_build_transaction_bytes")


def test_unfinalized_manifest_retains_hard_stop_recovery_inputs(
    tmp_path: Path,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())

    class SimulatedHardStop(BaseException):
        pass

    def stop_after_paz_write(phase: str) -> None:
        if phase == "after_paz_write":
            raise SimulatedHardStop("simulated process termination")

    service = BlackstarTimerService(profile, fault_injector=stop_after_paz_write)
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    with pytest.raises(SimulatedHardStop):
        service.apply(preview.token)

    manifest_path, manifest = _only_backup_manifest(archive.game_dir)
    assert manifest_path.is_file()
    assert manifest["post_apply_hashes"] == {}
    assert manifest["finalized"] is False
    assert manifest["rolled_back"] is False
    for relative, expected in manifest["source_hashes"].items():
        backup_file = manifest_path.parent / Path(relative)
        assert backup_file.is_file()
        assert service._hash_file(backup_file) == expected


def test_apply_has_bounded_archive_work(tmp_path: Path) -> None:
    archive = make_timer_archive(tmp_path)
    service = _CountingInspectionService(TimerProfile(**archive.profile_kwargs()))
    preview = service.preview(archive.game_dir)
    assert preview.token is not None
    service.reset_counts()

    service.apply(preview.token)

    violations = []
    if service.hash_call_count > 6:
        violations.append(f"hash calls: {service.hash_call_count} > 6")
    if service.decompress_call_count != 2:
        violations.append(
            f"decompressions: {service.decompress_call_count} != 2"
        )
    if hasattr(service, "_build_transaction_bytes"):
        violations.append("full PAZ candidate builder still exists")
    assert violations == []


def test_apply_failure_keeps_backup_manifest_unfinalized(tmp_path: Path) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())

    def fail_after_paz(phase: str) -> None:
        if phase == "after_paz_write":
            raise RuntimeError("injected failure: after_paz_write")

    service = BlackstarTimerService(profile, fault_injector=fail_after_paz)
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    with pytest.raises(TimerTransactionError, match="rolled back"):
        service.apply(preview.token)

    backup_root = (
        archive.game_dir
        / "bin64"
        / "SEModLoad"
        / "Backups"
        / "BlackstarTimer"
    )
    backups = [path for path in backup_root.iterdir() if path.is_dir()]
    assert len(backups) == 1
    manifest = json.loads(
        (backups[0] / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["post_apply_hashes"] == {}
    assert manifest["finalized"] is False
    assert manifest["rolled_back"] is True


def test_apply_combined_verification_failure_rolls_back_before_finalization(
    tmp_path: Path,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    paths = [
        archive.game_dir / "0008" / "0.paz",
        archive.game_dir / "0008" / "0.pamt",
        archive.game_dir / "meta" / "0.papgt",
    ]
    before = {path: path.read_bytes() for path in paths}

    class VerificationFailureService(BlackstarTimerService):
        def __init__(self) -> None:
            super().__init__(profile)
            self.verification_calls = 0

        def _verify_archive_set(self, *args: object, **kwargs: object) -> object:
            self.verification_calls += 1
            if self.verification_calls == 1:
                raise ValueError("injected combined verification failure")
            return super()._verify_archive_set(*args, **kwargs)

    service = VerificationFailureService()
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    with pytest.raises(TimerTransactionError, match="rolled back"):
        service.apply(preview.token)

    assert service.verification_calls == 2
    assert {path: path.read_bytes() for path in paths} == before
    backup_root = (
        archive.game_dir
        / "bin64"
        / "SEModLoad"
        / "Backups"
        / "BlackstarTimer"
    )
    backups = [path for path in backup_root.iterdir() if path.is_dir()]
    assert len(backups) == 1
    manifest = json.loads(
        (backups[0] / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["post_apply_hashes"] == {}
    assert manifest["finalized"] is False
    assert manifest["rolled_back"] is True


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


@pytest.mark.parametrize(
    "failure_phase",
    ["after_restore_file_1", "after_restore_file_2", "after_restore_file_3"],
)
def test_restore_rolls_back_to_applied_state_after_each_write_boundary(
    tmp_path: Path,
    failure_phase: str,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())

    def fail(phase: str) -> None:
        if phase == failure_phase:
            raise RuntimeError(f"injected failure: {phase}")

    service = BlackstarTimerService(profile, fault_injector=fail)
    preview = service.preview(archive.game_dir)
    assert preview.token is not None
    service.apply(preview.token)
    applied = _snapshot(archive.game_dir)

    with pytest.raises(TimerTransactionError, match="rolled back to the applied state"):
        service.restore(archive.game_dir)

    assert _snapshot(archive.game_dir) == applied
    assert service.detect(archive.game_dir).status is TimerStatus.APPLIED


def test_restore_rejects_unsafe_manifest_path_without_writing(tmp_path: Path) -> None:
    archive = make_timer_archive(tmp_path)
    service = BlackstarTimerService(TimerProfile(**archive.profile_kwargs()))
    preview = service.preview(archive.game_dir)
    assert preview.token is not None
    applied = service.apply(preview.token)
    assert applied.backup_dir is not None
    manifest_path = applied.backup_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_hashes"]["../outside.bin"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = _snapshot(archive.game_dir)

    with pytest.raises(BackupConflictError, match="archive paths"):
        service.restore(archive.game_dir)

    assert _snapshot(archive.game_dir) == before


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


def test_running_game_disables_preview_and_apply_without_writes(
    tmp_path: Path,
) -> None:
    archive = make_timer_archive(tmp_path)
    running = {"value": False}
    service = BlackstarTimerService(
        TimerProfile(**archive.profile_kwargs()),
        process_checker=lambda: running["value"],
    )
    preview = service.preview(archive.game_dir)
    assert preview.token is not None
    running["value"] = True
    before = _snapshot(archive.game_dir)

    blocked_preview = service.preview(archive.game_dir)
    assert blocked_preview.status is TimerStatus.GAME_RUNNING
    assert blocked_preview.token is None
    with pytest.raises(GameRunningError, match="running"):
        service.apply(preview.token)

    assert _snapshot(archive.game_dir) == before
    assert not (
        archive.game_dir / "bin64" / "SEModLoad" / "Backups" / "BlackstarTimer"
    ).exists()


def test_running_game_disables_restore_without_writes(tmp_path: Path) -> None:
    archive = make_timer_archive(tmp_path)
    running = {"value": False}
    service = BlackstarTimerService(
        TimerProfile(**archive.profile_kwargs()),
        process_checker=lambda: running["value"],
    )
    preview = service.preview(archive.game_dir)
    assert preview.token is not None
    service.apply(preview.token)
    running["value"] = True
    before = _snapshot(archive.game_dir)

    with pytest.raises(GameRunningError, match="running"):
        service.restore(archive.game_dir)

    assert _snapshot(archive.game_dir) == before
