from __future__ import annotations

import traceback
from dataclasses import dataclass, replace

from PySide6.QtCore import QObject, Signal, Slot

from blackstar_unlock import (
    BlackstarCancelledError,
    BlackstarProgress,
    unlock_blackstar,
)
from item_scanner import enrich_items_with_parc, scan_items


@dataclass(frozen=True)
class BlackstarWorkerResult:
    result: object
    refreshed_items: tuple[object, ...] | None
    parc_status: str


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

    def _forward_progress(self, event: BlackstarProgress) -> None:
        self.progress.emit(replace(event, total=7))

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
                progress=self._forward_progress,
                cancelled=lambda: self._cancel_requested,
            )
            refreshed_items = None
            parc_status = ""
            if result.output_blob is not None and result.output_blob != self._blob:
                self.progress.emit(
                    BlackstarProgress(
                        "refresh", 6, 7, "Refreshing item offsets in background"
                    )
                )
                if self._cancel_requested:
                    raise BlackstarCancelledError("Blackstar operation cancelled")
                items = scan_items(result.output_blob)
                _enriched, parc_status = enrich_items_with_parc(
                    result.output_blob, items
                )
                refreshed_items = tuple(items)
                if self._cancel_requested:
                    raise BlackstarCancelledError("Blackstar operation cancelled")
        except BlackstarCancelledError:
            self.cancelled.emit()
            return
        except Exception as exc:
            self.failed.emit(str(exc), traceback.format_exc())
            return
        if self._cancel_requested:
            self.cancelled.emit()
        else:
            self.progress.emit(
                BlackstarProgress("complete", 7, 7, "Blackstar operation complete")
            )
            self.completed.emit(
                BlackstarWorkerResult(result, refreshed_items, parc_status)
            )
