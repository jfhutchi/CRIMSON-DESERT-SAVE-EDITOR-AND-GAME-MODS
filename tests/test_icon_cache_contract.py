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


def test_icons_default_on_in_gui_source() -> None:
    source = (ROOT / "CrimsonSaveEditor" / "gui.py").read_text(encoding="utf-8-sig")
    assert 'self._config.get("show_icons", True)' in source
    assert 'self._config.get("show_icons", False)' not in source


def test_spec_bundles_the_icon_archive() -> None:
    spec = (ROOT / "CrimsonSaveEditor" / "CrimsonSaveEditor.spec").read_text(
        encoding="utf-8"
    )
    assert "icons_bundle.zip" in spec
