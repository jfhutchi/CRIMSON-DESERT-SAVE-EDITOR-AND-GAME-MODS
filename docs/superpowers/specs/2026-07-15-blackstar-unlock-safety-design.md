# Blackstar Unlock Safety Design

## Objective

Harden the existing no-quest Blackstar unlock operation so it remains responsive,
is safe to repeat, provides an exact dry-run report, refuses unsupported save
schemas, preserves every quest state, logs each processing and write phase, and
cannot overwrite a save without first creating a verified backup.

The implementation and tests must use only copied saves under `tests/fixtures`.
No code, test, or manual verification step may discover, open, modify, or write a
save from the game's normal save directories.

## Existing Behavior and Root Cause

The relevant GUI path is:

1. The `Unlock Dragon (No Quest)` button is connected to
   `MainWindow._unlock_dragon_mount_no_quests` in `CrimsonSaveEditor/gui.py`.
2. The slot converts the loaded blob to bytes and calls
   `parc_serializer.parse_parc_blob` and `save_parser.build_result_from_raw`.
3. It scans the decoded `MercenaryClanSaveData._mercenaryDataList` for
   `_characterKey == 1000799`.
4. It inserts a hard-coded mount element, updates list counts, trailing sizes,
   pointer offsets, and TOC offsets.
5. It calls `parc_inserter3.inject_all_knowledge`, which parses the whole save
   again, inserts missing knowledge elements, parses again, and performs
   byte-by-byte pointer scans.
6. It replaces the in-memory decompressed blob and marks the document dirty.
   It does not write immediately; the user must invoke Save.

All of this work runs synchronously in the Qt button slot. Calls to
`QApplication.processEvents()` occur only before expensive phases, so they do not
keep the interface responsive during a parser or insertion call. Every loop on
this path is bounded by a blob, block, type, field, or list length. Missing
`MercenarySaveData`, `_mercenaryDataList`, or `KnowledgeSaveData._list`
structures cause an error return; the code does not wait for them. The observed
freeze is therefore a long synchronous GUI-thread operation, not an identified
infinite loop or missing-structure wait.

The current no-quest path does not call `insert_quest_completed`. The separate
`Unlock Dragon (Quest Flag)` action does call it for quest keys `1000354`,
`1000212`, `1000305`, and `1000319`, setting new entries to state `0x1905`.

The current Save command asks whether to make a backup and allows the user to
select No. `save_crypto.write_save_file` then opens the destination directly in
write mode. A backup is therefore not currently guaranteed, and an interrupted
write can leave a truncated destination.

## Scope

This work hardens the no-quest Blackstar path. The safe action must never call
quest insertion code and must prove that quest semantics are unchanged. The
legacy quest-completing action remains separately and explicitly labeled; it is
not routed through the safe Blackstar service.

The work also centralizes compatibility enforcement, backup creation, save
serialization, encryption, validation, and final replacement because the
requirement to refuse unknown schemas and back up before writing must be enforced
at the actual write boundary rather than only in one feature.

Unrelated inventory, equipment, game-mod, PAZ, quest-editor, and data-extraction
behavior is outside scope except where it uses the centralized save writer.

## Compatibility Identity

The encrypted save header version is a container/cryptography version and is not
a Crimson Desert gameplay schema version. Container version `2` must not be
treated as evidence that a gameplay schema is compatible.

Loading an encrypted save calculates a `SaveSchemaIdentity` containing:

- encrypted container version;
- SHA-256 of the complete PARC schema bytes;
- root-entry and type counts;
- ordered structural signatures for `MercenaryClanSaveData`,
  `MercenarySaveData`, `ExperienceLevelSaveData`,
  `FriendlyDailyCountSaveData`, and `KnowledgeSaveData`;
- field names, field types, field order, metadata kind, metadata size, metadata
  auxiliary value, and calculated bitmask width for those types;
- observed list-prefix and element-mask encodings needed by mount and knowledge
  insertion.

Supported identities live in a version-controlled compatibility manifest. The
current copied fixture supplies the first profile. The profile is named by a
neutral compatibility identifier and schema digest; it is not labeled as game
version 1.10, 1.11, or another release unless the save itself provides verified
version metadata.

An exact manifest match is required for writes. A save with an unknown identity
may be loaded for inspection and dry-run compatibility reporting, but all
mutation controls and Save/Save As remain disabled. The error shows the observed
schema digest, missing or changed structures, and the supported profile IDs.

The Blackstar template is tied to a compatibility profile. Before use, the
service validates all embedded type references and the field/list layouts that
the template assumes. It does not accept a save merely because the expected type
names are present.

## Blackstar Service

A new `CrimsonSaveEditor/blackstar_unlock.py` module owns Blackstar analysis and
mutation without importing Qt. Its public operation accepts immutable `bytes`, a
supported compatibility profile, a dry-run flag, and a progress callback. It
returns a structured `BlackstarResult` containing the input hash, optional output
blob, compatibility identity, timings, diagnostics, and an exact semantic change
report.

The service performs these bounded phases:

1. Validate the container-derived compatibility identity supplied by the loader.
2. Parse the PARC schema, TOC, and object tree once into a reusable operation
   context.
3. Detect all mount elements with `_characterKey == 1000799` and count them.
4. Collect all existing knowledge keys and identify duplicate entries.
5. Capture a canonical quest snapshot containing every decoded quest element,
   field name, presence state, and semantic value, while excluding physical byte
   offsets and self-referential pointer locations that legitimately move after
   insertion.
6. Build the exact plan: insert the mount only when its count is zero and insert
   only requested knowledge keys not already present.
7. Apply the plan to a private bytearray, including count, pointer, trailing-size,
   TOC-offset, block-size, and stream-size updates.
8. Reparse the candidate blob and validate schema identity, block boundaries,
   list counts, pointer ranges, mount count, knowledge uniqueness, and requested
   key presence.
9. Recalculate the canonical quest snapshot and fail if it differs.
10. Return the result without touching GUI-owned state.

The existing insertion helpers are refactored to accept the reusable parsed
context. They must not perform another full `build_result_from_raw` call when a
valid context is supplied. Pointer scans use structured block ranges or
`bytes.find`/`bytearray.find` with monotonically increasing positions instead of
a Python iteration over every possible byte offset.

## Idempotency and Partial States

Mount and knowledge status are evaluated independently:

- zero Blackstar mount entries: plan one mount insertion;
- one Blackstar mount entry: skip mount insertion;
- more than one Blackstar mount entry: report an invalid pre-existing duplicate
  state and refuse mutation;
- requested knowledge key absent: plan one insertion;
- requested knowledge key present once: skip it;
- requested knowledge key present more than once: report the duplicate and
  refuse mutation.

A partial prior run with one mount but missing knowledge is repaired by inserting
only the missing knowledge. A second successful run returns a zero-change result,
does not change the blob hash, and does not add any mount or knowledge entry.

## Quest Invariance

The safe Blackstar service never imports or calls `insert_quest_completed`.
Before and after candidate mutation, it computes a canonical quest snapshot from
all `QuestSaveData` entries. The snapshot includes list order, element masks,
present semantic fields, quest keys, and states. It excludes physical offsets and
pointer locator values because structural insertions can shift those values
without changing quest semantics.

Any change to the canonical quest snapshot is a hard validation failure. The
candidate blob is discarded and cannot be applied or written. The result and log
explicitly state `quest_changes=0` only after this comparison succeeds.

## Dry-Run Behavior

The mercenary tab receives a `Dry run (no changes)` checkbox that defaults to
checked. Pressing the safe Blackstar button always runs the complete service
pipeline, including in-memory insertion and final reparsing. In dry-run mode the
candidate output blob is discarded after validation and the loaded document is
not replaced, marked dirty, or added to undo history.

The dry-run report includes:

- compatibility profile ID and schema SHA-256;
- input blob SHA-256 and candidate blob SHA-256;
- existing and resulting Blackstar mount counts;
- exact knowledge keys to add and keys skipped as already present;
- pre-existing duplicate diagnostics;
- list-count and byte-growth changes;
- pointer, trailing-size, TOC-offset, block-size, and stream-size fixup counts;
- canonical quest comparison result and quest change count;
- per-phase and total elapsed time;
- confirmation that no backup, encryption, or write was attempted.

Non-dry-run mode presents the same report before replacing GUI-owned state.

## GUI Worker and Document Ownership

The GUI uses a `QObject` worker moved to a dedicated `QThread`. The worker receives
only immutable input bytes, the compatibility profile, dry-run mode, an operation
ID, and a document-generation token. It never reads or writes widgets or the
mutable `SaveData` object.

The worker emits progress for compatibility validation, Blackstar detection,
mount insertion, knowledge insertion, structural fixups, reparsing, quest
verification, and completion. A modal progress dialog displays the phase and
elapsed time. Cancellation is cooperative between bounded phases; the UI does
not attempt unsafe forced thread termination.

While a worker is active, load, save, save-as, undo, and save-mutation controls
are disabled. On completion, the GUI applies a candidate only if the loaded path,
input blob hash, and document-generation token still match. Otherwise it discards
the stale result. Window close requests while work is active offer to wait or
cancel between phases.

A successful non-dry-run operation stores a full pre-operation blob snapshot for
undo, since an empty patch list cannot undo structural insertion. Dry-run creates
no undo entry.

## Logging

Application startup configures a rotating UTF-8 file log in the platform-local
application data directory. On Windows the intended location is
`%LOCALAPPDATA%/CrimsonSaveEditor/logs/crimson-save-editor.log`. Rotation uses a
5 MiB maximum file size and retains three older files. Console logging remains
available for source runs.

Every load, Blackstar, and save transaction receives a correlation ID. Logs use
phase start, phase success, phase failure, elapsed milliseconds, input/output
sizes, schema/profile IDs, hashes, counts, key lists, and exception tracebacks.
They never include decrypted save bytes, encryption keys, HMAC keys, nonces, or
arbitrary decoded player data.

Required logged phases are:

- save file read, header validation, decryption, HMAC verification, LZ4
  decompression, schema identity, and load completion;
- Blackstar detection and duplicate counts;
- mount template validation, insertion, and structural fixups;
- knowledge detection, exact missing-key list, insertion, and duplicate checks;
- candidate serialization/structural validation and canonical quest comparison;
- save serialization, compression, HMAC generation, and encryption;
- mandatory backup source, destination, verification, and completion;
- temporary-file write, flush, reload validation, atomic replacement, and final
  write completion.

## Transactional Save Writer

Save and Save As route through one centralized transaction:

1. Refuse the transaction unless the loaded `SaveSchemaIdentity` matches a
   supported manifest profile and the current blob still validates against it.
2. Select the backup source: the existing destination for a normal Save, or the
   currently loaded encrypted source for Save As.
3. Copy the backup source to a timestamped backup path using `shutil.copy2`.
4. Verify that the backup exists, has the expected size and SHA-256, and can be
   loaded successfully. Any failure aborts before destination modification.
5. Serialize, LZ4-compress, HMAC, and encrypt the edited blob entirely before
   opening a destination-side temporary file. Preserve the supported container
   version from the loaded header; never silently normalize it to version `2`.
6. Write the temporary file in the destination directory, flush it, and call
   `os.fsync`.
7. Reload the temporary file; verify HMAC, decompressed SHA-256, supported schema
   identity, and expected edited-blob length.
8. Replace the destination with `os.replace`, preserving the verified backup.
9. Refresh the in-memory raw header, document identity, dirty state, sidebar, and
   backup list.

The UI no longer offers a No option for backup creation. If no valid encrypted
backup source exists, the writer refuses to proceed.

## Testing and Fixture Isolation

Tests use `pytest` and copy `tests/fixtures/save.save` into pytest-managed
temporary directories before any operation that can write. The fixture and its
existing backup files are treated as immutable user-owned evidence. Test setup
records their SHA-256 values, and the final suite asserts those values are
unchanged.

Required tests cover:

- the copied fixture is recognized by the committed compatibility profile;
- a changed relevant schema field produces an unknown-schema refusal;
- missing required structures produce bounded, explicit failures;
- dry-run executes full candidate validation without changing GUI/input state or
  writing files;
- first run adds at most one mount and only missing knowledge;
- second run produces no changes and an identical blob hash;
- a mount-present/knowledge-missing partial state inserts only knowledge;
- pre-existing duplicate mount or knowledge entries refuse mutation;
- canonical quest snapshots are identical before and after unlock;
- the safe path never calls quest insertion code;
- progress phases are emitted in order and worker failures return to the GUI;
- stale worker results cannot replace a newly loaded or edited document;
- unknown schemas cannot be saved;
- backup failure prevents opening or replacing the destination;
- successful writes create and verify a backup, validate a temporary encrypted
  save, and atomically replace the copied destination;
- serialization, encryption, backup, and write phases appear in the log;
- fixture SHA-256 values remain unchanged after the full suite.

Tests that need malformed or partially modified saves create those variants only
in temporary directories or in memory.

## Build Documentation and Dependencies

The implementation updates `CrimsonSaveEditor/requirements.txt`,
`BUILD_FROM_SOURCE.md`, and `CrimsonSaveEditor/README.md` so Windows instructions
use Python 3.12 from python.org, a project virtual environment, pinned direct
dependencies where the repository already requires a specific version, and an
explicit PyInstaller command.

The documented direct runtime dependencies are Python 3.12, PySide6, shiboken6
as installed with PySide6, lz4, cryptography, and crimson_rs. PyInstaller is the
build dependency and pytest is the verification dependency. The
repository-supplied `parc_parser.dll`, JSON/TSV data files, locale directory,
knowledge packs, icon, and splash assets required by `CrimsonSaveEditor.spec`
are listed as build inputs. Pillow is removed from the Save Editor instructions
because no Save Editor source imports PIL and the build uses an existing ICO and
PNG rather than converting image formats.

The final handoff includes exact PowerShell commands to create the virtual
environment, install requirements, run tests, run a fixture-only dry-run, build
with PyInstaller, locate the executable, and verify its hash.

## Planned Source Boundaries

- Create `CrimsonSaveEditor/blackstar_unlock.py` for pure analysis, planning,
  mutation, validation, and change reports.
- Create `CrimsonSaveEditor/save_compat.py` for schema identities, structural
  signatures, manifest loading, and write gating.
- Create `CrimsonSaveEditor/save_schema_profiles.json` for supported identities
  and Blackstar template compatibility metadata.
- Create `CrimsonSaveEditor/app_logging.py` for rotating application logs and
  correlation IDs.
- Modify `CrimsonSaveEditor/parc_inserter3.py` so mount/knowledge helpers can use
  one parsed context and return detailed fixup metrics.
- Modify `CrimsonSaveEditor/save_crypto.py` to separate byte serialization from
  transactional filesystem replacement and to log cryptographic phases.
- Modify `CrimsonSaveEditor/models.py` to retain schema identity and document
  generation state.
- Modify `CrimsonSaveEditor/gui.py` for the worker, progress dialog, dry-run UI,
  safe result application, compatibility state, real undo, and mandatory save
  transactions.
- Modify `CrimsonSaveEditor/main.py` to initialize file logging before GUI import.
- Modify `CrimsonSaveEditor/CrimsonSaveEditor.spec` to bundle new manifest and
  modules.
- Add focused pytest files under `tests/` while leaving `tests/fixtures` intact.
- Update build and user documentation with exact Windows dependencies and
  commands.

## Acceptance Criteria

The work is accepted when the copied fixture completes a responsive Blackstar
dry-run and non-dry-run in tests; a second run is byte-identical; canonical quest
semantics are unchanged; unknown schemas cannot be written; every real write to a
copied save has a verified backup and atomic replacement; required phases are
logged; all automated tests pass; a Windows PyInstaller build succeeds; and the
original fixture hashes are unchanged.
