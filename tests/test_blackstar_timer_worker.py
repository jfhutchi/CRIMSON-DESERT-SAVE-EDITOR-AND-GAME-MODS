from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication

from crimson_common.blackstar_timer_worker import BlackstarTimerWorker


@pytest.fixture(scope="module", autouse=True)
def qt_application():
    return QCoreApplication.instance() or QCoreApplication([])


class FakeTimerService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.on_apply = None

    def preview(self, game_dir: Path, progress=None):
        self.calls.append(f"preview:{game_dir.name}")
        progress("pamt_lookup", 30)
        progress("candidate_verification", 80)
        return SimpleNamespace(action="preview")

    def apply(self, token, progress=None):
        self.calls.append("apply")
        progress("backup", 35)
        if self.on_apply:
            self.on_apply()
        progress("post_write_verification", 95)
        return SimpleNamespace(action="apply", token=token)

    def restore(self, game_dir: Path, progress=None):
        self.calls.append(f"restore:{game_dir.name}")
        progress("backup_verification", 30)
        progress("restore_verification", 95)
        return SimpleNamespace(action="restore")


def _capture(worker: BlackstarTimerWorker) -> dict[str, list]:
    events = {
        "progress": [],
        "completed": [],
        "failed": [],
        "cancelled": [],
        "finished": [],
        "cancellation": [],
    }
    worker.progress.connect(lambda phase, value: events["progress"].append((phase, value)))
    worker.completed.connect(events["completed"].append)
    worker.failed.connect(lambda *args: events["failed"].append(args))
    worker.cancelled.connect(lambda: events["cancelled"].append(True))
    worker.finished.connect(lambda: events["finished"].append(True))
    worker.cancellation_changed.connect(events["cancellation"].append)
    return events


@pytest.mark.parametrize("action", ["preview", "apply", "restore"])
def test_worker_emits_ordered_progress_and_one_terminal_signal(action: str) -> None:
    service = FakeTimerService()
    worker = BlackstarTimerWorker(
        action=action,
        service=service,
        game_dir=Path("synthetic-game"),
        token=SimpleNamespace() if action == "apply" else None,
    )
    events = _capture(worker)

    worker.run()

    values = [value for _phase, value in events["progress"]]
    assert values == sorted(values)
    assert values[-1] == 100
    assert len(events["completed"]) == 1
    assert not events["failed"]
    assert not events["cancelled"]
    assert events["finished"] == [True]


def test_worker_cancels_during_read_only_preflight() -> None:
    service = FakeTimerService()
    worker = BlackstarTimerWorker(
        action="apply",
        service=service,
        game_dir=Path("synthetic-game"),
        token=SimpleNamespace(),
    )
    events = _capture(worker)
    worker.progress.connect(
        lambda phase, _value: worker.request_cancel() if phase == "preflight" else None
    )

    worker.run()

    assert service.calls == []
    assert events["cancelled"] == [True]
    assert not events["completed"]
    assert not events["failed"]
    assert events["finished"] == [True]


def test_worker_disables_cancellation_after_transaction_starts() -> None:
    service = FakeTimerService()
    worker = BlackstarTimerWorker(
        action="apply",
        service=service,
        game_dir=Path("synthetic-game"),
        token=SimpleNamespace(),
    )
    service.on_apply = worker.request_cancel
    events = _capture(worker)

    worker.run()

    assert events["cancellation"][-1] is False
    assert len(events["completed"]) == 1
    assert not events["cancelled"]
    assert events["finished"] == [True]


def test_worker_exception_emits_only_failed_and_finished() -> None:
    service = FakeTimerService()

    def fail(_game_dir: Path, progress=None):
        raise ValueError("unknown timer schema")

    service.preview = fail
    worker = BlackstarTimerWorker(
        action="preview", service=service, game_dir=Path("synthetic-game")
    )
    events = _capture(worker)

    worker.run()

    assert len(events["failed"]) == 1
    assert "unknown timer schema" in events["failed"][0][0]
    assert "Traceback" in events["failed"][0][1]
    assert not events["completed"]
    assert not events["cancelled"]
    assert events["finished"] == [True]
