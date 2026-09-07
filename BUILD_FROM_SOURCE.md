# Build from Source

## Prerequisites

- **Python 3.12+** from [python.org](https://www.python.org/downloads/)
  - **Do NOT use the Microsoft Store version** — it restricts site-packages and breaks PyInstaller
  - Check "Add Python to PATH" during install
- **pip packages**: `PySide6 lz4 cryptography Pillow pyinstaller`

## Windows

```bat
pip install PySide6 lz4 cryptography Pillow pyinstaller

:: Build Game Mods
cd CrimsonGameMods
python -m PyInstaller CrimsonGameMods.spec --noconfirm
:: Output: CrimsonGameMods\dist\CrimsonGameMods.exe

:: Build Save Editor
cd ..\CrimsonSaveEditor
python -m PyInstaller CrimsonSaveEditor.spec --noconfirm
:: Output: CrimsonSaveEditor\dist\CrimsonSaveEditorStandalone.exe
```

Or use `build.bat` inside `CrimsonGameMods/` — it clears caches and runs PyInstaller for you.

The Python Save Editor's save validation and writes use `parc_parser.dll`. When
changing native code, build `CrimsonSaveEditorCpp` first (see its README), then
copy `CrimsonSaveEditorCpp/build/Release/parc_parser.dll` into
`CrimsonSaveEditor/parc_parser.dll` before packaging. The spec bundles that file;
it does not rebuild the DLL. Do not commit generated DLLs as part of a source fix.

For synthetic Python/C++ regression tests and real DLL integration checks, see
`TESTING.md`. These checks do not require a game installation.

## Linux / SteamOS

```bash
sudo apt install python3 python3-pip git   # Debian/Ubuntu/SteamOS
pip install PySide6 lz4 cryptography Pillow pyinstaller

git clone https://github.com/NattKh/CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS.git
cd CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS/CrimsonGameMods

python -m PyInstaller CrimsonGameMods.spec --noconfirm
```

## Note on native extensions

The tools use `dmm_parser` (Rust-based parser). Pre-built `.pyd` (Windows) and `.abi3.so` (Linux) binaries ship with the repo in `CrimsonGameMods/dmm_parser/`. You do not need Rust installed to build.

## Troubleshooting

| Error | Fix |
|-------|-----|
| "Unable to locate PySide6/shiboken6 shared libraries" | You're using MS Store Python. Uninstall it and install from [python.org](https://www.python.org/downloads/) |
| `pip` not found | Re-run Python installer, check "Add Python to PATH" |
| `ModuleNotFoundError: No module named 'PySide6'` | Run `pip install PySide6` (make sure you're using the right pip — `python -m pip install PySide6`) |
