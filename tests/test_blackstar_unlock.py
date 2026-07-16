from __future__ import annotations

import hashlib
import struct

from blackstar_unlock import canonical_root_snapshot, unlock_blackstar
from parc_inserter3 import build_insert_context
from save_crypto import load_save_file


def _load(path):
    save = load_save_file(str(path))
    return save, bytes(save.decompressed_blob)


def _blackstar_elements(blob: bytes):
    context = build_insert_context(blob)
    clan = next(o for o in context.result["objects"] if o.class_name == "MercenaryClanSaveData")
    mounts = next(f for f in clan.fields if f.name == "_mercenaryDataList")
    found = []
    for element in mounts.list_elements:
        fields = {f.name: f for f in element.child_fields or []}
        key = fields.get("_characterKey")
        if key and struct.unpack_from("<I", blob, key.start_offset)[0] == 1000799:
            found.append((element, fields))
    return context, found


def test_early_dry_run_plans_legitimate_idle_record_without_mutation(early_114_save_path) -> None:
    save, blob = _load(early_114_save_path)
    before = hashlib.sha256(blob).hexdigest()
    result = unlock_blackstar(blob, save.schema_identity, True, "early-preview")
    assert result.output_blob is None
    assert hashlib.sha256(blob).hexdigest() == before
    assert result.report.classification_before == "absent"
    assert result.report.action == "insert"
    assert (result.report.mercenary_no, result.report.item_no) == (1000003, 1000004)
    assert result.report.quest_changes == 0
    assert result.report.knowledge_changes == 0


def test_apply_inserts_one_legitimate_record_and_is_idempotent(early_114_save_path) -> None:
    save, blob = _load(early_114_save_path)
    quest_before = canonical_root_snapshot(build_insert_context(blob), "QuestSaveData")
    knowledge_before = canonical_root_snapshot(build_insert_context(blob), "KnowledgeSaveData")
    first = unlock_blackstar(blob, save.schema_identity, False, "early-apply")
    assert first.output_blob is not None
    context, found = _blackstar_elements(first.output_blob)
    assert len(found) == 1
    element, fields = found[0]
    assert element.end_offset - element.start_offset == 437
    assert fields["_ownedCharacterKey"].value_repr == "1"
    equipment = fields["_equipItemList"].list_elements
    assert len(equipment) == 1
    item_fields = {f.name: f for f in equipment[0].child_fields or []}
    assert item_fields["_itemKey"].value_repr == "1002269"
    assert canonical_root_snapshot(context, "QuestSaveData") == quest_before
    assert canonical_root_snapshot(context, "KnowledgeSaveData") == knowledge_before
    second = unlock_blackstar(first.output_blob, save.schema_identity, False, "second")
    assert second.output_blob == first.output_blob
    assert second.report.action == "none"


def test_legitimate_reference_states_are_no_change(
    legit_idle_114_save_path, legit_active_114_save_path
) -> None:
    for path, expected in ((legit_idle_114_save_path, "legitimate_idle"),
                           (legit_active_114_save_path, "legitimate_active")):
        save, blob = _load(path)
        result = unlock_blackstar(blob, save.schema_identity, False, str(path))
        assert result.output_blob == blob
        assert result.report.classification_before == expected
        assert result.report.action == "none"


def test_failed_legacy_record_is_replaced_not_duplicated(legacy_failed_save_path) -> None:
    save, blob = _load(legacy_failed_save_path)
    before_context, before = _blackstar_elements(blob)
    assert len(before) == 1
    assert before[0][0].end_offset - before[0][0].start_offset == 206
    result = unlock_blackstar(blob, save.schema_identity, False, "legacy-repair")
    assert result.report.classification_before == "legacy"
    assert result.report.action == "replace"
    after_context, after = _blackstar_elements(result.output_blob)
    assert len(after) == 1
    assert after[0][0].end_offset - after[0][0].start_offset == 437
    assert len(_mount_rows_for_test(before_context)) == len(_mount_rows_for_test(after_context))


def _mount_rows_for_test(context):
    clan = next(o for o in context.result["objects"] if o.class_name == "MercenaryClanSaveData")
    return next(f for f in clan.fields if f.name == "_mercenaryDataList").list_elements
