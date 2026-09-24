r"""
Main application window.
========================

::

  ┌──────────────────────────────────────────────────────────┐
  │ G(s) = …   K₂(s) = …   ● stable   PM 60°   [Edit model ▾]│  context bar
  ├──────────────────────────────────────────────────────────┤
  │ 📌 Snapshot  [ … ]  Restore  Delete  Compare             │
  ├──────────────────────────────────────────────────────────┤
  │ System │ Time │ Frequency │ … │ Simulink │ Modern        │
  │                                                          │
  │                    the analysis area                     │
  └──────────────────────────────────────────────────────────┘

The architecture diagram and the block editor are a **dock** (Ctrl+\),
not a permanent column. They used to occupy 420–760 px on every tab — 21 %
of the window — including on the two tabs that analyse a different model
entirely. What is always visible instead is the context bar, which answers
"what is loaded and is it stable?" in one strip.

Geometry, dock layout and the current tab are saved on close and restored on
launch; View ▸ Reset layout puts them back to the defaults.
"""

from __future__ import annotations

import json
from pathlib import Path

import control as ctl
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..console.apps import AppRequest, set_app_sink
from ..core.architecture import CourseArchitecture
from ..core.collection import SnapshotStore, SystemCollection
from ..core.lessons import Lesson, all_lessons
from ..core.report import text_report
from ..core.session import load_session_dict, session_dict
from ..core.tf_utils import (
    first_order,
    second_order,
    unity,
)
from .apps import ControlSystemDesigner, LTIViewer, PIDTuner, SnapshotBar
from .block_editor import BlockEditor
from .console import ConsolePanel, FigureArea
from .context_bar import ContextBar
from .design import TIGHT
from .diagram.fixed_diagram import FixedDiagramView
from .lesson_dock import LessonDock
from .panes import DEFAULT_LAYOUT, PaneGrid
from .sim.sim_tab import SimTab
from .tabs.design_tab import DesignTab
from .tabs.frequency_tab import FrequencyTab
from .tabs.modern import ModernTab
from .tabs.performance_tab import PerformanceTab
from .tabs.stability_tab import StabilityTab
from .tabs.system_tab import SystemTab
from .tabs.time_tab import TimeTab
from .workspace import Workspace, WorkspaceStack


class MainWindow(QMainWindow):

    APP_TITLE = "FakeMatlab — Classical Control Workbench"

    def __init__(self, arch: CourseArchitecture | None = None) -> None:
        super().__init__()
        self._arch = arch or CourseArchitecture(
            G  = first_order(1.0, 1.0),
            K2 = unity(),
            K1 = unity(),
            H  = unity(),
        )
        self.setWindowTitle(self.APP_TITLE)
        self.resize(1400, 850)
        #: Snapshots are shared: the bar above the tabs, the Compare button
        #: and the console all read the same store.
        self.snapshots = SnapshotStore()
        self._apps: dict[str, QWidget] = {}
        self._build_ui()
        self._build_docks()
        self._build_menus()
        self._build_status_bar()
        set_app_sink(self.open_app)

    # ── UI construction ───────────────────────────────────────

    #: Tab labels. Words, not emoji: the old `🔬 System` rendered as an empty
    #: box wherever the emoji font was missing — including in this project's
    #: own headless screenshots — and an emoji is not a navigable label for
    #: anything that reads the interface aloud.
    _TABS = (
        ("_sys_tab", "System"),
        ("_time_tab", "Time"),
        ("_freq_tab", "Frequency"),
        ("_stab_tab", "Stability"),
        ("_perf_tab", "Performance"),
        ("_des_tab", "Design"),
        ("_mod_tab", "Modern"),
    )

    def _build_ui(self) -> None:
        self._stack = WorkspaceStack()
        self.setCentralWidget(self._stack)
        self._stack.changed.connect(self._on_workspace_changed)

        self._stack.add_page(Workspace.ANALYSE, self._build_analyse())
        # The Simulink tab becomes the Model workspace outright: it is a
        # different model with its own undo stack and file format, not another
        # view of the architecture the other panels share.
        self._sim_tab = SimTab()
        self._stack.add_page(Workspace.MODEL, self._sim_tab)
        self._stack.add_page(Workspace.CONSOLE, self._build_console())

        # ── Connections ──
        self._diagram.block_selected.connect(self._on_block_selected)
        self._diagram.signal_selected.connect(self._on_signal_selected)
        self._diagram.architecture_changed.connect(self._on_arch_changed)
        self._editor.tf_changed.connect(self._on_tf_edited)
        self._des_tab.controller_changed.connect(self._on_controller_designed)
        self._sim_tab.linearised.connect(self._on_linearised)
        self._mod_tab.ctx.status.connect(
            lambda m: self._status.showMessage(m, 6000))
        self._mod_tab.model_sent_to_analysis.connect(
            self._on_modern_model_sent)
        self._tabs.currentChanged.connect(self._on_tab_changed)

    def _build_analyse(self) -> QWidget:
        central = QWidget()
        main_lay = QVBoxLayout(central)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(TIGHT)

        # ── the model context bar ──
        #
        # What used to be a permanent 420–760 px column is now one strip. The
        # diagram and the block editor live in a dock that opens on demand
        # (Ctrl+\), so the analysis area gets the width instead of a picture
        # of an architecture that two of the eight tabs do not even analyse.
        self._context = ContextBar(self._arch)
        self._context.edit_requested.connect(self.toggle_model_panel)
        main_lay.addWidget(self._context)

        # ── the snapshot bar ──
        #
        # Above the tabs because a snapshot is of the whole architecture, not
        # of whatever panel happens to be open — taking one on the Frequency
        # tab and restoring it on the Time tab is the point.
        self._snapshot_bar = SnapshotBar(self._arch, self.snapshots)
        self._snapshot_bar.restored.connect(self._on_snapshot_restored)
        self._snapshot_bar.compare_requested.connect(self._compare_snapshots)
        main_lay.addWidget(self._snapshot_bar)

        # The tabs still exist — they are whole workflows, and a pane can
        # host one — but they are no longer the only way to look at the
        # system. The grid is, because tuning is watching the step response
        # and the Bode plot and the locus move *together*, which six tabs
        # turn into a sequence of glances and a memory test.
        self._sys_tab  = SystemTab(self._arch)
        self._time_tab = TimeTab(self._arch)
        self._freq_tab = FrequencyTab(self._arch)
        self._stab_tab = StabilityTab(self._arch)
        self._perf_tab = PerformanceTab(self._arch)
        self._des_tab  = DesignTab(self._arch)
        self._mod_tab  = ModernTab(self._arch)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        for attribute, label in self._TABS:
            self._tabs.addTab(getattr(self, attribute), label)

        self._grid = PaneGrid(self._arch, tab_factory=self._make_tab)

        self._view_tabs = QTabWidget()
        self._view_tabs.setDocumentMode(True)
        self._view_tabs.addTab(self._wrap_grid(), "Panes")
        self._view_tabs.addTab(self._tabs, "Tabs")
        self._view_tabs.currentChanged.connect(
            lambda _i: self._update_all_tabs())
        main_lay.addWidget(self._view_tabs, stretch=1)

        # ── the model panel, as a dock ──
        self._model_dock = QDockWidget("Model", self)
        self._model_dock.setObjectName("ModelDock")
        self._model_dock.setAllowedAreas(Qt.LeftDockWidgetArea |
                                         Qt.RightDockWidgetArea)
        panel = QWidget()
        panel_lay = QVBoxLayout(panel)
        panel_lay.setContentsMargins(0, 0, 0, 0)
        panel_lay.setSpacing(TIGHT)
        # The diagram is inherently wide and short (roughly 3.3:1), so cap its
        # height and give the space it cannot use to the block editor.
        self._diagram = FixedDiagramView(self._arch)
        self._diagram.setMinimumHeight(150)
        self._diagram.setMaximumHeight(260)
        panel_lay.addWidget(self._diagram, stretch=0)
        self._editor = BlockEditor()
        panel_lay.addWidget(self._editor, stretch=1)
        self._model_dock.setWidget(panel)
        self.addDockWidget(Qt.LeftDockWidgetArea, self._model_dock)
        self._model_dock.hide()
        return central


    def _wrap_grid(self) -> QWidget:
        """The pane grid with its layout selector above it."""
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(TIGHT)

        row = QHBoxLayout()
        row.setSpacing(TIGHT)
        row.addWidget(QLabel("Panes:"))
        self._layout_buttons = {}
        for count, label in ((1, "1"), (2, "1 × 2"), (4, "2 × 2")):
            button = QToolButton()
            button.setText(label)
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setToolTip(f"Show {count} analysis pane"
                              f"{'s' if count > 1 else ''}")
            button.setAccessibleName(f"{count} panes")
            button.clicked.connect(
                lambda _checked=False, n=count: self.set_pane_layout(n))
            row.addWidget(button)
            self._layout_buttons[count] = button
        row.addStretch()
        column.addLayout(row)
        column.addWidget(self._grid, stretch=1)
        return holder

    def set_pane_layout(self, count: int) -> None:
        """1, 2 or 4 panes. A fresh 2×2 opens on step, Bode, locus, metrics."""
        keys = None if self._grid.count else DEFAULT_LAYOUT
        self._grid.set_layout_size(count, keys)
        for size, button in self._layout_buttons.items():
            button.blockSignals(True)
            button.setChecked(size == count)
            button.blockSignals(False)
        self._status.showMessage(
            f"{count} analysis pane{'s' if count > 1 else ''}", 3000)

    #: Which widget a pane gets when it asks for a whole tab.
    def _make_tab(self, name: str, arch):
        from .tabs.design_tab import DesignTab as _Design
        from .tabs.performance_tab import PerformanceTab as _Performance
        from .tabs.stability_tab import StabilityTab as _Stability
        from .tabs.system_tab import SystemTab as _System

        # A new instance rather than the shared one: a widget lives in one
        # place, so handing the grid the tab that is already inside the Tabs
        # view would move it out of there.
        factory = {"system": _System, "stability": _Stability,
                   "performance": _Performance, "design": _Design,
                   "modern": ModernTab}.get(name)
        return factory(arch) if factory else None

    def _build_console(self) -> QWidget:
        """
        The Console workspace: transcript and variables over the figures.

        The console used to be a dock hidden by default, which made a
        first-class way of driving this application into a panel you had to
        know existed. Plot commands drew into a second hidden dock.
        """
        self._figures = FigureArea()
        self._console = ConsolePanel(self._figures,
                                     extra=self._console_state())
        self._console.open_system.connect(self._on_console_system)
        self._console.open_model.connect(self._on_console_model)
        # A figure drawn from anywhere pulls the workspace into view, so
        # `step(G)` typed on the Analyse page does not draw somewhere unseen.
        self._figures.figure_added.connect(
            lambda: self._stack.set_current(Workspace.CONSOLE))

        split = QSplitter(Qt.Vertical)
        split.addWidget(self._console)
        split.addWidget(self._figures)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        return split

    # ── Docks ────────────────────────────────────────────────

    def _build_docks(self) -> None:
        """The lesson panel — the only remaining dock."""
        self._lessons = LessonDock(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self._lessons)
        self._lessons.hide()
        self._lessons.console_requested.connect(self._run_lesson_snippet)

    def _console_state(self) -> dict:
        """
        What the console starts with from the app.

        ``arch`` and ``model`` are live references, so a command typed at the
        prompt and a change made in a tab act on the same objects rather than
        on copies that quietly diverge.
        """
        return {
            "arch": self._arch,
            "G": self._arch.block_tf("G"),
            "K2": self._arch.block_tf("K2"),
            "model": self._sim_tab._canvas.model,
        }

    def _on_console_system(self, name: str, system) -> None:
        """A system was double-clicked in the workspace: analyse it as G(s)."""
        tf = ctl.ss2tf(system) if hasattr(system, "A") else system
        self._arch.set_block("G", tf)
        self._diagram.build()
        self._update_all_tabs()
        self._refresh_status()
        self._stack.set_current(Workspace.ANALYSE)
        self._tabs.setCurrentWidget(self._sys_tab)
        self._status.showMessage(f"{name} loaded as G(s)", 6000)

    def _on_console_model(self, name: str, model) -> None:
        """A Simulink model was double-clicked: open it on the canvas."""
        self._sim_tab._canvas.set_model(model)
        self._sim_tab._canvas.fit_all()
        self._stack.set_current(Workspace.MODEL)
        self._status.showMessage(f"{name} opened on the canvas", 6000)

    # ── Layout ───────────────────────────────────────────────

    #: Where `QSettings` keeps this window's layout.
    SETTINGS_ORG = "FauxMatlab"
    SETTINGS_APP = "FauxMatlab"

    def toggle_model_panel(self, *_ignored) -> None:
        """Show or hide the architecture diagram and block editor."""
        visible = not self._model_dock.isVisible()
        self._model_dock.setVisible(visible)
        if visible:
            self._model_dock.raise_()
        self._act_model.setChecked(visible)

    def _settings(self) -> QSettings:
        return QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)

    def save_layout(self) -> None:
        """
        Remember the arrangement.

        Nothing was persisted before: every launch put the splitter back,
        hid the console, forgot which tab you were on and dropped any dock
        you had arranged.
        """
        settings = self._settings()
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())
        settings.setValue("currentTab", self._tabs.currentIndex())
        settings.setValue("modelPanel", self._model_dock.isVisible())
        settings.setValue("workspace", self._stack.current.value)

    def restore_layout(self) -> bool:
        """Put it back. Returns whether anything was restored."""
        settings = self._settings()
        geometry = settings.value("geometry")
        state = settings.value("windowState")
        if geometry is None and state is None:
            return False
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self.restoreState(state)
        index = settings.value("currentTab")
        if index is not None:
            try:
                self._tabs.setCurrentIndex(int(index))
            except (TypeError, ValueError):
                pass
        saved = settings.value("workspace")
        if saved:
            try:
                self._stack.set_current(Workspace(saved))
            except ValueError:
                pass
        # `restoreState` brings back dock *visibility* too, so the menu check
        # marks have to be re-synchronised or they disagree with the window.
        self._sync_view_menu()
        return True

    def reset_layout(self) -> None:
        """
        Back to the defaults, and forget what was saved.

        A restored layout can become unusable — a dock dragged off-screen, a
        saved geometry from a monitor that is no longer attached. Without
        this, the only fix is deleting a registry key.
        """
        self._settings().clear()
        for dock in (self._model_dock, self._lessons):
            dock.hide()
        self.removeDockWidget(self._model_dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, self._model_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self._lessons)
        self.resize(1400, 850)
        self._tabs.setCurrentIndex(0)
        self._stack.set_current(Workspace.ANALYSE)
        self._sync_view_menu()
        self._status.showMessage("Layout reset", 4000)

    def _sync_view_menu(self) -> None:
        self._act_model.blockSignals(True)
        self._act_model.setChecked(self._model_dock.isVisible())
        self._act_model.blockSignals(False)

        current = self._stack.current
        for workspace, action in self._workspace_actions.items():
            action.blockSignals(True)
            action.setChecked(workspace is current)
            action.blockSignals(False)

    def closeEvent(self, event) -> None:
        self.save_layout()
        super().closeEvent(event)

    # ── Apps ─────────────────────────────────────────────────

    def open_app(self, request: AppRequest):
        """
        The console's app sink: ``ltiview(G)`` at the prompt lands here.

        Also the one path the menu actions take, so a window opened by typing
        and a window opened by clicking are the same window — not two copies
        of it quietly diverging.
        """
        opener = {
            "ltiview": self._open_lti_viewer,
            "sisotool": self._open_designer,
            "pidtuner": self._open_pid_tuner,
        }[request.app]
        return opener(request)

    def _show(self, key: str, widget: QWidget) -> QWidget:
        """Keep a reference — a parentless QWidget is garbage at once."""
        self._apps[key] = widget
        widget.show()
        widget.raise_()
        widget.activateWindow()
        return widget

    def _open_lti_viewer(self, request: AppRequest | None = None) -> LTIViewer:
        viewer = self._apps.get("ltiview")
        if not isinstance(viewer, LTIViewer):
            viewer = LTIViewer()
            viewer.open_requested.connect(self._on_console_system)
        systems = dict(request.systems) if request is not None else {}
        if not systems and not len(viewer.collection):
            systems = self._default_viewer_systems()
        for name, system in systems.items():
            viewer.collection.add(name, system)
        viewer.refresh()
        return self._show("ltiview", viewer)

    def _default_viewer_systems(self) -> dict:
        """What the viewer opens with when nothing was named: the loop."""
        return {
            "G (plant)": self._arch.block_tf("G"),
            "L (open loop)": self._arch.loop_tf(),
            "T (closed loop)": self._arch.get_closed_loop_tf("r", "y"),
        }

    def _open_designer(self,
                       request: AppRequest | None = None
                       ) -> ControlSystemDesigner:
        systems = dict(request.systems) if request is not None else {}
        designer = self._apps.get("sisotool")
        if not isinstance(designer, ControlSystemDesigner):
            designer = ControlSystemDesigner(
                plant=systems.get("plant", self._arch.block_tf("G")),
                sensor=self._arch.block_tf("H"))
            designer.compensator_applied.connect(self._on_controller_designed)
        elif "plant" in systems:
            designer.set_plant(systems["plant"], self._arch.block_tf("H"))
        return self._show("sisotool", designer)

    def _open_pid_tuner(self, request: AppRequest | None = None) -> PIDTuner:
        systems = dict(request.systems) if request is not None else {}
        kind = (request.options.get("kind", "PI")
                if request is not None else "PI")
        tuner = self._apps.get("pidtuner")
        if not isinstance(tuner, PIDTuner):
            tuner = PIDTuner(
                plant=systems.get("plant", self._arch.block_tf("G")),
                baseline=self._arch.block_tf("K2"), kind=kind)
            tuner.controller_applied.connect(self._on_controller_designed)
        else:
            tuner.set_plant(systems.get("plant", self._arch.block_tf("G")),
                            self._arch.block_tf("K2"))
        return self._show("pidtuner", tuner)

    # ── Lessons ──────────────────────────────────────────────

    #: Lesson tab names → the attribute holding that tab.
    _TAB_BY_NAME = {
        "System": "_sys_tab", "Time": "_time_tab", "Frequency": "_freq_tab",
        "Stability": "_stab_tab", "Performance": "_perf_tab",
        "Design": "_des_tab", "Simulink": "_sim_tab", "Modern": "_mod_tab",
    }

    def load_lesson(self, lesson: Lesson) -> None:
        """
        Load a worked example: its blocks, its tab, and its notes.

        A snapshot of the current design is taken first, so opening a lesson
        out of curiosity does not cost you the controller you were working on
        — Restore brings it back. It reuses one slot rather than accumulating,
        because browsing seven lessons should not fill the store with seven
        copies of the same "before".
        """
        self.snapshots.remove("before lesson")
        self.snapshots.take(self._arch, "before lesson")
        self._snapshot_bar.refresh()

        lesson.apply_to(self._arch)
        self._diagram.build()
        self._refresh_status()

        if lesson.tab == "Simulink":
            self._stack.set_current(Workspace.MODEL)
        else:
            self._stack.set_current(Workspace.ANALYSE)
            tab = getattr(self,
                          self._TAB_BY_NAME.get(lesson.tab, "_sys_tab"), None)
            if tab is not None:
                self._tabs.setCurrentWidget(tab)
        self._update_all_tabs()

        self._lessons.show_lesson(lesson, self._arch)
        self._status.showMessage(
            f"Chapter {lesson.chapter}: {lesson.title}  "
            f"({lesson.slides})", 10000)

    def _run_lesson_snippet(self, commands: tuple[str, ...]) -> None:
        """Send a lesson's snippet to the console, one line at a time."""
        self._stack.set_current(Workspace.CONSOLE)
        self._console.focus()
        for command in commands:
            self._console.execute(command)

    def _compare_snapshots(self, collection: SystemCollection) -> None:
        """The snapshot bar's Compare button: hand them to the LTI Viewer."""
        viewer = self._open_lti_viewer()
        viewer.set_collection(collection)
        self._status.showMessage(
            f"Comparing {len(collection)} designs in the LTI Viewer", 6000)

    def _on_snapshot_restored(self, snapshot) -> None:
        self._diagram.build()
        self._update_all_tabs()
        self._refresh_status()
        self._status.showMessage(f"Restored “{snapshot.label}”", 5000)

    # ── Menus ────────────────────────────────────────────────

    def _build_menus(self) -> None:
        mb = self.menuBar()

        # File menu
        file_menu = mb.addMenu("&File")
        act_new  = QAction("&New session",    self); act_new.setShortcut("Ctrl+N")
        act_open = QAction("&Open session…",  self); act_open.setShortcut("Ctrl+O")
        act_save = QAction("&Save session…",  self); act_save.setShortcut("Ctrl+S")
        act_quit = QAction("&Quit",           self); act_quit.setShortcut("Ctrl+Q")
        act_new.triggered.connect(self._new_session)
        act_open.triggered.connect(self._open_session)
        act_save.triggered.connect(self._save_session)
        act_quit.triggered.connect(self.close)
        for a in [act_new, act_open, act_save, None, act_quit]:
            if a is None:
                file_menu.addSeparator()
            else:
                file_menu.addAction(a)

        # Export menu
        export_menu = mb.addMenu("&Export")
        act_copy = QAction("&Copy analysis report", self)
        act_copy.setShortcut("Ctrl+Shift+C")
        act_copy.triggered.connect(self._copy_report)
        act_report = QAction("Save analysis &report…", self)
        act_report.triggered.connect(self._save_report)
        act_png = QAction("Export current tab as &PNG…", self)
        act_png.setShortcut("Ctrl+Shift+P")
        act_png.triggered.connect(self._export_plot_png)
        for a in (act_copy, act_report, act_png):
            export_menu.addAction(a)

        # View menu
        view_menu = mb.addMenu("&View")
        act_model = QAction("&Model panel", self, checkable=True)
        act_model.setShortcut("Ctrl+\\")
        act_model.setStatusTip(
            "The architecture diagram and the block editor")
        act_model.triggered.connect(self.toggle_model_panel)
        self._act_model = act_model
        view_menu.addAction(act_model)

        view_menu.addSeparator()

        # The three workspaces. Ctrl+1/2/3, plus Ctrl+` for the console
        # because that is the key everyone's fingers already know.
        self._workspace_actions: dict[Workspace, QAction] = {}
        for workspace in Workspace:
            action = QAction(workspace.value, self, checkable=True)
            action.setShortcut(workspace.shortcut)
            action.setStatusTip(workspace.description)
            action.triggered.connect(
                lambda _checked=False, w=workspace:
                self._stack.set_current(w))
            view_menu.addAction(action)
            self._workspace_actions[workspace] = action

        console_shortcut = QAction("Command window", self)
        console_shortcut.setShortcut("Ctrl+`")
        console_shortcut.triggered.connect(
            lambda: self._stack.set_current(Workspace.CONSOLE))
        self.addAction(console_shortcut)

        view_menu.addSeparator()
        view_menu.addAction(QAction(
            "&Reset layout", self, triggered=self.reset_layout,
            statusTip="Restore the default window and dock arrangement"))
        view_menu.addSeparator()
        view_menu.addAction(QAction(
            "Send current plant to the console", self,
            triggered=self._push_to_console))

        # Apps menu
        apps_menu = mb.addMenu("&Apps")
        for label, shortcut, slot, tip in (
            ("&LTI Viewer", "Ctrl+Shift+L", self._open_lti_viewer,
             "Every loaded system, any response, on one set of axes."),
            ("&Control System Designer", "Ctrl+Shift+D", self._open_designer,
             "Drag a closed-loop pole on the root locus; Bode and step follow."),
            ("&PID Tuner", "Ctrl+Shift+T", self._open_pid_tuner,
             "Two sliders: response time and transient behaviour."),
        ):
            action = QAction(label, self)
            action.setShortcut(shortcut)
            action.setStatusTip(tip)
            action.triggered.connect(lambda _checked=False, s=slot: s())
            apps_menu.addAction(action)

        # Lessons menu
        lesson_menu = mb.addMenu("&Lessons")
        for item in all_lessons():
            action = QAction(f"Ch. {item.chapter} — {item.title}", self)
            action.setStatusTip(item.slides)
            action.triggered.connect(
                lambda _checked=False, les=item: self.load_lesson(les))
            lesson_menu.addAction(action)
        lesson_menu.addSeparator()
        show_notes = QAction("Show the lesson panel", self)
        show_notes.triggered.connect(
            lambda: (self._lessons.show(), self._lessons.raise_()))
        lesson_menu.addAction(show_notes)

        # Presets menu
        preset_menu = mb.addMenu("&Presets")
        preset_menu.addAction(QAction("1st order  K/(τs+1)", self,
                                       triggered=self._preset_first_order))
        preset_menu.addAction(QAction("2nd order underdamped", self,
                                       triggered=self._preset_so_under))
        preset_menu.addAction(QAction("2nd order overdamped", self,
                                       triggered=self._preset_so_over))
        preset_menu.addAction(QAction("Double integrator 1/s²", self,
                                       triggered=self._preset_double_int))
        preset_menu.addAction(QAction("Unstable plant 1/(s-1)", self,
                                       triggered=self._preset_unstable))
        preset_menu.addAction(QAction("Non-minimum phase (−s+1)/(s+1)", self,
                                       triggered=self._preset_nmp))
        preset_menu.addAction(QAction("Satellite (double integrator)", self,
                                       triggered=self._preset_satellite))

        # Help menu
        help_menu = mb.addMenu("&Help")
        help_menu.addAction(QAction("About", self,
                                     triggered=self._show_about))

    def _build_status_bar(self) -> None:
        self._status = QStatusBar()
        self.setStatusBar(self._status)

    # ── Event handlers ────────────────────────────────────────

    def _on_block_selected(self, block_id: str) -> None:
        bd = self._arch.get_block(block_id)
        self._editor.load_block(block_id, bd.tf, bd.label)
        self._status.showMessage(f"Editing {bd.label}", 3000)

    def _on_signal_selected(self, signal_id: str) -> None:
        self._status.showMessage(f"Signal tap: {signal_id}", 2000)
        self._sys_tab.set_active_signal(signal_id)
        self._time_tab.set_active_signal(signal_id)
        self._freq_tab.set_active_signal(signal_id)
        self._on_tab_changed(self._tabs.currentIndex())

    def _on_tf_edited(self, block_id: str, tf: ctl.TransferFunction) -> None:
        self._diagram.update_block(block_id, tf)
        self._update_all_tabs()
        self._refresh_status()

    def _on_arch_changed(self) -> None:
        self._update_all_tabs()

    def _on_controller_designed(self, tf: ctl.TransferFunction) -> None:
        """Design tab applied a new K2 — sync diagram and all tabs."""
        self._diagram.update_block("K2", tf)
        self._update_all_tabs()
        self._refresh_status()

    def _on_tab_changed(self, idx: int) -> None:
        arch = self._arch
        tab_widgets = [getattr(self, attribute)
                       for attribute, _ in self._TABS]
        if 0 <= idx < len(tab_widgets):
            tab_widgets[idx].refresh(arch)

    def _refresh_analyse(self) -> None:
        """Whichever view of the Analyse page is showing."""
        if self._view_tabs.currentIndex() == 0:
            self._grid.refresh(self._arch)
        else:
            self._on_tab_changed(self._tabs.currentIndex())

    def _on_modern_model_sent(self) -> None:
        """The Modern tab pushed its state-space model back as G(s)."""
        self._diagram.build()
        self._update_all_tabs()
        self._refresh_status()

    def _on_linearised(self, tf, description: str) -> None:
        """
        A model was linearised on the Simulink tab: analyse it here.

        The linearised system becomes the plant G, with the controller reset
        to unity — the loop is already baked into the linearisation, so
        leaving K₂ in place would apply it twice.
        """
        self._arch.set_block("G", tf)
        self._arch.set_block("K2", unity())
        self._diagram.build()
        self._update_all_tabs()
        self._refresh_status()
        self._stack.set_current(Workspace.ANALYSE)
        self._tabs.setCurrentWidget(self._sys_tab)
        self._status.showMessage(
            "Linearised model loaded as G(s) — " +
            description.splitlines()[0], 8000)

    # ── Full refresh ──────────────────────────────────────────

    def _update_all_tabs(self) -> None:
        """Refresh what is on screen now; the rest lazily when selected."""
        self._context.refresh()
        self._refresh_analyse()

    def _on_workspace_changed(self, workspace) -> None:
        """Refresh whatever the new page shows, and tell the menu."""
        if workspace is Workspace.ANALYSE:
            self._update_all_tabs()
        elif workspace is Workspace.CONSOLE:
            self._console.focus()
        self._sync_view_menu()
        self._status.showMessage(workspace.description, 4000)

    def show_workspace(self, workspace) -> None:
        self._stack.set_current(workspace)

    def _push_to_console(self) -> None:
        """Put the current plant and loop into the workspace under short names."""
        self._console.push(
            arch=self._arch,
            G=self._arch.block_tf("G"),
            K2=self._arch.block_tf("K2"),
            L=self._arch.loop_tf(),
            T=self._arch.get_closed_loop_tf("r", "y"),
            model=self._sim_tab._canvas.root_model(),
        )
        self._stack.set_current(Workspace.CONSOLE)
        self._status.showMessage(
            "G, K2, L, T, arch and model are now in the workspace", 6000)

    def _refresh_status(self) -> None:
        """
        Refresh the context bar.

        The status bar used to carry ``G=[1, 2]/[1, 3, 3, 1]`` — coefficient
        arrays, no factorisation, no verdict. That job belongs to the context
        bar now; the status bar is for transient messages.
        """
        self._context.refresh()

    # ── File I/O ──────────────────────────────────────────────

    def _new_session(self) -> None:
        self._arch = CourseArchitecture(
            G  = first_order(1.0, 1.0),
            K2 = unity(), K1 = unity(), H  = unity(),
        )
        self._diagram._arch = self._arch
        # Everything holding the *old* architecture has to be handed the new
        # one. A stale reference here is invisible until someone takes a
        # snapshot of a plant that is no longer on screen.
        self._snapshot_bar.set_architecture(self._arch)
        self._console.push(arch=self._arch)
        self._diagram.build()
        self._update_all_tabs()

    def _save_session(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Session", "", "JSON files (*.json)")
        if not path:
            return
        Path(path).write_text(
            json.dumps(session_dict(self._arch), indent=2), encoding="utf-8")
        self._status.showMessage(f"Saved to {path}", 4000)

    def _open_session(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Session", "", "JSON files (*.json)")
        if not path:
            return
        try:
            load_session_dict(
                self._arch, json.loads(Path(path).read_text(encoding="utf-8")))
            self._diagram.build()
            self._update_all_tabs()
            self._refresh_status()
            self._status.showMessage(f"Loaded {path}", 4000)
        except Exception as exc:
            QMessageBox.critical(self, "Load error", str(exc))

    # ── Export ────────────────────────────────────────────────

    def _copy_report(self) -> None:
        """Put the full text report on the clipboard."""
        report = text_report(self._arch)
        QApplication.clipboard().setText(report)
        self._status.showMessage(
            f"Analysis report copied to clipboard ({len(report)} chars)", 5000)

    def _save_report(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save analysis report", "fakematlab-report.txt",
            "Text files (*.txt)")
        if not path:
            return
        Path(path).write_text(text_report(self._arch), encoding="utf-8")
        self._status.showMessage(f"Report written to {path}", 4000)

    def _export_plot_png(self) -> None:
        """Export the visible tab as a PNG."""
        widget = self._tabs.currentWidget()
        if widget is None:
            return
        default = f"fakematlab-{self._tabs.tabText(self._tabs.currentIndex())}.png"
        default = "".join(c for c in default if c.isalnum() or c in "-_.")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export tab as PNG", default, "PNG images (*.png)")
        if not path:
            return
        if widget.grab().save(path):
            self._status.showMessage(f"Image written to {path}", 4000)
        else:
            QMessageBox.warning(self, "Export failed",
                                f"Qt could not write {path}")

    # ── Presets ───────────────────────────────────────────────

    def _load_preset_G(self, tf: ctl.TransferFunction) -> None:
        self._arch.set_block("G", tf)
        self._arch.set_block("K2", unity())
        self._diagram.build()
        self._update_all_tabs()
        self._refresh_status()

    def _preset_first_order(self):  self._load_preset_G(first_order(1.0, 1.0))
    def _preset_so_under(self):     self._load_preset_G(second_order(1.0, 0.2, 2.0))
    def _preset_so_over(self):      self._load_preset_G(second_order(1.0, 2.0, 1.0))
    def _preset_double_int(self):   self._load_preset_G(ctl.TransferFunction([1],[1,0,0]))
    def _preset_unstable(self):     self._load_preset_G(ctl.TransferFunction([1],[1,-1]))
    def _preset_nmp(self):          self._load_preset_G(ctl.TransferFunction([-1,1],[1,1]))
    def _preset_satellite(self):    self._load_preset_G(ctl.TransferFunction([1],[1,0,0]))

    # ── About ────────────────────────────────────────────────

    def _show_about(self) -> None:
        QMessageBox.about(
            self, "About FakeMatlab",
            "FakeMatlab — Classical Control Workbench\n\n"
            "Built for the CLACO course (Master Automatique et Robotique).\n\n"
            "Stack: Python 3.12 · python-control · PySide6 · pyqtgraph · sympy\n\n"
            "Architecture: 2-DOF feedback + feedforward (ch.5)\n"
            "Analysis: Bode, Nyquist, Nichols, Routh, Root Locus,\n"
            "          step/impulse/ramp metrics, PID tuning (Z-N)."
        )


# ── Helpers ───────────────────────────────────────────────────

def _tf_short(tf: ctl.TransferFunction) -> str:
    """Very short string for status bar."""
    num = tf.num[0][0]
    den = tf.den[0][0]
    n = ", ".join(f"{c:.3g}" for c in num)
    d = ", ".join(f"{c:.3g}" for c in den)
    return f"[{n}]/[{d}]"
