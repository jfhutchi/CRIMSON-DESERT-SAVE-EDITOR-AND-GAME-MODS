# Crimson Game Mods

A PySide6 desktop tool for modifying **Crimson Desert** game data via PAZ archive overlays. Companion to the [Crimson Save Editor (Standalone)](../releases) — this build is for `.pabgb` / PAZ modding, not save editing.

## Features

| Tab | What it does |
|---|---|
| **ItemBuffs** | Inject custom stats / buffs / enchants into `iteminfo.pabgb`. 28 stat hashes, presets from dev rings, in-game inventory lookup. |
| **Stores** | Edit vendor prices, purchase limits, and stock on `storeinfo.pabgb` (254 stores). Inline editable Limit / Buy / Sell cells. |
| **DropSets** | Modify item drop rates / quantities / keys in `dropsetinfo.pabgb`. Inline-editable rate/qty columns. |
| **SpawnEdit** | Edit creature / NPC / faction spawn counts, cooldowns, and region assignments across 6+ pabgb spawn tables. |
| **FieldEdit** | Unified editor for vehicle / region / mount / gimmick info — enable mounts in towns, tweak ride duration, adjust zone flags. |
| **Items → Database** | Readonly item lookup by key/name (used as reference for mod tabs). |

## Install

1. Download the latest `CrimsonGameMods.exe` from the [Releases page](../releases).
2. Place it in a folder where you want its config / backups to live.
3. Run it. The first time, point the "Game Path" bar at your Crimson Desert install (the tool tries to auto-detect).

## Build from source

These instructions are for 64-bit Windows. Install:

- 64-bit CPython 3.12 (the verified build used Python 3.12.6)
- Microsoft Visual C++ 2015-2022 Redistributable (x64), required by the bundled native modules
- Windows PowerShell 5.1 or newer
- Git only if you need to clone the repository

From the repository root, create an isolated environment and install the exact build set:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r CrimsonGameMods\requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
```

Runtime dependencies are pinned in `CrimsonGameMods\requirements.txt`:

| Dependency | Version | Purpose |
| --- | ---: | --- |
| PySide6 | 6.8.3 | Windows GUI and worker-thread integration |
| lz4 | 4.4.5 | Save/game-data compression support |
| cryptography | 49.0.0 | Encrypted data support |

Build and test dependencies are pinned in `CrimsonGameMods\requirements-dev.txt`: PyInstaller 6.21.0, pytest 9.1.1, and pytest-timeout 2.4.0. The complete resolved Python environment used for verification is: altgraph 0.17.5, cffi 2.1.0, colorama 0.4.6, cryptography 49.0.0, iniconfig 2.3.0, lz4 4.4.5, packaging 26.2, pefile 2024.8.26, pluggy 1.6.0, pycparser 3.0, Pygments 2.20.0, pyinstaller 6.21.0, pyinstaller-hooks-contrib 2026.6, PySide6 6.8.3, PySide6-Addons 6.8.3, PySide6-Essentials 6.8.3, pytest 9.1.1, pytest-timeout 2.4.0, pywin32-ctypes 0.2.3, setuptools 83.0.0, and shiboken6 6.8.3.

The repository also contains required prebuilt native files that are bundled by the spec and are not installed from PyPI:

| File | Size | SHA-256 | Purpose |
| --- | ---: | --- | --- |
| `CrimsonGameMods\crimson_rs\crimson_rs.pyd` | 7,133,696 bytes | `CCF25C5500E97F0C93D1A6E81CA96B80B64B2147FA2701A68245B11FD0533855` | PAZ extraction/building and PAPGT serialization |
| `CrimsonGameMods\dmm_parser\dmm_parser.pyd` | 7,191,040 bytes | `596CCB0AF8A7582C1C404E562C3E72D77F673C78E5981BCC6BB35BA6866ABF70` | Native PABGB parsing used by game-mod features |
| `CrimsonGameMods\parc_parser.dll` | 399,360 bytes | `AC7B26C8984E86FAE4C6982EFCC13A7201CE5788A386A354BD280D67274CDFD7` | PARC parsing support loaded by the application |

Pillow is not required to run, test, or build the application; it is used only by the optional `tools\regen_splash.py` artwork utility. NumPy appears only in disconnected optional model helpers and is not part of the packaged application dependency set.

To run the complete tests, use a copied fixture only. The installed game path is read for compatibility checks; tests that exercise writes create temporary copied game trees:

```powershell
$env:PYTHONPATH = (Resolve-Path CrimsonGameMods).Path
$env:CRIMSON_DESERT_GAME_PATH = 'D:\SteamLibrary\steamapps\common\Crimson Desert'
.\.venv\Scripts\python.exe -m pytest tests -v --timeout=300
```

Omit `CRIMSON_DESERT_GAME_PATH` when the game is not installed; the installed-schema integration test will skip. Build the executable with:

```powershell
Push-Location CrimsonGameMods
..\.venv\Scripts\python.exe -m PyInstaller CrimsonGameMods.spec --noconfirm --clean
Pop-Location
```

The output is `CrimsonGameMods\dist\CrimsonGameMods.exe`. The repo-root `build.cmd` remains an alternative build entry point.

## Save File Integration

The tool can optionally load your `.save` file to display the items you actually have in your inventory — useful for targeting the exact items you want to buff in ItemBuffs. Save loading is on-demand (click "My Inventory" in ItemBuffs), not automatic.

The Save Browser panel can be popped open as a floating window via the "Save Browser" button in the top-right of the main tab bar.

## How mods are applied

ItemBuffs / Stores / DropSets / SpawnEdit / FieldEdit write modified `.pabgb` files into PAZ overlay directories (e.g. `0036/`, `0039/`, `0058/`, `0060/`) plus regenerate PAPGT metadata. Mods are installed via PAZ front-insertion — the game loads overlays before the base archive, so changes take effect on next launch.

Each tab can also **export a CDUMM-compatible mod package** (for users of the [CDUMM Mod Manager](https://github.com/...)) via the "Export as CDUMM Mod" button.

## Restore / Backup

Every patch writes to a side PAZ directory. Restore = delete the overlay directory and restore the original PAPGT. The tool handles both automatically via its Restore UI.

## License

[Mozilla Public License 2.0](LICENSE). See [CREDITS.md](CREDITS.md) for contributor attribution.

## Disclaimer

This is an unofficial, non-commercial modding utility for **Crimson Desert** (© [Pearl Abyss](https://www.pearlabyss.com/)). No game assets or proprietary data are redistributed — all extraction happens locally from the user's own installed copy of the game. Use at your own risk; always back up your game files.
