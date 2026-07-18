from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
GAME_MODS = ROOT / "CrimsonGameMods"
if str(GAME_MODS) not in sys.path:
    sys.path.insert(0, str(GAME_MODS))

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QLabel,
    QMainWindow,
    QMenuBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from crimson_common.crimson_shell import (
    CrimsonApplicationShell,
    CrimsonRouteButton,
    ShellCommand,
    ShellDestination,
    ShellRoute,
    install_crimson_application_shell,
)


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _router() -> tuple[QTabWidget, QTabWidget, QTabWidget]:
    router = QTabWidget()
    first = QTabWidget()
    second = QTabWidget()
    first.addTab(QLabel("Alpha"), "Alpha")
    first.addTab(QLabel("Beta"), "Beta")
    second.addTab(QLabel("Gamma"), "Gamma")
    router.addTab(first, "First")
    router.addTab(second, "Second")
    return router, first, second


def test_shell_replaces_visible_tab_chrome_with_destination_and_context_navigation() -> None:
    _application()
    router, first, second = _router()
    destinations = (
        ShellDestination(
            "SAVE",
            (ShellRoute("Alpha", 0, first, 0, "A concise route description"),),
        ),
        ShellDestination("MOUNTS", (ShellRoute("Beta", 0, first, 1),)),
        ShellDestination("INVENTORY", (ShellRoute("Gamma", 1, second, 0),)),
        ShellDestination("WORLD", (ShellRoute("World Home", 0, first, 0),)),
        ShellDestination("TOOLS", (ShellRoute("Tool Home", 1, second, 0),)),
    )

    shell = CrimsonApplicationShell(
        product="SAVE EDITOR",
        router_tabs=router,
        destinations=destinations,
    )

    assert shell.objectName() == "crimsonApplicationShell"
    assert shell.findChild(QWidget, "commandHeader") is not None
    assert shell.findChild(QWidget, "contextNavigation") is not None
    assert shell.findChild(QWidget, "editorialWorkspace") is not None
    assert all(not button.icon().isNull() for button in shell.destination_buttons)
    assert [button.text() for button in shell.destination_buttons] == [
        "SAVE",
        "MOUNTS",
        "INVENTORY",
        "WORLD",
        "TOOLS",
    ]
    assert router.tabBar().isHidden()
    assert first.tabBar().isHidden()
    assert second.tabBar().isHidden()

    shell.resize(1366, 768)
    shell.show()
    _application().processEvents()
    assert shell.route_description.width() >= 320

    shell.activate_destination(1)
    assert router.currentIndex() == 0
    assert first.currentIndex() == 1
    assert shell.context_title.text() == "MOUNTS"
    assert [button.text() for button in shell.route_buttons] == ["Beta"]

    shell.activate_destination(2)
    assert router.currentIndex() == 1
    assert second.currentIndex() == 0
    assert [
        button.text()
        for button in shell.findChildren(QAbstractButton, "routeButton")
    ] == ["Gamma"]

    router.setCurrentIndex(0)
    first.setCurrentIndex(1)
    assert shell.context_title.text() == "MOUNTS"
    assert shell.route_title.text() == "Beta"


def test_shell_uses_game_art_in_the_registry_and_supports_immersive_routes() -> None:
    _application()
    router, first, _second = _router()
    route = ShellRoute(
        "Blackstar",
        0,
        first,
        0,
        "Blackstar ownership and archive settings.",
        icon_name="mounts",
        game_art_id=1000799,
        badge="DRAGON",
        immersive=True,
    )
    shell = CrimsonApplicationShell(
        product="SAVE EDITOR",
        router_tabs=router,
        destinations=(ShellDestination("MOUNTS", (route,), "Mount registry"),),
        commands=(ShellCommand("PATH", lambda: None, "Choose game path", "path"),),
    )

    shell.show()
    _application().processEvents()

    button = shell.findChild(QAbstractButton, "routeButton")
    assert isinstance(button, CrimsonRouteButton)
    assert button.badge == "DRAGON"
    assert button.uses_game_art
    assert not button.icon().isNull()
    assert shell.findChild(QWidget, "routeHeader").isHidden()
    assert shell.context_eyebrow.text() == "MOUNT REGISTRY"
    utility = shell.findChild(QAbstractButton, "shellUtilityButton")
    assert utility is not None
    assert not utility.icon().isNull()


def test_shell_keeps_legacy_menu_and_path_controls_reachable_but_collapsed() -> None:
    _application()
    router, first, _second = _router()
    menu_bar = QMenuBar()
    menu_bar.addMenu("File")
    context_strip = QLabel("Game path")
    destinations = tuple(
        ShellDestination(label, (ShellRoute("Alpha", 0, first, 0),))
        for label in ("SAVE", "MOUNTS", "INVENTORY", "WORLD", "TOOLS")
    )

    shell = CrimsonApplicationShell(
        product="SAVE EDITOR",
        router_tabs=router,
        destinations=destinations,
        menu_bar=menu_bar,
        context_widget=context_strip,
    )

    assert menu_bar.isHidden()
    assert context_strip.isHidden()
    shell.toggle_menu()
    shell.toggle_context()
    assert not menu_bar.isHidden()
    assert not context_strip.isHidden()
    shell.toggle_menu()
    shell.toggle_context()
    assert menu_bar.isHidden()
    assert context_strip.isHidden()


def test_external_navigation_preserves_the_active_destination_for_duplicate_routes() -> None:
    _application()
    router, first, second = _router()
    duplicate_routes = (
        ShellRoute("Alpha", 0, first, 0),
        ShellRoute("Beta", 0, first, 1),
    )
    shell = CrimsonApplicationShell(
        product="GAME MODS",
        router_tabs=router,
        destinations=(
            ShellDestination("SAVE", duplicate_routes),
            ShellDestination("MOUNTS", (ShellRoute("Gamma", 1, second, 0),)),
            ShellDestination("INVENTORY", (ShellRoute("Gamma", 1, second, 0),)),
            ShellDestination("WORLD", (ShellRoute("Gamma", 1, second, 0),)),
            ShellDestination("MODS", duplicate_routes),
        ),
    )

    shell.activate_destination(4)
    first.setCurrentIndex(1)

    assert shell.context_title.text() == "MODS"
    assert shell.route_title.text() == "Beta"


def test_installer_preserves_legacy_widgets_referenced_after_central_replacement() -> None:
    _application()
    window = QMainWindow()
    old_central = QWidget()
    old_layout = QVBoxLayout(old_central)
    center_status = QLabel("Ready")
    context_strip = QLabel("Game path")
    router, first, _second = _router()
    old_layout.addWidget(center_status)
    old_layout.addWidget(context_strip)
    old_layout.addWidget(router)
    window.setCentralWidget(old_central)

    shell = install_crimson_application_shell(
        window,
        product="SAVE EDITOR",
        router_tabs=router,
        destinations=tuple(
            ShellDestination(label, (ShellRoute("Alpha", 0, first, 0),))
            for label in ("SAVE", "MOUNTS", "INVENTORY", "WORLD", "TOOLS")
        ),
        context_widget=context_strip,
        preserve_widgets=(center_status,),
    )
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    center_status.setText("Still alive")
    assert center_status.text() == "Still alive"
    assert center_status.parent() is shell
    assert center_status.isHidden()


def test_both_windows_install_the_structural_shell_after_building_routes() -> None:
    for relative in (
        "CrimsonSaveEditor/gui.py",
        "CrimsonGameMods/gui/main_window.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "install_crimson_application_shell(" in source
        assert "self._shell_destinations()" in source
        assert "Select a save with SAVES or Menu > File > Open" in source
