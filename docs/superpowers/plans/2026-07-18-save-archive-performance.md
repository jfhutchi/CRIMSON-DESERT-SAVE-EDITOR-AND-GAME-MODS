# Save and Archive Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the confirmed redundant parsing, Python byte scans, archive I/O, slow save compression, and Python cipher fallback while preserving every compatibility, backup, rollback, and atomic-write guarantee.

**Architecture:** Save schema identity becomes one schema/TOC pass with two-class selective decoding, while full insertion contexts reuse that parsed layout rather than parsing it twice. Save transactions use exact hashes and decompressed equality instead of reparsing byte-identical backups and temporary outputs. Blackstar Timer operations share immutable inspection results, reuse source hashes, patch only the enrolled PAZ slot, and perform one combined independent integrity pass. Both duplicated application modules receive equivalent parser, serializer, compression, and crypto changes.

**Tech Stack:** Python 3.12, PySide6 6.8.3, `lz4==4.4.5`, `cryptography==49.0.0`, `crimson_rs`, pytest 9.1.1, PyInstaller 6.21.0, Windows PowerShell.

---

## File Structure

- Create `tests/test_save_performance_contract.py`: parser counts, selective decoding, transaction counts, compression configuration, and crypto-backend contracts.
- Create `tests/test_parc_fixup_performance.py`: byte-equivalence and native-search contracts for both serializer copies.
- Modify `CrimsonSaveEditor/save_parser.py`: reusable layout/result assembly and selective object decoding.
- Modify `CrimsonGameMods/save_parser.py`: keep the duplicated parser behavior identical.
- Modify `CrimsonSaveEditor/parc_inserter3.py`: build insertion contexts from one PARC layout.
- Modify `CrimsonGameMods/parc_inserter3.py`: mirror insertion-context reuse.
- Modify `CrimsonSaveEditor/save_compat.py`: single-pass, two-class schema identity.
- Modify `CrimsonSaveEditor/save_crypto.py`: optional schema detection on load, nonredundant transactions, HC3 compression, and required native ChaCha20.
- Modify `CrimsonGameMods/save_crypto.py`: HC3 compression and required native ChaCha20.
- Modify `CrimsonSaveEditor/parc_serializer.py`: C-speed sentinel search.
- Modify `CrimsonGameMods/parc_serializer.py`: identical C-speed sentinel search.
- Modify `crimson_common/blackstar_timer.py`: shared inspections, reused hashes, no unused PAZ candidate, combined verification, and hash-while-copy restore.
- Modify `tests/test_save_compat.py`: copied-fixture identity equivalence.
- Modify `tests/test_save_crypto_transaction.py`: parser-count and fail-closed transaction coverage.
- Modify `tests/test_blackstar_timer_core.py`: operation-count budgets and existing safety regression coverage.

### Task 1: Selective Single-Pass Schema Identity

**Files:**
- Create: `tests/test_save_performance_contract.py`
- Modify: `CrimsonSaveEditor/save_parser.py:1071-1123`
- Modify: `CrimsonSaveEditor/save_parser.py:1375-1422`
- Modify: `CrimsonSaveEditor/save_compat.py:46-102`
- Modify: `tests/test_save_compat.py`

- [ ] **Step 1: Write the failing selective-decoding test**

Add a test that loads a copied fixture, wraps `save_parser.decode_object_blocks`, and records the class names presented to it during a fresh identity calculation.

```python
def test_schema_identity_decodes_only_required_root_classes(
    fixture_save_path, monkeypatch
):
    save = load_save_file(str(fixture_save_path))
    observed = []
    original = save_parser.decode_object_blocks

    def record(raw, entries, types):
        observed.extend(entry.class_name for entry in entries)
        return original(raw, entries, types)

    monkeypatch.setattr(save_parser, "decode_object_blocks", record)
    compute_schema_identity(bytes(save.decompressed_blob), save.raw_header)
    assert set(observed) == {"MercenaryClanSaveData", "KnowledgeSaveData"}
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest tests/test_save_performance_contract.py::test_schema_identity_decodes_only_required_root_classes -vv`

Expected: FAIL because all TOC entries are passed to `decode_object_blocks`.

- [ ] **Step 3: Extract reusable result assembly in both parser copies**

Add a layout-aware helper and make the existing public function delegate to it. Mirror the same edit in `CrimsonGameMods/save_parser.py`.

```python
def build_result_from_layout(
    raw: bytes | bytearray,
    load_meta: dict[str, Any],
    schema: dict[str, Any],
    toc: dict[str, Any],
    *,
    object_class_names: set[str] | None = None,
    include_legacy: bool = False,
) -> dict[str, Any]:
    raw = bytes(raw)
    entries = toc["entries"]
    if object_class_names is not None:
        entries = [entry for entry in entries if entry.class_name in object_class_names]
    objects = decode_object_blocks(raw, entries, schema["types"])
    result = {
        "input": load_meta,
        "raw": {
            "size": len(raw),
            "schema_end": schema["schema_end"],
            "value_section_offset": schema["schema_end"],
            "value_section_size": len(raw) - schema["schema_end"],
        },
        "schema": {
            "header_tag": schema["header_tag"],
            "header_zero": schema["header_zero"],
            "type_count": schema["type_count"],
            "root_type": schema["root_type"],
            "types": schema["types"],
        },
        "toc": {
            "prefix_zero": toc["prefix_zero"],
            "entry_count": toc["toc_count"],
            "stream_size": toc["stream_size"],
            "entries": toc["entries"],
        },
        "objects": objects,
    }
    if include_legacy:
        type_map = classify_type_indices(schema["types"])
        character = parse_character_stats(raw, toc["entries"], type_map)
        items = scan_items(raw, toc["entries"], type_map)
        bags = scan_bag_expansion(raw, toc["entries"], type_map)
        result["character"] = character
        result["items"] = items
        result["items_summary"] = {
            "count": len(items),
            "player_count": sum(1 for item in items if item.section == 0),
            "sources": summarize_sources(items),
        }
        result["bagExpansion"] = bags
    return result
```

Make `build_result_from_raw` parse schema and TOC exactly once, then delegate to
`build_result_from_layout`. Do not change any returned key or value.

- [ ] **Step 4: Implement one-pass identity**

Replace both current parser calls in `compute_schema_identity` with one schema parse, one TOC parse, and filtered decoding.

```python
schema = save_parser.parse_schema(blob)
type_names = [item.name for item in schema["types"]]
toc = save_parser.parse_toc(blob, schema["schema_end"], type_names)
result = save_parser.build_result_from_layout(
    blob,
    {"input_kind": "schema_identity"},
    schema,
    toc,
    object_class_names={"MercenaryClanSaveData", "KnowledgeSaveData"},
)
schema_bytes = blob[0x0E:schema["schema_end"]]
root_count = struct.unpack_from("<I", blob, 0x0E)[0]
```

Build signatures from `schema["types"]`; `_type_signature` remains duck-typed over the existing field attributes.

- [ ] **Step 5: Add legacy-equivalence coverage across every copied fixture**

In the test module, retain a test-only reference using the old two-parser algorithm and compare `dataclasses.asdict()` for each `tests/fixtures/**/save.save` that loads successfully.

```python
@pytest.mark.parametrize("save_path", sorted(FIXTURE_ROOT.rglob("save.save")))
def test_optimized_identity_matches_legacy_identity(save_path):
    save = load_save_file(str(save_path))
    assert asdict(compute_schema_identity(bytes(save.decompressed_blob), save.raw_header)) == asdict(
        legacy_schema_identity(bytes(save.decompressed_blob), save.raw_header)
    )
```

- [ ] **Step 6: Run tests and commit**

Run: `python -m pytest tests/test_save_compat.py tests/test_save_performance_contract.py -k 'identity or schema' -vv`

Expected: all identity values match and only two root classes are decoded.

Commit: `perf: decode only required save identity objects`

### Task 2: Reuse Parsed Layouts in Insertion Contexts

**Files:**
- Modify: `CrimsonSaveEditor/save_parser.py`
- Modify: `CrimsonGameMods/save_parser.py`
- Modify: `CrimsonSaveEditor/parc_inserter3.py:62-71`
- Modify: `CrimsonGameMods/parc_inserter3.py:62-71`
- Modify: `tests/test_save_performance_contract.py`

- [ ] **Step 1: Write a failing no-second-layout-parse test**

```python
def test_build_insert_context_does_not_reparse_schema(fixture_save_path, monkeypatch):
    save = load_save_file(str(fixture_save_path))
    calls = 0
    original = save_parser.parse_schema

    def count(raw):
        nonlocal calls
        calls += 1
        return original(raw)

    monkeypatch.setattr(save_parser, "parse_schema", count)
    build_insert_context(save.decompressed_blob)
    assert calls == 0
```

The PARC layout parser remains the sole layout pass, so `save_parser.parse_schema` must not run.

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest tests/test_save_performance_contract.py::test_build_insert_context_does_not_reparse_schema -vv`

Expected: FAIL with `calls == 1`.

- [ ] **Step 3: Add `build_result_from_parc` to both parser copies**

Convert the already-parsed PARC entries into the existing `TocEntry` shape without reading schema or TOC bytes again.

```python
def build_result_from_parc(raw, load_meta, parc, *, object_class_names=None):
    types = parc.types
    schema = {
        "header_tag": struct.unpack_from("<H", raw, 0x0E)[0],
        "header_zero": struct.unpack_from("<H", raw, 0x10)[0],
        "type_count": len(types),
        "root_type": types[0].name if types else "",
        "types": types,
        "schema_end": parc.schema_end,
    }
    entries = [
        TocEntry(
            index=item.index,
            class_index=item.class_index,
            class_name=parc.type_by_index[item.class_index].name,
            sentinel1=item.sentinel1,
            sentinel2=item.sentinel2,
            data_offset=item.data_offset,
            data_size=item.data_size,
            entry_offset=parc.toc_offset + 12 + item.index * 20,
        )
        for item in parc.toc_entries
    ]
    toc = {
        "prefix_zero": struct.unpack_from("<I", raw, parc.toc_offset)[0],
        "toc_count": len(entries),
        "stream_size": parc.stream_size,
        "entries": entries,
    }
    return build_result_from_layout(
        raw, load_meta, schema, toc, object_class_names=object_class_names
    )
```

- [ ] **Step 4: Use the existing PARC object in both insertion-context builders**

```python
raw = bytes(blob)
parc = parc_serializer.parse_parc_blob(raw)
return ParsedInsertContext(
    raw=raw,
    parc=parc,
    result=save_parser.build_result_from_parc(
        raw, {"input_kind": "insert_context"}, parc
    ),
)
```

- [ ] **Step 5: Run Blackstar semantic tests and commit**

Run: `python -m pytest tests/test_save_performance_contract.py tests/test_blackstar_unlock.py tests/test_blackstar_knowledge.py -vv`

Expected: insertion context uses no second layout parse and Blackstar semantics remain unchanged.

Commit: `perf: reuse PARC layouts for insertion contexts`

### Task 3: Remove Redundant Transaction Re-parsing

**Files:**
- Modify: `CrimsonSaveEditor/save_crypto.py:160-243`
- Modify: `CrimsonSaveEditor/save_crypto.py:317-489`
- Modify: `tests/test_save_crypto_transaction.py`
- Modify: `tests/test_save_performance_contract.py`

- [ ] **Step 1: Write failing parser-budget tests**

After the initial copied-save load, wrap `save_compat.compute_schema_identity` and assert a normal transaction invokes it once. Patch `parc_inserter3.build_insert_context` to raise during `transactional_write_blackstar`; the scoped writer must not call it.

```python
def test_transaction_computes_candidate_identity_once(copied_save, monkeypatch):
    save = load_save_file(str(copied_save))
    calls = 0
    original = save_compat.compute_schema_identity

    def count(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(save_compat, "compute_schema_identity", count)
    transactional_write_save(
        copied_save, bytes(save.decompressed_blob), save.raw_header,
        copied_save, save.schema_identity, "parse-budget"
    )
    assert calls == 1
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m pytest tests/test_save_performance_contract.py -k 'transaction' -vv`

Expected: normal transaction reports three identity calculations and the scoped writer invokes insertion-context parsing.

- [ ] **Step 3: Make schema detection optional on internal reloads**

```python
def load_save_file(
    path: str,
    operation_id: str | None = None,
    *,
    detect_schema: bool = True,
) -> SaveData:
```

Add the keyword parameter to the existing function without changing its decrypt,
authentication, or decompression body. Initialize `identity = None` and
`profile = None`, execute the existing `compute_schema_identity`/`match_profile`
block only when `detect_schema` is true, and pass those values into the existing
`SaveData` constructor. Default behavior remains unchanged for every external
caller.

- [ ] **Step 4: Remove mathematically redundant backup and temporary identities**

Keep source and backup size/SHA equality. Delete the backup `load_save_file` call because the backup is byte-identical to the protected encrypted source. Reload the temporary save with `detect_schema=False`, then compare its decompressed SHA-256 to `edited_blob`. Candidate identity was already validated before serialization.

```python
if _sha256_file(backup_path) != source_hash:
    raise OSError("Backup SHA-256 verification failed")
```

At the existing temporary-round-trip verification point, replace the schema-aware
reload and identity comparison with:

```python
reloaded = load_save_file(str(temp_path), detect_schema=False)
if hashlib.sha256(reloaded.decompressed_blob).digest() != hashlib.sha256(edited_blob).digest():
    raise ValueError("Temporary save decompressed hash mismatch")
```

- [ ] **Step 5: Simplify scoped Blackstar write authorization**

Retain profile, normalized path, generation, source-file hash, candidate hash,
and expected schema-hash checks. Remove source reload, source-blob hash, and both
write-boundary `build_insert_context` calls because exact preview hashes already
bind those fully validated bytes.

```python
if _sha256_file(destination) != token.source_file_sha256:
    raise BlackstarCompatibilityError("Source file changed after preview")
if expected_identity.schema_sha256 != token.source_schema_sha256:
    raise BlackstarCompatibilityError("Source schema changed after preview")
if hashlib.sha256(edited_blob).hexdigest() != token.candidate_blob_sha256:
    raise BlackstarCompatibilityError("Candidate hash differs from preview")
```

- [ ] **Step 6: Run transaction, race, backup-failure, and scoped-write tests**

Run: `python -m pytest tests/test_save_crypto_transaction.py tests/test_save_performance_contract.py -k 'transaction or backup or destination or scoped' -vv`

Expected: one candidate identity, verified backups, stale-destination refusal, temporary round-trip validation, and scoped Blackstar idempotence all pass.

Commit: `perf: avoid redundant save transaction parsing`

### Task 4: Replace Bytewise Serializer Scans

**Files:**
- Create: `tests/test_parc_fixup_performance.py`
- Modify: `CrimsonSaveEditor/parc_serializer.py:224-292`
- Modify: `CrimsonGameMods/parc_serializer.py:224-292`

- [ ] **Step 1: Write the failing native-search contract and equivalence test**

Copy the current loop into a test-only `_legacy_fixup` reference. Construct deterministic shifted blocks containing valid self references, valid typed references, false sentinels, and boundary sentinels. Run both algorithms on separate byte arrays and compare exact bytes.

```python
def test_fixup_uses_native_find_and_matches_legacy():
    old_out, old_parc, entries = build_shifted_fixture()
    new_out = bytearray(old_out)
    _legacy_fixup(old_out, old_parc, entries)
    serializer._fixup_global_self_references(new_out, old_parc, entries)
    assert new_out == old_out
    source = inspect.getsource(serializer._fixup_global_self_references)
    assert ".find(sentinel" in source
    assert "out[pos:pos + 8] != sentinel" not in source
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest tests/test_parc_fixup_performance.py -vv`

Expected: byte equivalence passes but the native-search source contract fails.

- [ ] **Step 3: Implement bounded `bytearray.find` in both copies**

```python
for block_start, block_end, _ in shifted_blocks:
    search_end = max(block_start, block_end - 5)
    pos = out.find(sentinel, block_start, search_end)
    while pos >= 0 and pos < block_end - 12:
        ref_pos = pos + 8
        old_ref = struct.unpack_from("<I", out, ref_pos)[0]
        expected_old_ref = (pos - delta) + 12
        if old_ref == expected_old_ref:
            struct.pack_into("<I", out, ref_pos, old_ref + delta)
            next_start = pos + 12
        else:
            found_valid = False
            for mbc in (1, 2, 3, 4, 8):
                loc_start = pos - (mbc + 5)
                if loc_start < block_start:
                    continue
                if struct.unpack_from("<H", out, loc_start)[0] != mbc:
                    continue
                type_idx_pos = loc_start + 2 + mbc
                if type_idx_pos + 3 > pos:
                    continue
                type_idx = struct.unpack_from("<H", out, type_idx_pos)[0]
                if type_idx not in type_indices or out[type_idx_pos + 2] != 0:
                    continue
                struct.pack_into("<I", out, ref_pos, old_ref + delta)
                found_valid = True
                break
            next_start = pos + (12 if found_valid else 1)
        pos = out.find(sentinel, next_start, search_end)
```

Do not alter delta validation or accepted mask widths.

- [ ] **Step 4: Verify serializer-copy parity and Blackstar candidates**

Run: `python -m pytest tests/test_parc_fixup_performance.py tests/test_blackstar_unlock.py tests/test_blackstar_knowledge.py -vv`

Expected: legacy/new outputs are byte-identical, both serializer files expose the same function body, and copied-save Blackstar candidates retain their expected hashes.

Commit: `perf: use native sentinel search for PARC fixups`

### Task 5: Optimize Compression and Require Native ChaCha20

**Files:**
- Modify: `CrimsonSaveEditor/save_crypto.py:65-147`
- Modify: `CrimsonSaveEditor/save_crypto.py:281-310`
- Modify: `CrimsonGameMods/save_crypto.py:45-127`
- Modify: `CrimsonGameMods/save_crypto.py:209-249`
- Modify: `tests/test_save_performance_contract.py`
- Modify: `tests/test_save_crypto_transaction.py`

- [ ] **Step 1: Write failing compression and backend tests**

Wrap `lz4.block.compress` during serialization and require HC3. Assert both source modules have module-level cryptography imports and no `_chacha20_block`, `_quarter_round`, or broad fallback.

```python
def test_save_serialization_uses_balanced_hc3(fixture_save_path, monkeypatch):
    save = load_save_file(str(fixture_save_path))
    observed = {}
    original = save_crypto.lz4.block.compress

    def record(data, **kwargs):
        observed.update(kwargs)
        return original(data, **kwargs)

    monkeypatch.setattr(save_crypto.lz4.block, "compress", record)
    serialize_save_bytes(bytes(save.decompressed_blob), save.raw_header, "hc3-test")
    assert observed == {
        "store_size": False,
        "mode": "high_compression",
        "compression": 3,
    }
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m pytest tests/test_save_performance_contract.py -k 'compression or chacha' -vv`

Expected: compression is 9 and fallback helpers remain.

- [ ] **Step 3: Remove both Python cipher implementations**

At module scope in both copies:

```python
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

def chacha20_crypt(data: bytes, nonce16: bytes, key: bytes | None = None) -> bytes:
    key = KEY if key is None else key
    cipher = Cipher(algorithms.ChaCha20(key, nonce16), mode=None)
    transform = cipher.encryptor()
    return transform.update(data) + transform.finalize()
```

Delete `_rotl32`, `_quarter_round`, `_chacha20_block`, and all import-exception fallback code. A missing required dependency now fails before any file write begins.

- [ ] **Step 4: Change both save writers to HC3**

Use `mode="high_compression"`, `compression=3`, and `store_size=False`. Preserve header version, sizes, nonce, HMAC, and encryption order.

- [ ] **Step 5: Run round-trip and transaction tests**

Run: `python -m pytest tests/test_save_crypto_transaction.py tests/test_save_performance_contract.py -k 'serialization or compression or chacha or transaction' -vv`

Expected: native crypto round-trips, HC3 is observed, every save reloads exactly, and transaction safety tests pass.

Commit: `perf: use HC3 and native ChaCha20 for saves`

### Task 6: Reuse Blackstar Timer Inspections

**Files:**
- Modify: `crimson_common/blackstar_timer.py:93-157`
- Modify: `crimson_common/blackstar_timer.py:193-390`
- Modify: `tests/test_blackstar_timer_core.py`

- [ ] **Step 1: Write failing body-decompression budget tests**

Subclass the service and count `_read_body`. Preview must call it once; public token validation must call it once.

```python
class CountingTimerService(BlackstarTimerService):
    body_reads = 0

    def _read_body(self, game, entry):
        self.body_reads += 1
        return super()._read_body(game, entry)

def test_preview_decompresses_source_once(tmp_path):
    archive = make_timer_archive(tmp_path)
    service = CountingTimerService(TimerProfile(**archive.profile_kwargs()))
    preview = service.preview(archive.game_dir)
    assert preview.token is not None
    assert service.body_reads == 1
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_blackstar_timer_core.py -k 'decompresses_source_once' -vv`

Expected: Preview records two body reads.

- [ ] **Step 3: Add immutable internal inspection data**

```python
@dataclass(frozen=True)
class _ArchiveInspection:
    report: DetectionReport
    entry: dict
    body: bytes
    paths: tuple[Path, Path, Path]

def _inspect(self, game: Path) -> _ArchiveInspection:
    entry = self._find_entry(game)
    self._validate_entry(entry)
    body = self._read_body(game, entry)
    report = self._classify_body(game, entry, body)
    return _ArchiveInspection(report, entry, body, self._source_paths(game, entry))
```

`detect` returns `_inspect(game).report` while retaining its current exception-to-`UNKNOWN` behavior. Preview calls `_inspect` directly and builds its token from that body and entry.

- [ ] **Step 4: Split token validation into reusable metadata and hash phases**

```python
def _validate_token_against_inspection(self, token, inspection):
    report = inspection.report
    if report.status is not TimerStatus.VANILLA:
        raise StalePreviewError("Source archive changed after preview")
    if report.body_sha256 != token.source_body_sha256:
        raise StalePreviewError("Source archive changed after preview")
    hashes = {
        path.relative_to(token.game_dir).as_posix(): self._hash_file(path)
        for path in inspection.paths
    }
    if hashes != {item.relative_path: item.sha256 for item in token.archive_hashes}:
        raise StalePreviewError("Source archive changed after preview")
    return hashes
```

Public `validate_preview_token` performs one `_inspect` and discards the returned mapping. Apply will reuse both objects.

- [ ] **Step 5: Run detection/preview/stale-token tests and commit**

Run: `python -m pytest tests/test_blackstar_timer_core.py -k 'detect or preview or token' -vv`

Expected: all classifications remain exact, Preview is read-only, and one body read is observed.

Commit: `perf: reuse Blackstar timer archive inspections`

### Task 7: Remove Unused PAZ Candidate and Duplicate Apply Verification

**Files:**
- Modify: `crimson_common/blackstar_timer.py:392-519`
- Modify: `crimson_common/blackstar_timer.py:623-764`
- Modify: `tests/test_blackstar_timer_core.py`

- [ ] **Step 1: Write failing Apply operation-budget tests**

Extend `CountingTimerService` to count `_hash_file` and a new `_decompress_stream` seam. After Preview, reset counters and require Apply to use no more than six streaming hashes and exactly two characterinfo decompressions. Add a source contract that `_build_transaction_bytes` no longer exists.

```python
def test_apply_has_bounded_archive_work(tmp_path):
    archive = make_timer_archive(tmp_path)
    service = CountingTimerService(TimerProfile(**archive.profile_kwargs()))
    preview = service.preview(archive.game_dir)
    service.reset_counts()
    service.apply(preview.token)
    assert service.hash_calls <= 6
    assert service.decompress_calls == 2
    assert not hasattr(service, "_build_transaction_bytes")
```

- [ ] **Step 2: Run the budget test and verify RED**

Run: `python -m pytest tests/test_blackstar_timer_core.py::test_apply_has_bounded_archive_work -vv`

Expected: current Apply reports twelve hash calls, five decompressions, and the full-candidate helper exists.

- [ ] **Step 3: Create the backup before mutation without precomputed post hashes**

Change `_create_backup` to initialize `"post_apply_hashes": {}` and `"finalized": False`. It still copies and verifies all source files before returning. Apply reuses source hashes returned by token validation rather than recalculating them.

- [ ] **Step 4: Patch PAZ first, then build only metadata**

Replace `_build_transaction_bytes` with:

```python
def _build_metadata_bytes(
    self,
    game: Path,
    entry: dict,
    candidate_size: int,
    paz_checksum: int,
    paz_size: int,
) -> tuple[bytes, bytes]:
    _, pamt_path, papgt_path = self._source_paths(game, entry)
    pamt = crimson_rs.parse_pamt_file(str(pamt_path))
    target = self._find_entry_in_document(pamt)
    target["compressed_size"] = candidate_size
    chunk_id = int(target["chunk_id"])
    chunks = [item for item in pamt["chunks"] if int(item["id"]) == chunk_id]
    if len(chunks) != 1:
        raise ValueError(f"Expected one PAMT chunk {chunk_id}; found {len(chunks)}")
    chunks[0]["checksum"] = paz_checksum
    chunks[0]["size"] = paz_size
    pamt_bytes = bytearray(crimson_rs.serialize_pamt(pamt))
    struct.pack_into(
        "<I", pamt_bytes, 0, crimson_rs.calculate_checksum(bytes(pamt_bytes[12:]))
    )
    new_pamt = bytes(pamt_bytes)
    pamt_checksum = int(crimson_rs.parse_pamt_bytes(new_pamt)["checksum"])

    papgt = crimson_rs.parse_papgt_file(str(papgt_path))
    groups = [
        item
        for item in papgt["entries"]
        if str(item["group_name"]) == self.profile.group_name
    ]
    if len(groups) != 1:
        raise ValueError(
            f"Expected one PAPGT group {self.profile.group_name}; found {len(groups)}"
        )
    groups[0]["pack_meta_checksum"] = pamt_checksum
    papgt_bytes = bytearray(crimson_rs.serialize_papgt(papgt))
    struct.pack_into(
        "<I", papgt_bytes, 4, crimson_rs.calculate_checksum(bytes(papgt_bytes[12:]))
    )
    new_papgt = bytes(papgt_bytes)
    crimson_rs.parse_papgt_bytes(new_papgt)
    return new_pamt, new_papgt
```

Pass `game` or resolved paths explicitly rather than retaining global state. After the verified backup, write and `fsync` the PAZ slot. Read the resulting PAZ once, calculate its SHA-256 and Jenkins checksum, then build PAMT/PAPGT.

- [ ] **Step 5: Add one combined post-write verifier**

```python
def _verify_archive_set(self, game, expected_hashes, expected_status, expected_body_hash):
    paz_path, pamt_path, papgt_path = self._expected_paths(game)
    paz_bytes = paz_path.read_bytes()
    pamt_bytes = pamt_path.read_bytes()
    papgt_bytes = papgt_path.read_bytes()
    current = {
        paz_path.relative_to(game).as_posix(): hashlib.sha256(paz_bytes).hexdigest(),
        pamt_path.relative_to(game).as_posix(): hashlib.sha256(pamt_bytes).hexdigest(),
        papgt_path.relative_to(game).as_posix(): hashlib.sha256(papgt_bytes).hexdigest(),
    }
    if current != expected_hashes:
        raise ValueError("Post-write archive hash mismatch")
    self._verify_integrity_bytes(paz_bytes, pamt_bytes, papgt_bytes)
    report = self._detect_from_archive_bytes(game, paz_bytes, pamt_bytes)
    if report.status is not expected_status or report.body_sha256 != expected_body_hash:
        raise ValueError("Post-write body verification failed")
    return report
```

Use the returned report for `TransactionReport`; delete the final repeated `detect` call.

- [ ] **Step 6: Preserve rollback at every existing fault boundary**

Keep `wrote_source` and the current exception structure. On failure after PAZ mutation, restore all three verified backup files and prove their source hashes. Finalize the manifest only after combined verification, setting complete post hashes and timestamps.

- [ ] **Step 7: Run complete Apply, integrity, idempotence, and rollback tests**

Run: `python -m pytest tests/test_blackstar_timer_core.py -k 'apply or integrity or idempotent or rollback' -vv`

Expected: bounded operation counts, actual compressed length, checksum chain, verified backup, no-op second Apply, and every injected rollback pass.

Commit: `perf: eliminate redundant Blackstar timer apply I/O`

### Task 8: Reduce Restore Hashing Without Weakening Rollback

**Files:**
- Modify: `crimson_common/blackstar_timer.py:521-621`
- Modify: `crimson_common/blackstar_timer.py:784-846`
- Modify: `tests/test_blackstar_timer_core.py`

- [ ] **Step 1: Write a failing Restore hash-budget test**

Apply the synthetic preset, reset counters, Restore, and require at most six standalone `_hash_file` calls: three backups and three current files. Combined post-verification reads are counted separately.

```python
def test_restore_hashes_each_source_set_once(tmp_path):
    archive = make_timer_archive(tmp_path)
    service = CountingTimerService(TimerProfile(**archive.profile_kwargs()))
    preview = service.preview(archive.game_dir)
    service.apply(preview.token)
    service.reset_counts()
    service.restore(archive.game_dir)
    assert service.hash_calls <= 6
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest tests/test_blackstar_timer_core.py::test_restore_hashes_each_source_set_once -vv`

Expected: current Restore reports eighteen hash calls.

- [ ] **Step 3: Hash source bytes while copying to the temporary destination**

```python
def _copy_verified_to_temp(source: Path, destination: Path, expected: str) -> Path:
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{destination.name}.restore-", dir=destination.parent)
    digest = hashlib.sha256()
    try:
        with source.open("rb") as reader, os.fdopen(descriptor, "wb") as writer:
            for block in iter(lambda: reader.read(1024 * 1024), b""):
                digest.update(block)
                writer.write(block)
            writer.flush()
            os.fsync(writer.fileno())
        if digest.hexdigest() != expected:
            raise OSError(f"Verified restore source changed: {source}")
        shutil.copystat(source, raw_path)
        return Path(raw_path)
    except Exception:
        Path(raw_path).unlink(missing_ok=True)
        raise
```

`_restore_backup_files` uses this helper, atomically replaces each destination, and relies on the combined archive-set verifier for the independent destination readback.

- [ ] **Step 4: Reuse the combined verifier for vanilla and rollback states**

Normal Restore verifies the vanilla source hashes, integrity chain, body hash, and values once. If Restore fails, rollback uses the applied-state hashes and the same combined verifier. Preserve unsafe-path rejection and current-file conflict refusal.

- [ ] **Step 5: Run all Restore and fault-injection tests**

Run: `python -m pytest tests/test_blackstar_timer_core.py -k 'restore or unsafe or conflict or rollback' -vv`

Expected: success, unrelated-change refusal, unsafe-manifest refusal, bounded hashing, and each restore-boundary rollback pass.

Commit: `perf: verify Blackstar timer restores in one pass`

### Task 9: Benchmarks, Full Safety Suite, and Windows Builds

**Files:**
- Modify only files required by a verified failure.

- [ ] **Step 1: Record fixture hashes before verification**

Run:

```powershell
Get-ChildItem tests\fixtures -Recurse -File |
  Get-FileHash -Algorithm SHA256 |
  Sort-Object Path |
  Export-Csv $env:TEMP\crimson-fixtures-before.csv -NoTypeInformation
```

Expected: the baseline contains every copied fixture and performs no writes.

- [ ] **Step 2: Run focused performance and transaction suites**

Run:

```powershell
python -m pytest tests/test_save_performance_contract.py tests/test_parc_fixup_performance.py tests/test_save_compat.py tests/test_save_crypto_transaction.py tests/test_blackstar_timer_core.py -vv
```

Expected: all parser budgets, byte-equivalence checks, transactions, backups, fault injections, and restores pass.

- [ ] **Step 3: Benchmark identity and serialization on copied slot100**

Run the benchmark harness from the design investigation against only `tests/fixtures/slot100/save.save`, reporting median of three warm runs for identity, HC3 compression, serialization, and reload. Expected identity time is materially below the 6.96-second baseline; observed parser counts must meet the tests even when wall-clock variance is high.

- [ ] **Step 4: Run the complete tracked suite**

Run: `python -m pytest tests -q --ignore=tests/fixtures --ignore=tests/generated`

Expected: all tracked tests pass; only existing intentional skips remain.

- [ ] **Step 5: Prove copied fixtures are unchanged**

Run:

```powershell
Get-ChildItem tests\fixtures -Recurse -File |
  Get-FileHash -Algorithm SHA256 |
  Sort-Object Path |
  Export-Csv $env:TEMP\crimson-fixtures-after.csv -NoTypeInformation
Compare-Object (Import-Csv $env:TEMP\crimson-fixtures-before.csv) (Import-Csv $env:TEMP\crimson-fixtures-after.csv) -Property Path,Hash
```

Expected: `Compare-Object` produces no output.

- [ ] **Step 6: Build both executables cleanly**

Run:

```powershell
python -m PyInstaller --noconfirm --clean CrimsonSaveEditor\CrimsonSaveEditor.spec
python -m PyInstaller --noconfirm --clean CrimsonGameMods\CrimsonGameMods.spec
```

Expected:

- `CrimsonSaveEditor/dist/CrimsonSaveEditorStandalone.exe`
- `CrimsonGameMods/dist/CrimsonGameMods.exe`

- [ ] **Step 7: Smoke-test with copied data only**

Launch each built executable without selecting a real save or installed game. In Save Editor, open a temporary copy of `slot100`, save to a second temporary path, reload it, and verify the decompressed SHA-256. In both tools, run Blackstar Timer Preview/Apply/Restore only against the synthetic archive factory output copied to a temporary directory.

- [ ] **Step 8: Review and commit any final verified corrections**

For every correction, add or adjust the failing test first, observe RED, implement the smallest change, rerun focused and full suites, then commit with a defect-specific message. Run `git diff --check` and verify no fixture, generated save, backup, build directory, or executable is staged.

## Self-Review

- Spec coverage: Tasks 1-3 remove duplicate schema, object, backup, temporary, and scoped-write parsing; Task 4 replaces both bytewise fixup scans; Task 5 implements HC3 and required native crypto in both applications; Tasks 6-8 remove repeated Timer inspection, hashing, decompression, and unused PAZ construction while retaining rollback; Task 9 proves performance, safety, fixture immutability, and packaging.
- Placeholder scan: the plan contains no ellipses, deferred implementation, unspecified error handling, or unnamed tests.
- Type consistency: `build_result_from_layout`, `build_result_from_parc`, `_ArchiveInspection`, `_inspect`, `_validate_token_against_inspection`, `_build_metadata_bytes`, `_verify_archive_set`, and `_copy_verified_to_temp` keep one signature and responsibility throughout.
- Safety boundary: every mutation test uses pytest `tmp_path`, a copied save, or a synthetic PAZ group. No step authorizes access to a real save or installed Crimson Desert archive.
