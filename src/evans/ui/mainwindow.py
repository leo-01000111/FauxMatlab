r"""
Main application window.
========================

::

  ┌──────────────────────────────────────────────────────────┐
  │ ▣ File Export View …              Evans — …          ─ □ ✕ │  title bar
  ├──────────────────────────────────────────────────────────┤
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

The title bar (:mod:`.titlebar`) carries the menus. On Windows it replaces
the native caption while keeping the native frame (:mod:`.winframe`), so the
window still snaps, resizes and casts its shadow; View ▸ Integrated title bar
turns that off, and everywhere else the caption is the system's own.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import control as ctl
from PySide6.QtCore import QProcess, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..console.apps import AppRequest, set_app_sink
from ..core.architecture import CourseArchitecture
from ..core.collection import SnapshotStore, SystemCollection
from ..core.report import text_report
from ..core.session import load_session_dict, session_dict
from ..core.tf_utils import (
    first_order,
    second_order,
    unity,
)
from . import help, keys, persist, theme, winframe
from .apps import ControlSystemDesigner, LTIViewer, PIDTuner, SnapshotBar
from .block_editor import BlockEditor
from .console import ConsolePanel, FigureArea
from .context_bar import ContextBar
from .design import TIGHT
from .diagram.fixed_diagram import FixedDiagramView
from .panes import DEFAULT_LAYOUT, LAYOUTS, PANE_KINDS, PaneGrid, Source
from .persist import RecentFiles
from .sim.sim_tab import SimTab
from .tabs.modern import ModernTab
from .titlebar import TitleBar
from .updater import Updater
from .workspace import Workspace, WorkspaceStack


class MainWindow(QMainWindow):

    APP_TITLE = "Evans — Classical & Modern Control"

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
        self._app_docks: dict[str, QDockWidget] = {}
        #: Scripts and models opened or saved, for File ▸ Open recent.
        self.recent_files = RecentFiles()
        #: Unsaved scripts were settled for quitting; see `confirm_quit`.
        self._quit_confirmed = False
        # Before the menus: the title bar holds the menu bar they fill.
        self._title_bar = TitleBar(self)
        #: Help ▸ Check for updates; before the menus, which call it.
        self.updater = Updater(self)
        # Looked up at click time, not bound now, so the tests can patch them.
        self._title_bar.minimize_requested.connect(lambda: self.showMinimized())
        self._title_bar.maximize_requested.connect(
            lambda: self.toggle_maximized())
        self._title_bar.close_requested.connect(lambda: self.close())
        self.setMenuWidget(self._title_bar)
        self._native_frame = winframe.NativeFrame(self, self._title_bar)
        self._build_ui()
        self._build_menus()
        self._build_status_bar()
        self.updater.status.connect(self._status.showMessage)
        self.set_integrated_title_bar(
            persist.integrated_title_bar(default=winframe.supported()),
            remember=False)
        set_app_sink(self.open_app)

    # ── Title bar ─────────────────────────────────────────────

    def menuBar(self) -> QMenuBar:          # noqa: N802 (Qt API)
        """
        The menu bar inside the title bar.

        ``QMainWindow.menuBar()`` would make a new, empty one and put it in
        place of the title bar, since the menu widget is not a QMenuBar.
        """
        return self._title_bar.menu_bar

    @property
    def title_bar(self) -> TitleBar:
        return self._title_bar

    @property
    def integrated_title_bar(self) -> bool:
        """Whether the native caption is gone and our strip replaces it."""
        return self._title_bar.chrome_visible

    def toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def set_integrated_title_bar(self, on: bool, *, remember: bool = True
                                 ) -> bool:
        """
        Menus and window buttons in one strip, or the system's caption.

        Only on Windows; elsewhere, or if Windows refuses, the caption stays
        and the strip is a plain menu bar. ``remember`` keeps the choice for
        the next launch. Returns whether the strip is now integrated.
        """
        if remember:
            persist.set_integrated_title_bar(on)
        active = False
        if on:
            self._title_bar.set_chrome_visible(True)
            active = self._native_frame.install()
        if not active:
            self._native_frame.uninstall()
            self._title_bar.set_chrome_visible(False)
        action = getattr(self, "_act_title_bar", None)
        if action is not None:
            action.blockSignals(True)
            action.setChecked(on)
            action.blockSignals(False)
        return active

    def nativeEvent(self, event_type, message):   # noqa: N802 (Qt API)
        frame = getattr(self, "_native_frame", None)
        if frame is not None and frame.enabled:
            try:
                handled, result = frame.handle(int(message))
            except Exception:                       # noqa: BLE001
                # Never take the window down with us: stop handling at once,
                # and put the system caption back once this message is done.
                frame.enabled = False
                QTimer.singleShot(0, self._native_frame_failed)
                return False, 0
            if handled:
                return True, result
        return super().nativeEvent(event_type, message)

    def _native_frame_failed(self) -> None:
        self._native_frame.uninstall()
        self._title_bar.set_chrome_visible(False)
        self._status.showMessage(
            "The integrated title bar failed; using the system's instead",
            8000)

    # ── UI construction ───────────────────────────────────────

    def _build_ui(self) -> None:
        self._stack = WorkspaceStack()
        self.setCentralWidget(self._stack)
        self._stack.changed.connect(self._on_workspace_changed)
        self._stack.rail.help_requested.connect(help.open_help)

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
        self._sim_tab.linearised.connect(self._on_linearised)
        self._sim_tab.file_used.connect(self.recent_files.add)
        self._console.editor.file_used.connect(self.recent_files.add)

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

        # The pane grid *is* the analysis area. It used to sit beside a
        # second "Tabs" view of the same widgets; every workflow that view
        # held (System, Time, Frequency, ...) is now a pane kind, so nothing
        # is reachable only from a tab bar, and tuning stays a matter of
        # watching several views move together.
        self._grid = PaneGrid(self._arch, tab_factory=self._make_tab)
        main_lay.addWidget(self._wrap_grid(), stretch=1)
        self._sync_layout_buttons()

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
        self._sync_layout_buttons()
        self._status.showMessage(
            f"{count} analysis pane{'s' if count > 1 else ''}", 3000)

    def _sync_layout_buttons(self) -> None:
        for size, button in self._layout_buttons.items():
            button.blockSignals(True)
            button.setChecked(size == self._grid.count)
            button.blockSignals(False)

    def _make_tab(self, name: str, arch):
        """
        Which widget a pane gets when it asks for a whole workflow.

        Each pane owns its own instance (a widget lives in one place), so the
        signals that used to be wired once, at construction, are wired here,
        once per instance the grid creates.
        """
        from .tabs.design_tab import DesignTab
        from .tabs.frequency_tab import FrequencyTab
        from .tabs.performance_tab import PerformanceTab
        from .tabs.stability_tab import StabilityTab
        from .tabs.system_tab import SystemTab
        from .tabs.time_tab import TimeTab

        factory = {"system": SystemTab, "time": TimeTab,
                   "frequency": FrequencyTab, "stability": StabilityTab,
                   "performance": PerformanceTab, "design": DesignTab,
                   "modern": ModernTab}.get(name)
        if factory is None:
            return None
        widget = factory(arch)
        if name == "design":
            widget.controller_changed.connect(self._on_controller_designed)
        elif name == "modern":
            widget.ctx.status.connect(
                lambda m: self._status.showMessage(m, 6000))
            widget.model_sent_to_analysis.connect(
                self._on_modern_model_sent)
        return widget

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
        # Hidden on the Live tab: its figures are inline under their cells,
        # and a strip of the same figures below them only takes room.
        self._console.figure_area_wanted.connect(self._figures.setVisible)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        return split

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
        self._status.showMessage(f"{name} loaded as G(s)", 6000)

    def _on_console_model(self, name: str, model) -> None:
        """A Simulink model was double-clicked: open it on the canvas."""
        self._sim_tab._canvas.set_model(model)
        self._sim_tab._canvas.fit_all()
        self._stack.set_current(Workspace.MODEL)
        self._status.showMessage(f"{name} opened on the canvas", 6000)

    # ── Layout ───────────────────────────────────────────────

    #: Where `QSettings` keeps this window's layout.
    SETTINGS_ORG = "Evans"
    SETTINGS_APP = "Evans"

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
        settings.setValue("paneKeys", list(self._grid.keys))
        settings.setValue("paneSources",
                          [source.name for source in self._grid.sources])
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
        self._restore_panes(settings.value("paneKeys"),
                            settings.value("paneSources"))
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

    def _restore_panes(self, keys, sources) -> None:
        """
        Put the pane grid back: how many, what each shows, and of which system.

        Saved settings are untrusted input (an older build, a hand-edited
        key), so anything unrecognised is dropped and the grid keeps what it
        has rather than failing the whole restore.
        """
        if isinstance(keys, str):       # QSettings collapses 1-element lists
            keys = [keys]
        if isinstance(sources, str):
            sources = [sources]
        if not keys or len(keys) not in LAYOUTS:
            return
        known = {k.key for k in PANE_KINDS}
        if any(key not in known for key in keys):
            return
        chosen = []
        for name in list(sources or [])[:len(keys)]:
            chosen.append(Source[name] if name in Source.__members__ else None)
        self._grid.set_layout_size(len(keys), tuple(keys), tuple(chosen))
        self._sync_layout_buttons()

    def reset_layout(self) -> None:
        """
        Back to the defaults, and forget what was saved.

        A restored layout can become unusable — a dock dragged off-screen, a
        saved geometry from a monitor that is no longer attached. Without
        this, the only fix is deleting a registry key.
        """
        self._settings().clear()
        for dock in (self._model_dock, *self._app_docks.values()):
            dock.hide()
        self.removeDockWidget(self._model_dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, self._model_dock)
        self.resize(1400, 850)
        self._grid.set_layout_size(1, ("step",), (None,))
        self._sync_layout_buttons()
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

    def confirm_quit(self) -> bool:
        """
        Settle scripts with unsaved changes before Evans closes: save,
        discard or cancel each. False means stay open. Asked once, so a
        restart that asks first does not ask again as the window closes.
        """
        if not self._quit_confirmed:
            self._quit_confirmed = self._console.editor.confirm_close_all()
        return self._quit_confirmed

    def reopen_scripts(self) -> int:
        """The scripts open when Evans last closed, in their tabs again."""
        return self._console.editor.reopen_remembered()

    def closeEvent(self, event) -> None:
        if not self.confirm_quit():
            event.ignore()
            return
        self._console.editor.remember_open()
        self.save_layout()
        # "Update when I close Evans": the installer takes over from here.
        self.updater.install_pending()
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
        # These edit the architecture, so show the workspace their changes
        # land in — otherwise `sisotool(G)` typed in the console opens a panel
        # beside a page that is not showing what it changes.
        self._stack.set_current(Workspace.ANALYSE)
        return opener(request)

    #: Where each app docks, and what its dock is called.
    _APP_DOCKS = {
        "ltiview": ("LTI Viewer", Qt.RightDockWidgetArea),
        "sisotool": ("Control System Designer", Qt.RightDockWidgetArea),
        "pidtuner": ("PID Tuner", Qt.RightDockWidgetArea),
    }

    def _show(self, key: str, widget: QWidget) -> QWidget:
        """
        Dock the app, rather than opening a window.

        These were three parentless top-level windows. With the main window,
        and the model dock that made up to five independent
        surfaces, none of which remembered a position, all floating over a
        window that did not fit the screen. As docks they sit beside the
        analysis they are editing — which is the point of a designer whose
        changes go straight into the shared architecture.
        """
        self._apps[key] = widget
        dock = self._app_docks.get(key)
        if dock is None:
            title, area = self._APP_DOCKS[key]
            dock = QDockWidget(title, self)
            dock.setObjectName(f"{key}Dock")
            dock.setAllowedAreas(Qt.RightDockWidgetArea |
                                 Qt.LeftDockWidgetArea |
                                 Qt.BottomDockWidgetArea)
            # Scrolled. These apps were designed as ~1100 px windows, and a
            # dock adds its content's minimum to the window's — docking two
            # of them took the minimum width from 920 to 1634, undoing the
            # whole point of UI-1. The dock can now be any width and the app
            # scrolls inside it.
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            scroll.setWidget(widget)
            dock.setWidget(scroll)
            self.addDockWidget(area, dock)
            # Tab them together rather than stacking three narrow columns.
            siblings = [d for k, d in self._app_docks.items() if k != key]
            if siblings:
                self.tabifyDockWidget(siblings[-1], dock)
            self._app_docks[key] = dock
        else:
            # Only if it actually changed. `QScrollArea.setWidget` takes
            # ownership and deletes whatever was there, so handing it the
            # widget it already holds churns — and briefly leaves the app
            # parentless, which is to say a floating window.
            holder = dock.widget()
            if isinstance(holder, QScrollArea):
                if holder.widget() is not widget:
                    holder.setWidget(widget)
            elif holder is not widget:
                dock.setWidget(widget)

        dock.show()
        dock.raise_()
        self._status.showMessage(self._APP_DOCKS[key][0], 4000)
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
                baseline=self._arch.block_tf("K2"), kind=kind,
                sensor=self._arch.block_tf("H"),
                feedforward=self._arch.block_tf("K1"))
            tuner.controller_applied.connect(self._on_controller_designed)
        else:
            tuner.set_plant(systems.get("plant", self._arch.block_tf("G")),
                            self._arch.block_tf("K2"),
                            sensor=self._arch.block_tf("H"),
                            feedforward=self._arch.block_tf("K1"))
        return self._show("pidtuner", tuner)

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

    def _build_theme_menu(self) -> QMenu:
        """View ▸ Theme: System / Day / Night, one of them always checked."""
        menu = QMenu("&Theme", self)
        group = QActionGroup(self)
        group.setExclusive(True)
        self._theme_actions: dict[theme.Mode, QAction] = {}
        for mode, text, tip in (
            (theme.Mode.SYSTEM, "&System", "Follow the operating system"),
            (theme.Mode.DAY, "&Day", "Dry concrete: light ground, black ink"),
            (theme.Mode.NIGHT, "&Night", "Asphalt: dark ground, pale ink"),
        ):
            action = QAction(text, self, checkable=True, statusTip=tip)
            action.setChecked(theme.mode() is mode)
            action.triggered.connect(
                lambda _checked=False, m=mode: self.choose_theme(m))
            group.addAction(action)
            menu.addAction(action)
            self._theme_actions[mode] = action
        return menu

    def choose_theme(self, mode: theme.Mode) -> bool:
        """
        A theme picked from the menu: saved, then applied by a restart.

        The theme is not switched in place any more. Restyling every live
        widget and then dragging a splitter could hang the window, so the
        choice goes through a restart, after the user has had the chance to
        save their work. Returns whether a restart was started.
        """
        if mode is theme.mode():
            return False
        if not self._ask_theme_restart(mode):
            self._theme_actions[theme.mode()].setChecked(True)
            return False
        theme.save_mode(mode)
        return self._restart()

    def _ask_theme_restart(self, mode: theme.Mode) -> bool:
        """True for Restart. A method so tests can answer it."""
        t = theme.tokens()
        name = {theme.Mode.SYSTEM: "System", theme.Mode.DAY: "Day",
                theme.Mode.NIGHT: "Night"}[mode]
        box = QMessageBox(self)
        box.setWindowTitle("Change theme")
        box.setTextFormat(Qt.RichText)
        # Weight and colour set outright: the variable sign font ignored a
        # plain <b>, and this is the one phrase the dialog exists to say.
        box.setText(f"Changing to the {name} theme requires "
                    f'<span style="font-weight:800; color:{t.signal};">'
                    f"an app restart</span>.")
        box.setInformativeText(
            "Evans will close and open again. Unsaved models, scripts and "
            "figures are not kept, so save anything you need first.")
        restart = box.addButton("Restart", QMessageBox.AcceptRole)
        back = box.addButton("Go back and save work", QMessageBox.RejectRole)
        restart.setStyleSheet(
            f"QPushButton {{ background: {t.lamp_go}; color: #ffffff; "
            f"border: none; padding: 6px 16px; font-weight: 600; }}")
        back.setStyleSheet(
            f"QPushButton {{ background: {t.hold}; color: {t.on_hold}; "
            f"border: none; padding: 6px 16px; font-weight: 600; }}")
        for button in (restart, back):
            # The uppercase sign font sets "BACK AND" so tight it reads as
            # one word; a little more room between words.
            font = button.font()
            font.setWordSpacing(4)
            button.setFont(font)
        box.setDefaultButton(back)
        box.setEscapeButton(back)
        box.exec()
        return box.clickedButton() is restart

    def _restart(self) -> bool:
        """Start a new Evans with the same arguments, then close this one."""
        if not self.confirm_quit():
            return False
        if getattr(sys, "frozen", False):        # Evans.exe
            program, args = sys.executable, sys.argv[1:]
        else:                                     # python app.py / evans
            program = sys.executable
            args = [os.path.abspath(sys.argv[0]), *sys.argv[1:]]
        if not self._start_detached(program, args):
            QMessageBox.warning(
                self, "Change theme",
                "Evans could not start a new window. The theme is saved and "
                "applies the next time you open Evans.")
            return False
        self.close()
        QApplication.instance().quit()
        return True

    @staticmethod
    def _start_detached(program: str, args: list[str]) -> bool:
        """A method so tests can stop the real relaunch."""
        ok = QProcess.startDetached(program, args, os.getcwd())
        return bool(ok[0] if isinstance(ok, tuple) else ok)

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
        for a in [act_new, act_open, act_save, None]:
            if a is None:
                file_menu.addSeparator()
            else:
                file_menu.addAction(a)
        self._recent_menu = file_menu.addMenu("Open &recent")
        self._recent_menu.setToolTipsVisible(True)
        self._recent_menu.aboutToShow.connect(self._fill_recent_menu)
        self._fill_recent_menu()
        file_menu.addSeparator()
        file_menu.addAction(act_quit)

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
        # On a Mac ⌘` is the system's "next window of this app"; Control-`
        # (Qt's Meta there) is free, and is VS Code's terminal key on a Mac.
        console_shortcut.setShortcut("Meta+`" if keys.is_mac() else "Ctrl+`")
        console_shortcut.triggered.connect(
            lambda: self._stack.set_current(Workspace.CONSOLE))
        self.addAction(console_shortcut)

        view_menu.addSeparator()
        view_menu.addMenu(self._build_theme_menu())
        act_title_bar = QAction("Integrated &title bar", self, checkable=True)
        act_title_bar.setStatusTip(
            "Menus and window buttons in one strip (Windows)" if
            winframe.supported() else
            "Only on Windows; this system draws its own title bar")
        act_title_bar.setEnabled(winframe.supported())
        act_title_bar.triggered.connect(self.set_integrated_title_bar)
        self._act_title_bar = act_title_bar
        view_menu.addAction(act_title_bar)
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
        help_menu.addAction(QAction("Documentation", self, shortcut="F1",
                                     triggered=lambda: help.open_help()))
        help_menu.addSeparator()
        help_menu.addAction(QAction(
            "Check for &updates…", self,
            triggered=lambda: self.updater.check(),
            statusTip="Look for a newer Evans on GitHub"))
        act_auto_update = QAction("Check for updates &automatically", self,
                                  checkable=True)
        act_auto_update.setChecked(persist.update_auto_check())
        act_auto_update.setStatusTip("Once a day, a few seconds after launch")
        act_auto_update.triggered.connect(persist.set_update_auto_check)
        help_menu.addAction(act_auto_update)
        help_menu.addSeparator()
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
        self._grid.set_active_signal(signal_id)
        self._grid.refresh(self._arch)

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

    def _refresh_analyse(self) -> None:
        """Refresh every pane of the Analyse page."""
        self._grid.refresh(self._arch)

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

    def _fill_recent_menu(self) -> None:
        """
        List the recent scripts and models, newest first.

        Rebuilt each time the menu opens, so a file deleted since it was
        opened is simply not offered.
        """
        menu = self._recent_menu
        menu.clear()
        paths = self.recent_files.paths()
        for n, path in enumerate(paths, start=1):
            prefix = f"&{n}  " if n < 10 else f"{n}  "
            action = QAction(f"{prefix}{path.name}   —   {path.parent}", menu)
            action.setToolTip(str(path))
            action.triggered.connect(
                lambda _checked=False, p=path: self.open_recent(p))
            menu.addAction(action)
        if not paths:
            empty = QAction("No recent files", menu)
            empty.setEnabled(False)
            menu.addAction(empty)
        menu.addSeparator()
        clear = QAction("&Clear recent files", menu)
        clear.setEnabled(bool(paths))
        clear.triggered.connect(self.recent_files.clear)
        menu.addAction(clear)

    def open_recent(self, path: str | Path) -> bool:
        """
        Open a recent file where it belongs: a model on the Model canvas, a
        script in the Console's Script tab. Returns whether it opened.
        """
        path = Path(path)
        if not path.is_file():
            self.recent_files.paths()          # forgets it
            self._status.showMessage(f"{path} no longer exists", 6000)
            return False
        if path.suffix.lower() == ".fmdl":
            self._sim_tab.load_model(path)
            self._stack.set_current(Workspace.MODEL)
        else:
            try:
                self._console.editor.load_file(path)
            except (OSError, UnicodeDecodeError) as exc:
                QMessageBox.critical(self, "Open error", str(exc))
                return False
            self._stack.set_current(Workspace.CONSOLE)
            self._console.show_script()
        return True

    # ── Export ────────────────────────────────────────────────

    def _copy_report(self) -> None:
        """Put the full text report on the clipboard."""
        report = text_report(self._arch)
        QApplication.clipboard().setText(report)
        self._status.showMessage(
            f"Analysis report copied to clipboard ({len(report)} chars)", 5000)

    def _save_report(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save analysis report", "evans-report.txt",
            "Text files (*.txt)")
        if not path:
            return
        Path(path).write_text(text_report(self._arch), encoding="utf-8")
        self._status.showMessage(f"Report written to {path}", 4000)

    def _export_plot_png(self) -> None:
        """Export the analysis pane grid as a PNG."""
        widget = self._grid
        path, _ = QFileDialog.getSaveFileName(
            self, "Export analysis as PNG", "evans-analysis.png",
            "PNG images (*.png)")
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
            self, "About Evans",
            "Evans — Classical & Modern Control\n\n"
            "Built for the CLACO course (Master Automatique et Robotique).\n\n"
            "Stack: Python 3.12 · python-control · PySide6 · pyqtgraph · sympy\n\n"
            "Architecture: 2-DOF feedback + feedforward (ch.5)\n"
            "Analysis: Bode, Nyquist, Nichols, Routh, Root Locus,\n"
            "          step/impulse/ramp metrics, PID tuning (Z-N).\n\n"
            "Named after Walter R. Evans, who invented the root locus.\n\n"
            "MATLAB and Simulink are registered trademarks of The MathWorks, Inc. Evans is an independent project, not affiliated with or endorsed by MathWorks."
        )


# ── Helpers ───────────────────────────────────────────────────

def _tf_short(tf: ctl.TransferFunction) -> str:
    """Very short string for status bar."""
    num = tf.num[0][0]
    den = tf.den[0][0]
    n = ", ".join(f"{c:.3g}" for c in num)
    d = ", ".join(f"{c:.3g}" for c in den)
    return f"[{n}]/[{d}]"
