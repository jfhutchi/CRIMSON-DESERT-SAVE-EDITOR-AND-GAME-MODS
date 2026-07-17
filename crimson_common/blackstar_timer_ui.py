from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
)

from .blackstar_timer import (
    BlackstarTimerService,
    PreviewReport,
    TimerStatus,
    TransactionReport,
)
from .blackstar_timer_worker import BlackstarTimerWorker

log = logging.getLogger(__name__)


class BlackstarTimerPanel(QGroupBox):
    status_message = Signal(str)

    def __init__(
        self,
        *,
        title: str,
        service_factory: Callable[[], BlackstarTimerService] = BlackstarTimerService,
        parent=None,
    ) -> None:
        super().__init__(title, parent)
        self._service_factory = service_factory
        self._game_dir = Path()
        self._preview_token = None
        self._thread: QThread | None = None
        self._worker: BlackstarTimerWorker | None = None
        self._progress: QProgressDialog | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        info = QLabel(
            "Fixed verified preset: mounted time 30 minutes; summon cooldown 1 second. "
            "This modifies installed game archives, affects every save, and does not "
            "change the loaded save or any quest-completion flags."
        )
        info.setObjectName("blackstarTimerWarning")
        info.setWordWrap(True)
        layout.addWidget(info)

        buttons = QHBoxLayout()
        self._preview_button = QPushButton("Preview 30m / 1s")
        self._preview_button.setObjectName("blackstarTimerPreview")
        self._preview_button.clicked.connect(lambda: self._start("preview"))
        buttons.addWidget(self._preview_button)

        self._apply_button = QPushButton("Apply Preset")
        self._apply_button.setObjectName("blackstarTimerApply")
        self._apply_button.setEnabled(False)
        self._apply_button.clicked.connect(lambda: self._start("apply"))
        buttons.addWidget(self._apply_button)

        self._restore_button = QPushButton("Restore Original")
        self._restore_button.setObjectName("blackstarTimerRestore")
        self._restore_button.setEnabled(False)
        self._restore_button.clicked.connect(lambda: self._start("restore"))
        buttons.addWidget(self._restore_button)
        buttons.addStretch()
        layout.addLayout(buttons)

        self._status = QLabel("Select the Crimson Desert install folder, then Preview.")
        self._status.setObjectName("blackstarTimerStatus")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

    def set_game_path(self, game_dir: str | Path) -> None:
        normalized = Path(game_dir).expanduser() if str(game_dir).strip() else Path()
        if normalized != self._game_dir:
            self._preview_token = None
            self._apply_button.setEnabled(False)
        self._game_dir = normalized
        self._restore_button.setEnabled(self._has_owned_backup())

    def _has_owned_backup(self) -> bool:
        if not str(self._game_dir):
            return False
        root = (
            self._game_dir
            / "bin64"
            / "SEModLoad"
            / "Backups"
            / "BlackstarTimer"
        )
        return root.is_dir() and any(
            (child / "manifest.json").is_file()
            for child in root.iterdir()
            if child.is_dir()
        )

    def _start(self, action: str) -> None:
        if self._thread is not None:
            QMessageBox.information(
                self, "Blackstar Timer", "A Blackstar timer operation is already running."
            )
            return
        game = self._game_dir.expanduser().resolve()
        required = (
            game / "0008" / "0.pamt",
            game / "0008" / "0.paz",
            game / "meta" / "0.papgt",
        )
        if not all(path.is_file() for path in required):
            QMessageBox.warning(
                self,
                "Blackstar Timer",
                "Select a valid Crimson Desert install folder first.\n\n"
                "Expected 0008/0.paz, 0008/0.pamt, and meta/0.papgt.",
            )
            return
        if action == "apply" and self._preview_token is None:
            QMessageBox.warning(
                self,
                "Preview Required",
                "Run Preview first. Apply is enabled only for that exact unchanged source.",
            )
            return

        service = self._service_factory()
        thread = QThread(self)
        worker = BlackstarTimerWorker(
            action=action,
            service=service,
            game_dir=game,
            token=self._preview_token if action == "apply" else None,
        )
        worker.moveToThread(thread)
        progress = QProgressDialog(
            "Checking Crimson Desert game archives...", "Cancel", 0, 100, self
        )
        progress.setWindowTitle("Blackstar Timer")
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setValue(0)

        self._thread = thread
        self._worker = worker
        self._progress = progress
        self._set_busy(True)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.completed.connect(self._on_completed)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        worker.cancellation_changed.connect(self._on_cancellation_changed)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._cleanup)
        progress.canceled.connect(worker.request_cancel)
        progress.show()
        thread.start()

    def _set_busy(self, busy: bool) -> None:
        self._preview_button.setEnabled(not busy)
        self._apply_button.setEnabled(not busy and self._preview_token is not None)
        self._restore_button.setEnabled(not busy and self._has_owned_backup())

    def _on_progress(self, phase: str, value: int) -> None:
        label = phase.replace("_", " ").title()
        if self._progress is not None:
            self._progress.setValue(value)
            self._progress.setLabelText(f"{label}...")
        self._status.setText(label)
        self.status_message.emit(f"Blackstar Timer: {label}")

    def _on_cancellation_changed(self, enabled: bool) -> None:
        if self._progress is not None and not enabled:
            self._progress.setCancelButton(None)
            self._progress.setLabelText(
                "Writing and verifying game archives; cancellation is disabled..."
            )

    def _on_completed(self, result: object) -> None:
        if isinstance(result, PreviewReport):
            self._preview_token = result.token
            self._apply_button.setEnabled(result.token is not None)
            self._status.setText(result.reason)
        elif isinstance(result, TransactionReport):
            self._preview_token = None
            self._apply_button.setEnabled(False)
            self._status.setText(result.reason)
        self._restore_button.setEnabled(self._has_owned_backup())
        self.status_message.emit(self._status.text())
        if self._progress is not None:
            self._progress.close()
        QMessageBox.information(
            self, "Blackstar Timer Report", self._format_report(result)
        )

    def _format_report(self, result: object) -> str:
        if isinstance(result, PreviewReport):
            return (
                "Mode: Preview (nothing written)\n"
                f"Status: {result.status.value}\n"
                f"Profile: {result.profile_id}\n"
                f"Cooldown: {result.cooldown_before} -> {result.cooldown_after} seconds\n"
                f"Mounted time: {result.duration_before} -> {result.duration_after} seconds\n"
                f"Candidate SHA-256: {result.candidate_body_sha256}\n"
                f"Compressed bytes: {result.candidate_compressed_size} / {result.slot_capacity}\n\n"
                "Save-file changes: none\nQuest-flag changes: none"
            )
        if isinstance(result, TransactionReport):
            backup = str(result.backup_dir) if result.backup_dir else "none"
            return (
                f"Mode: {result.action.title()}\n"
                f"Status: {result.status.value}\n"
                f"Profile: {result.profile_id}\n"
                f"Changed: {'yes' if result.changed else 'no'}\n"
                f"Cooldown: {result.cooldown_seconds} seconds\n"
                f"Mounted time: {result.duration_seconds} seconds\n"
                f"Backup: {backup}\n\n"
                "Save-file changes: none\nQuest-flag changes: none"
            )
        return str(result)

    def _on_failed(self, message: str, details: str) -> None:
        log.error("Blackstar timer worker failed: %s\n%s", message, details)
        self._preview_token = None
        self._apply_button.setEnabled(False)
        self._status.setText(message)
        if self._progress is not None:
            self._progress.close()
        QMessageBox.critical(
            self,
            "Blackstar Timer Failed",
            f"{message}\n\nNo save file was changed. See the application log for details.",
        )

    def _on_cancelled(self) -> None:
        self._status.setText("Cancelled before any game archive write.")
        if self._progress is not None:
            self._progress.close()
        self.status_message.emit(self._status.text())

    def _cleanup(self) -> None:
        thread = self._thread
        self._thread = None
        self._worker = None
        self._progress = None
        self._set_busy(False)
        if thread is not None:
            thread.deleteLater()
