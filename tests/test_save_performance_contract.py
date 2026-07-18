from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import asdict
from pathlib import Path

import pytest

import parc_serializer
import save_parser
from save_compat import (
    REQUIRED_TYPES,
    SaveSchemaIdentity,
    compute_schema_identity,
    extract_required_list_encodings,
)
from save_crypto import load_save_file


FIXTURES = Path(__file__).resolve().parent / "fixtures"
IDENTITY_OBJECT_CLASSES = {"MercenaryClanSaveData", "KnowledgeSaveData"}


def _legacy_type_signature(type_def: parc_serializer.TypeDef) -> str:
    payload = [
        [field.name, field.type_name, field.meta_kind, field.meta_size, field.meta_aux]
        for field in type_def.fields
    ]
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()


def _legacy_schema_identity(blob: bytes, raw_header: bytes) -> SaveSchemaIdentity:
    parc = parc_serializer.parse_parc_blob(blob)
    result = save_parser.build_result_from_raw(blob, {"input_kind": "raw_blob"})
    by_name = {type_def.name: type_def for type_def in parc.types}
    signatures = {
        name: _legacy_type_signature(by_name[name]) if name in by_name else "MISSING"
        for name in REQUIRED_TYPES
    }
    version = struct.unpack_from("<H", raw_header, 4)[0] if len(raw_header) >= 6 else 0
    return SaveSchemaIdentity(
        container_version=version,
        schema_sha256=hashlib.sha256(parc.schema_bytes).hexdigest(),
        root_entry_count=parc.num_root_entries,
        type_count=len(parc.types),
        required_type_signatures=signatures,
        observed_encodings=extract_required_list_encodings(result),
    )


SAVE_FIXTURES = tuple(sorted(FIXTURES.glob("**/save.save")))


def test_schema_identity_decodes_only_required_root_objects(
    copied_save: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save = load_save_file(str(copied_save))
    decoded_entry_classes: list[tuple[str, ...]] = []
    original_decode = save_parser.decode_object_blocks

    def record_decoded_entries(raw, toc_entries, types):
        decoded_entry_classes.append(tuple(entry.class_name for entry in toc_entries))
        return original_decode(raw, toc_entries, types)

    monkeypatch.setattr(save_parser, "decode_object_blocks", record_decoded_entries)

    compute_schema_identity(bytes(save.decompressed_blob), save.raw_header)

    assert decoded_entry_classes
    assert set().union(*map(set, decoded_entry_classes)) == IDENTITY_OBJECT_CLASSES
    assert all(
        class_name in IDENTITY_OBJECT_CLASSES
        for decoded_batch in decoded_entry_classes
        for class_name in decoded_batch
    )


@pytest.mark.parametrize(
    "fixture_path",
    SAVE_FIXTURES,
    ids=lambda path: path.relative_to(FIXTURES).as_posix(),
)
def test_schema_identity_matches_legacy_two_parser_reference(
    fixture_path: Path,
) -> None:
    save = load_save_file(str(fixture_path))
    blob = bytes(save.decompressed_blob)

    actual = compute_schema_identity(blob, save.raw_header)
    legacy = _legacy_schema_identity(blob, save.raw_header)

    assert asdict(actual) == asdict(legacy)
