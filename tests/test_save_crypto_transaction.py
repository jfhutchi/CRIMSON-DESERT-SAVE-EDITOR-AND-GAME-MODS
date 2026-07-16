from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest

import save_crypto
from blackstar_unlock import unlock_blackstar
from blackstar_compat import make_blackstar_apply_token
from save_crypto import (
    VERSION_OFFSET,
    load_save_file,
    serialize_save_bytes,
    transactional_write_save,
    transactional_write_blackstar,
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


def test_save_as_backs_up_existing_destination_not_loaded_source(
    copied_save: Path,
    tmp_path: Path,
) -> None:
    save = load_save_file(str(copied_save))
    source_hash = _sha256(copied_save)
    destination = tmp_path / "existing-slot" / "save.save"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(
        serialize_save_bytes(
            bytes(save.decompressed_blob),
            save.raw_header,
            "save-as-existing-destination-setup",
        )
    )
    destination_hash = _sha256(destination)
    assert destination_hash != source_hash

    result = transactional_write_save(
        destination=destination,
        edited_blob=bytes(save.decompressed_blob),
        original_header=save.raw_header,
        backup_source=copied_save,
        expected_identity=save.schema_identity,
        operation_id="save-as-existing-destination-test",
    )

    assert result.backup_path.parent == destination.parent / "backups"
    assert _sha256(result.backup_path) == destination_hash


def test_destination_change_after_backup_aborts_replace(
    copied_save: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save = load_save_file(str(copied_save))
    original_serialize = save_crypto.serialize_save_bytes
    externally_changed = b"changed by another process"

    def mutate_destination_after_backup(*args, **kwargs) -> bytes:
        serialized = original_serialize(*args, **kwargs)
        copied_save.write_bytes(externally_changed)
        return serialized

    monkeypatch.setattr(
        save_crypto, "serialize_save_bytes", mutate_destination_after_backup
    )
    with pytest.raises(RuntimeError, match="changed after its verified backup"):
        transactional_write_save(
            destination=copied_save,
            edited_blob=bytes(save.decompressed_blob),
            original_header=save.raw_header,
            backup_source=copied_save,
            expected_identity=save.schema_identity,
            operation_id="destination-race-test",
        )

    assert copied_save.read_bytes() == externally_changed


def test_blackstar_apply_write_reload_is_idempotent(copied_save: Path) -> None:
    save = load_save_file(str(copied_save))
    original_encrypted_hash = _sha256(copied_save)

    applied = unlock_blackstar(
        blob=save.decompressed_blob,
        identity=save.schema_identity,
        dry_run=False,
        operation_id="blackstar-transaction-test",
    )
    assert applied.output_blob is not None
    assert applied.report.quest_changes == 0

    write_result = transactional_write_save(
        destination=copied_save,
        edited_blob=applied.output_blob,
        original_header=save.raw_header,
        backup_source=copied_save,
        expected_identity=save.schema_identity,
        operation_id="blackstar-transaction-test",
    )

    assert _sha256(write_result.backup_path) == original_encrypted_hash
    reloaded = load_save_file(str(copied_save))
    second = unlock_blackstar(
        blob=reloaded.decompressed_blob,
        identity=reloaded.schema_identity,
        dry_run=False,
        operation_id="blackstar-transaction-second-run",
    )
    assert second.output_blob == bytes(reloaded.decompressed_blob)
    assert second.report.byte_growth == 0
    assert second.report.knowledge_changes == 0
    assert second.report.quest_changes == 0


def test_scoped_blackstar_transaction_writes_unknown_schema_with_backup(
    early_114_save_path: Path, tmp_path: Path
) -> None:
    destination = tmp_path / "early" / "save.save"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(early_114_save_path.read_bytes())
    save = load_save_file(str(destination))
    preview = unlock_blackstar(
        save.decompressed_blob, save.schema_identity, True, "scoped-preview"
    )
    applied = unlock_blackstar(
        save.decompressed_blob, save.schema_identity, False, "scoped-apply"
    )
    token = make_blackstar_apply_token(
        destination, bytes(save.decompressed_blob), save.schema_identity,
        preview.candidate_sha256, generation=3,
    )
    result = transactional_write_blackstar(
        destination, applied.output_blob, save.raw_header, save.schema_identity,
        token, generation=3, operation_id="scoped-write",
    )
    assert result.backup_path.exists()
    reloaded = load_save_file(str(destination))
    assert hashlib.sha256(reloaded.decompressed_blob).hexdigest() == preview.candidate_sha256
