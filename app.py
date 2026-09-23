"""
FakeMatlab — Classical Control Workbench
Entry point: python app.py
"""

import sys
import os

# Force pyqtgraph to use PySide6 BEFORE it (or anything else) loads Qt DLLs.
# With PyQt5/PyQt6/PySide6 all installed, pyqtgraph defaults to PyQt5 which
# conflicts with PySide6 at the DLL level.
os.environ["PYQTGRAPH_QT_LIB"] = "PySide6"
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

import pyqtgraph as pg
pg.setConfigOptions(antialias=True, useOpenGL=False)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore    import Qt
from PySide6.QtGui     import QFont

from fakematlab.ui.mainwindow   import MainWindow
from fakematlab.core.architecture import CourseArchitecture
from fakematlab.core.tf_utils     import first_order, second_order, unity


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)

    # Enable high-DPI
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app.setApplicationName("FakeMatlab")
    app.setApplicationDisplayName("FakeMatlab — Classical Control")

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
