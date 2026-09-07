# Save safety regression tests

Run commands from the repository root. These tests use synthetic containers and
PARC objects; they do not require a game installation or private save files.

## Python

```powershell
python -m pip install -r tests/requirements.txt
python -m pytest tests -q
```

The ordinary run covers both Python container writers, Game Mods field writes
and read-only scanning, native bridge error handling, and asynchronous knowledge
job identity. GUI handler tests execute the actual method bodies against small
widget harnesses without launching the full application or loading game data.

Tests in `test_native_dll.py` skip unless `CSE_NATIVE_DLL` is set. A missing or
unloadable explicitly selected DLL fails the tests instead of silently skipping.

## C++ and the real Python/DLL boundary (Windows)

Install Visual Studio's Desktop development with C++ workload and CMake. With
Visual Studio 2022:

```powershell
cmake -S CrimsonSaveEditorCpp -B CrimsonSaveEditorCpp/build -G "Visual Studio 17 2022" -A x64
cmake --build CrimsonSaveEditorCpp/build --config Release
ctest --test-dir CrimsonSaveEditorCpp/build -C Release --output-on-failure
$env:CSE_NATIVE_DLL = (Resolve-Path CrimsonSaveEditorCpp/build/Release/parc_parser.dll).Path
python -m pytest tests -q
```

For Visual Studio 2026 use `-G "Visual Studio 18 2026"` in a separate clean build
directory. `BUILD_TESTING` defaults to `ON`; pass `-DBUILD_TESTING=OFF` to omit the
test executables. The optional Qt shell is not needed by these tests.

CTest checks versioned encrypted container roundtrips, the known version-2 key,
unsupported versions, malformed PARC table bounds, byte-stable serialization,
and native file replacement. Windows replacement-failure tests allow ordinary
writes to the destination while denying delete/replace access: this catches
writers that truncate an existing file instead of staging a candidate. Another
test rejects a reopened candidate before installation.

The opt-in Python tests use the newly built DLL for in-place validated writes,
schema mismatch rejection, direct C ABI calls, null output arguments, and
temporary-file cleanup. Native crash probes run in child processes. The tests
never overwrite the checked-in DLL.

## Application packaging

See `BUILD_FROM_SOURCE.md` for PyInstaller commands. CTest and the focused GUI
harnesses do not establish that every application feature or packaged executable
works. The ImGui application also needs runtime item/icon data described in
`CrimsonSaveEditorCpp/README.md`. Proprietary fixture checks and in-game testing
must be performed separately on disposable copies; do not add private saves to
this suite.
