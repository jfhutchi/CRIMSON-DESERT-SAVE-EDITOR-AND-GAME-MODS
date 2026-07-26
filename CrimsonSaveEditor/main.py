import socket
import sys
import os
import logging
from pathlib import Path

# urlretrieve takes no timeout argument, so a stalled server would hang the
# window forever. One default covers every download path in the app.
socket.setdefaulttimeout(30)

if not getattr(sys, "frozen", False):
    REPO_ROOT = Path(__file__).resolve().parents[1]
    for shared_path in (REPO_ROOT, REPO_ROOT / "CrimsonGameMods"):
        value = str(shared_path)
        if value not in sys.path:
            sys.path.insert(0, value)

from app_logging import configure_logging


def _splash(text: str) -> None:
    try:
        import pyi_splash
        pyi_splash.update_text(text)
    except Exception:
        pass


def _splash_close() -> None:
    try:
        import pyi_splash
        pyi_splash.close()
    except Exception:
        pass


_splash("Starting up...")

LOG_PATH = configure_logging()
logging.getLogger(__name__).info("Application logging initialized: %s", LOG_PATH)

_splash("Loading Qt framework...")
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt

_splash("Loading editor modules...")
from gui import MainWindow


def main() -> None:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    from updater import APP_VERSION
    app.setApplicationName("Crimson Desert Save Editor")
    app.setApplicationVersion(APP_VERSION)

    font = QFont("Bahnschrift", 10)
    font.setStyleName("SemiCondensed")
    font.setStyleHint(QFont.SansSerif)
    app.setFont(font)

    _splash("Building main window...")
    window = MainWindow()
    _splash_close()
    window.show()

    if len(sys.argv) > 1:
        path = sys.argv[1]
        if os.path.isfile(path):
            if path.lower().endswith(".save"):
                window._load_save(path)
            elif path.lower().endswith(".bin"):
                from save_crypto import load_raw_stream
                try:
                    window._save_data = load_raw_stream(path)
                    window._loaded_path = path
                    window._scan_and_populate()
                    window._update_status(f"Loaded: {os.path.basename(path)}")
                except Exception as e:
                    print(f"Error loading {path}: {e}")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
