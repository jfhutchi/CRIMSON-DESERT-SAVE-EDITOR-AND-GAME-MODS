from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import BinaryIO, Callable, Mapping

import crimson_rs

log = logging.getLogger(__name__)


class TimerStatus(str, Enum):
    VANILLA = "vanilla"
    APPLIED = "applied"
    UNKNOWN = "unknown"
    PARTIAL = "partial"
    BACKUP_CONFLICT = "backup_conflict"
    GAME_RUNNING = "game_running"


class StalePreviewError(RuntimeError):
    """Raised when an archive changed after a successful preview."""


class TimerTransactionError(RuntimeError):
    """Raised after an Apply failure has been rolled back."""


class BackupConflictError(RuntimeError):
    """Raised when Restore cannot prove ownership of the current files."""


class GameRunningError(RuntimeError):
    """Raised when an archive write is requested while the game is open."""


class _ArchiveSourceError(RuntimeError):
    """Wraps only source-inspection errors translated by legacy detection."""


def is_crimson_desert_running() -> bool:
    if os.name != "nt":
        return False
    completed = subprocess.run(
        [
            "tasklist",
            "/FI",
            "IMAGENAME eq CrimsonDesert.exe",
            "/FO",
            "CSV",
            "/NH",
        ],
        capture_output=True,
        text=True,
        check=True,
        creationflags=0x08000000,
    )
    return '"crimsondesert.exe"' in completed.stdout.lower()


@dataclass(frozen=True)
class TimerProfile:
    profile_id: str
    group_name: str
    directory: str
    file_name: str
    entry_offset: int
    vanilla_compressed_size: int
    uncompressed_size: int
    vanilla_body_sha256: str
    applied_body_sha256: str
    cooldown_offset: int
    duration_offset: int
    vanilla_cooldown_seconds: int
    vanilla_duration_seconds: int
    preset_cooldown_seconds: int
    preset_duration_seconds: int
    compression: int = 2
    crypto: int = 0

    @property
    def archive_path(self) -> str:
        directory = self.directory.strip("/")
        return f"{directory}/{self.file_name}" if directory else self.file_name


@dataclass(frozen=True)
class DetectionReport:
    status: TimerStatus
    reason: str
    profile_id: str
    game_dir: Path
    body_sha256: str | None = None
    cooldown_seconds: int | None = None
    duration_seconds: int | None = None
    entry_offset: int | None = None
    compressed_size: int | None = None
    uncompressed_size: int | None = None


@dataclass(frozen=True)
class ArchiveFileHash:
    relative_path: str
    sha256: str


@dataclass(frozen=True)
class PreviewToken:
    profile_id: str
    game_dir: Path
    archive_hashes: tuple[ArchiveFileHash, ...]
    source_body_sha256: str
    candidate_body_sha256: str
    entry_offset: int
    source_compressed_size: int
    candidate_compressed_size: int


@dataclass(frozen=True)
class _ArchiveEntry:
    chunk_offset: int
    compressed_size: int
    uncompressed_size: int
    chunk_id: int
    compression: int
    crypto: int

    @classmethod
    def from_mapping(cls, entry: Mapping[str, object]) -> _ArchiveEntry:
        return cls(
            chunk_offset=int(entry["chunk_offset"]),
            compressed_size=int(entry["compressed_size"]),
            uncompressed_size=int(entry["uncompressed_size"]),
            chunk_id=int(entry["chunk_id"]),
            compression=int(entry["compression"]),
            crypto=int(entry["crypto"]),
        )


@dataclass(frozen=True)
class _PazIdentity:
    sha256: str
    source_sha256: str
    checksum: int
    size: int
    entry_bytes: bytes | None
    source_entry_sha256: str


class _JenkinsChecksum:
    _mask = 0xFFFFFFFF
    _triple = struct.Struct("<III")

    def __init__(self, length: int) -> None:
        self._length = length
        self._seen = 0
        self._processed = 0
        self._tail = bytearray()
        seed = (length + 0xDEBA1DCD) & self._mask
        self._a = self._b = self._c = seed

    @classmethod
    def _rotate(cls, value: int, count: int) -> int:
        return (
            (value << count) | (value >> (32 - count))
        ) & cls._mask

    def _mix_block(self, block: bytes | memoryview) -> None:
        word_a, word_b, word_c = self._triple.unpack(block)
        a = (self._a + word_a) & self._mask
        b = (self._b + word_b) & self._mask
        c = (self._c + word_c) & self._mask
        a = ((a - c) ^ self._rotate(c, 4)) & self._mask
        c = (c + b) & self._mask
        b = ((b - a) ^ self._rotate(a, 6)) & self._mask
        a = (a + c) & self._mask
        c = ((c - b) ^ self._rotate(b, 8)) & self._mask
        b = (b + a) & self._mask
        a = ((a - c) ^ self._rotate(c, 16)) & self._mask
        c = (c + b) & self._mask
        b = ((b - a) ^ self._rotate(a, 19)) & self._mask
        a = (a + c) & self._mask
        c = ((c - b) ^ self._rotate(b, 4)) & self._mask
        b = (b + a) & self._mask
        self._a, self._b, self._c = a, b, c

    def update(self, data: bytes) -> None:
        if self._seen + len(data) > self._length:
            raise ValueError("Checksum stream exceeded its declared length")
        self._seen += len(data)
        view = memoryview(data)
        offset = 0

        if self._tail and self._processed + 12 < self._length:
            needed = 12 - len(self._tail)
            take = min(needed, len(view))
            self._tail.extend(view[:take])
            offset += take
            if len(self._tail) == 12:
                self._mix_block(self._tail)
                self._processed += 12
                self._tail.clear()

        while (
            offset + 12 <= len(view)
            and self._processed + 12 < self._length
        ):
            self._mix_block(view[offset:offset + 12])
            self._processed += 12
            offset += 12

        if offset < len(view):
            self._tail.extend(view[offset:])

    def digest(self) -> int:
        if self._seen != self._length:
            raise ValueError("Checksum stream ended before its declared length")
        if not self._tail:
            return self._c
        if len(self._tail) > 12:
            raise ValueError("Checksum tail exceeds one block")

        padded = bytes(self._tail) + b"\x00" * (12 - len(self._tail))
        word_a, word_b, word_c = self._triple.unpack(padded)
        a = (self._a + word_a) & self._mask
        b = (self._b + word_b) & self._mask
        c = (self._c + word_c) & self._mask
        c = ((c ^ b) - self._rotate(b, 14)) & self._mask
        a = ((a ^ c) - self._rotate(c, 11)) & self._mask
        b = ((b ^ a) - self._rotate(a, 25)) & self._mask
        c = ((c ^ b) - self._rotate(b, 16)) & self._mask
        a = ((a ^ c) - self._rotate(c, 4)) & self._mask
        b = ((b ^ a) - self._rotate(a, 14)) & self._mask
        c = ((c ^ b) - self._rotate(b, 24)) & self._mask
        return c


@dataclass(frozen=True)
class _ArchiveInspection:
    report: DetectionReport
    entry: _ArchiveEntry
    body: bytes
    paths: tuple[Path, Path, Path]


@dataclass(frozen=True)
class PreviewReport:
    status: TimerStatus
    reason: str
    profile_id: str
    game_dir: Path
    token: PreviewToken | None
    cooldown_before: int | None
    cooldown_after: int | None
    duration_before: int | None
    duration_after: int | None
    source_body_sha256: str | None
    candidate_body_sha256: str | None
    candidate_compressed_size: int | None
    slot_capacity: int | None


@dataclass(frozen=True)
class TransactionReport:
    status: TimerStatus
    action: str
    changed: bool
    reason: str
    profile_id: str
    game_dir: Path
    backup_dir: Path | None
    source_body_sha256: str | None
    candidate_body_sha256: str | None
    source_compressed_size: int | None
    candidate_compressed_size: int | None
    cooldown_seconds: int | None
    duration_seconds: int | None


BLACKSTAR_114_PROFILE = TimerProfile(
    profile_id="blackstar-timer-114-v1",
    group_name="0008",
    directory="gamedata",
    file_name="characterinfo.pabgb",
    entry_offset=2_381_376,
    vanilla_compressed_size=1_194_691,
    uncompressed_size=26_431_464,
    vanilla_body_sha256=(
        "e234565b744fb1bb304547b5883cf9249c6cfff54c034c2611a87da26d8324d2"
    ),
    applied_body_sha256=(
        "c90f6689c0aa757efa702e51669be8ff9ff0ab58a4393bc220ee390903fa1402"
    ),
    cooldown_offset=25_579_991,
    duration_offset=25_579_999,
    vanilla_cooldown_seconds=3600,
    vanilla_duration_seconds=600,
    preset_cooldown_seconds=1,
    preset_duration_seconds=1800,
)


class BlackstarTimerService:
    def __init__(
        self,
        profile: TimerProfile = BLACKSTAR_114_PROFILE,
        fault_injector: Callable[[str], None] | None = None,
        process_checker: Callable[[], bool] | None = None,
    ) -> None:
        self.profile = profile
        self._fault_injector = fault_injector
        self._process_checker = process_checker or is_crimson_desert_running

    def detect(self, game_dir: str | Path) -> DetectionReport:
        game = Path(game_dir).expanduser().resolve()
        process_report = self._process_report(game)
        if process_report is not None:
            return process_report
        try:
            return self._inspect(game).report
        except _ArchiveSourceError as exc:
            return self._report(
                TimerStatus.UNKNOWN,
                game,
                f"Archive compatibility check failed: {exc}",
            )

    def preview(
        self,
        game_dir: str | Path,
        progress: Callable[[str, int], None] | None = None,
    ) -> PreviewReport:
        self._emit_progress(progress, "process_check", 5)
        game = Path(game_dir).expanduser().resolve()
        process_report = self._process_report(game)
        inspection = None
        if process_report is not None:
            detection = process_report
        else:
            try:
                inspection = self._inspect(game)
                detection = inspection.report
            except _ArchiveSourceError as exc:
                detection = self._report(
                    TimerStatus.UNKNOWN,
                    game,
                    f"Archive compatibility check failed: {exc}",
                )
        if detection.status is not TimerStatus.VANILLA:
            return PreviewReport(
                status=detection.status,
                reason=detection.reason,
                profile_id=self.profile.profile_id,
                game_dir=detection.game_dir,
                token=None,
                cooldown_before=detection.cooldown_seconds,
                cooldown_after=None,
                duration_before=detection.duration_seconds,
                duration_after=None,
                source_body_sha256=detection.body_sha256,
                candidate_body_sha256=None,
                candidate_compressed_size=None,
                slot_capacity=detection.compressed_size,
            )
        if inspection is None or detection.body_sha256 is None:
            raise ValueError("Vanilla detection is missing its archive inspection")

        self._emit_progress(progress, "pamt_lookup", 20)
        entry = inspection.entry
        source = inspection.body
        self._emit_progress(progress, "decompression", 40)
        candidate = self._build_candidate(source)
        candidate_hash = hashlib.sha256(candidate).hexdigest()
        if candidate_hash != self.profile.applied_body_sha256:
            raise ValueError(
                "Candidate body hash does not match the enrolled applied schema"
            )
        candidate_compressed = bytes(
            crimson_rs.compress_data(candidate, entry.compression)
        )
        self._emit_progress(progress, "candidate_compression", 70)
        slot_capacity = entry.compressed_size
        if len(candidate_compressed) > slot_capacity:
            raise ValueError(
                "Candidate compressed stream does not fit the enrolled PAZ slot"
            )
        verified = self._decompress_stream(
            candidate_compressed,
            entry.compression,
            entry.uncompressed_size,
        )
        if verified != candidate:
            raise ValueError("Candidate failed independent compression verification")
        self._emit_progress(progress, "candidate_verification", 90)
        token = PreviewToken(
            profile_id=self.profile.profile_id,
            game_dir=detection.game_dir,
            archive_hashes=tuple(
                ArchiveFileHash(
                    relative_path=path.relative_to(detection.game_dir).as_posix(),
                    sha256=self._hash_file(path),
                )
                for path in inspection.paths
            ),
            source_body_sha256=detection.body_sha256,
            candidate_body_sha256=candidate_hash,
            entry_offset=entry.chunk_offset,
            source_compressed_size=entry.compressed_size,
            candidate_compressed_size=len(candidate_compressed),
        )
        return PreviewReport(
            status=TimerStatus.VANILLA,
            reason="Verified preview; Apply is enabled for this exact source",
            profile_id=self.profile.profile_id,
            game_dir=detection.game_dir,
            token=token,
            cooldown_before=detection.cooldown_seconds,
            cooldown_after=self.profile.preset_cooldown_seconds,
            duration_before=detection.duration_seconds,
            duration_after=self.profile.preset_duration_seconds,
            source_body_sha256=detection.body_sha256,
            candidate_body_sha256=candidate_hash,
            candidate_compressed_size=len(candidate_compressed),
            slot_capacity=slot_capacity,
        )

    def _normalize_token_archive_hashes(
        self,
        game: Path,
        archive_hashes: tuple[ArchiveFileHash, ...],
    ) -> dict[str, str]:
        expected_hashes: dict[str, str] = {}
        for expected in archive_hashes:
            try:
                path = self._contained_path(game, expected.relative_path)
            except BackupConflictError as exc:
                raise StalePreviewError(str(exc)) from exc
            relative = path.relative_to(game).as_posix()
            if relative in expected_hashes:
                raise StalePreviewError("Source archive changed after preview")
            expected_hashes[relative] = expected.sha256
        return expected_hashes

    def validate_preview_token(self, token: PreviewToken) -> None:
        if token.profile_id != self.profile.profile_id:
            raise StalePreviewError("Preview profile does not match this service")
        game = token.game_dir.expanduser().resolve()
        if game != token.game_dir:
            raise StalePreviewError("Preview game path is no longer normalized")
        expected_hashes = self._normalize_token_archive_hashes(
            game, token.archive_hashes
        )
        process_report = self._process_report(game)
        if process_report is not None:
            raise StalePreviewError("Source archive changed after preview")
        try:
            inspection = self._inspect(game)
        except _ArchiveSourceError as exc:
            raise StalePreviewError("Source archive changed after preview") from exc
        self._validate_token_against_inspection(
            token, inspection, expected_hashes
        )

    def _validate_token_against_inspection(
        self,
        token: PreviewToken,
        inspection: _ArchiveInspection,
        expected_hashes: dict[str, str],
    ) -> dict[str, str]:
        detection = inspection.report
        if (
            detection.status is not TimerStatus.VANILLA
            or detection.body_sha256 != token.source_body_sha256
            or detection.entry_offset != token.entry_offset
            or detection.compressed_size != token.source_compressed_size
        ):
            raise StalePreviewError("Source archive changed after preview")

        game = detection.game_dir

        current_hashes: dict[str, str] = {}
        for source_path in inspection.paths:
            try:
                relative = source_path.resolve().relative_to(game).as_posix()
                path = self._contained_path(game, relative)
            except (BackupConflictError, ValueError) as exc:
                raise StalePreviewError(str(exc)) from exc
            if not path.is_file():
                raise StalePreviewError(
                    f"Source archive changed after preview: {relative}"
                )
            current_hashes[relative] = self._hash_file(path)

        if current_hashes != expected_hashes:
            changed = sorted(
                key
                for key in current_hashes.keys() | expected_hashes.keys()
                if current_hashes.get(key) != expected_hashes.get(key)
            )
            detail = f": {changed[0]}" if changed else ""
            raise StalePreviewError(
                f"Source archive changed after preview{detail}"
            )
        return current_hashes

    def apply(
        self,
        token: PreviewToken,
        progress: Callable[[str, int], None] | None = None,
    ) -> TransactionReport:
        self._emit_progress(progress, "process_check", 5)
        self._ensure_game_closed()
        if token.profile_id != self.profile.profile_id:
            raise StalePreviewError("Preview profile does not match this service")
        game = token.game_dir.expanduser().resolve()
        if game != token.game_dir:
            raise StalePreviewError("Preview game path is no longer normalized")

        process_report = self._process_report(game)
        inspection = None
        if process_report is not None:
            current = process_report
        else:
            try:
                inspection = self._inspect(game)
                current = inspection.report
            except _ArchiveSourceError as exc:
                current = self._report(
                    TimerStatus.UNKNOWN,
                    game,
                    f"Archive compatibility check failed: {exc}",
                )
        if (
            current.status is TimerStatus.APPLIED
            and current.body_sha256 == token.candidate_body_sha256
        ):
            return TransactionReport(
                status=TimerStatus.APPLIED,
                action="none",
                changed=False,
                reason="Verified preset is already applied; no files were written",
                profile_id=self.profile.profile_id,
                game_dir=game,
                backup_dir=self._latest_finalized_backup(game),
                source_body_sha256=token.source_body_sha256,
                candidate_body_sha256=token.candidate_body_sha256,
                source_compressed_size=token.source_compressed_size,
                candidate_compressed_size=current.compressed_size,
                cooldown_seconds=current.cooldown_seconds,
                duration_seconds=current.duration_seconds,
            )

        expected_hashes = self._normalize_token_archive_hashes(
            game, token.archive_hashes
        )
        process_report = self._process_report(game)
        if process_report is not None:
            raise StalePreviewError("Source archive changed after preview")
        if inspection is None:
            try:
                inspection = self._inspect(game)
            except _ArchiveSourceError as exc:
                raise StalePreviewError("Source archive changed after preview") from exc
        source_hashes = self._validate_token_against_inspection(
            token, inspection, expected_hashes
        )
        self._emit_progress(progress, "source_revalidation", 15)

        entry = inspection.entry
        candidate = self._build_candidate(inspection.body)
        candidate_compressed = bytes(
            crimson_rs.compress_data(candidate, entry.compression)
        )
        if (
            hashlib.sha256(candidate).hexdigest() != token.candidate_body_sha256
            or len(candidate_compressed) != token.candidate_compressed_size
        ):
            raise StalePreviewError("Candidate no longer matches the verified preview")

        paths = inspection.paths
        padding = token.source_compressed_size - len(candidate_compressed)
        if padding < 0:
            raise ValueError("Candidate no longer fits the enrolled PAZ slot")
        slot_payload = candidate_compressed + bytes(padding)

        backup_dir, expected_paz = self._create_backup(
            game,
            paths,
            source_hashes,
            token,
            slot_payload,
        )
        self._emit_progress(progress, "backup_verification", 30)
        manifest_path = backup_dir / "manifest.json"
        paz_path, pamt_path, papgt_path = paths

        mutation_attempted = False
        try:
            mutation_attempted = True
            self._patch_paz_slot(
                paz_path,
                token.entry_offset,
                slot_payload,
                expected_paz.source_entry_sha256,
            )
            self._emit_progress(progress, "paz_write", 50)
            self._inject_fault("after_paz_write")

            new_pamt, new_papgt = self._build_metadata_bytes(
                backup_dir,
                entry,
                len(candidate_compressed),
                expected_paz.checksum,
                expected_paz.size,
            )
            expected_post_hashes = {
                paz_path.relative_to(game).as_posix(): expected_paz.sha256,
                pamt_path.relative_to(game).as_posix(): self._sha256_bytes(new_pamt),
                papgt_path.relative_to(game).as_posix(): self._sha256_bytes(new_papgt),
            }
            self._atomic_write(pamt_path, new_pamt, "pamt")
            self._emit_progress(progress, "pamt_update", 65)
            self._inject_fault("after_pamt_write")
            self._atomic_write(papgt_path, new_papgt, "papgt")
            self._emit_progress(progress, "papgt_update", 80)
            self._inject_fault("after_papgt_write")
            verified, post_hashes = self._verify_archive_set(
                game,
                paths,
                expected_post_hashes,
                TimerStatus.APPLIED,
                token.candidate_body_sha256,
            )
            self._emit_progress(progress, "post_write_verification", 95)
            manifest = self._read_manifest(manifest_path)
            manifest["post_apply_hashes"] = post_hashes
            manifest["finalized"] = True
            manifest["finalized_at"] = datetime.now(timezone.utc).isoformat()
            self._write_manifest(manifest_path, manifest)
        except Exception as exc:
            if not mutation_attempted:
                raise
            try:
                self._restore_backup_files(game, backup_dir, source_hashes)
                self._verify_archive_set(
                    game,
                    paths,
                    source_hashes,
                    TimerStatus.VANILLA,
                    token.source_body_sha256,
                )
                manifest = self._read_manifest(manifest_path)
                manifest["post_apply_hashes"] = {}
                manifest["finalized"] = False
                manifest.pop("finalized_at", None)
                manifest["rolled_back"] = True
                manifest["rollback_reason"] = str(exc)
                self._write_manifest(manifest_path, manifest)
            except Exception as rollback_exc:
                raise TimerTransactionError(
                    f"Apply failed: {exc}; rollback also failed: {rollback_exc}"
                ) from exc
            raise TimerTransactionError(
                f"Apply failed and all three game archives were rolled back: {exc}"
            ) from exc

        return TransactionReport(
            status=TimerStatus.APPLIED,
            action="apply",
            changed=True,
            reason="Blackstar 30 minute / 1 second preset applied and verified",
            profile_id=self.profile.profile_id,
            game_dir=game,
            backup_dir=backup_dir,
            source_body_sha256=token.source_body_sha256,
            candidate_body_sha256=token.candidate_body_sha256,
            source_compressed_size=token.source_compressed_size,
            candidate_compressed_size=token.candidate_compressed_size,
            cooldown_seconds=verified.cooldown_seconds,
            duration_seconds=verified.duration_seconds,
        )

    def restore(
        self,
        game_dir: str | Path,
        progress: Callable[[str, int], None] | None = None,
    ) -> TransactionReport:
        self._emit_progress(progress, "process_check", 5)
        self._ensure_game_closed()
        game = Path(game_dir).expanduser().resolve()
        backup_dir = self._latest_finalized_backup(game)
        if backup_dir is None:
            raise BackupConflictError("No finalized Blackstar Timer backup was found")
        manifest_path = backup_dir / "manifest.json"
        manifest = self._read_manifest(manifest_path)
        if manifest.get("profile_id") != self.profile.profile_id:
            raise BackupConflictError("Backup profile does not match this service")
        if Path(str(manifest.get("game_dir", ""))).resolve() != game:
            raise BackupConflictError("Backup belongs to a different game directory")
        source_hashes = self._manifest_hashes(manifest, "source_hashes")
        post_hashes = self._manifest_hashes(manifest, "post_apply_hashes")
        expected_paths = self._expected_archive_paths(game)
        if set(source_hashes) != expected_paths or set(post_hashes) != expected_paths:
            raise BackupConflictError(
                "Backup manifest archive paths do not match the enrolled timer files"
            )
        for relative, expected in source_hashes.items():
            backup_file = self._contained_path(backup_dir, relative)
            if not backup_file.is_file() or self._hash_file(backup_file) != expected:
                raise BackupConflictError(f"Backup file is missing or altered: {relative}")
        self._emit_progress(progress, "backup_verification", 30)
        for relative, expected in post_hashes.items():
            current_file = self._contained_path(game, relative)
            if not current_file.is_file() or self._hash_file(current_file) != expected:
                raise BackupConflictError(
                    f"Game archive changed after this preset was applied: {relative}"
                )

        rollback_dir = Path(
            tempfile.mkdtemp(prefix=".restore-rollback-", dir=backup_dir.parent)
        )
        try:
            self._restore_backup_files(rollback_dir, game, post_hashes)
            try:
                self._restore_backup_files(
                    game,
                    backup_dir,
                    source_hashes,
                    after_replace=lambda index, _relative: self._inject_fault(
                        f"after_restore_file_{index}"
                    ),
                )
                self._emit_progress(progress, "archive_restore", 70)
                detection = self.detect(game)
                if detection.status is not TimerStatus.VANILLA:
                    raise TimerTransactionError(
                        "Vanilla verification failed: " + detection.reason
                    )
                self._emit_progress(progress, "restore_verification", 95)
                manifest["restored"] = True
                manifest["restored_at"] = datetime.now(timezone.utc).isoformat()
                self._write_manifest(manifest_path, manifest)
            except Exception as exc:
                try:
                    self._restore_backup_files(game, rollback_dir, post_hashes)
                    rollback_detection = self.detect(game)
                    if rollback_detection.status is not TimerStatus.APPLIED:
                        raise TimerTransactionError(
                            "Applied-state verification failed: "
                            + rollback_detection.reason
                        )
                except Exception as rollback_exc:
                    raise TimerTransactionError(
                        f"Restore failed: {exc}; rollback also failed: {rollback_exc}"
                    ) from exc
                raise TimerTransactionError(
                    "Restore failed and all three archives were rolled back to the "
                    f"applied state: {exc}"
                ) from exc
        finally:
            try:
                shutil.rmtree(rollback_dir)
            except OSError as exc:
                log.warning(
                    "Could not remove temporary restore rollback directory %s: %s",
                    rollback_dir,
                    exc,
                )
        return TransactionReport(
            status=TimerStatus.VANILLA,
            action="restore",
            changed=True,
            reason="Original Blackstar timer archives restored and verified",
            profile_id=self.profile.profile_id,
            game_dir=game,
            backup_dir=backup_dir,
            source_body_sha256=detection.body_sha256,
            candidate_body_sha256=None,
            source_compressed_size=detection.compressed_size,
            candidate_compressed_size=None,
            cooldown_seconds=detection.cooldown_seconds,
            duration_seconds=detection.duration_seconds,
        )

    def _stream_paz_identity(
        self,
        path: Path,
        entry_offset: int,
        entry_size: int,
        replacement: bytes | None = None,
    ) -> _PazIdentity:
        size = path.stat().st_size
        entry_end = entry_offset + entry_size
        if entry_offset < 0 or entry_size < 0 or entry_end > size:
            raise ValueError("PAZ entry range is outside the archive")
        if replacement is not None and len(replacement) != entry_size:
            raise ValueError("PAZ replacement must exactly fill the enrolled slot")

        sha256 = hashlib.sha256()
        source_sha256 = hashlib.sha256()
        checksum = _JenkinsChecksum(size)
        source_entry_sha256 = hashlib.sha256()

        def update_identity(data: bytes) -> None:
            sha256.update(data)
            checksum.update(data)

        with path.open("rb") as handle:
            if replacement is not None:
                remaining = entry_offset
                while remaining:
                    block = handle.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ValueError("PAZ ended before the enrolled entry")
                    update_identity(block)
                    source_sha256.update(block)
                    remaining -= len(block)

                remaining = entry_size
                while remaining:
                    block = handle.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ValueError("PAZ entry is truncated")
                    source_entry_sha256.update(block)
                    source_sha256.update(block)
                    remaining -= len(block)
                update_identity(replacement)

                while True:
                    block = handle.read(1024 * 1024)
                    if not block:
                        break
                    update_identity(block)
                    source_sha256.update(block)
                entry_bytes = None
            else:
                position = 0
                captured = bytearray()
                while True:
                    block = handle.read(1024 * 1024)
                    if not block:
                        break
                    update_identity(block)
                    source_sha256.update(block)
                    block_end = position + len(block)
                    overlap_start = max(position, entry_offset)
                    overlap_end = min(block_end, entry_end)
                    if overlap_start < overlap_end:
                        relative_start = overlap_start - position
                        relative_end = overlap_end - position
                        entry_block = block[relative_start:relative_end]
                        captured.extend(entry_block)
                        source_entry_sha256.update(entry_block)
                    position = block_end
                entry_bytes = bytes(captured)

        return _PazIdentity(
            sha256=sha256.hexdigest(),
            source_sha256=source_sha256.hexdigest(),
            checksum=checksum.digest(),
            size=size,
            entry_bytes=entry_bytes,
            source_entry_sha256=source_entry_sha256.hexdigest(),
        )

    def _patch_paz_slot(
        self,
        paz_path: Path,
        entry_offset: int,
        slot_payload: bytes,
        source_entry_sha256: str,
    ) -> None:
        with paz_path.open("r+b") as handle:
            handle.seek(entry_offset)
            source_entry = handle.read(len(slot_payload))
            if (
                len(source_entry) != len(slot_payload)
                or self._sha256_bytes(source_entry) != source_entry_sha256
            ):
                raise StalePreviewError("Source archive changed after preview")
            handle.seek(entry_offset)
            self._write_all(handle, slot_payload, "paz-slot")
            self._flush_file(handle, "paz-slot")
            self._fsync_file(handle, "paz-slot")

    def _build_metadata_bytes(
        self,
        game: Path,
        entry: _ArchiveEntry,
        candidate_compressed_size: int,
        paz_checksum: int,
        paz_size: int,
    ) -> tuple[bytes, bytes]:
        _paz_path, pamt_path, papgt_path = self._source_paths(game, entry)
        pamt = crimson_rs.parse_pamt_file(str(pamt_path))
        pamt_entry = self._find_entry_in_document(pamt)
        pamt_entry["compressed_size"] = candidate_compressed_size
        chunk_id = int(pamt_entry["chunk_id"])
        chunks = [chunk for chunk in pamt["chunks"] if int(chunk["id"]) == chunk_id]
        if len(chunks) != 1:
            raise ValueError(f"Expected one PAMT chunk {chunk_id}; found {len(chunks)}")
        chunks[0]["checksum"] = paz_checksum
        chunks[0]["size"] = paz_size
        pamt_bytes = bytearray(crimson_rs.serialize_pamt(pamt))
        struct.pack_into(
            "<I", pamt_bytes, 0, crimson_rs.calculate_checksum(bytes(pamt_bytes[12:]))
        )
        new_pamt = bytes(pamt_bytes)
        verified_pamt = crimson_rs.parse_pamt_bytes(new_pamt)
        pamt_checksum = int(verified_pamt["checksum"])

        papgt = crimson_rs.parse_papgt_file(str(papgt_path))
        groups = [
            item
            for item in papgt["entries"]
            if str(item["group_name"]) == self.profile.group_name
        ]
        if len(groups) != 1:
            raise ValueError(
                f"Expected one PAPGT group {self.profile.group_name}; found {len(groups)}"
            )
        groups[0]["pack_meta_checksum"] = pamt_checksum
        papgt_bytes = bytearray(crimson_rs.serialize_papgt(papgt))
        struct.pack_into(
            "<I", papgt_bytes, 4, crimson_rs.calculate_checksum(bytes(papgt_bytes[12:]))
        )
        new_papgt = bytes(papgt_bytes)
        crimson_rs.parse_papgt_bytes(new_papgt)
        return new_pamt, new_papgt

    def _copy_backup_file(
        self,
        source: Path,
        destination: Path,
        operation: str,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with (
            source.open("rb") as source_handle,
            destination.open("xb") as backup_handle,
        ):
            while True:
                block = source_handle.read(1024 * 1024)
                if not block:
                    break
                self._write_all(backup_handle, block, operation)
            self._flush_file(backup_handle, operation)
            self._fsync_file(backup_handle, operation)

    def _create_backup(
        self,
        game: Path,
        paths: tuple[Path, Path, Path],
        source_hashes: dict[str, str],
        token: PreviewToken,
        slot_payload: bytes,
    ) -> tuple[Path, _PazIdentity]:
        root = game / "bin64" / "SEModLoad" / "Backups" / "BlackstarTimer"
        root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        backup_dir = root / timestamp
        backup_dir.mkdir(exist_ok=False)
        self._sync_directory(root, "backup-root-directory")

        expected_paz: _PazIdentity | None = None
        for path in paths:
            relative = path.relative_to(game)
            relative_text = relative.as_posix()
            destination = backup_dir / relative
            operation = f"backup:{relative_text}"
            self._copy_backup_file(path, destination, operation)
            self._sync_directory(
                destination.parent,
                f"backup-directory:{relative_text}",
            )
            expected = source_hashes[relative_text]
            if path == paths[0]:
                expected_paz = self._stream_paz_identity(
                    destination,
                    token.entry_offset,
                    token.source_compressed_size,
                    replacement=slot_payload,
                )
                backup_hash = expected_paz.source_sha256
            else:
                backup_hash = self._hash_file(destination)
            if backup_hash != expected:
                raise OSError(f"Backup verification failed: {relative_text}")
        self._sync_directory(backup_dir, "backup-directory")

        manifest = {
            "format_version": 1,
            "profile_id": self.profile.profile_id,
            "game_dir": str(game),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_hashes": source_hashes,
            "post_apply_hashes": {},
            "source_body_sha256": token.source_body_sha256,
            "candidate_body_sha256": token.candidate_body_sha256,
            "source_compressed_size": token.source_compressed_size,
            "candidate_compressed_size": token.candidate_compressed_size,
            "finalized": False,
            "rolled_back": False,
            "restored": False,
        }
        self._write_manifest(backup_dir / "manifest.json", manifest)
        if expected_paz is None:
            raise OSError("Backup PAZ identity was not calculated")
        return backup_dir, expected_paz

    def _verify_archive_set(
        self,
        game: Path,
        paths: tuple[Path, Path, Path],
        expected_hashes: dict[str, str],
        expected_status: TimerStatus,
        expected_body_hash: str,
    ) -> tuple[DetectionReport, dict[str, str]]:
        contained_paths: list[tuple[str, Path]] = []
        for path in paths:
            relative = path.resolve().relative_to(game).as_posix()
            contained_paths.append((relative, self._contained_path(game, relative)))

        paz_relative, paz_path = contained_paths[0]
        pamt_relative, pamt_path = contained_paths[1]
        papgt_relative, papgt_path = contained_paths[2]
        pamt_bytes = pamt_path.read_bytes()
        papgt_bytes = papgt_path.read_bytes()
        entry_mapping, chunk_checksum, chunk_size = (
            self._verify_integrity_bytes(pamt_bytes, papgt_bytes)
        )
        entry = _ArchiveEntry.from_mapping(entry_mapping)
        expected_paz_path = self._source_paths(game, entry)[0].resolve()
        if paz_path.resolve() != expected_paz_path:
            raise ValueError("PAMT entry references an unexpected PAZ chunk")

        paz_identity = self._stream_paz_identity(
            paz_path,
            entry.chunk_offset,
            entry.compressed_size,
        )
        current_hashes = {
            paz_relative: paz_identity.sha256,
            pamt_relative: self._sha256_bytes(pamt_bytes),
            papgt_relative: self._sha256_bytes(papgt_bytes),
        }
        if current_hashes != expected_hashes:
            changed = sorted(
                key
                for key in current_hashes.keys() | expected_hashes.keys()
                if current_hashes.get(key) != expected_hashes.get(key)
            )
            relative = changed[0] if changed else "<archive set>"
            raise ValueError(f"Post-write hash mismatch: {relative}")
        if chunk_checksum != paz_identity.checksum:
            raise ValueError("PAZ chunk checksum mismatch")
        if chunk_size != paz_identity.size:
            raise ValueError("PAZ chunk size mismatch")
        if paz_identity.entry_bytes is None:
            raise ValueError("PAZ entry verification bytes are unavailable")

        body = self._decompress_entry(paz_identity.entry_bytes, entry)
        inspection = self._classify_inspection(game, entry, body, paths)
        report = inspection.report
        expected_values = {
            TimerStatus.VANILLA: (
                self.profile.vanilla_cooldown_seconds,
                self.profile.vanilla_duration_seconds,
            ),
            TimerStatus.APPLIED: (
                self.profile.preset_cooldown_seconds,
                self.profile.preset_duration_seconds,
            ),
        }
        if expected_status not in expected_values:
            raise ValueError(
                f"Unsupported verification status: {expected_status.value}"
            )
        cooldown, duration = expected_values[expected_status]
        if (
            report.status is not expected_status
            or report.body_sha256 != expected_body_hash
            or report.cooldown_seconds != cooldown
            or report.duration_seconds != duration
        ):
            raise ValueError(f"Post-write body verification failed: {report.reason}")
        return report, current_hashes

    def _verify_integrity_bytes(
        self,
        pamt_bytes: bytes,
        papgt_bytes: bytes,
    ) -> tuple[dict, int, int]:
        pamt = crimson_rs.parse_pamt_bytes(pamt_bytes)
        if int(pamt["checksum"]) != crimson_rs.calculate_checksum(pamt_bytes[12:]):
            raise ValueError("PAMT payload checksum mismatch")
        entry = self._find_entry_in_document(pamt)
        self._validate_entry(entry)
        chunk_id = int(entry["chunk_id"])
        chunks = [chunk for chunk in pamt["chunks"] if int(chunk["id"]) == chunk_id]
        if len(chunks) != 1:
            raise ValueError("PAMT chunk identity is ambiguous")

        papgt = crimson_rs.parse_papgt_bytes(papgt_bytes)
        if int(papgt["checksum"]) != crimson_rs.calculate_checksum(papgt_bytes[12:]):
            raise ValueError("PAPGT payload checksum mismatch")
        groups = [
            item
            for item in papgt["entries"]
            if str(item["group_name"]) == self.profile.group_name
        ]
        if len(groups) != 1 or int(groups[0]["pack_meta_checksum"]) != int(
            pamt["checksum"]
        ):
            raise ValueError("PAPGT does not reference the current PAMT checksum")
        return entry, int(chunks[0]["checksum"]), int(chunks[0]["size"])

    def _find_entry_in_document(self, pamt: dict) -> dict:
        matches = []
        expected_directory = self.profile.directory.strip("/").lower()
        expected_name = self.profile.file_name.lower()
        for directory in pamt.get("directories", []):
            if str(directory.get("path", "")).strip("/").lower() != expected_directory:
                continue
            matches.extend(
                entry
                for entry in directory.get("files", [])
                if str(entry.get("name", "")).lower() == expected_name
            )
        if len(matches) != 1:
            raise ValueError(
                f"Expected exactly one {self.profile.archive_path} entry; found {len(matches)}"
            )
        return matches[0]

    def _restore_backup_files(
        self,
        game: Path,
        backup_dir: Path,
        source_hashes: dict[str, str],
        after_replace: Callable[[int, str], None] | None = None,
    ) -> None:
        for index, (relative, expected) in enumerate(source_hashes.items(), start=1):
            source = self._contained_path(backup_dir, relative)
            destination = self._contained_path(game, relative)
            if not source.is_file() or self._hash_file(source) != expected:
                raise OSError(f"Backup cannot be verified: {relative}")
            temp_path = self._copy_to_temp(source, destination)
            os.replace(temp_path, destination)
            if after_replace is not None:
                after_replace(index, relative)
        for relative, expected in source_hashes.items():
            if self._hash_file(self._contained_path(game, relative)) != expected:
                raise OSError(f"Restored file hash mismatch: {relative}")

    def _expected_archive_paths(self, game: Path) -> set[str]:
        try:
            entry = self._find_entry(game)
            paths = self._source_paths(game, entry)
            return {path.relative_to(game).as_posix() for path in paths}
        except Exception as exc:
            raise BackupConflictError(
                f"Could not resolve the enrolled timer archive paths: {exc}"
            ) from exc

    @staticmethod
    def _contained_path(root: Path, relative: str) -> Path:
        if "\\" in relative:
            raise BackupConflictError(f"Unsafe backup path: {relative}")
        parts = relative.split("/")
        if (
            not parts
            or any(part in {"", ".", ".."} or ":" in part for part in parts)
            or relative.startswith("/")
        ):
            raise BackupConflictError(f"Unsafe backup path: {relative}")
        root = root.resolve()
        candidate = (root / Path(*parts)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise BackupConflictError(f"Unsafe backup path: {relative}") from exc
        return candidate

    @staticmethod
    def _copy_to_temp(source: Path, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{destination.name}.restore-", dir=destination.parent
        )
        os.close(descriptor)
        temp_path = Path(raw_path)
        try:
            shutil.copy2(source, temp_path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return temp_path

    @staticmethod
    def _write_all(
        handle: BinaryIO,
        data: bytes,
        operation: str,
    ) -> None:
        del operation
        view = memoryview(data)
        written_total = 0
        while written_total < len(view):
            written = handle.write(view[written_total:])
            if written is None or written <= 0:
                raise OSError("Archive write did not make progress")
            written_total += written

    @staticmethod
    def _flush_file(handle: BinaryIO, operation: str) -> None:
        del operation
        handle.flush()

    @staticmethod
    def _fsync_file(handle: BinaryIO, operation: str) -> None:
        del operation
        os.fsync(handle.fileno())

    @staticmethod
    def _sync_directory(path: Path, operation: str) -> None:
        del operation
        if os.name == "nt":
            # Windows os.open cannot acquire a directory handle for fsync.
            return
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _atomic_write(
        self,
        path: Path,
        data: bytes,
        operation: str | None = None,
    ) -> None:
        operation = operation or f"atomic:{path.name}"
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{path.name}.timer-", dir=path.parent
        )
        temp_path = Path(raw_path)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                self._write_all(handle, data, operation)
                self._flush_file(handle, operation)
                self._fsync_file(handle, operation)
            os.replace(temp_path, path)
            directory_operation = (
                "manifest-directory"
                if operation == "manifest"
                else f"{operation}-directory"
            )
            self._sync_directory(path.parent, directory_operation)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            temp_path.unlink(missing_ok=True)
            raise

    def _write_manifest(self, path: Path, manifest: dict) -> None:
        payload = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        self._atomic_write(path, payload, "manifest")

    @staticmethod
    def _read_manifest(path: Path) -> dict:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BackupConflictError(f"Backup manifest is unreadable: {exc}") from exc
        if not isinstance(value, dict):
            raise BackupConflictError("Backup manifest root is not an object")
        return value

    @staticmethod
    def _manifest_hashes(manifest: dict, key: str) -> dict[str, str]:
        values = manifest.get(key)
        if not isinstance(values, dict) or not values:
            raise BackupConflictError(f"Backup manifest has no {key}")
        if not all(isinstance(path, str) and isinstance(value, str) for path, value in values.items()):
            raise BackupConflictError(f"Backup manifest {key} is invalid")
        return dict(values)

    def _latest_finalized_backup(self, game: Path) -> Path | None:
        root = game / "bin64" / "SEModLoad" / "Backups" / "BlackstarTimer"
        if not root.is_dir():
            return None
        for candidate in sorted(
            (path for path in root.iterdir() if path.is_dir()), reverse=True
        ):
            manifest_path = candidate / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                manifest = self._read_manifest(manifest_path)
            except BackupConflictError:
                continue
            if (
                manifest.get("profile_id") == self.profile.profile_id
                and manifest.get("finalized") is True
                and manifest.get("restored") is not True
            ):
                return candidate
        return None

    def _inject_fault(self, phase: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(phase)

    def _emit_progress(
        self,
        callback: Callable[[str, int], None] | None,
        phase: str,
        value: int,
    ) -> None:
        log.info(
            "blackstar_timer profile=%s phase=%s progress=%d",
            self.profile.profile_id,
            phase,
            value,
        )
        if callback is not None:
            callback(phase, value)

    def _process_report(self, game: Path) -> DetectionReport | None:
        try:
            if self._process_checker():
                return self._report(
                    TimerStatus.GAME_RUNNING,
                    game,
                    "Crimson Desert is running; close it before previewing or writing",
                )
        except (OSError, subprocess.SubprocessError) as exc:
            return self._report(
                TimerStatus.UNKNOWN,
                game,
                f"Could not verify whether Crimson Desert is running: {exc}",
            )
        return None

    def _ensure_game_closed(self) -> None:
        try:
            running = self._process_checker()
        except (OSError, subprocess.SubprocessError) as exc:
            raise GameRunningError(
                f"Could not verify whether Crimson Desert is running: {exc}"
            ) from exc
        if running:
            raise GameRunningError(
                "Crimson Desert is running; close it before changing game archives"
            )

    @staticmethod
    def _sha256_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _inspect(self, game: Path) -> _ArchiveInspection:
        try:
            source_entry = dict(self._find_entry(game))
            self._validate_entry(source_entry)
            body = self._read_body(game, source_entry)
            paths = self._source_paths(game, source_entry)
            entry = _ArchiveEntry.from_mapping(source_entry)
        except (FileNotFoundError, OSError, ValueError, KeyError, TypeError) as exc:
            raise _ArchiveSourceError(str(exc)) from exc
        return self._classify_inspection(game, entry, body, paths)

    def _classify_inspection(
        self,
        game: Path,
        entry: _ArchiveEntry,
        body: bytes,
        paths: tuple[Path, Path, Path],
    ) -> _ArchiveInspection:
        digest = hashlib.sha256(body).hexdigest()
        cooldown = self._read_u64(body, self.profile.cooldown_offset)
        duration = self._read_u64(body, self.profile.duration_offset)
        values = (cooldown, duration)
        vanilla_values = (
            self.profile.vanilla_cooldown_seconds,
            self.profile.vanilla_duration_seconds,
        )
        applied_values = (
            self.profile.preset_cooldown_seconds,
            self.profile.preset_duration_seconds,
        )
        details = {
            "body_sha256": digest,
            "cooldown_seconds": cooldown,
            "duration_seconds": duration,
            "entry_offset": entry.chunk_offset,
            "compressed_size": entry.compressed_size,
            "uncompressed_size": entry.uncompressed_size,
        }
        if (
            digest == self.profile.vanilla_body_sha256
            and values == vanilla_values
            and entry.compressed_size == self.profile.vanilla_compressed_size
        ):
            report = self._report(
                TimerStatus.VANILLA,
                game,
                "Enrolled vanilla Blackstar timer schema detected",
                **details,
            )
        elif digest == self.profile.applied_body_sha256 and values == applied_values:
            report = self._report(
                TimerStatus.APPLIED,
                game,
                "Verified Blackstar timer preset is already applied",
                **details,
            )
        elif values[0] in (vanilla_values[0], applied_values[0]) and values[1] in (
            vanilla_values[1],
            applied_values[1],
        ) and values not in (vanilla_values, applied_values):
            report = self._report(
                TimerStatus.PARTIAL,
                game,
                "Blackstar timer fields are only partially patched",
                **details,
            )
        elif values not in (vanilla_values, applied_values):
            report = self._report(
                TimerStatus.PARTIAL,
                game,
                "Blackstar timer field values do not match an enrolled state",
                **details,
            )
        else:
            report = self._report(
                TimerStatus.UNKNOWN,
                game,
                "Characterinfo body hash is not enrolled for this game version",
                **details,
            )
        return _ArchiveInspection(
            report=report,
            entry=entry,
            body=body,
            paths=paths,
        )

    def _build_candidate(self, source: bytes) -> bytes:
        candidate = bytearray(source)
        cooldown_end = self.profile.cooldown_offset + 8
        duration_end = self.profile.duration_offset + 8
        if min(self.profile.cooldown_offset, self.profile.duration_offset) < 0 or max(
            cooldown_end, duration_end
        ) > len(candidate):
            raise ValueError("Enrolled timer offsets are outside characterinfo")
        candidate[self.profile.cooldown_offset:cooldown_end] = (
            self.profile.preset_cooldown_seconds.to_bytes(8, "little")
        )
        candidate[self.profile.duration_offset:duration_end] = (
            self.profile.preset_duration_seconds.to_bytes(8, "little")
        )
        return bytes(candidate)

    def _source_paths(
        self,
        game: Path,
        entry: _ArchiveEntry | Mapping[str, object],
    ) -> tuple[Path, Path, Path]:
        group = game / self.profile.group_name
        chunk_id = (
            entry.chunk_id
            if isinstance(entry, _ArchiveEntry)
            else int(entry["chunk_id"])
        )
        return (
            group / f"{chunk_id}.paz",
            group / "0.pamt",
            game / "meta" / "0.papgt",
        )

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _find_entry(self, game: Path) -> dict:
        pamt_path = game / self.profile.group_name / "0.pamt"
        if not pamt_path.is_file():
            raise FileNotFoundError(f"PAMT not found: {pamt_path}")
        pamt = crimson_rs.parse_pamt_file(str(pamt_path))
        return self._find_entry_in_document(pamt)

    def _validate_entry(self, entry: dict) -> None:
        checks = {
            "entry offset": (int(entry["chunk_offset"]), self.profile.entry_offset),
            "uncompressed size": (
                int(entry["uncompressed_size"]),
                self.profile.uncompressed_size,
            ),
            "compression": (int(entry["compression"]), self.profile.compression),
            "crypto": (int(entry["crypto"]), self.profile.crypto),
        }
        for label, (actual, expected) in checks.items():
            if actual != expected:
                raise ValueError(f"Unexpected {label}: {actual}; expected {expected}")

    def _read_body(self, game: Path, entry: dict) -> bytes:
        archive_entry = _ArchiveEntry.from_mapping(entry)
        paz_path = self._source_paths(game, archive_entry)[0]
        if not paz_path.is_file():
            raise FileNotFoundError(f"PAZ not found: {paz_path}")
        offset = archive_entry.chunk_offset
        compressed_size = archive_entry.compressed_size
        with paz_path.open("rb") as handle:
            handle.seek(offset)
            compressed = handle.read(compressed_size)
        return self._decompress_entry(compressed, archive_entry)

    def _decompress_entry(
        self,
        compressed: bytes,
        entry: _ArchiveEntry,
    ) -> bytes:
        if len(compressed) != entry.compressed_size:
            raise ValueError(
                "Compressed entry is truncated: "
                f"{len(compressed)} of {entry.compressed_size} bytes"
            )
        body = self._decompress_stream(
            compressed,
            entry.compression,
            entry.uncompressed_size,
        )
        if len(body) != self.profile.uncompressed_size:
            raise ValueError(
                f"Decompressed body size is {len(body)}; "
                f"expected {self.profile.uncompressed_size}"
            )
        return body

    @staticmethod
    def _decompress_stream(
        compressed: bytes,
        compression: int,
        uncompressed_size: int,
    ) -> bytes:
        return bytes(
            crimson_rs.decompress_data(
                compressed,
                compression,
                uncompressed_size,
            )
        )

    @staticmethod
    def _read_u64(body: bytes, offset: int) -> int:
        end = offset + 8
        if offset < 0 or end > len(body):
            raise ValueError(f"Timer field offset {offset} is outside the body")
        return int.from_bytes(body[offset:end], "little", signed=False)

    def _report(
        self,
        status: TimerStatus,
        game: Path,
        reason: str,
        **details: object,
    ) -> DetectionReport:
        return DetectionReport(
            status=status,
            reason=reason,
            profile_id=self.profile.profile_id,
            game_dir=game,
            **details,
        )
