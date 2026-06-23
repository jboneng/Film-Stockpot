# PyInstaller spec for a standalone Windows x64 build of Film Stockpot.
# Run via: uv run pyinstaller packaging/film_stockpot.spec --noconfirm --clean

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None

root = Path(SPECPATH).parent
src = root / "src"
entry = src / "film_stockpot" / "__main__.py"

pyqt_datas, pyqt_binaries, pyqt_hiddenimports = collect_all("PyQt6")
img_datas, img_binaries, img_hiddenimports = collect_all("imagecodecs")

datas = [
    (str(root / "FilmPresets"), "FilmPresets"),
    (str(src / "film_stockpot" / "assets"), "film_stockpot/assets"),
]
datas += pyqt_datas + img_datas

binaries = pyqt_binaries + img_binaries

hiddenimports = [
    "PyQt6.QtSvg",
    "PyQt6.sip",
]
hiddenimports += pyqt_hiddenimports + img_hiddenimports

a = Analysis(
    [str(entry)],
    pathex=[str(src)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name="FilmStockpot",
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
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="FilmStockpot",
)
