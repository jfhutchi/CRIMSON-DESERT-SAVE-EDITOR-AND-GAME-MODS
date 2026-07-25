# Blackstar Call Dragon Wheel Repair Design

## Purpose

Extend the 1.14 Blackstar repair so a legitimately owned Blackstar also has the
single save-side ability entry required to appear on the summon wheel. Preserve
the existing preview-bound transaction, mandatory verified backup, schema gate,
worker-thread execution, and quest invariance.

## Evidence

The copied early save and both official 1.14 cross-save references decode as
follows:

| Knowledge entry | Early `slot102` | Legitimate `slot107` | Legitimate `slot108` |
| --- | --- | --- | --- |
| `1000174` `Knowledge_CallVehicle` | present, level 1 | present, level 1 | present, level 1 |
| `1000175` `Knowledge_CallDragon` | missing | present, level 1 | present, level 1 |
| `40068` `Knowledge_BlackWolf` | present, level 2 | present, level 3 | present, level 3 |

The ownership-only candidate preserves the early knowledge list, so it remains
without `Knowledge_CallDragon`. In-game testing confirms that the resulting
Blackstar record is structurally legitimate and idempotent but does not appear
on the wheel. The working hypothesis is therefore that ownership and wheel
eligibility are separate: the 437-byte mercenary record supplies ownership,
while knowledge key `1000175` supplies the Call Dragon ability.

The early save contains 228 target-local 43-byte knowledge elements with the
same present fields as the legitimate Call Dragon element:

- `_key`;
- `_level`;
- `_learnedFieldTime`;
- `_isNewMark`.

This makes a foreign raw knowledge template unnecessary.

## Chosen Approach

Add exactly one `KnowledgeSaveData._list` element for key `1000175` when it is
missing. Materialize it from a structurally compatible element already present
in the target save, set `_key = 1000175`, `_level = 1`, and
`_isNewMark = true`, and retain the target template's learned-time value.

This is preferred over:

1. another game-file summon-wheel overlay, because the earlier overlay crashed
   the game and is not required by the legitimate save evidence;
2. quest-completion changes, because they violate the no-quest requirement and
   are not isolated by the reference comparison;
3. the older broad knowledge injection, because it added dozens of unrelated
   abilities and obscured which dependency mattered.

## Scope

The operation may change only:

- `MercenaryClanSaveData._mercenaryDataList`, when Blackstar ownership is absent
  or the recognized legacy 206-byte record needs replacement; and
- `KnowledgeSaveData._list`, when key `1000175` is absent.

It must not change:

- any quest, mission, stage, or quest-completion flag;
- knowledge key `40068` or its level;
- any other existing knowledge entry;
- inventory, cooldown, duration, position, or unrelated root semantics;
- any game file or PAZ overlay.

## State Model

Ownership and wheel eligibility are evaluated independently.

| Ownership state | Call Dragon state | Planned action |
| --- | --- | --- |
| absent | missing | insert ownership and Call Dragon |
| absent | present | insert ownership only |
| recognized legacy | missing | replace ownership and insert Call Dragon |
| recognized legacy | present | replace ownership only |
| legitimate idle/active | missing | insert Call Dragon only |
| legitimate idle/active | present | no change |
| duplicate or unknown ownership | either | refuse |

This lets the operation repair the already-modified save without deleting or
replacing its legitimate Blackstar record.

## Knowledge Detection and Materialization

Detection parses `KnowledgeSaveData._list` and counts elements whose decoded
`_key` equals `1000175`.

- Zero matches means missing.
- One match with `_level >= 1` means present.
- More than one match refuses mutation as a duplicate state.
- A malformed or incomplete matching element refuses mutation.

For insertion, choose a target-local element whose exact present-field set is
`_key`, `_level`, `_learnedFieldTime`, and `_isNewMark`; whose decoded field
widths match the enrolled 1.14 knowledge layout; and whose `_isNewMark` is true.
Use the last matching element for deterministic selection. Relocate its pointer
locators using the existing bounded knowledge-insertion machinery, append one
element, increment the list count, and apply the existing pointer, trailing-size,
TOC-offset, block-size, and stream-size fixups.

If no compatible target-local template exists, refuse before producing an
apply token. Do not fall back to a foreign record, raw byte search, or generic
knowledge unlock.

## Candidate Construction and Validation

Build the ownership candidate first when required, reparse it, and then append
Call Dragon when required. Reparse the final candidate and require:

- the existing Blackstar ownership validator to pass;
- exactly one knowledge key `1000175` at level 1 or greater;
- knowledge-list growth of exactly one element when it was missing;
- every pre-existing knowledge element to remain semantically identical and in
  the same order;
- an unchanged canonical quest snapshot;
- every root other than the explicitly changed mercenary and knowledge roots to
  remain semantically identical;
- valid decoded block boundaries, pointers, schema bytes, type count, and root
  count.

Dry run builds and validates the complete candidate but writes nothing. Apply
must remain bound to the exact source file, source blob, schema, document
generation, and candidate hash produced by that preview.

## Reporting and Logging

The report adds explicit Call Dragon state and keeps exact change counts:

- ownership classification before and after;
- Call Dragon knowledge missing/present before and after;
- mount action and knowledge action;
- mount count before and after;
- knowledge changes `0` or `1`;
- quest completion changes `0`;
- total byte growth and candidate SHA-256.

Logging adds bounded phases for Call Dragon detection, template selection,
knowledge insertion, reparse, and semantic validation. Logs include key,
element size, template field set, fixup counts, and hashes, but no player names,
coordinates, decrypted blobs, or encryption keys.

## GUI and Transaction Behavior

Keep the existing `Preview Blackstar` and `Apply & Save Blackstar` two-step
flow. A successful preview for the already-owned save should report a
knowledge-only repair with mount count `1 -> 1`, knowledge changes `1`, quest
changes `0`, and byte growth equal to one target-local knowledge element.

Apply continues to run off the GUI thread and uses the mandatory backup,
temporary encrypted write, temporary reload validation, and atomic replacement.
After success, reload the written save. A second preview must report no action,
mount count `1 -> 1`, knowledge changes `0`, quest changes `0`, and byte growth
`0`.

## Compatibility

Keep the feature-scoped 1.14 compatibility family. `KnowledgeSaveData` is
already a required touched type. Extend the gate with decoded checks for the
knowledge list, Call Dragon element fields, field widths, element mask width,
and the availability of a compatible target-local insertion template.

Unknown or changed knowledge layouts remain readable but cannot receive an
apply token.

## Tests

Tests must prove:

- the early fixture lacks `1000175` while both legitimate references contain
  exactly one level-1 entry;
- a dry run plans one ownership record and one Call Dragon entry without
  mutating the source;
- an ownership-only candidate receives a knowledge-only repair;
- the inserted entry has key `1000175`, level 1, `_isNewMark = true`, and the
  target-local 43-byte shape;
- no other knowledge entry changes and knowledge key `40068` is untouched;
- quest and mission snapshots remain identical;
- the second run is byte-identical and reports no action;
- duplicates, malformed matching entries, missing templates, changed field
  widths, changed masks, stale tokens, backup failure, and temporary validation
  failure all refuse or leave the destination unchanged;
- apply to a temporary copy creates a verified backup and reloadable encrypted
  save;
- original fixture hashes remain unchanged;
- the standalone Windows executable builds with the repair included.

## Acceptance Criteria

The change is ready for game testing when a copied ownership-only save produces
a validated dry-run plan containing exactly one Call Dragon knowledge addition,
temporary-copy Apply creates a verified backup and reloadable save, a second run
is byte-identical, all quest-completion changes remain zero, all safety tests
pass, fixture hashes are unchanged, and the standalone executable builds.

Whether `Knowledge_CallDragon` alone makes the wheel entry visible is finally
confirmed only by the user's in-game test. If it does not, stop and return to
reference analysis; do not add quest flags or overlays speculatively.
