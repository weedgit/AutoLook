# PyInstaller spec file for AutoLook
# Build with: pyinstaller autolook.spec

import sys
from pathlib import Path

block_cipher = None
project_root = Path(SPECPATH)

a = Analysis(
    [str(project_root / 'autolook' / 'main.py')],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / 'config' / 'default_config.json'), 'config'),
    ],
    hiddenimports=[
        'autolook.config',
        'autolook.db.netmonitor_db',
        'autolook.db.incident_db',
        'autolook.detection.text_detector',
        'autolook.detection.domain_app_detector',
        'autolook.detection.nsfw_detector',
        'autolook.detection.ocr_detector',
        'autolook.detection.alert_scorer',
        'autolook.engine.scanner',
        'autolook.engine.watcher',
        'autolook.engine.frame_extractor',
        'autolook.engine.worker',
        'autolook.gui.main_window',
        'autolook.gui.dashboard',
        'autolook.gui.settings_dialog',
        'autolook.gui.incident_viewer',
        'autolook.gui.report_export',
        'autolook.utils.hangul',
        'autolook.utils.thumbnail',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AutoLook',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
