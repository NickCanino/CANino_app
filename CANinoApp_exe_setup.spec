# -*- mode: python ; coding: utf-8 -*-

import subprocess

# The version must be defined as __version__ = "x.y.z"
with open("VERSION", encoding="utf-8") as f:
    __version__ = f.read().strip()

# Obtain the git commit hash
try:
    git_hash = (
        subprocess.check_output(["git", "rev-parse", "--short", "HEAD"])
        .decode("utf-8")
        .strip()
    )
except Exception:
    git_hash = "nogit"

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[
        ('tools/PCANBasic.dll', '.'),
        ('tools/arduino-cli.exe', '.'),
    ],
    datas=[
        ('src/gui.py', '.'),
        ('src/dbc_loader.py', '.'),
        ('src/received_frames_class.py', '.'),
        ('src/can_interface.py', '.'),
        ('src/xmetro_class.py', '.'),
        ('src/exceptions_logger.py', '.'),
        ('src/PCANBasic.py', '.'),
        ('VERSION', '.'),
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
    name=f'CANinoApp_v{__version__}_h{git_hash}',
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
