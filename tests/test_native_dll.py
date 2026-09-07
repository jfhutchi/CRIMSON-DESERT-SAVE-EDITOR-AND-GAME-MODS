"""Opt-in tests against a freshly built DLL, using only synthetic PARC data."""
import importlib.util
import ctypes
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

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


@pytest.mark.parametrize("entry", ["parc_parse_file", "parc_parse_raw_file", "parc_parse_blob"])
def test_legacy_exports_reject_null_output_pointers(bridge, tmp_path, entry):
    _, backend = bridge
    # Isolate a native access violation so it cannot take down the test runner.
    script = '''
import ctypes, sys
ctypes.windll.kernel32.SetErrorMode(3)
dll = ctypes.CDLL(sys.argv[1])
name = sys.argv[2]
function = getattr(dll, name)
if name == "parc_parse_file": code = function(b"missing.save", None, None, None)
elif name == "parc_parse_raw_file": code = function(b"missing.bin", None, None)
else: code = function(None, 0, None, None)
assert code == -2, code
'''
    env = dict(os.environ, TEMP=str(tmp_path), TMP=str(tmp_path))
    result = subprocess.run([sys.executable, "-c", script, backend.dll_path, entry],
        env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_legacy_blob_parse_failure_cleans_temporary_file(bridge, tmp_path, monkeypatch):
    _, backend = bridge
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))
    function = backend._dll.parc_parse_blob
    function.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_uint32)]
    buffer = (ctypes.c_uint8 * 3)(1, 2, 3)
    result_json, result_size = ctypes.c_char_p(), ctypes.c_uint32()
    code = function(buffer, 3, ctypes.byref(result_json), ctypes.byref(result_size))
    try:
        assert code != 0
        assert result_json
    finally:
        if result_json:
            backend._dll.parc_free(result_json)
    assert list(tmp_path.iterdir()) == []
