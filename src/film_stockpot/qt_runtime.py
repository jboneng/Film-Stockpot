"""Windows frozen-app Qt6 DLL path setup.

PyInstaller's ``pyi_rth_pyqt6`` runtime hook prepends ``sys._MEIPASS`` to
``PATH`` *after* our packaging runtime hook runs. That can make Windows load
incompatible DLLs from the bundle root before the matching copies in
``PyQt6/Qt6/bin``, which surfaces as::

    DLL load failed while importing QtWidgets: The specified procedure could not be found.

Call :func:`ensure_qt_dll_paths` immediately before the first PyQt6 import in
the GUI entry path so ``PATH`` is sanitized after all runtime hooks finish.
"""

from __future__ import annotations


def ensure_qt_dll_paths() -> None:
    """Register bundled Qt directories and replace ``PATH`` on frozen builds."""
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
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    system32 = os.path.join(system_root, "System32")

    for path in (qt_bin, pyqt_dir, base):
        if os.path.isdir(path):
            try:
                os.add_dll_directory(path)
            except (AttributeError, OSError):
                pass

    path_parts = [p for p in (qt_bin, pyqt_dir, system32, system_root) if os.path.isdir(p)]
    os.environ["PATH"] = os.pathsep.join(path_parts)

    plugins = os.path.join(qt_root, "plugins")
    if os.path.isdir(plugins):
        os.environ["QT_PLUGIN_PATH"] = plugins
        platforms = os.path.join(plugins, "platforms")
        if os.path.isdir(platforms):
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = platforms
