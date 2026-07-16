# Slot100 Blackstar Repair and Timers Design

**Status:** Approved in conversation on 2026-07-16

## Goal

Produce two local, testable artifacts for the copied `slot100` fixture:

1. a repaired encrypted save that replaces the obsolete Blackstar ownership
   record while preserving the existing Call Dragon wheel knowledge; and
2. a Blackstar-only game-data mod that triples the mounted duration from 600
   seconds to 1,800 seconds and reduces the summon cooldown from 3,600 seconds
   to 1 second.

The operation must not modify the fixture, any real save, or the installed game.
It must not change quests or unrelated mounts. Installation remains an explicit
manual action after the user reviews the generated artifacts.

## Confirmed Inputs

### Copied save

The only authorized save input is:

`tests/fixtures/slot100/save.save`

| Property | Value |
| --- | --- |
| Encrypted size | `1,629,231` bytes |
| Encrypted SHA-256 | `663a3c8522c12e33d0b1e43e68a7d5ba66dd4f2b40affcf18227d7420c5ccfb6` |
| Decompressed SHA-256 | `cbb0c8ab5f8a58c6628c999685a5b155b86619d44056a3213ebb581a13e232ce` |
| Container version | `2` |
| Schema SHA-256 | `97b086ba545981e2678a91ae7eb81237681c8842fbe04e6d75a5f2ee1513a004` |
| Blackstar state | one 206-byte legacy record |
| Mount records | `80` |
| Call Dragon knowledge | exactly one key `1000175`, level `1` |
| Knowledge records | `3,201` |

The existing Blackstar record has character key `1000799`, mercenary number
`1017`, and occupation state `1`, but it lacks the legitimate ownership and
equipment structure. It is classified as `legacy` by the existing fail-closed
Blackstar service.

### Installed 1.14 game data

Read-only extraction from PAZ group `0008` confirms the current base files:

| Property | Value |
| --- | --- |
| `characterinfo.pabgb` size | `26,431,464` bytes |
| `characterinfo.pabgb` SHA-256 | `e234565b744fb1bb304547b5883cf9249c6cfff54c034c2611a87da26d8324d2` |
| `characterinfo.pabgh` size | `56,842` bytes |
| `characterinfo.pabgh` SHA-256 | `f774cd93b0cd865297918b849472d276bd5a04355fdf908b541b043a40a5ab22` |
| Parsed entries | `7,105` |

Exactly one target record exists:

| Field | Value |
| --- | --- |
| Entry key | `1000799` |
| Internal name | `Riding_Dragon_1` |
| Vehicle type | `16984` (`Dragon`) |
| Spawn duration | `600` seconds |
| Summon cooldown | `3,600` seconds |
| Cooldown type | `0` |
| Cooldown field offset | `25,579,991` |
| Duration field offset | `25,579,999` |

The offsets are evidence for this exact 1.14 body, not cross-version constants.
The generated JSON mod is valid only for this fingerprint and exact original
field bytes.

The active PAPGT contains only official groups through `0035`. There is no
active custom group at or above `0036`, no `0039` FieldEdit overlay, and group
`0035` contains no character, vehicle, region, or field data. Therefore no
current game-data overlay conflicts with this scoped patch.

## Selected Architecture

Use two independent artifacts because ownership and configured timer limits live
in different data domains.

### 1. Repaired save copy

Use the existing `blackstar_unlock` service against the decompressed fixture
blob. The service will replace the single 206-byte legacy record with the
legitimate 437-byte idle Blackstar record. The planned decompressed candidate is
already proven by dry run:

| Property | Value |
| --- | --- |
| Action | `replace` |
| Candidate decompressed SHA-256 | `b9a5ef56e6c6b6537a8e5dd908f1f2ae42c90bb0bea8aa88410f80ff3299f8fd` |
| Byte growth | `231` bytes |
| Allocated mercenary number | `1000798` |
| Allocated equipment item number | `1000799` |
| Reference character key | `85001` |
| Quest changes | `0` |
| Knowledge changes | `0` |

The existing Call Dragon key is retained byte-semantically. The knowledge
inserter is not called because key `1000175` is already present at level `1`.
No cooldown or duration runtime entries are inserted into the save. The repaired
Blackstar remains idle so the first in-game summon creates runtime entries from
the installed game-data values.

The encrypted output will be written only under:

`tests/generated/slot100_blackstar_30m_1s/save.save`

The transaction starts from a copied destination, creates a backup inside the
same generated tree, writes through a temporary file, reloads the encrypted
candidate, and verifies its decompressed SHA-256 and schema identity. The source
fixture hash is checked again after the operation.

### 2. Scoped timer JSON mod

Generate a JD/CDUMM-compatible byte-guarded JSON mod containing exactly one
`gamedata/characterinfo.pabgb` patch group and two changes:

| Semantic field | Offset | Original bytes | Patched bytes | Meaning |
| --- | ---: | --- | --- | --- |
| `_callMercenaryCoolTime` | `25,579,991` | `100e000000000000` | `0100000000000000` | `3600 -> 1` second |
| `_callMercenarySpawnDuration` | `25,579,999` | `5802000000000000` | `0807000000000000` | `600 -> 1800` seconds |

The output path is:

`tests/generated/slot100_blackstar_30m_1s/Blackstar_30m_1s_1.14.json`

The JSON metadata records both supported source hashes and states that the mod
affects Blackstar globally across all saves while enabled. It does not include
vehicle, region, summon-wheel, quest, knowledge, or other mount patches.

The generated JSON is tested against a temporary copy of the extracted 1.14
body. Validation reparses the candidate with the matching header and proves:

- exactly one Blackstar record still exists;
- body length and table structure are unchanged;
- the Blackstar duration is exactly `1,800`;
- the Blackstar cooldown is exactly `1`;
- every other parsed field of the Blackstar record is unchanged;
- every other character record is byte-identical; and
- the only raw byte differences fall within the two declared eight-byte fields.

Codex will not load the JSON into the mod manager or write an overlay. The user
will install it manually through the existing Load Manager only after reviewing
the report.

## Alternatives Rejected

### Save-only timer editing

The save records active runtime timer state after a mount is summoned, but it
does not define the maximum duration or cooldown. Editing runtime values would
be temporary and the game would recreate them from `characterinfo.pabgb`.

### Standalone PAZ overlay

A dedicated overlay could carry the same two changes, but it would also carry a
generated PAPGT document that can become stale if another mod is installed
before deployment. The JSON loader can merge the two byte-guarded changes into
the user's current mod state and is easier to remove.

### Enable Mounts Everywhere

The existing broad mod changes hundreds of fields across vehicle, region, and
character tables, including many unrelated mount timers. Its offsets also come
from an older game body. It is unnecessary and outside this feature's scope.

## Failure Handling

The generation and validation process fails closed when any of these conditions
is observed:

- the fixture encrypted or decompressed hash differs from the confirmed input;
- the save schema is not accepted by `blackstar-owner-114-v1`;
- Blackstar is missing, duplicated, or not classified as the expected legacy
  record;
- Call Dragon knowledge is missing, duplicated, or below level `1`;
- the installed `characterinfo` body or header fingerprint differs;
- the target record is missing, duplicated, or no longer has values `600` and
  `3600`;
- the save candidate changes quests or knowledge;
- the timer candidate changes any unrelated byte or semantic field;
- encrypted save reload, schema comparison, or idempotence validation fails; or
- either source hash changes during the operation.

There is no force mode and no fallback to guessed offsets.

## Verification Report

Create `tests/generated/slot100_blackstar_30m_1s/VERIFICATION.md` containing:

- source and output encrypted/decompressed hashes;
- backup path and backup hash;
- save schema and compatibility family;
- Blackstar classification before and after;
- mount and knowledge counts before and after;
- Call Dragon state before and after;
- quest and knowledge semantic change counts;
- allocated identifiers and save byte growth;
- timer source/candidate body hashes and sizes;
- exact timer fields, values, offsets, and raw byte differences;
- first-run and second-run idempotence results; and
- an explicit statement that the fixture and installed game hashes were
  unchanged.

## User Workflow

After generation, the user will:

1. copy the generated `save.save` into the intended game slot using their own
   normal save-backup procedure;
2. load `Blackstar_30m_1s_1.14.json` through the Game Mods Load Manager;
3. apply the enabled JSON mods and fully restart Crimson Desert; and
4. test Blackstar summon, 30-minute mounted duration, expiration, and resummon.

The timer mod affects Blackstar in every save while enabled. A later game update
invalidates the supported fingerprint; the mod must be removed and regenerated
for the new `characterinfo` files.

## Scope Boundaries

This design does not modify or promise:

- `lobby.save`;
- quest, mission, achievement, or completion flags;
- additional knowledge entries;
- Blackstar attacks, health, damage, or armor configuration;
- Wyvern or other mount duration/cooldown values;
- summon-in-town restrictions;
- live save directories;
- live game archives, PAPGT, PAMT, or PAZ files; or
- automatic installation or restoration of the timer mod.
