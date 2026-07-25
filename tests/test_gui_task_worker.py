from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from crimson_common.gui_task_worker import GuiTaskWorker


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_worker_forwards_progress_and_emits_one_success_terminal() -> None:
    _app()
    events: list[tuple[str, object]] = []

    def task(report):
        report("decrypt", 20)
        report("scan", 70)
        return {"loaded": True}

    worker = GuiTaskWorker(task=task)
    worker.progress.connect(lambda phase, value: events.append((phase, value)))
    worker.completed.connect(lambda result: events.append(("completed", result)))
    worker.failed.connect(lambda *_: events.append(("failed", None)))
    worker.cancelled.connect(lambda: events.append(("cancelled", None)))
    worker.finished.connect(lambda: events.append(("finished", None)))

    worker.run()

    assert events == [
        ("decrypt", 20),
        ("scan", 70),
        ("completed", {"loaded": True}),
        ("finished", None),
    ]


def test_worker_surfaces_exception_details_and_always_finishes() -> None:
    _app()
    events: list[tuple[str, str]] = []

    def task(_report):
        raise ValueError("bad copied fixture")

    worker = GuiTaskWorker(task=task)
    worker.failed.connect(lambda message, details: events.append((message, details)))
    finished: list[bool] = []
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    assert events and events[0][0] == "bad copied fixture"
    assert "ValueError" in events[0][1]
    assert finished == [True]


def test_worker_can_cancel_between_read_only_phases() -> None:
    _app()
    terminal: list[str] = []

    def task(report):
        report("decrypt", 20)
        report("scan", 70)
        return "unreachable"

    worker = GuiTaskWorker(task=task)
    worker.progress.connect(lambda *_: worker.request_cancel())
    worker.completed.connect(lambda _: terminal.append("completed"))
    worker.cancelled.connect(lambda: terminal.append("cancelled"))
    worker.failed.connect(lambda *_: terminal.append("failed"))
    worker.finished.connect(lambda: terminal.append("finished"))

    worker.run()

    assert terminal == ["cancelled", "finished"]
