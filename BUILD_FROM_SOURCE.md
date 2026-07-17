# Build the Crimson Save Editor on Windows

These commands build and test the standalone save editor. Run them from the
repository root in 64-bit PowerShell. Do not point an unverified build at your
live game save; the dry-run example below uses only a temporary copy of the
fixture under `tests/fixtures`.

## Required software

- 64-bit CPython 3.12 from python.org (the verified environment used Python 3.12.6).
- Microsoft Visual C++ 2015-2022 Redistributable (x64), required by the shipped
  Windows native parser and Qt binaries.
- Git, if you are cloning rather than using an existing checkout.
- PowerShell 5.1 or newer.

`dumpbin.exe` was not available in the verification environment, so the native
dependency table could not be enumerated with `dumpbin /DEPENDENTS`. The bundled
`CrimsonSaveEditor/parc_parser.dll` is 399,360 bytes and has SHA-256
`AC7B26C8984E86FAE4C6982EFCC13A7201CE5788A386A354BD280D67274CDFD7`.

## Python dependencies

Direct runtime dependencies are pinned in `CrimsonSaveEditor/requirements.txt`:

| Dependency | Version | Purpose |
|---|---:|---|
| PySide6 | 6.8.3 | Qt desktop interface |
| lz4 | 4.4.5 | Save payload compression/decompression |
| cryptography | 49.0.0 | ChaCha20 implementation |

PySide6 installs matching `PySide6_Addons`, `PySide6_Essentials`, and
`shiboken6` 6.8.3. Cryptography installs `cffi` and `pycparser`.

Development/build dependencies are pinned in
`CrimsonSaveEditor/requirements-dev.txt`: PyInstaller 6.21.0, pytest 9.1.1,
and pytest-timeout 2.4.0. PyInstaller also installs altgraph, packaging,
pefile, pyinstaller-hooks-contrib, pywin32-ctypes, and setuptools.

For an exact reproducibility check, the verified virtual environment resolved
to this complete package set (direct and transitive):

```text
altgraph==0.17.5
cffi==2.1.0
colorama==0.4.6
cryptography==49.0.0
iniconfig==2.3.0
lz4==4.4.5
packaging==26.2
pefile==2024.8.26
pluggy==1.6.0
pycparser==3.0
Pygments==2.20.0
pyinstaller==6.21.0
pyinstaller-hooks-contrib==2026.6
PySide6==6.8.3
PySide6_Addons==6.8.3
PySide6_Essentials==6.8.3
pytest==9.1.1
pytest-timeout==2.4.0
pywin32-ctypes==0.2.3
setuptools==83.0.0
shiboken6==6.8.3
```

`crimson_rs` is required for the shared Blackstar game-timer feature. It supports
game-archive extraction and mod-packing features, is not published on PyPI, and
is included in this repository as a prebuilt native package. Save loading,
encryption, Blackstar ownership unlock, compatibility checks, backups, and atomic
save writes do not depend on it; the Blackstar game-timer preset does. The
compatible native module is bundled under
`CrimsonGameMods\crimson_rs` and the standalone PyInstaller spec packages it.

Pillow is not a dependency: the source has no Pillow import and PyInstaller does
not require it for this build.

## Expected optional-module warnings

PyInstaller's warning report may include Windows-inapplicable standard-library
modules such as `pwd`, `grp`, `posix`, `resource`, `termios`, and `fcntl`; these
are not Windows dependencies. It may also report delayed game-mod helper imports
such as `paz_parse`, `dropset_editor`,
`pipeline_report`, `wantedinfo_parser`, and `mod_loader`. Those helpers belong to
the separate `CrimsonGameMods` surface (or are absent experimental modules), so
their related game-mod tabs may be unavailable in the Save Editor standalone.
Build `CrimsonGameMods` separately if you need that surface.

The Blackstar/save pipeline modules (`app_logging`, `blackstar_compat`,
`blackstar_template`, `blackstar_unlock`,
`blackstar_worker`, `parc_inserter3`, `parc_serializer`, `save_compat`,
`save_crypto`, and `save_parser`) must not appear as missing. They were all
collected in the verified build.

## Create the environment

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r CrimsonSaveEditor\requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
```

## Verify only copied fixtures

First verify the immutable fixture guards:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_fixture_integrity.py -v
```

Create a temporary copy and run the Blackstar dry-run. This command decrypts and
analyzes the copy but never serializes or writes it:

```powershell
$scratch = Join-Path ([IO.Path]::GetTempPath()) "crimson-blackstar-build-test"
New-Item -ItemType Directory -Force -Path $scratch | Out-Null
$copiedSave = Join-Path $scratch "save.save"
Copy-Item -LiteralPath tests\fixtures\slot102\save.save -Destination $copiedSave -Force
$env:PYTHONPATH = (Resolve-Path CrimsonSaveEditor).Path
.\.venv\Scripts\python.exe -m blackstar_unlock --dry-run --save $copiedSave
```

The report must show `quest_changes: 0` and `knowledge_changes: 0`. The copied encrypted file hash must be
unchanged because dry-run returns no output blob and has no write path.

Run the complete automated suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -v --timeout=600
```

Tests create writable save copies only under pytest temporary directories.
`tests/fixtures/save.save` and `tests/fixtures/lobby.save` are guarded by their
committed SHA-256 values and are never write destinations.

## Build the executable

```powershell
Push-Location CrimsonSaveEditor
..\.venv\Scripts\python.exe -m PyInstaller CrimsonSaveEditor.spec --noconfirm --clean
Pop-Location
```

Expected artifact:

```text
CrimsonSaveEditor\dist\CrimsonSaveEditorStandalone.exe
```

The root wrapper is also valid for the PyInstaller backend:

```powershell
.\build.cmd --project saveeditor --target full --backend pyinstaller
```

## Packaged native and data files

`CrimsonSaveEditor.spec` packages the native `parc_parser.dll`; the
`save_schema_profiles.json` compatibility manifest; item, store, item-template,
master-template, limit, category, enchant, waypoint, abyss-gimmick, knowledge,
quest, mission, stage, respawn, quest-chain, dye-slot, buff-description, map,
localization TSV, and standalone-version files; plus the complete `locale/` and
`knowledge_packs/` directories. It also declares the parser, serializer,
logging, compatibility, Blackstar service, and Blackstar worker modules as
hidden imports.

## Runtime safety behavior

- Logs are written to `%LOCALAPPDATA%\CrimsonSaveEditor\logs\crimson-save-editor.log`.
- Unknown full schemas load read-only for general editing. Blackstar Preview may
  grant only its feature-scoped operation when all seven touched type signatures match.
- Every GUI save creates and hash-verifies a backup before writing a sibling temp file.
  Save As preserves an existing destination (the file at risk); a new destination
  preserves the loaded source instead.
- The temp file is decrypted and schema-validated before atomic replacement.
- A destination hash is rechecked immediately before replacement, so an external
  change made after backup aborts the write instead of being overwritten.
- Blackstar defaults to Preview and runs parsing, validation, mandatory backup,
  and its explicitly authorized Apply & Save transaction on a background thread.

If a build fails, keep the full PyInstaller output and the application operation
ID from any error dialog. Do not work around a missing manifest, parser DLL,
unknown schema, failed backup, or failed temporary validation.
