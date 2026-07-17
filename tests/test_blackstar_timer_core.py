from __future__ import annotations

from pathlib import Path

from blackstar_timer_archive import make_timer_archive
from crimson_common.blackstar_timer import (
    BlackstarTimerService,
    StalePreviewError,
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
