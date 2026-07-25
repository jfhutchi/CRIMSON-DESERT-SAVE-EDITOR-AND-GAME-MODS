# Blackstar Call Dragon Wheel Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the safe 1.14 Blackstar transaction to add exactly `Knowledge_CallDragon` when missing so an owned Blackstar can become summon-wheel eligible without changing quest flags.

**Architecture:** Add a focused `blackstar_knowledge.py` policy module that detects, validates, and inserts one target-local Call Dragon knowledge element through the existing PARC fixup machinery. Refactor the pure Blackstar service to plan ownership and wheel eligibility independently, validate only the authorized mercenary and knowledge deltas, and preserve the existing preview token, worker, mandatory backup, temporary reload, and atomic replacement.

**Tech Stack:** Python 3.12, dataclasses, existing PARC parser/inserter/fixup helpers, PySide6/QThread, pytest, PyInstaller.

---

## File Map

- Create `CrimsonSaveEditor/blackstar_knowledge.py`: Call Dragon knowledge constants, state detection, target-local template selection, insertion, and element-level semantic snapshots.
- Modify `CrimsonSaveEditor/parc_inserter3.py`: allow the bounded knowledge inserter to clone an explicitly selected element from the same parsed list.
- Modify `CrimsonSaveEditor/blackstar_compat.py`: fail closed when a missing Call Dragon entry has no compatible target-local 1.14 template.
- Modify `CrimsonSaveEditor/blackstar_unlock.py`: plan ownership and Call Dragon independently, apply the authorized deltas, and validate quest/root invariance.
- Modify `CrimsonSaveEditor/blackstar_worker.py`: make progress ordering monotonic across the longer service and write phases.
- Modify `CrimsonSaveEditor/gui.py`: report Call Dragon before/after state and separate mount/knowledge actions.
- Modify `CrimsonSaveEditor/CrimsonSaveEditor.spec`: explicitly bundle `blackstar_knowledge`.
- Modify `CrimsonSaveEditor/README.md` and `BUILD_FROM_SOURCE.md`: document the one-key wheel repair and revised expected dry-run output.
- Create `tests/test_blackstar_knowledge.py`: reference evidence, target-local template selection, exact inserted shape, refusal cases, and idempotency.
- Modify `tests/test_blackstar_compat.py`, `tests/test_blackstar_unlock.py`, `tests/test_blackstar_worker.py`, `tests/test_gui_save_contract.py`, `tests/test_save_crypto_transaction.py`, and `tests/test_packaging_contract.py`.

### Task 1: Explicit Target-Local Knowledge Template Support

**Files:**
- Modify: `CrimsonSaveEditor/parc_inserter3.py:2358`
- Create: `tests/test_blackstar_knowledge.py`

- [ ] **Step 1: Write the failing explicit-template tests**

Create `tests/test_blackstar_knowledge.py` with fixture helpers that parse the
knowledge list without raw-byte searching:

```python
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
        obj for obj in context.result["objects"]
        if obj.class_name == "KnowledgeSaveData"
    )
    entries = next(field for field in root.fields if field.name == "_list")
    return root, entries


def _fields(element):
    return {field.name: field for field in element.child_fields or [] if field.present}


def _key(context, element):
    field = _fields(element)["_key"]
    return struct.unpack_from("<I", context.raw, field.start_offset)[0]


def test_context_inserter_uses_requested_target_local_template(early_114_save_path) -> None:
    context = _context(early_114_save_path)
    _root, entries = _knowledge_parts(context)
    template = next(
        element for element in reversed(entries.list_elements)
        if set(_fields(element)) == {
            "_key", "_level", "_learnedFieldTime", "_isNewMark"
        }
    )

    candidate, _metrics = insert_knowledge_keys_with_context(
        context,
        [1000175],
        override_level=1,
        template_element=template,
    )
    after = build_insert_context(candidate)
    _root_after, entries_after = _knowledge_parts(after)
    inserted = [element for element in entries_after.list_elements if _key(after, element) == 1000175]

    assert len(inserted) == 1
    assert inserted[0].end_offset - inserted[0].start_offset == 43
    assert set(_fields(inserted[0])) == {
        "_key", "_level", "_learnedFieldTime", "_isNewMark"
    }


def test_context_inserter_rejects_template_outside_target_list(early_114_save_path) -> None:
    context = _context(early_114_save_path)
    foreign = type("ForeignElement", (), {"start_offset": 1, "end_offset": 2})()
    with pytest.raises(ValueError, match="target knowledge list"):
        insert_knowledge_keys_with_context(
            context,
            [1000175],
            override_level=1,
            template_element=foreign,
        )
```

- [ ] **Step 2: Run the tests and verify the expected failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_knowledge.py -v --timeout=300
```

Expected: both tests fail because `template_element` is not an accepted keyword.

- [ ] **Step 3: Add the explicit target-local template parameter**

Change the signature and template selection in
`insert_knowledge_keys_with_context`:

```python
def insert_knowledge_keys_with_context(
    context: ParsedInsertContext,
    keys_to_insert: tuple[int, ...] | list[int],
    override_level: int = -1,
    *,
    template_element=None,
) -> tuple[bytes, FixupMetrics]:
    orig_blob = context.raw
    know_obj = know_field = None
    for obj in context.result['objects']:
        if obj.class_name == 'KnowledgeSaveData':
            for field in obj.fields:
                if field.name == '_list' and field.list_elements:
                    know_obj = obj
                    know_field = field
                    break
            break
    if not know_obj or not know_field:
        raise ValueError("KnowledgeSaveData._list not found")
    if not keys_to_insert:
        return orig_blob, FixupMetrics()

    if template_element is None:
        template_elem = know_field.list_elements[-1]
    else:
        template_elem = next(
            (
                element for element in know_field.list_elements
                if element.start_offset == template_element.start_offset
                and element.end_offset == template_element.end_offset
            ),
            None,
        )
        if template_elem is None:
            raise ValueError("Knowledge template is not from the target knowledge list")
```

Keep the existing bounded clone, locator relocation, list-count update, and
fixup body unchanged after `template_elem` is selected.

- [ ] **Step 4: Run the focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_knowledge.py -v --timeout=300
```

Expected: `2 passed`.

- [ ] **Step 5: Commit the target-local insertion seam**

```powershell
git add CrimsonSaveEditor/parc_inserter3.py tests/test_blackstar_knowledge.py
git commit -m "feat: support target-local knowledge templates"
```

### Task 2: Call Dragon Knowledge Policy

**Files:**
- Create: `CrimsonSaveEditor/blackstar_knowledge.py`
- Modify: `tests/test_blackstar_knowledge.py`
- Modify: `tests/test_blackstar_compat.py`
- Modify: `CrimsonSaveEditor/blackstar_compat.py`

- [ ] **Step 1: Add failing reference, insertion, and refusal tests**

Extend `tests/test_blackstar_knowledge.py`:

```python
from dataclasses import replace

from blackstar_knowledge import (
    CALL_DRAGON_KNOWLEDGE_KEY,
    CallDragonKnowledgeError,
    inspect_call_dragon,
    insert_call_dragon,
    select_call_dragon_template,
)


def test_reference_evidence_isolated_to_call_dragon(
    early_114_save_path, legit_idle_114_save_path, legit_active_114_save_path
) -> None:
    assert inspect_call_dragon(_context(early_114_save_path)).status == "missing"
    for path in (legit_idle_114_save_path, legit_active_114_save_path):
        state = inspect_call_dragon(_context(path))
        assert state.status == "present"
        assert state.count == 1
        assert state.level == 1


def test_call_dragon_insert_has_legitimate_target_local_shape(early_114_save_path) -> None:
    context = _context(early_114_save_path)
    before_count = len(_knowledge_parts(context)[1].list_elements)
    candidate, metrics = insert_call_dragon(context)
    after = build_insert_context(candidate)
    state = inspect_call_dragon(after)
    _root, entries = _knowledge_parts(after)
    inserted = [element for element in entries.list_elements if _key(after, element) == CALL_DRAGON_KNOWLEDGE_KEY]

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
        element for element in entries.list_elements
        if _key(parsed, element) == CALL_DRAGON_KNOWLEDGE_KEY
    )
    level = _fields(target)["_level"]
    malformed = bytearray(first)
    malformed[level.start_offset:level.end_offset] = b"\x00\x00\x00\x00"
    with pytest.raises(CallDragonKnowledgeError, match="below 1"):
        inspect_call_dragon(build_insert_context(malformed))


def test_template_selection_requires_exact_fields_and_widths(early_114_save_path) -> None:
    context = _context(early_114_save_path)
    template = select_call_dragon_template(context)
    fields = _fields(template)
    assert set(fields) == {"_key", "_level", "_learnedFieldTime", "_isNewMark"}
    assert {name: field.end_offset - field.start_offset for name, field in fields.items()} == {
        "_key": 4,
        "_level": 4,
        "_learnedFieldTime": 8,
        "_isNewMark": 1,
    }
```

Extend `tests/test_blackstar_compat.py` with a monkeypatched refusal contract:

```python
import blackstar_compat
from blackstar_knowledge import CallDragonKnowledgeError


def test_missing_call_dragon_requires_compatible_local_template(
    early_114_save_path, monkeypatch
) -> None:
    save = load_save_file(str(early_114_save_path))
    monkeypatch.setattr(
        blackstar_compat,
        "select_call_dragon_template",
        lambda _context: (_ for _ in ()).throw(
            CallDragonKnowledgeError("No compatible target-local Call Dragon template")
        ),
    )
    with pytest.raises(BlackstarCompatibilityError, match="target-local"):
        require_blackstar_compatibility(
            build_insert_context(save.decompressed_blob), save.schema_identity
        )
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_knowledge.py tests\test_blackstar_compat.py -v --timeout=300
```

Expected: collection fails because `blackstar_knowledge` does not exist.

- [ ] **Step 3: Implement the focused knowledge policy module**

Create `CrimsonSaveEditor/blackstar_knowledge.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from parc_inserter3 import (
    FixupMetrics,
    ParsedInsertContext,
    insert_knowledge_keys_with_context,
)

CALL_DRAGON_KNOWLEDGE_KEY = 1000175
CALL_DRAGON_FIELDS = {
    "_key": 4,
    "_level": 4,
    "_learnedFieldTime": 8,
    "_isNewMark": 1,
}


class CallDragonKnowledgeError(ValueError):
    pass


@dataclass(frozen=True)
class CallDragonKnowledgeState:
    status: str
    count: int
    level: int | None


def _value(raw: bytes, field) -> int:
    return int.from_bytes(raw[field.start_offset:field.end_offset], "little")


def knowledge_parts(context: ParsedInsertContext):
    roots = [
        obj for obj in context.result["objects"]
        if obj.class_name == "KnowledgeSaveData"
    ]
    if len(roots) != 1:
        raise CallDragonKnowledgeError("Expected exactly one KnowledgeSaveData")
    entries = next((field for field in roots[0].fields if field.name == "_list"), None)
    if not entries or entries.list_elements is None:
        raise CallDragonKnowledgeError("KnowledgeSaveData._list is missing")
    return roots[0], entries


def present_fields(element) -> dict[str, object]:
    return {
        field.name: field for field in element.child_fields or []
        if field.present
    }


def inspect_call_dragon(context: ParsedInsertContext) -> CallDragonKnowledgeState:
    _root, entries = knowledge_parts(context)
    matches = []
    for element in entries.list_elements:
        fields = present_fields(element)
        key = fields.get("_key")
        if key and key.end_offset - key.start_offset == 4:
            if _value(context.raw, key) == CALL_DRAGON_KNOWLEDGE_KEY:
                matches.append(fields)
    if not matches:
        return CallDragonKnowledgeState("missing", 0, None)
    if len(matches) != 1:
        raise CallDragonKnowledgeError(
            f"Duplicate Call Dragon knowledge entries: {len(matches)}"
        )
    level = matches[0].get("_level")
    if not level or level.end_offset - level.start_offset != 4:
        raise CallDragonKnowledgeError("Call Dragon knowledge level is malformed")
    value = _value(context.raw, level)
    if value < 1:
        raise CallDragonKnowledgeError("Call Dragon knowledge level is below 1")
    return CallDragonKnowledgeState("present", 1, value)


def select_call_dragon_template(context: ParsedInsertContext):
    _root, entries = knowledge_parts(context)
    candidates = []
    for element in entries.list_elements:
        fields = present_fields(element)
        widths = {
            name: field.end_offset - field.start_offset
            for name, field in fields.items()
        }
        if widths != CALL_DRAGON_FIELDS:
            continue
        if _value(context.raw, fields["_isNewMark"]) != 1:
            continue
        if element.end_offset - element.start_offset != 43:
            continue
        candidates.append(element)
    if not candidates:
        raise CallDragonKnowledgeError(
            "No compatible target-local Call Dragon template"
        )
    return candidates[-1]


def insert_call_dragon(
    context: ParsedInsertContext,
) -> tuple[bytes, FixupMetrics]:
    if inspect_call_dragon(context).status == "present":
        return context.raw, FixupMetrics()
    template = select_call_dragon_template(context)
    return insert_knowledge_keys_with_context(
        context,
        [CALL_DRAGON_KNOWLEDGE_KEY],
        override_level=1,
        template_element=template,
    )
```

- [ ] **Step 4: Extend the compatibility boundary**

In `CrimsonSaveEditor/blackstar_compat.py`, import the knowledge policy and add
this check after root validation:

```python
from blackstar_knowledge import (
    CallDragonKnowledgeError,
    inspect_call_dragon,
    select_call_dragon_template,
)

try:
    call_dragon = inspect_call_dragon(context)
    if call_dragon.status == "missing":
        select_call_dragon_template(context)
except CallDragonKnowledgeError as exc:
    raise BlackstarCompatibilityError(str(exc)) from exc
```

- [ ] **Step 5: Run focused policy and compatibility tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_knowledge.py tests\test_blackstar_compat.py -v --timeout=300
```

Expected: all tests pass.

- [ ] **Step 6: Commit the Call Dragon policy**

```powershell
git add CrimsonSaveEditor/blackstar_knowledge.py CrimsonSaveEditor/blackstar_compat.py tests/test_blackstar_knowledge.py tests/test_blackstar_compat.py
git commit -m "feat: add Call Dragon knowledge policy"
```

### Task 3: Independent Ownership and Wheel-Eligibility Planning

**Files:**
- Modify: `CrimsonSaveEditor/blackstar_unlock.py`
- Modify: `tests/test_blackstar_unlock.py`

- [ ] **Step 1: Replace ownership-only expectations with failing combined-state tests**

Add a knowledge helper and update the early fixture expectations in
`tests/test_blackstar_unlock.py`:

```python
from blackstar_knowledge import CALL_DRAGON_KNOWLEDGE_KEY, inspect_call_dragon


def _ownership_only_candidate(save, blob: bytes) -> bytes:
    import blackstar_unlock as service
    from blackstar_template import BlackstarDynamicValues, materialize_blackstar_template

    context = build_insert_context(blob)
    mercenary_no, item_no = service._allocate_ids(context)
    _reference_key, _time, base = service._reference_values(context)
    values = BlackstarDynamicValues(
        mercenary_no=mercenary_no,
        item_no=item_no,
        owner_key=base.owner_key,
        last_paid_time=base.last_paid_time,
        last_breeding_time=base.last_breeding_time,
        spawn_position=base.spawn_position,
        spawn_yaw=base.spawn_yaw,
        spawn_field_key=base.spawn_field_key,
    )
    _clan, mounts = service._clan_parts(context)
    record = materialize_blackstar_template(
        context, mounts.list_elements[-1].end_offset, values
    )
    candidate, _metrics = service._insert_record(context, record)
    return candidate


def test_early_dry_run_plans_ownership_and_call_dragon_without_mutation(
    early_114_save_path,
) -> None:
    save, blob = _load(early_114_save_path)
    before = hashlib.sha256(blob).hexdigest()
    result = unlock_blackstar(blob, save.schema_identity, True, "early-preview")
    assert result.output_blob is None
    assert hashlib.sha256(blob).hexdigest() == before
    assert result.report.classification_before == "absent"
    assert result.report.call_dragon_before == "missing"
    assert result.report.call_dragon_after == "present"
    assert result.report.mount_action == "insert"
    assert result.report.knowledge_action == "insert_call_dragon"
    assert result.report.knowledge_changes == 1
    assert result.report.quest_changes == 0


def test_ownership_only_state_gets_knowledge_only_repair(early_114_save_path) -> None:
    save, blob = _load(early_114_save_path)
    ownership_only = _ownership_only_candidate(save, blob)
    before_context = build_insert_context(ownership_only)
    assert inspect_call_dragon(before_context).status == "missing"

    result = unlock_blackstar(
        ownership_only, save.schema_identity, False, "wheel-repair"
    )
    assert result.report.classification_before == "legitimate_idle"
    assert result.report.mount_action == "none"
    assert result.report.knowledge_action == "insert_call_dragon"
    assert result.report.mount_before == result.report.mount_after == 1
    assert result.report.mercenary_no is None
    assert result.report.item_no is None
    assert result.report.knowledge_changes == 1
    assert result.report.quest_changes == 0
    assert result.report.byte_growth == 43
    assert inspect_call_dragon(build_insert_context(result.output_blob)).status == "present"


def test_second_run_after_wheel_repair_is_byte_identical(early_114_save_path) -> None:
    save, blob = _load(early_114_save_path)
    first = unlock_blackstar(blob, save.schema_identity, False, "first")
    second = unlock_blackstar(first.output_blob, save.schema_identity, False, "second")
    assert second.output_blob == first.output_blob
    assert second.report.mount_action == "none"
    assert second.report.knowledge_action == "none"
    assert second.report.knowledge_changes == 0
    assert second.report.quest_changes == 0
    assert second.report.byte_growth == 0
```

Update the existing early apply test to require one Call Dragon element and to
compare every original knowledge element with the corresponding prefix in the
candidate instead of requiring the complete knowledge roots to be identical.
Decode key `40068` before and after and assert its level and learned-time fields
remain identical.

- [ ] **Step 2: Run the unlock tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_unlock.py -v --timeout=600
```

Expected: failures for missing report fields and the ownership-only early return.

- [ ] **Step 3: Extend the report and add element/root snapshot helpers**

Change `BlackstarChangeReport` to keyword-oriented fields:

```python
@dataclass(frozen=True)
class BlackstarChangeReport:
    classification_before: str
    classification_after: str
    call_dragon_before: str
    call_dragon_after: str
    action: str
    mount_action: str
    knowledge_action: str
    mount_before: int
    mount_after: int
    mercenary_no: int | None
    item_no: int | None
    reference_character_key: int | None
    knowledge_changes: int
    quest_changes: int
    byte_growth: int
    fixups: FixupMetrics
    timings_ms: dict[str, float]
```

Add element and unchanged-root snapshots:

```python
def canonical_element_snapshot(element) -> tuple:
    snapshots = []
    for path, field in _walk(element, "element"):
        children = getattr(field, "child_fields", None) or []
        elements = getattr(field, "list_elements", None)
        if children or elements is not None:
            snapshots.append((
                path,
                field.type_name,
                field.child_mask_bytes.hex(),
                field.list_prefix_u8,
                len(elements) if elements is not None else None,
            ))
        elif field.present:
            semantic = _TARGET_PATTERN.sub("", str(field.value_repr))
            snapshots.append((path, field.type_name, semantic))
    return tuple(snapshots)


def unchanged_root_snapshots(context: ParsedInsertContext) -> dict[str, tuple]:
    excluded = {"MercenaryClanSaveData", "KnowledgeSaveData"}
    names = sorted({
        obj.class_name for obj in context.result["objects"]
        if obj.class_name not in excluded
    })
    return {name: canonical_root_snapshot(context, name) for name in names}
```

- [ ] **Step 4: Refactor `unlock_blackstar` around independent required actions**

Import the knowledge policy:

```python
from blackstar_knowledge import (
    inspect_call_dragon,
    insert_call_dragon,
    knowledge_parts,
)
```

Replace the legitimate-ownership early return with this state plan:

```python
classification, found = _classify(context)
call_before = inspect_call_dragon(context)
needs_mount = not classification.startswith("legitimate")
needs_knowledge = call_before.status == "missing"

if not needs_mount and not needs_knowledge:
    digest = hashlib.sha256(original).hexdigest()
    report = BlackstarChangeReport(
        classification_before=classification,
        classification_after=classification,
        call_dragon_before="present",
        call_dragon_after="present",
        action="none",
        mount_action="none",
        knowledge_action="none",
        mount_before=1,
        mount_after=1,
        mercenary_no=None,
        item_no=None,
        reference_character_key=None,
        knowledge_changes=0,
        quest_changes=0,
        byte_growth=0,
        fixups=FixupMetrics(),
        timings_ms={"total": (time.perf_counter() - started) * 1000},
    )
    return BlackstarResult(
        digest, digest, None if dry_run else original, grant.family_id, report
    )
```

Before mutation capture:

```python
quest_before = canonical_root_snapshot(context, "QuestSaveData")
unchanged_before = unchanged_root_snapshots(context)
_knowledge_root, knowledge_list_before = knowledge_parts(context)
knowledge_entries_before = tuple(
    canonical_element_snapshot(element)
    for element in knowledge_list_before.list_elements
)
```

Initialize `candidate = original`, `candidate_context = context`,
`fixups = FixupMetrics()`, ID fields to `None`, and action fields to `"none"`.
Run the existing allocation/materialization/insert-or-replace block only when
`needs_mount` is true, then reparse the ownership candidate. Run this knowledge
block independently:

```python
if needs_knowledge:
    candidate, knowledge_fixups = insert_call_dragon(candidate_context)
    fixups = fixups + knowledge_fixups
    candidate_context = build_insert_context(candidate)
    knowledge_action = "insert_call_dragon"
```

Validate the final state:

```python
after_classification, after_found = _classify(candidate_context)
expected_classification = (
    classification if classification.startswith("legitimate")
    else "legitimate_idle"
)
if after_classification != expected_classification or len(after_found) != 1:
    raise BlackstarValidationError("Candidate Blackstar record did not validate")
call_after = inspect_call_dragon(candidate_context)
if call_after.status != "present" or call_after.count != 1:
    raise BlackstarValidationError("Candidate Call Dragon knowledge did not validate")
if canonical_root_snapshot(candidate_context, "QuestSaveData") != quest_before:
    raise BlackstarValidationError("Quest semantics changed")
if unchanged_root_snapshots(candidate_context) != unchanged_before:
    raise BlackstarValidationError("Unrelated root semantics changed")
_knowledge_root_after, knowledge_list_after = knowledge_parts(candidate_context)
knowledge_entries_after = tuple(
    canonical_element_snapshot(element)
    for element in knowledge_list_after.list_elements
)
if knowledge_entries_after[:len(knowledge_entries_before)] != knowledge_entries_before:
    raise BlackstarValidationError("Existing knowledge semantics changed")
expected_growth = 1 if needs_knowledge else 0
if len(knowledge_entries_after) - len(knowledge_entries_before) != expected_growth:
    raise BlackstarValidationError("Unexpected knowledge-list growth")
```

Build `action` from non-`none` actions joined with `+`, construct the report with
keyword arguments, and keep `output_blob=None` for dry run.

- [ ] **Step 5: Run the unlock and reference tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_unlock.py tests\test_blackstar_knowledge.py -v --timeout=600
```

Expected: all tests pass; the early candidate grows by 480 bytes, the
ownership-only repair grows by 43 bytes, and the second run grows by 0 bytes.

- [ ] **Step 6: Commit the combined state machine**

```powershell
git add CrimsonSaveEditor/blackstar_unlock.py tests/test_blackstar_unlock.py
git commit -m "feat: repair Blackstar wheel eligibility"
```

### Task 4: Worker Progress, GUI Report, and Logging

**Files:**
- Modify: `CrimsonSaveEditor/blackstar_unlock.py`
- Modify: `CrimsonSaveEditor/blackstar_worker.py`
- Modify: `CrimsonSaveEditor/gui.py:9640`
- Modify: `tests/test_blackstar_worker.py`
- Modify: `tests/test_gui_save_contract.py`

- [ ] **Step 1: Write failing progress and GUI report contracts**

Update the worker assertion in `tests/test_blackstar_worker.py`:

```python
assert [event.completed for event in progress] == [1, 7, 8, 9]
assert all(event.total == 9 for event in progress)
```

Make the fake service emit `BlackstarProgress("parse", 1, 7, "Parsed")` and
`BlackstarProgress("complete", 7, 7, "Done")`.

Extend `test_blackstar_has_preview_bound_atomic_apply` in
`tests/test_gui_save_contract.py`:

```python
assert "Call Dragon knowledge" in finish
assert "report.mount_action" in finish
assert "report.knowledge_action" in finish
assert "report.call_dragon_before" in finish
assert "report.call_dragon_after" in finish
```

Replace the obsolete `apply_blackstar_plan` source assertion in
`tests/test_app_logging.py` with a contract against the current service:

```python
def test_blackstar_ownership_and_call_dragon_have_distinct_log_phases() -> None:
    source = inspect.getsource(blackstar_unlock.unlock_blackstar)
    for phase_name in (
        "blackstar_mount_insertion",
        "call_dragon_detection",
        "call_dragon_template_selection",
        "call_dragon_insertion",
        "blackstar_final_reparse",
        "blackstar_semantic_validation",
    ):
        assert f'"{phase_name}"' in source
```

- [ ] **Step 2: Run focused contracts and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_worker.py tests\test_gui_save_contract.py -v
```

Expected: progress ordering and missing GUI report fields fail.

- [ ] **Step 3: Make worker progress monotonic**

In `blackstar_worker.py`:

```python
BLACKSTAR_WORK_TOTAL = 9

def _forward_progress(self, event: BlackstarProgress) -> None:
    self.progress.emit(replace(event, total=BLACKSTAR_WORK_TOTAL))
```

Use completed value `8` for the write event and `9` for the worker terminal
event. The pure service uses completed values `1` through `7`.

- [ ] **Step 4: Add bounded knowledge logging phases**

In `blackstar_unlock.py`, stop deleting `operation_id`, add a module logger, and
wrap state detection, knowledge insertion, final reparse, and validation:

```python
import logging

from app_logging import phase

log = logging.getLogger(__name__)
```

Use phase names `call_dragon_detection`, `call_dragon_template_selection`,
`call_dragon_insertion`, `blackstar_final_reparse`, and
`blackstar_semantic_validation`. Log only status, count, element size, fixup
counts, and SHA-256 values.

- [ ] **Step 5: Expand the GUI report**

In `_finish_blackstar_unlock`, include:

```python
f"Ownership: {report.classification_before} -> {report.classification_after}\n"
f"Call Dragon knowledge: {report.call_dragon_before} -> {report.call_dragon_after}\n"
f"Mount action: {report.mount_action}\n"
f"Knowledge action: {report.knowledge_action}\n"
```

Keep the existing mount count, allocated IDs, knowledge change count, quest
change count, byte growth, and candidate hash lines.

- [ ] **Step 6: Run worker, GUI, and logging tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_worker.py tests\test_gui_save_contract.py tests\test_app_logging.py -v --timeout=300
```

Expected: all tests pass with monotonic progress and explicit Call Dragon
reporting.

- [ ] **Step 7: Commit worker/UI/logging integration**

```powershell
git add CrimsonSaveEditor/blackstar_unlock.py CrimsonSaveEditor/blackstar_worker.py CrimsonSaveEditor/gui.py tests/test_blackstar_worker.py tests/test_gui_save_contract.py tests/test_app_logging.py
git commit -m "feat: report Blackstar wheel repair progress"
```

### Task 5: Transaction, Packaging, Documentation, and Build

**Files:**
- Modify: `tests/test_save_crypto_transaction.py`
- Modify: `tests/test_packaging_contract.py`
- Modify: `CrimsonSaveEditor/CrimsonSaveEditor.spec`
- Modify: `CrimsonSaveEditor/README.md`
- Modify: `BUILD_FROM_SOURCE.md`

- [ ] **Step 1: Update failing transactional and packaging expectations**

In `test_blackstar_apply_write_reload_is_idempotent`, require the first apply to
report `knowledge_changes == 1`, reload with Call Dragon present, and require
the second apply to report zero changes. In
`test_scoped_blackstar_transaction_writes_unknown_schema_with_backup`, assert:

```python
assert preview.report.call_dragon_before == "missing"
assert preview.report.call_dragon_after == "present"
assert preview.report.knowledge_changes == 1
assert preview.report.quest_changes == 0
assert applied.candidate_sha256 == preview.candidate_sha256
```

Extend `test_spec_bundles_blackstar_safety_modules_and_schema_manifest` so its
module tuple contains `"blackstar_knowledge"`.

- [ ] **Step 2: Run transaction and packaging tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_save_crypto_transaction.py tests\test_packaging_contract.py -v --timeout=600
```

Expected: failures for the old zero-knowledge expectation and missing hidden
import.

- [ ] **Step 3: Bundle the policy module and update documentation**

Add `'blackstar_knowledge'` beside the other Blackstar hidden imports in
`CrimsonSaveEditor/CrimsonSaveEditor.spec`.

Update both documentation files to state:

- Preview may plan exactly one `Knowledge_CallDragon` addition;
- quest-completion changes always remain zero;
- an existing legitimate Blackstar with missing Call Dragon receives a
  knowledge-only 43-byte repair;
- the second preview must report no action and zero byte growth;
- no game-file overlay is part of this operation;
- only copied fixture or temporary saves are used in command-line verification.

- [ ] **Step 4: Run the complete focused safety suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_compat.py tests\test_blackstar_template.py tests\test_blackstar_knowledge.py tests\test_blackstar_unlock.py tests\test_blackstar_worker.py tests\test_gui_blackstar_contract.py tests\test_gui_save_contract.py tests\test_save_crypto_transaction.py tests\test_packaging_contract.py tests\test_fixture_integrity.py -q --timeout=600
```

Expected: all tests pass; no original fixture hash changes.

- [ ] **Step 5: Run a copied-save dry run and temporary-copy apply**

Run from the repository root:

```powershell
$scratch = Join-Path ([IO.Path]::GetTempPath()) "crimson-call-dragon-test"
New-Item -ItemType Directory -Force $scratch | Out-Null
$copiedSave = Join-Path $scratch "save.save"
Copy-Item tests\fixtures\slot102\save.save $copiedSave -Force
$env:PYTHONPATH = (Resolve-Path CrimsonSaveEditor)
.\.venv\Scripts\python.exe -m blackstar_unlock --dry-run --save $copiedSave
```

Expected dry-run fields: ownership `absent -> legitimate_idle`, Call Dragon
`missing -> present`, mount changes `0 -> 1`, knowledge changes `1`, quest
changes `0`, and no file hash change.

Use the scoped transaction test for the actual temporary-copy write; do not add
a CLI apply mode.

- [ ] **Step 6: Verify immutable fixture hashes**

Run:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath tests\fixtures\slot102\save.save,tests\fixtures\slot107\save.save,tests\fixtures\slot108\save.save,tests\fixtures\slot102_legacy\save.save | Format-Table -AutoSize Path,Hash
```

Expected hashes:

```text
57060A7707340F20410E04FAD3127F2D6A1FDBD515CD163A196D841C6892EF78 slot102
3B9D2BDC63A892B1E513344C9121D0606B1C474DB3823CFD7ADA0AE7E234F724 slot107
6315B31B9847B585552788E9FEEB11966EBF8B09B65F6518002F9624D51623C7 slot108
E8E1F084C392F35DA4F30658C9D829890E3FE29F230EF07A8AFD6FCF534B362C slot102_legacy
```

- [ ] **Step 7: Build and hash the standalone Windows executable**

Run:

```powershell
Set-Location CrimsonSaveEditor
..\.venv\Scripts\python.exe -m PyInstaller CrimsonSaveEditor.spec --noconfirm --clean
Get-FileHash -Algorithm SHA256 .\dist\CrimsonSaveEditorStandalone.exe
Get-Item .\dist\CrimsonSaveEditorStandalone.exe | Select-Object FullName,Length,LastWriteTime
```

Expected: PyInstaller exits `0`; the executable exists at
`CrimsonSaveEditor\dist\CrimsonSaveEditorStandalone.exe` and has a new SHA-256.

- [ ] **Step 8: Commit packaging and documentation**

```powershell
git add CrimsonSaveEditor/CrimsonSaveEditor.spec CrimsonSaveEditor/README.md BUILD_FROM_SOURCE.md tests/test_save_crypto_transaction.py tests/test_packaging_contract.py
git commit -m "docs: document Blackstar wheel eligibility repair"
```

## Final In-Game Checkpoint

The implementation is ready for the user's copied-save test only after every
automated and build checkpoint passes. The user must Preview again with the new
executable, verify knowledge changes `1` and quest changes `0`, Apply & Save,
then Preview a second time and verify both actions are `none` with byte growth
`0` before launching the game.

If Blackstar remains absent from the wheel after this isolated one-key test,
stop. Preserve the resulting save and return to differential reference analysis;
do not add quest flags, broad knowledge sets, or a PAZ overlay.
