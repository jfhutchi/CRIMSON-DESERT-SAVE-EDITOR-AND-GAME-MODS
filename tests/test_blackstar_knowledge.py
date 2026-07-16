from __future__ import annotations

import struct

import pytest

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
