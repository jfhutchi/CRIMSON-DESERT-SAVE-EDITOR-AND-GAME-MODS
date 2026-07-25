from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

import blackstar_worker
from blackstar_unlock import BlackstarProgress
from blackstar_worker import BlackstarWorker


@pytest.fixture(scope="module", autouse=True)
def qt_application():
    return QApplication.instance() or QApplication([])


def _worker(*, dry_run: bool = True) -> BlackstarWorker:
    return BlackstarWorker(
        blob=b"fixture-copy",
        identity=SimpleNamespace(schema_sha256="schema"),
        dry_run=dry_run,
        operation_id="worker-test",
        generation=7,
        loaded_path="copied.save",
        original_header=b"header",
        apply_token=SimpleNamespace() if not dry_run else None,
    )


def test_worker_emits_ordered_progress_and_one_terminal_signal(monkeypatch) -> None:
    expected = SimpleNamespace(output_blob=b"changed-candidate")
    item = SimpleNamespace(item_no=1)

    def fake_unlock(**kwargs):
        kwargs["progress"](BlackstarProgress("parse", 1, 2, "Parsed"))
        kwargs["progress"](BlackstarProgress("complete", 2, 2, "Done"))
        return expected

    monkeypatch.setattr(blackstar_worker, "unlock_blackstar", fake_unlock)
    write_calls = []

    def fake_write(**kwargs):
        write_calls.append(kwargs)
        return "written"

    monkeypatch.setattr(
        blackstar_worker, "transactional_write_blackstar", fake_write, raising=False
    )
    worker = _worker(dry_run=False)
    progress = []
    completed = []
    failed = []
    cancelled = []
    worker.progress.connect(progress.append)
    worker.completed.connect(completed.append)
    worker.failed.connect(lambda *args: failed.append(args))
    worker.cancelled.connect(lambda: cancelled.append(True))

    worker.run()

    assert [event.completed for event in progress] == [1, 2, 6, 7]
    assert completed[0].result is expected
    assert completed[0].write_result == "written"
    assert write_calls[0]["loaded_blob"] == b"fixture-copy"
    assert not failed
    assert not cancelled


def test_dry_run_worker_does_not_write(monkeypatch) -> None:
    expected = SimpleNamespace(output_blob=None)
    monkeypatch.setattr(
        blackstar_worker,
        "unlock_blackstar",
        lambda **_kwargs: expected,
    )
    monkeypatch.setattr(blackstar_worker, "transactional_write_blackstar", lambda **_kwargs: pytest.fail("dry run must not write"), raising=False)
    worker = _worker(dry_run=True)
    completed = []
    worker.completed.connect(completed.append)

    worker.run()

    assert completed[0].result is expected
    assert completed[0].write_result is None


def test_worker_cancelled_before_start_emits_only_cancelled(monkeypatch) -> None:
    monkeypatch.setattr(
        blackstar_worker,
        "unlock_blackstar",
        lambda **_kwargs: pytest.fail("cancelled worker must not start"),
    )
    worker = _worker()
    terminals = []
    worker.completed.connect(lambda _result: terminals.append("completed"))
    worker.failed.connect(lambda *_args: terminals.append("failed"))
    worker.cancelled.connect(lambda: terminals.append("cancelled"))
    worker.request_cancel()
    worker.run()
    assert terminals == ["cancelled"]


def test_worker_cancelled_after_analysis_never_starts_transaction(monkeypatch) -> None:
    worker = _worker(dry_run=False)

    def fake_unlock(**_kwargs):
        worker.request_cancel()
        return SimpleNamespace(output_blob=b"changed-candidate")

    monkeypatch.setattr(blackstar_worker, "unlock_blackstar", fake_unlock)
    monkeypatch.setattr(
        blackstar_worker,
        "transactional_write_blackstar",
        lambda **_kwargs: pytest.fail("cancelled analysis must not write"),
        raising=False,
    )
    terminals = []
    worker.completed.connect(lambda _result: terminals.append("completed"))
    worker.failed.connect(lambda *_args: terminals.append("failed"))
    worker.cancelled.connect(lambda: terminals.append("cancelled"))

    worker.run()

    assert terminals == ["cancelled"]


def test_worker_disables_cancellation_once_transaction_starts(monkeypatch) -> None:
    worker = _worker(dry_run=False)
    monkeypatch.setattr(
        blackstar_worker,
        "unlock_blackstar",
        lambda **_kwargs: SimpleNamespace(output_blob=b"changed-candidate"),
    )

    def fake_write(**_kwargs):
        worker.request_cancel()
        return "written"

    monkeypatch.setattr(
        blackstar_worker, "transactional_write_blackstar", fake_write, raising=False
    )
    cancellation_states = []
    terminals = []
    worker.cancellation_changed.connect(cancellation_states.append)
    worker.completed.connect(lambda _result: terminals.append("completed"))
    worker.failed.connect(lambda *_args: terminals.append("failed"))
    worker.cancelled.connect(lambda: terminals.append("cancelled"))

    worker.run()

    assert cancellation_states == [False]
    assert terminals == ["completed"]


def test_worker_exception_emits_only_failed(monkeypatch) -> None:
    def fail_unlock(**_kwargs):
        raise ValueError("unknown compatibility profile")

    monkeypatch.setattr(blackstar_worker, "unlock_blackstar", fail_unlock)
    worker = _worker()
    terminals = []
    failures = []
    worker.completed.connect(lambda _result: terminals.append("completed"))
    worker.failed.connect(lambda *args: (terminals.append("failed"), failures.append(args)))
    worker.cancelled.connect(lambda: terminals.append("cancelled"))
    worker.run()
    assert terminals == ["failed"]
    assert "unknown compatibility profile" in failures[0][0]
    assert "Traceback" in failures[0][1]
