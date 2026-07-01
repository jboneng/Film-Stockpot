# PyInstaller runtime hook: register Qt6 DLL directories before PyQt6 is imported.
# Runs before PyInstaller's pyi_rth_pyqt6 hook; PATH is finalized in qt_runtime.py.


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

    for path in (qt_bin, pyqt_dir, base):
        if os.path.isdir(path):
            try:
                os.add_dll_directory(path)
            except (AttributeError, OSError):
                pass

    plugins = os.path.join(qt_root, "plugins")
    if os.path.isdir(plugins):
        os.environ["QT_PLUGIN_PATH"] = plugins
        platforms = os.path.join(plugins, "platforms")
        if os.path.isdir(platforms):
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = platforms


_bootstrap_pyqt6_dll_paths()
del _bootstrap_pyqt6_dll_paths
