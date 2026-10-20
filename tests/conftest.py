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


@pytest.fixture(scope="session", autouse=True)
def _no_modal_dialogs():
    """
    Fail at once on a dialog no test answered, instead of hanging.

    A modal dialog waits for a click that never comes on a headless runner.
    One did: an SVG export failed on a newer PySide6, the figure view showed
    "Save failed" in a QMessageBox, and CI sat on it until GitHub cancelled
    the job six hours later. A test that expects a dialog patches it itself
    (``monkeypatch.setattr``), which takes precedence over this.
    """
    try:
        from PySide6.QtWidgets import QFileDialog, QMessageBox
    except ImportError:                      # no Qt: no dialogs
        yield
        return

    def refuse(what):
        def dialog(*args, **kwargs):
            text = " | ".join(str(a) for a in args[1:3] if isinstance(a, str))
            raise AssertionError(f"unexpected modal {what}: {text}")
        return dialog

    saved = {}
    for owner, names in ((QMessageBox, ("warning", "information",
                                        "critical", "question", "exec")),
                         (QFileDialog, ("getSaveFileName", "getOpenFileName",
                                        "getExistingDirectory"))):
        for name in names:
            saved[owner, name] = getattr(owner, name)
            setattr(owner, name, refuse(f"{owner.__name__}.{name}"))
    yield
    for (owner, name), original in saved.items():
        setattr(owner, name, original)
