"""
Shared pytest setup.

PyQt5, PyQt6 and PySide6 are all installed in this environment. pyqtgraph
picks PyQt5 by default, which then fights PySide6 over the Qt DLLs and fails
with "DLL load failed while importing QtCore". ``app.py`` pins the binding
before importing pyqtgraph; tests that touch :mod:`evans.ui` need the
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
        from evans.ui import persist
    except ImportError:                      # no Qt: nothing to redirect
        yield
        return
    persist.ORG, persist.APP = "EvansTest", "PersistTest"
    persist.settings().clear()
    yield
    persist.settings().clear()


@pytest.fixture(scope="session", autouse=True)
def _no_openrouter_key():
    """
    Hide the developer's own OpenRouter key from the suite.

    Cedric's panel is built with every main window; with a real key in the
    environment (or saved for the user on Windows) a test that showed it
    would fetch the model list from the network. Tests that want a key hand
    the panel one.
    """
    saved = os.environ.pop("OPENROUTER_API_KEY", None)
    try:
        from evans.ui.assistant import panel
    except ImportError:                      # no Qt: no panel
        panel = None
    if panel is not None:
        real, panel.windows_user_key = panel.windows_user_key, lambda: None
    yield
    if panel is not None:
        panel.windows_user_key = real
    if saved is not None:
        os.environ["OPENROUTER_API_KEY"] = saved


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


def pytest_sessionfinish(session, exitstatus):
    session.config._evans_exitstatus = int(exitstatus)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    """
    End the process as soon as pytest has reported, with pytest's own status.

    The suite leaves hundreds of hidden windows behind, and PySide6 6.12
    crashes in Qt's own C++ teardown of them at interpreter exit: "Fatal
    Python error: Aborted" with no Python frame, after every test had
    passed — exit code 1 on the Windows runner, 139 on Linux. Each test file
    run alone exits cleanly, and so does the application (checked with the
    same versions), so only the full session's leftovers trigger it, and
    tearing them down checks nothing. When Qt was used, skip it. Every report
    has been written by now: this hook runs last, and it passes on pytest's
    own status, so a failing test still fails the run.
    """
    import sys

    widgets = sys.modules.get("PySide6.QtWidgets")
    if widgets is None or widgets.QApplication.instance() is None:
        return
    status = getattr(config, "_evans_exitstatus", 0)
    sys.stdout.flush()
    sys.stderr.flush()
    if sys.platform == "win32":
        # os._exit still runs every DLL's detach code on Windows, Qt's
        # teardown among it, and crashed there. TerminateProcess does not.
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32")
        # Declared, or the pseudo-handle is passed as a 32-bit int on 64-bit
        # Windows, the call fails silently and os._exit below runs anyway.
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateProcess(kernel32.GetCurrentProcess(), status)
    os._exit(status)
