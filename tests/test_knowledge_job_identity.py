import json
import os
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QTimer

from gui_method_loader import load_method


@pytest.fixture
def job(tmp_path, monkeypatch):
    pack = tmp_path / "pack.json"
    pack.write_text(json.dumps({"entries": [{"key": 1}]}))
    workers, timers, inputs = [], [], []
    monkeypatch.setattr(threading, "Thread", lambda *, target, **kwargs:
        SimpleNamespace(start=lambda: workers.append(target)))
    monkeypatch.setattr(QTimer, "singleShot", lambda delay, callback: timers.append(callback))

    def inject(blob, keys_filter):
        inputs.append((bytes(blob), tuple(keys_filter)))
        return True, bytes(blob) + b"knowledge", "Injected"

    monkeypatch.setitem(sys.modules, "parc_inserter3", SimpleNamespace(inject_knowledge_fast=inject))
    dialogs = Mock(Yes=1, No=2)
    dialogs.question.return_value = 1
    method = load_method("CrimsonSaveEditor/gui.py", "MainWindow", "_know_inject_pack_fast", {
        "os": os, "QApplication": Mock(), "QMessageBox": dialogs,
        "QFileDialog": SimpleNamespace(getOpenFileName=lambda *args: (str(pack), "")),
    })
    owner = SimpleNamespace(
        _save_data=SimpleNamespace(decompressed_blob=bytearray(b"source")),
        _loaded_path="save-a.save", _app_dir=lambda: str(tmp_path),
        _know_learned_keys=set(), _know_all_entries=[(1, "entry", "category", False, "description")],
        _know_status=Mock(), _dirty=False, _undo_stack=["old offset patch"],
        _scan_and_populate=Mock(),
    )
    return SimpleNamespace(start=lambda: method(owner), owner=owner, workers=workers,
        timers=timers, inputs=inputs, dialogs=dialogs)


@pytest.mark.parametrize("change_before_worker", [False, True])
def test_reloaded_save_never_receives_previous_job(job, change_before_worker):
    job.start()
    old_save = job.owner._save_data
    replacement = SimpleNamespace(decompressed_blob=bytearray(b"source"))
    if change_before_worker:
        job.owner._save_data = replacement
    job.workers.pop()()
    job.owner._save_data = replacement
    job.timers.pop()()
    assert replacement.decompressed_blob == b"source"
    assert old_save.decompressed_blob == b"source"
    assert not job.owner._dirty
    assert not job.owner._know_learned_keys
    assert "discard" in job.owner._know_status.setText.call_args.args[0].lower()


def test_worker_uses_captured_input_even_if_save_switches(job):
    job.start()
    job.owner._save_data = SimpleNamespace(decompressed_blob=bytearray(b"other"))
    job.workers.pop()()
    assert job.inputs == [(b"source", (1,))]


def test_intervening_edit_is_not_overwritten(job):
    job.start()
    job.workers.pop()()
    job.owner._save_data.decompressed_blob[:] = b"edited"
    job.timers.pop()()
    assert job.owner._save_data.decompressed_blob == b"edited"
    assert not job.owner._dirty


def test_second_job_cannot_overwrite_first_job_state(job):
    job.start()
    job.start()
    assert len(job.workers) == 1


def test_success_refreshes_offsets_and_invalidates_old_undo(job):
    job.start()
    job.workers.pop()()
    job.timers.pop()()
    assert job.owner._save_data.decompressed_blob == b"sourceknowledge"
    assert job.owner._dirty
    assert job.owner._know_learned_keys == {1}
    job.owner._scan_and_populate.assert_called_once()
    assert job.owner._undo_stack == []
