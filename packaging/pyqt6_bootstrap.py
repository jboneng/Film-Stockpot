# PyInstaller runtime hook: set Qt6 DLL search paths before PyQt6 is imported.
# Runs in addition to PyInstaller's pyi_rth_pyqt6 hook.


def _bootstrap_pyqt6_dll_paths() -> None:
    import os
    import sys

    if not getattr(sys, "frozen", False):
        return

    base = getattr(sys, "_MEIPASS", "")
    if not base:
        return

    qt_root = os.path.join(base, "PyQt6", "Qt6")
    qt_bin = os.path.join(qt_root, "bin")
    pyqt_dir = os.path.join(base, "PyQt6")

    if os.path.isdir(qt_bin):
        os.environ["PATH"] = qt_bin + os.pathsep + os.environ.get("PATH", "")
        try:
            os.add_dll_directory(qt_bin)
        except (AttributeError, OSError):
            pass

    if os.path.isdir(pyqt_dir):
        try:
            os.add_dll_directory(pyqt_dir)
        except (AttributeError, OSError):
            pass

    plugins = os.path.join(qt_root, "plugins")
    if os.path.isdir(plugins):
        os.environ["QT_PLUGIN_PATH"] = plugins


_bootstrap_pyqt6_dll_paths()
del _bootstrap_pyqt6_dll_paths
