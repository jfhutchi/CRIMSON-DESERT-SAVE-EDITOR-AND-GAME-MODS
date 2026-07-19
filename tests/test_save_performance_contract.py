from __future__ import annotations

import hashlib
import json
import struct
import sys
from dataclasses import asdict
from pathlib import Path
from typing import get_args, get_type_hints

import pytest

import parc_serializer
import save_parser
from save_compat import (
    REQUIRED_TYPES,
    SaveSchemaIdentity,
    _type_signature,
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


def test_type_signature_accepts_both_parser_type_definitions() -> None:
    type_def_hint = get_type_hints(_type_signature)["type_def"]

    assert set(get_args(type_def_hint)) == {
        parc_serializer.TypeDef,
        save_parser.TypeDef,
    }


def test_schema_identity_parses_once_and_decodes_only_required_root_objects(
    copied_save: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save = load_save_file(str(copied_save))
    call_counts = {"parse_schema": 0, "parse_toc": 0, "decode_object_blocks": 0}
    decoded_entry_classes: list[tuple[str, ...]] = []
    original_parse_schema = save_parser.parse_schema
    original_parse_toc = save_parser.parse_toc
    original_decode = save_parser.decode_object_blocks

    def count_parse_schema(raw):
        call_counts["parse_schema"] += 1
        return original_parse_schema(raw)

    def count_parse_toc(raw, schema_end, type_names):
        call_counts["parse_toc"] += 1
        return original_parse_toc(raw, schema_end, type_names)

    def record_decoded_entries(raw, toc_entries, types):
        call_counts["decode_object_blocks"] += 1
        decoded_entry_classes.append(tuple(entry.class_name for entry in toc_entries))
        return original_decode(raw, toc_entries, types)

    monkeypatch.setattr(save_parser, "parse_schema", count_parse_schema)
    monkeypatch.setattr(save_parser, "parse_toc", count_parse_toc)
    monkeypatch.setattr(save_parser, "decode_object_blocks", record_decoded_entries)

    compute_schema_identity(bytes(save.decompressed_blob), save.raw_header)

    assert call_counts == {
        "parse_schema": 1,
        "parse_toc": 1,
        "decode_object_blocks": 1,
    }
    assert decoded_entry_classes
    assert set().union(*map(set, decoded_entry_classes)) == IDENTITY_OBJECT_CLASSES
    assert all(
        class_name in IDENTITY_OBJECT_CLASSES
        for decoded_batch in decoded_entry_classes
        for class_name in decoded_batch
    )


def test_selective_layout_result_retains_full_toc(copied_save: Path) -> None:
    save = load_save_file(str(copied_save))
    raw = bytes(save.decompressed_blob)
    schema = save_parser.parse_schema(raw)
    type_names = [type_def.name for type_def in schema["types"]]
    toc = save_parser.parse_toc(raw, schema["schema_end"], type_names)

    result = save_parser.build_result_from_layout(
        raw,
        {"input_kind": "raw_blob"},
        schema,
        toc,
        object_class_names=IDENTITY_OBJECT_CLASSES,
    )

    assert result["toc"]["entries"] == toc["entries"]
    assert result["toc"]["entry_count"] == toc["toc_count"]
    assert len(result["toc"]["entries"]) > len(result["objects"])
    assert {obj.class_name for obj in result["objects"]} == IDENTITY_OBJECT_CLASSES


def test_insert_context_reuses_parc_layout_without_schema_or_toc_reparse(
    copied_save: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from CrimsonSaveEditor import parc_inserter3 as editor_inserter
    from CrimsonSaveEditor import parc_serializer as editor_parc_serializer
    from CrimsonSaveEditor import save_parser as editor_save_parser

    save = load_save_file(str(copied_save))
    raw = bytes(save.decompressed_blob)
    call_counts = {"parse_parc_blob": 0, "parse_schema": 0, "parse_toc": 0}
    original_parse_parc = editor_parc_serializer.parse_parc_blob
    original_parse_schema = editor_save_parser.parse_schema
    original_parse_toc = editor_save_parser.parse_toc

    def count_parse_parc(blob):
        call_counts["parse_parc_blob"] += 1
        return original_parse_parc(blob)

    def count_parse_schema(blob):
        call_counts["parse_schema"] += 1
        return original_parse_schema(blob)

    def count_parse_toc(blob, schema_end, type_names):
        call_counts["parse_toc"] += 1
        return original_parse_toc(blob, schema_end, type_names)

    monkeypatch.setitem(sys.modules, "parc_serializer", editor_parc_serializer)
    monkeypatch.setitem(sys.modules, "save_parser", editor_save_parser)
    monkeypatch.setattr(editor_parc_serializer, "parse_parc_blob", count_parse_parc)
    monkeypatch.setattr(editor_save_parser, "parse_schema", count_parse_schema)
    monkeypatch.setattr(editor_save_parser, "parse_toc", count_parse_toc)

    context = editor_inserter.build_insert_context(raw)

    assert context.raw == raw
    assert context.parc.raw == raw
    assert call_counts == {
        "parse_parc_blob": 1,
        "parse_schema": 0,
        "parse_toc": 0,
    }


def _schema_semantics(result: dict) -> tuple:
    schema = result["schema"]
    return (
        schema["header_tag"],
        schema["header_zero"],
        schema["type_count"],
        schema["root_type"],
        tuple(asdict(type_def) for type_def in schema["types"]),
    )


def _toc_semantics(result: dict) -> tuple:
    return tuple(
        (
            entry.index,
            entry.class_index,
            entry.class_name,
            entry.sentinel1,
            entry.sentinel2,
            entry.data_offset,
            entry.data_size,
            entry.entry_offset,
        )
        for entry in result["toc"]["entries"]
    )


def test_parc_layout_adapter_matches_raw_result_semantics(copied_save: Path) -> None:
    from CrimsonSaveEditor import parc_serializer as editor_parc_serializer
    from CrimsonSaveEditor import save_parser as editor_save_parser

    save = load_save_file(str(copied_save))
    raw = bytes(save.decompressed_blob)
    load_meta = {"input_kind": "raw_blob"}
    parc = editor_parc_serializer.parse_parc_blob(raw)

    expected = editor_save_parser.build_result_from_raw(
        raw,
        load_meta,
        include_legacy=True,
    )
    actual = editor_save_parser.build_result_from_parc(
        bytearray(raw),
        load_meta,
        parc,
        include_legacy=True,
    )

    assert actual["input"] == expected["input"]
    assert actual["raw"] == expected["raw"]
    assert _schema_semantics(actual) == _schema_semantics(expected)
    assert all(
        isinstance(type_def, editor_save_parser.TypeDef)
        and all(
            isinstance(field, editor_save_parser.FieldDef)
            for field in type_def.fields
        )
        for type_def in actual["schema"]["types"]
    )
    assert actual["toc"]["prefix_zero"] == expected["toc"]["prefix_zero"]
    assert actual["toc"]["entry_count"] == expected["toc"]["entry_count"]
    assert actual["toc"]["stream_size"] == expected["toc"]["stream_size"]
    assert _toc_semantics(actual) == _toc_semantics(expected)
    assert [asdict(obj) for obj in actual["objects"]] == [
        asdict(obj) for obj in expected["objects"]
    ]
    assert len(actual["toc"]["entries"]) == len(parc.toc_entries)
    for key in ("character", "items", "items_summary", "bagExpansion"):
        assert editor_save_parser.to_jsonable(actual[key]) == (
            editor_save_parser.to_jsonable(expected[key])
        )

    filtered = editor_save_parser.build_result_from_parc(
        bytearray(raw),
        load_meta,
        parc,
        object_class_names=IDENTITY_OBJECT_CLASSES,
    )
    assert [asdict(obj) for obj in filtered["objects"]] == [
        asdict(obj)
        for obj in expected["objects"]
        if obj.class_name in IDENTITY_OBJECT_CLASSES
    ]
    assert _toc_semantics(filtered) == _toc_semantics(expected)


def test_parc_layout_adapter_forwards_decode_options(
    copied_save: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from CrimsonSaveEditor import parc_serializer as editor_parc_serializer
    from CrimsonSaveEditor import save_parser as editor_save_parser

    save = load_save_file(str(copied_save))
    raw = bytes(save.decompressed_blob)
    parc = editor_parc_serializer.parse_parc_blob(raw)
    sentinel = object()
    captured: dict = {}

    def capture_layout(
        blob,
        load_meta,
        schema,
        toc,
        *,
        object_class_names=None,
        include_legacy=False,
    ):
        captured.update(
            raw=blob,
            load_meta=load_meta,
            schema=schema,
            toc=toc,
            object_class_names=object_class_names,
            include_legacy=include_legacy,
        )
        return sentinel

    monkeypatch.setattr(editor_save_parser, "build_result_from_layout", capture_layout)

    result = editor_save_parser.build_result_from_parc(
        raw,
        {"source": "contract"},
        parc,
        object_class_names=IDENTITY_OBJECT_CLASSES,
        include_legacy=True,
    )

    assert result is sentinel
    assert captured["raw"] == raw
    assert captured["load_meta"] == {"source": "contract"}
    assert captured["object_class_names"] == IDENTITY_OBJECT_CLASSES
    assert captured["include_legacy"] is True


def _synthetic_parc(editor_parc_serializer, *, types=(), toc_entries=()):
    raw = bytes(64)
    type_list = list(types)
    return raw, editor_parc_serializer.ParcBlob(
        raw=raw,
        header=raw[:14],
        schema_bytes=b"",
        schema_offset=14,
        schema_end=20,
        toc_header_bytes=bytes(12),
        toc_offset=20,
        types=type_list,
        type_by_index={type_def.index: type_def for type_def in type_list},
        toc_entries=list(toc_entries),
        data_start=32 + len(toc_entries) * 20,
        num_root_entries=0,
        stream_size=len(raw),
        block_raw={},
        modified_blocks={},
    )


def test_parc_layout_adapter_accepts_empty_types() -> None:
    from CrimsonSaveEditor import parc_serializer as editor_parc_serializer
    from CrimsonSaveEditor import save_parser as editor_save_parser

    raw, parc = _synthetic_parc(editor_parc_serializer)

    result = editor_save_parser.build_result_from_parc(raw, {}, parc)

    assert result["schema"]["root_type"] == ""
    assert result["schema"]["types"] == []
    assert result["toc"]["entries"] == []


def test_parc_layout_adapter_resolves_class_name_by_type_index() -> None:
    from CrimsonSaveEditor import parc_serializer as editor_parc_serializer
    from CrimsonSaveEditor import save_parser as editor_save_parser

    mapped_type = editor_parc_serializer.TypeDef(
        index=7,
        name="MappedType",
        fields=[],
    )
    toc_entry = editor_parc_serializer.TOCEntry(
        index=0,
        class_index=7,
        sentinel1=0,
        sentinel2=0,
        data_offset=52,
        data_size=0,
    )
    raw, parc = _synthetic_parc(
        editor_parc_serializer,
        types=[mapped_type],
        toc_entries=[toc_entry],
    )

    result = editor_save_parser.build_result_from_parc(
        raw,
        {},
        parc,
        object_class_names=set(),
    )

    assert result["toc"]["entries"][0].class_name == "MappedType"


def test_parc_layout_adapter_uses_concrete_parc_type_contract() -> None:
    from CrimsonSaveEditor import save_parser as editor_save_parser

    assert editor_save_parser.build_result_from_parc.__annotations__["parc"] == (
        "ParcBlob"
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
