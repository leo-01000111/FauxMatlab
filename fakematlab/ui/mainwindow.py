"""
Main application window.
========================
Layout:
  ┌──────────────────┬────────────────────────────────────────┐
  │  [Diagram view]  │  [Tab: System|Time|Freq|Stab|Perf|Design]│
  │                  │                                        │
  ├──────────────────┤                                        │
  │  [Block editor]  │                                        │
  └──────────────────┴────────────────────────────────────────┘

The left panel (diagram + editor) is fixed-width; the right panel
takes the remaining space. A QSplitter lets the user resize.
"""

from __future__ import annotations

import json
from pathlib import Path

import control as ctl
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
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
from .console import ConsoleDock, FigureDock
from .diagram.fixed_diagram import FixedDiagramView
from .lesson_dock import LessonDock
from .sim.sim_tab import SimTab
from .tabs.design_tab import DesignTab
from .tabs.frequency_tab import FrequencyTab
from .tabs.modern import ModernTab
from .tabs.performance_tab import PerformanceTab
from .tabs.stability_tab import StabilityTab
from .tabs.system_tab import SystemTab
from .tabs.time_tab import TimeTab


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

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_lay = QHBoxLayout(central)
        main_lay.setContentsMargins(4, 4, 4, 4)
        main_lay.setSpacing(4)

        outer_splitter = QSplitter(Qt.Horizontal)

        # ── Left panel ──
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(4)
        # The diagram is inherently wide and short (roughly 3.3:1), so a narrow
        # column renders it tiny with a tall band of empty space underneath.
        # Give the panel room, and cap the diagram's height so the space it
        # cannot use goes to the block editor instead.
        left.setMinimumWidth(420)
        left.setMaximumWidth(760)

        self._diagram = FixedDiagramView(self._arch)
        self._diagram.setMinimumHeight(150)
        self._diagram.setMaximumHeight(260)
        left_lay.addWidget(self._diagram, stretch=0)

        self._editor = BlockEditor()
        left_lay.addWidget(self._editor, stretch=1)

        outer_splitter.addWidget(left)

        # ── Right panel: the snapshot bar over the tabs ──
        #
        # The bar lives here rather than inside a tab because a snapshot is of
        # the whole architecture, not of whatever panel happens to be open —
        # taking one on the Frequency tab and restoring it on the Time tab is
        # the point.
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(4)

        self._snapshot_bar = SnapshotBar(self._arch, self.snapshots)
        self._snapshot_bar.restored.connect(self._on_snapshot_restored)
        self._snapshot_bar.compare_requested.connect(self._compare_snapshots)
        right_lay.addWidget(self._snapshot_bar)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        self._sys_tab  = SystemTab(self._arch)
        self._time_tab = TimeTab(self._arch)
        self._freq_tab = FrequencyTab(self._arch)
        self._stab_tab = StabilityTab(self._arch)
        self._perf_tab = PerformanceTab(self._arch)
        self._des_tab  = DesignTab(self._arch)
        self._sim_tab  = SimTab()
        self._mod_tab  = ModernTab(self._arch)

        self._tabs.addTab(self._sys_tab,  "🔬 System")
        self._tabs.addTab(self._time_tab, "⏱ Time")
        self._tabs.addTab(self._freq_tab, "〜 Frequency")
        self._tabs.addTab(self._stab_tab, "🔒 Stability")
        self._tabs.addTab(self._perf_tab, "📊 Performance")
        self._tabs.addTab(self._des_tab,  "🎛 Design")
        self._tabs.addTab(self._sim_tab,  "⛓ Simulink")
        self._tabs.addTab(self._mod_tab,  "▦ Modern")

        right_lay.addWidget(self._tabs, stretch=1)
        outer_splitter.addWidget(right)
        outer_splitter.setStretchFactor(0, 1)
        outer_splitter.setStretchFactor(1, 3)

        main_lay.addWidget(outer_splitter)

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

    # ── Docks ────────────────────────────────────────────────

    def _build_docks(self) -> None:
        """
        The command window and the figure area.

        Both start hidden: the app opens on the analysis tabs, and a console
        nobody asked for would take a third of the window on first launch.
        View ▸ Command Window (Ctrl+`) brings it up.
        """
        self._figures = FigureDock(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self._figures)
        self._figures.hide()

        self._console = ConsoleDock(self._figures, extra=self._console_state())
        self.addDockWidget(Qt.BottomDockWidgetArea, self._console)
        self._console.hide()

        self._console.open_system.connect(self._on_console_system)
        self._console.open_model.connect(self._on_console_model)

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
        self._tabs.setCurrentWidget(self._sys_tab)
        self._status.showMessage(f"{name} loaded as G(s)", 6000)

    def _on_console_model(self, name: str, model) -> None:
        """A Simulink model was double-clicked: open it on the canvas."""
        self._sim_tab._canvas.set_model(model)
        self._sim_tab._canvas.fit_all()
        self._tabs.setCurrentWidget(self._sim_tab)
        self._status.showMessage(f"{name} opened on the canvas", 6000)

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

        tab = getattr(self, self._TAB_BY_NAME.get(lesson.tab, "_sys_tab"), None)
        if tab is not None:
            self._tabs.setCurrentWidget(tab)
        self._update_all_tabs()

        self._lessons.show_lesson(lesson, self._arch)
        self._status.showMessage(
            f"Chapter {lesson.chapter}: {lesson.title}  "
            f"({lesson.slides})", 10000)

    def _run_lesson_snippet(self, commands: tuple[str, ...]) -> None:
        """Send a lesson's snippet to the console, one line at a time."""
        self._act_console.setChecked(True)
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
        act_console = QAction("&Command Window", self, checkable=True)
        act_console.setShortcut("Ctrl+`")
        act_console.toggled.connect(self._toggle_console)
        self._act_console = act_console
        view_menu.addAction(act_console)
        act_figures = QAction("&Figures", self, checkable=True)
        act_figures.toggled.connect(
            lambda on: self._figures.setVisible(on))
        view_menu.addAction(act_figures)
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
        self._arch_label = QLabel("Architecture: G=1/(s+1)  K₂=1")
        self._status.addWidget(self._arch_label)

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
        tab_widgets = [
            self._sys_tab, self._time_tab, self._freq_tab,
            self._stab_tab, self._perf_tab, self._des_tab, self._sim_tab,
            self._mod_tab,
        ]
        if 0 <= idx < len(tab_widgets):
            tab_widgets[idx].refresh(arch)

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
        self._tabs.setCurrentWidget(self._sys_tab)
        self._status.showMessage(
            "Linearised model loaded as G(s) — " +
            description.splitlines()[0], 8000)

    # ── Full refresh ──────────────────────────────────────────

    def _update_all_tabs(self) -> None:
        """Refresh only the currently visible tab immediately; others lazily."""
        idx = self._tabs.currentIndex()
        self._on_tab_changed(idx)

    def _toggle_console(self, visible: bool) -> None:
        self._console.setVisible(visible)
        if visible:
            self._console.focus()

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
        self._act_console.setChecked(True)
        self._status.showMessage(
            "G, K2, L, T, arch and model are now in the workspace", 6000)

    def _refresh_status(self) -> None:
        G_str  = _tf_short(self._arch.block_tf("G"))
        K2_str = _tf_short(self._arch.block_tf("K2"))
        self._arch_label.setText(f"G={G_str}   K₂={K2_str}")

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
