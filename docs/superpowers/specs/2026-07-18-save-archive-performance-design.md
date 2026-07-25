# Save and Archive Performance Design

**Status:** Approved in conversation on 2026-07-18

## Objective

Remove four confirmed performance defects from both Crimson Desert tools without
weakening schema compatibility checks, backup verification, stale-preview
protection, atomic writes, rollback, or post-write validation. All mutation
tests use copied saves or synthetic archives. Installed game files and real save
directories are outside the test boundary.

## Confirmed Baseline

The current Blackstar save transaction performs twelve parser passes:

1. source `load_save_file`: PARC layout plus every decoded object;
2. source insertion context: PARC layout plus every decoded object;
3. candidate insertion context: PARC layout plus every decoded object;
4. candidate schema identity: PARC layout plus every decoded object;
5. verified-backup reload: PARC layout plus every decoded object;
6. temporary-output reload: PARC layout plus every decoded object.

`compute_schema_identity` alone calls both `parse_parc_blob` and
`build_result_from_raw`. The latter decodes every root object even though schema
identity observes list encodings from only `MercenaryClanSaveData` and
`KnowledgeSaveData`. On copied `slot100`, one identity calculation takes about
6.96 seconds.

Both copies of `parc_serializer._fixup_global_self_references` advance through
shifted blocks one byte at a time in Python while searching for an eight-byte
sentinel.

The current Blackstar Timer apply performs twelve archive hash operations, five
characterinfo decompressions, and creates a complete candidate PAZ byte string
that is used for hashes and metadata but is never written. Restore performs
eighteen archive hash operations. The production PAZ is roughly 119 MB and the
characterinfo body is roughly 26 MB.

Every save write uses LZ4 high-compression level 9. Copied `slot100` measured:

| Mode | Median compression time | Payload bytes |
| --- | ---: | ---: |
| HC9 | 106 ms | 1,629,103 |
| HC3 | 24 ms | 1,703,848 |
| Fast 1 | 6 ms | 1,969,171 |

HC3 is the approved balance: about 4.5 times faster than HC9 with a 4.6 percent
payload increase. Both save-crypto modules also contain a byte-at-a-time Python
ChaCha20 fallback even though `cryptography==49.0.0` is a required and bundled
dependency.

## Parser Architecture

### Schema identity

`compute_schema_identity` will use one `save_parser` layout pass:

1. parse the schema once;
2. hash the exact original schema byte range;
3. parse the TOC once;
4. filter TOC entries to `MercenaryClanSaveData` and `KnowledgeSaveData`;
5. decode only those filtered object blocks;
6. construct the existing `SaveSchemaIdentity` with byte-identical values.

Type signatures remain based on ordered field name, type, metadata kind,
metadata size, and metadata auxiliary value. Container version, root count,
type count, schema hash, list prefixes, and element masks remain unchanged.
Unknown or malformed structures continue to fail closed.

### Insertion contexts

`build_insert_context` will parse the PARC layout once and pass that layout into
the object decoder. It must not parse the schema and TOC a second time. Full
object decoding remains available where Blackstar allocation and semantic
invariance checks genuinely require it.

The duplicated parser modules in `CrimsonSaveEditor` and `CrimsonGameMods`
remain behaviorally identical after this change. Tests enforce their parity.

## Save Transaction

The broad save transaction retains these checks:

- loaded identity must be enrolled unless an explicitly scoped compatibility
  family authorizes the operation;
- the candidate identity must structurally match the loaded identity;
- the protected source must be a regular file;
- a byte-identical verified backup must exist before serialization or write;
- the destination must not change between backup and atomic replacement;
- the temporary encrypted save must decrypt and decompress to the exact
  candidate bytes;
- only a verified temporary file may replace the destination.

Redundant work is removed as follows:

- candidate identity is calculated once with the selective decoder;
- backup equality is proven by size and SHA-256, so the identical encrypted
  backup is not decrypted, decompressed, and schema-parsed again;
- temporary validation decrypts and decompresses without schema detection;
  exact decompressed equality proves that the already-validated candidate was
  serialized correctly;
- the scoped Blackstar writer trusts the exact preview-bound source-file hash,
  candidate hash, schema hash, and document generation instead of rebuilding
  source and candidate insertion contexts at the write boundary.

An exact source-file SHA-256 match is stronger than rechecking selected decoded
fields: it proves every encrypted source byte is unchanged. The candidate hash
binds the writer to the fully parsed and semantically validated preview result.

## Sentinel Fixup

The serializer will use `bytearray.find` to locate the next sentinel within each
shifted block. All existing validation after a match remains unchanged:

- self-reference arithmetic;
- mask-byte-count candidates;
- type-index membership;
- reserved byte validation;
- pointer update width and delta.

Tests compare the optimized implementation with a retained test-only reference
of the old algorithm over deterministic randomized blocks and real copied-save
candidates. Outputs must be byte-identical. Both serializer copies receive the
same implementation.

## Blackstar Timer Transaction

### Shared inspection

An internal archive inspection result will carry the normalized game path,
PAMT entry, source paths, decompressed body, body hash, timer values, and status.
Preview, token validation, and Apply reuse one inspection per phase instead of
calling `detect`, `_find_entry`, and `_read_body` repeatedly.

Preview reads and decompresses characterinfo once. Apply inspects the current
source once and performs one independent post-write inspection. A second Apply
remains an idempotent no-op.

### Source hashes and backup

Apply validates each archive hash from the preview token once and reuses that
mapping as the transaction's source hashes. It creates and verifies the
three-file backup before opening the PAZ for mutation. The initial manifest may
contain an empty post-state mapping while unfinalized; the complete post hashes
are written before finalization. Only finalized manifests are restorable.

### PAZ and metadata update

The service no longer builds a complete candidate PAZ before writing. After the
verified backup exists, it writes only the enrolled compressed slot and padding,
flushes, and calls `fsync`. It then reads the resulting PAZ once to calculate
the required PAZ checksum and SHA-256. Those values build the new PAMT and PAPGT
metadata and final manifest.

A combined post-write verifier reads each current archive once, verifies its
recorded SHA-256, validates PAZ/PAMT/PAPGT checksums, reparses metadata, extracts
the current compressed characterinfo stream, decompresses it, and verifies the
candidate body hash and both timer values. Its report is reused as the final
transaction result; no final `detect` pass repeats decompression.

### Restore

Restore keeps all ownership and conflict checks. Backup and current archive
hashes are each verified once before replacement. Copy helpers hash bytes while
copying to temporary files, compare the expected digest before replacement,
flush and `fsync`, and then atomically replace destinations. One combined
post-restore verifier proves the vanilla body and integrity chain. Failure at
any injected boundary restores the verified applied-state rollback set.

## Compression and Encryption

Both save writers use deterministic LZ4 block compression with
`mode="high_compression"`, `compression=3`, and `store_size=False`. Decompression
and header formats do not change. Round-trip tests cover all copied schema
families used by the suite.

`cryptography` becomes a module-level required dependency in both save-crypto
modules. `chacha20_crypt` delegates directly to its native ChaCha20
implementation. The Python quarter-round, block generator, per-byte XOR loop,
and broad exception fallback are removed. Missing or broken native crypto fails
closed with a clear dependency error; it never begins a save write using a slow
fallback.

## Testing and Evidence

Test-first changes must prove:

- schema identities before and after optimization are identical for every
  copied fixture;
- identity decoding visits only the two required root classes;
- a normal transaction performs one candidate identity calculation and no
  identity calculation for backup or temporary reload;
- a scoped Blackstar transaction performs no write-boundary insertion-context
  rebuild;
- serializer fixups are byte-identical to the reference algorithm;
- timer Preview, Apply, Restore, idempotency, stale-token, backup-conflict, and
  every fault-injection rollback test still pass;
- operation counters demonstrate the removal of duplicate body decompressions,
  archive hashes, and the unused full candidate archive;
- HC3 serialization round-trips through the game-compatible container parser;
- ChaCha20 matches known vectors and ciphertext round-trips through the native
  backend;
- backup failure and temporary validation failure leave the destination
  untouched;
- fixture SHA-256 values are unchanged after all tests.

Benchmarks use `tests/fixtures/slot100/save.save` and pytest temporary copies.
No benchmark or test opens the installed game's archive or real save folder.

## Acceptance Criteria

The change is complete when all four reported findings are removed from both
applications, all safety and rollback tests pass, the complete test suite is
green, copied fixtures retain their original hashes, parser and archive-I/O
counters prove the reduced work, performance measurements improve materially,
and both Windows executables build and launch successfully.
