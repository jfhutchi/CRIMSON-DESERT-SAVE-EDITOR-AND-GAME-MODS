"""Synthetic container roundtrips; no game installation or save fixtures needed."""
import importlib.util
import struct
import sys
from pathlib import Path

import pytest


@pytest.fixture(params=["CrimsonSaveEditor", "CrimsonGameMods"])
def crypto(request):
    directory = Path(__file__).resolve().parents[1] / request.param
    previous_models = sys.modules.pop("models", None)
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location("version_crypto", directory / "save_crypto.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path.pop(0)
        sys.modules.pop("models", None)
        if previous_models is not None:
            sys.modules["models"] = previous_models


@pytest.mark.parametrize("version", [1, 2])
def test_writer_preserves_container_version_and_payload(crypto, version, tmp_path):
    header = bytearray(crypto.HEADER_SIZE)
    header[:4] = b"SAVE"
    struct.pack_into("<H", header, crypto.VERSION_OFFSET, version)
    payload = bytes(range(256)) * 4
    output = tmp_path / "roundtrip.save"
    crypto.write_save_file(str(output), payload, header)
    assert struct.unpack_from("<H", output.read_bytes(), crypto.VERSION_OFFSET)[0] == version
    assert bytes(crypto.load_save_file(str(output)).decompressed_blob) == payload


def test_unsupported_version_preserves_destination(crypto, tmp_path):
    header = bytearray(crypto.HEADER_SIZE)
    struct.pack_into("<H", header, crypto.VERSION_OFFSET, 99)
    output = tmp_path / "existing.save"
    output.write_bytes(b"original")
    with pytest.raises(ValueError, match="Unsupported save version"):
        crypto.write_save_file(str(output), b"candidate", header)
    assert output.read_bytes() == b"original"
