# Crimson Desert UI Redesign

## Outcome

Redesign both Windows tools so they feel native to Crimson Desert while keeping
the Save Editor and Game Mods as separate executables. Preserve every existing
feature, callback, persistence key, menu, tab, dialog entry point, Blackstar
ownership action, and Blackstar timer action. The redesign changes presentation
and navigation clarity; it does not merge the applications or alter save/game
mutation behavior.

## Feature Inventory Boundary

The pre-redesign inventory is executable in `tests/test_ui_feature_inventory.py`.
It snapshots 364 Save Editor and 537 Game Mods literal menu, tab, button, and
action constructions, plus the three shared timer commands. Runtime offscreen
tests also verify the complete primary and secondary navigation trees.

| Application | Primary destination | Existing surfaces retained |
| --- | --- | --- |
| Save Editor | Save Editor | Inventory, Item Swap, Repurchase, Equipment, Sockets, Mercenary/Pets, Dye |
| Save Editor | Items | Item Database, Item Packs |
| Save Editor | World | Quest Editor, Quest Database, Abyss Gates, Knowledge, Teleport, Faction |
| Save Editor | Utility | Backup/Restore, Save Browser, Pack Browser, Settings, guides, update, experimental mode |
| Game Mods | Game Mods | Game Patches, FieldEdit, Dragon Wheel, ItemBuffs, Stacker Tool, Stores, BagSpace, DropSets, SpawnEdit, SkillTree, MercPets, Load Manager, Game Browser |
| Game Mods | Items | Item Database |
| Shared | Blackstar | Preview 30m/1s, Apply Preset, Restore Original, progress, reports, safety warning |

Dialogs and context commands remain owned by their current modules. The new
theme applies through Qt object roles and a global stylesheet, so dialog logic,
models, signals, and mutation callbacks do not move.

## Visual Direction

The interface uses the approved Blackstar mockup's restrained Crimson Desert
vocabulary instead of generic dashboard cards, gold-outlined Qt forms, or the
old DOS-like treatment:

- Ink `#050706` and obsidian `#080B09` form the green-black application depth.
- Surface `#0D120F` and warm surface `#17150F` create subtle editorial depth.
- Graphite `#29302B` draws quiet one-pixel dividers rather than control boxes.
- Bone `#E6E1D7` and bright bone `#F2EDE3` carry primary text; ash `#7F857D`
  carries descriptions and inactive navigation.
- Crimson `#B63A32` is the focused accent for selection underlines, section
  eyebrows, primary actions, and left-edge status markers.
- Moss `#78917B`, amber `#A88455`, and iron red `#C05247` communicate success,
  warning, and error without becoming decorative fills.

Panels are squared and largely borderless. Generic group boxes use a single
graphite top rule; buttons are transparent until selected; primary and
secondary navigation use crimson underlines instead of boxed tabs. A restrained
warm gradient is reserved for the Blackstar work surface and contextual strips.

The Blackstar timer is the reference surface: a red eyebrow and large serif
title lead into two before/after metric rows, a left-rule verification status,
and a right-hand Change Record. This exact surface is shared by both executables.

## Typography

Display and navigation roles use Georgia with Cambria as fallback. Dense body,
control, and table roles use Bahnschrift SemiCondensed with Segoe UI fallback.
Monospace is limited to hashes, offsets, paths, and diagnostic reports. No font
download or extra font license is required on supported Windows systems.

## Application Shell

Each window uses one full-width command header with a restrained brand block,
five destination-level navigation choices, and a quiet utility cluster. A
contextual left rail lists only the routes relevant to the selected destination.
The remaining width is one uninterrupted editorial work surface with a compact
route title and the existing feature page below it.

Existing `QTabWidget` instances remain the routing mechanism and keep their
current indices, callbacks, and View-menu actions, but their tab bars are hidden.
Changes made through shortcuts or the legacy View menu synchronize back to the
new destination and route selection. This preserves functionality without
making nested native tab strips the visible information architecture.

The native menu and game-path strip are collapsed by default and remain
available through `MENU` and `PATH` utilities in the header. Save Browser and
Pack Browser remain dockable, but open on demand through `SAVES` and `PACKS`
rather than permanently boxing in the workspace. The existing status bar forms
the bottom command rail.

## Component Roles

Both applications expose a `crimson_theme.py` entry point. Those entry points
provide the same token names, typography roles, object-name contracts, minimum
control sizes, focus treatment, and stylesheet builder. Game Mods retains its
light-theme menu as a parchment-day variant rather than removing a current
feature. The Save Editor receives the Crimson dark presentation by default.

Stable roles include:

- `crimsonWindow` for the main window;
- `primaryNav` for application-level tabs;
- `sectionNav` for feature-level tabs;
- `contextStrip` for the game/save path strip;
- `statusRail` for the bottom status area;
- `saveBrowser` and `packBrowser` for dock workflows;
- `dangerAction`, `primaryAction`, and `quietAction` dynamic properties for
  semantic button emphasis where an existing action already has that meaning.
- `brandBlock`, `brandMark`, and `shellIdentity` for the branded primary rail;
- `crimsonApplicationShell`, `commandHeader`, `destinationNavigation`,
  `contextNavigation`, `routeNavigation`, `routeHeader`, and
  `editorialWorkspace` for the structural shell;
- `blackstarTimerPanel`, `blackstarMetricRow`, and `changeRecord` for the shared
  reference surface.

## Interaction And Accessibility

All interactive controls have at least a 28-pixel compact height, visible
keyboard focus, and sufficient parchment/obsidian contrast. Destination and
route selection use text, a crimson rule, and subtle tonal depth rather than
boxed tab states. Existing keyboard shortcuts, F-key navigation, tab order,
context menus, detachable legacy tools, UI scale, zoom, and compact mode remain
operational.

The minimum supported layout is 1366x768 at 100 percent scale. Both windows must
also render at 1920x1080 and with Qt high-DPI scaling. Horizontal overflow stays
inside existing table/scroll areas; required primary navigation remains visible.
Motion is limited to native progress indication so the redesign adds no animation
latency or reduced-motion concern.

## Responsiveness Boundary

Styling alone is not considered a responsiveness fix. After the shell migration,
all button-reachable filesystem scans, save parsing, archive parsing, compression,
encryption, serialization, database loading, and bulk enrichment paths are
audited. Expensive work moves to workers with phase reporting. UI population
returns to the GUI thread in bounded updates. Errors remain visible in the log
and a dialog; controls are restored on success, error, and cancellation.

The Blackstar timer already follows this worker model. Save loading and other
high-cost legacy paths receive separate regression contracts before any behavior
change.

## Verification

Verification combines:

- literal command inventory hashes to catch removed actions;
- offscreen runtime navigation checks for both complete shells;
- theme token, focus, type, and minimum-size contracts;
- 1366x768 and 1920x1080 layout checks;
- existing save, Blackstar, Dragon Wheel, timer, and GUI behavior suites;
- responsiveness contracts for audited heavy callbacks;
- fresh PyInstaller builds and safe smoke tests using no real save and only a
  copied synthetic game directory.

The final adversarial review treats missing features, weak compatibility gates,
GUI-thread work, unsafe writes, restore gaps, and untracked build/test artifacts
as release blockers.
