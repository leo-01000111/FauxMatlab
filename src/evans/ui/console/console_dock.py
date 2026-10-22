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
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
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
from ..assistant import AskCedricFloat, ConsoleSource, EditorSource, SwitchSource
from ..code import (
    CodeEditor,
    Context,
    FollowController,
    MatlabHighlighter,
    Target,
    code_request,
    warm_up,
)
from ..design import TIGHT, EmptyState
from .console_widget import ConsoleWidget
from .figure_view import FigureView, export_figure
from .history_widget import HistoryWidget
from .live_editor import LiveScriptEditor, set_code_highlighter
from .script_editor import ScriptDocument, ScriptEditor
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
    #: *Ask Cedric* on a selection: (context, source, action) for the panel.
    cedric_requested = Signal(object, object, str)

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
        self.editor.breakpoints_changed.connect(self._sync_breakpoints)
        #: The tab the current run or section came from; None between runs.
        self._run_document: ScriptDocument | None = None
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

        # What Cedric is asked about: the showing tab's code, and the last
        # error from wherever it came. Built before the editors attach
        # their per-widget hooks below, which use them.
        #: The last error anything here printed: the prompt, a run, a cell.
        self.last_error = ""
        self._console_source = ConsoleSource(
            self.console._input, self.console._transcript,
            language=lambda: ("matlab" if looks_like_matlab(
                self.console._input.text()) else "python"),
            variables=self.interpreter.variables,
            last_error=lambda: self.last_error)
        self._script_source = EditorSource(
            lambda: self.editor.code, where="script",
            language=self.editor.language,
            variables=self.interpreter.variables,
            last_error=lambda: self.last_error)
        self._live_source = EditorSource(
            self._live_cell_editor, where="live", language="matlab",
            variables=self.interpreter.variables,
            last_error=self._live_error, whole="cell")
        #: Cedric's source: whichever Console tab is showing.
        self.assistant_source = SwitchSource(self._showing_source)

        # Hover for syntax and Ctrl+click to go, wherever code is written
        # or shown: the script tabs, the live cells, the prompt, the output.
        # The floating Ask Cedric button rides along on the same hooks.
        def script_hooks(widget) -> None:
            self._attach_follow(widget, self._folder)
            self._attach_ask(widget, EditorSource(
                widget, where="script", language=self.editor.language,
                variables=self.interpreter.variables,
                last_error=lambda: self.last_error))

        def live_hooks(widget) -> None:
            self._attach_follow(
                widget, lambda: self.live.folder or self._folder())
            self._attach_ask(widget, EditorSource(
                widget, where="live", language="matlab",
                variables=self.interpreter.variables,
                last_error=self._live_error, whole="cell"))

        self.editor.set_follow(script_hooks)
        self.live.set_follow(live_hooks)
        self._attach_follow(self.console._input, self._folder)
        self._attach_follow(self.console._transcript, self._folder)
        self._attach_ask(self.console._input, self._console_source)
        self._attach_ask(self.console._transcript, self._console_source)

        # Cedric's button in the tab bar; the main window gives it the
        # action that shows and hides his dock.
        self.cedric_button = QToolButton()
        self.cedric_button.setObjectName("cedricButton")
        self.cedric_button.setText("Cedric")
        self.cedric_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._tabs.setCornerWidget(self.cedric_button, Qt.TopRightCorner)

        layout.addWidget(self._tabs)

        self.console.executed.connect(self.workspace.refresh)
        self.console.executed.connect(self._record)
        self.console.executed.connect(self._note_result)
        self.live.ran.connect(self._note_live_error)
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
        for key, slot in (("F5", self._run_or_continue),
                          ("Shift+F5", self.stop),
                          ("F10", lambda: self._debug(dbg.STEP)),
                          ("F11", lambda: self._debug(dbg.STEP_IN))):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)

    # ── hover and Ctrl+click ────────────────────────────────────

    def _attach_follow(self, widget, folder) -> FollowController:
        """Hover and Ctrl+click on ``widget``, looking in ``folder()``."""
        return FollowController(
            widget, lambda: self._follow_context(folder()), self.follow)

    def _follow_context(self, folder: Path) -> Context:
        interpreter = self.interpreter
        return Context(
            find_file=lambda name: self._function_file(name, folder),
            is_variable=lambda name: name in interpreter.variables(),
            python=lambda name: interpreter.namespace.get(name))

    def _function_file(self, name: str, folder: Path) -> Path | None:
        """``name.m`` in ``folder``, then on the path ``addpath`` built."""
        runtime = self.interpreter._matlab_runtime()
        for place in [folder, *runtime.path]:
            path = Path(place) / f"{name}.m"
            if path.is_file():
                return path
        return None

    def follow(self, target: Target, widget=None) -> None:
        """
        Go where a Ctrl+click points: a local function's line in the same
        editor, a function file in a script tab, a built-in's help page.
        """
        if target.kind == "local" and isinstance(widget, CodeEditor):
            widget.goto_line(target.line)
            widget.setFocus()
        elif target.kind == "file" and target.path is not None:
            self._tabs.setCurrentWidget(self.editor)
            self.editor.load_file(target.path, target.line).code.setFocus()
        elif target.kind == "help":
            from ..help import open_help
            open_help(target.name)

    # ── Cedric ──────────────────────────────────────────────────

    def _attach_ask(self, widget, source) -> AskCedricFloat:
        """The floating Ask Cedric button on ``widget``, asking ``source``."""
        return AskCedricFloat(widget, lambda action: self.cedric_requested.emit(
            source.context(), source.resolve(), action))

    def _showing_source(self):
        current = self._tabs.currentWidget()
        if current is self.editor:
            return self._script_source
        if current is self.live:
            return self._live_source
        return self._console_source

    def _live_cell_editor(self):
        """The current live cell's code editor, if the current cell is code."""
        cell = self.live.current_cell
        if cell is None or not cell.is_code:
            return None
        try:
            return self.live.widget_for(cell).editor
        except KeyError:
            return None

    def _live_error(self) -> str:
        """The current cell's error, else the last one printed anywhere."""
        cell = self.live.current_cell
        output = getattr(cell, "output", None)
        if output is not None and output.error:
            return output.error
        return self.last_error

    def _note_result(self, result) -> None:
        if result is not None and result.error:
            self.last_error = result.error

    def _note_live_error(self) -> None:
        failed = next((c for c in self.live.document.code_cells()
                       if c.output is not None and not c.output.ok), None)
        if failed is not None:
            self.last_error = failed.output.error

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
        """
        The current folder: the running script's, else the showing tab's,
        else where the app started.
        """
        document = self._run_document or self.editor.current_document()
        return document.path.parent if document.path else Path.cwd()

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
        if not self._offer_to_save_scripts():
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
        document = self._begin_run()
        self.figures.begin_script_run()
        path = document.path
        self.interpreter.script_folder = str(path.parent) if path else None
        try:
            results = self.console.run_script(source, language,
                                              debuggable=True)
        finally:
            self.figures.end_script_run()
            self._end_run()
        self._show_outcome(results, document=document)
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
        if not self._offer_to_save_scripts():
            return False
        document = self._begin_run()
        try:
            results = self.console.run_script(source, language,
                                              debuggable=True)
        finally:
            self._end_run()
        self._show_outcome(results, section=True, document=document)
        self.workspace.refresh()
        if advance:
            self.editor.next_section(document)
        return True

    def _begin_run(self) -> ScriptDocument:
        """The showing tab becomes the running one, until the run ends."""
        document = self.editor.current_document()
        self._run_document = document
        self.editor.set_busy(document)
        self._sync_breakpoints()
        self.console.folder = self._folder()
        document.code.set_error_line(None)
        self._running_script = True            # not a typed command
        return document

    def _end_run(self) -> None:
        self._running_script = False
        self.editor.set_busy(None)
        self._run_document = None
        self._sync_breakpoints()

    def _offer_to_save_scripts(self) -> bool:
        """
        A run calls function files from disk, so tabs of ``.m`` files with
        unsaved changes are offered for saving first. Returns False if the
        user cancelled the run. The script being run needs no saving: it
        runs from its tab.
        """
        unsaved = self.editor.unsaved_files(
            exclude=self.editor.current_document())
        if not unsaved:
            return True
        choice = self._ask_to_save_scripts([d.name for d in unsaved])
        if choice == "cancel":
            return False
        if choice == "save":
            return all(self.editor.save(d) for d in unsaved)
        return True

    def _ask_to_save_scripts(self, names: list[str]) -> str:
        """'save', 'run' or 'cancel'. A method so tests can answer it."""
        box = QMessageBox(
            QMessageBox.Question, "Save before running?",
            "Functions run from their saved files, and "
            + (f"{names[0]} has" if len(names) == 1
               else f"{len(names)} open files have")
            + " changes that are not saved.", QMessageBox.NoButton, self)
        if len(names) > 1:
            box.setInformativeText(", ".join(names))
        save = box.addButton("Save and run", QMessageBox.AcceptRole)
        run = box.addButton("Run without saving", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(save)
        box.exec()
        clicked = box.clickedButton()
        return "save" if clicked is save else "run" if clicked is run \
            else "cancel"

    def _show_outcome(self, results: list[Result], section: bool = False,
                      document: ScriptDocument | None = None) -> None:
        """Tint the line a run failed or was stopped on, and say so."""
        document = document or self.editor.current_document()
        failed = next((r for r in results if r.error), None)
        what = "Section" if section else "Run"
        if failed is not None:
            self.last_error = failed.error
        if failed is None:
            self.editor.set_status(f"{what} finished.")
            return
        if failed.line and document in self.editor.documents():
            self.editor.show_document(document)
            document.code.set_error_line(failed.line)
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

    def _sync_breakpoints(self) -> None:
        """
        Hand every tab's breakpoints to the tracer: the running (else the
        showing) tab's as the script's own, and each saved file's under its
        name, for when a run calls into it.
        """
        tracer = self.interpreter.tracer
        document = self._run_document or self.editor.current_document()
        tracer.breakpoints = document.code.breakpoints
        tracer.file_breakpoints = {
            d.key: d.code.breakpoints for d in self.editor.documents()
            if d.path is not None and d.code.breakpoints}

    def _on_pause(self, pause: dbg.Pause) -> str:
        """
        The tracer reached a breakpoint (or a step): show where, then wait
        in a nested event loop — the prompt evaluates in the paused scope
        meanwhile — until Continue, Step, Step in or Stop.
        """
        self.console.show_output(self.interpreter.drain_output())
        shown = self._document_paused_in(pause) if pause.debuggable \
            else None
        where = f" of {shown.name}" if shown is not None \
            and len(self.editor.documents()) > 1 else ""
        self.console.note(
            f"Paused at line {pause.line}{where} — F5 continue, F10 step, "
            f"F11 step in, Shift+F5 stop. The prompt sees this scope.")
        if shown is not None:
            # The paused line is the thing to look at: the Script tab, its
            # file's tab, the line. The prompt is a tab away for inspecting.
            self._tabs.setCurrentWidget(self.editor)
            self.editor.show_document(shown)
            shown.code.set_current_line(pause.line)
        self.console.set_debugging(True)
        self.workspace.refresh()
        self._sync_run_state()
        self._pause_action = dbg.CONTINUE
        if not self.interpreter.tracer.stop_requested:
            self._pause_loop = QEventLoop()
            self._pause_loop.exec()
            self._pause_loop = None
        if shown is not None:
            shown.code.set_current_line(None)
        self.console.set_debugging(False)
        self.editor.set_run_state(True, False)
        return self._pause_action

    def _document_paused_in(self, pause: dbg.Pause) -> ScriptDocument | None:
        """
        The tab to show a pause in: the running script's, or — paused in a
        function file — that file's tab, opened for it if need be.
        """
        if pause.file is None:
            return self._run_document or self.editor.current_document()
        document = self.editor.document_by_key(pause.file)
        if document is None:
            try:
                document = self.editor.load_file(pause.file)
            except (OSError, UnicodeDecodeError):
                return None
        return document

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
