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

The interface uses a restrained Crimson Desert vocabulary instead of generic
dashboard cards or the current DOS-like monospace treatment:

- Ink `#0A0907` and obsidian `#12100D` form the application depth.
- Charcoal `#201A14` and ember `#2C2118` separate work areas without cards.
- Bronze `#9C743B` and bright bronze `#C6A15F` draw one-pixel rules, focus, and
  selected navigation.
- Parchment `#E7DCC5` is primary text; ash `#A89B87` is secondary text.
- Crimson `#87352D` is reserved for destructive or dangerous actions, never used
  as a decorative wash.
- Moss `#758B5C`, amber `#C28A3C`, and iron red `#A94A3E` communicate success,
  warning, and error.

Panels are squared and translucent-looking through layered near-black colors,
not rounded floating cards. Separators are narrow bronze rules. Texture comes
from subtle linear gradients in headers and selected tabs rather than images,
which keeps builds deterministic and high-DPI safe.

## Typography

Display and navigation roles use Georgia with Cambria as fallback. Dense body,
control, and table roles use Bahnschrift SemiCondensed with Segoe UI fallback.
Monospace is limited to hashes, offsets, paths, and diagnostic reports. No font
download or extra font license is required on supported Windows systems.

## Application Shell

Each window keeps the native menu bar, then presents a horizontal primary
navigation band and a compact secondary navigation band. Existing `QTabWidget`
instances remain the routing mechanism, receive stable object names, and keep
their current indices and callbacks. The game path strip becomes a contextual
bronze-edged command strip. The main workspace remains dense and table-first.

Save Browser and Pack Browser remain dockable. Game Mods continues to open them
on demand; Save Editor continues to expose both as persistent workflow tools.
The status bar becomes a bottom command rail with concise state, progress, and
keyboard hints. No navigation is hidden behind a new hamburger menu.

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

## Interaction And Accessibility

All interactive controls have at least a 28-pixel compact height, visible
keyboard focus, and sufficient parchment/obsidian contrast. Selected tabs use
text, border, and background changes rather than color alone. Existing keyboard
shortcuts, F-key navigation, tab order, context menus, detachable tabs, UI scale,
zoom, and compact mode remain operational.

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
