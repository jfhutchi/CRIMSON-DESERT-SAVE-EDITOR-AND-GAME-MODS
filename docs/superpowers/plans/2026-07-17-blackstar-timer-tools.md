# Blackstar Timer Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the verified Blackstar 30-minute mounted-time and 1-second cooldown preset in both Windows tools, then redesign both complete interfaces in the approved Crimson Desert visual direction and push the verified branch to the user's GitHub fork.

**Architecture:** A repository-level `crimson_common` package owns archive compatibility, preview, transactional apply/restore, logging, and the shared Qt worker. The existing Save Editor and Game Mods applications remain separate executables and become thin consumers of that package. The UI phase inventories every current surface before replacing presentation, preserves all commands, and moves blocking work behind workers so neither main window appears frozen.

**Tech Stack:** Python 3.12, PySide6 6.8.3, `crimson_rs`, LZ4 4.4.5, pytest 9.1.1, PyInstaller 6.21.0, Windows PowerShell, Git/GitHub.

---

## File Structure

- Create `crimson_common/__init__.py`: stable exports shared by both applications.
- Create `crimson_common/blackstar_timer.py`: immutable profile, archive detection, preview tokens, transactional apply/restore, manifests, integrity checks, and structured reports.
- Create `crimson_common/blackstar_timer_worker.py`: shared Qt worker with ordered progress, safe cancellation, and exactly one terminal signal.
- Create `tests/blackstar_timer_archive.py`: compact temporary PAZ/PAMT/PAPGT factory; never points at an installed game or save.
- Create `tests/test_blackstar_timer_core.py`: compatibility, preview, transaction, idempotence, rollback, and restore coverage.
- Create `tests/test_blackstar_timer_worker.py`: worker lifecycle and cancellation coverage.
- Create `tests/test_blackstar_timer_gui_contract.py`: both applications expose equivalent actions and warnings.
- Create `tests/test_ui_feature_inventory.py`: prevents redesigned navigation from dropping existing commands.
- Create `tests/test_ui_responsiveness_contract.py`: prevents known long-running entry points from executing directly on the GUI thread.
- Modify `CrimsonGameMods/mod_loader.py`: fix the generic compressed-patch metadata regression.
- Modify `CrimsonGameMods/gui/tabs/patches.py`: add the shared Blackstar Timer panel.
- Modify `CrimsonGameMods/gui/main_window.py`: expose Game Patches and adopt the redesigned shell.
- Modify `CrimsonGameMods/main.py`: source-checkout import bootstrap and startup reporting.
- Modify `CrimsonGameMods/CrimsonGameMods.spec`: package the shared modules and native dependencies.
- Modify `CrimsonSaveEditor/gui.py`: add the shared timer panel beside Blackstar ownership, then adopt the redesigned shell without removing tools.
- Modify `CrimsonSaveEditor/main.py`: source-checkout import bootstrap and startup reporting.
- Modify `CrimsonSaveEditor/CrimsonSaveEditor.spec`: package the shared modules and native dependencies.
- Create `CrimsonGameMods/gui/crimson_theme.py` and `CrimsonSaveEditor/crimson_theme.py`: app-specific theme entry points using one Crimson Desert token vocabulary.
- Create `docs/windows-build.md`: exact dependency, build, executable, backup, and smoke-test instructions.

### Task 1: Temporary Archive Harness and Compatibility Detection

**Files:**
- Create: `tests/blackstar_timer_archive.py`
- Create: `tests/test_blackstar_timer_core.py`
- Create: `crimson_common/__init__.py`
- Create: `crimson_common/blackstar_timer.py`

- [ ] **Step 1: Write the failing detection tests**

Create a compact body with two unsigned little-endian 64-bit fields and build group `0008` using `crimson_rs.PackGroupBuilder`. Assert `BlackstarTimerService.detect()` returns `VANILLA` only when path, entry count, size, SHA-256, compression, and both field values match; mutate each independently and assert `UNKNOWN` or `PARTIAL`.

```python
def test_detects_only_enrolled_vanilla(temp_archive):
    service = BlackstarTimerService(temp_archive.profile)
    report = service.detect(temp_archive.game_dir)
    assert report.status is TimerStatus.VANILLA
    assert report.cooldown_seconds == 3600
    assert report.duration_seconds == 600
```

- [ ] **Step 2: Verify the tests fail before implementation**

Run: `python -m pytest tests/test_blackstar_timer_core.py -k detect -vv`

Expected: collection fails because `crimson_common.blackstar_timer` does not exist.

- [ ] **Step 3: Implement immutable types and read-only detection**

Define frozen `TimerProfile`, `ArchiveIdentity`, `DetectionReport`, `PreviewToken`, `TransactionReport`, and `TimerStatus`. Resolve `0008/0.pamt`, `0008/<chunk>.paz`, and `meta/0.papgt`; parse the PAMT with `crimson_rs.parse_pamt_file`; require exactly one `gamedata/characterinfo.pabgb`; read exactly `compressed_size`; decompress with the recorded compression; and classify only exact enrolled hashes and values.

```python
class TimerStatus(str, Enum):
    VANILLA = "vanilla"
    APPLIED = "applied"
    UNKNOWN = "unknown"
    PARTIAL = "partial"
    BACKUP_CONFLICT = "backup_conflict"
    GAME_RUNNING = "game_running"
```

- [ ] **Step 4: Run detection tests and commit**

Run: `python -m pytest tests/test_blackstar_timer_core.py -k detect -vv`

Expected: all detection cases pass and no file mtime changes during detection.

Commit: `feat: add Blackstar timer compatibility detection`

### Task 2: Read-Only Preview and Candidate Verification

**Files:**
- Modify: `tests/test_blackstar_timer_core.py`
- Modify: `crimson_common/blackstar_timer.py`

- [ ] **Step 1: Write failing preview tests**

Record the complete temporary tree before/after `preview()`. Assert no path, bytes, or mtime changes; the candidate has values `1` and `1800`; recompressed bytes fit the existing slot; decompression using the candidate length yields the applied hash; and a changed source invalidates the token.

- [ ] **Step 2: Run the preview tests to observe RED**

Run: `python -m pytest tests/test_blackstar_timer_core.py -k preview -vv`

Expected: failures because `preview()` and token validation are absent.

- [ ] **Step 3: Implement preview and token binding**

Build the candidate solely in memory, verify its field values and SHA-256, compress with the entry's algorithm, verify it fits the original slot, decompress it independently, and return a token bound to normalized game path, all three source hashes, profile ID, entry identity, and candidate hash.

- [ ] **Step 4: Run preview tests and commit**

Run: `python -m pytest tests/test_blackstar_timer_core.py -k preview -vv`

Expected: all preview tests pass with zero filesystem changes.

Commit: `feat: add read-only Blackstar timer preview`

### Task 3: Transaction, Real Compressed Length, Backup, and Restore

**Files:**
- Modify: `tests/test_blackstar_timer_core.py`
- Modify: `crimson_common/blackstar_timer.py`

- [ ] **Step 1: Write failing transaction regression tests**

Assert Apply creates a timestamped backup containing PAZ, PAMT, PAPGT, and `manifest.json`; writes the candidate stream; changes the PAMT entry compressed size to `len(candidate_compressed)`; updates the PAZ chunk checksum/size, PAMT checksum, and PAPGT group checksum; and can decompress by reading exactly the newly declared length.

```python
assert applied_entry["compressed_size"] == len(candidate_compressed)
stream = paz_bytes[offset:offset + applied_entry["compressed_size"]]
assert crimson_rs.decompress_data(stream, 2, profile.body_size) == candidate_body
```

- [ ] **Step 2: Observe RED against current behavior**

Run: `python -m pytest tests/test_blackstar_timer_core.py -k 'apply or compressed_size' -vv`

Expected: failure because Apply does not exist; the companion loader regression demonstrates that padded compressed data with the old declared length cannot be decompressed.

- [ ] **Step 3: Implement guarded Apply and automatic rollback**

Re-detect and match the exact token; check that Crimson Desert is closed; create and hash-verify all backup copies before opening a source for write; patch PAZ; serialize PAMT with actual compressed length and updated chunk metadata; serialize PAPGT with the PAMT checksum; atomically replace metadata; independently re-read and verify; restore all three originals on any failure after backup verification.

- [ ] **Step 4: Implement idempotence and guarded Restore**

Return a no-op `APPLIED` report on a second Apply. Restore only from an owned complete manifest whose backup hashes match and whose post-apply hashes equal the current archive; otherwise return `BACKUP_CONFLICT` without writing.

- [ ] **Step 5: Run transaction fault-injection tests and commit**

Run: `python -m pytest tests/test_blackstar_timer_core.py -k 'apply or restore or rollback or idempotent' -vv`

Expected: Apply, second Apply, each injected write-boundary rollback, Restore, and conflict refusal pass.

Commit: `feat: add transactional Blackstar timer apply and restore`

### Task 4: Repair the Generic Compressed Patch Loader

**Files:**
- Create: `tests/test_mod_loader_compressed_patch.py`
- Modify: `CrimsonGameMods/mod_loader.py`

- [ ] **Step 1: Write the failing generic-loader regression test**

Patch a compact compressed entry to a smaller LZ4 stream and assert the corresponding PAMT file record stores the new stream length, not the old slot capacity; then reparse and decompress only that declared range.

- [ ] **Step 2: Run it to reproduce the bug**

Run: `python -m pytest tests/test_mod_loader_compressed_patch.py -vv`

Expected: decompression fails or the recorded compressed size remains unchanged.

- [ ] **Step 3: Update `_apply_compressed_patch`**

After writing the candidate and padding unused capacity, locate the unique PAMT record, assign its `compressed_size` to the actual stream length, update chunk size/checksum and PAMT/PAPGT integrity, then perform an independent read/decompress verification before success.

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_mod_loader_compressed_patch.py tests/test_blackstar_timer_core.py -vv`

Expected: both the generic path and purpose-built transaction suite pass.

Commit: `fix: persist compressed patch lengths safely`

### Task 5: Shared Responsive Worker

**Files:**
- Create: `tests/test_blackstar_timer_worker.py`
- Create: `crimson_common/blackstar_timer_worker.py`

- [ ] **Step 1: Write failing lifecycle tests**

Use `QCoreApplication` and signal spies to assert phase order, exactly one terminal signal, read-only cancellation before transaction start, cancellation disabled once writing begins, and errors surfaced without success-shaped fallback.

- [ ] **Step 2: Run worker tests to observe RED**

Run: `python -m pytest tests/test_blackstar_timer_worker.py -vv`

Expected: import failure because the worker is absent.

- [ ] **Step 3: Implement `BlackstarTimerWorker`**

Expose `progress(str, int)`, `completed(object)`, `failed(str)`, and `finished()` signals; accept `preview`, `apply`, or `restore`; poll a cancellation event only in read-only phases; call the shared service; emit exactly one terminal result and always emit `finished`.

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_blackstar_timer_worker.py -vv`

Expected: all signal-order and cancellation tests pass.

Commit: `feat: add responsive shared timer worker`

### Task 6: Wire Both Existing Applications

**Files:**
- Create: `tests/test_blackstar_timer_gui_contract.py`
- Modify: `CrimsonSaveEditor/gui.py`
- Modify: `CrimsonGameMods/gui/tabs/patches.py`
- Modify: `CrimsonGameMods/gui/main_window.py`

- [ ] **Step 1: Write failing GUI contract tests**

Assert both applications visibly contain `Preview 30m / 1s`, `Apply Preset`, `Restore Original`, `affects every save`, and `does not change the loaded save`; assert Game Mods exposes `Game Patches`; assert Apply remains disabled until a matching preview token exists; and assert work starts on a `QThread`.

- [ ] **Step 2: Run contracts to observe RED**

Run: `python -m pytest tests/test_blackstar_timer_gui_contract.py -vv`

Expected: missing controls and hidden Game Patches failures.

- [ ] **Step 3: Add equivalent panels and reports**

Place Save Editor controls next to `Unlock Blackstar (No Quest Changes)`. Add the same group to `GamePatchesTab`, expose that tab in Game Mods, share report formatting, invalidate stale tokens when the path changes, and disable conflicting controls while the worker runs.

- [ ] **Step 4: Run GUI contracts and commit**

Run: `python -m pytest tests/test_blackstar_timer_gui_contract.py tests/test_gui_blackstar_contract.py -vv`

Expected: controls, warnings, state transitions, and thread ownership pass in both applications.

Commit: `feat: expose Blackstar timer preset in both tools`

### Task 7: Packaging and Exact Windows Build Documentation

**Files:**
- Modify: `tests/test_packaging_contract.py`
- Modify: `CrimsonGameMods/main.py`
- Modify: `CrimsonSaveEditor/main.py`
- Modify: `CrimsonGameMods/CrimsonGameMods.spec`
- Modify: `CrimsonSaveEditor/CrimsonSaveEditor.spec`
- Create: `docs/windows-build.md`

- [ ] **Step 1: Write failing packaging contracts**

Require repository-root `pathex`, `crimson_common`, worker, `crimson_rs`, and LZ4 in both specs; require source-only repository bootstrap guarded by `not getattr(sys, "frozen", False)`.

- [ ] **Step 2: Run packaging contracts to observe RED**

Run: `python -m pytest tests/test_packaging_contract.py -vv`

Expected: both specs fail shared-package requirements.

- [ ] **Step 3: Update entry points, specs, and build guide**

Document Python 3.12, pinned runtime/dev dependencies, native compiler prerequisites if rebuilding `crimson_rs`, virtual-environment commands, both PyInstaller commands, output executable paths, and safe copied-directory smoke tests. Include backup locations and state explicitly that automated tests never point at the installed game or real saves.

- [ ] **Step 4: Run packaging tests and commit**

Run: `python -m pytest tests/test_packaging_contract.py -vv`

Expected: both application packaging contracts pass.

Commit: `build: package shared Blackstar timer tools`

### Task 8: Inventory 100 Percent of Both Current Interfaces

**Files:**
- Create: `docs/superpowers/specs/2026-07-17-crimson-ui-redesign.md`
- Create: `tests/test_ui_feature_inventory.py`

- [ ] **Step 1: Extract the current navigation and commands**

Use structural search and Qt object names to enumerate every menu, top tab, bottom tab, button, context action, dialog entry point, status field, and timer control in both applications. Record the current owner method and the redesigned destination for each item.

- [ ] **Step 2: Encode the inventory as failing tests**

Parametrize the required action labels/object names and assert every entry remains reachable after the shell replacement. Include Blackstar ownership and timer actions in the same inventory.

- [ ] **Step 3: Finalize the approved Crimson Desert UI spec**

Specify squared translucent obsidian panels, narrow bronze separators, parchment text, restrained crimson emphasis, expressive serif display type with readable condensed body type, horizontal game-style navigation, dense data tables, bottom command hints, keyboard focus, 1366x768 minimum layout, high-DPI behavior, and no generic dashboard cards or pill controls.

- [ ] **Step 4: Commit the inventory and UI spec**

Run: `python -m pytest tests/test_ui_feature_inventory.py -vv`

Expected: initial failures identify the navigation elements the redesign must wire.

Commit: `test: lock complete editor feature inventory`

### Task 9: Shared Crimson Desert Visual Language

**Files:**
- Create: `CrimsonSaveEditor/crimson_theme.py`
- Create: `CrimsonGameMods/gui/crimson_theme.py`
- Modify: `CrimsonSaveEditor/gui.py`
- Modify: `CrimsonGameMods/gui/main_window.py`

- [ ] **Step 1: Add failing theme and accessibility contracts**

Assert named colors, typography roles, focus states, selection contrast, reduced-motion handling, minimum control heights, and high-DPI-safe icon sizes exist in both theme entry points.

- [ ] **Step 2: Implement the token vocabulary and application shells**

Use `ink`, `obsidian`, `charcoal`, `bronze`, `parchment`, `ash`, and `crimson` tokens. Replace the old DOS-like presentation with a horizontal title/nav band, contextual action strip, main workspace, persistent status rail, and bottom command hints while reusing existing widgets and callbacks.

- [ ] **Step 3: Verify feature inventory and commit**

Run: `python -m pytest tests/test_ui_feature_inventory.py tests/test_blackstar_timer_gui_contract.py -vv`

Expected: every existing command remains reachable and timer controls remain equivalent.

Commit: `feat: add Crimson Desert application shells`

### Task 10: Redesign Every Existing Surface Without Feature Loss

**Files:**
- Modify: `CrimsonSaveEditor/gui.py`
- Modify: `CrimsonGameMods/gui/main_window.py`
- Modify: `CrimsonGameMods/gui/tabs/*.py`
- Modify: the existing Save Editor dialogs reached by the feature inventory

- [ ] **Step 1: Migrate surfaces in inventory order**

Restyle menus, save browser, inventory/item tools, character and mount tools, knowledge, quests, package browsers, field/game-data tools, mod loader, patch tools, editors, dialogs, tables, progress/report surfaces, and status bars. Preserve callbacks and persistence keys; assign stable object names where absent.

- [ ] **Step 2: Add layout regression tests**

Instantiate both main windows offscreen at 1366x768 and 1920x1080; assert no required navigation control is hidden, all tab pages can be selected, dialogs fit the available screen, and table headers remain readable.

- [ ] **Step 3: Run complete inventory and GUI suites**

Run: `python -m pytest tests/test_ui_feature_inventory.py tests/test_blackstar_timer_gui_contract.py tests/test_gui_blackstar_contract.py tests/test_gui_save_contract.py -vv`

Expected: full feature reachability and existing behavior contracts pass.

- [ ] **Step 4: Commit the complete surface redesign**

Commit: `feat: redesign both Crimson Desert tool interfaces`

### Task 11: Remove Remaining GUI-Thread Stalls

**Files:**
- Create: `tests/test_ui_responsiveness_contract.py`
- Modify: blocking entry points identified in `CrimsonSaveEditor/gui.py`
- Modify: blocking entry points identified in `CrimsonGameMods/gui/main_window.py` and `CrimsonGameMods/gui/tabs/*.py`

- [ ] **Step 1: Audit and write failing responsiveness contracts**

Find filesystem walks, save parsing, archive parsing, compression, encryption, serialization, database loading, and bulk table population reachable from button callbacks. Assert expensive functions are invoked by workers and UI updates are chunked on the main thread.

- [ ] **Step 2: Move blocking work behind workers**

Reuse existing worker patterns where available; provide phase text and determinate progress when countable; disable only conflicting controls; guarantee cleanup on success, error, and cancellation; and surface exceptions in the application log and dialog.

- [ ] **Step 3: Run responsiveness and behavior tests**

Run: `python -m pytest tests/test_ui_responsiveness_contract.py tests/test_blackstar_worker.py tests/test_blackstar_timer_worker.py -vv`

Expected: no audited expensive action runs synchronously from a GUI callback.

- [ ] **Step 4: Commit the responsiveness pass**

Commit: `fix: keep editor interfaces responsive during heavy work`

### Task 12: Full Verification, Builds, Review, and GitHub Push

**Files:**
- Modify only files needed to resolve verified defects.

- [ ] **Step 1: Run the complete tracked test suite**

Run: `python -m pytest tests -vv --ignore=tests/fixtures --ignore=tests/generated`

Expected: all tracked tests pass; no installed game path or real save appears in test logs.

- [ ] **Step 2: Perform adversarial source and safety review**

Inspect token invalidation, unknown-schema refusal, backup verification, rollback boundaries, restore conflict handling, game-running checks, thread ownership, all feature-inventory mappings, and staging scope. Run `git diff --check` and confirm `git status --short` lists no generated executables, fixtures, copied saves, backups, or `.superpowers` files for staging.

- [ ] **Step 3: Build both Windows executables fresh**

Run from the activated environment:

```powershell
python -m PyInstaller --noconfirm --clean CrimsonSaveEditor\CrimsonSaveEditor.spec
python -m PyInstaller --noconfirm --clean CrimsonGameMods\CrimsonGameMods.spec
```

Expected outputs:

- `CrimsonSaveEditor/dist/CrimsonSaveEditorStandalone.exe`
- `CrimsonGameMods/dist/CrimsonGameMods.exe`

- [ ] **Step 4: Smoke-test only copied synthetic directories**

Launch each executable, Preview the compact copied archive, Apply, verify `1` and `1800`, Apply again as a no-op, Restore, and verify vanilla hashes and values. Exercise every navigation destination from the feature inventory. Do not select the installed Crimson Desert directory or any real save.

- [ ] **Step 5: Commit any final verified corrections**

Run focused RED/GREEN tests for each correction, rerun the full suite, and commit with a specific defect message.

- [ ] **Step 6: Push the completed branch to the user's fork**

Verify `origin` is the user's fork and push:

```powershell
git push -u origin codex/blackstar-unlock-safety
```

Expected: the remote branch contains source, tests, specs, and docs only; local copied fixtures, generated saves, backups, and build artifacts remain untracked or ignored.

## Self-Review

- Spec coverage: Tasks 1-7 cover the complete approved timer safety design; Tasks 8-11 cover the separately approved complete two-application UI redesign and responsiveness goal; Task 12 covers builds, adversarial review, and GitHub delivery.
- Placeholder scan: no `TBD`, implementation deferrals, or unspecified error-handling steps remain.
- Type consistency: `TimerStatus`, `TimerProfile`, `PreviewToken`, `DetectionReport`, `TransactionReport`, `BlackstarTimerService`, and `BlackstarTimerWorker` keep the same names and responsibilities throughout.
- Safety boundary: all mutation tests use temporary synthetic archives; no plan step writes an installed game or real save.
