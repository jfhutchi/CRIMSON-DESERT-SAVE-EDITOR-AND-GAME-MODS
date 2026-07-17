from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import crimson_rs


class TimerStatus(str, Enum):
    VANILLA = "vanilla"
    APPLIED = "applied"
    UNKNOWN = "unknown"
    PARTIAL = "partial"
    BACKUP_CONFLICT = "backup_conflict"
    GAME_RUNNING = "game_running"


class StalePreviewError(RuntimeError):
    """Raised when an archive changed after a successful preview."""


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
    def __init__(self, profile: TimerProfile = BLACKSTAR_114_PROFILE) -> None:
        self.profile = profile

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
        matches = []
        expected_directory = self.profile.directory.strip("/").lower()
        expected_name = self.profile.file_name.lower()
        for directory in pamt.get("directories", []):
            if str(directory.get("path", "")).strip("/").lower() != expected_directory:
                continue
            for entry in directory.get("files", []):
                if str(entry.get("name", "")).lower() == expected_name:
                    matches.append(entry)
        if len(matches) != 1:
            raise ValueError(
                f"Expected exactly one {self.profile.archive_path} entry; found {len(matches)}"
            )
        return matches[0]

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
