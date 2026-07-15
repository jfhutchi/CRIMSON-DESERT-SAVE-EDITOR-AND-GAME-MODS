# Crimson Save Editor

A PySide6 desktop editor for encrypted Crimson Desert saves. It supports
inventory, equipment, quests, knowledge, abyss gates, dyes, mercenaries, and
related PARC structures.

## Blackstar safety

The no-quest Blackstar action defaults to dry-run, runs outside the Qt GUI
thread, reports phase progress, inserts no quest completion entries, and rejects
unknown schemas, duplicate Blackstar mounts, duplicate requested knowledge, or
any candidate whose canonical quest semantics change. Applying twice is a
byte-identical no-op.

GUI writes require a known compatibility profile. Before every write the editor
creates and SHA-256-verifies an encrypted backup, writes a sibling temporary
file, decrypts and validates it, and only then atomically replaces the
destination.

## Windows build

From the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r CrimsonSaveEditor\requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -v --timeout=600
Push-Location CrimsonSaveEditor
..\.venv\Scripts\python.exe -m PyInstaller CrimsonSaveEditor.spec --noconfirm --clean
Pop-Location
```

Output: `CrimsonSaveEditor\dist\CrimsonSaveEditorStandalone.exe`.

See `BUILD_FROM_SOURCE.md` in the repository root for the complete dependency
inventory, fixture-copy dry-run command, optional `crimson_rs` limitations,
native runtime requirement, packaged data list, and troubleshooting guidance.
