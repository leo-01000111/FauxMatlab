"""
The command window, the workspace browser, the script editor, the figures.

These are plain widgets, not docks. They used to be two docks
hidden by default, which meant the console — a first-class way to drive this
application — was a panel you had to know existed. They are now the contents
of the **Console workspace**, reachable with Ctrl+3.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...console.figures import FigureSpec, set_figure_sink
from ...console.interpreter import Interpreter
from ..design import EmptyState
from .console_widget import ConsoleWidget
from .figure_view import FigureView
from .workspace_widget import WorkspaceWidget

#: Beyond this many open figures the oldest is closed, the way MATLAB reuses
#: figure numbers — an unbounded pile of tabs is not a feature.
MAX_FIGURES = 12


class FigureArea(QWidget):
    """Where ``step(G)`` and ``bode(L)`` draw."""

    #: A figure arrived — the workspace uses it to reveal itself.
    figure_added = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        layout.addWidget(self._tabs)
        self._count = 0
        self._placeholder = EmptyState(
            "No figures yet",
            "Plot commands draw here — try step(G) or bode(L) at the prompt.")
        layout.addWidget(self._placeholder)
        self._sync_placeholder()

    def show_figure(self, spec: FigureSpec) -> FigureView:
        """Render a figure spec as a new tab, and bring it to the front."""
        view = FigureView(spec)
        self._count += 1
        title = spec.title or spec.kind
        index = self._tabs.addTab(view, f"{self._count}: {title}")
        self._tabs.setCurrentIndex(index)
        while self._tabs.count() > MAX_FIGURES:
            self._close_tab(0)
        self._sync_placeholder()
        self.figure_added.emit()
        return view

    def _close_tab(self, index: int) -> None:
        widget = self._tabs.widget(index)
        self._tabs.removeTab(index)
        if widget is not None:
            widget.deleteLater()
        self._sync_placeholder()

    def close_all(self) -> None:
        while self._tabs.count():
            self._close_tab(0)

    def _sync_placeholder(self) -> None:
        """An empty tab strip is indistinguishable from a broken panel."""
        empty = self._tabs.count() == 0
        self._tabs.setVisible(not empty)
        self._placeholder.setVisible(empty)

    @property
    def figure_count(self) -> int:
        return self._tabs.count()


class ScriptEditor(QWidget):
    """
    A plain editor that runs its contents against the console's namespace.

    Deliberately minimal — no syntax highlighting, no project model. Its job
    is to let a sequence of commands be kept, edited and re-run without
    retyping, which is what a script is for.
    """

    run_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        row = QHBoxLayout()
        run = QPushButton("▶ Run (F5)")
        run.setShortcut("F5")
        run.clicked.connect(self._run)
        row.addWidget(run)
        for label, slot in (("Open…", self._open), ("Save…", self._save)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch()
        self._path_label = QLabel("untitled")
        self._path_label.setStyleSheet("color: palette(mid);")
        row.addWidget(self._path_label)
        layout.addLayout(row)

        self._editor = QPlainTextEdit()
        self._editor.setFont(QFont("Consolas", 10))
        self._editor.setPlaceholderText(
            "# Runs against the same workspace as the console.\n"
            "G = tf([1], [1, 2, 1])\n"
            "T = feedback(pid(Kp=2, Ki=1) * G, 1)\n"
            "step(T)\n"
            "stepinfo(T)")
        layout.addWidget(self._editor, stretch=1)

        self._path: Path | None = None

    def _run(self) -> None:
        self.run_requested.emit(self._editor.toPlainText())

    def _open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open script", "", "Python scripts (*.py);;All files (*)")
        if not path:
            return
        self._path = Path(path)
        self._editor.setPlainText(self._path.read_text(encoding="utf-8"))
        self._path_label.setText(self._path.name)

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save script", str(self._path or "script.py"),
            "Python scripts (*.py)")
        if not path:
            return
        self._path = Path(path)
        self._path.write_text(self._editor.toPlainText(), encoding="utf-8")
        self._path_label.setText(self._path.name)

    def set_text(self, text: str) -> None:
        self._editor.setPlainText(text)

    def text(self) -> str:
        return self._editor.toPlainText()


class ConsolePanel(QWidget):
    """Command window on the left, workspace on the right, script behind."""

    #: A system in the workspace was double-clicked.
    open_system = Signal(str, object)
    #: A Simulink model in the workspace was double-clicked.
    open_model = Signal(str, object)

    def __init__(self, figures: FigureArea, extra: dict | None = None,
                 parent=None) -> None:
        super().__init__(parent)

        self.interpreter = Interpreter(extra)
        self.figures = figures

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        split = QSplitter(Qt.Horizontal)
        self.console = ConsoleWidget(self.interpreter)
        split.addWidget(self.console)
        self.workspace = WorkspaceWidget(self.interpreter)
        split.addWidget(self.workspace)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        self._tabs.addTab(split, "Console")

        self.editor = ScriptEditor()
        self.editor.run_requested.connect(self._run_script)
        self._tabs.addTab(self.editor, "Script")

        layout.addWidget(self._tabs)

        self.console.executed.connect(self.workspace.refresh)
        self.workspace.open_system.connect(self.open_system)
        self.workspace.open_model.connect(self.open_model)

        # Plot commands draw into the figure dock from here on.
        set_figure_sink(self.figures.show_figure)

    def _run_script(self, source: str) -> None:
        self._tabs.setCurrentIndex(0)
        self.console.run_script(source)
        self.workspace.refresh()

    # ── outside access ──────────────────────────────────────────

    def push(self, **variables) -> None:
        """Put values into the workspace — how the app shares its state."""
        self.interpreter.namespace.update(variables)
        self.workspace.refresh()

    def execute(self, source: str):
        """Run a command as if it had been typed."""
        self._tabs.setCurrentIndex(0)
        result = self.console.execute(source)
        self.workspace.refresh()
        return result

    def focus(self) -> None:
        self._tabs.setCurrentIndex(0)
        self.console.focus_input()
