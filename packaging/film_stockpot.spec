# PyInstaller spec for a standalone Windows x64 build of Film Stockpot.
# Run via: uv run pyinstaller packaging/film_stockpot.spec --noconfirm --clean

from pathlib import Path

from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.hooks.qt import pyqt6_library_info

block_cipher = None

root = Path(SPECPATH).parent
src = root / "src"
entry = src / "film_stockpot" / "__main__.py"

img_datas, img_binaries, img_hiddenimports = collect_all("imagecodecs")

datas = [
    (str(root / "FilmPresets"), "FilmPresets"),
    (str(src / "film_stockpot" / "assets"), "film_stockpot/assets"),
]
datas += img_datas

binaries = list(img_binaries)
binaries += pyqt6_library_info.collect_extra_binaries()

hiddenimports = [
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.QtSvg",
    "PyQt6.sip",
]
hiddenimports += img_hiddenimports

for _qt_module in ("PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets", "PyQt6.QtSvg"):
    mod_hidden, mod_bins, mod_datas = pyqt6_library_info.collect_module(_qt_module)
    hiddenimports += mod_hidden
    binaries += mod_bins
    datas += mod_datas

_pyqt6_excludes = [
    f"PyQt6.{name}"
    for name in (
        "QAxContainer",
        "QtBluetooth",
        "QtDBus",
        "QtDesigner",
        "QtHelp",
        "QtMultimedia",
        "QtMultimediaWidgets",
        "QtNfc",
        "QtOpenGL",
        "QtOpenGLWidgets",
        "QtPdf",
        "QtPdfWidgets",
        "QtPositioning",
        "QtPrintSupport",
        "QtQml",
        "QtQuick",
        "QtQuick3D",
        "QtQuickWidgets",
        "QtRemoteObjects",
        "QtSensors",
        "QtSerialPort",
        "QtSpatialAudio",
        "QtSql",
        "QtStateMachine",
        "QtSvgWidgets",
        "QtTest",
        "QtTextToSpeech",
        "QtWebChannel",
        "QtWebEngineCore",
        "QtWebEngineQuick",
        "QtWebEngineWidgets",
        "QtWebSockets",
        "QtXml",
        "uic",
    )
]

runtime_hooks = [str(root / "packaging" / "pyqt6_bootstrap.py")]

a = Analysis(
    [str(entry)],
    pathex=[str(src)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=runtime_hooks,
    excludes=_pyqt6_excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FilmStockpot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FilmStockpot",
)
