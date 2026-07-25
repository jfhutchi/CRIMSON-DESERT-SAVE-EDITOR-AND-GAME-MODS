# Blackstar Unlock Safety Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the no-quest Blackstar unlock responsive, dry-runnable, idempotent, schema-gated, quest-invariant, fully logged, and safe to persist through a mandatory verified backup and atomic save transaction.

**Architecture:** Extract save compatibility, Blackstar mutation, logging, and transactional writing into Qt-free modules. Run the pure Blackstar pipeline on immutable bytes in a `QThread`, validate the candidate before applying it to GUI state, and enforce compatibility plus backup requirements again at the centralized write boundary.

**Tech Stack:** Python 3.12, PySide6 6.8.3, lz4, cryptography, pytest, PyInstaller, the repository PARC parsers, and copied encrypted fixtures under `tests/fixtures`.

---

## File Map

- Create `CrimsonSaveEditor/app_logging.py`: rotating file logging, correlation IDs, and timed phase records.
- Create `CrimsonSaveEditor/save_compat.py`: schema identities, profile manifest loading, structural checks, and write gating.
- Create `CrimsonSaveEditor/save_schema_profiles.json`: allowlisted schema/profile data generated from the copied fixture.
- Create `CrimsonSaveEditor/blackstar_unlock.py`: pure detection, planning, mount/knowledge insertion, validation, quest invariance, dry-run reports, and constants moved out of the GUI.
- Create `CrimsonSaveEditor/blackstar_worker.py`: Qt signals and `QObject` worker around the pure service.
- Modify `CrimsonSaveEditor/parc_inserter3.py`: reusable parsed insertion context, bounded sentinel iteration, detailed fixup metrics, and context-aware knowledge insertion.
- Modify `CrimsonSaveEditor/save_crypto.py`: detailed load/crypto logging, byte serialization, verified mandatory backup, temporary validation, and atomic replacement.
- Modify `CrimsonSaveEditor/models.py`: schema compatibility/document generation state and full-blob structural undo.
- Modify `CrimsonSaveEditor/gui.py`: safe button, dry-run control, worker lifecycle, stale-result guard, compatibility UI, structural undo, and centralized transactional save.
- Modify `CrimsonSaveEditor/main.py`: configure file logging before importing the GUI.
- Modify `CrimsonSaveEditor/CrimsonSaveEditor.spec`: bundle the schema manifest and hidden-import the new modules.
- Modify `CrimsonSaveEditor/requirements.txt`: retain runtime dependencies and verified pins.
- Create `CrimsonSaveEditor/requirements-dev.txt`: build and test dependencies.
- Create `tests/conftest.py`: import path, immutable fixture access, and temporary copied-save helpers.
- Create focused tests under `tests/` without staging or changing `tests/fixtures`.
- Modify `BUILD_FROM_SOURCE.md` and `CrimsonSaveEditor/README.md`: exact Windows build, test, fixture dry-run, and dependency instructions.

### Task 1: Build a fixture-safe test harness

**Files:**
- Create: `CrimsonSaveEditor/requirements-dev.txt`
- Create: `tests/conftest.py`
- Create: `tests/test_fixture_integrity.py`
- Modify: `.gitignore`

- [ ] **Step 1: Add development dependencies and local build outputs to ignore rules**

Add this complete development requirements file:

```text
-r requirements.txt
pytest
pytest-timeout
```

Append these entries to `.gitignore`:

```text
.venv/
.pytest_cache/
CrimsonSaveEditor/build/
CrimsonSaveEditor/dist/
CrimsonSaveEditor/*.spec.bak
```

- [ ] **Step 2: Create the fixture helpers**

```python
# tests/conftest.py
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / "CrimsonSaveEditor"
FIXTURES = ROOT / "tests" / "fixtures"
if str(EDITOR) not in sys.path:
    sys.path.insert(0, str(EDITOR))

SAVE_FIXTURE_SHA256 = "91ee9f4e1ed4541a488b79519d95b3136800d336267b5a2fa97a66b5b1268c13"
LOBBY_FIXTURE_SHA256 = "6885369400874a8b729e669bc0c983e11ab12020a716c58652f7d11b4f663a34"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="session")
def fixture_save_path() -> Path:
    path = FIXTURES / "save.save"
    assert sha256_file(path) == SAVE_FIXTURE_SHA256
    return path


@pytest.fixture
def copied_save(tmp_path: Path, fixture_save_path: Path) -> Path:
    destination = tmp_path / "slot-test" / "save.save"
    destination.parent.mkdir(parents=True)
    shutil.copy2(fixture_save_path, destination)
    return destination
```

- [ ] **Step 3: Add the immutable-fixture regression test**

```python
# tests/test_fixture_integrity.py
from conftest import (
    FIXTURES,
    LOBBY_FIXTURE_SHA256,
    SAVE_FIXTURE_SHA256,
    sha256_file,
)


def test_user_owned_fixtures_keep_their_original_hashes() -> None:
    assert sha256_file(FIXTURES / "save.save") == SAVE_FIXTURE_SHA256
    assert sha256_file(FIXTURES / "lobby.save") == LOBBY_FIXTURE_SHA256
```

- [ ] **Step 4: Create the isolated Python environment and run the guard test**

Run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r CrimsonSaveEditor\requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests\test_fixture_integrity.py -v
```

Expected: one passing test and unchanged fixture hashes.

- [ ] **Step 5: Commit only harness files, never fixture files**

```powershell
git add .gitignore CrimsonSaveEditor/requirements-dev.txt tests/conftest.py tests/test_fixture_integrity.py
git commit -m "test: protect copied save fixtures"
```

### Task 2: Add persistent structured logging

**Files:**
- Create: `tests/test_app_logging.py`
- Create: `CrimsonSaveEditor/app_logging.py`
- Modify: `CrimsonSaveEditor/main.py`

- [ ] **Step 1: Write the failing logging tests**

```python
# tests/test_app_logging.py
import logging
from pathlib import Path

from app_logging import configure_logging, new_operation_id, phase


def test_configure_logging_writes_rotating_utf8_file(tmp_path: Path) -> None:
    log_path = configure_logging(tmp_path)
    logging.getLogger("test").info("fixture-safe log message")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert log_path == tmp_path / "logs" / "crimson-save-editor.log"
    assert "fixture-safe log message" in log_path.read_text(encoding="utf-8")


def test_phase_logs_start_success_and_elapsed_time(tmp_path: Path, caplog) -> None:
    configure_logging(tmp_path)
    operation_id = new_operation_id("blackstar")
    with caplog.at_level(logging.INFO):
        with phase(logging.getLogger("test"), operation_id, "detection", count=1):
            pass
    text = caplog.text
    assert "phase_start" in text
    assert "phase_success" in text
    assert "elapsed_ms=" in text
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_app_logging.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'app_logging'`.

- [ ] **Step 3: Implement logging configuration and timed phases**

```python
# CrimsonSaveEditor/app_logging.py
from __future__ import annotations

import contextlib
import logging
import os
import sys
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterator

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def application_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "CrimsonSaveEditor"
    return Path.home() / ".local" / "state" / "CrimsonSaveEditor"


def configure_logging(base_dir: Path | None = None) -> Path:
    target = (base_dir or application_data_dir()) / "logs" / "crimson-save-editor.log"
    target.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    formatter = logging.Formatter(LOG_FORMAT)
    file_handler = RotatingFileHandler(
        target, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    if not getattr(sys, "frozen", False):
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        root.addHandler(console)
    return target


def new_operation_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _fields(values: dict[str, object]) -> str:
    return " ".join(f"{key}={value!r}" for key, value in sorted(values.items()))


@contextlib.contextmanager
def phase(logger: logging.Logger, operation_id: str, name: str, **fields: object) -> Iterator[None]:
    started = time.perf_counter()
    logger.info("operation=%s phase_start=%s %s", operation_id, name, _fields(fields))
    try:
        yield
    except Exception:
        logger.exception(
            "operation=%s phase_failure=%s elapsed_ms=%.1f %s",
            operation_id, name, (time.perf_counter() - started) * 1000, _fields(fields),
        )
        raise
    logger.info(
        "operation=%s phase_success=%s elapsed_ms=%.1f %s",
        operation_id, name, (time.perf_counter() - started) * 1000, _fields(fields),
    )
```

Replace `logging.basicConfig(...)` in `main.py` with:

```python
from app_logging import configure_logging

LOG_PATH = configure_logging()
logging.getLogger(__name__).info("Application logging initialized: %s", LOG_PATH)
```

- [ ] **Step 4: Run GREEN and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_app_logging.py -v`

Expected: two passing tests.

```powershell
git add CrimsonSaveEditor/app_logging.py CrimsonSaveEditor/main.py tests/test_app_logging.py
git commit -m "feat: add persistent operation logging"
```

### Task 3: Identify and gate supported save schemas

**Files:**
- Create: `tests/test_save_compat.py`
- Create: `CrimsonSaveEditor/save_compat.py`
- Create: `CrimsonSaveEditor/save_schema_profiles.json`
- Modify: `CrimsonSaveEditor/models.py`

- [ ] **Step 1: Write failing compatibility tests**

```python
# tests/test_save_compat.py
from dataclasses import replace

import pytest

from save_compat import (
    UnknownSaveSchemaError,
    compute_schema_identity,
    load_profiles,
    match_profile,
    require_supported_identity,
)
from save_crypto import load_save_file


def test_copied_fixture_matches_committed_profile(fixture_save_path) -> None:
    save = load_save_file(str(fixture_save_path))
    identity = compute_schema_identity(bytes(save.decompressed_blob), save.raw_header)
    profile = match_profile(identity, load_profiles())
    assert profile is not None
    assert profile.profile_id == "fixture-current-20260714"


def test_unknown_schema_is_read_only(fixture_save_path) -> None:
    save = load_save_file(str(fixture_save_path))
    identity = compute_schema_identity(bytes(save.decompressed_blob), save.raw_header)
    unknown = replace(identity, schema_sha256="0" * 64)
    with pytest.raises(UnknownSaveSchemaError, match="schema_sha256"):
        require_supported_identity(unknown, load_profiles())
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_save_compat.py -v`

Expected: import failure for `save_compat`.

- [ ] **Step 3: Implement immutable identity/profile types and matching**

Create `save_compat.py` with these public contracts and exact matching rules:

```python
from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path

import parc_serializer
import save_parser

REQUIRED_TYPES = (
    "MercenaryClanSaveData",
    "MercenarySaveData",
    "ExperienceLevelSaveData",
    "FriendlyDailyCountSaveData",
    "KnowledgeSaveData",
)


@dataclass(frozen=True)
class SaveSchemaIdentity:
    container_version: int
    schema_sha256: str
    root_entry_count: int
    type_count: int
    required_type_signatures: dict[str, str]
    observed_encodings: dict[str, str]


@dataclass(frozen=True)
class CompatibilityProfile:
    profile_id: str
    identity: SaveSchemaIdentity
    mount_list_prefix: int
    mount_element_mask_hex: str
    knowledge_list_prefix: int
    knowledge_element_mask_hex: str


class UnknownSaveSchemaError(ValueError):
    pass


def _type_signature(type_def) -> str:
    payload = [
        [field.name, field.type_name, field.meta_kind, field.meta_size, field.meta_aux]
        for field in type_def.fields
    ]
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()


def compute_schema_identity(blob: bytes, raw_header: bytes) -> SaveSchemaIdentity:
    parc = parc_serializer.parse_parc_blob(blob)
    result = save_parser.build_result_from_raw(blob, {"input_kind": "raw_blob"})
    by_name = {type_def.name: type_def for type_def in parc.types}
    missing = [name for name in REQUIRED_TYPES if name not in by_name]
    signatures = {
        name: _type_signature(by_name[name]) for name in REQUIRED_TYPES if name in by_name
    }
    for name in missing:
        signatures[name] = "MISSING"
    version = struct.unpack_from("<H", raw_header, 4)[0] if len(raw_header) >= 6 else 0
    encodings = extract_required_list_encodings(result)
    return SaveSchemaIdentity(
        container_version=version,
        schema_sha256=hashlib.sha256(parc.schema_bytes).hexdigest(),
        root_entry_count=parc.num_root_entries,
        type_count=len(parc.types),
        required_type_signatures=signatures,
        observed_encodings=encodings,
    )


def extract_required_list_encodings(result: dict) -> dict[str, str]:
    targets = {
        "MercenaryClanSaveData": "_mercenaryDataList",
        "KnowledgeSaveData": "_list",
    }
    encodings: dict[str, str] = {}
    objects = {obj.class_name: obj for obj in result["objects"]}
    for class_name, field_name in targets.items():
        prefix_key = f"{class_name}.{field_name}.list_prefix"
        mask_key = f"{class_name}.{field_name}.element_mask"
        obj = objects.get(class_name)
        field = next((item for item in obj.fields if item.name == field_name), None) if obj else None
        elements = field.list_elements if field and field.list_elements else []
        encodings[prefix_key] = str(field.list_prefix_u8) if field else "MISSING"
        encodings[mask_key] = (
            elements[-1].child_mask_bytes.hex()
            if elements and elements[-1].child_mask_bytes
            else "MISSING"
        )
    return encodings


def load_profiles(path: Path | None = None) -> tuple[CompatibilityProfile, ...]:
    source = path or Path(__file__).with_name("save_schema_profiles.json")
    if not source.is_file():
        return ()
    data = json.loads(source.read_text(encoding="utf-8"))
    return tuple(CompatibilityProfile(
        profile_id=item["profile_id"],
        identity=SaveSchemaIdentity(**item["identity"]),
        mount_list_prefix=item["mount_list_prefix"],
        mount_element_mask_hex=item["mount_element_mask_hex"],
        knowledge_list_prefix=item["knowledge_list_prefix"],
        knowledge_element_mask_hex=item["knowledge_element_mask_hex"],
    ) for item in data["profiles"])


def match_profile(identity, profiles):
    return next((profile for profile in profiles if profile.identity == identity), None)


def require_supported_identity(identity, profiles):
    profile = match_profile(identity, profiles)
    if profile is None:
        raise UnknownSaveSchemaError(
            f"Unknown save schema: schema_sha256={identity.schema_sha256} "
            f"container_version={identity.container_version}"
        )
    return profile
```

`extract_required_list_encodings` must locate
`MercenaryClanSaveData._mercenaryDataList` and `KnowledgeSaveData._list`, then
return their `list_prefix_u8` and last-element `child_mask_bytes.hex()` under
stable keys. Missing objects, fields, or elements are recorded as `"MISSING"`.

Add `schema_identity`, `compatibility_profile_id`, `is_schema_supported`, and
`document_generation` fields to `SaveData`. Add `previous_blob: bytes | None` to
`UndoEntry` for structural undo. At the end of `load_save_file`, compute and store
the identity, match the profile, and set the two compatibility fields so every
caller receives gated state.

- [ ] **Step 4: Generate the profile from the copied fixture without writing it**

Add a `python -m save_compat` CLI with required `--fixture`, `--profile-id`, and
`--output` arguments. It loads the fixture, computes the identity, copies the
observed mount/knowledge encodings into the profile, and writes only
`save_schema_profiles.json`. Run:

```powershell
.\.venv\Scripts\python.exe -m save_compat --fixture tests\fixtures\save.save --profile-id fixture-current-20260714 --output CrimsonSaveEditor\save_schema_profiles.json
```

Then rerun fixture hashes and confirm they match Task 1.

- [ ] **Step 5: Run GREEN and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_save_compat.py tests\test_fixture_integrity.py -v`

Expected: three passing tests.

```powershell
git add CrimsonSaveEditor/save_compat.py CrimsonSaveEditor/save_schema_profiles.json CrimsonSaveEditor/models.py tests/test_save_compat.py
git commit -m "feat: gate writes by save schema"
```

### Task 4: Make encrypted writes mandatory-backup and atomic

**Files:**
- Create: `tests/test_save_crypto_transaction.py`
- Modify: `CrimsonSaveEditor/save_crypto.py`

- [ ] **Step 1: Write failing serialization and transaction tests**

Tests must assert that `serialize_save_bytes` preserves the source header version,
round-trips the intended blob, and that `transactional_write_save` creates a
verified backup before replacing a temporary copied save. Include a backup
failure test by monkeypatching `shutil.copy2` to raise `OSError` and asserting the
destination hash remains unchanged.

Use this public API in the test:

```python
serialized = serialize_save_bytes(bytes(save.decompressed_blob), save.raw_header, "test-op")
identity = compute_schema_identity(bytes(save.decompressed_blob), save.raw_header)
result = transactional_write_save(
    destination=copied_save,
    edited_blob=bytes(save.decompressed_blob),
    original_header=save.raw_header,
    backup_source=copied_save,
    expected_identity=identity,
    operation_id="test-op",
)
assert result.backup_path.exists()
assert result.destination == copied_save
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_save_crypto_transaction.py -v`

Expected: imports fail for the new functions.

- [ ] **Step 3: Split byte serialization from filesystem writes**

Implement:

```python
@dataclass(frozen=True)
class SaveWriteResult:
    destination: Path
    backup_path: Path
    output_sha256: str
    byte_count: int


def serialize_save_bytes(edited_blob: bytes, original_header: bytes, operation_id: str) -> bytes:
    version = struct.unpack_from("<H", original_header, VERSION_OFFSET)[0]
    key = _generate_save_key(version)
    with phase(log, operation_id, "serialization", input_bytes=len(edited_blob)):
        compressed = lz4.block.compress(
            edited_blob, store_size=False, mode="high_compression", compression=9
        )
    with phase(log, operation_id, "hmac", compressed_bytes=len(compressed)):
        digest = compute_hmac(compressed, key)
    nonce = os.urandom(16)
    with phase(log, operation_id, "encryption", compressed_bytes=len(compressed)):
        encrypted = chacha20_crypt(compressed, nonce, key)
    header = bytearray(HEADER_SIZE)
    header[: min(len(original_header), HEADER_SIZE)] = original_header[:HEADER_SIZE]
    header[0:4] = b"SAVE"
    struct.pack_into("<H", header, VERSION_OFFSET, version)
    struct.pack_into("<H", header, FLAGS_OFFSET, 0x0080)
    struct.pack_into("<I", header, UNCOMP_SIZE_OFFSET, len(edited_blob))
    struct.pack_into("<I", header, PAYLOAD_SIZE_OFFSET, len(compressed))
    header[NONCE_OFFSET:NONCE_OFFSET + 16] = nonce
    header[HMAC_OFFSET:HMAC_OFFSET + 32] = digest
    return bytes(header) + encrypted


def transactional_write_save(
    destination: str | Path,
    edited_blob: bytes,
    original_header: bytes,
    backup_source: str | Path,
    expected_identity,
    operation_id: str,
) -> SaveWriteResult:
    destination = Path(destination)
    backup_source = Path(backup_source)
    profiles = load_profiles()
    require_supported_identity(expected_identity, profiles)
    candidate_identity = compute_schema_identity(edited_blob, original_header)
    if candidate_identity != expected_identity:
        raise UnknownSaveSchemaError("Edited blob schema differs from the loaded schema")

    backup_dir = backup_source.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = backup_dir / f"{backup_source.name}.{stamp}.bak"
    with phase(log, operation_id, "backup", source=backup_source, destination=backup_path):
        source_hash = _sha256_file(backup_source)
        source_size = backup_source.stat().st_size
        shutil.copy2(backup_source, backup_path)
        if backup_path.stat().st_size != source_size:
            raise OSError("Backup size verification failed")
        if _sha256_file(backup_path) != source_hash:
            raise OSError("Backup SHA-256 verification failed")
        backup_data = load_save_file(str(backup_path))
        if backup_data.schema_identity != expected_identity:
            raise UnknownSaveSchemaError("Backup schema differs from loaded schema")

    serialized = serialize_save_bytes(edited_blob, original_header, operation_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temp_path = Path(temp_name)
    try:
        with phase(log, operation_id, "temporary_write", destination=temp_path, bytes=len(serialized)):
            with os.fdopen(fd, "wb") as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
        with phase(log, operation_id, "temporary_validation", destination=temp_path):
            reloaded = load_save_file(str(temp_path))
            if hashlib.sha256(reloaded.decompressed_blob).digest() != hashlib.sha256(edited_blob).digest():
                raise ValueError("Temporary save decompressed hash mismatch")
            if reloaded.schema_identity != expected_identity:
                raise UnknownSaveSchemaError("Temporary save schema differs from loaded schema")
        with phase(log, operation_id, "final_write", destination=destination):
            os.replace(temp_path, destination)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return SaveWriteResult(
        destination=destination,
        backup_path=backup_path,
        output_sha256=_sha256_file(destination),
        byte_count=destination.stat().st_size,
    )
```

Retain `write_save_file` only as a compatibility wrapper for non-GUI callers;
make it call `serialize_save_bytes` and write a new path only. The GUI must move
to `transactional_write_save` in Task 8.

- [ ] **Step 4: Run GREEN and commit**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_save_crypto_transaction.py tests\test_fixture_integrity.py -v`

Expected: all tests pass and the copied destination, not the fixture, is replaced.

```powershell
git add CrimsonSaveEditor/save_crypto.py tests/test_save_crypto_transaction.py
git commit -m "feat: write saves transactionally"
```

### Task 5: Extract and test the pure Blackstar pipeline

**Files:**
- Create: `tests/test_blackstar_unlock.py`
- Create: `CrimsonSaveEditor/blackstar_unlock.py`
- Modify: `CrimsonSaveEditor/parc_inserter3.py`

- [ ] **Step 1: Write failing behavior tests against the copied fixture**

Cover dry-run immutability, first-run exact changes, second-run byte identity,
mount-present/knowledge-missing repair, duplicate mount refusal, duplicate
requested-knowledge refusal, canonical quest equality, ordered progress, and the
absence of any quest-insertion import or call. Build partial and duplicate inputs
in memory by calling the lower-level `build_blackstar_plan` and
`apply_blackstar_plan` with a test-specific `BlackstarSpec`; never write those
variants into `tests/fixtures`.

Use the public API:

```python
result = unlock_blackstar(
    blob=input_blob,
    profile=profile,
    dry_run=True,
    operation_id="test-blackstar",
    progress=events.append,
)
assert result.output_blob is None
assert result.candidate_sha256
assert result.report.quest_changes == 0
assert bytes(input_blob) == before
```

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_unlock.py -v --timeout=120`

Expected: import failure for `blackstar_unlock`.

- [ ] **Step 3: Add reusable insertion context and bounded sentinel search**

In `parc_inserter3.py`, add:

```python
@dataclass(frozen=True)
class ParsedInsertContext:
    raw: bytes
    parc: object
    result: dict


@dataclass(frozen=True)
class FixupMetrics:
    pointer_offsets: int = 0
    trailing_sizes: int = 0
    toc_offsets: int = 0
    block_sizes: int = 0
    stream_sizes: int = 0


def build_insert_context(blob: bytes) -> ParsedInsertContext:
    return ParsedInsertContext(
        raw=blob,
        parc=parc_serializer.parse_parc_blob(blob),
        result=save_parser.build_result_from_raw(blob, {"input_kind": "raw_blob"}),
    )


def iter_sentinels(data: bytes, start: int = 0, end: int | None = None):
    limit = len(data) if end is None else min(end, len(data))
    position = data.find(SENTINEL, start, limit)
    while position >= 0:
        yield position
        position = data.find(SENTINEL, position + len(SENTINEL), limit)
```

Refactor knowledge cloning and pointer/TOC fixups to accept a supplied context,
return `FixupMetrics`, and never call `build_result_from_raw` internally when the
context is present.

- [ ] **Step 4: Implement the service data model and canonical quest snapshot**

Move the exact no-quest `DRAGON_HEX` bytes and knowledge-key tuple from
`MainWindow._unlock_dragon_mount_no_quests` into `blackstar_unlock.py`. Define:

```python
BLACKSTAR_CHARACTER_KEY = 1000799

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


@dataclass(frozen=True)
class BlackstarSpec:
    character_key: int
    mount_template: bytes
    knowledge_keys: tuple[int, ...]
```

Add `build_blackstar_plan(context, profile, spec) -> BlackstarPlan` and
`apply_blackstar_plan(context, profile, spec, plan) -> AppliedBlackstarPlan`.
Both return immutable dataclasses, not dictionaries;
their fields are the mount count/element offsets, existing key counts, requested
missing keys, insertion fragments, absolute splice positions, containing block
indices, list-count positions, and `FixupMetrics`. Tests construct partial states
by applying
`BlackstarSpec(character_key=BLACKSTAR_CHARACTER_KEY, mount_template=BLACKSTAR_MOUNT_TEMPLATE, knowledge_keys=())`,
then run the production spec against that in-memory output.

Canonicalize each `QuestSaveData` element as nested tuples of field index, name,
type, presence, semantic `value_repr`, element masks, and child/list values. Do
not include offsets, payload locators, or pointer values.

- [ ] **Step 5: Implement plan, splice, relocate, and validation phases**

Build mount and knowledge fragments from the initial context, validate their
profile-bound masks/types, and apply planned splices from highest absolute offset
to lowest. Apply one relocation pass that maps every original absolute position
to its shifted candidate position based on all splice points. Update containing
list counts, internal element pointers, external self-pointers, containing
trailing sizes, TOC data offsets/sizes, and stream size once. Reparse only after
the candidate is complete.

The final validator must enforce:

```python
if mount_after != 1:
    raise BlackstarValidationError(f"Expected one Blackstar mount, found {mount_after}")
if duplicate_requested_knowledge:
    raise BlackstarValidationError("Duplicate requested knowledge entries detected")
if missing_requested_knowledge:
    raise BlackstarValidationError("Requested knowledge entries are still missing")
if quest_before != quest_after:
    raise BlackstarValidationError("Quest semantics changed; candidate discarded")
```

When `dry_run` is true, calculate and hash the candidate but return
`output_blob=None`. When no changes are needed, return the original hash and an
empty change report without rebuilding the blob.

- [ ] **Step 6: Run focused RED/GREEN cycles for each behavior, then the complete file**

Run the second-run test after the idempotency slice:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_unlock.py::test_second_run_is_byte_identical -v --timeout=120
```

Then run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_unlock.py tests\test_fixture_integrity.py -v --timeout=300
```

Expected: all Blackstar tests pass and fixture hashes remain unchanged.

- [ ] **Step 7: Commit**

```powershell
git add CrimsonSaveEditor/blackstar_unlock.py CrimsonSaveEditor/parc_inserter3.py tests/test_blackstar_unlock.py
git commit -m "feat: add idempotent Blackstar service"
```

### Task 6: Run Blackstar work off the GUI thread

**Files:**
- Create: `tests/test_blackstar_worker.py`
- Create: `CrimsonSaveEditor/blackstar_worker.py`

- [ ] **Step 1: Write failing signal tests**

Instantiate the worker directly, connect signal lambdas, call `run()`, and assert
ordered progress plus exactly one terminal signal. Add a cancelled-before-start
case and an exception case using an unknown compatibility profile.

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_worker.py -v --timeout=120`

Expected: import failure for `blackstar_worker`.

- [ ] **Step 3: Implement the worker**

```python
from PySide6.QtCore import QObject, Signal, Slot

from blackstar_unlock import BlackstarProgress, unlock_blackstar


class BlackstarWorker(QObject):
    progress = Signal(object)
    completed = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal()

    def __init__(self, *, blob, profile, dry_run, operation_id, generation, loaded_path):
        super().__init__()
        self._blob = bytes(blob)
        self._profile = profile
        self._dry_run = dry_run
        self._operation_id = operation_id
        self.generation = generation
        self.loaded_path = loaded_path
        self._cancel_requested = False

    @Slot()
    def request_cancel(self):
        self._cancel_requested = True

    @Slot()
    def run(self):
        if self._cancel_requested:
            self.cancelled.emit()
            return
        try:
            result = unlock_blackstar(
                blob=self._blob,
                profile=self._profile,
                dry_run=self._dry_run,
                operation_id=self._operation_id,
                progress=self.progress.emit,
                cancelled=lambda: self._cancel_requested,
            )
        except Exception as exc:
            import traceback
            self.failed.emit(str(exc), traceback.format_exc())
            return
        if self._cancel_requested:
            self.cancelled.emit()
        else:
            self.completed.emit(result)
```

- [ ] **Step 4: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_worker.py -v --timeout=120
git add CrimsonSaveEditor/blackstar_worker.py tests/test_blackstar_worker.py
git commit -m "feat: add Blackstar background worker"
```

### Task 7: Integrate compatibility, dry-run, progress, and structural undo in Qt

**Files:**
- Create: `tests/test_gui_blackstar_contract.py`
- Modify: `CrimsonSaveEditor/gui.py`
- Modify: `CrimsonSaveEditor/models.py`

- [ ] **Step 1: Write contract tests before GUI edits**

Use source/AST contract tests for this monolithic GUI to assert that the safe
button connects only to `_start_blackstar_unlock`, the safe method contains no
`insert_quest_completed`, the dry-run checkbox defaults true, the GUI constructs
a `QThread`, and stale results compare generation plus input hash before apply.

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_gui_blackstar_contract.py -v`

Expected: assertions fail because the old synchronous slot is still connected.

- [ ] **Step 3: Replace the safe button and add worker lifecycle state**

Add `QObject`, `QThread`, and `Slot` imports. In `__init__`, initialize:

```python
self._blackstar_thread = None
self._blackstar_worker = None
self._blackstar_input_hash = ""
self._blackstar_previous_blob = None
```

In the mercenary tab, retain the explicitly labeled quest-flag button, then add:

```python
self._blackstar_dry_run = QCheckBox("Dry run (no changes)")
self._blackstar_dry_run.setChecked(True)
btn_row2.addWidget(self._blackstar_dry_run)
self._blackstar_btn = QPushButton("Unlock Blackstar (No Quest Changes)")
self._blackstar_btn.clicked.connect(self._start_blackstar_unlock)
btn_row2.addWidget(self._blackstar_btn)
```

Delete `_unlock_dragon_mount_no_quests` after its exact constants move to the
service. Do not change the separate `_unlock_dragon_mount` behavior in this task.

- [ ] **Step 4: Implement start, progress, completion, error, cancellation, and cleanup slots**

`_start_blackstar_unlock` must refuse unsupported schemas, snapshot immutable
bytes, record SHA-256 and generation, create a modal 0-to-8 `QProgressDialog`,
move `BlackstarWorker` to a `QThread`, connect all signals before `thread.start()`,
and disable load/save/undo/mutation controls until cleanup. Pass
`loaded_path=self._loaded_path` to the worker constructor.

`_finish_blackstar_unlock` must discard stale results unless all three match:

```python
current = bytes(self._save_data.decompressed_blob)
if self._save_data.document_generation != worker.generation:
    return self._discard_stale_blackstar_result()
if hashlib.sha256(current).hexdigest() != self._blackstar_input_hash:
    return self._discard_stale_blackstar_result()
if self._loaded_path != worker.loaded_path:
    return self._discard_stale_blackstar_result()
```

For non-dry-run output, append `UndoEntry(description="Blackstar unlock (no quest changes)", previous_blob=current)`, replace the blob, increment generation, set dirty, and repopulate relevant views. Dry-run must only display the report.

Update `_undo` to restore `entry.previous_blob` when present before using byte
patches.

- [ ] **Step 5: Run GUI contract and service tests, then commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_gui_blackstar_contract.py tests\test_blackstar_worker.py tests\test_blackstar_unlock.py -v --timeout=300
git add CrimsonSaveEditor/gui.py CrimsonSaveEditor/models.py tests/test_gui_blackstar_contract.py
git commit -m "feat: make Blackstar unlock responsive"
```

### Task 8: Enforce compatibility and mandatory backup in the GUI write path

**Files:**
- Create: `tests/test_gui_save_contract.py`
- Modify: `CrimsonSaveEditor/gui.py`
- Modify: `CrimsonSaveEditor/save_crypto.py`

- [ ] **Step 1: Write failing GUI save contract tests**

Assert `_load_save` computes and stores compatibility state, unknown schemas set
Save/Save As and mutation controls read-only, `_do_save` contains no Yes/No backup
prompt, and `_do_save` calls `transactional_write_save` with the loaded encrypted
path as backup source for Save As.

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_gui_save_contract.py -v`

- [ ] **Step 3: Integrate load compatibility and transactional save**

During load, log file read, decryption, HMAC, decompression, schema identity, and
profile match. Set:

```python
identity = compute_schema_identity(bytes(save.decompressed_blob), save.raw_header)
profile = match_profile(identity, load_profiles())
save.schema_identity = identity
save.compatibility_profile_id = profile.profile_id if profile else ""
save.is_schema_supported = profile is not None
save.document_generation += 1
```

Unknown schemas remain inspectable but read-only and display the digest plus
changed/missing required signatures.

Replace the optional-backup branch in `_do_save` with one confirmation explaining
that a verified backup is mandatory. Call `transactional_write_save`; on success,
reload the destination header, update path/dirty state, and refresh backups. Any
backup, validation, serialization, encryption, temporary write, or replacement
error must leave the destination unchanged and show the correlation ID plus log
path.

Route `QuestEditorWindow._save_file` through the same transactional writer using
its existing encrypted `_save_path` as both destination and backup source. This
removes the second direct writer that currently bypasses `MainWindow._do_save`.

- [ ] **Step 4: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_gui_save_contract.py tests\test_save_crypto_transaction.py tests\test_save_compat.py -v --timeout=300
git add CrimsonSaveEditor/gui.py CrimsonSaveEditor/save_crypto.py tests/test_gui_save_contract.py
git commit -m "feat: enforce safe save transactions"
```

### Task 9: Package the new files and document exact Windows builds

**Files:**
- Modify: `CrimsonSaveEditor/CrimsonSaveEditor.spec`
- Modify: `CrimsonSaveEditor/requirements.txt`
- Modify: `CrimsonSaveEditor/requirements-dev.txt`
- Modify: `BUILD_FROM_SOURCE.md`
- Modify: `CrimsonSaveEditor/README.md`
- Create: `tests/test_packaging_contract.py`

- [ ] **Step 1: Write failing packaging contract tests**

Assert the spec bundles `save_schema_profiles.json`, includes hidden imports for
`app_logging`, `save_compat`, `blackstar_unlock`, and `blackstar_worker`, and the
Windows docs use `.venv\Scripts\python.exe` for install, tests, fixture-only dry
run, and PyInstaller build.

- [ ] **Step 2: Run RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_packaging_contract.py -v`

- [ ] **Step 3: Update packaging and dependency records**

Use installed, verified versions from:

```powershell
.\.venv\Scripts\python.exe -m pip freeze
```

Pin direct dependencies in `requirements.txt` and `requirements-dev.txt`. Do not
add Pillow unless PyInstaller reports a concrete missing Pillow import. Document
Python 3.12, PySide6/shiboken6, lz4, cryptography, crimson_rs, PyInstaller,
pytest, pytest-timeout, `parc_parser.dll`, every data file/directory in the spec,
and the Microsoft Visual C++ 2015-2022 x64 runtime required by the shipped native
Windows parser binaries. Verify the binaries with `dumpbin /DEPENDENTS` when the
Visual Studio tools are available; the documented runtime requirement remains
even when `dumpbin` is unavailable.

Add to `CrimsonSaveEditor.spec`:

```python
('save_schema_profiles.json', '.'),
```

and hidden imports:

```python
'app_logging',
'save_compat',
'blackstar_unlock',
'blackstar_worker',
```

- [ ] **Step 4: Add an explicit fixture-only dry-run CLI command**

Expose `python -m blackstar_unlock --dry-run --save <copied-path>` and make it
reject paths outside `tests/fixtures` or a caller-created temporary directory
unless `--allow-any-copied-path` is explicitly supplied. The documented command
must point only to a temporary copy made from `tests/fixtures/save.save`.

- [ ] **Step 5: Run GREEN and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_packaging_contract.py -v
git add CrimsonSaveEditor/CrimsonSaveEditor.spec CrimsonSaveEditor/requirements.txt CrimsonSaveEditor/requirements-dev.txt BUILD_FROM_SOURCE.md CrimsonSaveEditor/README.md tests/test_packaging_contract.py
git commit -m "docs: add verified Windows build workflow"
```

### Task 10: Verify end-to-end without touching a real save

**Files:**
- Modify only if a verification failure identifies a root cause in an already scoped file.

- [ ] **Step 1: Record fixture hashes before verification**

```powershell
Get-FileHash -Algorithm SHA256 tests\fixtures\save.save,tests\fixtures\lobby.save
```

Expected hashes are the constants in `tests/conftest.py`.

- [ ] **Step 2: Run the complete test suite**

```powershell
.\.venv\Scripts\python.exe -m pytest tests -v --timeout=600
```

Expected: zero failures, zero errors, and no writes under `tests/fixtures`.

- [ ] **Step 3: Run a CLI dry-run against a temporary copy**

```powershell
$scratch = Join-Path $env:TEMP 'crimson-blackstar-test'
New-Item -ItemType Directory -Force -Path $scratch | Out-Null
Copy-Item -LiteralPath tests\fixtures\save.save -Destination (Join-Path $scratch 'save.save') -Force
.\.venv\Scripts\python.exe -m blackstar_unlock --dry-run --save (Join-Path $scratch 'save.save') --allow-any-copied-path
```

Expected: exact mount/knowledge report, `quest_changes=0`, and no change to the
temporary encrypted file hash because dry-run never writes.

- [ ] **Step 4: Build the Windows executable**

```powershell
Push-Location CrimsonSaveEditor
..\.venv\Scripts\python.exe -m PyInstaller CrimsonSaveEditor.spec --noconfirm --clean
Pop-Location
```

Expected: exit code 0 and
`CrimsonSaveEditor\dist\CrimsonSaveEditorStandalone.exe` exists.

- [ ] **Step 5: Run post-build static and artifact checks**

```powershell
.\.venv\Scripts\python.exe -m compileall -q CrimsonSaveEditor tests
Get-FileHash -Algorithm SHA256 CrimsonSaveEditor\dist\CrimsonSaveEditorStandalone.exe
git diff --check
git status --short
Get-FileHash -Algorithm SHA256 tests\fixtures\save.save,tests\fixtures\lobby.save
```

Expected: compilation succeeds, diff check is clean, the executable has a SHA-256,
and fixture hashes are unchanged.

- [ ] **Step 6: Review the final diff against all fourteen user requirements**

Confirm the final report identifies the exact button path and root cause, schema
dependency, every modified mount/knowledge/structural field, quest behavior,
backup behavior, logging coverage, idempotency, worker progress, dry-run output,
unknown-schema refusal, dependencies/build commands, fixture-only testing, and
links to every complete modified source file.

- [ ] **Step 7: Commit verification-only corrections if any**

If verification required scoped corrections, rerun the complete commands above
before committing them. Do not create an empty verification commit.
