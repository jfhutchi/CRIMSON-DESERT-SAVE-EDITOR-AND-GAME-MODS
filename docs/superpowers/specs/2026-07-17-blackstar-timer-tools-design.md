# Blackstar Timer Tools Safety Design

**Status:** Approved in conversation on 2026-07-17

## Goal

Add the exact Blackstar timer preset that was verified successfully against
Crimson Desert 1.14 to both existing Windows applications:

- mounted duration: `600 -> 1800` seconds;
- summon cooldown: `3600 -> 1` second.

Both applications must use the same implementation, remain responsive, create
restorable backups, and refuse unknown game schemas.

## Product boundary

This project retains both existing executables:

- `CrimsonSaveEditorStandalone.exe`;
- `CrimsonGameMods.exe`.

It does not merge them. After this project, both complete user interfaces will
be redesigned as a separate project in the approved Crimson Desert visual
direction. That later redesign must retain 100 percent of the current features
in each tool plus the Blackstar work added on this branch.

The following are also outside this project:

- allowing Blackstar summoning in towns;
- changing region, field, or per-mount summon restrictions;
- accepting user-defined timer values;
- creating a PAZ overlay;
- changing save ownership, knowledge, equipment, or quest data;
- applying a broad visual refresh to only part of either application.

## User experience

### Fixed preset

The only exposed preset is `30 minute mounted time / 1 second cooldown`. The
user does not enter raw offsets or arbitrary values.

### Save Editor placement

The Save Editor places a compact `Blackstar Game Settings` group beside the
existing `Unlock Blackstar (No Quest Changes)` operation. It clearly states
that the timer preset modifies installed game archives, affects every save,
and does not change the loaded save.

### Game Mods placement

The Game Mods application exposes its existing `Game Patches` surface as a
visible bottom tab and adds a `Blackstar Timer` group there. The group uses the
same language, status model, reports, and actions as the Save Editor.

### Actions

Both surfaces provide:

1. `Preview 30m / 1s` - read-only compatibility and candidate validation;
2. `Apply Preset` - enabled only for the unchanged source that was previewed;
3. `Restore Original` - enabled only when a valid owned backup exists and the
   current files still match the corresponding applied state.

If the preset is already installed, Preview reports `Already applied` and
Apply is a harmless no-op.

### Responsiveness

Preview, Apply, and Restore run on a Qt worker thread. Progress identifies the
current phase rather than showing an indeterminate frozen window. Cancellation
is allowed during read-only scanning and candidate construction. Cancellation
is disabled after the transaction begins writing; from that point the operation
must finish verification or roll back.

## Architecture

### Shared package

A repository-level Python package named `crimson_common` contains the canonical
implementation. Both applications import and package this code. Neither GUI
contains binary offsets, compression logic, checksum logic, or backup logic.

The package contains two focused modules:

- `crimson_common/blackstar_timer.py` - profile, detection, preview token,
  backup manifest, apply transaction, restore transaction, and reports;
- `crimson_common/blackstar_timer_worker.py` - Qt signal adapter and worker
  lifecycle shared by both applications.

Each PyInstaller specification includes the repository root in `pathex` and
bundles the shared package plus the required `crimson_rs` native package. The
source entry points add the repository root only when running unfrozen from a
checkout.

### Compatibility profile

The enrolled production profile is immutable and identifies the verified 1.14
layout by structural and content evidence:

- game file: `gamedata/characterinfo.pabgb`;
- PAZ group: `0008`;
- entry offset: `2381376`;
- vanilla compressed size: `1194691`;
- uncompressed size: `26431464`;
- vanilla body SHA-256:
  `e234565b744fb1bb304547b5883cf9249c6cfff54c034c2611a87da26d8324d2`;
- applied body SHA-256:
  `c90f6689c0aa757efa702e51669be8ff9ff0ab58a4393bc220ee390903fa1402`;
- cooldown offset: `25579991`, unsigned little-endian 64-bit;
- duration offset: `25579999`, unsigned little-endian 64-bit;
- expected vanilla values: `3600` and `600`;
- preset values: `1` and `1800`.

Compatibility never relies on the offsets alone. An extracted body with an
unknown hash, unexpected size, unexpected value, ambiguous PAMT entry, or
unreadable compression is `Unknown` and remains read-only.

### Status model

The service reports one of these states:

- `VANILLA` - enrolled source is present and ready for Preview;
- `APPLIED` - the exact enrolled preset is already installed;
- `UNKNOWN` - the archive does not match an enrolled profile;
- `PARTIAL` - only some target bytes or metadata match;
- `BACKUP_CONFLICT` - an owned backup or manifest is incomplete or altered;
- `GAME_RUNNING` - Crimson Desert is open and writes are disabled.

Only `VANILLA` can produce an apply token. `APPLIED` is idempotent. All other
states refuse writes and explain the failing check.

## Preview data flow

Preview is strictly read-only:

1. Resolve and normalize the selected game directory.
2. Check whether `CrimsonDesert.exe` is running.
3. Parse `0008/0.pamt` and require exactly one characterinfo entry.
4. Read exactly the compressed length declared by PAMT.
5. Decompress to the declared uncompressed size.
6. Classify the body against the enrolled vanilla and applied hashes.
7. Verify both target fields and their widths.
8. Build the candidate in memory.
9. Recompress with pinned `lz4==4.4.5` settings and require it to fit in the
   original PAZ slot.
10. Decompress the candidate using the new compressed length and verify the
    applied body hash and values.
11. Return a report and a preview token bound to the normalized path, source
    file hashes, PAMT entry identity, profile identifier, and candidate hash.

Preview never creates directories, copies files, writes configuration, or
changes save data.

## Apply transaction

Apply performs these guarded phases:

1. Recheck that the game is closed.
2. Re-run detection and require an exact match with the preview token.
3. Build and independently verify the candidate again.
4. Create a versioned backup under
   `bin64/SEModLoad/Backups/BlackstarTimer/<timestamp>/` containing:
   - `0008/0.paz`;
   - `0008/0.pamt`;
   - `meta/0.papgt`;
   - `manifest.json` with source hashes, profile ID, paths, sizes, and the
     expected post-apply hashes.
5. Verify every backup copy before any source file is opened for writing.
6. Write the recompressed stream at the existing PAZ entry offset and pad only
   the unused slot capacity.
7. Update the characterinfo PAMT entry's compressed size to the actual new
   stream length. This step is mandatory and prevents the exact unreadable LZ4
   failure observed in the repository's old `CommunityModLoader`.
8. Recalculate the PAZ chunk checksum and size stored in PAMT.
9. Recalculate the PAMT payload checksum.
10. Update group `0008` in PAPGT with the new PAMT checksum.
11. Atomically replace the small PAMT and PAPGT metadata files.
12. Start a fresh read, reparse PAMT, read only its new compressed length,
    decompress characterinfo, and verify the candidate hash and both values.
13. Verify the PAZ -> PAMT -> PAPGT integrity chain.
14. Finalize the backup manifest and return the complete report.

Temporary metadata files are written beside their destinations and removed in
all terminal paths.

## Rollback and restore

### Automatic rollback

After backup verification, any exception or failed assertion restores all three
source files from the just-created backup. Rollback verifies the restored hashes
before re-raising the original error. A rollback failure is reported as a
critical error with both the original and rollback failures; it is never shown
as partial success.

### User restore

`Restore Original` reads an owned manifest and verifies:

- all backup files exist and match their recorded hashes;
- the selected game path matches the manifest;
- the current three files match the manifest's recorded post-apply hashes;
- the game is closed.

If another mod or game update changed any current file after this preset, Restore
refuses to overwrite it. Otherwise it restores all three originals and verifies
the vanilla profile and integrity chain.

## Logging and reports

Both tools emit the same structured phase messages for:

- game path and process check;
- PAMT lookup;
- characterinfo read and decompression;
- compatibility classification;
- source and candidate hashes;
- field values before and after;
- recompressed length and available slot capacity;
- backup creation and verification;
- PAZ write;
- PAMT compressed-size and checksum update;
- PAPGT checksum update;
- independent post-write verification;
- rollback or user restore;
- final outcome.

Normal UI text uses `game archive`; technical reports may additionally identify
PAZ, PAMT, and PAPGT paths. Reports explicitly state that no save or quest data
was changed.

## Test strategy

All automated mutation tests operate under `tmp_path` or copied fixtures. They
never use the installed game or a real save directory.

### Core tests

A test archive factory builds a small real PAZ/PAMT/PAPGT group using a compact
test profile. Tests cover:

- vanilla detection;
- unknown-body refusal;
- ambiguous-entry refusal;
- partial-byte refusal;
- preview performs no writes;
- preview token rejects changed source files;
- candidate values and body hash;
- compressed-size field changes to the actual recompressed length;
- reading the post-apply stream using the updated PAMT length successfully
  decompresses it;
- PAZ, PAMT, and PAPGT checksum agreement;
- automatic backup manifest and backup hashes;
- idempotent second Apply;
- rollback after injected failures at each write boundary;
- guarded Restore success;
- Restore refusal after unrelated post-apply modification;
- game-running refusal;
- no save or quest paths are touched.

The compressed-size regression test must fail against the current
`CommunityModLoader` behavior before the new implementation is written.

### Worker and GUI contract tests

Tests cover ordered progress, one terminal signal, cancellation before write,
disabled cancellation during the transaction, stale preview rejection, button
enablement, visible warnings that the change affects every save, and identical
report fields in both applications.

### Packaging and builds

Contract tests require both PyInstaller specs to bundle `crimson_common`,
`crimson_rs`, `lz4`, and the UI worker. Fresh Windows builds are created for
both executables. Each executable is smoke-tested against a copied synthetic
game directory, first in Preview mode and then through Apply and Restore.

### Source delivery

Tracked source, tests, documentation, and build metadata are committed on the
working `codex/` branch and pushed to the user's GitHub fork. Copied saves,
fixture directories, generated artifacts, local game backups, and visual
brainstorm files are never staged or pushed.

## Acceptance criteria

The project is complete when:

1. both current executables expose the fixed preset;
2. both call the same shared transaction implementation;
3. both stay responsive and show phase progress;
4. Preview writes nothing;
5. Apply creates and verifies a versioned three-file backup;
6. PAMT records the actual recompressed characterinfo length;
7. a fresh independent read verifies `1800` seconds and `1` second;
8. all integrity checksums agree;
9. a second Apply is a no-op;
10. Restore is guarded and verified;
11. unknown schemas and running-game states cannot write;
12. copied-fixture tests, packaging tests, and both Windows builds pass;
13. no installed game file or real save is used by the automated test suite;
14. the next project remains the complete two-UI redesign, not an executable
    merger;
15. the reviewed commits are pushed to the user's GitHub fork without local
    fixtures, generated files, or backups.
