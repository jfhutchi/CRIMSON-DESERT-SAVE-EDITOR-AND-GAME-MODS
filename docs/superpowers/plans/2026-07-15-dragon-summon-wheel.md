# Dragon Summon Wheel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a packaged Crimson Game Mods tab that safely adds only the Dragon category to the normal F1 mount wheel for the verified current ReserveSlot schema.

**Architecture:** A Qt-free byte patcher validates exact supported hashes and changes one opaque target record without serializing unknown entries. A separate deployer owns backup, overlay, PAPGT, rollback, and restore transactions. A focused Qt tab exposes analyze, preview, apply, and restore while never touching save or quest data.

**Tech Stack:** Python 3.12, PySide6, `crimson_rs`, pytest, PyInstaller, SHA-256 compatibility profiles.

---

### Task 1: Pure Dragon Category Patcher

**Files:**
- Create: `CrimsonGameMods/dragon_wheel_patch.py`
- Create: `tests/test_dragon_wheel_patch.py`

- [ ] **Step 1: Write generated-fixture tests for analysis, mutation, idempotency, and refusal**

Create `tests/test_dragon_wheel_patch.py` with a synthetic 30-entry PABGH/PABGB pair. The target record is index 26 and contains the current-format signature, while all unrelated records are opaque bytes.

```python
import hashlib
import struct

import pytest

from dragon_wheel_patch import (
    ReserveSlotCompatibilityError,
    ReserveSlotProfile,
    analyze_reserveslot,
    enable_dragon_category,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fixture() -> tuple[bytes, bytes, ReserveSlotProfile]:
    records = []
    keys = []
    for index in range(30):
        key = 1_000_000 + index
        name = f"Record{index}".encode()
        record = struct.pack("<II", key, len(name)) + name + bytes([index]) * 12
        if index == 26:
            key = 1_000_006
            name = b"VehicleSlot"
            record = (
                struct.pack("<II", key, len(name))
                + name
                + b"opaque-prefix"
                + b"\x02\x00\x00\x00\x4e\x51"
                + b"opaque-suffix"
            )
        keys.append(key)
        records.append(record)

    offsets = []
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
        b"\x02\x00\x00\x00\x4e\x51", target_offset, offsets[27]
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


def test_enables_only_dragon_and_adjusts_later_offsets():
    pabgh, pabgb, profile = _fixture()
    before_offsets = [
        struct.unpack_from("<I", pabgh, 2 + index * 8 + 4)[0]
        for index in range(30)
    ]

    result = enable_dragon_category(pabgh, pabgb, profile)

    after_offsets = [
        struct.unpack_from("<I", result.pabgh, 2 + index * 8 + 4)[0]
        for index in range(30)
    ]
    assert result.report.before_categories == (0x4E, 0x51)
    assert result.report.after_categories == (0x4E, 0x4F, 0x51)
    assert after_offsets[:27] == before_offsets[:27]
    assert after_offsets[27:] == [value + 1 for value in before_offsets[27:]]
    assert len(result.pabgb) == len(pabgb) + 1


def test_second_run_is_byte_identical():
    pabgh, pabgb, profile = _fixture()
    first = enable_dragon_category(pabgh, pabgb, profile)
    second = enable_dragon_category(first.pabgh, first.pabgb, profile)
    assert second.pabgh == first.pabgh
    assert second.pabgb == first.pabgb
    assert second.report.already_enabled is True


def test_unknown_hashes_are_refused():
    pabgh, pabgb, profile = _fixture()
    with pytest.raises(ReserveSlotCompatibilityError, match="Unsupported"):
        analyze_reserveslot(pabgh, pabgb + b"x", profile)


@pytest.mark.parametrize("mutation", ["header", "target_key", "target_name", "duplicate"])
def test_malformed_target_is_refused(mutation):
    pabgh, pabgb, profile = _fixture()
    bad_h = bytearray(pabgh)
    bad_b = bytearray(pabgb)
    if mutation == "header":
        bad_h.append(0)
    elif mutation == "target_key":
        target = struct.unpack_from("<I", bad_h, 2 + 26 * 8 + 4)[0]
        struct.pack_into("<I", bad_b, target, 123)
    elif mutation == "target_name":
        target = struct.unpack_from("<I", bad_h, 2 + 26 * 8 + 4)[0]
        bad_b[target + 8:target + 19] = b"VehicleSl0t"
    else:
        target = struct.unpack_from("<I", bad_h, 2 + 26 * 8 + 4)[0]
        bad_b[target:target] = b"\x02\x00\x00\x00\x4e\x51"
    permissive = profile.with_hashes(
        original_pabgh_sha256=_sha(bytes(bad_h)),
        original_pabgb_sha256=_sha(bytes(bad_b)),
    )
    with pytest.raises(ReserveSlotCompatibilityError):
        analyze_reserveslot(bytes(bad_h), bytes(bad_b), permissive)
```

- [ ] **Step 2: Run the patcher tests and verify RED**

Run:

```powershell
$env:PYTHONPATH = (Resolve-Path 'CrimsonGameMods').Path
.\.venv\Scripts\python.exe -m pytest tests\test_dragon_wheel_patch.py -v
```

Expected: collection fails because `dragon_wheel_patch` does not exist.

- [ ] **Step 3: Implement the strict opaque-record patcher**

Create `CrimsonGameMods/dragon_wheel_patch.py` with these public types and functions:

```python
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, replace


ORIGINAL_SIGNATURE = b"\x02\x00\x00\x00\x4e\x51"
PATCHED_SIGNATURE = b"\x03\x00\x00\x00\x4e\x4f\x51"


class ReserveSlotCompatibilityError(ValueError):
    pass


@dataclass(frozen=True)
class ReserveSlotProfile:
    schema_id: str
    entry_count: int
    target_key: int
    target_index: int
    target_name: bytes
    original_pabgh_sha256: str
    original_pabgb_sha256: str
    patched_pabgh_sha256: str
    patched_pabgb_sha256: str

    def with_hashes(self, **changes: str) -> "ReserveSlotProfile":
        return replace(self, **changes)


CURRENT_PROFILE = ReserveSlotProfile(
    schema_id="reserveslot-2026-07-11-30-entry-u8-categories",
    entry_count=30,
    target_key=1_000_006,
    target_index=26,
    target_name=b"VehicleSlot",
    original_pabgh_sha256="d4e041a8c744e4bc2585ff09b75df20e0d06d20d300ace25fb15ddac8baadcd3",
    original_pabgb_sha256="292b384a5a9e16d24c59a5cc44fe9b1aca835eec870c54e703f870b2a9682938",
    patched_pabgh_sha256="18304bd6b0692427a39775258f77900f498305f57e1a45662c175548d378fd64",
    patched_pabgb_sha256="09dbcf9ace932ca1df39d2c06d862958453e018f358fcc6cf987186746200d64",
)


@dataclass(frozen=True)
class DragonWheelReport:
    schema_id: str
    state: str
    source_pabgh_sha256: str
    source_pabgb_sha256: str
    output_pabgh_sha256: str
    output_pabgb_sha256: str
    before_categories: tuple[int, ...]
    after_categories: tuple[int, ...]
    adjusted_entry_indexes: tuple[int, ...]
    byte_growth: int
    already_enabled: bool


@dataclass(frozen=True)
class DragonWheelPatchResult:
    pabgh: bytes
    pabgb: bytes
    report: DragonWheelReport


def analyze_reserveslot(
    pabgh: bytes,
    pabgb: bytes,
    profile: ReserveSlotProfile = CURRENT_PROFILE,
) -> DragonWheelReport:
    state, entries, target_start, target_end, signature_offset = _inspect(
        pabgh, pabgb, profile
    )
    categories = (0x4E, 0x51) if state == "original" else (0x4E, 0x4F, 0x51)
    h_hash, b_hash = _sha(pabgh), _sha(pabgb)
    return DragonWheelReport(
        schema_id=profile.schema_id,
        state=state,
        source_pabgh_sha256=h_hash,
        source_pabgb_sha256=b_hash,
        output_pabgh_sha256=h_hash,
        output_pabgb_sha256=b_hash,
        before_categories=categories,
        after_categories=categories,
        adjusted_entry_indexes=(),
        byte_growth=0,
        already_enabled=state == "patched",
    )


def enable_dragon_category(
    pabgh: bytes,
    pabgb: bytes,
    profile: ReserveSlotProfile = CURRENT_PROFILE,
) -> DragonWheelPatchResult:
    before = analyze_reserveslot(pabgh, pabgb, profile)
    if before.already_enabled:
        return DragonWheelPatchResult(pabgh, pabgb, before)

    _, entries, target_start, _, signature_offset = _inspect(pabgh, pabgb, profile)
    count_offset = target_start + signature_offset
    insert_offset = count_offset + 5
    new_h = bytearray(pabgh)
    new_b = bytearray(pabgb)
    struct.pack_into("<I", new_b, count_offset, 3)
    new_b[insert_offset:insert_offset] = b"\x4f"
    adjusted = tuple(range(profile.target_index + 1, profile.entry_count))
    for index in adjusted:
        field_offset = 2 + index * 8 + 4
        old_offset = struct.unpack_from("<I", new_h, field_offset)[0]
        struct.pack_into("<I", new_h, field_offset, old_offset + 1)

    candidate_h, candidate_b = bytes(new_h), bytes(new_b)
    candidate = analyze_reserveslot(candidate_h, candidate_b, profile)
    if candidate.state != "patched":
        raise ReserveSlotCompatibilityError("Candidate did not validate as patched")

    inverse_h = bytearray(candidate_h)
    inverse_b = bytearray(candidate_b)
    for index in adjusted:
        field_offset = 2 + index * 8 + 4
        old_offset = struct.unpack_from("<I", inverse_h, field_offset)[0]
        struct.pack_into("<I", inverse_h, field_offset, old_offset - 1)
    del inverse_b[insert_offset]
    struct.pack_into("<I", inverse_b, count_offset, 2)
    if bytes(inverse_h) != pabgh or bytes(inverse_b) != pabgb:
        raise ReserveSlotCompatibilityError("Candidate inverse check failed")

    report = DragonWheelReport(
        schema_id=profile.schema_id,
        state="patched",
        source_pabgh_sha256=before.source_pabgh_sha256,
        source_pabgb_sha256=before.source_pabgb_sha256,
        output_pabgh_sha256=candidate.output_pabgh_sha256,
        output_pabgb_sha256=candidate.output_pabgb_sha256,
        before_categories=(0x4E, 0x51),
        after_categories=(0x4E, 0x4F, 0x51),
        adjusted_entry_indexes=adjusted,
        byte_growth=1,
        already_enabled=False,
    )
    return DragonWheelPatchResult(candidate_h, candidate_b, report)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_index(pabgh: bytes, pabgb: bytes, profile: ReserveSlotProfile):
    expected_size = 2 + profile.entry_count * 8
    if len(pabgh) != expected_size:
        raise ReserveSlotCompatibilityError(
            f"PABGH size {len(pabgh)} does not match {expected_size}"
        )
    count = struct.unpack_from("<H", pabgh, 0)[0]
    if count != profile.entry_count:
        raise ReserveSlotCompatibilityError(f"Unexpected entry count {count}")
    entries = tuple(
        struct.unpack_from("<II", pabgh, 2 + index * 8)
        for index in range(count)
    )
    offsets = [offset for _, offset in entries]
    if not offsets or offsets[0] != 0 or offsets != sorted(offsets):
        raise ReserveSlotCompatibilityError("PABGH offsets are not ordered from zero")
    if offsets[-1] >= len(pabgb):
        raise ReserveSlotCompatibilityError("PABGH offset is outside PABGB")
    if entries[profile.target_index][0] != profile.target_key:
        raise ReserveSlotCompatibilityError("Target key is not at the supported index")
    return entries


def _inspect(pabgh: bytes, pabgb: bytes, profile: ReserveSlotProfile):
    hashes = (_sha(pabgh), _sha(pabgb))
    original = (profile.original_pabgh_sha256, profile.original_pabgb_sha256)
    patched = (profile.patched_pabgh_sha256, profile.patched_pabgb_sha256)
    if hashes == original:
        state, signature = "original", ORIGINAL_SIGNATURE
    elif hashes == patched:
        state, signature = "patched", PATCHED_SIGNATURE
    else:
        raise ReserveSlotCompatibilityError(
            f"Unsupported ReserveSlot hashes: {hashes[0]} / {hashes[1]}"
        )

    entries = _parse_index(pabgh, pabgb, profile)
    target_start = entries[profile.target_index][1]
    target_end = entries[profile.target_index + 1][1]
    record = pabgb[target_start:target_end]
    if len(record) < 8:
        raise ReserveSlotCompatibilityError("Target record is truncated")
    embedded_key, name_size = struct.unpack_from("<II", record, 0)
    name_end = 8 + name_size
    if embedded_key != profile.target_key or record[8:name_end] != profile.target_name:
        raise ReserveSlotCompatibilityError("Target record key or name changed")
    if record.count(signature) != 1:
        raise ReserveSlotCompatibilityError("Target category signature is not unique")
    other = PATCHED_SIGNATURE if state == "original" else ORIGINAL_SIGNATURE
    if other in record:
        raise ReserveSlotCompatibilityError("Target contains conflicting category signatures")
    return state, entries, target_start, target_end, record.index(signature)
```

Every mismatch raises `ReserveSlotCompatibilityError`; do not add a permissive
flag.

- [ ] **Step 4: Run the patcher tests and verify GREEN**

Run the Step 2 command. Expected: all patcher tests pass.

- [ ] **Step 5: Commit the pure patcher**

```powershell
git add CrimsonGameMods/dragon_wheel_patch.py tests/test_dragon_wheel_patch.py
git commit -m "feat: add strict Dragon wheel byte patcher"
```

### Task 2: Transactional Overlay Deployment

**Files:**
- Create: `CrimsonGameMods/dragon_wheel_deploy.py`
- Create: `tests/test_dragon_wheel_deploy.py`
- Modify: `CrimsonGameMods/overlay_coordinator.py`

- [ ] **Step 1: Write failing filesystem transaction tests**

Create tests that use `tmp_path` and a small fake `crimson_rs` adapter. The fake
must implement `PackGroupBuilder`, `parse_pamt_bytes`, `parse_papgt_file`,
`add_papgt_entry`, and `write_papgt_file` using ordinary files and dictionaries.

```python
def test_apply_creates_backup_marker_and_preserves_papgt(tmp_path, fake_crimson_rs, patch_result):
    game = make_game_tree(tmp_path, groups=["0008", "0042"])
    backup_root = tmp_path / "backups"
    receipt = deploy_dragon_wheel(
        game_path=game,
        overlay_group="0067",
        patch_result=patch_result,
        backup_root=backup_root,
        crimson_rs_module=fake_crimson_rs,
        timestamp="20260715-210000",
    )
    assert receipt.backup_dir == backup_root / "20260715-210000"
    assert (receipt.backup_dir / "0.papgt").is_file()
    assert (game / "0067" / ".se_dragon_wheel").is_file()
    assert registered_groups(game, fake_crimson_rs) == {"0008", "0042", "0067"}


def test_apply_refuses_unmarked_existing_overlay(tmp_path, fake_crimson_rs, patch_result):
    game = make_game_tree(tmp_path, groups=["0008", "0067"])
    with pytest.raises(DragonWheelDeploymentError, match="not owned"):
        deploy_dragon_wheel(
            game, "0067", patch_result, tmp_path / "backups",
            fake_crimson_rs, "20260715-210000"
        )


def test_apply_rolls_back_after_papgt_failure(tmp_path, failing_crimson_rs, patch_result):
    game = make_game_tree(tmp_path, groups=["0008"])
    original_papgt = (game / "meta" / "0.papgt").read_bytes()
    with pytest.raises(DragonWheelDeploymentError, match="rolled back"):
        deploy_dragon_wheel(
            game, "0067", patch_result, tmp_path / "backups",
            failing_crimson_rs, "20260715-210000"
        )
    assert (game / "meta" / "0.papgt").read_bytes() == original_papgt
    assert not (game / "0067").exists()


def test_restore_refuses_foreign_overlay(tmp_path, fake_crimson_rs):
    game = make_game_tree(tmp_path, groups=["0008", "0067"])
    with pytest.raises(DragonWheelDeploymentError, match="ownership marker"):
        restore_dragon_wheel(game, "0067", fake_crimson_rs)
```

- [ ] **Step 2: Run deployer tests and verify RED**

```powershell
$env:PYTHONPATH = (Resolve-Path 'CrimsonGameMods').Path
.\.venv\Scripts\python.exe -m pytest tests\test_dragon_wheel_deploy.py -v
```

Expected: collection fails because `dragon_wheel_deploy` does not exist.

- [ ] **Step 3: Implement deploy, rollback, and restore**

Create `CrimsonGameMods/dragon_wheel_deploy.py` with:

```python
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from dragon_wheel_patch import DragonWheelPatchResult


INTERNAL_DIR = "gamedata/binary__/client/bin"
MARKER_NAME = ".se_dragon_wheel"


@dataclass(frozen=True)
class DeploymentReceipt:
    overlay_group: str
    backup_dir: Path
    papgt_groups_before: tuple[str, ...]
    papgt_groups_after: tuple[str, ...]
    candidate_pabgh_sha256: str
    candidate_pabgb_sha256: str


class DragonWheelDeploymentError(RuntimeError):
    pass


def deploy_dragon_wheel(
    game_path: str | Path,
    overlay_group: str,
    patch_result: DragonWheelPatchResult,
    backup_root: str | Path,
    crimson_rs_module,
    timestamp: str | None = None,
) -> DeploymentReceipt:
    game = Path(game_path)
    group = _validate_group(overlay_group)
    live_overlay = game / group
    marker = live_overlay / MARKER_NAME
    papgt_path = game / "meta" / "0.papgt"
    if not papgt_path.is_file():
        raise DragonWheelDeploymentError("meta/0.papgt is missing")
    if live_overlay.exists() and not marker.is_file():
        raise DragonWheelDeploymentError(
            f"Overlay {group} exists and is not owned by Dragon Wheel"
        )

    from overlay_coordinator import post_write, pre_write
    safe, reason = pre_write(str(game), group, owner="CrimsonGameMods")
    if not safe:
        raise DragonWheelDeploymentError(reason)

    stamp = timestamp or time.strftime("%Y%m%d-%H%M%S")
    backup_dir = Path(backup_root) / stamp
    if backup_dir.exists():
        raise DragonWheelDeploymentError(f"Backup already exists: {backup_dir}")

    original_overlay_existed = live_overlay.exists()
    papgt_temp: Path | None = None
    backup_started = False
    try:
        with tempfile.TemporaryDirectory(prefix="dragon-wheel-build-") as temp:
            stage = Path(temp) / group
            builder = crimson_rs_module.PackGroupBuilder(
                str(stage),
                crimson_rs_module.Compression.NONE,
                crimson_rs_module.Crypto.NONE,
            )
            builder.add_file(INTERNAL_DIR, "reserveslot.pabgb", patch_result.pabgb)
            builder.add_file(INTERNAL_DIR, "reserveslot.pabgh", patch_result.pabgh)
            pamt_bytes = bytes(builder.finish())
            checksum = crimson_rs_module.parse_pamt_bytes(pamt_bytes)["checksum"]
            if not (stage / "0.paz").is_file() or not (stage / "0.pamt").is_file():
                raise DragonWheelDeploymentError("PAZ builder did not produce 0.paz and 0.pamt")
            (stage / MARKER_NAME).write_text(
                json.dumps({
                    "schema_id": patch_result.report.schema_id,
                    "pabgh_sha256": patch_result.report.output_pabgh_sha256,
                    "pabgb_sha256": patch_result.report.output_pabgb_sha256,
                }, indent=2),
                encoding="utf-8",
            )

            backup_dir.mkdir(parents=True)
            backup_started = True
            shutil.copy2(papgt_path, backup_dir / "0.papgt")
            if original_overlay_existed:
                shutil.copytree(live_overlay, backup_dir / group)

            before_doc = crimson_rs_module.parse_papgt_file(str(papgt_path))
            before_groups = tuple(
                entry["group_name"] for entry in before_doc.get("entries", [])
            )
            next_doc = dict(before_doc)
            next_doc["entries"] = [
                entry for entry in before_doc.get("entries", [])
                if entry.get("group_name") != group
            ]
            next_doc = crimson_rs_module.add_papgt_entry(
                next_doc, group, checksum, is_optional=0, language=0x3FFF
            )
            papgt_temp = papgt_path.with_name(
                f".0.papgt.dragon-wheel-{uuid.uuid4().hex}.tmp"
            )
            crimson_rs_module.write_papgt_file(next_doc, str(papgt_temp))
            verified_doc = crimson_rs_module.parse_papgt_file(str(papgt_temp))
            after_groups = tuple(
                entry["group_name"] for entry in verified_doc.get("entries", [])
            )
            expected = (set(before_groups) - {group}) | {group}
            if set(after_groups) != expected:
                raise DragonWheelDeploymentError("Temporary PAPGT verification failed")

            if live_overlay.exists():
                shutil.rmtree(live_overlay)
            shutil.copytree(stage, live_overlay)
            os.replace(papgt_temp, papgt_path)
            papgt_temp = None

        post_write(
            str(game), group, "Dragon Wheel",
            ["reserveslot.pabgb", "reserveslot.pabgh"],
            owner="CrimsonGameMods",
        )
        return DeploymentReceipt(
            overlay_group=group,
            backup_dir=backup_dir,
            papgt_groups_before=before_groups,
            papgt_groups_after=after_groups,
            candidate_pabgh_sha256=patch_result.report.output_pabgh_sha256,
            candidate_pabgb_sha256=patch_result.report.output_pabgb_sha256,
        )
    except Exception as exc:
        if papgt_temp is not None:
            papgt_temp.unlink(missing_ok=True)
        if backup_started:
            shutil.copy2(backup_dir / "0.papgt", papgt_path)
            if live_overlay.exists():
                shutil.rmtree(live_overlay)
            saved_overlay = backup_dir / group
            if saved_overlay.exists():
                shutil.copytree(saved_overlay, live_overlay)
        if isinstance(exc, DragonWheelDeploymentError):
            raise DragonWheelDeploymentError(f"{exc}; rolled back") from exc
        raise DragonWheelDeploymentError(f"Deployment failed and rolled back: {exc}") from exc


def restore_dragon_wheel(
    game_path: str | Path,
    overlay_group: str,
    crimson_rs_module,
) -> tuple[str, ...]:
    game = Path(game_path)
    group = _validate_group(overlay_group)
    overlay = game / group
    marker = overlay / MARKER_NAME
    papgt_path = game / "meta" / "0.papgt"
    if not marker.is_file():
        raise DragonWheelDeploymentError("Dragon Wheel ownership marker is missing")

    from overlay_coordinator import post_restore, pre_restore
    safe, reason = pre_restore(str(game), group, owner="CrimsonGameMods")
    if not safe:
        raise DragonWheelDeploymentError(reason)

    original_papgt = papgt_path.read_bytes()
    rollback_overlay = overlay.with_name(f".{group}.dragon-wheel-rollback-{uuid.uuid4().hex}")
    papgt_temp = papgt_path.with_name(f".0.papgt.dragon-wheel-{uuid.uuid4().hex}.tmp")
    try:
        doc = crimson_rs_module.parse_papgt_file(str(papgt_path))
        doc["entries"] = [
            entry for entry in doc.get("entries", [])
            if entry.get("group_name") != group
        ]
        crimson_rs_module.write_papgt_file(doc, str(papgt_temp))
        verified = crimson_rs_module.parse_papgt_file(str(papgt_temp))
        remaining = tuple(entry["group_name"] for entry in verified.get("entries", []))
        if group in remaining:
            raise DragonWheelDeploymentError("Temporary PAPGT still contains overlay")
        os.replace(overlay, rollback_overlay)
        os.replace(papgt_temp, papgt_path)
        shutil.rmtree(rollback_overlay)
        post_restore(str(game), group)
        return remaining
    except Exception as exc:
        papgt_temp.unlink(missing_ok=True)
        papgt_path.write_bytes(original_papgt)
        if rollback_overlay.exists() and not overlay.exists():
            os.replace(rollback_overlay, overlay)
        if isinstance(exc, DragonWheelDeploymentError):
            raise
        raise DragonWheelDeploymentError(f"Restore failed and rolled back: {exc}") from exc


def _validate_group(group: str) -> str:
    if group != "0067":
        raise DragonWheelDeploymentError(
            f"Dragon Wheel must use reserved group 0067, not {group}"
        )
    return group
```

Build the PAZ in a temporary directory before mutation. Require the dedicated
group 0067 because 0066 is already owned by ItemBuffs. Refuse an existing
directory without `.se_dragon_wheel`.
Back up PAPGT and any owned overlay before mutation. Write and parse a temporary
PAPGT, verify all prior groups remain, then atomically replace live PAPGT. Roll
back PAPGT and the overlay on every failure. Restore must remove only a marked
overlay and its PAPGT entry.

Add `"0067": "Dragon Wheel (reserveslot)"` to
`overlay_coordinator.OUR_GROUPS`, and call `pre_write`, `post_write`,
`pre_restore`, and `post_restore` at the documented transaction boundaries.

- [ ] **Step 4: Run deployer and patcher tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_dragon_wheel_patch.py tests\test_dragon_wheel_deploy.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit deployment support**

```powershell
git add CrimsonGameMods/dragon_wheel_deploy.py CrimsonGameMods/overlay_coordinator.py tests/test_dragon_wheel_deploy.py
git commit -m "feat: deploy Dragon wheel overlay transactionally"
```

### Task 3: Focused Dragon Wheel Tab

**Files:**
- Replace: `CrimsonGameMods/gui/tabs/reserveslot.py`
- Modify: `CrimsonGameMods/gui/main_window.py`
- Create: `tests/test_dragon_wheel_gui_contract.py`

- [ ] **Step 1: Write failing GUI contract tests**

Use source-level contracts for packaging-safe tab wiring and lightweight Qt
tests for button state when PySide6 is available.

```python
def test_main_window_registers_dragon_wheel_tab():
    source = Path("CrimsonGameMods/gui/main_window.py").read_text(encoding="utf-8")
    assert "from gui.tabs.reserveslot import ReserveSlotTab" in source
    assert 'self._mods_tabs.addTab(self._reserve_slot_tab, "Dragon Wheel")' in source
    assert "self._reserve_slot_tab.set_game_path(path)" in source


def test_tab_has_no_broad_all_mounts_action():
    source = Path("CrimsonGameMods/gui/tabs/reserveslot.py").read_text(encoding="utf-8")
    assert "All Mounts Everywhere" not in source
    assert "Preview Dragon Wheel Patch" in source
    assert "Apply Dragon Wheel Patch" in source
    assert "Restore Dragon Wheel Patch" in source


def test_apply_starts_disabled(qtbot):
    tab = ReserveSlotTab({}, lambda: "")
    qtbot.addWidget(tab)
    assert tab._apply_btn.isEnabled() is False
```

- [ ] **Step 2: Run GUI contract tests and verify RED**

```powershell
$env:PYTHONPATH = "$(Resolve-Path 'CrimsonGameMods');$(Resolve-Path 'CrimsonSaveEditor')"
.\.venv\Scripts\python.exe -m pytest tests\test_dragon_wheel_gui_contract.py -v
```

Expected: tests fail because the tab is not wired and still contains the broad preset.

- [ ] **Step 3: Replace the dormant editor with the focused workflow**

Implement `ReserveSlotTab` with these state fields and handlers:

```python
self._source_hashes: tuple[str, str] | None = None
self._preview_result: DragonWheelPatchResult | None = None
self._analyze_btn.clicked.connect(self._analyze_game_files)
self._preview_btn.clicked.connect(self._preview_patch)
self._apply_btn.clicked.connect(self._apply_patch)
self._restore_btn.clicked.connect(self._restore_patch)
self._apply_btn.setEnabled(False)
```

`_extract_source()` must call `crimson_rs.extract_file` for the two ReserveSlot
files. Analyze displays schema and current categories. Preview builds only in
memory, stores source hashes, and enables Apply. Apply re-extracts, rejects stale
hashes, rebuilds and compares the candidate, confirms exact changes, and calls
`deploy_dragon_wheel`. Restore calls `restore_dragon_wheel`. All compatibility
and deployment exceptions must be shown as refusal/failure, never success.

Use a read-only `QPlainTextEdit` report and explicit labels stating:

```text
Modifies game-data overlays only. Does not edit save files or quest flags.
Close Crimson Desert before Apply/Restore and fully restart it afterward.
```

Wire the tab in `main_window.py`, including signal connections, initial game
path, and `_set_game_path` propagation.

- [ ] **Step 4: Run GUI and service tests and verify GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_dragon_wheel_gui_contract.py tests\test_dragon_wheel_patch.py tests\test_dragon_wheel_deploy.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the focused UI**

```powershell
git add CrimsonGameMods/gui/tabs/reserveslot.py CrimsonGameMods/gui/main_window.py tests/test_dragon_wheel_gui_contract.py
git commit -m "feat: expose safe Dragon wheel workflow"
```

### Task 4: Packaging and Installed-File Read-Only Verification

**Files:**
- Modify: `CrimsonGameMods/CrimsonGameMods.spec`
- Modify: `tests/test_packaging_contract.py`
- Create: `tests/test_dragon_wheel_installed.py`

- [ ] **Step 1: Write failing packaging and integration tests**

Add packaging assertions:

```python
def test_game_mods_packages_dragon_wheel_modules():
    spec = Path("CrimsonGameMods/CrimsonGameMods.spec").read_text(encoding="utf-8")
    assert "dragon_wheel_patch" in spec
    assert "dragon_wheel_deploy" in spec
    assert "gui.tabs.reserveslot" in spec
```

Create an opt-in installed-file test:

```python
@pytest.mark.skipif(
    not os.environ.get("CRIMSON_DESERT_GAME_PATH"),
    reason="Set CRIMSON_DESERT_GAME_PATH for read-only installed-file verification",
)
def test_installed_reserveslot_builds_expected_candidate_without_writing():
    game_path = os.environ["CRIMSON_DESERT_GAME_PATH"]
    h = bytes(crimson_rs.extract_file(
        game_path, "0008", "gamedata/binary__/client/bin", "reserveslot.pabgh"
    ))
    b = bytes(crimson_rs.extract_file(
        game_path, "0008", "gamedata/binary__/client/bin", "reserveslot.pabgb"
    ))
    result = enable_dragon_category(h, b)
    assert result.report.schema_id == CURRENT_PROFILE.schema_id
    assert result.report.after_categories == (0x4E, 0x4F, 0x51)
    assert result.report.output_pabgh_sha256 == CURRENT_PROFILE.patched_pabgh_sha256
    assert result.report.output_pabgb_sha256 == CURRENT_PROFILE.patched_pabgb_sha256
```

- [ ] **Step 2: Run the new tests and verify RED**

```powershell
$env:PYTHONPATH = (Resolve-Path 'CrimsonGameMods').Path
$env:CRIMSON_DESERT_GAME_PATH = 'D:\SteamLibrary\steamapps\common\Crimson Desert'
.\.venv\Scripts\python.exe -m pytest tests\test_packaging_contract.py tests\test_dragon_wheel_installed.py -v
```

Expected: packaging contract fails because the two new hidden imports are absent.

- [ ] **Step 3: Add PyInstaller hidden imports**

Add `'dragon_wheel_patch'` and `'dragon_wheel_deploy'` to `hiddenimports` in
`CrimsonGameMods/CrimsonGameMods.spec`. Keep `gui.tabs.reserveslot`.

- [ ] **Step 4: Run the complete relevant suite**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_dragon_wheel_patch.py tests\test_dragon_wheel_deploy.py tests\test_dragon_wheel_gui_contract.py tests\test_packaging_contract.py tests\test_dragon_wheel_installed.py -v
```

Expected: all tests pass; installed-file test performs extraction and in-memory
mutation only.

- [ ] **Step 5: Commit packaging coverage**

```powershell
git add CrimsonGameMods/CrimsonGameMods.spec tests/test_packaging_contract.py tests/test_dragon_wheel_installed.py
git commit -m "test: verify packaged Dragon wheel support"
```

### Task 5: Build and Packaged Smoke Test

**Files:**
- Build output: `CrimsonGameMods/dist/CrimsonGameMods.exe`

- [ ] **Step 1: Run the full repository safety suite**

```powershell
.\.venv\Scripts\python.exe -m pytest tests -v --timeout=300
```

Expected: all tests pass and fixture integrity remains unchanged.

- [ ] **Step 2: Build the Game Mods executable**

```powershell
Push-Location CrimsonGameMods
& ..\.venv\Scripts\python.exe -m PyInstaller CrimsonGameMods.spec --noconfirm --clean
Pop-Location
```

Expected: `CrimsonGameMods/dist/CrimsonGameMods.exe` exists and PyInstaller
reports a successful build.

- [ ] **Step 3: Verify packaged contents and executable metadata**

```powershell
Get-Item CrimsonGameMods\dist\CrimsonGameMods.exe |
    Select-Object FullName, Length, LastWriteTimeUtc
Get-FileHash CrimsonGameMods\dist\CrimsonGameMods.exe -Algorithm SHA256
```

Expected: a non-empty executable and a recorded SHA-256 hash.

- [ ] **Step 4: Perform a packaged UI smoke test without applying**

Launch the executable, confirm the `Dragon Wheel` tab appears, use `Analyze Game
Files` and `Preview Dragon Wheel Patch`, verify the report shows
`[0x4E, 0x51] -> [0x4E, 0x4F, 0x51]`, then close the application without clicking
Apply. Confirm the installed game directory timestamps and hashes for PAPGT and
all overlay directories remain unchanged.

- [ ] **Step 5: Record final verification evidence**

Run:

```powershell
git status --short --branch
git log -6 --oneline --decorate
```

Expected: only the user's pre-existing untracked `tests/fixtures/` remains
outside committed implementation changes.
