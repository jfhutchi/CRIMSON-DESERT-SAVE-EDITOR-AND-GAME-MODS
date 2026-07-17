from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / "CrimsonSaveEditor"


def test_spec_bundles_blackstar_safety_modules_and_schema_manifest() -> None:
    spec = (EDITOR / "CrimsonSaveEditor.spec").read_text(encoding="utf-8")
    assert "('save_schema_profiles.json', '.')" in spec
    for module in ("app_logging", "save_compat", "blackstar_compat", "blackstar_template", "blackstar_unlock", "blackstar_worker"):
        assert f"'{module}'" in spec


def test_direct_dependencies_are_pinned_and_publicly_installable() -> None:
    runtime = (EDITOR / "requirements.txt").read_text(encoding="utf-8")
    development = (EDITOR / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "PySide6==6.8.3" in runtime
    assert "lz4==" in runtime
    assert "cryptography==" in runtime
    assert "crimson_rs" not in runtime
    assert "Pillow" not in runtime + development
    assert "-r requirements.txt" in development
    assert "pyinstaller==" in development
    assert "pytest==" in development
    assert "pytest-timeout==" in development


def test_windows_docs_use_isolated_python_and_fixture_copy_only() -> None:
    docs = (ROOT / "BUILD_FROM_SOURCE.md").read_text(encoding="utf-8")
    assert "py -3.12 -m venv .venv" in docs
    assert ".\\.venv\\Scripts\\python.exe -m pip install" in docs
    assert ".\\.venv\\Scripts\\python.exe -m pytest" in docs
    assert "tests\\fixtures\\slot102\\save.save" in docs
    assert "Copy-Item" in docs
    assert "-m blackstar_unlock --dry-run" in docs
    assert "-m PyInstaller CrimsonSaveEditor.spec --noconfirm --clean" in docs
    assert "Microsoft Visual C++ 2015-2022 Redistributable (x64)" in docs
    assert "crimson_rs" in docs
    assert "not published on PyPI" in docs


def test_game_mods_packages_dragon_wheel_modules() -> None:
    spec = (ROOT / "CrimsonGameMods" / "CrimsonGameMods.spec").read_text(
        encoding="utf-8"
    )
    assert "'dragon_wheel_patch'" in spec
    assert "'dragon_wheel_deploy'" in spec
    assert "'gui.tabs.reserveslot'" in spec
    assert "'reserveslot_parser'" not in spec


def test_game_mods_windows_build_is_pinned_and_documents_native_dependencies() -> None:
    game_mods = ROOT / "CrimsonGameMods"
    runtime = (game_mods / "requirements.txt").read_text(encoding="utf-8")
    development = (game_mods / "requirements-dev.txt").read_text(encoding="utf-8")
    readme = (game_mods / "README.md").read_text(encoding="utf-8")

    assert "PySide6==6.8.3" in runtime
    assert "lz4==4.4.5" in runtime
    assert "cryptography==49.0.0" in runtime
    assert "-r requirements.txt" in development
    assert "pyinstaller==6.21.0" in development
    assert "pytest==9.1.1" in development
    assert "pytest-timeout==2.4.0" in development
    assert "py -3.12 -m venv .venv" in readme
    assert "CrimsonGameMods\\requirements-dev.txt" in readme
    assert "-m PyInstaller CrimsonGameMods.spec --noconfirm --clean" in readme
    assert "Microsoft Visual C++ 2015-2022 Redistributable (x64)" in readme
    assert "crimson_rs" in readme
    assert "dmm_parser" in readme
    assert "Pillow is not required" in readme


def test_both_specs_bundle_shared_timer_and_native_archive_runtime() -> None:
    specs = [
        ROOT / "CrimsonSaveEditor" / "CrimsonSaveEditor.spec",
        ROOT / "CrimsonGameMods" / "CrimsonGameMods.spec",
    ]
    for path in specs:
        spec = path.read_text(encoding="utf-8")
        assert "REPO_ROOT" in spec
        assert "crimson_common" in spec
        assert "crimson_common.blackstar_timer" in spec
        assert "crimson_common.blackstar_timer_worker" in spec
        assert "crimson_common.blackstar_timer_ui" in spec
        assert "crimson_common.crimson_theme" in spec
        assert "crimson_rs" in spec
        assert "lz4.block" in spec

    assert "'crimson_theme'" in specs[0].read_text(encoding="utf-8")
    assert "'gui.crimson_theme'" in specs[1].read_text(encoding="utf-8")


def test_source_entry_points_bootstrap_repository_shared_packages() -> None:
    for relative in ("CrimsonSaveEditor/main.py", "CrimsonGameMods/main.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert 'if not getattr(sys, "frozen", False):' in source
        assert "REPO_ROOT" in source
        assert "sys.path.insert" in source


def test_unified_windows_build_guide_lists_every_timer_dependency() -> None:
    guide = (ROOT / "docs" / "windows-build.md").read_text(encoding="utf-8")
    for expected in (
        "CPython 3.12",
        "PySide6==6.8.3",
        "lz4==4.4.5",
        "cryptography==49.0.0",
        "pyinstaller==6.21.0",
        "pytest==9.1.1",
        "pytest-timeout==2.4.0",
        "crimson_rs.pyd",
        "dmm_parser.pyd",
        "parc_parser.dll",
        "CrimsonSaveEditorStandalone.exe",
        "CrimsonGameMods.exe",
    ):
        assert expected in guide
    assert "copied synthetic game directory" in guide
    assert "Do not select the installed game directory" in guide
