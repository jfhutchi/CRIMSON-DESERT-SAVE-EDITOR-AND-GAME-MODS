# Blackstar 1.14 Ownership Repair Design

## Objective

Replace the obsolete 206-byte Blackstar insertion with a fail-closed operation
derived from a legitimate Crimson Desert 1.14 cross-save. The operation must add
or repair Blackstar ownership without changing quests, knowledge, inventory,
world state, or summon runtime lists. It must remain responsive, support an
exact dry run, create a verified backup before a write, and be idempotent.

All development and verification use only copied saves under `tests/fixtures`
or pytest-managed temporary directories. Codex must never open or modify the
game's real save directory.

## Evidence

Three copied saves establish the behavior:

| Fixture | State | Relevant evidence |
| --- | --- | --- |
| `slot102` | Early-game, no Blackstar or Wyvern | 20 mercenary records; content-dependent 96-type schema; every required Blackstar nested type is present |
| `slot107` | Completed game, legitimate Blackstar idle, Wyvern summoned | one 437-byte Blackstar ownership record; no Blackstar cooldown or duration entry |
| `slot108` | Same lineage as `slot107`, Blackstar and Wyvern summoned | Blackstar record grows to 454 bytes; exactly one cooldown and one duration entry appear; Wyvern is semantically unchanged |

The seven types touched by a legitimate ownership record have identical ordered
field signatures in the early and completed saves:

- `MercenaryClanSaveData`
- `MercenarySaveData`
- `ExperienceLevelSaveData`
- `FriendlyDailyCountSaveData`
- `ItemSaveData`
- `ItemSocketSaveData`
- `KnowledgeSaveData`

The legitimate idle Blackstar record has:

- `_characterKey = 1000799`;
- a save-local, unique `_mercenaryNo`;
- `_ownedCharacterKey` copied from the target save's active primary mount;
- the standard empty `ExperienceLevelSaveData` nested objects;
- target-derived `_lastPaidTime` and `_lastBreedingTime`;
- target-derived spawn position, yaw, and field;
- `_isMainMercenary = true`;
- `_isInitialize = true`;
- one equipped item with `_itemKey = 1002269`, a unique save-local `_itemNo`,
  five empty sockets, and the legitimate static item fields;
- `_occupationState = 1`;
- no `_lastSummoned`, `_currentHp`, or `_currentMp` field while idle.

Summoning Blackstar changes only the ownership record's runtime fields and adds
runtime list entries:

- idle record mask `0d19003e0a00` becomes active mask `0d19003f0a06`;
- `_lastSummoned = true` appears;
- `_currentHp` and `_currentMp` appear;
- spawn position and yaw update;
- `CallMercenaryCoolTimeSaveData` references the Blackstar mercenary number;
- `CallMercenarySpawnDurationSaveData` references the same mercenary number and
  vehicle key `16984`.

The `slot107`/`slot108` knowledge trees are byte-semantically identical. Their
mission lists are identical. The only quest-stage differences are repeating
weather stages, caused by runtime weather progression rather than Blackstar.
The earlier non-Blackstar PC fixture already contains key `1000799` in quest,
mission, knowledge, and follow-knowledge structures and already contains all
eleven attack-knowledge keys. Those keys are not ownership signals.

## Root Cause Being Replaced

The existing service inserts a hard-coded 206-byte record from an obsolete
layout and injects a broad knowledge list. When decoded against the current
field layout, that record contains `mercenaryNo=1017`, no owner, no equipment,
no main-mount flag, invalid-looking spawn/HP values, and initially
`isInitialize=false`. The game may preserve or partially normalize the record,
but it does not become legitimate Blackstar ownership and does not appear on the
summon wheel.

This is not a missing quest flag and not merely a wheel-category problem. The
ownership record itself is obsolete.

## Scope

This design changes only the safe no-quest Blackstar operation. It removes all
knowledge insertion from that operation. It does not change the separately
labeled quest-completion action.

The operation supports:

1. inserting Blackstar when no Blackstar record exists;
2. replacing exactly one recognized legacy 206-byte Blackstar record;
3. reporting no changes for exactly one legitimate idle or active Blackstar;
4. refusing duplicates or an unrecognized Blackstar-shaped record.

Wyvern attack replacement and PAZ overlays are separate work. No game files,
ReserveSlot categories, summon-wheel overlays, or quest flags are modified.

## Content-Scoped Compatibility

The complete PARC schema is content-dependent. The copied 1.14 saves contain
96, 109, and 111 types, while their touched Blackstar type signatures match.
Therefore a complete-schema SHA-256 is suitable for broad editor-write profiles
but is too narrow to describe this single operation.

Blackstar receives a feature-scoped compatibility family containing:

- container version `2`;
- root entry count `15`;
- exact ordered signatures for the seven touched types listed above;
- exact `MercenaryClanSaveData._mercenaryDataList` prefix and mask width;
- exact list and nested-object encodings used by the legitimate template;
- the legitimate normalized template SHA-256 and source type-index manifest;
- required root objects and the required primary-mount reference fields.

Missing types, changed fields, unexpected metadata, unsupported mask widths,
missing primary-mount state, or ambiguous reference mounts cause a bounded
compatibility error. This feature-scoped approval does not enable inventory,
quest, general Save/Save As, or any other mutation on an otherwise unknown full
schema.

## Normalized Template

`blackstar_template.py` owns an immutable, normalized idle ownership template.
It is derived from the legitimate 437-byte record but contains no source-save
identifier, timestamp, or position:

- mercenary and item instance numbers are placeholders;
- owner, paid/breeding times, spawn position, yaw, and field are placeholders;
- Blackstar character key, item key, masks, booleans, occupation state, socket
  structure, and other static item bytes remain fixed;
- every embedded source type index maps to an expected type name.

Materialization translates every embedded type index by name into the target
schema, patches every pointer locator relative to the target insertion offset,
and patches dynamic values only through named offsets verified by reparsing the
template. No raw offset from a user save is hard-coded as a target location.

## Target-Derived Values

The planner derives dynamic fields before mutation:

1. Collect every nonzero, non-`UINT64_MAX` `MercenaryNo` and `ItemNo` value.
2. Treat those two declared types as one collision domain. Allocate the next two
   consecutive values above the maximum: mercenary number first, equipment item
   number second. Refuse overflow or any post-allocation collision.
3. Find primary-mount candidates with a present owner key, main flag,
   initialized flag, spawn position, yaw, and field. Prefer a unique Kliff horse
   record (`_characterKey = 1003120`), then a unique `_lastSummoned=true`
   candidate, then a sole remaining candidate. Refuse ambiguity at every tier.
4. Copy `_ownedCharacterKey`, spawn position, yaw, and field from that target
   reference record.
5. Set both paid/breeding timestamps to the greatest present paid or breeding
   timestamp in the target mercenary list. Use zero only when neither field is
   present anywhere.

These rules are deterministic and contain no completed-save identifiers or
coordinates. The early fixture is expected to allocate mercenary/item numbers
`1000003` and `1000004` because `1000002` is its greatest live instance number.

## Classification and Idempotency

Every Blackstar record is classified semantically after parsing:

- `absent`: no `_characterKey == 1000799` record;
- `legacy`: exactly one record matching the complete obsolete 206-byte semantic
  fingerprint and containing no legitimate Blackstar equipment;
- `legitimate_idle`: exactly one validated 437-byte-equivalent ownership tree;
- `legitimate_active`: exactly one validated active ownership tree plus
  consistent runtime references when those lists are present;
- `unknown`: one record that matches the character key but not a known state;
- `duplicate`: more than one matching character key.

`absent` inserts one normalized idle record. `legacy` replaces the old element
at its existing list index and leaves the list count unchanged. Legitimate
states return a zero-change result with an identical blob hash. Unknown and
duplicate states refuse mutation. A second successful invocation must be
byte-identical.

Legacy recognition uses the full decoded field set, mask, length, and known
static values. It never replaces an arbitrary record solely because it has the
Blackstar character key. Repair also requires that the legacy mercenary number
has no cooldown, duration, or other external `MercenaryNo` reference. A legacy
record with external runtime state is refused rather than leaving stale
references.

## Mutation Boundaries

Insertion and replacement operate on a private byte array. They update only:

- one mercenary list element;
- the mercenary list count for insertion only;
- owning block and stream sizes;
- affected pointer locators and TOC offsets.

The operation does not add cooldown or duration records. The game creates those
when Blackstar is summoned. It does not add or change knowledge, quest, mission,
inventory, equipment-root, ReserveSlot, or alert-history entries.

Before and after mutation, the service creates canonical semantic snapshots.
All root objects except `MercenaryClanSaveData` must be identical. Inside
`MercenaryClanSaveData`, all fields except `_mercenaryDataList` must be
identical. The mercenary list must differ only by the planned insert or legacy
replacement. Physical offsets and pointer locator targets are excluded from the
semantic comparison.

The candidate is reparsed and must prove:

- unchanged schema bytes, type count, and root count;
- exactly one legitimate Blackstar record;
- unique allocated instance numbers;
- correct owner, static item key, socket count, flags, and occupation state;
- no Blackstar cooldown or duration insertion by the editor;
- unchanged quest and knowledge snapshots;
- all decoded block boundaries and pointers remain valid.

## Dry Run, Apply Token, and Write Authorization

Dry run remains the default. It builds and fully validates the candidate without
changing GUI state or writing a file. Its report includes classification,
action, allocated IDs, copied dynamic sources, exact static fields, byte delta,
fixup counts, schema-family evidence, quest changes `0`, knowledge changes `0`,
input/candidate hashes, and timings.

A successful dry run creates an in-memory apply token bound to:

- source path;
- encrypted source-file SHA-256;
- decompressed source SHA-256;
- complete source schema SHA-256;
- candidate decompressed SHA-256;
- feature compatibility family ID;
- document generation token.

The GUI enables `Apply & Save Blackstar` only for that exact token. Apply runs in
the worker, rereads the source, verifies all token fields, creates the mandatory
verified backup, writes a temporary encrypted candidate, reloads and validates
it, and atomically replaces the selected source. Any source, document, schema,
or candidate mismatch invalidates the token and requires another dry run.

This scoped writer accepts only the exact Blackstar candidate authorized by the
token. The broad Save and Save As gates remain unchanged and continue requiring
a complete supported profile.

## GUI and Responsiveness

The existing Blackstar worker remains off the GUI thread. Progress phases become:

1. parse and feature compatibility;
2. classify Blackstar state;
3. allocate identifiers and select the target reference;
4. materialize insert or repair candidate;
5. reparse and semantic-invariance validation;
6. preview complete;
7. backup, serialization/encryption, temporary validation, and final write for
   apply mode.

Load, save, undo, and other mutation controls remain disabled while the worker
is active. Cancellation is cooperative between bounded phases. Stale worker
results and stale apply tokens are discarded. A broadly unknown schema remains
read-only for every other editor feature, but the Blackstar preview control may
start its worker so the feature-specific compatibility gate can produce either
a scoped preview or an explicit refusal.

## Logging

Existing rotating logging remains. Blackstar logs add:

- feature-family compatibility signatures and failures;
- classification and record fingerprint;
- legacy replacement versus absent insertion;
- identifier-domain maximum and allocated numbers;
- reference-record selection without logging coordinates;
- template hash, translated type names, and materialized record hash;
- semantic snapshot comparison counts;
- apply-token creation/validation/invalidation;
- backup, serialization, encryption, temporary reload, and final replacement.

Logs never contain decrypted blobs, encryption keys, coordinates, player names,
or arbitrary decoded content.

## Tests

Tests copy fixture bytes into memory or pytest temporary directories and assert
the source fixtures remain unchanged. Required coverage includes:

- the early content-dependent schema passes only Blackstar feature compatibility
  while broad Save remains read-only;
- all seven touched type signatures match the committed family;
- missing or changed touched fields fail closed;
- dry run on the early fixture plans one legitimate idle ownership record,
  allocates collision-free IDs, and writes nothing;
- apply to a temporary copy creates and verifies a backup and reloads cleanly;
- the result contains exactly one validated Blackstar and no Wyvern requirement;
- quest, mission, knowledge, inventory, and all non-mercenary roots are
  semantically unchanged;
- no cooldown or duration entry is added by ownership insertion;
- an in-memory legacy 206-byte state is recognized and replaced, not duplicated;
- an unknown single Blackstar record and duplicate records are refused;
- legitimate idle and active reference states are zero-change/idempotent;
- stale apply tokens, changed source files, backup failures, and temporary
  validation failures prevent replacement;
- progress and logging cover all phases;
- the full test suite and PyInstaller build pass;
- hashes of `tests/fixtures` files are unchanged.

## Source Boundaries

- Create `CrimsonSaveEditor/blackstar_template.py` for the normalized template,
  static semantic contract, type mapping, and materialization.
- Create `CrimsonSaveEditor/blackstar_compat.py` for feature signatures,
  compatibility reports, and scoped write authorization.
- Refactor `CrimsonSaveEditor/blackstar_unlock.py` for classification,
  target-derived planning, insert/legacy replacement, and invariance validation.
- Extend `CrimsonSaveEditor/save_crypto.py` with a scoped transactional writer
  that accepts only a validated Blackstar apply token; preserve the existing
  broad writer unchanged by default.
- Modify `CrimsonSaveEditor/gui.py` for preview-token state and the explicit
  `Apply & Save Blackstar` flow using the existing worker.
- Update `CrimsonSaveEditor/CrimsonSaveEditor.spec` for the new modules if
  PyInstaller analysis does not include them automatically.
- Replace obsolete knowledge-insertion tests with focused ownership, repair,
  compatibility, authorization, GUI-contract, and packaging tests.
- Update `CrimsonSaveEditor/README.md` and `BUILD_FROM_SOURCE.md` with the new
  two-step behavior and copied-fixture verification commands.

## Acceptance Criteria

The work is accepted when the early copied fixture produces a fully validated
dry-run candidate without requiring Wyvern, a temporary-copy apply creates a
verified backup and reloadable encrypted save, the candidate contains exactly
one legitimate idle Blackstar record, legacy insertion is safely repaired,
quests and knowledge remain identical, a second run is byte-identical, unknown
layouts and stale tokens cannot write, all tests pass, the Windows executable
builds, and every original fixture hash is unchanged.
