"""
Shared pytest setup.

PyQt5, PyQt6 and PySide6 are all installed in this environment. pyqtgraph
picks PyQt5 by default, which then fights PySide6 over the Qt DLLs and fails
with "DLL load failed while importing QtCore". ``app.py`` pins the binding
before importing pyqtgraph; tests that touch :mod:`fakematlab.ui` need the
same pin, applied before any Qt import happens.
"""

import os

import pytest

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def _scratch_persistence():
    """
    Keep the command history and recent files out of the user's own.

    Session-wide, so it is in place first: a module-scoped window is built
    before any function fixture runs, and it reads and writes both as it goes.
    """
    try:
        from fakematlab.ui import persist
    except ImportError:                      # no Qt: nothing to redirect
        yield
        return
    persist.ORG, persist.APP = "FauxMatlabTest", "PersistTest"
    persist.settings().clear()
    yield
    persist.settings().clear()
