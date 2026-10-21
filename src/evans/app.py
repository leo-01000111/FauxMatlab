"""
Evans — a classical and modern control workbench.

    evans            open the window          (python app.py from a checkout)
    evans FILE       open the window with FILE: a .fmdl model on the Model
                     canvas, a script in the Console (what double-clicking a
                     file associated with Evans sends)
    evans --check    run the headless self-test and exit
    evans --version  print the version and exit

``--check`` is the one a packaged build needs: it ships without the test
suite, so this is how you ask an installed copy whether it works. Its exit
code is the number of failed checks.
"""

import os
import sys
from pathlib import Path

# Force pyqtgraph to use PySide6 BEFORE it (or anything else) loads Qt DLLs.
# With PyQt5/PyQt6/PySide6 all installed, pyqtgraph defaults to PyQt5 which
# conflicts with PySide6 at the DLL level.
os.environ["PYQTGRAPH_QT_LIB"] = "PySide6"
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

# Read from the package rather than declared here, so the two cannot
# drift — which they already had.
from evans import __version__ as VERSION


def _run_check(argv: list[str]) -> int:
    """
    The self-test. Imported late and deliberately.

    ``--check`` has to work on a machine with no display, so nothing above
    this line may have opened a Qt GUI connection. The self-test pins the
    offscreen platform itself before it touches Qt.
    """
    from evans.selftest import run

    report = run(verbose="--quiet" not in argv,
                 include_ui="--no-ui" not in argv)
    return len(report.failures)


#: The taskbar identity Windows groups this program's windows under.
APP_USER_MODEL_ID = "LeonGorecki.Evans"


def _claim_taskbar_identity() -> None:
    """
    Give the taskbar button Evans' own icon on Windows.

    Without an explicit AppUserModelID, Windows groups the window under the
    executable that started it. From a checkout that is python.exe, so the
    taskbar showed Python's icon whatever icon the window set. Must run
    before the first window is created.
    """
    if sys.platform != "win32":
        return
    import ctypes

    try:
        set_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_id.argtypes = [ctypes.c_wchar_p]
        set_id(APP_USER_MODEL_ID)
    except (AttributeError, OSError):       # very old Windows: keep default
        pass


def _file_arguments(argv: list[str]) -> list[Path]:
    """
    The files named on the command line, in order.

    Anything starting with ``-`` is an option, ours or Qt's, and is skipped.
    Pass the arguments after Qt has taken its own (``app.arguments()``), so
    the value of a Qt option such as ``-style fusion`` is gone too. Whether
    each file exists is left to the window, which says so in the status bar
    rather than failing the launch.
    """
    return [Path(arg) for arg in argv if arg and not arg.startswith("-")]


def main() -> None:
    argv = sys.argv[1:]

    if "--version" in argv:
        print(f"Evans {VERSION}")
        raise SystemExit(0)

    if "--check" in argv:
        raise SystemExit(_run_check(argv))

    # Only what the splash needs comes before it: Qt, the settings and the
    # theme. numpy, scipy, python-control and the window load behind it.
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    _claim_taskbar_identity()
    app = QApplication.instance() or QApplication(sys.argv)

    # Enable high-DPI
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app.setApplicationName("Evans")
    # No setApplicationDisplayName: Qt appends it to every native caption,
    # which made the window read "Evans — … - Evans — …".

    # Identity first: QSettings (the saved theme among them) is keyed on it.
    app.setOrganizationName("Evans")
    # This program was called FauxMatlab until 0.9; bring its settings along
    # once, so the rename does not reset the theme, layout and history.
    from evans.ui import persist

    persist.migrate_legacy_settings()

    # Holding Point: bundled typefaces, the saved Day/Night choice, then the
    # palette and stylesheet. The app font is set in there too — no more
    # hard-coded "Segoe UI".
    from evans.ui import theme, theme_qt

    theme.load_fonts()
    theme.set_mode(theme.saved_mode(), persist=False)
    theme_qt.apply(app)

    from evans.ui import iconset

    app.setWindowIcon(iconset.app_icon())
    finder_files = _finder_files(app)

    from evans.ui.splash import Splash

    splash = Splash(steps=3)
    splash.show()
    splash.step("Loading numerics")

    import pyqtgraph as pg

    pg.setConfigOptions(antialias=True, useOpenGL=False)

    from evans.core.architecture import CourseArchitecture
    from evans.core.tf_utils import second_order, unity

    splash.step("Loading the workbench")
    from evans.ui.mainwindow import MainWindow

    splash.step("Opening the window")
    # Default architecture: textbook 2nd-order plant, unity feedback
    arch = CourseArchitecture(
        G  = second_order(K=1.0, zeta=0.5, wn=2.0),
        K2 = unity(),
        K1 = unity(),
        H  = unity(),
    )

    win = MainWindow(arch)
    win.show()
    win.raise_()
    splash.finish(win)

    # `Evans.exe model.fmdl`: the file association, or a drop on the exe.
    for path in _file_arguments(app.arguments()[1:]):
        win.open_recent(path)
    # The same on a Mac, where Finder sends an event instead.
    finder_files.set_target(win.open_recent)

    # Once a day, a few seconds from now: is there a newer release?
    win.updater.start()

    sys.exit(app.exec())


# Below main() on purpose: nothing above it may import Qt, so that
# --check works on a machine with no display.
def _finder_files(app):
    """
    Files macOS asks Evans to open: a double-click in Finder, a drop on the
    Dock icon. They come as ``FileOpen`` events, never on the command line,
    and the first can arrive before the window exists, so they wait in
    ``pending`` until :attr:`open` is set.
    """
    from PySide6.QtCore import QEvent, QObject

    class FinderFiles(QObject):
        def __init__(self) -> None:
            super().__init__(app)
            self.pending: list[Path] = []
            self.open = None

        def set_target(self, open_file) -> None:
            self.open = open_file
            for path in self.pending:
                open_file(path)
            self.pending.clear()

        def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt API)
            if event.type() != QEvent.FileOpen or not event.file():
                return False
            path = Path(event.file())
            if self.open is None:
                self.pending.append(path)
            else:
                self.open(path)
            return True

    files = FinderFiles()
    app.installEventFilter(files)
    return files


if __name__ == "__main__":
    main()
