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
EARLY_114_SHA256 = "57060a7707340f20410e04fad3127f2d6a1fdbd515cd163a196d841c6892ef78"
LEGIT_IDLE_114_SHA256 = "3b9d2bdc63a892b1e513344c9121d0606b1c474db3823cfd7ada0ae7e234f724"
LEGIT_ACTIVE_114_SHA256 = "6315b31b9847b585552788e9feeb11966ebf8b09b65f6518002f9624d51623c7"
LEGACY_FAILED_SHA256 = "e8e1f084c392f35da4f30658c9d829890e3fe29f230ef07a8afd6fcf534b362c"


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


def _reference_save(folder: str, expected_hash: str) -> Path:
    path = FIXTURES / folder / "save.save"
    assert sha256_file(path) == expected_hash
    return path


@pytest.fixture(scope="session")
def early_114_save_path() -> Path:
    return _reference_save("slot102", EARLY_114_SHA256)


@pytest.fixture(scope="session")
def legit_idle_114_save_path() -> Path:
    return _reference_save("slot107", LEGIT_IDLE_114_SHA256)


@pytest.fixture(scope="session")
def legit_active_114_save_path() -> Path:
    return _reference_save("slot108", LEGIT_ACTIVE_114_SHA256)


@pytest.fixture(scope="session")
def legacy_failed_save_path() -> Path:
    return _reference_save("slot102_legacy", LEGACY_FAILED_SHA256)
