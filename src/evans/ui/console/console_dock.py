"""
The command window, the workspace browser, the script editor, the figures.

These are plain widgets, not docks. They used to be two docks
hidden by default, which meant the console — a first-class way to drive this
application — was a panel you had to know existed. They are now the contents
of the **Console workspace**, reachable with Ctrl+3.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QEventLoop, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...console import tracer as dbg
from ...console.figures import FigureSpec, set_figure_sink
from ...console.interpreter import Interpreter, Result
from ...console.matlab import looks_like_matlab
from .. import iconset
from ..code import (
    CodeEditor,
    MatlabHighlighter,
    code_request,
    section_source,
    warm_up,
)
from ..design import TIGHT, EmptyState
from .console_widget import ConsoleWidget
from .figure_view import FigureView, export_figure
from .history_widget import HistoryWidget
from .live_editor import LiveScriptEditor, set_code_highlighter
from .workspace_widget import WorkspaceWidget

#: Beyond this many open figures the oldest is closed, the way MATLAB reuses
#: figure numbers — an unbounded pile of tabs is not a feature.
MAX_FIGURES = 12

#: What a figure saved without a name is called: ``figure_1.png``, and so on.
PLACEHOLDER_STEM = "figure"


def placeholder_names(folder: Path, count: int,
                      stem: str = PLACEHOLDER_STEM) -> list[Path]:
    """
    ``count`` free file names in ``folder``: figure_1.png, figure_2.png, …

    Numbers already taken on disk are skipped rather than overwritten, so
    saving a second run's figures beside the first run's keeps both.
    """
    names: list[Path] = []
    n = 1
    while len(names) < count:
        path = folder / f"{stem}_{n}.png"
        if not path.exists():
            names.append(path)
        n += 1
    return names


class FigureWindow(QWidget):
    """
    A figure undocked into a window of its own.

    The figure is the same live widget, reparented — not a picture of it — so
    it still pans, zooms and reads out under the mouse, and still follows the
    theme. Closing the window docks the figure back rather than deleting it:
    undocking is a change of place, and losing a plot to a window's close box
    would be a surprise. Closing its tab is how a figure is got rid of.
    """

    #: The figure wants to go back into the figure area.
    dock_requested = Signal(object)            # FigureView
    #: The figure wants saving, through the figure area's own dialog.
    save_requested = Signal(object)            # FigureView

    def __init__(self, view: FigureView, title: str, parent=None) -> None:
        super().__init__(parent, Qt.Window)
        self.setWindowTitle(f"{title} — Evans")
        self.view: FigureView | None = view

        layout = QVBoxLayout(self)
        layout.setContentsMargins(TIGHT, TIGHT, TIGHT, TIGHT)
        layout.setSpacing(TIGHT)
        row = QHBoxLayout()
        row.addStretch()
        save = QToolButton()
        save.setText("Save…")
        save.setToolTip("Save this figure as PNG, SVG or CSV data")
        save.clicked.connect(lambda: self.save_requested.emit(self.view))
        row.addWidget(save)
        dock = QToolButton()
        dock.setText("Dock")
        dock.setToolTip("Put this figure back in the Console's figure area")
        dock.clicked.connect(self.close)
        row.addWidget(dock)
        layout.addLayout(row)
        layout.addWidget(view, stretch=1)
        view.show()
        self.resize(760, 520)

    def release(self) -> FigureView | None:
        """Let go of the figure, so closing the window no longer re-docks it."""
        view, self.view = self.view, None
        return view

    def closeEvent(self, event) -> None:          # noqa: N802 (Qt API)
        if self.view is not None:
            self.dock_requested.emit(self.view)
        super().closeEvent(event)


class FigureArea(QWidget):
    """
    Where ``step(G)`` and ``bode(L)`` draw.

    One tab strip, or two side by side (*Split*); and any figure can leave for
    a window of its own (*Undock*) and come back. The small controls above the
    tabs act on the *current* figure: the selected tab on whichever side was
    used last.
    """

    #: A figure arrived — the workspace uses it to reveal itself.
    figure_added = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = self._build_header()
        layout.addWidget(self._header)

        # Two tab strips in a splitter. The right one always exists and is
        # only shown in split view, so a figure crosses over by reparenting —
        # its zoom and cursor intact — rather than by being drawn again.
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._tabs = self._make_pane()
        self._side = self._make_pane()
        self._splitter.addWidget(self._tabs)
        self._splitter.addWidget(self._side)
        self._side.hide()
        layout.addWidget(self._splitter, stretch=1)
        self._active = self._tabs

        self._views: list[FigureView] = []
        self._windows: dict[FigureView, FigureWindow] = {}
        self._script_running = False
        self._placeholder = EmptyState(
            "No figures yet",
            "Plot commands draw here — try step(G) or bode(L) at the prompt.")
        layout.addWidget(self._placeholder)
        self._sync_placeholder()

    def _make_pane(self) -> QTabWidget:
        pane = QTabWidget()
        pane.setTabsClosable(True)
        pane.setDocumentMode(True)
        pane.tabCloseRequested.connect(
            lambda index, p=pane: self._close_tab(p, index))
        pane.tabBarClicked.connect(lambda _index, p=pane: self._activate(p))
        pane.currentChanged.connect(lambda _index, p=pane: self._activate(p))
        return pane

    def _build_header(self) -> QWidget:
        """
        The figure controls, small and to the right above the tabs.

        Tool buttons rather than push buttons: the stylesheet draws them
        borderless until hovered, so they read as part of the tab strip's
        edge and not as a second toolbar competing with the console's.
        """
        header = QWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(TIGHT, 0, TIGHT, 0)
        row.setSpacing(TIGHT)
        row.addStretch()

        def tool(text: str, tip: str, slot) -> QToolButton:
            button = QToolButton()
            button.setText(text)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            row.addWidget(button)
            return button

        self._split_button = tool(
            "Split", "Show two figures side by side",
            lambda checked: self.set_split(checked))
        iconset.bind(self._split_button, "grid-1x2")
        self._split_button.setCheckable(True)
        self._move_button = tool(
            "Move ↔", "Move the current figure to the other side — "
            "or, when it is alone there, swap it with the one opposite",
            lambda: self.move_to_other_side())
        self._undock_button = tool(
            "Undock", "Open the current figure in a window of its own",
            lambda: self.undock())
        iconset.bind(self._undock_button, "restore")
        self._save_button = tool(
            "Save…", "Save the current figure as PNG, SVG or CSV data",
            lambda: self.save_current())
        iconset.bind(self._save_button, "save")
        for button in (self._split_button, self._move_button,
                       self._undock_button, self._save_button):
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        return header

    # ── adding and removing ─────────────────────────────────────

    def show_figure(self, spec: FigureSpec) -> FigureView:
        """Render a figure spec as a new tab, and bring it to the front."""
        view = FigureView(spec)
        # The lowest number no open figure has, as MATLAB numbers them: once
        # a run's figures are cleared away, the next run starts at 1 again.
        taken = {v.number for v in self._views}
        view.number = next(n for n in range(1, len(taken) + 2)
                           if n not in taken)
        view.from_script = self._script_running
        self._views.append(view)
        self._place(view, self._tabs)
        while len(self._views) > MAX_FIGURES:
            self.close_figure(self._views[0])
        self._sync_placeholder()
        self.figure_added.emit()
        return view

    @staticmethod
    def _label(view: FigureView) -> str:
        return f"{view.number}: {view.spec.title or view.spec.kind}"

    def _place(self, view: FigureView, pane: QTabWidget) -> None:
        """
        Add a figure's tab, kept in the order the figures were drawn — so
        however often they cross a split and come back, older is left.
        """
        order = self._views.index(view) if view in self._views else len(self._views)
        index = next((i for i in range(pane.count())
                      if self._views.index(pane.widget(i)) > order),
                     pane.count())
        index = pane.insertTab(index, view, self._label(view))
        pane.setCurrentIndex(index)
        self._active = pane

    def _close_tab(self, pane: QTabWidget, index: int) -> None:
        widget = pane.widget(index)
        if widget is not None:
            self.close_figure(widget)

    def close_figure(self, view: FigureView) -> None:
        """Close one figure, wherever it is: either side, or its own window."""
        window = self._windows.pop(view, None)
        if window is not None:
            window.release()
            window.close()
            window.deleteLater()
        for pane in (self._tabs, self._side):
            index = pane.indexOf(view)
            if index >= 0:
                pane.removeTab(index)
        if view in self._views:
            self._views.remove(view)
        view.deleteLater()
        self._sync_placeholder()

    def close_all(self) -> None:
        for view in list(self._views):
            self.close_figure(view)

    def _sync_placeholder(self) -> None:
        """An empty tab strip is indistinguishable from a broken panel."""
        # A split with one side emptied — its figures closed, undocked or
        # moved across — folds back to a single strip.
        if self.split and not (self._tabs.count() and self._side.count()):
            self.set_split(False)
        docked = self._tabs.count() + self._side.count()
        self._splitter.setVisible(docked > 0)
        self._header.setVisible(docked > 0)
        self._placeholder.setVisible(docked == 0)
        self._sync_controls()

    def _sync_controls(self) -> None:
        current = self.current_figure() is not None
        self._undock_button.setEnabled(current)
        self._save_button.setEnabled(current)
        self._split_button.setEnabled(self.split or self._tabs.count() >= 2)
        self._move_button.setVisible(self.split)

    @property
    def figure_count(self) -> int:
        """Every open figure: docked on either side or in a window."""
        return len(self._views)

    @property
    def figures(self) -> list[FigureView]:
        """The open figures, oldest first."""
        return list(self._views)

    # ── the current figure ──────────────────────────────────────

    def _activate(self, pane: QTabWidget) -> None:
        if pane.count():
            self._active = pane
        self._sync_controls()

    def current_figure(self) -> FigureView | None:
        """The selected tab on the side used last, else on the other side."""
        for pane in (self._active, self._tabs, self._side):
            if pane.count() and (pane is self._tabs or self.split):
                return pane.currentWidget()
        return None

    # ── split view ──────────────────────────────────────────────

    @property
    def split(self) -> bool:
        return not self._side.isHidden()

    def set_split(self, on: bool) -> None:
        """
        Two figures side by side, or one strip again.

        Splitting pairs the current figure with its neighbour — the next
        one drawn, or for the newest the one before it — and moves the newer
        of the two to the right, so the older is on the left whichever of
        them was selected. New figures still arrive on the left.
        Unsplitting brings the right side's figures back, in drawing order.
        """
        if on and not self.split:
            if self._tabs.count() < 2:
                self._split_button.setChecked(False)
                return
            index = self._tabs.currentIndex()
            newer = index + 1 if index + 1 < self._tabs.count() else index
            self._side.show()
            self.move_to_other_side(self._tabs.widget(newer))
            half = max(self._splitter.width() // 2, 1)
            self._splitter.setSizes([half, half])
        elif not on and self.split:
            while self._side.count():
                view = self._side.widget(0)
                self._side.removeTab(0)
                self._place(view, self._tabs)
            self._side.hide()
            self._active = self._tabs
        self._split_button.setChecked(self.split)
        self._sync_controls()

    def move_to_other_side(self, view: FigureView | None = None) -> None:
        """
        Move a docked figure across the split.

        A figure alone on its side swaps with the one shown opposite instead:
        moving it outright would empty that side and fold the split away,
        which is what pressing Split again already does.
        """
        view = view or self.current_figure()
        if view is None or not self.split:
            return
        source = self._tabs if self._tabs.indexOf(view) >= 0 else self._side
        target = self._side if source is self._tabs else self._tabs
        index = source.indexOf(view)
        if index < 0:
            return
        partner = target.currentWidget() if source.count() == 1 else None
        source.removeTab(index)
        if partner is not None:
            target.removeTab(target.indexOf(partner))
            self._place(partner, source)
        self._place(view, target)
        self._sync_placeholder()

    # ── undocking ───────────────────────────────────────────────

    def undock(self, view: FigureView | None = None) -> FigureWindow | None:
        """Move a docked figure into a window of its own."""
        view = view or self.current_figure()
        if view is None or view in self._windows:
            return None
        for pane in (self._tabs, self._side):
            index = pane.indexOf(view)
            if index >= 0:
                pane.removeTab(index)
        # Parented to the area, so it closes with the application and is
        # never orphaned; Qt.Window makes it a top-level window regardless.
        window = FigureWindow(view, self._label(view), self)
        window.dock_requested.connect(self.dock)
        window.save_requested.connect(self.save_current)
        self._windows[view] = window
        window.show()
        self._sync_placeholder()
        return window

    def dock(self, view: FigureView) -> None:
        """Bring an undocked figure back as a tab, on the side used last."""
        window = self._windows.pop(view, None)
        if window is None:
            return
        window.release()
        window.hide()
        window.deleteLater()
        self._place(view, self._active if self.split else self._tabs)
        self._sync_placeholder()

    def window_for(self, view: FigureView) -> FigureWindow | None:
        """The window an undocked figure is in, or None if it is docked."""
        return self._windows.get(view)

    # ── saving ──────────────────────────────────────────────────

    @staticmethod
    def save_figure(view: FigureView, path: str | Path) -> bool:
        """Write a figure, as PNG, SVG or CSV by the path's extension."""
        try:
            export_figure(view, path)
        except (OSError, ValueError):
            return False
        return True

    def save_figures(self, views: Iterable[FigureView],
                     folder: str | Path) -> list[Path]:
        """Save figures under placeholder names; returns the files written."""
        views = list(views)
        names = placeholder_names(Path(folder), len(views))
        return [path for view, path in zip(views, names)
                if self.save_figure(view, path)]

    def save_current(self, view: FigureView | None = None) -> None:
        """Save a figure (the current one by default) where the user says."""
        view = view or self.current_figure()
        if view is not None:
            view.save_dialog()

    # ── script runs ─────────────────────────────────────────────

    def script_figures(self, *, unsaved: bool = False) -> list[FigureView]:
        """The figures the last script run drew — optionally only unsaved."""
        return [v for v in self._views
                if v.from_script and not (unsaved and v.saved)]

    def begin_script_run(self) -> None:
        """
        Clear the previous run's figures away, and tag the ones that follow.

        A script's figures are its output: running it again should replace
        them, as it replaces its printed output, not pile a second copy beside
        the first. Figures typed at the prompt belong to no run and stay.
        """
        for view in self.script_figures():
            self.close_figure(view)
        self._script_running = True

    def end_script_run(self) -> None:
        self._script_running = False


class ScriptEditor(QWidget):
    """
    An editor that runs its contents against the console's namespace.

    Its job is to let a sequence of commands be kept, edited and re-run
    without retyping, which is what a script is for — with what that needs
    in practice: highlighting, line numbers, ``%%`` sections run on their
    own (Ctrl+Enter), Tab completion, and a debugger (click the gutter for a
    breakpoint; F5 continues, F10 steps, F11 steps in, Shift+F5 stops).
    Still no project model.

    It takes MATLAB or Python. *Auto* decides from the text, and a script
    that reads as both (or as nothing yet) is MATLAB, the app's language;
    the selector is there to say otherwise.
    """

    #: (source, language) — language is "matlab" or "python".
    run_requested = Signal(str, str)
    #: A file was opened or saved — the recent-files list listens.
    file_used = Signal(object)                 # Path
    #: (source padded to its lines, language, move on afterwards).
    section_requested = Signal(str, str, bool)
    #: Stop, Continue / Step / Step in: "stop", "continue", "step", "step_in".
    debug_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        row = QHBoxLayout()
        run = QPushButton("Run (F5)")
        iconset.bind(run, "run")
        run.setToolTip(
            "Run the whole script (F5), or continue when paused. The console "
            "and the last run's figures are cleared first; unsaved figures "
            "are offered for saving.")
        run.clicked.connect(self._run)
        row.addWidget(run)
        self._run_button = run
        section = QPushButton("Run section")
        section.setToolTip(
            "Run the %% section the cursor is in (Ctrl+Enter); "
            "Ctrl+Shift+Enter runs it and moves to the next. Appends to the "
            "console, like typed commands.")
        section.clicked.connect(lambda: self.run_section(False))
        row.addWidget(section)
        self._section_button = section

        def debug(label: str, action: str, tip: str) -> QToolButton:
            button = QToolButton()
            button.setText(label)
            button.setToolTip(tip)
            button.setEnabled(False)
            button.clicked.connect(
                lambda: self.debug_requested.emit(action))
            row.addWidget(button)
            return button

        self._stop_button = debug("Stop", "stop",
                                  "Stop the run (Shift+F5)")
        iconset.bind(self._stop_button, "stop", "hold_ink")
        self._stop_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._step_button = debug("Step", "step",
                                  "Run the paused line (F10)")
        self._step_in_button = debug(
            "Step in", "step_in",
            "Run the paused line, stopping inside a function it calls (F11)")
        # What a run said, beside the controls that started it. Ignored
        # width: a long message must not widen the window.
        self._status = QLabel("")
        self._status.setStyleSheet("color: palette(mid);")
        self._status.setSizePolicy(QSizePolicy.Ignored,
                                   QSizePolicy.Preferred)
        row.addWidget(self._status, stretch=1)
        layout.addLayout(row)

        # A second row for the file and the language, so the run and debug
        # controls do not set the window's minimum width.
        row = QHBoxLayout()
        for label, icon, slot in (("Open…", "open", self._open),
                                  ("Save…", "save", self._save)):
            button = QPushButton(label)
            iconset.bind(button, icon)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addSpacing(12)
        row.addWidget(QLabel("Language"))
        self._language = QComboBox()
        for label, key in (("Auto", "auto"), ("MATLAB", "matlab"),
                           ("Python", "python")):
            self._language.addItem(label, key)
        self._language.currentIndexChanged.connect(self._update_detected)
        row.addWidget(self._language)
        self._detected = QLabel("")
        self._detected.setStyleSheet("color: palette(mid);")
        row.addWidget(self._detected)
        row.addStretch()
        self._path_label = QLabel("untitled")
        self._path_label.setStyleSheet("color: palette(mid);")
        row.addWidget(self._path_label)
        layout.addLayout(row)

        self._editor = CodeEditor()
        self._editor.run_section_requested.connect(self.run_section)
        self._editor.setPlaceholderText(
            "% MATLAB (or Python) — paste a .m script and press Run.\n"
            "s = tf('s');\n"
            "G = 1/((s+1)*(0.5*s+1));\n"
            "T = feedback(pid(2, 1)*G, 1);\n"
            "step(G, T); legend('open loop', 'closed loop')\n"
            "stepinfo(T)")
        self._editor.textChanged.connect(self._update_detected)
        layout.addWidget(self._editor, stretch=1)

        self._path: Path | None = None

    @property
    def code(self) -> CodeEditor:
        """The text area: breakpoints, highlights, sections."""
        return self._editor

    def set_completion_source(self, source) -> None:
        self._editor.set_completion_source(source)

    def set_completion(self, request) -> None:
        """The completion popup, offering ``request(text before cursor)``."""
        self._editor.set_completion(request)

    def completion_language(self) -> str:
        """
        :meth:`language`, for completing while typing: *Auto* reads the
        whole text, so its answer is kept until the line count changes.
        """
        if self._language.currentData() != "auto":
            return self._language.currentData()
        lines = self._editor.blockCount()
        cached = getattr(self, "_completion_language", None)
        if cached is None or cached[0] != lines:
            self._completion_language = (lines, self.language())
        return self._completion_language[1]

    def language(self) -> str:
        """The language the next run will use: 'matlab' or 'python'."""
        chosen = self._language.currentData()
        if chosen != "auto":
            return chosen
        text = self._editor.toPlainText()
        return "matlab" if not text.strip() or looks_like_matlab(text) \
            else "python"

    def set_language(self, key: str) -> None:
        index = self._language.findData(key)
        if index >= 0:
            self._language.setCurrentIndex(index)

    def _update_detected(self, *_args) -> None:
        auto = self._language.currentData() == "auto"
        text = self._editor.toPlainText().strip()
        language = self.language()
        name = "MATLAB" if language == "matlab" else "Python"
        self._detected.setText(f"(reads as {name})" if auto and text else "")
        self._editor.set_language(language)

    def _run(self) -> None:
        self.run_requested.emit(self._editor.toPlainText(), self.language())

    def run_section(self, advance: bool = False) -> None:
        """Ask for the section under the cursor to run (then move on)."""
        text = self._editor.toPlainText()
        section = self._editor.current_section()
        self.section_requested.emit(section_source(text, section),
                                    self.language(), advance)

    def next_section(self) -> None:
        """Put the cursor at the start of the section after the current."""
        sections = self._editor.sections()
        current = self._editor.current_section()
        later = [s for s in sections if s.start > current.start]
        if later:
            self._editor.goto_line(later[0].start)

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def set_run_state(self, running: bool, paused: bool) -> None:
        """Which buttons apply: Run is Continue while paused."""
        self._run_button.setText("Continue (F5)" if paused
                                 else "Run (F5)")
        self._run_button.setEnabled(paused or not running)
        self._section_button.setEnabled(not running)
        self._stop_button.setEnabled(running)
        self._step_button.setEnabled(paused)
        self._step_in_button.setEnabled(paused)

    def _open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open script", "",
            "Scripts (*.m *.py);;MATLAB scripts (*.m);;Python scripts (*.py);;"
            "All files (*)")
        if path:
            self.load_file(path)

    def load_file(self, path: str | Path) -> None:
        """Open a script into the editor, choosing its language by suffix."""
        self._path = Path(path)
        self._editor.setPlainText(self._path.read_text(encoding="utf-8"))
        self._editor.set_breakpoints(())
        self._path_label.setText(self._path.name)
        self.set_language({".m": "matlab", ".py": "python"}.get(
            self._path.suffix.lower(), "auto"))
        self.file_used.emit(self._path)

    def _save(self) -> None:
        default = self._path or Path(
            "script.m" if self.language() == "matlab" else "script.py")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save script", str(default),
            "MATLAB scripts (*.m);;Python scripts (*.py);;All files (*)")
        if not path:
            return
        self._path = Path(path)
        self._path.write_text(self._editor.toPlainText(), encoding="utf-8")
        self._path_label.setText(self._path.name)
        self.file_used.emit(self._path)

    @property
    def path(self) -> Path | None:
        """The file the script was opened from or saved to, if any."""
        return self._path

    def set_text(self, text: str) -> None:
        self._editor.setPlainText(text)

    def text(self) -> str:
        return self._editor.toPlainText()


class ConsolePanel(QWidget):
    """
    Command window on the left; workspace and history on the right, as tabs;
    the script behind.
    """

    #: A system in the workspace was double-clicked.
    open_system = Signal(str, object)
    #: A Simulink model in the workspace was double-clicked.
    open_model = Signal(str, object)
    #: Whether the figure area below is worth showing: not on the Live tab,
    #: where each cell's figures are drawn inline under it.
    figure_area_wanted = Signal(bool)

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
        # The history shares the workspace's side as a second tab: both are
        # lookups beside the prompt, and a third column would squeeze it.
        self._side = QTabWidget()
        self._side.setDocumentMode(True)
        self.workspace = WorkspaceWidget(self.interpreter)
        self._side.addTab(self.workspace, "Workspace")
        self.history = HistoryWidget()
        self._side.addTab(self.history, "History")
        split.addWidget(self._side)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        self._tabs.addTab(split, "Console")

        self.editor = ScriptEditor()
        self.editor.run_requested.connect(self._run_script)
        self.editor.section_requested.connect(self._run_section)
        self.editor.debug_requested.connect(self._debug)
        self.editor.set_completion(
            lambda before: code_request(
                before, self.editor.completion_language(), self.interpreter,
                self._folder()))
        warm_up()          # the fixed completion lists, in the background
        self.editor.code.breakpoints_changed.connect(self._set_breakpoints)
        self._tabs.addTab(self.editor, "Script")

        # Live scripts: cells of code and formatted text, run in this same
        # workspace. `live.folder` is its current folder, as `editor.path`
        # is the plain script's file.
        self.live = LiveScriptEditor(self.interpreter)
        set_code_highlighter(MatlabHighlighter)  # its cells read as MATLAB
        self.live.ran.connect(self.workspace.refresh)
        self.live.figure_requested.connect(self._open_live_figure)
        self._tabs.addTab(self.live, "Live")
        self._tabs.currentChanged.connect(
            lambda _index: self.figure_area_wanted.emit(not self.live_active))

        layout.addWidget(self._tabs)

        self.console.executed.connect(self.workspace.refresh)
        self.console.executed.connect(self._record)
        self.history.recall.connect(self.recall)
        self.history.rerun.connect(self.execute)
        self._running_script = False
        # Last session's commands are on ↑ as well as in the panel.
        self.interpreter.history[:0] = self.history.commands()
        self.console._history_index = len(self.interpreter.history)
        self.console.stop_requested.connect(self.stop)
        self.console.running_changed.connect(self._sync_run_state)
        self.workspace.open_system.connect(self.open_system)
        self.workspace.open_model.connect(self.open_model)

        # Plot commands draw into the figure dock from here on.
        set_figure_sink(self.figures.show_figure)
        # `close all` in a MATLAB script closes the figures drawn so far.
        self.interpreter.close_figures = self.figures.close_all

        # Stopping and debugging: user code runs on this (the GUI) thread,
        # and the tracer gives the event loop a turn while it does — see
        # evans.console.tracer for why not a worker thread.
        tracer = self.interpreter.tracer
        tracer.poll = QApplication.processEvents
        tracer.on_pause = self._on_pause
        self._pause_loop: QEventLoop | None = None
        self._pause_action = dbg.CONTINUE
        app = QApplication.instance()
        if app is not None:
            # Quitting mid-run must unwind the script, or it would keep the
            # process alive after the last window closed.
            app.lastWindowClosed.connect(self.stop)
        for keys, slot in (("F5", self._run_or_continue),
                           ("Shift+F5", self.stop),
                           ("F10", lambda: self._debug(dbg.STEP)),
                           ("F11", lambda: self._debug(dbg.STEP_IN))):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)

    @property
    def live_active(self) -> bool:
        """Whether the Live tab is the one showing."""
        return self._tabs.currentWidget() is self.live

    def _open_live_figure(self, spec: FigureSpec) -> None:
        """
        A live script's figure, opened larger than it is inline.

        The figure area is hidden while the Live tab shows, so the figure
        goes straight to a window of its own; its Dock button still puts it
        in the figure area, for when the Console tab is back.
        """
        view = self.figures.show_figure(spec)
        if self.live_active:
            self.figures.undock(view)

    def _folder(self) -> Path:
        """The current folder: the script's, or where the app started."""
        return self.editor.path.parent if self.editor.path else Path.cwd()

    @property
    def running(self) -> bool:
        return self.interpreter.tracer.running

    def _run_script(self, source: str, language: str = "auto") -> bool:
        """
        Run the whole script from a clean slate.

        The transcript and the previous run's figures are cleared first, so
        running a script twice shows one run's output, not two. Before the
        figures go, any that were never saved are offered for saving. Lines
        typed at the prompt are not affected: they still append.

        Returns False if the user cancelled, in which case nothing ran and
        nothing was cleared — or if something is already running (Run while
        paused continues it instead).
        """
        if self.running:
            if self.interpreter.tracer.paused is not None:
                self._debug(dbg.CONTINUE)
            return False
        saved = self._offer_to_save_figures()
        if saved is None:
            return False
        self._tabs.setCurrentIndex(0)
        self.console.clear_transcript()
        if saved:
            self.console.note(
                f"Saved {len(saved)} figure{'s' if len(saved) != 1 else ''} "
                f"from the last run to {saved[0].parent}: "
                + ", ".join(p.name for p in saved))
        self.console.folder = self._folder()
        self.editor.code.set_error_line(None)
        self.figures.begin_script_run()
        self._running_script = True
        path = self.editor.path
        self.interpreter.script_folder = str(path.parent) if path else None
        try:
            results = self.console.run_script(source, language,
                                              debuggable=True)
        finally:
            self._running_script = False
            self.figures.end_script_run()
        self._show_outcome(results)
        self.workspace.refresh()
        return True

    def _run_section(self, source: str, language: str = "auto",
                     advance: bool = False) -> bool:
        """
        Run one ``%%`` section, appending to the console as typed commands
        do: no clearing, no save prompt, and its figures are not a run's.
        ``source`` is padded to the section's lines, so errors and
        breakpoints use the editor's line numbers.
        """
        if self.running:
            return False
        self.console.folder = self._folder()
        self.editor.code.set_error_line(None)
        self._running_script = True            # not a typed command
        try:
            results = self.console.run_script(source, language,
                                              debuggable=True)
        finally:
            self._running_script = False
        self._show_outcome(results, section=True)
        self.workspace.refresh()
        if advance:
            self.editor.next_section()
        return True

    def _show_outcome(self, results: list[Result],
                      section: bool = False) -> None:
        """Tint the line a run failed or was stopped on, and say so."""
        failed = next((r for r in results if r.error), None)
        what = "Section" if section else "Run"
        if failed is None:
            self.editor.set_status(f"{what} finished.")
            return
        if failed.line:
            self.editor.code.set_error_line(failed.line)
        where = f" at line {failed.line}" if failed.line else ""
        stopped = failed.error.startswith(str(dbg.Interrupted(None)))
        self.editor.set_status(f"{what} {'stopped' if stopped else 'failed'}"
                               f"{where} — see the Console tab.")

    # ── stopping and debugging ──────────────────────────────────

    def stop(self) -> None:
        """Interrupt whatever runs: a script, a section, a command."""
        self.interpreter.tracer.request_stop()
        self._debug(dbg.STOP)

    def _run_or_continue(self) -> None:
        if self.interpreter.tracer.paused is not None:
            self._debug(dbg.CONTINUE)
        elif not self.running:
            self.editor._run()

    def _debug(self, action: str) -> None:
        """Leave the pause with Continue, Step, Step in or Stop."""
        if action == dbg.STOP and self._pause_loop is None:
            self.interpreter.tracer.request_stop()
            return
        if self._pause_loop is not None:
            self._pause_action = action
            self._pause_loop.quit()

    def _set_breakpoints(self, lines: set[int]) -> None:
        self.interpreter.tracer.breakpoints = set(lines)

    def _on_pause(self, pause: dbg.Pause) -> str:
        """
        The tracer reached a breakpoint (or a step): show where, then wait
        in a nested event loop — the prompt evaluates in the paused scope
        meanwhile — until Continue, Step, Step in or Stop.
        """
        self.console.show_output(self.interpreter.drain_output())
        self.console.note(
            f"Paused at line {pause.line} — F5 continue, F10 step, "
            f"F11 step in, Shift+F5 stop. The prompt sees this scope.")
        if pause.debuggable:
            self.editor.code.set_current_line(pause.line)
        self.console.set_debugging(True)
        self.workspace.refresh()
        self._sync_run_state()
        self._pause_action = dbg.CONTINUE
        if not self.interpreter.tracer.stop_requested:
            self._pause_loop = QEventLoop()
            self._pause_loop.exec()
            self._pause_loop = None
        self.editor.code.set_current_line(None)
        self.console.set_debugging(False)
        self.editor.set_run_state(True, False)
        return self._pause_action

    def _sync_run_state(self, running: bool | None = None) -> None:
        tracer = self.interpreter.tracer
        if running is None:
            running = tracer.running
        self.editor.set_run_state(running, self._pause_loop is not None
                                  or tracer.paused is not None)

    def _offer_to_save_figures(self) -> list[Path] | None:
        """
        Ask whether the last run's unsaved figures should be kept.

        Returns the files written (empty when there was nothing to save or
        the user chose to discard), or None if the user cancelled the run.
        """
        unsaved = self.figures.script_figures(unsaved=True)
        if not unsaved:
            return []
        choice = self._ask_to_save_figures(len(unsaved))
        if choice == "cancel":
            return None
        if choice == "discard":
            return []
        folder = self._choose_figure_folder()
        if folder is None:
            return None
        return self.figures.save_figures(unsaved, folder)

    def _ask_to_save_figures(self, count: int) -> str:
        """'save', 'discard' or 'cancel'. A method so tests can answer it."""
        plural = "s" if count != 1 else ""
        box = QMessageBox(
            QMessageBox.Question, "Save figures?",
            f"The last run drew {count} figure{plural} that "
            f"{'have' if count != 1 else 'has'} not been saved. Running the "
            f"script again replaces {'them' if count != 1 else 'it'}.",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, self)
        names = f"{PLACEHOLDER_STEM}_1.png" + (
            f", {PLACEHOLDER_STEM}_2.png{' …' if count > 2 else ''}"
            if count > 1 else "")
        box.setInformativeText(
            f"Save keeps {'them' if count != 1 else 'it'} as {names} in a "
            f"folder you choose; names already taken there are skipped.")
        box.setDefaultButton(QMessageBox.Save)
        answer = box.exec()
        return {QMessageBox.Save: "save",
                QMessageBox.Discard: "discard"}.get(answer, "cancel")

    def _choose_figure_folder(self) -> Path | None:
        """Where unsaved figures go: the script's own folder, by default."""
        start = self.editor.path.parent if self.editor.path else Path.home()
        folder = QFileDialog.getExistingDirectory(
            self, "Save figures to", str(start))
        return Path(folder) if folder else None

    # ── history ─────────────────────────────────────────────────

    def _record(self, result) -> None:
        """A command ran at the prompt: keep it. A script's lines are not."""
        if result is not None and not self._running_script:
            self.history.add(result.source)

    def recall(self, command: str) -> None:
        """Put a command back at the prompt, ready to edit."""
        self._tabs.setCurrentIndex(0)
        self.console.set_input(command)
        self.console.focus_input()

    def show_history(self) -> None:
        self._tabs.setCurrentIndex(0)
        self._side.setCurrentWidget(self.history)

    def show_script(self) -> None:
        self._tabs.setCurrentWidget(self.editor)

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
