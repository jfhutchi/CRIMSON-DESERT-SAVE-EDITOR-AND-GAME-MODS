from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import struct
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable

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
    ) -> None:
        self.profile = profile
        self._fault_injector = fault_injector

    def detect(self, game_dir: str | Path) -> DetectionReport:
        game = Path(game_dir).expanduser().resolve()
        try:
            entry = self._find_entry(game)
            self._validate_entry(entry)
            body = self._read_body(game, entry)
        except (FileNotFoundError, OSError, ValueError, KeyError, TypeError) as exc:
            return self._report(
                TimerStatus.UNKNOWN,
                game,
                f"Archive compatibility check failed: {exc}",
            )

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
            "entry_offset": int(entry["chunk_offset"]),
            "compressed_size": int(entry["compressed_size"]),
            "uncompressed_size": int(entry["uncompressed_size"]),
        }
        if (
            digest == self.profile.vanilla_body_sha256
            and values == vanilla_values
            and int(entry["compressed_size"])
            == self.profile.vanilla_compressed_size
        ):
            return self._report(
                TimerStatus.VANILLA,
                game,
                "Enrolled vanilla Blackstar timer schema detected",
                **details,
            )
        if digest == self.profile.applied_body_sha256 and values == applied_values:
            return self._report(
                TimerStatus.APPLIED,
                game,
                "Verified Blackstar timer preset is already applied",
                **details,
            )
        if values[0] in (vanilla_values[0], applied_values[0]) and values[1] in (
            vanilla_values[1],
            applied_values[1],
        ) and values not in (vanilla_values, applied_values):
            return self._report(
                TimerStatus.PARTIAL,
                game,
                "Blackstar timer fields are only partially patched",
                **details,
            )
        if values not in (vanilla_values, applied_values):
            return self._report(
                TimerStatus.PARTIAL,
                game,
                "Blackstar timer field values do not match an enrolled state",
                **details,
            )
        return self._report(
            TimerStatus.UNKNOWN,
            game,
            "Characterinfo body hash is not enrolled for this game version",
            **details,
        )

    def preview(self, game_dir: str | Path) -> PreviewReport:
        detection = self.detect(game_dir)
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

        entry = self._find_entry(detection.game_dir)
        source = self._read_body(detection.game_dir, entry)
        candidate = self._build_candidate(source)
        candidate_hash = hashlib.sha256(candidate).hexdigest()
        if candidate_hash != self.profile.applied_body_sha256:
            raise ValueError(
                "Candidate body hash does not match the enrolled applied schema"
            )
        candidate_compressed = bytes(
            crimson_rs.compress_data(candidate, int(entry["compression"]))
        )
        slot_capacity = int(entry["compressed_size"])
        if len(candidate_compressed) > slot_capacity:
            raise ValueError(
                "Candidate compressed stream does not fit the enrolled PAZ slot"
            )
        verified = bytes(
            crimson_rs.decompress_data(
                candidate_compressed,
                int(entry["compression"]),
                int(entry["uncompressed_size"]),
            )
        )
        if verified != candidate:
            raise ValueError("Candidate failed independent compression verification")
        source_paths = self._source_paths(detection.game_dir, entry)
        token = PreviewToken(
            profile_id=self.profile.profile_id,
            game_dir=detection.game_dir,
            archive_hashes=tuple(
                ArchiveFileHash(
                    relative_path=path.relative_to(detection.game_dir).as_posix(),
                    sha256=self._hash_file(path),
                )
                for path in source_paths
            ),
            source_body_sha256=hashlib.sha256(source).hexdigest(),
            candidate_body_sha256=candidate_hash,
            entry_offset=int(entry["chunk_offset"]),
            source_compressed_size=int(entry["compressed_size"]),
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

    def validate_preview_token(self, token: PreviewToken) -> None:
        if token.profile_id != self.profile.profile_id:
            raise StalePreviewError("Preview profile does not match this service")
        game = token.game_dir.expanduser().resolve()
        if game != token.game_dir:
            raise StalePreviewError("Preview game path is no longer normalized")
        for expected in token.archive_hashes:
            path = game / Path(expected.relative_path)
            if not path.is_file() or self._hash_file(path) != expected.sha256:
                raise StalePreviewError(
                    f"Source archive changed after preview: {expected.relative_path}"
                )
        detection = self.detect(game)
        if (
            detection.status is not TimerStatus.VANILLA
            or detection.body_sha256 != token.source_body_sha256
            or detection.entry_offset != token.entry_offset
            or detection.compressed_size != token.source_compressed_size
        ):
            raise StalePreviewError("Source archive changed after preview")

    def apply(self, token: PreviewToken) -> TransactionReport:
        if token.profile_id != self.profile.profile_id:
            raise StalePreviewError("Preview profile does not match this service")
        game = token.game_dir.expanduser().resolve()
        if game != token.game_dir:
            raise StalePreviewError("Preview game path is no longer normalized")

        current = self.detect(game)
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

        self.validate_preview_token(token)
        entry = self._find_entry(game)
        source = self._read_body(game, entry)
        candidate = self._build_candidate(source)
        candidate_compressed = bytes(
            crimson_rs.compress_data(candidate, int(entry["compression"]))
        )
        if (
            hashlib.sha256(candidate).hexdigest() != token.candidate_body_sha256
            or len(candidate_compressed) != token.candidate_compressed_size
        ):
            raise StalePreviewError("Candidate no longer matches the verified preview")

        paths = self._source_paths(game, entry)
        source_hashes = {
            path.relative_to(game).as_posix(): self._hash_file(path) for path in paths
        }
        new_bytes = self._build_transaction_bytes(
            game, entry, candidate_compressed
        )
        post_hashes = {
            path.relative_to(game).as_posix(): self._sha256_bytes(data)
            for path, data in zip(paths, new_bytes, strict=True)
        }
        backup_dir = self._create_backup(
            game,
            paths,
            source_hashes,
            post_hashes,
            token,
        )
        manifest_path = backup_dir / "manifest.json"
        wrote_source = False
        try:
            paz_path, pamt_path, papgt_path = paths
            padding = token.source_compressed_size - len(candidate_compressed)
            if padding < 0:
                raise ValueError("Candidate no longer fits the enrolled PAZ slot")
            with paz_path.open("r+b") as handle:
                handle.seek(token.entry_offset)
                handle.write(candidate_compressed)
                handle.write(b"\x00" * padding)
                handle.flush()
                os.fsync(handle.fileno())
            wrote_source = True
            self._inject_fault("after_paz_write")
            self._atomic_write(pamt_path, new_bytes[1])
            self._inject_fault("after_pamt_write")
            self._atomic_write(papgt_path, new_bytes[2])
            self._inject_fault("after_papgt_write")
            self._verify_post_apply(game, post_hashes, token)
            manifest = self._read_manifest(manifest_path)
            manifest["finalized"] = True
            manifest["finalized_at"] = datetime.now(timezone.utc).isoformat()
            self._write_manifest(manifest_path, manifest)
        except Exception as exc:
            if not wrote_source:
                raise
            try:
                self._restore_backup_files(game, backup_dir, source_hashes)
                manifest = self._read_manifest(manifest_path)
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

        verified = self.detect(game)
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

    def restore(self, game_dir: str | Path) -> TransactionReport:
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
        for relative, expected in source_hashes.items():
            backup_file = backup_dir / Path(relative)
            if not backup_file.is_file() or self._hash_file(backup_file) != expected:
                raise BackupConflictError(f"Backup file is missing or altered: {relative}")
        for relative, expected in post_hashes.items():
            current_file = game / Path(relative)
            if not current_file.is_file() or self._hash_file(current_file) != expected:
                raise BackupConflictError(
                    f"Game archive changed after this preset was applied: {relative}"
                )
        self._restore_backup_files(game, backup_dir, source_hashes)
        detection = self.detect(game)
        if detection.status is not TimerStatus.VANILLA:
            raise TimerTransactionError(
                f"Restore completed but vanilla verification failed: {detection.reason}"
            )
        manifest["restored"] = True
        manifest["restored_at"] = datetime.now(timezone.utc).isoformat()
        self._write_manifest(manifest_path, manifest)
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

    def _build_transaction_bytes(
        self,
        game: Path,
        entry: dict,
        candidate_compressed: bytes,
    ) -> tuple[bytes, bytes, bytes]:
        paz_path, pamt_path, papgt_path = self._source_paths(game, entry)
        paz = bytearray(paz_path.read_bytes())
        start = int(entry["chunk_offset"])
        capacity = int(entry["compressed_size"])
        end = start + capacity
        if len(candidate_compressed) > capacity or end > len(paz):
            raise ValueError("Candidate does not fit the enrolled PAZ entry")
        paz[start:end] = candidate_compressed + b"\x00" * (
            capacity - len(candidate_compressed)
        )
        new_paz = bytes(paz)

        pamt = crimson_rs.parse_pamt_file(str(pamt_path))
        pamt_entry = self._find_entry_in_document(pamt)
        pamt_entry["compressed_size"] = len(candidate_compressed)
        chunk_id = int(pamt_entry["chunk_id"])
        chunks = [chunk for chunk in pamt["chunks"] if int(chunk["id"]) == chunk_id]
        if len(chunks) != 1:
            raise ValueError(f"Expected one PAMT chunk {chunk_id}; found {len(chunks)}")
        chunks[0]["checksum"] = crimson_rs.calculate_checksum(new_paz)
        chunks[0]["size"] = len(new_paz)
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
        return new_paz, new_pamt, new_papgt

    def _create_backup(
        self,
        game: Path,
        paths: tuple[Path, Path, Path],
        source_hashes: dict[str, str],
        post_hashes: dict[str, str],
        token: PreviewToken,
    ) -> Path:
        root = game / "bin64" / "SEModLoad" / "Backups" / "BlackstarTimer"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        backup_dir = root / timestamp
        backup_dir.mkdir(parents=True, exist_ok=False)
        for path in paths:
            relative = path.relative_to(game)
            destination = backup_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            expected = source_hashes[relative.as_posix()]
            if self._hash_file(destination) != expected:
                raise OSError(f"Backup verification failed: {relative.as_posix()}")
        manifest = {
            "format_version": 1,
            "profile_id": self.profile.profile_id,
            "game_dir": str(game),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_hashes": source_hashes,
            "post_apply_hashes": post_hashes,
            "source_body_sha256": token.source_body_sha256,
            "candidate_body_sha256": token.candidate_body_sha256,
            "source_compressed_size": token.source_compressed_size,
            "candidate_compressed_size": token.candidate_compressed_size,
            "finalized": False,
            "rolled_back": False,
            "restored": False,
        }
        self._write_manifest(backup_dir / "manifest.json", manifest)
        return backup_dir

    def _verify_post_apply(
        self,
        game: Path,
        post_hashes: dict[str, str],
        token: PreviewToken,
    ) -> None:
        for relative, expected in post_hashes.items():
            if self._hash_file(game / Path(relative)) != expected:
                raise ValueError(f"Post-write hash mismatch: {relative}")
        detection = self.detect(game)
        if (
            detection.status is not TimerStatus.APPLIED
            or detection.body_sha256 != token.candidate_body_sha256
            or detection.cooldown_seconds != self.profile.preset_cooldown_seconds
            or detection.duration_seconds != self.profile.preset_duration_seconds
        ):
            raise ValueError(f"Post-write body verification failed: {detection.reason}")
        self._verify_integrity(game)

    def _verify_integrity(self, game: Path) -> None:
        pamt_path = game / self.profile.group_name / "0.pamt"
        pamt_bytes = pamt_path.read_bytes()
        pamt = crimson_rs.parse_pamt_bytes(pamt_bytes)
        if int(pamt["checksum"]) != crimson_rs.calculate_checksum(pamt_bytes[12:]):
            raise ValueError("PAMT payload checksum mismatch")
        entry = self._find_entry_in_document(pamt)
        chunk_id = int(entry["chunk_id"])
        chunks = [chunk for chunk in pamt["chunks"] if int(chunk["id"]) == chunk_id]
        if len(chunks) != 1:
            raise ValueError("PAMT chunk identity is ambiguous")
        paz_path = game / self.profile.group_name / f"{chunk_id}.paz"
        paz_bytes = paz_path.read_bytes()
        if int(chunks[0]["checksum"]) != crimson_rs.calculate_checksum(paz_bytes):
            raise ValueError("PAZ chunk checksum mismatch")
        if int(chunks[0]["size"]) != len(paz_bytes):
            raise ValueError("PAZ chunk size mismatch")
        papgt_path = game / "meta" / "0.papgt"
        papgt_bytes = papgt_path.read_bytes()
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
    ) -> None:
        for relative, expected in source_hashes.items():
            source = backup_dir / Path(relative)
            destination = game / Path(relative)
            if not source.is_file() or self._hash_file(source) != expected:
                raise OSError(f"Backup cannot be verified: {relative}")
            temp_path = self._copy_to_temp(source, destination)
            os.replace(temp_path, destination)
        for relative, expected in source_hashes.items():
            if self._hash_file(game / Path(relative)) != expected:
                raise OSError(f"Restored file hash mismatch: {relative}")

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
    def _atomic_write(path: Path, data: bytes) -> None:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{path.name}.timer-", dir=path.parent
        )
        temp_path = Path(raw_path)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            temp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _write_manifest(path: Path, manifest: dict) -> None:
        payload = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        BlackstarTimerService._atomic_write(path, payload)

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

    @staticmethod
    def _sha256_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

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

    def _source_paths(self, game: Path, entry: dict) -> tuple[Path, Path, Path]:
        group = game / self.profile.group_name
        return (
            group / f"{int(entry['chunk_id'])}.paz",
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
        chunk_id = int(entry["chunk_id"])
        paz_path = game / self.profile.group_name / f"{chunk_id}.paz"
        if not paz_path.is_file():
            raise FileNotFoundError(f"PAZ not found: {paz_path}")
        offset = int(entry["chunk_offset"])
        compressed_size = int(entry["compressed_size"])
        with paz_path.open("rb") as handle:
            handle.seek(offset)
            compressed = handle.read(compressed_size)
        if len(compressed) != compressed_size:
            raise ValueError(
                f"Compressed entry is truncated: {len(compressed)} of {compressed_size} bytes"
            )
        body = bytes(
            crimson_rs.decompress_data(
                compressed,
                int(entry["compression"]),
                int(entry["uncompressed_size"]),
            )
        )
        if len(body) != self.profile.uncompressed_size:
            raise ValueError(
                f"Decompressed body size is {len(body)}; expected {self.profile.uncompressed_size}"
            )
        return body

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
