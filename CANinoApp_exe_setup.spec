# -*- mode: python ; coding: utf-8 -*-

import glob
import os
import subprocess


def _git(*args):
    return subprocess.check_output(["git", *args]).decode("utf-8").strip()


# The version must be defined as __version__ = "x.y.z"
with open("VERSION", encoding="utf-8") as f:
    __version__ = f.read().strip()

# Commit hash, plus "-dirty" when tracked files differ from it (TODO 10.6):
# an exe named after a commit must contain exactly that commit
try:
    git_hash = _git("rev-parse", "--short", "HEAD")
    if _git("status", "--porcelain", "--untracked-files=no"):
        git_hash += "-dirty"
except Exception:
    git_hash = "nogit"

# Payload-script templates: tracked files only - a local, untracked copy is
# never shipped (TODO 10.3)
try:
    templates = _git("ls-files", "resources/script_templates/*.py").splitlines()
except Exception:
    templates = [
        t.replace(os.sep, "/")
        for t in glob.glob("resources/script_templates/*.py")
        if " " not in os.path.basename(t)
    ]

a = Analysis(
    ['main.py'],
    pathex=[],
    # PCANBasic.dll is not bundled: PEAK's driver setup (required for any PCAN
    # adapter) installs it in System32, which is where python-can loads it from.
    binaries=[
        ('tools/arduino-cli.exe', 'tools'),
    ],
    # src/*.py are compiled into the archive as modules; shipping them again as
    # data files was redundant (TODO 10.3)
    datas=[
        ('VERSION', '.'),
        ('resources/figures/dii_logo.png', 'resources/figures'),
        ('resources/figures/app_logo.ico', 'resources/figures'),
        ('resources/figures/CANinoApp_banner_background.png', 'resources/figures'),
        ('resources/figures/arduino_uno.png', 'resources/figures'),
    ]
    + [(t, 'resources/script_templates') for t in templates],
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
