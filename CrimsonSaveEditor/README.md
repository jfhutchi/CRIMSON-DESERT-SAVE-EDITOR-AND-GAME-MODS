# Crimson Save Editor

A PySide6 desktop editor for encrypted Crimson Desert saves. It supports
inventory, equipment, quests, knowledge, abyss gates, dyes, mercenaries, and
related PARC structures.

## Blackstar safety

The no-quest Blackstar action defaults to Preview (dry run), runs outside the Qt
GUI thread, and validates a legitimate 1.14 ownership record without changing
quests or knowledge. A successful preview authorizes Apply & Save only for the
exact unchanged source and candidate. Apply creates a verified encrypted backup,
validates a temporary save, and atomically replaces the selected file. Running
the operation twice is a byte-identical no-op; recognized obsolete 206-byte
Blackstar records are replaced rather than duplicated.

General GUI writes require a known compatibility profile. Blackstar uses a
narrow compatibility family covering only its mount/equipment structures and
does not enable any other editor write on an unknown full schema. Before every write the editor
creates and SHA-256-verifies an encrypted backup, writes a sibling temporary
file, decrypts and validates it, and only then atomically replaces the
destination. Save As backs up an existing destination rather than an unrelated
loaded slot, and a last-moment destination hash check rejects concurrent changes.

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
