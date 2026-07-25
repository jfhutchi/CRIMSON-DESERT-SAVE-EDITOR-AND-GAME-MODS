# Blackstar 1.14 Ownership Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the obsolete Blackstar/knowledge insertion with a legitimate, idempotent 1.14 ownership insert or legacy repair that never changes quests or knowledge and can write only through a preview-bound, verified transaction.

**Architecture:** A feature-scoped compatibility module validates only the seven touched PARC types, while a normalized template module translates the legitimate idle Blackstar tree into the target schema and patches target-derived values. The pure unlock service classifies absent, legacy, legitimate, unknown, and duplicate states; the GUI worker previews first and a scoped apply token authorizes only the exact candidate for mandatory-backup atomic writing.

**Tech Stack:** Python 3.12, dataclasses, PySide6/QThread, existing PARC parser/fixup helpers, LZ4, ChaCha20/HMAC save container, pytest, PyInstaller.

---

## File Map

- Create `CrimsonSaveEditor/blackstar_template.py`: normalized 437-byte template, legacy fingerprint, type translation, dynamic patching.
- Create `CrimsonSaveEditor/blackstar_compat.py`: feature signatures, compatibility grant, preview/apply token validation.
- Rewrite `CrimsonSaveEditor/blackstar_unlock.py`: classification, planning, target-derived allocation, splice, invariance validation, reporting, CLI.
- Modify `CrimsonSaveEditor/blackstar_worker.py`: preview and scoped apply modes; no item-offset refresh or GUI-owned mutation.
- Modify `CrimsonSaveEditor/save_crypto.py`: reusable validated transaction core plus Blackstar-token entry point.
- Modify `CrimsonSaveEditor/gui.py`: preview-token state, unknown-full-schema preview access, explicit Apply & Save flow, reload after apply.
- Modify `CrimsonSaveEditor/CrimsonSaveEditor.spec`: bundle the two new modules.
- Modify `tests/conftest.py`: immutable hashes/fixtures for the clean early and legitimate reference copies.
- Replace/update `tests/test_blackstar_unlock.py`, `tests/test_blackstar_worker.py`, `tests/test_save_crypto_transaction.py`, `tests/test_gui_save_contract.py`, and `tests/test_packaging_contract.py`.
- Create `tests/test_blackstar_compat.py` and `tests/test_blackstar_template.py`.
- Modify `CrimsonSaveEditor/README.md` and `BUILD_FROM_SOURCE.md`.

### Task 1: Feature Compatibility Contract

**Files:**
- Create: `CrimsonSaveEditor/blackstar_compat.py`
- Create: `tests/test_blackstar_compat.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Add immutable copied-fixture accessors**

Add session fixtures that assert these exact encrypted hashes before returning paths:

```python
EARLY_114_SHA256 = "57060a7707340f20410e04fad3127f2d6a1fdbd515cd163a196d841c6892ef78"
LEGIT_IDLE_114_SHA256 = "3b9d2bdc63a892b1e513344c9121d0606b1c474db3823cfd7ada0ae7e234f724"
LEGIT_ACTIVE_114_SHA256 = "6315b31b9847b585552788e9feeb11966ebf8b09b65f6518002f9624d51623c7"

@pytest.fixture(scope="session")
def early_114_save_path() -> Path:
    path = FIXTURES / "slot102" / "save.save"
    assert sha256_file(path) == EARLY_114_SHA256
    return path
```

Repeat the same shape for `slot107` and `slot108`. Never copy into or write inside `tests/fixtures`.

- [ ] **Step 2: Write failing feature-compatibility tests**

Test that the early fixture is broad-read-only, but `require_blackstar_compatibility()` accepts it; all seven signatures equal the committed values; replacing the `ItemSaveData` signature with zeros raises `BlackstarCompatibilityError`; missing `ItemSocketSaveData` raises the same error.

```python
grant = require_blackstar_compatibility(
    build_insert_context(bytes(save.decompressed_blob)), save.schema_identity
)
assert grant.family_id == "blackstar-owner-114-v1"
assert not save.is_schema_supported
```

- [ ] **Step 3: Run the tests and verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_compat.py -v`

Expected: collection fails because `blackstar_compat` does not exist.

- [ ] **Step 4: Implement the feature gate**

Define the exact family signatures:

```python
BLACKSTAR_TYPE_SIGNATURES = {
    "MercenaryClanSaveData": "dfd071099c52729b1a4a81d8227feae5e1369d7a78382e0b4c493e82b36f9118",
    "MercenarySaveData": "9eb3b14c5c3bcfb28010eb0e6213a253a4813a13645f37ee37e2344c063b2972",
    "ExperienceLevelSaveData": "f582f2a269e3d5fa443b6c11b4648e52052a2495df1461d66cde28b9754c67d5",
    "FriendlyDailyCountSaveData": "e901369cd8b8602e892c19be4a7832e7bbd5ef927690dbfab5af605c7150be50",
    "ItemSaveData": "6d245a805bcc83cc5631563c79e7918f8dfd1ba1ee21bfb8e281ec7dfbf426ff",
    "ItemSocketSaveData": "6198ec9b4b46a21482e1ba713d877388c9c58daac5c82827eae22854e5741979",
    "KnowledgeSaveData": "124fdeffcc6583cb99cc82640364591e9d616d8bcca79ddaf77605606097029e",
}
```

Add:

```python
@dataclass(frozen=True)
class BlackstarCompatibilityGrant:
    family_id: str
    container_version: int
    source_schema_sha256: str
    source_type_count: int
    source_root_count: int
    touched_type_signatures: tuple[tuple[str, str], ...]

class BlackstarCompatibilityError(ValueError):
    pass

def require_blackstar_compatibility(
    context: ParsedInsertContext,
    identity: SaveSchemaIdentity,
) -> BlackstarCompatibilityGrant:
    if identity.container_version != 2 or identity.root_entry_count != 15:
        raise BlackstarCompatibilityError("Unsupported container/root layout")
    by_name = {item.name: item for item in context.parc.types}
    observed = tuple(
        (name, type_signature(by_name[name]) if name in by_name else "MISSING")
        for name in BLACKSTAR_TYPE_SIGNATURES
    )
    expected = tuple(BLACKSTAR_TYPE_SIGNATURES.items())
    if observed != expected:
        raise BlackstarCompatibilityError("Blackstar type signatures differ")
    clan = require_root_list(context, "MercenaryClanSaveData", "_mercenaryDataList")
    if clan.list_prefix_u8 != 1 or len(clan.child_mask_bytes) not in (0, 6):
        raise BlackstarCompatibilityError("Unsupported mercenary list encoding")
    return BlackstarCompatibilityGrant(
        "blackstar-owner-114-v1", identity.container_version,
        identity.schema_sha256, identity.type_count, identity.root_entry_count,
        observed,
    )
```

The implementation must calculate each signature from `context.parc.types`, require container version `2`, root count `15`, all seven exact signatures, a present nonempty `_mercenaryDataList` with prefix `1`, and required root objects. Return an immutable grant; never update `SaveData.is_schema_supported`.

- [ ] **Step 5: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_compat.py tests\test_save_compat.py -v`

Expected: PASS.

Commit: `git commit -m "feat: add Blackstar-scoped compatibility gate"`

### Task 2: Normalized Legitimate Template

**Files:**
- Create: `CrimsonSaveEditor/blackstar_template.py`
- Create: `tests/test_blackstar_template.py`

- [ ] **Step 1: Write failing normalized-template tests**

Assert the normalized bytes are 437 bytes with SHA-256 `a65b7d3bc22b1c83dc1eb30be85263def6dd682af8023851f1056ec7ea5841b2`, contain neither completed-save instance ID, and expose these dynamic slices:

```python
DYNAMIC_SLICES = {
    "mercenary_no": (31, 39),
    "owner_key": (39, 43),
    "last_paid_time": (147, 155),
    "last_breeding_time": (155, 163),
    "spawn_position": (163, 175),
    "spawn_yaw": (175, 179),
    "spawn_field_key": (179, 183),
    "item_no": (232, 240),
}
```

Test materialization against the early schema: all embedded type indices resolve to `MercenarySaveData`, `ExperienceLevelSaveData`, `FriendlyDailyCountSaveData`, `ItemSaveData`, and `ItemSocketSaveData`; all pointer locators point to their own sentinel+12 location; supplied dynamic values occupy only named slices.

- [ ] **Step 2: Verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_template.py -v`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the immutable template and materializer**

Add the normalized bytes and type map:

```python
NORMALIZED_BLACKSTAR_TEMPLATE = bytes.fromhex(
    "06000d19003e0a003b0000ffffffffffffffff110d2600000000005f450f00"
    "00000000000000000000000001001c3c0000ffffffffffffffff370d260000"
    "0000000100002f0000ffffffffffffffff4d0d260000000000040000000100"
    "002f0000ffffffffffffffff670d260000000000040000000100002f0000ff"
    "ffffffffffffff810d26000000000004000000520000000000000000000000"
    "00000000000000000000000000000000000000000000000000010100010000"
    "000000000000000000000000000004009f288d00120000ffffffffffffffff"
    "da0d2600000000000100000000000000000000001d4b0f0000000100000000"
    "000000ffff050005000000000000000000000000000000000100001a0000ffff"
    "ffffffffffff1f0e260000000000040000000100001a0000ffffffffffffffff"
    "390e260000000000040000000100001a0000ffffffffffffffff530e26000000"
    "0000040000000100001a0000ffffffffffffffff6d0e26000000000004000000"
    "0100001a0000ffffffffffffffff870e2600000000000400000001011d4b0f00"
    "01000000010000000000000001c800000001000101019a010000"
)
SOURCE_TYPE_OFFSETS = {
    8: "MercenarySaveData", 46: "ExperienceLevelSaveData",
    68: "FriendlyDailyCountSaveData", 94: "FriendlyDailyCountSaveData",
    120: "FriendlyDailyCountSaveData", 209: "ItemSaveData",
    278: "ItemSocketSaveData", 304: "ItemSocketSaveData",
    330: "ItemSocketSaveData", 356: "ItemSocketSaveData",
    382: "ItemSocketSaveData",
}
```

Add the dynamic slices and:

```python
@dataclass(frozen=True)
class BlackstarDynamicValues:
    mercenary_no: int
    owner_key: int
    last_paid_time: int
    last_breeding_time: int
    spawn_position: bytes
    spawn_yaw: bytes
    spawn_field_key: int
    item_no: int

def materialize_blackstar_template(
    context: ParsedInsertContext,
    insert_offset: int,
    values: BlackstarDynamicValues,
) -> bytes:
    record = bytearray(NORMALIZED_BLACKSTAR_TEMPLATE)
    patch_u64(record, DYNAMIC_SLICES["mercenary_no"], values.mercenary_no)
    patch_u32(record, DYNAMIC_SLICES["owner_key"], values.owner_key)
    patch_u64(record, DYNAMIC_SLICES["last_paid_time"], values.last_paid_time)
    patch_u64(record, DYNAMIC_SLICES["last_breeding_time"], values.last_breeding_time)
    patch_bytes(record, DYNAMIC_SLICES["spawn_position"], values.spawn_position)
    patch_bytes(record, DYNAMIC_SLICES["spawn_yaw"], values.spawn_yaw)
    patch_u32(record, DYNAMIC_SLICES["spawn_field_key"], values.spawn_field_key)
    patch_u64(record, DYNAMIC_SLICES["item_no"], values.item_no)
    target_types = {item.name: item.index for item in context.parc.types}
    for offset, type_name in SOURCE_TYPE_OFFSETS.items():
        if type_name not in target_types:
            raise BlackstarTemplateError(f"Missing target type {type_name}")
        struct.pack_into("<H", record, offset, target_types[type_name])
    for sentinel in iter_sentinels(record, 0, len(record) - 4):
        struct.pack_into("<I", record, sentinel + 8, insert_offset + sentinel + 12)
    locator_end = 2 + 6 + 2 + 1 + 8 + 4
    struct.pack_into("<I", record, len(record) - 4, len(record) - 4 - locator_end)
    validate_static_blackstar_fields(record)
    return bytes(record)
```

Validate ranges and byte widths, translate type indices by name, patch every sentinel pointer, recalculate the trailing locator, and assert the static character/item keys before returning bytes.

- [ ] **Step 4: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_template.py -v`

Expected: PASS.

Commit: `git commit -m "feat: add legitimate Blackstar ownership template"`

### Task 3: Ownership Planning, Classification, and Mutation

**Files:**
- Rewrite: `CrimsonSaveEditor/blackstar_unlock.py`
- Replace: `tests/test_blackstar_unlock.py`
- Modify: `CrimsonSaveEditor/parc_inserter3.py`

- [ ] **Step 1: Write failing plan/classification tests**

Cover early fixture classification `absent`, legitimate fixtures `legitimate_idle` and `legitimate_active`, allocated IDs `1000003/1000004`, Kliff horse reference selection, maximum target timestamp, zero knowledge changes, zero quest changes, and no input mutation.

The report contract becomes:

```python
@dataclass(frozen=True)
class BlackstarChangeReport:
    classification_before: str
    action: str
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

- [ ] **Step 2: Write failing mutation and legacy tests**

Assert dry run returns no output blob but a different candidate hash; apply returns a candidate containing one legitimate idle record; cooldown/duration fields remain unchanged; second apply is byte-identical. Build a legacy state in memory using the committed legacy template, verify classification `legacy`, replace rather than append, preserve count, and refuse legacy external `MercenaryNo` references. Refuse unknown single and duplicate records.

- [ ] **Step 3: Verify tests fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_unlock.py -v`

Expected: failures against the obsolete knowledge-oriented API.

- [ ] **Step 4: Implement pure planning helpers**

Implement `collect_instance_numbers`, `allocate_instance_numbers`, `select_reference_mount`, `classify_blackstar`, `build_blackstar_plan`, and canonical semantic snapshots. Instance allocation uses the union of nonzero/non-sentinel `MercenaryNo` and `ItemNo` leaves and chooses max+1/max+2 with uint64 overflow checks. Reference selection follows the design's Kliff-horse/active/sole tiers.

- [ ] **Step 5: Implement signed list splice**

Generalize `_fixup_external` and `_fixup_trailing_sizes` to accept a signed `delta`. Add `_splice_mount_element(context, start, end, replacement, increment_count)` that replaces `[start:end]`, adjusts the list count only for insertion, updates block/stream/TOC sizes, and fixes pointer locators after the splice boundary.

- [ ] **Step 6: Implement candidate validation**

Reparse; require unchanged schema bytes; require one legitimate idle record; validate unique IDs and item key `1002269`; require all non-mercenary roots semantically identical; require all other clan fields identical; require quest and knowledge snapshots identical; require cooldown/duration lists identical.

- [ ] **Step 7: Run focused tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_unlock.py tests\test_blackstar_template.py tests\test_blackstar_compat.py -v --timeout=600`

Expected: PASS and fixture hashes unchanged.

Commit: `git commit -m "fix: build legitimate idempotent Blackstar ownership"`

### Task 4: Preview-Bound Transactional Apply

**Files:**
- Modify: `CrimsonSaveEditor/blackstar_compat.py`
- Modify: `CrimsonSaveEditor/save_crypto.py`
- Modify: `tests/test_save_crypto_transaction.py`

- [ ] **Step 1: Write failing token and writer tests**

Define and test:

```python
@dataclass(frozen=True)
class BlackstarApplyToken:
    family_id: str
    source_path: str
    source_file_sha256: str
    source_blob_sha256: str
    source_schema_sha256: str
    candidate_blob_sha256: str
    document_generation: int
```

Tests must prove a temporary copy gets a verified backup and reloadable candidate, while source hash change, path mismatch, candidate mismatch, stale generation, backup failure, and temporary validation failure all leave the destination unmodified.

- [ ] **Step 2: Verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_save_crypto_transaction.py -v`

Expected: missing scoped writer/token failures.

- [ ] **Step 3: Refactor the transaction core**

Extract the existing backup/temp/fsync/reload/atomic-replace body into a private `_transactional_write_validated(destination, edited_blob, original_header, protected_source, operation_id, validate_source, validate_candidate)` receiving explicit source and candidate validator callbacks. Keep `transactional_write_save` behavior unchanged for broad profiles.

Add `transactional_write_blackstar(destination, candidate_blob, original_header, token, identity, generation, operation_id)` that rereads and hashes the source, verifies every token field, rechecks Blackstar feature compatibility and unchanged schema, and passes only the exact candidate to the shared transaction core.

- [ ] **Step 4: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_save_crypto_transaction.py tests\test_save_compat.py -v --timeout=600`

Expected: PASS.

Commit: `git commit -m "feat: add preview-bound Blackstar save transaction"`

### Task 5: Worker and GUI Two-Step Flow

**Files:**
- Modify: `CrimsonSaveEditor/blackstar_worker.py`
- Modify: `CrimsonSaveEditor/gui.py`
- Modify: `tests/test_blackstar_worker.py`
- Modify: `tests/test_gui_save_contract.py`

- [ ] **Step 1: Write failing worker tests**

Preview mode runs the pure service with `dry_run=True` and never writes. Apply mode requires a token, reloads the exact source, deterministically rebuilds the candidate, calls `transactional_write_blackstar`, and emits backup/write results. Both modes emit one terminal signal and ordered progress; cancellation never writes.

- [ ] **Step 2: Write failing GUI contract tests**

AST/source contracts require Blackstar preview to remain enabled for encrypted unknown-full-schema saves, broad Save actions to remain disabled, successful preview to store a token, Apply to require the token, and successful apply to reload from disk. Assert obsolete strings `filtered knowledge set` and `save with Ctrl+S` are absent.

- [ ] **Step 3: Verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_worker.py tests\test_gui_save_contract.py -v`

- [ ] **Step 4: Implement worker modes and GUI state**

Replace `_blackstar_previous_blob` with `_blackstar_preview_token`. Dry-run completion displays classification, action, allocated IDs, `Knowledge changes: 0`, `Quest changes: 0`, hashes, and enables Apply. Unchecking dry run changes the button to `Apply & Save Blackstar`; without an exact token it instructs the user to preview. Apply writes in the worker and reloads the save after success; it never creates an undo entry or dirty in-memory candidate.

Any load, edit, generation change, path change, failed/cancelled operation, or checkbox mode change invalidates the token. Other mutation controls remain broad-profile-gated.

- [ ] **Step 5: Run tests and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_worker.py tests\test_gui_save_contract.py -v`

Expected: PASS.

Commit: `git commit -m "feat: add Blackstar preview and atomic apply flow"`

### Task 6: CLI, Packaging, and Documentation

**Files:**
- Modify: `CrimsonSaveEditor/blackstar_unlock.py`
- Modify: `CrimsonSaveEditor/CrimsonSaveEditor.spec`
- Modify: `tests/test_packaging_contract.py`
- Modify: `CrimsonSaveEditor/README.md`
- Modify: `BUILD_FROM_SOURCE.md`

- [ ] **Step 1: Write failing packaging/documentation contracts**

Require `blackstar_template` and `blackstar_compat` hidden imports; require docs to describe Preview then Apply & Save, feature-scoped compatibility, zero quest/knowledge changes, mandatory backup, copied-fixture dry run, and exact executable path.

- [ ] **Step 2: Update CLI and docs**

The fixture-only CLI loads the copied save, invokes feature compatibility instead of broad `require_supported_identity`, runs dry-run only, and prints classification/action/IDs/hashes without writing. Update PowerShell commands and dependency list without adding a dependency.

- [ ] **Step 3: Update PyInstaller spec and run contracts**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_packaging_contract.py -v`

Expected: PASS.

Commit: `git commit -m "docs: document safe Blackstar ownership repair"`

### Task 7: Full Verification and Windows Build

**Files:**
- Verify only; do not modify `tests/fixtures`.

- [ ] **Step 1: Record fixture hashes**

Run: `Get-FileHash -Algorithm SHA256 tests\fixtures\save.save,tests\fixtures\slot102\save.save,tests\fixtures\slot107\save.save,tests\fixtures\slot108\save.save`

Expected: hashes match `tests/conftest.py`.

- [ ] **Step 2: Run copied-fixture dry run**

Run: `.\.venv\Scripts\python.exe -m blackstar_unlock --save tests\fixtures\slot102\save.save --dry-run`

Expected: `classification_before=absent`, `action=insert`, IDs `1000003/1000004`, quest and knowledge changes `0`, no file hash change.

- [ ] **Step 3: Run full suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests -v --timeout=600`

Expected: all tests PASS.

- [ ] **Step 4: Build Windows executable**

Run from `CrimsonSaveEditor`: `..\.venv\Scripts\python.exe -m PyInstaller CrimsonSaveEditor.spec --noconfirm --clean`

Expected: exit code `0`; executable at `CrimsonSaveEditor\dist\CrimsonSaveEditorStandalone.exe`.

- [ ] **Step 5: Recheck fixture hashes and inspect git scope**

Run: `git status --short` and the Step 1 hash command.

Expected: no fixture hash changes; only intended source, tests, docs, and build outputs are present. Never stage `tests/fixtures` or `CrimsonGameMods/test`.

- [ ] **Step 6: Commit final verification adjustments if required**

Commit only source/test/doc changes with: `git commit -m "test: verify Blackstar 1.14 ownership repair"`

The user already authorized inline execution, so proceed with `superpowers:executing-plans` after plan self-review instead of requesting another execution choice.
