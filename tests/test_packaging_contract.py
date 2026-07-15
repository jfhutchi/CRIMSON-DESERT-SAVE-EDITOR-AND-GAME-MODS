from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / "CrimsonSaveEditor"


def test_spec_bundles_blackstar_safety_modules_and_schema_manifest() -> None:
    spec = (EDITOR / "CrimsonSaveEditor.spec").read_text(encoding="utf-8")
    assert "('save_schema_profiles.json', '.')" in spec
    for module in ("app_logging", "save_compat", "blackstar_unlock", "blackstar_worker"):
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
    assert "tests\\fixtures\\save.save" in docs
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
