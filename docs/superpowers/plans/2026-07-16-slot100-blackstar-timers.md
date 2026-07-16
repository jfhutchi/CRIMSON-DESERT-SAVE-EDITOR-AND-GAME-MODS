# Slot100 Blackstar Repair and Timers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate and independently validate a repaired `slot100` save plus a Blackstar-only 1.14 JSON mod that sets a 30-minute mounted duration and a 1-second summon cooldown without writing to the fixture or installed game.

**Architecture:** Use the existing, tested Blackstar ownership and transactional save services for the encrypted save artifact. Build the timer JSON from semantically resolved 1.14 `Riding_Dragon_1` fields, validate it against an in-memory extracted body, and write only the JSON and verification report under `tests/generated`. No application source file or live save/game file changes.

**Tech Stack:** Python 3.12 from `.venv`, `pytest`, existing `save_crypto`, `blackstar_unlock`, `blackstar_knowledge`, `parc_inserter3`, `crimson_rs`, `characterinfo_full_parser`, PowerShell, JSON, SHA-256.

---

## File Map

- Read only: `tests/fixtures/slot100/save.save` - authorized copied input save.
- Read only: installed PAZ group `0008` - current 1.14 `characterinfo.pabgb` and `characterinfo.pabgh` extraction source.
- Create: `tests/generated/slot100_blackstar_30m_1s/save.save` - repaired encrypted save.
- Create: `tests/generated/slot100_blackstar_30m_1s/backups/save.save.<timestamp>.bak` - verified backup of the generated destination before its transactional replacement.
- Create: `tests/generated/slot100_blackstar_30m_1s/Blackstar_30m_1s_1.14.json` - two-change byte-guarded timer mod.
- Create: `tests/generated/slot100_blackstar_30m_1s/VERIFICATION.md` - complete save and timer validation evidence.
- Do not modify: `tests/fixtures/slot100/lobby.save`, real save directories, installed game files, PAPGT, PAMT, or PAZ files.

The save and timer artifacts are one user-facing deliverable even though they use two data domains: the save establishes legitimate ownership and the JSON changes the persistent global timer configuration.

### Task 1: Establish a Clean, Supported Baseline

**Files:**
- Read: `tests/fixtures/slot100/save.save`
- Read: `tests/test_blackstar_unlock.py`
- Read: `tests/test_blackstar_knowledge.py`
- Read: `tests/test_save_crypto_transaction.py`
- Read: installed `0008` `characterinfo.pabgb` and `characterinfo.pabgh`

- [ ] **Step 1: Confirm the output directory does not already exist**

Run:

```powershell
Test-Path -LiteralPath '.\tests\generated\slot100_blackstar_30m_1s'
```

Expected: `False`. If it is `True`, stop without deleting or replacing it and inspect the existing generated artifacts.

- [ ] **Step 2: Run the existing save mutation and transaction tests**

Run:

```powershell
$env:PYTHONPATH = "$(Resolve-Path '.\CrimsonSaveEditor');$(Resolve-Path '.\CrimsonGameMods')"
.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_unlock.py tests\test_blackstar_knowledge.py tests\test_save_crypto_transaction.py -q
```

Expected: `19 passed` and exit code `0`.

- [ ] **Step 3: Recheck the fixture and 1.14 fingerprints before any output write**

Run:

```powershell
$env:PYTHONPATH = "$(Resolve-Path '.\CrimsonSaveEditor');$(Resolve-Path '.\CrimsonGameMods')"
@'
import hashlib
from pathlib import Path

import crimson_rs
from blackstar_knowledge import inspect_call_dragon
from blackstar_unlock import _classify
from characterinfo_full_parser import parse_all_entries
from parc_inserter3 import build_insert_context
from save_crypto import load_save_file

fixture = Path(r"tests\fixtures\slot100\save.save")
assert hashlib.sha256(fixture.read_bytes()).hexdigest() == (
    "663a3c8522c12e33d0b1e43e68a7d5ba66dd4f2b40affcf18227d7420c5ccfb6"
)
save = load_save_file(str(fixture), operation_id="slot100-preflight")
assert hashlib.sha256(save.decompressed_blob).hexdigest() == (
    "cbb0c8ab5f8a58c6628c999685a5b155b86619d44056a3213ebb581a13e232ce"
)
context = build_insert_context(save.decompressed_blob)
assert _classify(context)[0] == "legacy"
assert inspect_call_dragon(context).status == "present"

game = r"D:\SteamLibrary\steamapps\common\Crimson Desert"
directory = "gamedata/binary__/client/bin"
body = bytes(crimson_rs.extract_file(game, "0008", directory, "characterinfo.pabgb"))
header = bytes(crimson_rs.extract_file(game, "0008", directory, "characterinfo.pabgh"))
assert len(body) == 26431464
assert hashlib.sha256(body).hexdigest() == (
    "e234565b744fb1bb304547b5883cf9249c6cfff54c034c2611a87da26d8324d2"
)
assert len(header) == 56842
assert hashlib.sha256(header).hexdigest() == (
    "f774cd93b0cd865297918b849472d276bd5a04355fdf908b541b043a40a5ab22"
)
targets = [row for row in parse_all_entries(body, header)
           if row.get("entry_key") == 1000799 and row.get("name") == "Riding_Dragon_1"]
assert len(targets) == 1
target = targets[0]
assert target["_vehicleInfo"] == 16984
assert target["_callMercenarySpawnDuration"] == 600
assert target["_callMercenaryCoolTime"] == 3600
assert target["_callMercenaryCoolTime_offset"] == 25579991
assert target["_callMercenarySpawnDuration_offset"] == 25579999
print("PRE-FLIGHT OK: slot100 legacy repair and 1.14 timer source are supported")
'@ | .\.venv\Scripts\python.exe -
```

Expected: `PRE-FLIGHT OK: slot100 legacy repair and 1.14 timer source are supported` and exit code `0`.

### Task 2: Generate the Repaired Encrypted Save

**Files:**
- Read: `tests/fixtures/slot100/save.save`
- Create: `tests/generated/slot100_blackstar_30m_1s/save.save`
- Create: `tests/generated/slot100_blackstar_30m_1s/backups/save.save.<timestamp>.bak`

- [ ] **Step 1: Run the fail-closed save generation transaction**

Run:

```powershell
$env:PYTHONPATH = "$(Resolve-Path '.\CrimsonSaveEditor');$(Resolve-Path '.\CrimsonGameMods')"
@'
import hashlib
import json
import shutil
from pathlib import Path

from blackstar_knowledge import inspect_call_dragon, knowledge_parts
from blackstar_unlock import (
    _classify,
    _clan_parts,
    canonical_root_snapshot,
    unlock_blackstar,
)
from parc_inserter3 import build_insert_context
from save_compat import schema_structure_matches
from save_crypto import load_save_file, transactional_write_save

SOURCE_ENCRYPTED = "663a3c8522c12e33d0b1e43e68a7d5ba66dd4f2b40affcf18227d7420c5ccfb6"
SOURCE_DECOMPRESSED = "cbb0c8ab5f8a58c6628c999685a5b155b86619d44056a3213ebb581a13e232ce"
CANDIDATE_DECOMPRESSED = "b9a5ef56e6c6b6537a8e5dd908f1f2ae42c90bb0bea8aa88410f80ff3299f8fd"

source = Path(r"tests\fixtures\slot100\save.save")
out_dir = Path(r"tests\generated\slot100_blackstar_30m_1s")
destination = out_dir / "save.save"
timer_json = out_dir / "Blackstar_30m_1s_1.14.json"
verification = out_dir / "VERIFICATION.md"

for artifact in (destination, timer_json, verification):
    if artifact.exists():
        raise FileExistsError(f"Refusing to replace existing generated artifact: {artifact}")

assert hashlib.sha256(source.read_bytes()).hexdigest() == SOURCE_ENCRYPTED
loaded = load_save_file(str(source), operation_id="slot100-source-load")
assert hashlib.sha256(loaded.decompressed_blob).hexdigest() == SOURCE_DECOMPRESSED
before = build_insert_context(loaded.decompressed_blob)
before_state, before_rows = _classify(before)
assert before_state == "legacy" and len(before_rows) == 1
assert before_rows[0][1].end_offset - before_rows[0][1].start_offset == 206
before_call = inspect_call_dragon(before)
assert (before_call.status, before_call.count, before_call.level) == ("present", 1, 1)
quest_before = canonical_root_snapshot(before, "QuestSaveData")
knowledge_before = canonical_root_snapshot(before, "KnowledgeSaveData")
mounts_before = len(_clan_parts(before)[1].list_elements)
knowledge_count_before = len(knowledge_parts(before)[1].list_elements)

applied = unlock_blackstar(
    loaded.decompressed_blob,
    loaded.schema_identity,
    dry_run=False,
    operation_id="slot100-generate",
)
assert applied.output_blob is not None
assert applied.profile_id == "blackstar-owner-114-v1"
assert applied.report.classification_before == "legacy"
assert applied.report.action == "replace"
assert applied.report.byte_growth == 231
assert applied.report.quest_changes == 0
assert applied.report.knowledge_changes == 0
assert applied.report.mercenary_no == 1000798
assert applied.report.item_no == 1000799
assert applied.report.reference_character_key == 85001
assert hashlib.sha256(applied.output_blob).hexdigest() == CANDIDATE_DECOMPRESSED

out_dir.mkdir(parents=True, exist_ok=False)
shutil.copy2(source, destination)
assert hashlib.sha256(destination.read_bytes()).hexdigest() == SOURCE_ENCRYPTED
write = transactional_write_save(
    destination=destination,
    edited_blob=applied.output_blob,
    original_header=loaded.raw_header,
    backup_source=destination,
    expected_identity=loaded.schema_identity,
    operation_id="slot100-generated-transaction",
    scope_family_id=applied.profile_id,
)
assert write.backup_path.parent == out_dir / "backups"
assert hashlib.sha256(write.backup_path.read_bytes()).hexdigest() == SOURCE_ENCRYPTED

reloaded = load_save_file(str(destination), operation_id="slot100-generated-reload")
assert schema_structure_matches(reloaded.schema_identity, loaded.schema_identity)
assert reloaded.schema_identity.schema_sha256 == loaded.schema_identity.schema_sha256
assert hashlib.sha256(reloaded.decompressed_blob).hexdigest() == CANDIDATE_DECOMPRESSED
after = build_insert_context(reloaded.decompressed_blob)
after_state, after_rows = _classify(after)
assert after_state == "legitimate_idle" and len(after_rows) == 1
assert after_rows[0][1].end_offset - after_rows[0][1].start_offset == 437
after_call = inspect_call_dragon(after)
assert (after_call.status, after_call.count, after_call.level) == ("present", 1, 1)
assert len(_clan_parts(after)[1].list_elements) == mounts_before
assert len(knowledge_parts(after)[1].list_elements) == knowledge_count_before
assert canonical_root_snapshot(after, "QuestSaveData") == quest_before
assert canonical_root_snapshot(after, "KnowledgeSaveData") == knowledge_before

second = unlock_blackstar(
    reloaded.decompressed_blob,
    reloaded.schema_identity,
    dry_run=False,
    operation_id="slot100-idempotence",
)
assert second.output_blob == bytes(reloaded.decompressed_blob)
assert second.report.action == "none"
assert second.report.byte_growth == 0
assert second.report.quest_changes == 0
assert second.report.knowledge_changes == 0
assert hashlib.sha256(source.read_bytes()).hexdigest() == SOURCE_ENCRYPTED

print(json.dumps({
    "destination": str(destination.resolve()),
    "backup": str(write.backup_path.resolve()),
    "output_encrypted_sha256": write.output_sha256,
    "output_decompressed_sha256": CANDIDATE_DECOMPRESSED,
    "classification": f"{before_state} -> {after_state}",
    "mounts": f"{mounts_before} -> {len(_clan_parts(after)[1].list_elements)}",
    "knowledge": f"{knowledge_count_before} -> {len(knowledge_parts(after)[1].list_elements)}",
    "call_dragon": "present level 1 -> present level 1",
    "quests_changed": 0,
    "knowledge_changed": 0,
    "second_run_action": second.report.action,
}, indent=2))
'@ | .\.venv\Scripts\python.exe -
```

Expected: JSON showing `legacy -> legitimate_idle`, `80 -> 80` mounts, `3201 -> 3201` knowledge, zero quest/knowledge changes, and second-run action `none`.

### Task 3: Create and Validate the Blackstar-Only Timer JSON

**Files:**
- Create: `tests/generated/slot100_blackstar_30m_1s/Blackstar_30m_1s_1.14.json`
- Read: installed `0008` `characterinfo.pabgb` and `characterinfo.pabgh`

- [ ] **Step 1: Create the complete byte-guarded JSON mod**

Use `apply_patch` to create this exact file:

```json
{
  "name": "Blackstar 30m Ride 1s Cooldown (1.14)",
  "version": "1.0.0",
  "author": "Codex",
  "description": "Blackstar only: mounted duration 600 -> 1800 seconds and summon cooldown 3600 -> 1 second. Requires the recorded 1.14 characterinfo fingerprint.",
  "supported_characterinfo": {
    "body_size": 26431464,
    "body_sha256": "e234565b744fb1bb304547b5883cf9249c6cfff54c034c2611a87da26d8324d2",
    "header_size": 56842,
    "header_sha256": "f774cd93b0cd865297918b849472d276bd5a04355fdf908b541b043a40a5ab22",
    "entry_key": 1000799,
    "entry_name": "Riding_Dragon_1",
    "scope": "Blackstar globally across all saves while enabled"
  },
  "patches": [
    {
      "game_file": "gamedata/characterinfo.pabgb",
      "changes": [
        {
          "offset": 25579991,
          "label": "Riding_Dragon_1: _callMercenaryCoolTime (3600s -> 1s)",
          "original": "100E000000000000",
          "patched": "0100000000000000"
        },
        {
          "offset": 25579999,
          "label": "Riding_Dragon_1: _callMercenarySpawnDuration (600s -> 1800s)",
          "original": "5802000000000000",
          "patched": "0807000000000000"
        }
      ]
    }
  ]
}
```

- [ ] **Step 2: Validate loader parsing and in-memory patch semantics**

Run:

```powershell
$env:PYTHONPATH = "$(Resolve-Path '.\CrimsonSaveEditor');$(Resolve-Path '.\CrimsonGameMods')"
@'
import hashlib
import json
from pathlib import Path

import crimson_rs
import lz4.block
from characterinfo_full_parser import parse_all_entries
from mod_loader import CommunityModLoader

EXPECTED_BODY = "e234565b744fb1bb304547b5883cf9249c6cfff54c034c2611a87da26d8324d2"
EXPECTED_HEADER = "f774cd93b0cd865297918b849472d276bd5a04355fdf908b541b043a40a5ab22"
EXPECTED_DIFFS = [25579991, 25579992, 25579999, 25580000]

path = Path(r"tests\generated\slot100_blackstar_30m_1s\Blackstar_30m_1s_1.14.json")
document = json.loads(path.read_text(encoding="utf-8"))
assert len(document["patches"]) == 1
assert document["patches"][0]["game_file"] == "gamedata/characterinfo.pabgb"
assert len(document["patches"][0]["changes"]) == 2

loader = CommunityModLoader(r"D:\SteamLibrary\steamapps\common\Crimson Desert")
parsed = loader._parse_mod_file(str(path), path.name)
assert parsed is not None
assert len(parsed.patches) == 1
assert len(parsed.patches[0].changes) == 2
assert loader.resolve_mod(parsed), parsed.error_msg
resolved = parsed.patches[0]
assert resolved.compressed
assert resolved.orig_size == 26431464

game = r"D:\SteamLibrary\steamapps\common\Crimson Desert"
directory = "gamedata/binary__/client/bin"
body = bytes(crimson_rs.extract_file(game, "0008", directory, "characterinfo.pabgb"))
header = bytes(crimson_rs.extract_file(game, "0008", directory, "characterinfo.pabgh"))
assert hashlib.sha256(body).hexdigest() == EXPECTED_BODY
assert hashlib.sha256(header).hexdigest() == EXPECTED_HEADER

before_rows = parse_all_entries(body, header)
before_targets = [row for row in before_rows
                  if row.get("entry_key") == 1000799 and row.get("name") == "Riding_Dragon_1"]
assert len(before_targets) == 1
before = before_targets[0]
assert before["_callMercenaryCoolTime_offset"] == 25579991
assert before["_callMercenarySpawnDuration_offset"] == 25579999
assert before["_callMercenaryCoolTime"] == 3600
assert before["_callMercenarySpawnDuration"] == 600

candidate = bytearray(body)
for change in document["patches"][0]["changes"]:
    offset = change["offset"]
    original = bytes.fromhex(change["original"])
    patched = bytes.fromhex(change["patched"])
    assert len(original) == len(patched) == 8
    assert bytes(candidate[offset:offset + 8]) == original
    candidate[offset:offset + 8] = patched

changed = [index for index, (left, right) in enumerate(zip(body, candidate)) if left != right]
assert changed == EXPECTED_DIFFS
assert len(candidate) == len(body)
after_rows = parse_all_entries(bytes(candidate), header)
after_targets = [row for row in after_rows
                 if row.get("entry_key") == 1000799 and row.get("name") == "Riding_Dragon_1"]
assert len(after_targets) == 1
after = after_targets[0]
assert after["_callMercenaryCoolTime"] == 1
assert after["_callMercenarySpawnDuration"] == 1800

def stable_fields(row):
    return {
        key: value for key, value in row.items()
        if key not in {"_callMercenaryCoolTime", "_callMercenarySpawnDuration"}
    }

assert stable_fields(after) == stable_fields(before)
assert len(after_rows) == len(before_rows) == 7105
recompressed = lz4.block.compress(
    bytes(candidate), mode="high_compression", store_size=False
)
assert len(recompressed) <= resolved.comp_size
print(json.dumps({
    "loader_name": parsed.name,
    "changes": len(parsed.patches[0].changes),
    "resolved_paz": str(Path(resolved.paz_path).resolve()),
    "paz_slot_bytes": resolved.comp_size,
    "candidate_recompressed_bytes": len(recompressed),
    "recompression_headroom_bytes": resolved.comp_size - len(recompressed),
    "raw_changed_offsets": changed,
    "candidate_body_sha256": hashlib.sha256(candidate).hexdigest(),
    "cooldown_seconds": after["_callMercenaryCoolTime"],
    "duration_seconds": after["_callMercenarySpawnDuration"],
    "installed_game_writes": 0,
}, indent=2))
'@ | .\.venv\Scripts\python.exe -
```

Expected: two loader changes, four raw changed offsets, cooldown `1`, duration `1800`, positive recompression headroom, and installed-game writes `0`.

### Task 4: Produce the Independent Verification Report

**Files:**
- Read: `tests/fixtures/slot100/save.save`
- Read: `tests/generated/slot100_blackstar_30m_1s/save.save`
- Read: `tests/generated/slot100_blackstar_30m_1s/backups/save.save.<timestamp>.bak`
- Read: `tests/generated/slot100_blackstar_30m_1s/Blackstar_30m_1s_1.14.json`
- Create: `tests/generated/slot100_blackstar_30m_1s/VERIFICATION.md`

- [ ] **Step 1: Reparse every artifact and write the evidence report**

Run:

```powershell
$env:PYTHONPATH = "$(Resolve-Path '.\CrimsonSaveEditor');$(Resolve-Path '.\CrimsonGameMods')"
@'
import hashlib
import json
from pathlib import Path

import crimson_rs
from blackstar_knowledge import inspect_call_dragon, knowledge_parts
from blackstar_unlock import (
    _classify,
    _clan_parts,
    canonical_root_snapshot,
    unlock_blackstar,
)
from characterinfo_full_parser import parse_all_entries
from parc_inserter3 import build_insert_context
from save_compat import schema_structure_matches
from save_crypto import load_save_file

SOURCE_ENCRYPTED = "663a3c8522c12e33d0b1e43e68a7d5ba66dd4f2b40affcf18227d7420c5ccfb6"
SOURCE_DECOMPRESSED = "cbb0c8ab5f8a58c6628c999685a5b155b86619d44056a3213ebb581a13e232ce"
OUTPUT_DECOMPRESSED = "b9a5ef56e6c6b6537a8e5dd908f1f2ae42c90bb0bea8aa88410f80ff3299f8fd"
GAME_BODY = "e234565b744fb1bb304547b5883cf9249c6cfff54c034c2611a87da26d8324d2"
GAME_HEADER = "f774cd93b0cd865297918b849472d276bd5a04355fdf908b541b043a40a5ab22"

source_path = Path(r"tests\fixtures\slot100\save.save")
out_dir = Path(r"tests\generated\slot100_blackstar_30m_1s")
save_path = out_dir / "save.save"
json_path = out_dir / "Blackstar_30m_1s_1.14.json"
report_path = out_dir / "VERIFICATION.md"
backups = list((out_dir / "backups").glob("save.save.*.bak"))
assert len(backups) == 1
backup_path = backups[0]

assert hashlib.sha256(source_path.read_bytes()).hexdigest() == SOURCE_ENCRYPTED
assert hashlib.sha256(backup_path.read_bytes()).hexdigest() == SOURCE_ENCRYPTED
source = load_save_file(str(source_path), operation_id="slot100-report-source")
output = load_save_file(str(save_path), operation_id="slot100-report-output")
assert hashlib.sha256(source.decompressed_blob).hexdigest() == SOURCE_DECOMPRESSED
assert hashlib.sha256(output.decompressed_blob).hexdigest() == OUTPUT_DECOMPRESSED
assert schema_structure_matches(output.schema_identity, source.schema_identity)
assert output.schema_identity.schema_sha256 == source.schema_identity.schema_sha256

before = build_insert_context(source.decompressed_blob)
after = build_insert_context(output.decompressed_blob)
before_state, before_rows = _classify(before)
after_state, after_rows = _classify(after)
assert before_state == "legacy" and len(before_rows) == 1
assert after_state == "legitimate_idle" and len(after_rows) == 1
assert before_rows[0][1].end_offset - before_rows[0][1].start_offset == 206
assert after_rows[0][1].end_offset - after_rows[0][1].start_offset == 437
before_call = inspect_call_dragon(before)
after_call = inspect_call_dragon(after)
assert (before_call.status, before_call.count, before_call.level) == ("present", 1, 1)
assert (after_call.status, after_call.count, after_call.level) == ("present", 1, 1)
mounts_before = len(_clan_parts(before)[1].list_elements)
mounts_after = len(_clan_parts(after)[1].list_elements)
knowledge_before_count = len(knowledge_parts(before)[1].list_elements)
knowledge_after_count = len(knowledge_parts(after)[1].list_elements)
assert (mounts_before, mounts_after) == (80, 80)
assert (knowledge_before_count, knowledge_after_count) == (3201, 3201)
assert canonical_root_snapshot(before, "QuestSaveData") == canonical_root_snapshot(after, "QuestSaveData")
assert canonical_root_snapshot(before, "KnowledgeSaveData") == canonical_root_snapshot(after, "KnowledgeSaveData")
second = unlock_blackstar(
    output.decompressed_blob,
    output.schema_identity,
    dry_run=False,
    operation_id="slot100-report-idempotence",
)
assert second.output_blob == bytes(output.decompressed_blob)
assert second.report.action == "none"
assert second.report.byte_growth == 0

document = json.loads(json_path.read_text(encoding="utf-8"))
game = r"D:\SteamLibrary\steamapps\common\Crimson Desert"
directory = "gamedata/binary__/client/bin"
body = bytes(crimson_rs.extract_file(game, "0008", directory, "characterinfo.pabgb"))
header = bytes(crimson_rs.extract_file(game, "0008", directory, "characterinfo.pabgh"))
assert hashlib.sha256(body).hexdigest() == GAME_BODY
assert hashlib.sha256(header).hexdigest() == GAME_HEADER
candidate = bytearray(body)
for change in document["patches"][0]["changes"]:
    offset = change["offset"]
    original = bytes.fromhex(change["original"])
    patched = bytes.fromhex(change["patched"])
    assert bytes(candidate[offset:offset + len(original)]) == original
    candidate[offset:offset + len(patched)] = patched
changed = [index for index, pair in enumerate(zip(body, candidate)) if pair[0] != pair[1]]
assert changed == [25579991, 25579992, 25579999, 25580000]
target = next(row for row in parse_all_entries(bytes(candidate), header)
              if row.get("entry_key") == 1000799 and row.get("name") == "Riding_Dragon_1")
assert target["_callMercenaryCoolTime"] == 1
assert target["_callMercenarySpawnDuration"] == 1800
candidate_hash = hashlib.sha256(candidate).hexdigest()
output_encrypted_hash = hashlib.sha256(save_path.read_bytes()).hexdigest()
json_hash = hashlib.sha256(json_path.read_bytes()).hexdigest()

report = f"""# Slot100 Blackstar 30m/1s Verification

## Save Artifact

- Source: `{source_path.resolve()}`
- Source encrypted SHA-256: `{SOURCE_ENCRYPTED}`
- Source decompressed SHA-256: `{SOURCE_DECOMPRESSED}`
- Output: `{save_path.resolve()}`
- Output encrypted SHA-256: `{output_encrypted_hash}`
- Output decompressed SHA-256: `{OUTPUT_DECOMPRESSED}`
- Backup: `{backup_path.resolve()}`
- Backup SHA-256: `{SOURCE_ENCRYPTED}`
- Compatibility family: `blackstar-owner-114-v1`
- Schema SHA-256: `{source.schema_identity.schema_sha256}`
- Blackstar state: `legacy -> legitimate_idle`
- Blackstar record bytes: `206 -> 437`
- Mount records: `{mounts_before} -> {mounts_after}`
- Knowledge records: `{knowledge_before_count} -> {knowledge_after_count}`
- Call Dragon: `present level 1 -> present level 1`
- Quest semantic changes: `0`
- Knowledge semantic changes: `0`
- Save byte growth: `231`
- Allocated mercenary number: `1000798`
- Allocated equipment item number: `1000799`
- Second-run action: `{second.report.action}`
- Second-run byte growth: `{second.report.byte_growth}`

## Timer Mod

- JSON: `{json_path.resolve()}`
- JSON SHA-256: `{json_hash}`
- Source characterinfo size: `{len(body)}`
- Source characterinfo SHA-256: `{GAME_BODY}`
- Source header size: `{len(header)}`
- Source header SHA-256: `{GAME_HEADER}`
- Candidate characterinfo SHA-256: `{candidate_hash}`
- Target: `Riding_Dragon_1` / key `1000799`
- Cooldown: `3600 -> 1` second at offset `25579991`
- Mounted duration: `600 -> 1800` seconds at offset `25579999`
- Raw changed offsets: `{', '.join(str(value) for value in changed)}`
- Other character semantic changes: `0`
- Installed game writes by Codex: `0`

## Source Preservation

- Fixture encrypted hash after generation: `{hashlib.sha256(source_path.read_bytes()).hexdigest()}` (unchanged)
- Installed characterinfo body hash after validation: `{hashlib.sha256(body).hexdigest()}` (unchanged)
- Installed characterinfo header hash after validation: `{hashlib.sha256(header).hexdigest()}` (unchanged)
- `lobby.save` changes: `0`
- Live save writes: `0`
- Live PAPGT/PAMT/PAZ writes: `0`
"""
report_path.write_text(report, encoding="utf-8")
print(report)
'@ | .\.venv\Scripts\python.exe -
```

Expected: the complete Markdown report prints and is written to `VERIFICATION.md`, with all source-preservation values marked unchanged.

### Task 5: Run Fresh Final Verification

**Files:**
- Verify: `tests/generated/slot100_blackstar_30m_1s/save.save`
- Verify: `tests/generated/slot100_blackstar_30m_1s/backups/save.save.<timestamp>.bak`
- Verify: `tests/generated/slot100_blackstar_30m_1s/Blackstar_30m_1s_1.14.json`
- Verify: `tests/generated/slot100_blackstar_30m_1s/VERIFICATION.md`
- Verify unchanged: `tests/fixtures/slot100/save.save`

- [ ] **Step 1: Rerun the focused regression suite**

Run:

```powershell
$env:PYTHONPATH = "$(Resolve-Path '.\CrimsonSaveEditor');$(Resolve-Path '.\CrimsonGameMods')"
.\.venv\Scripts\python.exe -m pytest tests\test_blackstar_unlock.py tests\test_blackstar_knowledge.py tests\test_save_crypto_transaction.py -q
```

Expected: `19 passed` and exit code `0`.

- [ ] **Step 2: Verify all artifact paths, hashes, and source preservation**

Run:

```powershell
Get-ChildItem -LiteralPath '.\tests\generated\slot100_blackstar_30m_1s' -Recurse -File |
    Select-Object FullName,Length,LastWriteTime
Get-FileHash -Algorithm SHA256 -LiteralPath '.\tests\fixtures\slot100\save.save'
Get-FileHash -Algorithm SHA256 -LiteralPath '.\tests\generated\slot100_blackstar_30m_1s\save.save'
Get-FileHash -Algorithm SHA256 -LiteralPath '.\tests\generated\slot100_blackstar_30m_1s\Blackstar_30m_1s_1.14.json'
Get-Content -Raw -LiteralPath '.\tests\generated\slot100_blackstar_30m_1s\VERIFICATION.md'
```

Expected:

- exactly one generated save, one generated backup, one JSON mod, and one verification report;
- fixture SHA-256 remains `663A3C8522C12E33D0B1E43E68A7D5BA66DD4F2B40AFFCF18227D7420C5CCFB6`;
- report shows `legacy -> legitimate_idle`, zero quest and knowledge changes, duration `1800`, cooldown `1`, and no live writes.

- [ ] **Step 3: Confirm no tracked source files changed during artifact generation**

Run:

```powershell
git status --short
```

Expected: only the pre-existing untracked fixture/test/generated trees are listed. Do not stage or commit `tests/fixtures`, `tests/generated`, or `CrimsonGameMods/test`.

- [ ] **Step 4: Hand off the exact local paths and installation boundary**

Report these paths:

```text
tests/generated/slot100_blackstar_30m_1s/save.save
tests/generated/slot100_blackstar_30m_1s/Blackstar_30m_1s_1.14.json
tests/generated/slot100_blackstar_30m_1s/VERIFICATION.md
```

State explicitly that Codex did not install the JSON or replace a real save. The user must copy the generated save into the intended slot and place the JSON in the Game Mods Load Manager folder before applying it and fully restarting the game.
