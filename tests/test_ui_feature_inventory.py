from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _nested_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Call):
        for argument in node.args:
            value = _nested_string(argument)
            if value is not None:
                return value
    if isinstance(node, ast.JoinedStr):
        return "<dynamic-fstring>"
    return None


def _literal_command_snapshot(paths: list[Path]) -> tuple[int, str]:
    rows: list[tuple[str, str, str]] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            else:
                continue
            if name not in {"QPushButton", "QToolButton", "QAction", "addMenu", "addTab"}:
                continue
            arguments = node.args[1:] if name == "addTab" else node.args[:1]
            label = next(
                (value for argument in arguments if (value := _nested_string(argument)) is not None),
                None,
            )
            if label is not None:
                rows.append((path.relative_to(ROOT).as_posix(), name, label))
    rows.sort()
    payload = json.dumps(rows, ensure_ascii=True, separators=(",", ":")).encode()
    return len(rows), hashlib.sha256(payload).hexdigest()


def test_literal_menu_tab_and_command_inventory_is_preserved() -> None:
    save_editor = _literal_command_snapshot([ROOT / "CrimsonSaveEditor" / "gui.py"])
    game_mods = _literal_command_snapshot(
        sorted((ROOT / "CrimsonGameMods" / "gui").rglob("*.py"))
    )
    shared_timer = _literal_command_snapshot(
        [ROOT / "crimson_common" / "blackstar_timer_ui.py"]
    )

    assert save_editor == (
        364,
        "010c468dd91a075725b4d4ddc6184a815d8b87091a775665fc8516eaa409cf6c",
    )
    assert game_mods == (
        537,
        "968e4593211dfb9bb0567461f6c6d924bcdafcd2548f79534cbc9cee6e59ddcc",
    )
    assert shared_timer == (
        3,
        "935c83142b2b38c5ac1c2242ff5026e61168017b9b80ce83f5dc629679d70415",
    )


def _runtime_inventory(component: str) -> dict[str, object]:
    if component == "save":
        component_path = ROOT / "CrimsonSaveEditor"
        import_line = "from gui import MainWindow"
    else:
        component_path = ROOT / "CrimsonGameMods"
        import_line = "from gui.main_window import MainWindow"

    script = f"""
import json
import tempfile
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton, QWidget
{import_line}
temporary = tempfile.TemporaryDirectory(prefix="codex-ui-inventory-")
synthetic_game = Path(temporary.name)
MainWindow._load_config = lambda self: {{"game_install_path": str(synthetic_game)}}
MainWindow._save_config = lambda self: None
MainWindow._refresh_sidebar = lambda self: None
MainWindow._pack_browser_refresh = lambda self: None
app = QApplication.instance() or QApplication([])
window = MainWindow()
window.setAttribute(Qt.WA_DontShowOnScreen, True)
window.resize(1366, 768)
window.show()
app.processEvents()

def layout_report():
    reports = {{}}
    for width, height in ((1366, 768), (1920, 1080)):
        window.resize(width, height)
        app.processEvents()
        by_tabs = {{}}
        for name in ("_tabs", "_save_tabs", "_mods_tabs", "_items_tabs", "_world_tabs"):
            tabs = getattr(window, name)
            selectable = True
            for index in range(tabs.count()):
                tabs.setCurrentIndex(index)
                selectable = selectable and tabs.currentIndex() == index
            bar = tabs.tabBar()
            last_right = bar.tabRect(tabs.count() - 1).right() if tabs.count() else 0
            by_tabs[name] = {{
                "selectable": selectable,
                "fits": last_right <= bar.width(),
                "hidden": bar.isHidden(),
            }}
        destination_nav = window._shell.findChild(QWidget, "destinationNavigation")
        utilities = window._shell.findChild(QWidget, "shellUtilities")
        destination_buttons = window._shell.destination_buttons
        utility_buttons = utilities.findChildren(QToolButton, "shellUtilityButton")
        by_tabs["_shell"] = {{
            "selectable": True,
            "fits": (
                window.width() == width
                and destination_nav.width() > 0
                and utilities.width() > 0
                and all(
                    button.isVisible()
                    and button.geometry().left() >= 0
                    and button.geometry().right() < destination_nav.width()
                    for button in destination_buttons
                )
                and all(
                    button.isVisible()
                    and button.geometry().left() >= 0
                    and button.geometry().right() < utilities.width()
                    for button in utility_buttons
                )
            ),
            "hidden": False,
        }}
        reports[f"{{width}}x{{height}}"] = by_tabs
    return reports

def missing_shell_routes():
    section_names = {{
        id(getattr(window, name)): name
        for name in ("_save_tabs", "_mods_tabs", "_items_tabs", "_world_tabs")
    }}
    actual = set()
    for destination in window._shell._destinations:
        for route in destination.routes:
            if route.section_tabs is None:
                actual.add(f"{{route.primary_index}}:direct")
            else:
                section_name = section_names[id(route.section_tabs)]
                actual.add(
                    f"{{route.primary_index}}:{{section_name}}:{{route.section_index}}"
                )
    required = set()
    for primary_index in range(window._real_tabs.count()):
        primary_widget = window._real_tabs.widget(primary_index)
        section_name = section_names.get(id(primary_widget))
        if section_name is None:
            required.add(f"{{primary_index}}:direct")
            continue
        for section_index in range(primary_widget.count()):
            required.add(f"{{primary_index}}:{{section_name}}:{{section_index}}")
    return sorted(required - actual)

result = {{
    "top": [window._tabs.tabText(i) for i in range(window._tabs.count())],
    "save": [window._save_tabs.tabText(i) for i in range(window._save_tabs.count())],
    "mods": [window._mods_tabs.tabText(i) for i in range(window._mods_tabs.count())],
    "items": [window._items_tabs.tabText(i) for i in range(window._items_tabs.count())],
    "world": [window._world_tabs.tabText(i) for i in range(window._world_tabs.count())],
    "menus": [action.text() for action in window.menuBar().actions()],
    "buttons": sorted({{button.text() for button in window.findChildren(QPushButton) if button.text()}}),
    "game_path": window._global_game_path.text(),
    "synthetic_game": str(synthetic_game),
    "dock_widths": {{name: getattr(window, name).width() for name in ("_save_dock", "_pack_dock")}},
    "save_nav_widths": {{button.text(): button.width() for button in window._save_dock.findChildren(QPushButton) if button.text() in {{"Home", "Backup"}}}},
    "shell_destinations": [button.text() for button in window._shell.destination_buttons],
    "menu_hidden": window.menuBar().isHidden(),
    "missing_shell_routes": missing_shell_routes(),
    "layouts": layout_report(),
}}
print("UI_INVENTORY=" + json.dumps(result, ensure_ascii=True))
window.close()
temporary.cleanup()
"""
    environment = os.environ.copy()
    environment.pop("QT_QPA_PLATFORM", None)
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(component_path), str(ROOT), str(ROOT / "CrimsonGameMods")]
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
        check=True,
    )
    marker = next(
        line for line in completed.stdout.splitlines() if line.startswith("UI_INVENTORY=")
    )
    return json.loads(marker.removeprefix("UI_INVENTORY="))


def test_save_editor_runtime_navigation_and_critical_actions_are_reachable() -> None:
    inventory = _runtime_inventory("save")
    assert inventory["game_path"] == inventory["synthetic_game"]
    assert min(inventory["dock_widths"].values()) >= 210
    assert min(inventory["save_nav_widths"].values()) >= 70
    assert all(
        tab["selectable"]
        for size in inventory["layouts"].values()
        for tab in size.values()
    )
    assert all(
        inventory["layouts"][size][name]["hidden"]
        for size in inventory["layouts"]
        for name in ("_tabs", "_save_tabs", "_items_tabs", "_world_tabs")
    )
    assert inventory["menu_hidden"]
    assert inventory["missing_shell_routes"] == []
    assert all(
        size["_shell"]["fits"] for size in inventory["layouts"].values()
    )
    assert inventory["shell_destinations"] == [
        "SAVE",
        "MOUNTS",
        "INVENTORY",
        "WORLD",
        "TOOLS",
    ]
    assert inventory["top"] == ["Save Editor", "Items", "World", "Backup/Restore"]
    assert inventory["save"] == [
        "Inventory",
        "Item Swap",
        "Repurchase",
        "Equipment",
        "Sockets",
        "Mercenary/Pets",
        "Dye",
    ]
    assert inventory["items"] == ["Item Database", "Item Packs"]
    assert inventory["world"] == [
        "Quest Editor",
        "Quest Database",
        "Abyss Gates",
        "Knowledge",
        "Teleport",
        "Faction",
    ]
    assert inventory["menus"] == ["File", "Edit", "Help", "Update", "View", "Guides", "Dev"]
    assert {
        "Give Item",
        "Delete Item",
        "Preview Blackstar",
        "Preview 30m / 1s",
        "Apply Preset",
        "Restore Original",
        "Learn Selected",
        "Unlearn Selected",
        "Reveal Map",
        "Backup to Local Folder",
    } <= set(inventory["buttons"])


def test_game_mods_runtime_navigation_and_critical_actions_are_reachable() -> None:
    inventory = _runtime_inventory("mods")
    assert inventory["game_path"] == inventory["synthetic_game"]
    assert all(
        tab["selectable"]
        for size in inventory["layouts"].values()
        for tab in size.values()
    )
    assert all(
        inventory["layouts"][size][name]["hidden"]
        for size in inventory["layouts"]
        for name in ("_tabs", "_mods_tabs", "_items_tabs")
    )
    assert inventory["menu_hidden"]
    assert inventory["missing_shell_routes"] == []
    assert all(
        size["_shell"]["fits"] for size in inventory["layouts"].values()
    )
    assert inventory["shell_destinations"] == [
        "SAVE",
        "MOUNTS",
        "INVENTORY",
        "WORLD",
        "MODS",
    ]
    assert inventory["top"] == ["Game Mods", "Items"]
    assert inventory["mods"] == [
        "Game Patches",
        "FieldEdit",
        "Dragon Wheel",
        "ItemBuffs",
        "Stacker Tool",
        "Stores",
        "BagSpace",
        "DropSets",
        "SpawnEdit",
        "SkillTree",
        "MercPets",
        "Load Manager",
        "Game Browser",
    ]
    assert inventory["items"] == ["Item Database"]
    assert inventory["menus"] == ["File", "Edit", "Help", "Discord", "Update", "View", "Guides"]
    assert {
        "Preview 30m / 1s",
        "Apply Preset",
        "Restore Original",
        "Load FieldInfo",
        "Enable Mounts Everywhere",
        "1. Analyze Game Files",
        "2. Preview Dragon Wheel Patch",
        "3. Apply Dragon Wheel Patch",
        "Apply to Game",
    } <= set(inventory["buttons"])
