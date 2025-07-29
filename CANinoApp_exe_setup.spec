# -*- mode: python ; coding: utf-8 -*-

import re

with open("src/version.py", encoding="utf-8") as f:
    content = f.read()
    match = re.search(r'__version__\s*=\s*[\'"]([^\'"]+)[\'"]', content)
    __version__ = match.group(1) if match else "0.0.000"

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[('resources/PCANBasic.dll', '.')],
    datas=[
        ('src/gui.py', '.'),
        ('src/dbc_loader.py', '.'),
        ('src/received_frames_class.py', '.'),
        ('src/can_interface.py', '.'),
        ('src/xmetro_class.py', '.'),
        ('src/exceptions_logger.py', '.'),
        ('src/version.py', '.'),
        ('src/PCANBasic.py', '.'),
        ('resources/figures/dii_logo.png', 'resources/figures'),
        ('resources/figures/app_logo.ico', 'resources/figures'),
        ('resources/figures/CANinoApp_banner_background.png', 'resources/figures'),
    ],
    hiddenimports=['can.interfaces.pcan'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=f'CANinoApp_v{__version__}',
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
    codesign_identity=None,
    entitlements_file=None,
    icon='resources/figures/app_logo.ico'
)
