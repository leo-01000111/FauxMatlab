"""
Shared pytest setup.

PyQt5, PyQt6 and PySide6 are all installed in this environment. pyqtgraph
picks PyQt5 by default, which then fights PySide6 over the Qt DLLs and fails
with "DLL load failed while importing QtCore". ``app.py`` pins the binding
before importing pyqtgraph; tests that touch :mod:`fakematlab.ui` need the
same pin, applied before any Qt import happens.
"""

import os

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
