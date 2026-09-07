"""Exercise ctypes response ownership and destination preservation without a DLL."""
import ctypes
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture
def native():
    path = Path(__file__).resolve().parents[1] / "CrimsonSaveEditor" / "native_backend.py"
    spec = importlib.util.spec_from_file_location("bridge_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bridge_with_result(native, result, code=0):
    bridge = native.NativeSaveBackend.__new__(native.NativeSaveBackend)
    dll = Mock()
    bridge._dll = dll
    payload = json.dumps(result).encode()
    buffer = ctypes.create_string_buffer(payload)

    def write(source, blob, size, output, out_json, out_size):
        Path(output.decode()).write_bytes(b"candidate")
        ctypes.cast(out_json, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.addressof(buffer)
        ctypes.cast(out_size, ctypes.POINTER(ctypes.c_uint32))[0] = len(payload)
        return code

    dll.parc_write_validated_save.side_effect = write
    dll._result_buffer = buffer
    return bridge, dll


@pytest.mark.parametrize("result", [[], None, {"ok": "false"}, {"ok": 1}, {"ok": False}])
def test_invalid_success_response_preserves_destination(native, result, tmp_path):
    bridge, dll = bridge_with_result(native, result)
    destination = tmp_path / "save.save"
    destination.write_bytes(b"original")
    with pytest.raises(native.NativeBackendError):
        bridge.write_validated_save(destination, b"blob", destination)
    assert destination.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [destination]
    dll.parc_free.assert_called_once()


def test_flush_failure_preserves_destination(native, tmp_path, monkeypatch):
    bridge, dll = bridge_with_result(native, {"ok": True})
    destination = tmp_path / "save.save"
    destination.write_bytes(b"original")
    monkeypatch.setattr(native.os, "fsync", Mock(side_effect=OSError("disk flush failed")))
    with pytest.raises(OSError, match="disk flush failed"):
        bridge.write_validated_save(destination, b"blob", destination)
    assert destination.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [destination]
    dll.parc_free.assert_called_once()


def test_native_failure_diagnostic_preserves_destination(native, tmp_path):
    bridge, dll = bridge_with_result(native, {"ok": False, "error": "schema mismatch"}, 1)
    destination = tmp_path / "save.save"
    destination.write_bytes(b"original")
    with pytest.raises(native.NativeBackendError, match="schema mismatch"):
        bridge.write_validated_save(destination, b"blob", destination)
    assert destination.read_bytes() == b"original"
    dll.parc_free.assert_called_once()


def test_success_installs_candidate_and_frees_response(native, tmp_path):
    bridge, dll = bridge_with_result(native, {"ok": True})
    destination = tmp_path / "save.save"
    destination.write_bytes(b"original")
    result = bridge.write_validated_save(destination, b"blob", destination)
    assert destination.read_bytes() == b"candidate"
    assert result["output_path"] == str(destination)
    assert list(tmp_path.iterdir()) == [destination]
    dll.parc_free.assert_called_once()
