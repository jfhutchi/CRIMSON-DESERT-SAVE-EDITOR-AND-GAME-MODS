from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import struct
import tempfile
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from app_logging import phase
from parc_inserter3 import (
    FixupMetrics,
    ParsedInsertContext,
    _fixup_external,
    _fixup_trailing_sizes,
    build_insert_context,
    insert_knowledge_keys_with_context,
    iter_sentinels,
)
from save_compat import CompatibilityProfile

log = logging.getLogger(__name__)

BLACKSTAR_CHARACTER_KEY = 1000799
BLACKSTAR_MOUNT_TEMPLATE = bytes.fromhex(
    "06000519801f0003380000ffffffffffffffff"
    "591e1200000000005f450f00f90300000000000001"
    "001c3a0000ffffffffffffffff7b1e120000000000"
    "0100002e0000ffffffffffffffff911e12000000000004000000"
    "0100002e0000ffffffffffffffffab1e12000000000004000000"
    "0100002e0000ffffffffffffffffc51e12000000000004000000"
    "520000001cdd8dc3000000001cdd8dc30000000001eb7b45c6"
    "90098144e2862dc59e9c673f0100000001010101010101"
    "c40900000000000000000000000000b4000000"
)
BLACKSTAR_KNOWLEDGE_KEYS = (
    40038, 1000174, 1000175, 1000187, 1000189, 1000697, 1000720,
    1000948, 1001892, 1003893, 1004138, 1004154, 1004176, 1004177,
    1004178, 2147483119, 2147483121, 2147483122, 2147483123,
    2147483124, 2147483125, 2147483126, 2147483127, 2147483128,
    2147483130, 2147483131, 2147483132, 2147483133, 2147483134,
    2147483135, 2601, 2602, 2603, 2617, 2618, 1000560, 1001083, 1003311,
    40001, 40002, 40003, 40012, 40013, 40014, 40018, 40024, 40028,
    40030, 40034, 40036, 40039, 40048, 40063, 40064, 40065, 40068,
    40069, 40071, 40072, 40082, 40086, 40089, 40090, 40091, 40114,
    1000000, 1000001, 1000013, 1000014, 1000024, 1000034, 1000037,
    1000100, 1000101, 1000109, 1000134, 1000137, 1000138, 1000210,
    1000230, 1000490, 1000493, 1000908, 1000929, 1001116, 1001117,
    1001710, 1001744, 1001756, 1001760, 1001789, 1002348, 1002349,
    1002351, 1002352, 1002710, 1002741, 1002743, 1003088, 1003090,
    1003108, 1003245, 1003269, 1003273, 1003274, 1003279, 1003346,
    1003359, 1003482, 1003505, 1003508, 1003512, 1003513, 1003518,
    1003519, 1003521, 1003522, 1003523, 1003524, 1003525, 1003571,
    1000372, 1000375, 1000738, 1001290, 1001297, 1001298, 1001434,
    1001435, 1001436, 1001453, 1001463, 1001464, 1001465, 1001541,
    1001542, 1001550, 1001553, 1001704, 1002592, 1003325, 1003334,
    1003341, 1003467, 1003468, 1003470, 1003472, 1003473, 1003474,
    1003475, 1003476, 1003477, 1003480, 1003481, 1003492, 1003494,
    1003495, 1003500, 1003501, 1003502, 1003503, 1003504, 1003507,
    1003510, 1000070, 1000574, 1001100, 1001422, 1000297, 1000464,
    1000776, 1001287, 1001511, 1001516, 2147483447, 2147483454,
    1001304, 1001664, 1001692, 1001695, 1001700, 1001895, 1001897,
    1001651, 1002833, 1003658, 1003790,
)

_SOURCE_TYPE_INDICES = {
    56: "MercenarySaveData",
    58: "ExperienceLevelSaveData",
    46: "FriendlyDailyCountSaveData",
}
_TARGET_PATTERN = re.compile(r"\s*target=0x[0-9A-Fa-f]+")
_MOUNT_TEMPLATE_FIELDS = (
    "_characterKey",
    "_mercenaryNo",
    "_levelData",
    "_lastPaidTime",
    "_lastBreedingTime",
    "_spawnPosition",
    "_spawnYaw",
    "_spawnFieldInfoKey",
    "_isInitialize",
    "_occupationState",
    "_currentHp",
    "_currentMp",
)


@dataclass(frozen=True)
class BlackstarProgress:
    phase: str
    completed: int
    total: int
    message: str


@dataclass(frozen=True)
class BlackstarChangeReport:
    mount_before: int
    mount_after: int
    knowledge_added: tuple[int, ...]
    knowledge_skipped: tuple[int, ...]
    duplicate_mounts: int
    duplicate_knowledge: tuple[int, ...]
    byte_growth: int
    quest_changes: int
    fixups: FixupMetrics
    timings_ms: dict[str, float]


@dataclass(frozen=True)
class BlackstarResult:
    input_sha256: str
    candidate_sha256: str
    output_blob: bytes | None
    profile_id: str
    report: BlackstarChangeReport


class BlackstarValidationError(ValueError):
    pass


class BlackstarCancelledError(RuntimeError):
    pass


@dataclass(frozen=True)
class BlackstarSpec:
    character_key: int
    mount_template: bytes
    knowledge_keys: tuple[int, ...]


BLACKSTAR_SPEC = BlackstarSpec(
    character_key=BLACKSTAR_CHARACTER_KEY,
    mount_template=BLACKSTAR_MOUNT_TEMPLATE,
    knowledge_keys=BLACKSTAR_KNOWLEDGE_KEYS,
)


@dataclass(frozen=True)
class BlackstarPlan:
    mount_count: int
    mount_insert_offset: int
    mount_list_start: int
    mount_toc_index: int
    mount_block_end: int
    mount_template_mask_hex: str
    mount_object: object = field(repr=False, compare=False)
    mount_field: object = field(repr=False, compare=False)
    knowledge_counts: tuple[tuple[int, int], ...]
    knowledge_missing: tuple[int, ...]
    knowledge_existing: tuple[int, ...]
    duplicate_knowledge: tuple[int, ...]


@dataclass(frozen=True)
class AppliedBlackstarPlan:
    output_blob: bytes
    fixups: FixupMetrics
    timings_ms: dict[str, float]


def _find_list(context: ParsedInsertContext, class_name: str, field_name: str):
    for obj in context.result["objects"]:
        if obj.class_name != class_name:
            continue
        for list_field in obj.fields:
            if list_field.name == field_name and list_field.list_elements:
                return obj, list_field
    raise BlackstarValidationError(f"{class_name}.{field_name} is missing or empty")


def _element_key(raw: bytes, element, field_name: str) -> int | None:
    for child in element.child_fields or []:
        if child.name == field_name and child.present:
            return struct.unpack_from("<I", raw, child.start_offset)[0]
    return None


def _validate_profile_encoding(
    list_field,
    expected_prefix: int,
    expected_mask: str,
    label: str,
) -> None:
    if list_field.list_prefix_u8 != expected_prefix:
        raise BlackstarValidationError(
            f"{label} prefix {list_field.list_prefix_u8} does not match profile "
            f"prefix {expected_prefix}"
        )
    observed_masks = {
        element.child_mask_bytes.hex()
        for element in list_field.list_elements or []
        if element.child_mask_bytes
    }
    if expected_mask not in observed_masks:
        raise BlackstarValidationError(
            f"{label} mask {expected_mask} is not present in this save"
        )


def build_blackstar_plan(
    context: ParsedInsertContext,
    profile: CompatibilityProfile,
    spec: BlackstarSpec = BLACKSTAR_SPEC,
) -> BlackstarPlan:
    if len(spec.knowledge_keys) != len(set(spec.knowledge_keys)):
        raise BlackstarValidationError("Blackstar specification contains duplicate knowledge keys")
    mount_obj, mount_field = _find_list(
        context, "MercenaryClanSaveData", "_mercenaryDataList"
    )
    knowledge_obj, knowledge_field = _find_list(context, "KnowledgeSaveData", "_list")
    _validate_profile_encoding(
        mount_field,
        profile.mount_list_prefix,
        profile.mount_element_mask_hex,
        "MercenaryClanSaveData._mercenaryDataList",
    )
    _validate_profile_encoding(
        knowledge_field,
        profile.knowledge_list_prefix,
        profile.knowledge_element_mask_hex,
        "KnowledgeSaveData._list",
    )

    mount_count = sum(
        _element_key(context.raw, element, "_characterKey") == spec.character_key
        for element in mount_field.list_elements
    )
    if mount_count > 1:
        raise BlackstarValidationError(
            f"Expected at most one Blackstar mount; found {mount_count} Blackstar mounts"
        )
    knowledge_counter = Counter(
        key
        for element in knowledge_field.list_elements
        if (key := _element_key(context.raw, element, "_key")) is not None
    )
    duplicates = tuple(
        key for key in spec.knowledge_keys if knowledge_counter[key] > 1
    )
    if duplicates:
        raise BlackstarValidationError(
            f"Duplicate requested knowledge entries detected: {duplicates}"
        )
    missing = tuple(key for key in spec.knowledge_keys if knowledge_counter[key] == 0)
    existing = tuple(key for key in spec.knowledge_keys if knowledge_counter[key] == 1)
    toc_index = next(
        (
            entry.index
            for entry in context.parc.toc_entries
            if context.parc.type_by_index.get(entry.class_index)
            and context.parc.type_by_index[entry.class_index].name
            == "MercenaryClanSaveData"
        ),
        None,
    )
    if toc_index is None:
        raise BlackstarValidationError("MercenaryClanSaveData TOC entry is missing")
    compatible_template = next(
        (
            element
            for element in mount_field.list_elements
            if element.end_offset - element.start_offset == len(spec.mount_template)
            and tuple(
                child.name
                for child in element.child_fields or []
                if child.present
            )
            == _MOUNT_TEMPLATE_FIELDS
        ),
        None,
    )
    if compatible_template is None:
        raise BlackstarValidationError(
            "No schema-compatible 206-byte mercenary template encoding was found"
        )
    return BlackstarPlan(
        mount_count=mount_count,
        mount_insert_offset=mount_field.list_elements[-1].end_offset,
        mount_list_start=mount_field.start_offset,
        mount_toc_index=toc_index,
        mount_block_end=mount_obj.data_offset + mount_obj.data_size,
        mount_template_mask_hex=compatible_template.child_mask_bytes.hex(),
        mount_object=mount_obj,
        mount_field=mount_field,
        knowledge_counts=tuple(
            (key, knowledge_counter[key]) for key in spec.knowledge_keys
        ),
        knowledge_missing=missing,
        knowledge_existing=existing,
        duplicate_knowledge=duplicates,
    )


def _set_list_count(blob: bytearray, offset: int, prefix: int, count: int) -> None:
    if prefix == 1:
        if count > 0xFFFF:
            raise BlackstarValidationError("Mount list count exceeds 16-bit encoding")
        blob[offset + 1] = (count >> 8) & 0xFF
        blob[offset + 2] = count & 0xFF
    elif prefix == 0:
        if count > 0xFFFFFF:
            raise BlackstarValidationError("List count exceeds 24-bit encoding")
        blob[offset + 1] = count & 0xFF
        blob[offset + 2] = (count >> 8) & 0xFF
        blob[offset + 3] = (count >> 16) & 0xFF
    else:
        raise BlackstarValidationError(f"Unsupported list prefix {prefix}")


def _insert_mount(
    context: ParsedInsertContext,
    profile: CompatibilityProfile,
    spec: BlackstarSpec,
    plan: BlackstarPlan,
) -> tuple[bytes, FixupMetrics]:
    name_to_index = {item.name: item.index for item in context.parc.types}
    missing_types = [
        name for name in _SOURCE_TYPE_INDICES.values() if name not in name_to_index
    ]
    if missing_types:
        raise BlackstarValidationError(
            f"Required mount schema types are missing: {', '.join(missing_types)}"
        )
    mount = bytearray(spec.mount_template)
    mask_byte_count = struct.unpack_from("<H", mount, 0)[0]
    translated_mask = bytes.fromhex(plan.mount_template_mask_hex)
    if len(translated_mask) != mask_byte_count:
        raise BlackstarValidationError(
            "Schema-compatible mount mask width differs from the Blackstar template"
        )
    mount[2:2 + mask_byte_count] = translated_mask
    top_type_offset = 2 + mask_byte_count
    source_type = struct.unpack_from("<H", mount, top_type_offset)[0]
    source_name = _SOURCE_TYPE_INDICES.get(source_type)
    if source_name is None:
        raise BlackstarValidationError(f"Unknown mount template type index {source_type}")
    struct.pack_into("<H", mount, top_type_offset, name_to_index[source_name])
    locator_end = 2 + mask_byte_count + 2 + 1 + 8 + 4
    struct.pack_into("<I", mount, len(mount) - 4, len(mount) - 4 - locator_end)
    for sentinel_pos in iter_sentinels(mount, 23, len(mount) - 4):
        if sentinel_pos < 3:
            continue
        nested_type = struct.unpack_from("<H", mount, sentinel_pos - 3)[0]
        nested_name = _SOURCE_TYPE_INDICES.get(nested_type)
        if nested_name:
            struct.pack_into("<H", mount, sentinel_pos - 3, name_to_index[nested_name])
    for sentinel_pos in iter_sentinels(mount, 0, len(mount) - 4):
        po_offset = sentinel_pos + 8
        if po_offset + 4 <= len(mount):
            struct.pack_into(
                "<I",
                mount,
                po_offset,
                plan.mount_insert_offset + po_offset + 4,
            )

    blob = bytearray(context.raw)
    blob[plan.mount_insert_offset:plan.mount_insert_offset] = mount
    growth = len(mount)
    trailing_count = _fixup_trailing_sizes(
        blob,
        context.raw,
        plan.mount_insert_offset,
        growth,
        "MercenaryClanSaveData",
        result=context.result,
    )
    _set_list_count(
        blob,
        plan.mount_list_start,
        profile.mount_list_prefix,
        len(plan.mount_field.list_elements) + 1,
    )
    pointer_count = _fixup_external(
        blob,
        context.raw,
        context.parc,
        plan.mount_toc_index,
        plan.mount_insert_offset,
        growth,
    )
    toc_count = sum(
        1
        for entry in context.parc.toc_entries
        if entry.data_offset >= plan.mount_block_end
    )
    return bytes(blob), FixupMetrics(
        pointer_offsets=pointer_count,
        trailing_sizes=trailing_count,
        toc_offsets=toc_count,
        block_sizes=1,
        stream_sizes=1,
    )


def apply_blackstar_plan(
    context: ParsedInsertContext,
    profile: CompatibilityProfile,
    spec: BlackstarSpec,
    plan: BlackstarPlan,
) -> AppliedBlackstarPlan:
    blob = context.raw
    metrics = FixupMetrics()
    timings: dict[str, float] = {}
    knowledge_context = context
    if plan.mount_count == 0:
        started = time.perf_counter()
        blob, mount_metrics = _insert_mount(context, profile, spec, plan)
        metrics += mount_metrics
        timings["mount_insertion"] = (time.perf_counter() - started) * 1000
        if plan.knowledge_missing:
            started = time.perf_counter()
            knowledge_context = build_insert_context(blob)
            timings["mount_reparse"] = (time.perf_counter() - started) * 1000
    if plan.knowledge_missing:
        started = time.perf_counter()
        blob, knowledge_metrics = insert_knowledge_keys_with_context(
            knowledge_context, plan.knowledge_missing
        )
        metrics += knowledge_metrics
        timings["knowledge_insertion"] = (time.perf_counter() - started) * 1000
    return AppliedBlackstarPlan(blob, metrics, timings)


def _canonical_field(value) -> tuple:
    semantic = _TARGET_PATTERN.sub("", str(getattr(value, "value_repr", "")))
    return (
        getattr(value, "field_index", -1),
        getattr(value, "name", ""),
        getattr(value, "type_name", ""),
        bool(getattr(value, "present", False)),
        semantic,
        bytes(getattr(value, "child_mask_bytes", b"")).hex(),
        tuple(_canonical_field(child) for child in (value.child_fields or [])),
        tuple(_canonical_field(child) for child in (value.list_elements or [])),
    )


def canonical_quest_snapshot(context: ParsedInsertContext) -> tuple:
    for obj in context.result["objects"]:
        if obj.class_name == "QuestSaveData":
            return tuple(_canonical_field(item) for item in obj.fields)
    raise BlackstarValidationError("QuestSaveData is missing")


def _emit(
    callback: Callable[[BlackstarProgress], None] | None,
    phase_name: str,
    completed: int,
    message: str,
) -> None:
    if callback:
        callback(BlackstarProgress(phase_name, completed, 6, message))


def _check_cancelled(callback: Callable[[], bool] | None) -> None:
    if callback and callback():
        raise BlackstarCancelledError("Blackstar operation cancelled")


def unlock_blackstar(
    blob: bytes | bytearray,
    profile: CompatibilityProfile,
    dry_run: bool,
    operation_id: str,
    progress: Callable[[BlackstarProgress], None] | None = None,
    spec: BlackstarSpec = BLACKSTAR_SPEC,
    cancelled: Callable[[], bool] | None = None,
) -> BlackstarResult:
    original = bytes(blob)
    input_hash = hashlib.sha256(original).hexdigest()
    timings: dict[str, float] = {}
    started = time.perf_counter()
    with phase(log, operation_id, "blackstar_parse", bytes=len(original)):
        context = build_insert_context(original)
    timings["parse"] = (time.perf_counter() - started) * 1000
    _emit(progress, "parse", 1, "Parsed save structures")
    _check_cancelled(cancelled)

    started = time.perf_counter()
    with phase(log, operation_id, "blackstar_detection"):
        plan = build_blackstar_plan(context, profile, spec)
        quest_before = canonical_quest_snapshot(context)
    timings["detection"] = (time.perf_counter() - started) * 1000
    _emit(progress, "detection", 2, "Detected mount and knowledge state")
    _check_cancelled(cancelled)

    if plan.mount_count == 1 and not plan.knowledge_missing:
        report = BlackstarChangeReport(
            mount_before=1,
            mount_after=1,
            knowledge_added=(),
            knowledge_skipped=plan.knowledge_existing,
            duplicate_mounts=0,
            duplicate_knowledge=(),
            byte_growth=0,
            quest_changes=0,
            fixups=FixupMetrics(),
            timings_ms=timings,
        )
        _emit(progress, "mount", 3, "Blackstar mount already present")
        _emit(progress, "knowledge", 4, "Requested knowledge already present")
        _emit(progress, "validation", 5, "No changes required")
        _emit(progress, "complete", 6, "Blackstar unlock is already complete")
        return BlackstarResult(
            input_hash,
            input_hash,
            None if dry_run else original,
            profile.profile_id,
            report,
        )

    with phase(
        log,
        operation_id,
        "blackstar_mount_insertion",
        needed=plan.mount_count == 0,
    ):
        applied = apply_blackstar_plan(context, profile, spec, plan)
    timings.update(applied.timings_ms)
    _check_cancelled(cancelled)
    _emit(
        progress,
        "mount",
        3,
        "Inserted Blackstar mount" if plan.mount_count == 0 else "Blackstar mount present",
    )
    _emit(
        progress,
        "knowledge",
        4,
        f"Inserted {len(plan.knowledge_missing)} knowledge entries",
    )
    _check_cancelled(cancelled)

    started = time.perf_counter()
    with phase(log, operation_id, "blackstar_validation"):
        candidate_context = build_insert_context(applied.output_blob)
        candidate_plan = build_blackstar_plan(candidate_context, profile, spec)
        quest_after = canonical_quest_snapshot(candidate_context)
        if candidate_plan.mount_count != 1:
            raise BlackstarValidationError(
                f"Expected one Blackstar mount, found {candidate_plan.mount_count}"
            )
        if candidate_plan.duplicate_knowledge:
            raise BlackstarValidationError("Duplicate requested knowledge entries detected")
        if candidate_plan.knowledge_missing:
            raise BlackstarValidationError("Requested knowledge entries are still missing")
        if quest_before != quest_after:
            raise BlackstarValidationError("Quest semantics changed; candidate discarded")
    timings["validation"] = (time.perf_counter() - started) * 1000
    _emit(progress, "validation", 5, "Validated mount, knowledge, and unchanged quests")
    candidate_hash = hashlib.sha256(applied.output_blob).hexdigest()
    report = BlackstarChangeReport(
        mount_before=plan.mount_count,
        mount_after=candidate_plan.mount_count,
        knowledge_added=plan.knowledge_missing,
        knowledge_skipped=plan.knowledge_existing,
        duplicate_mounts=0,
        duplicate_knowledge=(),
        byte_growth=len(applied.output_blob) - len(original),
        quest_changes=0,
        fixups=applied.fixups,
        timings_ms=timings,
    )
    log.info(
        "operation=%s blackstar_complete dry_run=%s input_sha256=%s "
        "candidate_sha256=%s report=%s",
        operation_id,
        dry_run,
        input_hash,
        candidate_hash,
        json.dumps(asdict(report), sort_keys=True),
    )
    _emit(progress, "complete", 6, "Blackstar unlock candidate is valid")
    return BlackstarResult(
        input_sha256=input_hash,
        candidate_sha256=candidate_hash,
        output_blob=None if dry_run else applied.output_blob,
        profile_id=profile.profile_id,
        report=report,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Blackstar unlock changes")
    parser.add_argument("--save", required=True)
    parser.add_argument("--dry-run", action="store_true", required=True)
    parser.add_argument(
        "--allow-any-copied-path",
        action="store_true",
        help="Allow a copied save outside tests/fixtures or the system temporary directory.",
    )
    args = parser.parse_args()
    from app_logging import new_operation_id
    from save_compat import load_profiles, require_supported_identity
    from save_crypto import load_save_file

    save_path = Path(args.save).resolve()
    fixture_root = (Path(__file__).resolve().parents[1] / "tests" / "fixtures").resolve()
    temporary_root = Path(tempfile.gettempdir()).resolve()
    safe_roots = (fixture_root, temporary_root)
    if not args.allow_any_copied_path and not any(
        save_path == root or root in save_path.parents for root in safe_roots
    ):
        parser.error(
            "Dry-run input must be under tests/fixtures or the system temporary "
            "directory. Use --allow-any-copied-path only for another copied save."
        )
    save = load_save_file(str(save_path))
    profile = require_supported_identity(save.schema_identity, load_profiles())
    result = unlock_blackstar(
        save.decompressed_blob,
        profile,
        dry_run=True,
        operation_id=new_operation_id("blackstar-cli"),
    )
    print(json.dumps(asdict(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
