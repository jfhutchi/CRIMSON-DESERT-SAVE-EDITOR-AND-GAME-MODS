from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest

import save_crypto
from save_crypto import (
    VERSION_OFFSET,
    load_save_file,
    serialize_save_bytes,
    transactional_write_save,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_serialization_preserves_version_and_round_trips(
    fixture_save_path: Path,
    tmp_path: Path,
) -> None:
    save = load_save_file(str(fixture_save_path))
    serialized = serialize_save_bytes(
        bytes(save.decompressed_blob), save.raw_header, "serialize-test"
    )
    assert struct.unpack_from("<H", serialized, VERSION_OFFSET)[0] == struct.unpack_from(
        "<H", save.raw_header, VERSION_OFFSET
    )[0]

    output = tmp_path / "serialized.save"
    output.write_bytes(serialized)
    reloaded = load_save_file(str(output))
    assert reloaded.decompressed_blob == save.decompressed_blob


def test_transaction_creates_verified_backup_before_atomic_replace(
    copied_save: Path,
) -> None:
    save = load_save_file(str(copied_save))
    source_hash = _sha256(copied_save)

    result = transactional_write_save(
        destination=copied_save,
        edited_blob=bytes(save.decompressed_blob),
        original_header=save.raw_header,
        backup_source=copied_save,
        expected_identity=save.schema_identity,
        operation_id="transaction-test",
    )

    assert result.destination == copied_save
    assert result.backup_path.exists()
    assert _sha256(result.backup_path) == source_hash
    assert result.output_sha256 == _sha256(copied_save)
    assert not list(copied_save.parent.glob(".save.save.*.tmp"))
    assert load_save_file(str(copied_save)).decompressed_blob == save.decompressed_blob


def test_backup_failure_leaves_destination_untouched(
    copied_save: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save = load_save_file(str(copied_save))
    source_hash = _sha256(copied_save)

    def fail_copy(*_args, **_kwargs) -> None:
        raise OSError("simulated backup failure")

    monkeypatch.setattr(save_crypto.shutil, "copy2", fail_copy)
    with pytest.raises(OSError, match="simulated backup failure"):
        transactional_write_save(
            destination=copied_save,
            edited_blob=bytes(save.decompressed_blob),
            original_header=save.raw_header,
            backup_source=copied_save,
            expected_identity=save.schema_identity,
            operation_id="backup-failure-test",
        )

    assert _sha256(copied_save) == source_hash
    assert not list(copied_save.parent.glob(".save.save.*.tmp"))
