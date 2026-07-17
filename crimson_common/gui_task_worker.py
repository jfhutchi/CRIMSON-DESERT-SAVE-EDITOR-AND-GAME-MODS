from __future__ import annotations

import threading
import traceback
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal, Slot


class _TaskCancelled(RuntimeError):
    pass


class GuiTaskWorker(QObject):
    """Run one long task on a QThread with progress and cooperative cancellation."""

    progress = Signal(str, int)
    completed = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal()
    finished = Signal()

    def __init__(self, *, task: Callable[[Callable[[str, int], None]], object]) -> None:
        super().__init__()
        self._task = task
        self._cancel_requested = threading.Event()
        self._terminal_emitted = False

    @Slot()
    def request_cancel(self) -> None:
        self._cancel_requested.set()

    def _check_cancelled(self) -> None:
        if self._cancel_requested.is_set():
            raise _TaskCancelled()

    def _report(self, phase: str, value: int) -> None:
        self._check_cancelled()
        self.progress.emit(str(phase), max(0, min(99, int(value))))

    def _terminal(self, signal, *args) -> None:
        if self._terminal_emitted:
            return
        self._terminal_emitted = True
        signal.emit(*args)

    @Slot()
    def run(self) -> None:
        try:
            self._check_cancelled()
            result = self._task(self._report)
            self._check_cancelled()
            self._terminal(self.completed, result)
        except _TaskCancelled:
            self._terminal(self.cancelled)
        except Exception as exc:
            self._terminal(self.failed, str(exc), traceback.format_exc())
        finally:
            self.finished.emit()
