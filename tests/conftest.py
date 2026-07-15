from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / "CrimsonSaveEditor"
FIXTURES = ROOT / "tests" / "fixtures"
if str(EDITOR) not in sys.path:
    sys.path.insert(0, str(EDITOR))

SAVE_FIXTURE_SHA256 = "91ee9f4e1ed4541a488b79519d95b3136800d336267b5a2fa97a66b5b1268c13"
LOBBY_FIXTURE_SHA256 = "6885369400874a8b729e669bc0c983e11ab12020a716c58652f7d11b4f663a34"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="session")
def fixture_save_path() -> Path:
    path = FIXTURES / "save.save"
    assert sha256_file(path) == SAVE_FIXTURE_SHA256
    return path


@pytest.fixture
def copied_save(tmp_path: Path, fixture_save_path: Path) -> Path:
    destination = tmp_path / "slot-test" / "save.save"
    destination.parent.mkdir(parents=True)
    shutil.copy2(fixture_save_path, destination)
    return destination
