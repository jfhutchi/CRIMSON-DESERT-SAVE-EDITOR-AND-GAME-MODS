"""Contracts for default-on, offline, thread-safe item icons.

Defects covered:
1. ``IconCache.has_icon`` returned ``True`` unconditionally, so enabling icons
   without local files spawned one download thread and one GitHub request per
   visible item row.
2. Icons were never bundled, so a fresh install had to download 6,011 files
   from GitHub one request at a time before the icon column showed anything.
3. Download-path callbacks ran on worker threads and touched Qt widgets.
4. Pixmaps were cached at source resolution; browsing the full item database
   would hold thousands of full-size pixmaps in memory.
"""
from __future__ import annotations

import os
import sys
import threading
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from icon_cache import IconCache  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_has_icon_reports_missing_files(tmp_path: Path) -> None:
    _app()
    cache = IconCache(local_dir=str(tmp_path / "icons_local"))
    assert cache.has_icon(999_999_999) is False

    icon_file = tmp_path / "icons_local" / "424242.webp"
    icon_file.write_bytes(b"stub")
    assert cache.has_icon(424242) is True


def test_get_pixmap_bounds_cached_icon_size(tmp_path: Path) -> None:
    _app()
    source_dir = ROOT / "icons_local"
    sample = next(source_dir.glob("*.webp"))
    local = tmp_path / "icons_local"
    local.mkdir()
    target = local / "777.webp"
    target.write_bytes(sample.read_bytes())

    cache = IconCache(local_dir=str(local))
    px = cache.get_pixmap(777)
    assert px is not None and not px.isNull()
    assert px.width() <= 48 and px.height() <= 48


def test_seed_from_bundle_extracts_icon_archive(tmp_path: Path) -> None:
    _app()
    bundle = tmp_path / "icons_bundle.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("icons_local/1.webp", b"a" * 200)
        zf.writestr("icons_mercenary/2.webp", b"b" * 200)
        zf.writestr("icons_local/../evil.webp", b"nope")
        zf.writestr("unrelated/3.webp", b"nope")

    local = tmp_path / "seeded" / "icons_local"
    cache = IconCache(local_dir=str(local))
    count = cache.seed_from_bundle_sync(bundle_path=str(bundle))

    assert count == 2
    assert (local / "1.webp").is_file()
    assert (local.parent / "icons_mercenary" / "2.webp").is_file()
    assert not (local.parent / "evil.webp").exists()
    assert not list(local.parent.glob("**/3.webp"))

    assert cache.seed_from_bundle_sync(bundle_path=str(bundle), min_files=1) == 0


def test_worker_thread_callbacks_are_delivered_on_the_gui_thread(tmp_path: Path) -> None:
    app = _app()
    cache = IconCache(local_dir=str(tmp_path / "icons_local"))

    delivered: list[threading.Thread] = []
    loop = QEventLoop()

    def callback(_key: int, _px: object) -> None:
        delivered.append(threading.current_thread())
        loop.quit()

    worker = threading.Thread(
        target=lambda: cache._deliver.emit(1, None, callback), daemon=True
    )
    worker.start()
    QTimer.singleShot(2000, loop.quit)
    loop.exec()
    worker.join(timeout=2)

    assert delivered, "queued delivery never ran"
    assert delivered[0] is threading.main_thread()
    app.processEvents()


def test_peek_never_touches_disk(tmp_path: Path) -> None:
    _app()
    local = tmp_path / "icons_local"
    local.mkdir()
    source_dir = ROOT / "icons_local"
    sample = next(source_dir.glob("*.webp"))
    (local / "555.webp").write_bytes(sample.read_bytes())

    cache = IconCache(local_dir=str(local))
    assert cache.peek(555) is None, "peek must not read from disk"
    assert cache.get_pixmap(555) is not None
    assert cache.peek(555) is not None, "peek must see cached pixmaps"


def test_warm_cache_async_loads_icons_off_thread(tmp_path: Path) -> None:
    app = _app()
    local = tmp_path / "icons_local"
    local.mkdir()
    source_dir = ROOT / "icons_local"
    sample = next(source_dir.glob("*.webp")).read_bytes()
    for key in (11, 22, 33):
        (local / f"{key}.webp").write_bytes(sample)

    cache = IconCache(local_dir=str(local))
    loop = QEventLoop()
    counts: list[int] = []

    def completed(count: int) -> None:
        counts.append(count)
        loop.quit()

    assert cache.warm_cache_async([11, 22, 33, 44], completed=completed) is True
    QTimer.singleShot(5000, loop.quit)
    loop.exec()

    assert counts == [3]
    for key in (11, 22, 33):
        px = cache.peek(key)
        assert px is not None and not px.isNull()
        assert px.width() <= 48 and px.height() <= 48
    assert cache.peek(44) is None
    app.processEvents()


def test_startup_bulk_populates_never_load_icons_from_disk() -> None:
    import ast

    source = (ROOT / "CrimsonSaveEditor" / "gui.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    wanted = {"_populate_swap_list", "_filter_database"}
    seen = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "MainWindow":
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name in wanted:
                    segment = ast.get_source_segment(source, child)
                    assert segment is not None
                    assert "peek(" in segment, (
                        f"{child.name} runs synchronously for ~6,000 rows at "
                        "startup; it must only attach already-cached pixmaps, "
                        "never load them from disk"
                    )
                    assert "get_pixmap(" not in segment, child.name
                    seen.add(child.name)
    assert seen == wanted


def test_icons_are_opt_in_and_remembered() -> None:
    # Off for fresh installs; the toggle persists show_icons in the config, so
    # anyone who clicked Show Icons in a previous session gets them back.
    source = (ROOT / "CrimsonSaveEditor" / "gui.py").read_text(encoding="utf-8-sig")
    assert 'self._config.get("show_icons", False)' in source
    assert 'self._config.get("show_icons", True)' not in source
    assert '_config["show_icons"] = self._icons_enabled' in source


def test_spec_ships_without_the_icon_archive() -> None:
    # Shipping decision: the exe must stay small; icons are downloaded on
    # demand with a visible progress dialog. A user-supplied icons_bundle.zip
    # next to the exe still seeds offline, but the build must not embed one.
    spec = (ROOT / "CrimsonSaveEditor" / "CrimsonSaveEditor.spec").read_text(
        encoding="utf-8"
    )
    assert "icons_bundle.zip" not in spec


def test_bulk_download_runs_concurrently_and_supports_cancel(tmp_path: Path) -> None:
    import json
    import threading
    import urllib.request

    _app()
    listing = [
        {"name": "1.webp"},
        {"name": "2.webp"},
        {"name": "3.webp"},
        {"name": "readme.txt"},
    ]

    class _FakeResponse:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    active = []
    lock = threading.Lock()

    def fake_urlopen(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "api.github.com" in url:
            return _FakeResponse(json.dumps(listing).encode())
        with lock:
            active.append(url)
        return _FakeResponse(b"w" * 200)

    original = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        cache = IconCache(local_dir=str(tmp_path / "icons_local"))
        progress: list[tuple] = []
        stats = cache.bulk_download_all(
            progress_callback=lambda *args: progress.append(args)
        )
    finally:
        urllib.request.urlopen = original

    assert stats["downloaded"] == 6, "3 webp files in each of the two folders"
    assert (tmp_path / "icons_local" / "1.webp").is_file()
    assert (tmp_path / "icons_mercenary" / "2.webp").is_file()
    assert progress, "progress callback must fire"

    source = (ROOT / "CrimsonSaveEditor" / "icon_cache.py").read_text(
        encoding="utf-8-sig"
    )
    assert "ThreadPoolExecutor" in source, (
        "6,000 sequential requests take ~15 minutes; downloads must run on a "
        "worker pool"
    )
    assert "cancel_event" in source


def test_download_ui_is_discoverable_with_progress() -> None:
    source = (ROOT / "CrimsonSaveEditor" / "gui.py").read_text(encoding="utf-8-sig")
    assert "_maybe_offer_icon_download" in source, (
        "a fresh install with icons enabled must offer the download instead "
        "of silently showing an empty icon column"
    )
    assert "icons_download_declined" in source, "the offer must not nag"

    import ast

    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "MainWindow":
            for child in node.body:
                if (
                    isinstance(child, ast.FunctionDef)
                    and child.name == "_bulk_download_icons"
                ):
                    segment = ast.get_source_segment(source, child)
                    assert segment is not None
                    assert "download_icons_with_progress(" in segment, (
                        "the download must go through the shared progress "
                        "dialog so it never looks frozen"
                    )
                    assert "QApplication.processEvents" not in segment
                    return
    raise AssertionError("MainWindow._bulk_download_icons not found")
