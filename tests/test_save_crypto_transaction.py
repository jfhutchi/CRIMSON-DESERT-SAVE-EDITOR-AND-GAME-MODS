from __future__ import annotations

import hashlib
import struct
from dataclasses import replace
from pathlib import Path

import lz4.block
import pytest

import parc_inserter3
import save_crypto
import save_compat
from blackstar_unlock import unlock_blackstar
from blackstar_compat import BlackstarCompatibilityError, make_blackstar_apply_token
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
    copied_save: Path,
    tmp_path: Path,
) -> None:
    save = load_save_file(str(copied_save))
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


def test_load_with_detect_schema_false_preserves_verified_save_fields(
    copied_save: Path,
) -> None:
    detected = load_save_file(str(copied_save))

    undetected = load_save_file(str(copied_save), detect_schema=False)

    assert undetected.raw_header == detected.raw_header
    assert undetected.decompressed_blob == detected.decompressed_blob
    assert undetected.original_compressed_size == detected.original_compressed_size
    assert undetected.original_decompressed_size == detected.original_decompressed_size
    assert undetected.file_path == detected.file_path
    assert undetected.is_raw_stream is False
    assert undetected.schema_identity is None
    assert undetected.compatibility_profile_id is None
    assert undetected.is_schema_supported is False


def test_loads_capture_sha256_of_exact_encrypted_input(
    copied_save: Path,
) -> None:
    encrypted_sha256 = hashlib.sha256(copied_save.read_bytes()).hexdigest()

    detected = load_save_file(str(copied_save))
    undetected = load_save_file(str(copied_save), detect_schema=False)

    assert detected.source_file_sha256 == encrypted_sha256
    assert undetected.source_file_sha256 == encrypted_sha256


def test_load_with_detect_schema_false_still_rejects_hmac_mismatch(
    copied_save: Path,
    tmp_path: Path,
) -> None:
    save = load_save_file(str(copied_save))
    corrupted = bytearray(
        serialize_save_bytes(
            bytes(save.decompressed_blob), save.raw_header, "hmac-corruption-setup"
        )
    )
    corrupted[save_crypto.HMAC_OFFSET] ^= 0x01
    corrupted_path = tmp_path / "hmac-corrupt.save"
    corrupted_path.write_bytes(corrupted)

    with pytest.raises(Warning, match="HMAC mismatch"):
        load_save_file(str(corrupted_path), detect_schema=False)


def test_load_with_detect_schema_false_still_validates_decompression(
    copied_save: Path,
    tmp_path: Path,
) -> None:
    save = load_save_file(str(copied_save))
    serialized = bytearray(
        serialize_save_bytes(
            bytes(save.decompressed_blob), save.raw_header, "lz4-corruption-setup"
        )
    )
    version = struct.unpack_from("<H", serialized, save_crypto.VERSION_OFFSET)[0]
    payload_size = struct.unpack_from(
        "<I", serialized, save_crypto.PAYLOAD_SIZE_OFFSET
    )[0]
    nonce = bytes(
        serialized[save_crypto.NONCE_OFFSET:save_crypto.NONCE_OFFSET + 16]
    )
    key = save_crypto._generate_save_key(version)
    invalid_compressed = bytes(payload_size)
    serialized[
        save_crypto.HMAC_OFFSET:save_crypto.HMAC_OFFSET + 32
    ] = save_crypto.compute_hmac(invalid_compressed, key)
    serialized[save_crypto.PAYLOAD_OFFSET:] = save_crypto.chacha20_crypt(
        invalid_compressed, nonce, key
    )
    corrupted_path = tmp_path / "lz4-corrupt.save"
    corrupted_path.write_bytes(serialized)

    with pytest.raises(lz4.block.LZ4BlockError):
        load_save_file(str(corrupted_path), detect_schema=False)


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


def test_verified_backup_is_not_reloaded(
    copied_save: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save = load_save_file(str(copied_save))
    source_bytes = copied_save.read_bytes()
    original_load = save_crypto.load_save_file
    loaded_paths: list[Path] = []

    def reject_backup_reload(path, *args, **kwargs):
        loaded_path = Path(path)
        loaded_paths.append(loaded_path)
        if loaded_path.suffix == ".bak":
            pytest.fail("a byte-identical verified backup must not be reloaded")
        return original_load(path, *args, **kwargs)

    monkeypatch.setattr(save_crypto, "load_save_file", reject_backup_reload)

    result = transactional_write_save(
        destination=copied_save,
        edited_blob=bytes(save.decompressed_blob),
        original_header=save.raw_header,
        backup_source=copied_save,
        expected_identity=save.schema_identity,
        operation_id="backup-reload-budget",
    )

    assert result.backup_path.read_bytes() == source_bytes
    assert len(loaded_paths) == 1
    assert loaded_paths[0].suffix == ".tmp"


def test_temporary_verification_reloads_without_schema_detection(
    copied_save: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save = load_save_file(str(copied_save))
    edited_blob = bytes(save.decompressed_blob)
    original_load = save_crypto.load_save_file
    temp_verifications = []

    def record_temp_reload(path, *args, **kwargs):
        reloaded = original_load(path, *args, **kwargs)
        if Path(path).suffix == ".tmp":
            temp_verifications.append((kwargs.get("detect_schema"), reloaded))
        return reloaded

    monkeypatch.setattr(save_crypto, "load_save_file", record_temp_reload)

    transactional_write_save(
        destination=copied_save,
        edited_blob=edited_blob,
        original_header=save.raw_header,
        backup_source=copied_save,
        expected_identity=save.schema_identity,
        operation_id="temporary-reload-budget",
    )

    assert len(temp_verifications) == 1
    detect_schema, reloaded = temp_verifications[0]
    assert detect_schema is False
    assert hashlib.sha256(reloaded.decompressed_blob).digest() == hashlib.sha256(
        edited_blob
    ).digest()
    assert bytes(reloaded.decompressed_blob) == edited_blob
    assert reloaded.schema_identity is None
    assert reloaded.compatibility_profile_id is None
    assert reloaded.is_schema_supported is False


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


def test_save_as_rejects_invalid_occupied_destination_after_verified_backup(
    copied_save: Path,
    tmp_path: Path,
) -> None:
    save = load_save_file(str(copied_save))
    destination = tmp_path / "invalid-slot" / "save.save"
    destination.parent.mkdir(parents=True)
    invalid_bytes = b"NOT!" + bytes(200)
    destination.write_bytes(invalid_bytes)

    with pytest.raises(ValueError, match="Bad magic"):
        transactional_write_save(
            destination=destination,
            edited_blob=bytes(save.decompressed_blob),
            original_header=save.raw_header,
            backup_source=copied_save,
            expected_identity=save.schema_identity,
            operation_id="save-as-invalid-destination-test",
        )

    assert destination.read_bytes() == invalid_bytes
    backups = list((destination.parent / "backups").glob("*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == invalid_bytes
    assert not list(destination.parent.glob(".save.save.*.tmp"))


def test_save_as_rejects_unknown_occupied_destination_after_verified_backup(
    copied_save: Path,
    early_114_save_path: Path,
    tmp_path: Path,
) -> None:
    save = load_save_file(str(copied_save))
    destination = tmp_path / "unknown-slot" / "save.save"
    destination.parent.mkdir(parents=True)
    unknown_bytes = early_114_save_path.read_bytes()
    destination.write_bytes(unknown_bytes)

    with pytest.raises(save_compat.UnknownSaveSchemaError):
        transactional_write_save(
            destination=destination,
            edited_blob=bytes(save.decompressed_blob),
            original_header=save.raw_header,
            backup_source=copied_save,
            expected_identity=save.schema_identity,
            operation_id="save-as-unknown-destination-test",
        )

    assert destination.read_bytes() == unknown_bytes
    backups = list((destination.parent / "backups").glob("*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == unknown_bytes
    assert not list(destination.parent.glob(".save.save.*.tmp"))

def test_destination_change_after_backup_aborts_replace(
    copied_save: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save = load_save_file(str(copied_save))
    source_bytes = copied_save.read_bytes()
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
    backups = list((copied_save.parent / "backups").glob("*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == source_bytes
    assert not list(copied_save.parent.glob(".save.save.*.tmp"))


def test_unsupported_candidate_schema_is_refused_before_backup(
    copied_save: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save = load_save_file(str(copied_save))
    source_bytes = copied_save.read_bytes()
    original_compute = save_compat.compute_schema_identity

    def unsupported_candidate(blob, raw_header):
        identity = original_compute(blob, raw_header)
        return replace(identity, schema_sha256="0" * 64)

    monkeypatch.setattr(save_compat, "compute_schema_identity", unsupported_candidate)

    with pytest.raises(
        save_compat.UnknownSaveSchemaError,
        match="Edited blob schema differs from the loaded schema",
    ):
        transactional_write_save(
            destination=copied_save,
            edited_blob=bytes(save.decompressed_blob),
            original_header=save.raw_header,
            backup_source=copied_save,
            expected_identity=save.schema_identity,
            operation_id="unsupported-candidate-test",
        )

    assert copied_save.read_bytes() == source_bytes
    assert not (copied_save.parent / "backups").exists()


def test_corrupted_temporary_save_cannot_replace_destination(
    copied_save: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save = load_save_file(str(copied_save))
    source_bytes = copied_save.read_bytes()
    original_serialize = save_crypto.serialize_save_bytes

    def corrupt_temporary_hmac(*args, **kwargs) -> bytes:
        serialized = bytearray(original_serialize(*args, **kwargs))
        serialized[save_crypto.HMAC_OFFSET] ^= 0x01
        return bytes(serialized)

    monkeypatch.setattr(
        save_crypto, "serialize_save_bytes", corrupt_temporary_hmac
    )

    with pytest.raises(Warning, match="HMAC mismatch"):
        transactional_write_save(
            destination=copied_save,
            edited_blob=bytes(save.decompressed_blob),
            original_header=save.raw_header,
            backup_source=copied_save,
            expected_identity=save.schema_identity,
            operation_id="temporary-corruption-test",
        )

    assert copied_save.read_bytes() == source_bytes
    backups = list((copied_save.parent / "backups").glob("*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == source_bytes
    assert not list(copied_save.parent.glob(".save.save.*.tmp"))


def test_scoped_blackstar_transaction_rejects_changed_source(
    copied_save: Path,
) -> None:
    save = load_save_file(str(copied_save))
    edited_blob = bytes(save.decompressed_blob)
    token = make_blackstar_apply_token(
        copied_save,
        edited_blob,
        save.schema_identity,
        hashlib.sha256(edited_blob).hexdigest(),
        generation=4,
        source_file_sha256=save.source_file_sha256,
    )
    copied_save.write_bytes(copied_save.read_bytes() + b"changed")

    with pytest.raises(BlackstarCompatibilityError, match="changed after preview"):
        transactional_write_blackstar(
            copied_save,
            edited_blob,
            save.raw_header,
            save.schema_identity,
            token,
            generation=4,
            loaded_blob=edited_blob,
            operation_id="scoped-source-race-test",
        )

    assert not (copied_save.parent / "backups").exists()


def test_scoped_blackstar_token_rejects_change_between_load_and_creation(
    copied_save: Path,
) -> None:
    loaded_file_sha256 = hashlib.sha256(copied_save.read_bytes()).hexdigest()
    save = load_save_file(str(copied_save))
    candidate = unlock_blackstar(
        save.decompressed_blob,
        save.schema_identity,
        False,
        "scoped-stale-preview-candidate",
    )
    assert candidate.output_blob is not None

    replacement = serialize_save_bytes(
        bytes(save.decompressed_blob),
        save.raw_header,
        "scoped-stale-preview-replacement",
    )
    assert hashlib.sha256(replacement).hexdigest() != loaded_file_sha256
    copied_save.write_bytes(replacement)
    replacement_bytes = copied_save.read_bytes()

    token = make_blackstar_apply_token(
        copied_save,
        bytes(save.decompressed_blob),
        save.schema_identity,
        candidate.candidate_sha256,
        generation=6,
        source_file_sha256=save.source_file_sha256,
    )
    assert token.source_file_sha256 == loaded_file_sha256
    assert token.source_file_sha256 != hashlib.sha256(replacement_bytes).hexdigest()

    with pytest.raises(BlackstarCompatibilityError, match="changed after preview"):
        transactional_write_blackstar(
            copied_save,
            candidate.output_blob,
            save.raw_header,
            save.schema_identity,
            token,
            generation=6,
            loaded_blob=bytes(save.decompressed_blob),
            operation_id="scoped-stale-preview-write",
        )

    assert copied_save.read_bytes() == replacement_bytes
    assert not (copied_save.parent / "backups").exists()


def test_scoped_blackstar_transaction_binds_expected_schema_hash(
    copied_save: Path,
) -> None:
    save = load_save_file(str(copied_save))
    edited_blob = bytes(save.decompressed_blob)
    token = make_blackstar_apply_token(
        copied_save,
        edited_blob,
        save.schema_identity,
        hashlib.sha256(edited_blob).hexdigest(),
        generation=5,
        source_file_sha256=save.source_file_sha256,
    )
    changed_identity = replace(save.schema_identity, schema_sha256="0" * 64)

    with pytest.raises(BlackstarCompatibilityError, match="schema changed after preview"):
        transactional_write_blackstar(
            copied_save,
            edited_blob,
            save.raw_header,
            changed_identity,
            token,
            generation=5,
            loaded_blob=edited_blob,
            operation_id="scoped-schema-binding-test",
        )

    assert not (copied_save.parent / "backups").exists()


def test_scoped_blackstar_rejects_race_before_backup_hash(
    copied_save: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save = load_save_file(str(copied_save))
    loaded_blob = bytes(save.decompressed_blob)
    token = make_blackstar_apply_token(
        copied_save,
        loaded_blob,
        save.schema_identity,
        hashlib.sha256(loaded_blob).hexdigest(),
        generation=8,
        source_file_sha256=save.source_file_sha256,
    )
    replacement = serialize_save_bytes(
        loaded_blob, save.raw_header, "scoped-backup-race-replacement"
    )
    real_sha256_file = save_crypto._sha256_file
    destination_hash_calls = 0

    def mutate_before_authoritative_hash(path: Path) -> str:
        nonlocal destination_hash_calls
        if Path(path).resolve() == copied_save.resolve():
            destination_hash_calls += 1
            if destination_hash_calls == 2:
                copied_save.write_bytes(replacement)
        return real_sha256_file(path)

    monkeypatch.setattr(save_crypto, "_sha256_file", mutate_before_authoritative_hash)

    with pytest.raises(BlackstarCompatibilityError, match="changed after preview"):
        transactional_write_blackstar(
            copied_save,
            loaded_blob,
            save.raw_header,
            save.schema_identity,
            token,
            generation=8,
            operation_id="scoped-backup-race-test",
            loaded_blob=loaded_blob,
        )

    assert destination_hash_calls == 2
    assert copied_save.read_bytes() == replacement
    assert not list((copied_save.parent / "backups").glob("*.bak"))
    assert not list(copied_save.parent.glob(".save.save.*.tmp"))


def test_scoped_blackstar_rejects_loaded_blob_not_bound_to_preview(
    copied_save: Path,
) -> None:
    save = load_save_file(str(copied_save))
    loaded_blob = bytes(save.decompressed_blob)
    token = make_blackstar_apply_token(
        copied_save,
        loaded_blob,
        save.schema_identity,
        hashlib.sha256(loaded_blob).hexdigest(),
        generation=9,
        source_file_sha256=save.source_file_sha256,
    )

    with pytest.raises(BlackstarCompatibilityError, match="Source blob changed after preview"):
        transactional_write_blackstar(
            copied_save,
            loaded_blob,
            save.raw_header,
            save.schema_identity,
            token,
            generation=9,
            operation_id="scoped-loaded-blob-binding-test",
            loaded_blob=loaded_blob + b"tampered",
        )

    assert not (copied_save.parent / "backups").exists()

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
    early_114_save_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
        source_file_sha256=save.source_file_sha256,
    )
    original_load = save_crypto.load_save_file
    write_boundary_reloads = []

    def record_write_boundary_reload(path, *args, **kwargs):
        reloaded = original_load(path, *args, **kwargs)
        write_boundary_reloads.append((Path(path), kwargs.get("detect_schema")))
        return reloaded

    def fail_write_boundary_context(*_args, **_kwargs):
        pytest.fail("scoped write must reuse preview-bound hashes")

    monkeypatch.setattr(
        save_crypto, "load_save_file", record_write_boundary_reload
    )
    monkeypatch.setattr(
        parc_inserter3, "build_insert_context", fail_write_boundary_context
    )
    result = transactional_write_blackstar(
        destination, applied.output_blob, save.raw_header, save.schema_identity,
        token, generation=3, operation_id="scoped-write",
        loaded_blob=bytes(save.decompressed_blob),
    )
    assert result.backup_path.exists()
    assert len(write_boundary_reloads) == 1
    assert write_boundary_reloads[0][0].suffix == ".tmp"
    assert write_boundary_reloads[0][1] is False
    reloaded = load_save_file(str(destination))
    assert hashlib.sha256(reloaded.decompressed_blob).hexdigest() == preview.candidate_sha256
