"""
FauxMatlab — a classical and modern control workbench.

    python app.py            open the window
    python app.py --check    run the headless self-test and exit
    python app.py --version  print the version and exit

``--check`` is the one a packaged build needs: it ships without the test
suite, so this is how you ask an installed copy whether it works. Its exit
code is the number of failed checks.
"""

import os
import sys

# Force pyqtgraph to use PySide6 BEFORE it (or anything else) loads Qt DLLs.
# With PyQt5/PyQt6/PySide6 all installed, pyqtgraph defaults to PyQt5 which
# conflicts with PySide6 at the DLL level.
os.environ["PYQTGRAPH_QT_LIB"] = "PySide6"
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

VERSION = "0.7.0"


def _run_check(argv: list[str]) -> int:
    """
    The self-test. Imported late and deliberately.

    ``--check`` has to work on a machine with no display, so nothing above
    this line may have opened a Qt GUI connection. The self-test pins the
    offscreen platform itself before it touches Qt.
    """
    from fakematlab.selftest import run

    report = run(verbose="--quiet" not in argv,
                 include_ui="--no-ui" not in argv)
    return len(report.failures)


def main() -> None:
    argv = sys.argv[1:]

    if "--version" in argv:
        print(f"FauxMatlab {VERSION}")
        raise SystemExit(0)

    if "--check" in argv:
        raise SystemExit(_run_check(argv))

    import pyqtgraph as pg

    pg.setConfigOptions(antialias=True, useOpenGL=False)

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from fakematlab.core.architecture import CourseArchitecture
    from fakematlab.core.tf_utils import second_order, unity
    from fakematlab.ui.mainwindow import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)

    # Enable high-DPI
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app.setApplicationName("FauxMatlab")
    app.setApplicationDisplayName("FauxMatlab — Classical & Modern Control")

    # Font
    font = app.font()
    font.setFamily("Segoe UI")
    font.setPointSize(10)
    app.setFont(font)

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

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
