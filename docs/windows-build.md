# Windows Build Guide

This repository produces two separate Windows desktop applications:

- `CrimsonSaveEditor\dist\CrimsonSaveEditorStandalone.exe`
- `CrimsonGameMods\dist\CrimsonGameMods.exe`

The applications share the Blackstar timer service in `crimson_common`. Build both
from the repository root so the shared package and native archive runtime are
available to PyInstaller.

## Dependencies

Install these prerequisites:

- 64-bit CPython 3.12
- Microsoft Visual C++ 2015-2022 Redistributable (x64)
- Windows PowerShell 5.1 or PowerShell 7
- Git for Windows if cloning or committing changes

The pinned Python packages are:

- `PySide6==6.8.3`
- `lz4==4.4.5`
- `cryptography==49.0.0`
- `pyinstaller==6.21.0`
- `pytest==9.1.1`
- `pytest-timeout==2.4.0`

The repository also contains required prebuilt 64-bit native files. They are not
installed from PyPI:

| File | Size | SHA-256 |
| --- | ---: | --- |
| `CrimsonGameMods\crimson_rs\crimson_rs.pyd` | 7,133,696 | `CCF25C5500E97F0C93D1A6E81CA96B80B64B2147FA2701A68245B11FD0533855` |
| `CrimsonGameMods\dmm_parser\dmm_parser.pyd` | 7,191,040 | `596CCB0AF8A7582C1C404E562C3E72D77F673C78E5981BCC6BB35BA6866ABF70` |
| `CrimsonGameMods\parc_parser.dll` | 399,360 | `AC7B26C8984E86FAE4C6982EFCC13A7201CE5788A386A354BD280D67274CDFD7` |
| `CrimsonSaveEditor\parc_parser.dll` | 399,360 | `AC7B26C8984E86FAE4C6982EFCC13A7201CE5788A386A354BD280D67274CDFD7` |

Rebuilding `crimson_rs.pyd` or `dmm_parser.pyd` requires their separate Rust
source projects, the Rust MSVC toolchain, and Microsoft C++ Build Tools. Those
sources are not required to build these applications from this repository.

## Create The Environment

Run from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r CrimsonSaveEditor\requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -r CrimsonGameMods\requirements-dev.txt
$env:PYTHONPATH = "$PWD\CrimsonSaveEditor;$PWD\CrimsonGameMods"
```

## Verify Source

The automated tests use temporary archives and copied fixture saves. They never
point at the installed game or a real save.

```powershell
$env:PYTHONPATH = "$PWD\CrimsonSaveEditor;$PWD\CrimsonGameMods"
.\.venv\Scripts\python.exe -m pytest tests -q
```

For a manual Blackstar timer smoke test, use only a copied synthetic game
directory containing copied `0008` and `meta` test data. Do not select the
installed game directory. Preview first; Preview is read-only. Apply creates a
verified backup under
`<copied-game>\bin64\SEModLoad\Backups\BlackstarTimer\<timestamp>` before any
write. Restore accepts only a complete backup owned by this tool.

## Build Both Executables

Build each spec from its component directory:

```powershell
Push-Location CrimsonSaveEditor
..\.venv\Scripts\python.exe -m PyInstaller CrimsonSaveEditor.spec --noconfirm --clean
Pop-Location

Push-Location CrimsonGameMods
..\.venv\Scripts\python.exe -m PyInstaller CrimsonGameMods.spec --noconfirm --clean
Pop-Location
```

The completed executables are:

- `CrimsonSaveEditor\dist\CrimsonSaveEditorStandalone.exe`
- `CrimsonGameMods\dist\CrimsonGameMods.exe`

Item icons are not packed into the executable to keep the download small.
Icons are on by default; on first launch the Save Editor offers to download
the icon set (about 70 MB) from GitHub on a worker pool with a cancelable
progress dialog, storing it in `icons_local\` next to the executable. The
"Download Icons…" toolbar button starts or resumes the same download. Placing
a prebuilt `icons_bundle.zip` (zip of `icons_local/` and `icons_mercenary/`)
next to the executable seeds the set offline instead.

Launch each executable without a command-line file for the first smoke test.
Confirm that both display the Blackstar timer panel. If testing Apply or Restore,
select only the copied synthetic game directory and keep Crimson Desert closed.
Do not select the installed game directory during development or verification.
