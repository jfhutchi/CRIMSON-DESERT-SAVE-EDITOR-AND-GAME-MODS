# Dragon Summon Wheel Compatibility Design

## Purpose

Add a narrowly scoped, reversible Crimson Game Mods operation that makes the
Dragon vehicle category available from the normal F1 mount wheel. The feature
must support the user's currently installed ReserveSlot schema, refuse unknown
schemas, preview every semantic change, and never modify a save file or quest
state.

## Context

The existing `ReserveSlotTab` is not registered in `gui/main_window.py`. It also
cannot safely be exposed as written:

- the tab imports the legacy root `reserveslot_parser.py`;
- that parser reads the current 4,091-byte `reserveslot.pabgb` but serializes it
  as 3,696 bytes;
- the newer `gui/reserveslot_parser.py` fails to parse the final current-format
  entry;
- the newer parser drops trailing data during serialization; and
- its `roundtrip_test` returns success when parsing yields entries instead of
  requiring byte-identical output.

The existing broad "All Mounts Everywhere" editor is therefore out of scope
until the complete current ReserveSlot schema is understood and round-trippable.

A read-only extraction of the user's installed game files established a
supported current profile:

- `reserveslot.pabgh`: 242 bytes, 30 entries, SHA-256
  `d4e041a8c744e4bc2585ff09b75df20e0d06d20d300ace25fb15ddac8baadcd3`;
- `reserveslot.pabgb`: 4,091 bytes, SHA-256
  `292b384a5a9e16d24c59a5cc44fe9b1aca835eec870c54e703f870b2a9682938`;
- normal `VehicleSlot`: key `1000006`, record index 26, category bytes
  `[0x4E, 0x51]`;
- `VehicleSlot_Dragon`: key `1000020`, category bytes `[0x4F]`; and
- the normal slot category count and bytes occur once at target-record relative
  offset 81 as `02 00 00 00 4E 51`.

The target mutation produces:

- `reserveslot.pabgh`: 242 bytes, SHA-256
  `18304bd6b0692427a39775258f77900f498305f57e1a45662c175548d378fd64`;
- `reserveslot.pabgb`: 4,092 bytes, SHA-256
  `09dbcf9ace932ca1df39d2c06d862958453e018f358fcc6cf987186746200d64`;
- normal `VehicleSlot` categories `[0x4E, 0x4F, 0x51]`; and
- PABGH data offsets for entries 27 through 29 increased by exactly one.

Removing `0x4F`, restoring the count, and decrementing those offsets has been
verified in memory to reproduce both original files byte-for-byte. No installed
game file was written during this analysis.

## Chosen Approach

Implement a focused opaque-record patcher instead of repairing or exposing the
entire ReserveSlot editor.

The patcher treats every non-target byte as opaque. It parses only the PABGH
index and the minimum target-record structure needed to identify and update the
normal vehicle category list. This avoids reserializing unrelated records whose
new schema remains unknown.

Alternatives rejected for this iteration:

1. Expose the legacy full editor. Rejected because both available serializers
   fail current-format round-trip validation.
2. Fully reverse-engineer all 30 current entries. Deferred because only one
   bounded record needs to change, and full parsing would increase both scope
   and corruption risk.
3. Enable every vehicle category. Rejected because it changes unrelated mount,
   mechanic, and vehicle behavior.

## Pure Patch Service

Create `CrimsonGameMods/dragon_wheel_patch.py` as a Qt-free module.

The module owns:

- `ReserveSlotCompatibilityError` for all refusal conditions;
- a frozen compatibility profile containing the supported original and patched
  hashes, entry count, target key, target record index, record name, category
  signatures, and expected output hashes;
- `DragonWheelReport` describing schema id, original/patched state, hashes,
  category values, byte growth, and adjusted entry offsets;
- `analyze_reserveslot(pabgh, pabgb)` for read-only compatibility and state
  detection; and
- `enable_dragon_category(pabgh, pabgb)` for the idempotent candidate build.

Compatibility validation must require all of the following:

1. PABGH length equals `2 + entry_count * 8`.
2. PABGH keys and offsets are readable, ordered, in range, and identify target
   key `1000006` at index 26.
3. The target record's embedded key and UTF-8 name are exactly `1000006` and
   `VehicleSlot`.
4. The input hashes equal either the supported original pair or the supported
   patched pair.
5. The expected category signature occurs exactly once inside the target
   record and never crosses its boundary.
6. Original input contains `[0x4E, 0x51]`; already-patched input contains
   `[0x4E, 0x4F, 0x51]`.

Any mismatch raises `ReserveSlotCompatibilityError`. There is no permissive or
best-effort write path.

The candidate builder must:

1. Return the original bytes unchanged when `0x4F` is already present.
2. Change the category count from 2 to 3.
3. Insert `0x4F` between `0x4E` and `0x51`.
4. Increase only the PABGH offsets after the target record by one.
5. Verify the exact expected patched hashes.
6. Verify the semantic report shows only the Dragon category addition.
7. Run an inverse check that removes the addition and reproduces the original
   bytes exactly before returning the candidate.

## User Interface

Replace the unsafe dormant ReserveSlot editing surface with a focused
`ReserveSlotTab` registered in the Game Mods tab bar as `Dragon Wheel`.

The tab contains:

- `Analyze Game Files`, which extracts the two vanilla ReserveSlot files and
  displays their schema, hashes, current categories, and compatibility result;
- `Preview Dragon Wheel Patch`, which builds and validates the candidate only
  in memory and reports the exact category and offset changes;
- `Apply Dragon Wheel Patch`, disabled until a successful preview for the same
  source hashes;
- the fixed Dragon-only overlay group 0067 (0066 is reserved for ItemBuffs); and
- `Restore Dragon Wheel Patch`, which removes only an overlay carrying this
  feature's ownership marker.

The tab must clearly state that it modifies game data, requires a full game
restart, does not edit saves, and does not change quests. It must not expose the
legacy manual checkboxes or broad all-mount preset.

The main window must import and instantiate `ReserveSlotTab`, connect its status
and config signals, add it to `_mods_tabs`, and propagate game-path changes.

## Apply Transaction

Apply is permitted only after a preview whose source hashes still match a fresh
read-only extraction.

The transaction is:

1. Re-extract and revalidate the supported source bytes.
2. Rebuild the same in-memory candidate and compare it with the preview hashes.
3. Require the dedicated 0067 overlay group. Never overwrite an unmarked
   directory or a group owned by another tool, and never use ItemBuffs group
   0066.
4. Build `reserveslot.pabgb` and `reserveslot.pabgh` into a temporary PAZ group.
5. Validate the generated PAMT checksum before touching the game directory.
6. Create a timestamped backup directory next to the executable under
   `backups/dragon-wheel/<timestamp>/` containing the current `meta/0.papgt`
   and, when updating an owned overlay, its complete overlay directory.
7. Copy the new overlay into place with an ownership marker
   `.se_dragon_wheel` containing schema id and source/candidate hashes.
8. Update a temporary copy of PAPGT, parse it back, verify all pre-existing
   groups remain, and atomically replace the live PAPGT.
9. Record overlay ownership through `overlay_coordinator.post_write`.

If any step fails after filesystem mutation starts, restore PAPGT and the owned
overlay from the transaction backup. A failed operation must not display a
success message.

## Restore

Restore must refuse unless overlay 0067 contains `.se_dragon_wheel` and
the shared state does not identify another owner.

Restore removes only that overlay's PAPGT entry and directory while preserving
every other PAPGT entry. It calls `overlay_coordinator.post_restore` after the
filesystem and PAPGT changes succeed. The timestamped backup remains available
for manual recovery.

## Logging

Log source hashes, schema decision, analysis result, preview candidate hashes,
fixed overlay group, backup path, PAZ build result, PAPGT verification,
rollback, restore, and final success. Do not log arbitrary game-file contents.

## Testing

Tests use generated synthetic byte fixtures and injected compatibility profiles;
they do not commit proprietary game data.

Automated tests must cover:

- supported original analysis;
- unknown hash refusal;
- malformed PABGH header, offsets, target key, name, and duplicate signature
  refusal;
- exact Dragon-only candidate mutation;
- offsets after the target increasing by one and earlier offsets remaining
  unchanged;
- second-run byte identity;
- exact inverse reconstruction;
- stale-preview refusal;
- apply refusal for an occupied unmarked overlay;
- backup creation before write;
- PAPGT preservation and rollback on simulated failure;
- restore ownership checks;
- main-window registration and game-path propagation; and
- PyInstaller inclusion of the tab and pure patch service.

A local read-only integration test must extract the user's installed files,
verify the documented original hashes, build the candidate in memory, confirm
the documented patched hashes, and confirm inverse byte identity. It must never
call the apply transaction.

## Acceptance Criteria

- The existing Save Editor and all quest data remain untouched.
- Unknown or updated ReserveSlot schemas cannot reach a write call.
- Preview reports the single category addition and three adjusted offsets.
- Applying creates a verified backup before any live mutation.
- Reapplying is idempotent.
- Restore removes only the marked Dragon Wheel overlay.
- The packaged `CrimsonGameMods.exe` visibly includes the `Dragon Wheel` tab.
- All automated tests and the read-only installed-file integration check pass.
