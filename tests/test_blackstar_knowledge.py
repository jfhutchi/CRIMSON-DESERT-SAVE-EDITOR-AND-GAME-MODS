from __future__ import annotations

import struct

import pytest

from blackstar_knowledge import (
    CALL_DRAGON_KNOWLEDGE_KEY,
    CallDragonKnowledgeError,
    inspect_call_dragon,
    insert_call_dragon,
    select_call_dragon_template,
)
from parc_inserter3 import build_insert_context, insert_knowledge_keys_with_context
from save_crypto import load_save_file


def _context(path):
    save = load_save_file(str(path))
    return build_insert_context(bytes(save.decompressed_blob))


def _knowledge_parts(context):
    root = next(
        obj
        for obj in context.result["objects"]
        if obj.class_name == "KnowledgeSaveData"
    )
    entries = next(field for field in root.fields if field.name == "_list")
    return root, entries


def _fields(element):
    return {
        field.name: field
        for field in element.child_fields or []
        if field.present
    }


def _key(context, element):
    field = _fields(element)["_key"]
    return struct.unpack_from("<I", context.raw, field.start_offset)[0]


def test_context_inserter_uses_requested_target_local_template(
    early_114_save_path,
) -> None:
    context = _context(early_114_save_path)
    _root, entries = _knowledge_parts(context)
    template = next(
        element
        for element in reversed(entries.list_elements)
        if set(_fields(element))
        == {"_key", "_level", "_learnedFieldTime", "_isNewMark"}
    )

    candidate, _metrics = insert_knowledge_keys_with_context(
        context,
        [1000175],
        override_level=1,
        template_element=template,
    )
    after = build_insert_context(candidate)
    _root_after, entries_after = _knowledge_parts(after)
    inserted = [
        element
        for element in entries_after.list_elements
        if _key(after, element) == 1000175
    ]

    assert len(inserted) == 1
    assert inserted[0].end_offset - inserted[0].start_offset == 43
    assert set(_fields(inserted[0])) == {
        "_key",
        "_level",
        "_learnedFieldTime",
        "_isNewMark",
    }


def test_context_inserter_rejects_template_outside_target_list(
    early_114_save_path,
) -> None:
    context = _context(early_114_save_path)
    foreign = type("ForeignElement", (), {"start_offset": 1, "end_offset": 2})()
    with pytest.raises(ValueError, match="target knowledge list"):
        insert_knowledge_keys_with_context(
            context,
            [1000175],
            override_level=1,
            template_element=foreign,
        )


def test_reference_evidence_isolated_to_call_dragon(
    early_114_save_path,
    legit_idle_114_save_path,
    legit_active_114_save_path,
) -> None:
    assert inspect_call_dragon(_context(early_114_save_path)).status == "missing"
    for path in (legit_idle_114_save_path, legit_active_114_save_path):
        state = inspect_call_dragon(_context(path))
        assert state.status == "present"
        assert state.count == 1
        assert state.level == 1


def test_call_dragon_insert_has_legitimate_target_local_shape(
    early_114_save_path,
) -> None:
    context = _context(early_114_save_path)
    before_count = len(_knowledge_parts(context)[1].list_elements)
    candidate, metrics = insert_call_dragon(context)
    after = build_insert_context(candidate)
    state = inspect_call_dragon(after)
    _root, entries = _knowledge_parts(after)
    inserted = [
        element
        for element in entries.list_elements
        if _key(after, element) == CALL_DRAGON_KNOWLEDGE_KEY
    ]

    assert state.status == "present"
    assert state.level == 1
    assert len(entries.list_elements) == before_count + 1
    assert len(inserted) == 1
    assert inserted[0].end_offset - inserted[0].start_offset == 43
    assert _fields(inserted[0])["_isNewMark"].value_repr == "true"
    assert metrics.block_sizes == 1
    assert metrics.stream_sizes == 1


def test_call_dragon_insert_is_idempotent(early_114_save_path) -> None:
    context = _context(early_114_save_path)
    first, _metrics = insert_call_dragon(context)
    second, second_metrics = insert_call_dragon(build_insert_context(first))
    assert second == first
    assert second_metrics.pointer_offsets == 0


def test_duplicate_call_dragon_entries_are_refused(early_114_save_path) -> None:
    context = _context(early_114_save_path)
    first, _metrics = insert_call_dragon(context)
    first_context = build_insert_context(first)
    duplicate, _duplicate_metrics = insert_knowledge_keys_with_context(
        first_context,
        [CALL_DRAGON_KNOWLEDGE_KEY],
        override_level=1,
        template_element=select_call_dragon_template(first_context),
    )
    with pytest.raises(CallDragonKnowledgeError, match="Duplicate"):
        inspect_call_dragon(build_insert_context(duplicate))


def test_malformed_call_dragon_level_is_refused(early_114_save_path) -> None:
    context = _context(early_114_save_path)
    first, _metrics = insert_call_dragon(context)
    parsed = build_insert_context(first)
    _root, entries = _knowledge_parts(parsed)
    target = next(
        element
        for element in entries.list_elements
        if _key(parsed, element) == CALL_DRAGON_KNOWLEDGE_KEY
    )
    level = _fields(target)["_level"]
    malformed = bytearray(first)
    malformed[level.start_offset : level.end_offset] = b"\x00\x00\x00\x00"
    with pytest.raises(CallDragonKnowledgeError, match="below 1"):
        inspect_call_dragon(build_insert_context(malformed))


def test_template_selection_requires_exact_fields_and_widths(
    early_114_save_path,
) -> None:
    context = _context(early_114_save_path)
    template = select_call_dragon_template(context)
    fields = _fields(template)
    assert set(fields) == {
        "_key",
        "_level",
        "_learnedFieldTime",
        "_isNewMark",
    }
    assert {
        name: field.end_offset - field.start_offset
        for name, field in fields.items()
    } == {
        "_key": 4,
        "_level": 4,
        "_learnedFieldTime": 8,
        "_isNewMark": 1,
    }
