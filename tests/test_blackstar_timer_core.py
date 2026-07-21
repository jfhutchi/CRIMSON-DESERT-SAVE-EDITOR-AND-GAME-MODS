from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
from collections import Counter
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

    def _hash_file(
        self,
        path: Path,
        operation: str | None = None,
    ) -> str:
        self.hash_call_count += 1
        if operation is None:
            return super()._hash_file(path)
        return super()._hash_file(path, operation)

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


@pytest.mark.parametrize("action", ["validate", "apply"])
def test_token_missing_root_is_stale_before_process_or_inspection(
    tmp_path: Path,
    action: str,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    preview = BlackstarTimerService(profile).preview(archive.game_dir)
    assert preview.token is not None
    preserved = tmp_path / "preserved-game"
    archive.game_dir.rename(preserved)
    before = _snapshot(preserved)
    process_calls = 0

    def check_process() -> bool:
        nonlocal process_calls
        process_calls += 1
        return False

    service = _CountingInspectionService(profile, process_checker=check_process)

    with pytest.raises(StalePreviewError) as raised:
        if action == "validate":
            service.validate_preview_token(preview.token)
        else:
            service.apply(preview.token)

    assert type(raised.value) is StalePreviewError
    assert str(raised.value) == "Source archive changed after preview"
    assert process_calls == 0
    assert service.entry_lookup_count == 0
    assert service.body_read_count == 0
    assert not archive.game_dir.exists()
    assert _snapshot(preserved) == before


@pytest.mark.parametrize("action", ["validate", "apply"])
def test_unsafe_token_precedes_missing_root_and_all_external_work(
    tmp_path: Path,
    action: str,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    preview = BlackstarTimerService(profile).preview(archive.game_dir)
    assert preview.token is not None
    unsafe = replace(
        preview.token,
        archive_hashes=(ArchiveFileHash("../outside.bin", "0" * 64),),
    )
    preserved = tmp_path / "preserved-game"
    archive.game_dir.rename(preserved)
    before = _snapshot(preserved)
    process_calls = 0

    def check_process() -> bool:
        nonlocal process_calls
        process_calls += 1
        return False

    service = _CountingInspectionService(profile, process_checker=check_process)

    with pytest.raises(StalePreviewError) as raised:
        if action == "validate":
            service.validate_preview_token(unsafe)
        else:
            service.apply(unsafe)

    assert type(raised.value) is StalePreviewError
    assert str(raised.value) == "Unsafe backup path: ../outside.bin"
    assert process_calls == 0
    assert service.entry_lookup_count == 0
    assert service.body_read_count == 0
    assert not archive.game_dir.exists()
    assert _snapshot(preserved) == before
    assert not (tmp_path / "outside.bin").exists()


@pytest.mark.skipif(timer_module.os.name != "nt", reason="Windows-only link resolution")
@pytest.mark.parametrize("action", ["validate", "apply"])
@pytest.mark.parametrize(
    "root_kind",
    ["broken_junction", "junction_loop", "broken_symlink", "symlink_loop"],
)
def test_token_broken_or_looped_root_is_stale_without_external_work(
    tmp_path: Path,
    action: str,
    root_kind: str,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    preview = BlackstarTimerService(profile).preview(archive.game_dir)
    assert preview.token is not None
    preserved = tmp_path / "preserved-game"
    archive.game_dir.rename(preserved)
    before = _snapshot(preserved)
    missing_target = tmp_path / "missing-target"
    peer = tmp_path / "root-link-peer"
    links: list[Path] = []

    try:
        if root_kind == "broken_junction":
            _create_junction(
                archive.game_dir,
                missing_target,
                create_target=False,
            )
            links.append(archive.game_dir)
        elif root_kind == "junction_loop":
            _create_junction(archive.game_dir, peer, create_target=False)
            _create_junction(peer, archive.game_dir, create_target=False)
            links.extend([archive.game_dir, peer])
        else:
            try:
                if root_kind == "broken_symlink":
                    os.symlink(
                        missing_target,
                        archive.game_dir,
                        target_is_directory=True,
                    )
                    links.append(archive.game_dir)
                else:
                    os.symlink(peer, archive.game_dir, target_is_directory=True)
                    os.symlink(
                        archive.game_dir,
                        peer,
                        target_is_directory=True,
                    )
                    links.extend([archive.game_dir, peer])
            except OSError as exc:
                pytest.skip(f"Directory symlinks are unavailable: {exc}")

        process_calls = 0

        def check_process() -> bool:
            nonlocal process_calls
            process_calls += 1
            return False

        service = _CountingInspectionService(
            profile,
            process_checker=check_process,
        )

        with pytest.raises(StalePreviewError) as raised:
            if action == "validate":
                service.validate_preview_token(preview.token)
            else:
                service.apply(preview.token)

        assert type(raised.value) is StalePreviewError
        assert str(raised.value) == "Source archive changed after preview"
        assert process_calls == 0
        assert service.entry_lookup_count == 0
        assert service.body_read_count == 0
        assert _snapshot(preserved) == before
        assert not missing_target.exists()
    finally:
        for link in links:
            _remove_directory_link(link)


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


def _create_junction(
    link: Path,
    target: Path,
    *,
    create_target: bool = True,
) -> None:
    if create_target:
        target.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        check=False,
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert os.path.isjunction(link)


def _remove_directory_link(path: Path) -> None:
    if os.path.isjunction(path):
        os.rmdir(path)
    elif path.is_symlink():
        path.unlink()


def _file_tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


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



@pytest.mark.parametrize(
    "failure_stage",
    ["write", "flush", "fsync", "replace", "directory"],
)
def test_rollback_durability_failure_leaves_manifest_unmarked(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    target_operation = "rollback:0008/0.paz"

    class RollbackDurabilityFailureService(BlackstarTimerService):
        faulted = False
        original_failure: RuntimeError | None = None

        def _inject_fault(self, phase: str) -> None:
            if phase == "after_paz_write":
                self.original_failure = RuntimeError("injected apply failure")
                raise self.original_failure
            return super()._inject_fault(phase)

        def _write_all(
            self,
            handle: BinaryIO,
            data: bytes,
            operation: str,
        ) -> None:
            if (
                failure_stage == "write"
                and operation == target_operation
                and not self.faulted
            ):
                self.faulted = True
                handle.write(data[:max(1, len(data) // 2)])
                raise OSError("injected rollback temp write failure")
            return super()._write_all(handle, data, operation)

        def _flush_file(self, handle: BinaryIO, operation: str) -> None:
            if (
                failure_stage == "flush"
                and operation == target_operation
                and not self.faulted
            ):
                self.faulted = True
                raise OSError("injected rollback temp flush failure")
            return super()._flush_file(handle, operation)

        def _fsync_file(self, handle: BinaryIO, operation: str) -> None:
            if (
                failure_stage == "fsync"
                and operation == target_operation
                and not self.faulted
            ):
                self.faulted = True
                raise OSError("injected rollback temp fsync failure")
            return super()._fsync_file(handle, operation)

        def _replace_path(
            self,
            source: Path,
            destination: Path,
            operation: str,
            *,
            directory_fd: int | None = None,
        ) -> None:
            if (
                failure_stage == "replace"
                and operation == target_operation
                and not self.faulted
            ):
                self.faulted = True
                raise OSError("injected rollback replace failure")

            return super()._replace_path(
                source,
                destination,
                operation,
                directory_fd=directory_fd,
            )

        def _sync_directory(self, path: Path, operation: str) -> None:
            if (
                failure_stage == "directory"
                and operation == "rollback-directory:0008/0.paz"
                and not self.faulted
            ):
                self.faulted = True
                raise OSError("injected rollback directory sync failure")
            return super()._sync_directory(path, operation)

    service = RollbackDurabilityFailureService(profile)
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    with pytest.raises(TimerTransactionError, match="rollback also failed") as raised:
        service.apply(preview.token)

    assert service.faulted is True
    assert raised.value.__cause__ is service.original_failure
    manifest_path, manifest = _only_backup_manifest(archive.game_dir)
    assert manifest["post_apply_hashes"] == {}
    assert manifest["finalized"] is False
    assert manifest["rolled_back"] is False
    for relative, expected in manifest["source_hashes"].items():
        backup_file = manifest_path.parent / Path(relative)
        assert service._hash_file(backup_file) == expected
    assert not list(archive.game_dir.rglob(".*.restore-*"))


def test_rollback_is_durable_before_combined_verification_and_manifest(
    tmp_path: Path,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())

    class RollbackDurabilityOrderService(BlackstarTimerService):
        def __init__(self) -> None:
            super().__init__(profile)
            self.events: list[tuple[str, str]] = []

        def _inject_fault(self, phase: str) -> None:
            if phase == "after_papgt_write":
                raise RuntimeError("injected apply failure")
            return super()._inject_fault(phase)

        def _write_all(
            self,
            handle: BinaryIO,
            data: bytes,
            operation: str,
        ) -> None:
            if operation.startswith("rollback:"):
                self.events.append(("write", operation))
            return super()._write_all(handle, data, operation)

        def _flush_file(self, handle: BinaryIO, operation: str) -> None:
            if operation.startswith("rollback:"):
                self.events.append(("flush", operation))
            return super()._flush_file(handle, operation)

        def _fsync_file(self, handle: BinaryIO, operation: str) -> None:
            if operation.startswith("rollback:"):
                self.events.append(("fsync", operation))
            return super()._fsync_file(handle, operation)

        def _replace_path(
            self,
            source: Path,
            destination: Path,
            operation: str,
            *,
            directory_fd: int | None = None,
        ) -> None:
            if operation.startswith("rollback:"):
                self.events.append(("replace", operation))

            return super()._replace_path(
                source,
                destination,
                operation,
                directory_fd=directory_fd,
            )

        def _sync_directory(self, path: Path, operation: str) -> None:
            if operation.startswith("rollback-directory:"):
                self.events.append(("directory", operation))
            return super()._sync_directory(path, operation)

        def _verify_archive_set(
            self,
            *args: object,
            **kwargs: object,
        ) -> tuple[DetectionReport, dict[str, str]]:
            self.events.append(("verify", "combined"))
            return super()._verify_archive_set(*args, **kwargs)

    service = RollbackDurabilityOrderService()
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    with pytest.raises(TimerTransactionError, match="rolled back"):
        service.apply(preview.token)

    verify_index = service.events.index(("verify", "combined"))
    for relative in ("0008/0.paz", "0008/0.pamt", "meta/0.papgt"):
        operation = f"rollback:{relative}"
        positions = [
            service.events.index((stage, operation))
            for stage in ("write", "flush", "fsync", "replace")
        ]
        directory_position = service.events.index(
            ("directory", f"rollback-directory:{relative}")
        )
        assert positions == sorted(positions)
        assert positions[-1] < directory_position < verify_index
    _assert_unfinalized_rollback_manifest(archive.game_dir)


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
        ("backup_root_parent", relative)
        for relative in (
            "bin64",
            "bin64/SEModLoad",
            "bin64/SEModLoad/Backups",
            "bin64/SEModLoad/Backups/BlackstarTimer",
        )
    ] + [
        ("backup_root", None),
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
        failed_operation: str | None = None
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
                self.failed_operation = operation
                handle.write(data[:max(1, len(data) // 2)])
                raise OSError("injected backup write failure")
            return super()._write_all(handle, data, operation)

        def _flush_file(self, handle: BinaryIO, operation: str) -> None:
            if (
                failure_stage == "backup_flush"
                and operation == f"backup:{target_relative}"
                and not self.failed
            ):
                self.failed = True
                self.failed_operation = operation
                raise OSError("injected backup flush failure")
            return super()._flush_file(handle, operation)

        def _fsync_file(self, handle: BinaryIO, operation: str) -> None:
            should_fail = (
                failure_stage == "backup_fsync"
                and operation == f"backup:{target_relative}"
            ) or (
                failure_stage == "manifest_fsync"
                and operation == "manifest"
            )
            if should_fail and not self.failed:
                self.failed = True
                self.failed_operation = operation
                raise OSError(f"injected {failure_stage} failure")
            return super()._fsync_file(handle, operation)

        def _sync_directory(self, path: Path, operation: str) -> None:
            should_fail = (
                failure_stage == "backup_directory"
                and operation == f"backup-directory:{target_relative}"
            ) or (
                failure_stage == "backup_root_parent"
                and operation == f"backup-root-parent:{target_relative}"
            ) or (
                failure_stage == "backup_root"
                and operation == "backup-root-directory"
            ) or (
                failure_stage == "manifest_directory"
                and operation == "manifest-directory"
            )
            if should_fail and not self.failed:
                self.failed = True
                self.failed_operation = operation
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
    if failure_stage == "backup_directory":
        expected_operation = f"backup-directory:{target_relative}"
    elif failure_stage == "backup_root_parent":
        expected_operation = f"backup-root-parent:{target_relative}"
    elif failure_stage == "backup_root":
        expected_operation = "backup-root-directory"
    elif failure_stage.startswith("backup_"):
        expected_operation = f"backup:{target_relative}"
    elif failure_stage == "manifest_fsync":
        expected_operation = "manifest"
    else:
        expected_operation = "manifest-directory"
    assert service.failed_operation == expected_operation
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
            self.sync_events: list[str] = []
            self.mutation_prerequisites: tuple[set[str], set[str], list[str]] | None = None

        def _fsync_file(self, handle: BinaryIO, operation: str) -> None:
            super()._fsync_file(handle, operation)
            self.synced_files.add(operation)

        def _sync_directory(self, path: Path, operation: str) -> None:
            super()._sync_directory(path, operation)
            self.synced_directories.add(operation)
            self.sync_events.append(operation)

        def _patch_paz_slot(self, *args: object, **kwargs: object) -> None:
            self.mutation_prerequisites = (
                set(self.synced_files),
                set(self.synced_directories),
                list(self.sync_events),
            )
            return super()._patch_paz_slot(*args, **kwargs)

    service = DurabilityOrderService()
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    service.apply(preview.token)

    assert service.mutation_prerequisites is not None
    synced_files, synced_directories, sync_events = service.mutation_prerequisites
    assert {
        "backup:0008/0.paz",
        "backup:0008/0.pamt",
        "backup:meta/0.papgt",
        "manifest",
    } <= synced_files
    assert {
        "backup-root-parent:bin64",
        "backup-root-parent:bin64/SEModLoad",
        "backup-root-parent:bin64/SEModLoad/Backups",
        "backup-root-parent:bin64/SEModLoad/Backups/BlackstarTimer",
        "backup-root-directory",
        "backup-directory:0008/0.paz",
        "backup-directory:0008/0.pamt",
        "backup-directory:meta/0.papgt",
        "manifest-directory",
    } <= synced_directories
    assert sync_events.count("manifest-directory") == 1
    assert "backup-directory" not in sync_events


class _FakeWindowsFunction:
    def __init__(self, callback: Callable[..., int]) -> None:
        self.callback = callback
        self.argtypes: list[object] | None = None
        self.restype: object | None = None

    def __call__(self, *args: object) -> int:
        return self.callback(*args)


@pytest.mark.skipif(timer_module.os.name != "nt", reason="Windows-only API contract")
def test_windows_directory_sync_uses_probed_createfile_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, tuple[object, ...]]] = []
    handle = 123

    class FakeKernel32:
        CreateFileW = _FakeWindowsFunction(
            lambda *args: events.append(("create", args)) or handle
        )
        FlushFileBuffers = _FakeWindowsFunction(
            lambda *args: events.append(("flush", args)) or 1
        )
        CloseHandle = _FakeWindowsFunction(
            lambda *args: events.append(("close", args)) or 1
        )

    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: FakeKernel32())
    archive = make_timer_archive(tmp_path)
    service = BlackstarTimerService(TimerProfile(**archive.profile_kwargs()))

    service._sync_directory(tmp_path, "test-directory")

    assert events == [
        (
            "create",
            (
                str(tmp_path),
                0x0002,
                0x00000001 | 0x00000002 | 0x00000004,
                None,
                3,
                0x02000000,
                None,
            ),
        ),
        ("flush", (handle,)),
        ("close", (handle,)),
    ]


@pytest.mark.skipif(timer_module.os.name != "nt", reason="Windows-only API contract")
@pytest.mark.parametrize("failure_stage", ["open", "flush", "close"])
def test_windows_directory_sync_propagates_win32_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    events: list[str] = []
    handle = 123
    invalid_handle = ctypes.c_void_p(-1).value

    def create_file(*args: object) -> int:
        del args
        events.append("create")
        if failure_stage == "open":
            ctypes.set_last_error(5)
            assert invalid_handle is not None
            return invalid_handle
        return handle

    def flush_file(*args: object) -> int:
        del args
        events.append("flush")
        if failure_stage == "flush":
            ctypes.set_last_error(5)
            return 0
        return 1

    def close_handle(*args: object) -> int:
        del args
        events.append("close")
        if failure_stage == "close":
            ctypes.set_last_error(5)
            return 0
        return 1

    class FakeKernel32:
        CreateFileW = _FakeWindowsFunction(create_file)
        FlushFileBuffers = _FakeWindowsFunction(flush_file)
        CloseHandle = _FakeWindowsFunction(close_handle)

    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: FakeKernel32())
    archive = make_timer_archive(tmp_path)
    service = BlackstarTimerService(TimerProfile(**archive.profile_kwargs()))

    with pytest.raises(OSError, match="test-directory"):
        service._sync_directory(tmp_path, "test-directory")

    if failure_stage == "open":
        assert events == ["create"]
    else:
        assert events == ["create", "flush", "close"]



@pytest.mark.skipif(timer_module.os.name != "nt", reason="Windows-only directory guard")
def test_windows_directory_chain_guard_blocks_swaps_and_allows_child_creation(
    tmp_path: Path,
) -> None:
    archive = make_timer_archive(tmp_path)
    service = BlackstarTimerService(TimerProfile(**archive.profile_kwargs()))
    guarded = archive.game_dir / "guarded-parent"
    guarded.mkdir()
    outside = tmp_path / "outside-directory-guard"
    outside.mkdir()
    assert hasattr(service, "_hold_safe_archive_directory_chain")

    rename_error: OSError | None = None
    remove_error: OSError | None = None
    renamed = guarded.with_name("guarded-parent-renamed")
    with service._hold_safe_archive_directory_chain(
        archive.game_dir,
        guarded,
        "directory-guard-probe",
        create_missing=False,
    ):
        try:
            guarded.rename(renamed)
        except OSError as exc:
            rename_error = exc
        try:
            guarded.rmdir()
        except OSError as exc:
            remove_error = exc
        if not guarded.exists():
            _create_junction(guarded, outside)
        (guarded / "child.bin").write_bytes(b"held-chain-child")

    assert rename_error is not None
    assert rename_error.winerror == 32
    assert remove_error is not None
    assert remove_error.winerror == 32
    assert not os.path.isjunction(guarded)
    assert (guarded / "child.bin").read_bytes() == b"held-chain-child"
    assert _file_tree(outside) == {}
    assert not renamed.exists()
    guarded.rename(renamed)
    renamed.rename(guarded)


@pytest.mark.skipif(timer_module.os.name != "nt", reason="Windows-only directory guard")
def test_windows_directory_guard_rejects_incompatible_existing_handle(
    tmp_path: Path,
) -> None:
    from ctypes import wintypes

    archive = make_timer_archive(tmp_path)
    service = BlackstarTimerService(TimerProfile(**archive.profile_kwargs()))
    guarded = archive.game_dir / "incompatible-parent"
    guarded.mkdir()
    assert hasattr(service, "_hold_safe_archive_directory_chain")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    existing = create_file(
        str(guarded),
        0x00010000,
        0x00000001 | 0x00000002 | 0x00000004,
        None,
        3,
        0x02000000 | 0x00200000,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    existing_value = (
        existing
        if isinstance(existing, int)
        else ctypes.cast(existing, ctypes.c_void_p).value
    )
    assert existing_value not in (None, invalid_handle)

    try:
        with pytest.raises(BackupConflictError) as raised:
            with service._hold_safe_archive_directory_chain(
                archive.game_dir,
                guarded,
                "incompatible-directory-guard",
                create_missing=False,
            ):
                pass
        assert isinstance(raised.value.__cause__, OSError)
        assert raised.value.__cause__.winerror == 32
    finally:
        assert close_handle(existing)

    released = guarded.with_name("incompatible-parent-released")
    guarded.rename(released)
    released.rename(guarded)


@pytest.mark.skipif(timer_module.os.name != "nt", reason="Windows-only junction contract")
@pytest.mark.parametrize(
    "relative",
    [
        "bin64",
        "bin64/SEModLoad",
        "bin64/SEModLoad/Backups",
        "bin64/SEModLoad/Backups/BlackstarTimer",
    ],
)
def test_apply_rejects_backup_hierarchy_junctions(
    tmp_path: Path,
    relative: str,
) -> None:
    archive = make_timer_archive(tmp_path)
    service = BlackstarTimerService(TimerProfile(**archive.profile_kwargs()))
    preview = service.preview(archive.game_dir)
    assert preview.token is not None
    paths = _timer_archive_paths(archive.game_dir)
    before = _archive_contents(paths)
    outside = tmp_path / ("outside-" + relative.replace("/", "-"))
    link = archive.game_dir / Path(relative)
    link.parent.mkdir(parents=True, exist_ok=True)
    _create_junction(link, outside)

    with pytest.raises(BackupConflictError, match="reparse"):
        service.apply(preview.token)

    assert _file_tree(outside) == {}
    assert _archive_contents(paths) == before


@pytest.mark.skipif(timer_module.os.name != "nt", reason="Windows-only junction contract")
def test_apply_rejects_timestamp_directory_swapped_to_junction(
    tmp_path: Path,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    paths = _timer_archive_paths(archive.game_dir)
    before = _archive_contents(paths)
    outside = tmp_path / "outside-timestamp"
    outside.mkdir()

    class TimestampSwapService(BlackstarTimerService):
        swapped = False

        def _sync_directory(self, path: Path, operation: str) -> None:
            super()._sync_directory(path, operation)
            if operation == "backup-root-directory" and not self.swapped:
                candidates = [item for item in path.iterdir() if item.is_dir()]
                assert len(candidates) == 1
                candidates[0].rmdir()
                _create_junction(candidates[0], outside)
                self.swapped = True

    service = TimestampSwapService(profile)
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    with pytest.raises(BackupConflictError, match="reparse"):
        service.apply(preview.token)

    assert service.swapped is True
    assert _file_tree(outside) == {}
    assert _archive_contents(paths) == before


@pytest.mark.skipif(timer_module.os.name != "nt", reason="Windows-only junction contract")
def test_backup_set_guard_blocks_swap_before_backup_copy(
    tmp_path: Path,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    paths = _timer_archive_paths(archive.game_dir)
    before = _archive_contents(paths)
    outside = tmp_path / "outside-copy-swap"
    outside.mkdir()

    class CopySwapService(BlackstarTimerService):
        blocked = False
        swapped = False

        def _copy_backup_file(
            self,
            game: Path,
            source: Path,
            destination: Path,
            operation: str,
            *,
            held_backup_root: Path | None = None,
            held_backup_root_fd: int | None = None,
        ) -> None:
            if not self.swapped:
                backup_dir = destination.parents[1]
                try:
                    backup_dir.rmdir()
                except PermissionError:
                    self.blocked = True
                    raise
                _create_junction(backup_dir, outside)
                self.swapped = True
            return super()._copy_backup_file(
                game,
                source,
                destination,
                operation,
                held_backup_root=held_backup_root,
                held_backup_root_fd=held_backup_root_fd,
            )

    service = CopySwapService(profile)
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    with pytest.raises(PermissionError):
        service.apply(preview.token)

    assert service.blocked is True
    assert service.swapped is False
    assert _file_tree(outside) == {}
    assert _archive_contents(paths) == before



@pytest.mark.skipif(timer_module.os.name != "nt", reason="Windows-only swap contract")
@pytest.mark.parametrize("swap_level", ["timestamp", "file_parent"])
def test_backup_destination_chain_blocks_swap_before_native_open(
    tmp_path: Path,
    swap_level: str,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    outside = tmp_path / f"outside-pre-open-{swap_level}"
    outside.mkdir()

    class DestinationSwapService(BlackstarTimerService):
        attempted = False
        swap_error: OSError | None = None

        def _before_backup_destination_open(
            self,
            destination: Path,
            operation: str,
        ) -> None:
            if self.attempted or operation != "backup:0008/0.paz":
                return
            self.attempted = True
            swap_path = (
                destination.parents[1]
                if swap_level == "timestamp"
                else destination.parent
            )
            moved = swap_path.with_name(swap_path.name + "-moved")
            try:
                swap_path.rename(moved)
            except OSError as exc:
                self.swap_error = exc
                return
            _create_junction(swap_path, outside)

    service = DestinationSwapService(profile)
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    report = service.apply(preview.token)

    assert report.status is TimerStatus.APPLIED
    assert service.attempted is True
    assert service.swap_error is not None
    assert service.swap_error.winerror == 32
    assert _file_tree(outside) == {}
    assert not list(archive.game_dir.rglob("*-moved"))



@pytest.mark.skipif(timer_module.os.name != "nt", reason="Windows-only backup-set guard")
@pytest.mark.parametrize(
    "phase",
    ["after-paz-verification", "before-manifest"],
)
def test_backup_set_guard_spans_all_files_manifest_and_final_check(
    tmp_path: Path,
    phase: str,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())

    class BackupSetSwapService(BlackstarTimerService):
        attempted = False
        release_checked = False
        rename_error: OSError | None = None

        def _before_backup_set_step(
            self,
            current_phase: str,
            backup_dir: Path,
        ) -> None:
            if self.attempted or current_phase != phase:
                return
            self.attempted = True
            moved = backup_dir.with_name(backup_dir.name + "-moved")
            try:
                backup_dir.rename(moved)
            except OSError as exc:
                self.rename_error = exc
                return
            backup_dir.mkdir()

        def _before_backup_guard_release(
            self,
            backup_dir: Path,
            source_hashes: dict[str, str],
        ) -> None:
            manifest_path = backup_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert manifest["source_hashes"] == source_hashes
            for relative, expected in source_hashes.items():
                backup_file = backup_dir / Path(relative)
                assert backup_file.is_file()
                assert self._hash_file(backup_file) == expected
            self.release_checked = True

    service = BackupSetSwapService(profile)
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    report = service.apply(preview.token)

    assert report.status is TimerStatus.APPLIED
    assert service.attempted is True
    assert service.release_checked is True
    assert service.rename_error is not None
    assert service.rename_error.winerror == 32
    manifest_path, manifest = _only_backup_manifest(archive.game_dir)
    assert manifest["finalized"] is True
    for relative, expected in manifest["source_hashes"].items():
        assert service._hash_file(manifest_path.parent / Path(relative)) == expected
    assert not list(manifest_path.parent.parent.glob("*-moved"))


@pytest.mark.skipif(timer_module.os.name != "nt", reason="Windows-only junction contract")
def test_resolved_game_root_remains_valid_when_supplied_through_junction(
    tmp_path: Path,
) -> None:
    archive = make_timer_archive(tmp_path / "real")
    alias = tmp_path / "game-alias"
    _create_junction(alias, archive.game_dir)
    service = BlackstarTimerService(TimerProfile(**archive.profile_kwargs()))

    preview = service.preview(alias)
    assert preview.token is not None
    assert preview.token.game_dir == archive.game_dir.resolve(strict=True)

    result = service.apply(preview.token)

    assert result.status is TimerStatus.APPLIED
    assert result.game_dir == archive.game_dir.resolve(strict=True)


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


@pytest.mark.parametrize(
    "tamper_stage",
    [
        "before_pamt",
        "during_pamt",
        "before_papgt",
        "during_papgt",
    ],
)
def test_apply_detects_live_metadata_tamper_and_restores_originals(
    tmp_path: Path,
    tamper_stage: str,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    paths = _timer_archive_paths(archive.game_dir)
    before = _archive_contents(paths)
    pamt_path, papgt_path = paths[1], paths[2]
    tampered = False
    external_bytes: bytes | None = None

    def tamper(path: Path) -> None:
        nonlocal tampered, external_bytes
        payload = bytearray(path.read_bytes())
        payload[-1] ^= 0x5A
        external_bytes = bytes(payload)
        path.write_bytes(external_bytes)
        tampered = True

    class MetadataTamperService(BlackstarTimerService):
        def _build_metadata_bytes(
            self,
            *args: object,
            **kwargs: object,
        ) -> tuple[bytes, bytes]:
            result = super()._build_metadata_bytes(*args, **kwargs)
            if tamper_stage == "before_pamt" and not tampered:
                tamper(pamt_path)
            return result

        def _write_all(
            self,
            handle: BinaryIO,
            data: bytes,
            operation: str,
        ) -> None:
            super()._write_all(handle, data, operation)
            if tamper_stage == "during_pamt" and operation == "pamt" and not tampered:
                tamper(pamt_path)
            if (
                tamper_stage == "during_papgt"
                and operation == "papgt"
                and not tampered
            ):
                tamper(papgt_path)

        def _inject_fault(self, phase: str) -> None:
            if (
                tamper_stage == "before_papgt"
                and phase == "after_pamt_write"
                and not tampered
            ):
                tamper(papgt_path)
            return super()._inject_fault(phase)

    service = MetadataTamperService(profile)
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    with pytest.raises(TimerTransactionError, match="rolled back"):
        service.apply(preview.token)

    assert tampered is True
    assert external_bytes is not None
    assert external_bytes not in _archive_contents(paths).values()
    assert _archive_contents(paths) == before
    _manifest_path, manifest = _only_backup_manifest(archive.game_dir)
    assert manifest["finalized"] is False
    assert manifest["rolled_back"] is True
    assert "metadata" in manifest["rollback_reason"].lower()



@pytest.mark.skipif(timer_module.os.name != "nt", reason="Windows-only sharing contract")
@pytest.mark.parametrize("relative", ["0008/0.pamt", "meta/0.papgt"])
def test_metadata_guard_blocks_writer_until_native_replace(
    tmp_path: Path,
    relative: str,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    target = archive.game_dir / Path(relative)

    class GuardWindowService(BlackstarTimerService):
        attempted = False
        writer_error: int | None = None

        def _before_metadata_replace(self, path: Path, operation: str) -> None:
            if self.attempted or path != target:
                return
            from ctypes import wintypes

            self.attempted = True
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            create_file = kernel32.CreateFileW
            create_file.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ]
            create_file.restype = wintypes.HANDLE
            writer = create_file(
                str(path),
                0x40000000,
                0x00000001 | 0x00000002 | 0x00000004,
                None,
                3,
                0,
                None,
            )
            writer_value = (
                writer
                if isinstance(writer, int)
                else ctypes.cast(writer, ctypes.c_void_p).value
            )
            if writer_value in (None, ctypes.c_void_p(-1).value):
                self.writer_error = ctypes.get_last_error()
                return
            service._close_windows_handle(writer, operation)

    service = GuardWindowService(profile)
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    report = service.apply(preview.token)

    assert report.status is TimerStatus.APPLIED
    assert service.attempted is True
    assert service.writer_error is not None
    assert service.writer_error == 32
    _manifest_path, manifest = _only_backup_manifest(archive.game_dir)
    assert manifest["finalized"] is True
    assert manifest["rolled_back"] is False



@pytest.mark.skipif(timer_module.os.name != "nt", reason="Windows-only identity contract")
def test_metadata_guard_detects_path_replacement_before_native_replace(
    tmp_path: Path,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    paths = _timer_archive_paths(archive.game_dir)
    before = _archive_contents(paths)
    target = paths[1]

    class IdentitySwapService(BlackstarTimerService):
        swapped = False

        def _before_metadata_replace(self, path: Path, operation: str) -> None:
            if self.swapped or path != target:
                return
            replacement = path.with_name(".identity-swap.pamt")
            payload = bytearray(path.read_bytes())
            payload[-1] ^= 0x7F
            replacement.write_bytes(payload)
            self._replace_windows_file(replacement, path, "identity-swap")
            self.swapped = True

    service = IdentitySwapService(profile)
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    with pytest.raises(TimerTransactionError, match="rolled back"):
        service.apply(preview.token)

    assert service.swapped is True
    assert _archive_contents(paths) == before
    _assert_unfinalized_rollback_manifest(archive.game_dir)



@pytest.mark.skipif(timer_module.os.name != "nt", reason="Windows-only exchange contract")
@pytest.mark.parametrize("relative", ["0008/0.pamt", "meta/0.papgt"])
def test_metadata_exchange_preserves_concurrent_replacement(
    tmp_path: Path,
    relative: str,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    paths = _timer_archive_paths(archive.game_dir)
    before = _archive_contents(paths)
    target = archive.game_dir / Path(relative)
    concurrent = b"concurrent-metadata-" + relative.encode("ascii")

    class ConcurrentExchangeService(BlackstarTimerService):
        exchanged = False

        def _before_metadata_exchange(self, path: Path, operation: str) -> None:
            if self.exchanged or path != target:
                return
            replacement = path.with_name(".concurrent-replacement")
            replacement.write_bytes(concurrent)
            self._replace_windows_file(
                replacement,
                path,
                "concurrent-exchange-seam",
            )
            self.exchanged = True

    service = ConcurrentExchangeService(profile)
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    with pytest.raises(TimerTransactionError, match="concurrent metadata"):
        service.apply(preview.token)

    assert service.exchanged is True
    assert target.read_bytes() == concurrent
    for path, expected in before.items():
        if path != target:
            assert path.read_bytes() == expected
    _manifest_path, manifest = _only_backup_manifest(archive.game_dir)
    assert manifest["finalized"] is False
    assert manifest["rolled_back"] is False
    assert not list(target.parent.glob(".*.displaced-*"))
    assert not list(target.parent.glob(".*.timer-*"))


@pytest.mark.skipif(timer_module.os.name != "nt", reason="Windows-only exchange contract")
@pytest.mark.parametrize(
    "failure_stage",
    ["backup_file", "replace", "verify", "restore", "cleanup"],
)
def test_metadata_exchange_faults_preserve_truthful_recovery_state(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    paths = _timer_archive_paths(archive.game_dir)
    before = _archive_contents(paths)
    target = paths[1]
    concurrent = b"concurrent-restore-failure"

    class ExchangeFaultService(BlackstarTimerService):
        faulted = False
        exchanged = False

        def _before_metadata_exchange(self, path: Path, operation: str) -> None:
            if failure_stage != "restore" or self.exchanged or path != target:
                return
            replacement = path.with_name(".concurrent-fault")
            replacement.write_bytes(concurrent)
            self._replace_windows_file(
                replacement,
                path,
                "concurrent-restore-fault",
            )
            self.exchanged = True

        def _metadata_displaced_path(
            self,
            path: Path,
            operation: str,
        ) -> Path:
            if failure_stage == "backup_file" and not self.faulted:
                self.faulted = True
                raise OSError("injected displaced backup-file creation failure")
            return super()._metadata_displaced_path(path, operation)

        def _replace_windows_file(
            self,
            source: Path,
            destination: Path,
            operation: str,
            backup_path: Path | None = None,
        ) -> None:
            if (
                failure_stage == "replace"
                and backup_path is not None
                and not self.faulted
            ):
                self.faulted = True
                raise OSError("injected metadata ReplaceFileW failure")
            return super()._replace_windows_file(
                source,
                destination,
                operation,
                backup_path,
            )

        def _read_metadata_bytes(
            self,
            source: Path | BinaryIO,
            operation: str,
        ) -> bytes:
            if (
                failure_stage == "verify"
                and operation.startswith("metadata-displaced-verification:")
                and not self.faulted
            ):
                self.faulted = True
                raise OSError("injected displaced verification failure")
            return super()._read_metadata_bytes(source, operation)

        def _restore_displaced_metadata(
            self,
            displaced: Path,
            destination: Path,
            operation: str,
        ) -> None:
            if failure_stage == "restore" and not self.faulted:
                self.faulted = True
                raise OSError("injected displaced restore failure")
            return super()._restore_displaced_metadata(
                displaced,
                destination,
                operation,
            )

        def _remove_displaced_metadata(
            self,
            displaced: Path,
            operation: str,
        ) -> None:
            if failure_stage == "cleanup" and not self.faulted:
                self.faulted = True
                raise OSError("injected displaced cleanup failure")
            return super()._remove_displaced_metadata(displaced, operation)

    service = ExchangeFaultService(profile)
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    with pytest.raises(TimerTransactionError) as raised:
        service.apply(preview.token)

    assert service.faulted is True
    assert raised.value.__cause__ is not None
    _manifest_path, manifest = _only_backup_manifest(archive.game_dir)
    assert manifest["finalized"] is False
    if failure_stage == "restore":
        assert manifest["rolled_back"] is False
        displaced = list(target.parent.glob(".*.displaced-*"))
        assert len(displaced) == 1
        assert displaced[0].read_bytes() == concurrent
    else:
        assert manifest["rolled_back"] is True
        assert _archive_contents(paths) == before
        assert not list(target.parent.glob(".*.displaced-*"))
    assert not list(target.parent.glob(".*.timer-*"))


@pytest.mark.skipif(timer_module.os.name != "nt", reason="Windows-only sharing contract")
def test_existing_metadata_writer_forces_apply_rollback(tmp_path: Path) -> None:
    archive = make_timer_archive(tmp_path)
    profile = TimerProfile(**archive.profile_kwargs())
    paths = _timer_archive_paths(archive.game_dir)
    before = _archive_contents(paths)
    service = BlackstarTimerService(profile)
    preview = service.preview(archive.game_dir)
    assert preview.token is not None

    with paths[1].open("r+b"):
        with pytest.raises(TimerTransactionError, match="rolled back"):
            service.apply(preview.token)

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
            self.large_bulk_passes: Counter[str] = Counter()
            self.metadata_file_passes: Counter[str] = Counter()
            self.metadata_reads: Counter[str] = Counter()
            self.metadata_parses: Counter[str] = Counter()
            self.bounded_paz_reads: Counter[str] = Counter()
            self.control_reads: Counter[str] = Counter()

        def reset_counts(self) -> None:
            super().reset_counts()
            self.identity_stream_calls = 0
            self.active_identity_streams = 0
            self.peak_identity_streams = 0
            self.backup_copy_passes = 0
            self.large_bulk_passes.clear()
            self.metadata_file_passes.clear()
            self.metadata_reads.clear()
            self.metadata_parses.clear()
            self.bounded_paz_reads.clear()
            self.control_reads.clear()

        def _hash_file(
            self,
            path: Path,
            operation: str | None = None,
        ) -> str:
            label = operation or "unlabeled"
            counter = (
                self.large_bulk_passes
                if path.suffix == ".paz"
                else self.metadata_file_passes
            )
            counter[f"hash:{label}"] += 1
            return super()._hash_file(path, operation)

        def _copy_backup_file(
            self,
            game: Path,
            source: Path,
            destination: Path,
            operation: str,
            *,
            held_backup_root: Path | None = None,
            held_backup_root_fd: int | None = None,
        ) -> None:
            self.backup_copy_passes += 1
            counter = (
                self.large_bulk_passes
                if source.suffix == ".paz"
                else self.metadata_file_passes
            )
            counter[f"copy:{operation}"] += 1
            return super()._copy_backup_file(
                game,
                source,
                destination,
                operation,
                held_backup_root=held_backup_root,
                held_backup_root_fd=held_backup_root_fd,
            )

        def _stream_paz_identity(
            self,
            *args: object,
            **kwargs: object,
        ) -> object:
            operation = str(kwargs.get("operation", "unlabeled"))
            self.large_bulk_passes[f"identity:{operation}"] += 1
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

        def _read_metadata_bytes(
            self,
            path: Path,
            operation: str,
        ) -> bytes:
            self.metadata_reads[operation] += 1
            return super()._read_metadata_bytes(path, operation)

        def _parse_pamt_bytes(
            self,
            data: bytes,
            operation: str,
        ) -> dict:
            self.metadata_parses[f"pamt:{operation}"] += 1
            return super()._parse_pamt_bytes(data, operation)

        def _parse_papgt_bytes(
            self,
            data: bytes,
            operation: str,
        ) -> dict:
            self.metadata_parses[f"papgt:{operation}"] += 1
            return super()._parse_papgt_bytes(data, operation)

        def _read_paz_entry(
            self,
            path: Path,
            offset: int,
            size: int,
            operation: str,
        ) -> bytes:
            self.bounded_paz_reads[operation] += 1
            return super()._read_paz_entry(path, offset, size, operation)

        def _read_paz_slot(
            self,
            handle: BinaryIO,
            size: int,
            operation: str,
        ) -> bytes:
            self.bounded_paz_reads[operation] += 1
            return super()._read_paz_slot(handle, size, operation)

        def _read_manifest(
            self,
            path: Path,
            operation: str | None = None,
        ) -> dict:
            self.control_reads[operation or "unlabeled"] += 1
            if operation is None:
                return super()._read_manifest(path)
            return super()._read_manifest(path, operation)

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
    assert service.large_bulk_passes == Counter(
        {
            "hash:source-revalidation:0008/0.paz": 1,
            "copy:backup:0008/0.paz": 1,
            "identity:backup-verification:0008/0.paz": 1,
            "identity:post-write-verification:0008/0.paz": 1,
        }
    )
    assert service.metadata_file_passes == Counter(
        {
            "hash:source-revalidation:0008/0.pamt": 1,
            "hash:source-revalidation:meta/0.papgt": 1,
            "hash:backup-verification:0008/0.pamt": 1,
            "hash:backup-verification:meta/0.papgt": 1,
            "copy:backup:0008/0.pamt": 1,
            "copy:backup:meta/0.papgt": 1,
        }
    )
    assert service.metadata_reads == Counter(
        {
            "source-inspection:0008/0.pamt": 1,
            "metadata-build:0008/0.pamt": 1,
            "metadata-build:meta/0.papgt": 1,
            "metadata-guard-after-paz:0008/0.pamt": 1,
            "metadata-guard-after-paz:meta/0.papgt": 1,
            "metadata-guard-before-replace:0008/0.pamt": 1,
            "metadata-guard-before-replace:meta/0.papgt": 1,
            "metadata-displaced-verification:pamt": 1,
            "metadata-displaced-verification:papgt": 1,
            "post-write-verification:0008/0.pamt": 1,
            "post-write-verification:meta/0.papgt": 1,
        }
    )
    assert service.metadata_parses == Counter(
        {
            "pamt:source-inspection:0008/0.pamt": 1,
            "pamt:metadata-build:0008/0.pamt": 1,
            "pamt:metadata-build:candidate:0008/0.pamt": 1,
            "papgt:metadata-build:meta/0.papgt": 1,
            "papgt:metadata-build:candidate:meta/0.papgt": 1,
            "pamt:post-write-verification:0008/0.pamt": 1,
            "papgt:post-write-verification:meta/0.papgt": 1,
        }
    )
    assert service.bounded_paz_reads == Counter(
        {
            "source-inspection:0008/0.paz-entry": 1,
            "paz-patch:0008/0.paz-slot": 1,
        }
    )
    assert service.control_reads == Counter({"manifest-finalization": 1})
    assert service.identity_stream_calls == 2
    assert service.peak_identity_streams == 1
    assert service.backup_copy_passes == 3
    assert service.hash_call_count == 5
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
