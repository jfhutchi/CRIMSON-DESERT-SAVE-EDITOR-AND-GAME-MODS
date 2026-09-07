"""Opt-in tests against a freshly built DLL, using only synthetic PARC data."""
import importlib.util
import ctypes
import os
import struct
import sys
from pathlib import Path

import pytest

@pytest.fixture
def crypto():
    directory = Path(__file__).resolve().parents[1] / "CrimsonSaveEditor"
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




@pytest.fixture
def bridge(monkeypatch):
    dll_path = os.environ.get("CSE_NATIVE_DLL")
    if not dll_path:
        pytest.skip("Set CSE_NATIVE_DLL to the freshly built parc_parser.dll")
    dll_path = Path(dll_path).resolve()
    assert dll_path.is_file(), f"Native test DLL does not exist: {dll_path}"
    source = Path(__file__).resolve().parents[1] / "CrimsonSaveEditor" / "native_backend.py"
    spec = importlib.util.spec_from_file_location("native_dll_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_application_dirs", lambda: [dll_path.parent])
    backend = module.NativeSaveBackend()
    assert backend.available, backend.load_error
    return module, backend


def raw_blob():
    raw = bytearray(39)
    raw[:4] = b"\xff\xff\x04\x00"
    raw[18] = raw[20] = 1
    raw[24] = ord("T")
    struct.pack_into("<I", raw, 35, len(raw))
    return bytes(raw)


@pytest.mark.parametrize("version", [1, 2])
def test_native_validated_in_place_roundtrip(bridge, crypto, tmp_path, version):
    _, backend = bridge
    destination = tmp_path / "source.save"
    header = bytearray(128)
    struct.pack_into("<H", header, 4, version)
    crypto.write_save_file(str(destination), raw_blob(), header)
    report = backend.write_validated_save(destination, raw_blob(), destination)
    assert report["ok"] is True
    assert report["hmac_ok"] is True
    assert report["roundtrip_stable"] is True
    assert bytes(crypto.load_save_file(str(destination)).decompressed_blob) == raw_blob()
    assert struct.unpack_from("<H", destination.read_bytes(), 4)[0] == version
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize("mutation", ["bad_schema", "invalid_blob"])
def test_native_rejection_preserves_destination(bridge, crypto, tmp_path, mutation):
    module, backend = bridge
    destination = tmp_path / "source.save"
    crypto.write_save_file(str(destination), raw_blob())
    original = destination.read_bytes()
    edited = bytearray(raw_blob())
    if mutation == "bad_schema":
        edited[24] = ord("U")
    else:
        edited = b"invalid"
    with pytest.raises(module.NativeBackendError):
        backend.write_validated_save(destination, edited, destination)
    assert destination.read_bytes() == original
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize("invalid", [False, True])
def test_direct_dll_in_place_write(bridge, crypto, tmp_path, invalid):
    module, backend = bridge
    destination = tmp_path / "direct.save"
    crypto.write_save_file(str(destination), raw_blob())
    original = destination.read_bytes()
    edited = b"invalid" if invalid else raw_blob()
    buffer = (ctypes.c_uint8 * len(edited)).from_buffer_copy(edited)
    result_json, result_size = ctypes.c_char_p(), ctypes.c_uint32()
    code = backend._dll.parc_write_validated_save(
        os.fsencode(destination), buffer, len(edited), os.fsencode(destination),
        ctypes.byref(result_json), ctypes.byref(result_size),
    )
    if invalid:
        with pytest.raises(module.NativeBackendError):
            backend._decode_result(code, result_json, result_size)
        assert destination.read_bytes() == original
    else:
        assert backend._decode_result(code, result_json, result_size)["ok"] is True
        assert bytes(crypto.load_save_file(str(destination)).decompressed_blob) == edited
    assert list(tmp_path.iterdir()) == [destination]
