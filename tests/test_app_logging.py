import logging
import inspect
from pathlib import Path

import blackstar_unlock
from app_logging import configure_logging, new_operation_id, phase


def test_configure_logging_writes_rotating_utf8_file(tmp_path: Path) -> None:
    log_path = configure_logging(tmp_path)
    logging.getLogger("test").info("fixture-safe log message")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert log_path == tmp_path / "logs" / "crimson-save-editor.log"
    assert "fixture-safe log message" in log_path.read_text(encoding="utf-8")


def test_phase_logs_start_success_and_elapsed_time(tmp_path: Path, caplog) -> None:
    configure_logging(tmp_path)
    operation_id = new_operation_id("blackstar")
    with caplog.at_level(logging.INFO):
        with phase(logging.getLogger("test"), operation_id, "detection", count=1):
            pass
    text = caplog.text
    assert "phase_start" in text
    assert "phase_success" in text
    assert "elapsed_ms=" in text


def test_blackstar_mount_and_knowledge_have_distinct_log_phases() -> None:
    source = inspect.getsource(blackstar_unlock.unlock_blackstar)
    assert '"blackstar_mount_insertion"' in source
    assert '"blackstar_knowledge_insertion"' in source
