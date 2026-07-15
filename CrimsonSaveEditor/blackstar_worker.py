from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, Signal, Slot

from blackstar_unlock import (
    BlackstarCancelledError,
    unlock_blackstar,
)


class BlackstarWorker(QObject):
    progress = Signal(object)
    completed = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal()

    def __init__(
        self,
        *,
        blob,
        profile,
        dry_run: bool,
        operation_id: str,
        generation: int,
        loaded_path: str,
    ) -> None:
        super().__init__()
        self._blob = bytes(blob)
        self._profile = profile
        self._dry_run = dry_run
        self._operation_id = operation_id
        self.generation = generation
        self.loaded_path = loaded_path
        self._cancel_requested = False

    @Slot()
    def request_cancel(self) -> None:
        self._cancel_requested = True

    @Slot()
    def run(self) -> None:
        if self._cancel_requested:
            self.cancelled.emit()
            return
        try:
            result = unlock_blackstar(
                blob=self._blob,
                profile=self._profile,
                dry_run=self._dry_run,
                operation_id=self._operation_id,
                progress=self.progress.emit,
                cancelled=lambda: self._cancel_requested,
            )
        except BlackstarCancelledError:
            self.cancelled.emit()
            return
        except Exception as exc:
            self.failed.emit(str(exc), traceback.format_exc())
            return
        if self._cancel_requested:
            self.cancelled.emit()
        else:
            self.completed.emit(result)
