# Wyvern With Blackstar Attacks Design

**Status:** Approved in conversation on 2026-07-16

## Goal

Give the already summonable Wyvern Blackstar's fireball and fire-breath input
routing while preserving the Wyvern's appearance, skeleton, flight behavior,
summon-wheel entry, ride duration, and 300-second summon cooldown.

The feature modifies static game data only. It must not read, edit, back up, or
write any `save.save` or `lobby.save` file. It must not change quest flags,
knowledge entries, mount roster entries, ReserveSlot data, or the disabled
Dragon-wheel overlay.

## Confirmed 1.13.01 Evidence

The current installed `characterinfo` files were extracted read-only from PAZ
group `0008` and inspected without writing to the game directory.

| Property | Value |
| --- | --- |
| `characterinfo.pabgb` size | `26,431,477` bytes |
| `characterinfo.pabgb` SHA-256 | `c386f2c06d71990640dc394fad085740dcfc1a3de004265677130784a3025e15` |
| `characterinfo.pabgh` size | `56,842` bytes |
| `characterinfo.pabgh` SHA-256 | `eefdda23ea948c4b2d3ecb7b821d290c85fd2d5d225e800026486e8c96fbe25f` |
| DMM parse/serialize round trip | Byte-identical, zero differing bytes |

The relevant records are:

| Field | Wyvern | Blackstar |
| --- | --- | --- |
| Character key | `1004233` | `1000799` |
| Internal name | `Riding_Wyvern_1000` | `Riding_Dragon_1` |
| Vehicle type | `16975` (`Wyvern`) | `16984` (`Dragon`) |
| Upper action package | `CD_M0004_Dragon` (`0x5FA926E8`) | Same |
| Lower action package | `CD_M0004_Dragon_Lower` (`0x4D6EDB5C`) | Same |
| Gameplay/input router | `mon_wyvern` (`0x56EB1C1C`) | `mon_animal_dragon` (`0x25856D15`) |
| Summon cooldown | 300 seconds | 3,600 seconds |
| Spawn duration | Unlimited (`0`) | 600 seconds |

The common action package includes Wyvern shot/breath nodes and Blackstar
fireball/fire-breath nodes. The Blackstar router is therefore the smallest
known field that can select Blackstar's attacks without replacing the model,
skeleton, movement packages, cooldown, duration, vehicle type, or save data.

The verified in-memory candidate changes four bytes at offsets
`24,563,857` through `24,563,860` in this exact 1.13.01 body. Its SHA-256 is
`9b058198b7474044ba2bafd8d6f57b122a5952565ed6eff4eb34dac867c4736e`.
The offset is evidence, not an implementation constant; the implementation
must locate the record and field semantically on every preview.

## Expected Behavior

The first controlled test is expected to:

1. Keep `Riding_Wyvern_1000` on the existing summon wheel.
2. Keep the Wyvern appearance, Wyvern skeleton, flight movement, unlimited
   ride duration, and 300-second summon cooldown.
3. Route the existing shot input to Blackstar's fireball action.
4. Expose Blackstar's fire-breath action on the input selected by
   `mon_animal_dragon`.

Ice breath, lightning breath, and multi-attack variants are explicitly outside
this first patch. Their knowledge labels exist, but current evidence does not
prove that the gameplay-router change alone activates every variant. Missing
variants must be investigated as a separate feature after the minimal patch is
tested.

## Approaches Considered

### 1. One-field gameplay-router swap (selected)

Patch only the semantic `_characterGamePlayDataName` value on character key
`1004233` from `mon_wyvern` to `mon_animal_dragon`.

This approach has the smallest mutation surface: four bytes in one record, no
size changes, no table-header changes, and no save changes. It preserves all
verified shared action packages and all Wyvern-specific visual and summon
properties.

### 2. Surgical action-node or projectile patch

Patch individual `.paa_metabin`, projectile, or effect records. This could
preserve the Wyvern input router exactly, but the complete projectile/effect
dependency chain is not mapped. It would touch more files and introduce more
version-sensitive assumptions than the selected approach.

### 3. Full Blackstar character behavior clone

Copy Blackstar gameplay, vehicle type, cooldown, duration, model, skeleton, and
unknown lookup fields onto the Wyvern. This would effectively recreate the
unsafe Blackstar path and could break the summon wheel, flight rig, or startup.
It is rejected.

## Architecture

### Pure patch planner

A Qt-free module will accept `characterinfo.pabgb` and `characterinfo.pabgh`
bytes and return an immutable preview containing:

- source and candidate SHA-256 hashes;
- source and candidate byte counts;
- the target record key and internal name;
- the semantic field name;
- old and new router names, hashes, and record-relative offsets;
- the complete list of changed absolute byte offsets;
- compatibility and invariant results;
- whether the operation is already applied.

The planner will use `characterinfo_full_parser.parse_all_entries` to locate the
target record and semantic field. It will not perform a global replacement:
`0x56EB1C1C` occurs six times in the current body, so a global search would alter
unrelated Wyvern records.

The candidate will be built with a fixed-width little-endian `u32` replacement
at the parsed target offset. It will then be reparsed and compared against the
source. A valid candidate must differ at exactly four bytes, have the same
length, preserve the header bytes, and change no semantic field except the
target gameplay router.

### Compatibility gate

Preview and apply must refuse unknown inputs. For the initial supported profile,
all of the following must hold:

- the PAZ `0008` vanilla body and header hashes and sizes match the confirmed
  1.13.01 profile before a new candidate is planned;
- exactly one `Riding_Wyvern_1000` record with key `1004233` exists;
- exactly one `Riding_Dragon_1` record with key `1000799` exists;
- both records share upper package `0x5FA926E8` and lower package
  `0x4D6EDB5C`;
- the vanilla Wyvern router is `0x56EB1C1C` when planning a new candidate;
- the Blackstar router remains `0x25856D15`;
- Wyvern vehicle type, cooldown, duration, appearance, skeleton, and all other
  fields match their expected source values.

An already-applied state is accepted only when an owned overlay reparses with
the Wyvern router `0x25856D15`, matches the exact supported candidate hash, and
has exactly one PAPGT registration. That state is an idempotent success; it does
not relax the vanilla-profile gate for new planning. Any other source value,
hash, duplicate record, missing record, or field mismatch is a hard refusal
with a precise diagnostic. There is no force-write option.

### UI integration

Add a dedicated **Wyvern: Blackstar Attacks** safety card to the existing
FieldEdit mount area. It will expose four actions:

- **Preview / Dry Run** -- extract and analyze current game data without
  writing;
- **Apply Previewed Change** -- enabled only for the exact source fingerprint
  used by the latest successful preview;
- **Restore** -- remove only the tool-owned overlay;
- **Copy Report** -- copy the full compatibility, diff, backup, and deployment
  report.

The preview states explicitly that the expected first test is fireball plus
fire breath, while ice/lightning/multi-attack variants are not promised.

All extraction, parsing, validation, packing, and deployment work runs off the
Qt GUI thread. Progress phases are reported for extraction, compatibility,
record detection, candidate construction, validation, backup, packing,
registration, verification, and completion.

### Overlay deployment

The feature will use a dedicated collision-free overlay group selected through
the existing deployment coordinator, with a preferred group different from the
disabled `0067` Dragon-wheel overlay. It will write only:

- `characterinfo.pabgb` containing the four-byte candidate;
- the unchanged, verified `characterinfo.pabgh`.

Packing uses `crimson_rs.PackGroupBuilder` with `Compression.NONE` and
`Crypto.NONE`. The overlay is first built and re-extracted in a temporary
directory. Its extracted body and header must match the previewed candidate and
profile before any live registration occurs.

Preflight scans registered overlays. If any non-owned overlay also supplies
`characterinfo.pabgb`, deployment refuses rather than silently overriding or
discarding another mod's changes.

### Backup, transaction, and restore

Before live deployment, create a timestamped backup containing:

- the current `0.papgt`;
- any existing directory at the chosen overlay group;
- source and candidate hashes;
- the preview report;
- an ownership marker identifying this feature and profile.

Backup files are verified by size and SHA-256. Deployment writes to a temporary
sibling directory, validates it, atomically promotes the directory, and
registers the group last. A failure after mutation begins triggers automatic
rollback from the verified backup.

Restore removes only an overlay carrying this feature's ownership marker and
removes only its PAPGT registration. It preserves every foreign group and
refuses ambiguous ownership. Running Apply twice must not duplicate files,
groups, or registration entries; running Restore twice reports that nothing is
installed.

## Logging and Reports

Every operation receives an operation ID. Structured logs and the user report
include:

- game path and selected overlay group;
- source paths, sizes, and SHA-256 hashes;
- profile ID and every compatibility invariant;
- target/source record counts and package/router values;
- exact planned and actual diff offsets;
- candidate hash;
- conflicting overlay scan results;
- backup path and verification hashes;
- pack, registration, read-back, rollback, and final status.

Logs must never claim success before final read-back verifies the installed
overlay and single PAPGT registration.

## Error Handling

All errors are fail-closed and user-visible. The implementation must distinguish
unknown game data, conflicting overlays, stale previews, record ambiguity,
unexpected semantic diffs, backup failure, pack validation failure, PAPGT
registration failure, and read-back failure.

The Apply button is disabled after any source-state change or failed preview.
No broad exception handler may convert a failure into a success-shaped result.

## Testing

Tests must not contain or modify the user's real save or installed game files.
No proprietary game table is committed. Coverage will include:

1. planner refusal for unknown hashes and sizes;
2. missing and duplicate Wyvern/Blackstar records;
3. mismatched action-package or router invariants;
4. a valid plan changing exactly four target-record bytes;
5. candidate reparse and semantic-diff validation;
6. idempotent already-applied planning and deployment;
7. dry-run immutability of every source path;
8. stale-preview refusal;
9. foreign `characterinfo` overlay conflict refusal;
10. verified backup before live writes;
11. automatic rollback on each deployment boundary failure;
12. ownership-safe, idempotent restore;
13. GUI worker/progress behavior and Apply-button gating;
14. packaging of every required module;
15. source-contract tests proving the feature does not import or call save,
    quest, knowledge, ReserveSlot, or Blackstar-unlock writers;
16. an opt-in read-only installed-data test that verifies the current 1.13.01
    hashes, byte-identical DMM round trip, exact four-byte candidate, and
    candidate SHA-256 without deploying it.

## Acceptance Criteria

Implementation is ready for a controlled user test only when:

- the complete test suite and Windows build pass;
- the installed-data dry run reports the exact supported profile and four-byte
  candidate;
- Apply cannot proceed without a matching preview fingerprint;
- the backup, ownership marker, restore, and rollback paths are verified;
- the disabled Dragon-wheel Apply path remains disabled;
- no save, quest, knowledge, mount-roster, or ReserveSlot data is changed;
- the user can fully restart the game, summon the existing Wyvern, test
  fireball/fire breath, and restore the overlay if behavior is unexpected.
