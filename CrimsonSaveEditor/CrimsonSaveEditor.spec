import zipfile
from pathlib import Path

SPEC_DIR = Path(SPECPATH).resolve()
REPO_ROOT = SPEC_DIR.parent
GAME_MODS_ROOT = REPO_ROOT / 'CrimsonGameMods'

# Bundle the complete icon set as one stored zip; the app extracts it next to
# the executable on first launch so icons work offline and default to on.
ICONS_BUNDLE = Path(workpath) / 'icons_bundle.zip'
_icon_sources = [
    ('icons_local', REPO_ROOT / 'icons_local'),
    ('icons_mercenary', REPO_ROOT / 'icons_mercenary'),
]
_source_files = [
    (prefix, path)
    for prefix, folder in _icon_sources
    if folder.is_dir()
    for path in sorted(folder.glob('*.webp'))
]
_needs_build = True
if ICONS_BUNDLE.is_file():
    with zipfile.ZipFile(ICONS_BUNDLE) as _zf:
        _needs_build = len(_zf.namelist()) != len(_source_files)
if _needs_build:
    ICONS_BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ICONS_BUNDLE, 'w', zipfile.ZIP_STORED) as _zf:
        for _prefix, _path in _source_files:
            _zf.write(_path, f'{_prefix}/{_path.name}')

a = Analysis(
    ['main.py'],
    pathex=[str(SPEC_DIR), str(REPO_ROOT), str(GAME_MODS_ROOT)],
    binaries=[],
    datas=[
        ('parc_parser.dll', '.'),
        ('item_names.json', '.'),
        ('store_names.json', '.'),
        ('item_templates.json', '.'),
        ('master_templates.json', '.'),
        ('item_limits.json', '.'),
        ('item_category_map.json', '.'),
        ('max_enchant_map.json', '.'),
        ('waypoint_templates_community.json', '.'),
        ('abyss_gimmick_templates.json', '.'),
        ('knowledge_keys_all.json', '.'),
        ('community_knowledge_keys.json', '.'),
        ('quest_names.json', '.'),
        ('quest_database.json', '.'),
        ('mission_names.json', '.'),
        ('quest_stage_map.json', '.'),
        ('stage_names.json', '.'),
        ('gimmick_respawn_timers.json', '.'),
        ('quest_chains.json', '.'),
        ('dye_slot_counts.json', '.'),
        ('buff_skill_descriptions.json', '.'),
        ('game_map.json', '.'),
        ('localizationstring_eng_items.tsv', '.'),
        ('editor_version_standalone.json', '.'),
        ('save_schema_profiles.json', '.'),
        ('locale', 'locale'),
        ('knowledge_packs', 'knowledge_packs'),
        (str(REPO_ROOT / 'icons_mercenary' / '1000799.webp'), 'crimson_assets'),
        (str(ICONS_BUNDLE), '.'),
        (str(REPO_ROOT / 'crimson_common'), 'crimson_common'),
        (str(GAME_MODS_ROOT / 'crimson_rs'), 'crimson_rs'),
    ],
    hiddenimports=[
        'lz4',
        'lz4.block',
        'cryptography',
        'cryptography.hazmat.primitives.ciphers',
        'cryptography.hazmat.primitives.ciphers.algorithms',
        'iteminfo_parser',
        'parc_inserter3',
        'parc_inserter2',
        'parc_serializer',
        'save_parser',
        'save_pet_rename',
        'quest_deep_parser',
        'questinfo_parser',
        'item_template_db',
        'ben_save_decrypt',
        'app_logging',
        'save_compat',
        'blackstar_compat',
        'blackstar_template',
        'blackstar_unlock',
        'blackstar_worker',
        'crimson_common',
        'crimson_common.blackstar_timer',
        'crimson_common.blackstar_timer_worker',
        'crimson_common.blackstar_timer_ui',
        'crimson_common.crimson_theme',
        'crimson_common.crimson_icons',
        'crimson_common.crimson_shell',
        'crimson_common.gui_population',
        'crimson_common.gui_task_worker',
        'crimson_theme',
        'crimson_rs',
        'crimson_rs.enums',
        'crimson_rs.create_pack',
        'crimson_rs.pack_mod',
        'crimson_rs.validate_game_dir',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

splash = Splash(
    'splash.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(24, 195),
    text_size=10,
    text_color='#F0F0F5',
    text_default='Initializing...',
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    splash,
    splash.binaries,
    [],
    name='CrimsonSaveEditorStandalone',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    icon='app_icon.ico',
    codesign_identity=None,
    entitlements_file=None,
)
