# -*- mode: python ; coding: utf-8 -*-

import glob
import os
import subprocess


def _git(*args):
    return subprocess.check_output(["git", *args]).decode("utf-8").strip()


# CANINO_ONEDIR=1: a folder (exe + _internal/) instead of one self-extracting
# exe - starts faster, nothing unpacked to %TEMP% at every launch (TODO 10.8)
ONEDIR = os.environ.get("CANINO_ONEDIR") == "1"

# Qt parts CANino never loads - a QtWidgets app without OpenGL, QML, PDF,
# network or virtual keyboard (TODO 10.11). Matched against the bundled path.
QT_UNUSED = (
    "opengl32sw.dll",  # software OpenGL fallback, 20 MB
    "Qt6Quick",
    "Qt6Qml",
    "Qt6Pdf",
    "Qt6VirtualKeyboard",
    "Qt6OpenGL",
    "Qt6Network",
    "QtNetwork.pyd",
    "libcrypto-3-x64.dll",  # Qt's own OpenSSL, for QtNetwork's TLS backend
    "libssl-3-x64.dll",
    "plugins/tls/",
    "plugins/networkinformation/",
    "plugins/platforminputcontexts/",
    "plugins/platforms/qdirect2d",
    "plugins/imageformats/qpdf",
    "plugins/imageformats/qjpeg",
    "plugins/imageformats/qwebp",
    "plugins/imageformats/qtiff",
    "PySide6/translations/",
)


def qt_used(entry):
    dest = entry[0].replace("\\", "/").lower()
    return not any(part.lower() in dest for part in QT_UNUSED)


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
a.binaries = [b for b in a.binaries if qt_used(b)]
a.datas = [d for d in a.datas if qt_used(d)]
pyz = PYZ(a.pure)
name = f'CANinoApp_v{__version__}_h{git_hash}'

exe = EXE(
    pyz,
    a.scripts,
    *([] if ONEDIR else [a.binaries, a.datas]),
    [],
    exclude_binaries=ONEDIR,
    name=name,
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
if ONEDIR:
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, name=name)
