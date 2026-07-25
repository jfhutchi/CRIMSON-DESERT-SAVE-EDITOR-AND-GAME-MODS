from __future__ import annotations

import hashlib
import struct

import pytest

from dragon_wheel_patch import (
    ReserveSlotCompatibilityError,
    ReserveSlotProfile,
    analyze_reserveslot,
    enable_dragon_category,
)


ORIGINAL_SIGNATURE = b"\x02\x00\x00\x00\x4e\x51"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _offsets(pabgh: bytes, count: int = 30) -> list[int]:
    return [
        struct.unpack_from("<I", pabgh, 2 + index * 8 + 4)[0]
        for index in range(count)
    ]


def _synthetic_fixture() -> tuple[bytes, bytes, ReserveSlotProfile]:
    records: list[bytes] = []
    keys: list[int] = []
    for index in range(30):
        key = 2_000_000 + index
        name = f"Record{index}".encode("ascii")
        record = struct.pack("<II", key, len(name)) + name + bytes([index]) * 12
        if index == 26:
            key = 1_000_006
            name = b"VehicleSlot"
            record = (
                struct.pack("<II", key, len(name))
                + name
                + b"opaque-prefix"
                + ORIGINAL_SIGNATURE
                + b"opaque-suffix"
            )
        keys.append(key)
        records.append(record)

    offsets: list[int] = []
    position = 0
    for record in records:
        offsets.append(position)
        position += len(record)
    pabgh = struct.pack("<H", len(records)) + b"".join(
        struct.pack("<II", key, offset) for key, offset in zip(keys, offsets)
    )
    pabgb = b"".join(records)

    patched_pabgb = bytearray(pabgb)
    target_offset = offsets[26]
    signature_offset = patched_pabgb.index(
        ORIGINAL_SIGNATURE, target_offset, offsets[27]
    )
    struct.pack_into("<I", patched_pabgb, signature_offset, 3)
    patched_pabgb[signature_offset + 5:signature_offset + 5] = b"\x4f"
    patched_pabgh = bytearray(pabgh)
    for index in range(27, 30):
        offset_position = 2 + index * 8 + 4
        old = struct.unpack_from("<I", patched_pabgh, offset_position)[0]
        struct.pack_into("<I", patched_pabgh, offset_position, old + 1)

    profile = ReserveSlotProfile(
        schema_id="synthetic-current",
        entry_count=30,
        target_key=1_000_006,
        target_index=26,
        target_name=b"VehicleSlot",
        original_pabgh_sha256=_sha(pabgh),
        original_pabgb_sha256=_sha(pabgb),
        patched_pabgh_sha256=_sha(bytes(patched_pabgh)),
        patched_pabgb_sha256=_sha(bytes(patched_pabgb)),
    )
    return pabgh, pabgb, profile


def test_analyzes_supported_original_without_changes() -> None:
    pabgh, pabgb, profile = _synthetic_fixture()

    report = analyze_reserveslot(pabgh, pabgb, profile)

    assert report.schema_id == "synthetic-current"
    assert report.state == "original"
    assert report.before_categories == (0x4E, 0x51)
    assert report.after_categories == (0x4E, 0x51)
    assert report.byte_growth == 0
    assert report.already_enabled is False


def test_enables_only_dragon_and_adjusts_later_offsets() -> None:
    pabgh, pabgb, profile = _synthetic_fixture()
    before_offsets = _offsets(pabgh)

    result = enable_dragon_category(pabgh, pabgb, profile)

    after_offsets = _offsets(result.pabgh)
    assert result.report.before_categories == (0x4E, 0x51)
    assert result.report.after_categories == (0x4E, 0x4F, 0x51)
    assert result.report.adjusted_entry_indexes == (27, 28, 29)
    assert after_offsets[:27] == before_offsets[:27]
    assert after_offsets[27:] == [value + 1 for value in before_offsets[27:]]
    assert len(result.pabgh) == len(pabgh)
    assert len(result.pabgb) == len(pabgb) + 1


def test_second_run_is_byte_identical() -> None:
    pabgh, pabgb, profile = _synthetic_fixture()
    first = enable_dragon_category(pabgh, pabgb, profile)

    second = enable_dragon_category(first.pabgh, first.pabgb, profile)

    assert second.pabgh == first.pabgh
    assert second.pabgb == first.pabgb
    assert second.report.already_enabled is True
    assert second.report.byte_growth == 0


def test_unknown_hashes_are_refused() -> None:
    pabgh, pabgb, profile = _synthetic_fixture()

    with pytest.raises(ReserveSlotCompatibilityError, match="Unsupported"):
        analyze_reserveslot(pabgh, pabgb + b"x", profile)


@pytest.mark.parametrize("mutation", ["header", "target_key", "target_name", "duplicate"])
def test_malformed_target_is_refused(mutation: str) -> None:
    pabgh, pabgb, profile = _synthetic_fixture()
    bad_h = bytearray(pabgh)
    bad_b = bytearray(pabgb)
    target = _offsets(pabgh)[26]
    next_target = _offsets(pabgh)[27]

    if mutation == "header":
        bad_h.append(0)
    elif mutation == "target_key":
        struct.pack_into("<I", bad_b, target, 123)
    elif mutation == "target_name":
        bad_b[target + 8:target + 19] = b"VehicleSl0t"
    else:
        signature_offset = bad_b.index(ORIGINAL_SIGNATURE, target, next_target)
        duplicate_offset = signature_offset + len(ORIGINAL_SIGNATURE)
        bad_b[duplicate_offset:duplicate_offset + len(ORIGINAL_SIGNATURE)] = (
            ORIGINAL_SIGNATURE
        )

    permissive = profile.with_hashes(
        original_pabgh_sha256=_sha(bytes(bad_h)),
        original_pabgb_sha256=_sha(bytes(bad_b)),
    )
    with pytest.raises(ReserveSlotCompatibilityError):
        analyze_reserveslot(bytes(bad_h), bytes(bad_b), permissive)
