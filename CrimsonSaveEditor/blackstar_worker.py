from __future__ import annotations

import traceback
from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, Signal, Slot

from blackstar_unlock import BlackstarCancelledError, BlackstarProgress, unlock_blackstar
from save_crypto import transactional_write_blackstar


@dataclass(frozen=True)
class BlackstarWorkerResult:
    result: object
    write_result: object | None


class BlackstarWorker(QObject):
    progress = Signal(object)
    completed = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal()

    def __init__(self, *, blob, identity, dry_run: bool, operation_id: str,
                 generation: int, loaded_path: str, original_header: bytes,
                 apply_token=None) -> None:
        super().__init__()
        self._blob = bytes(blob)
        self._identity = identity
        self._dry_run = dry_run
        self._operation_id = operation_id
        self.generation = generation
        self.loaded_path = loaded_path
        self._original_header = bytes(original_header)
        self._apply_token = apply_token
        self._cancel_requested = False

    @Slot()
    def request_cancel(self) -> None:
        self._cancel_requested = True

    def _forward_progress(self, event: BlackstarProgress) -> None:
        self.progress.emit(replace(event, total=7))

    @Slot()
    def run(self) -> None:
        if self._cancel_requested:
            self.cancelled.emit()
            return
        try:
            result = unlock_blackstar(
                blob=self._blob, identity=self._identity, dry_run=self._dry_run,
                operation_id=self._operation_id, progress=self._forward_progress,
                cancelled=lambda: self._cancel_requested,
            )
            write_result = None
            if not self._dry_run and result.output_blob != self._blob:
                if self._apply_token is None:
                    raise ValueError("A matching Blackstar preview is required before apply")
                self.progress.emit(BlackstarProgress("write", 6, 7, "Backing up and writing Blackstar"))
                write_result = transactional_write_blackstar(
                    destination=self.loaded_path, edited_blob=result.output_blob,
                    original_header=self._original_header,
                    expected_identity=self._identity, token=self._apply_token,
                    generation=self.generation, operation_id=self._operation_id,
                )
        except BlackstarCancelledError:
            self.cancelled.emit()
            return
        except Exception as exc:
            self.failed.emit(str(exc), traceback.format_exc())
            return
        if self._cancel_requested:
            self.cancelled.emit()
            return
        self.progress.emit(BlackstarProgress("complete", 7, 7, "Blackstar operation complete"))
        self.completed.emit(BlackstarWorkerResult(result, write_result))
