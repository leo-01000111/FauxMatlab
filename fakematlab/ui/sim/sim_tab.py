"""
The Simulink tab: palette · canvas · scope, plus a run toolbar.

The run happens on a worker thread. A stiff model or a long run can take
seconds, and a frozen window during a simulation is indistinguishable from a
crashed one — so the UI stays live, shows progress, and can be cancelled.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ...sim.compile import CompileError
from ...sim.linearize import LinearizationError, linearize, steady_state
from ...sim.model import ModelError, PortRef, SimModel
from ...sim.solver import FIXED_STEP, SimulationError, simulate
from ..design import NORMAL, TIGHT
from ..guard import GuardedPanel, guard
from .canvas import SimCanvas
from .inspector import BlockInspector
from .palette import BlockPalette
from .scope import ScopeWidget


class _Worker(QObject):
    """Runs one simulation off the GUI thread."""

    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(float)

    def __init__(self, model: SimModel, options: dict) -> None:
        super().__init__()
        self.model = model
        self.options = options
        self.cancelled = False

    def run(self) -> None:
        def tick(fraction: float) -> None:
            self.progress.emit(fraction)
            if self.cancelled:
                raise SimulationError("cancelled")

        try:
            self.finished.emit(simulate(self.model, progress=tick,
                                        **self.options))
        except (SimulationError, CompileError, ModelError, ValueError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:                       # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")


def _labelled(text: str, control: QWidget) -> QWidget:
    """A toolbar-sized ``label [control]`` pair that can be hidden as a unit."""
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(TIGHT, 0, 0, 0)
    row.setSpacing(TIGHT)
    caption = QLabel(text)
    caption.setStyleSheet("color: palette(mid);")
    row.addWidget(caption)
    row.addWidget(control)
    return holder


class SimTab(QWidget, GuardedPanel):
    """Model, run, inspect."""

    #: Emitted when the user linearises a model — the analysis tabs pick it up.
    linearised = Signal(object, str)       # TransferFunction, description

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _Worker | None = None
        self._result = None
        self._build_ui()
        self._load_default_model()

    # ── UI ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)
        self.install_error_banner(root)
        root.addWidget(self._build_toolbar())

        splitter = QSplitter(Qt.Horizontal)

        self._palette = BlockPalette()
        # A *preferred* width, not a floor. A 180 px minimum here was one
        # of the constraints that stopped the window being narrowed.
        self._palette.setMinimumWidth(0)
        self._palette.setMaximumWidth(280)
        splitter.addWidget(self._palette)

        centre = QSplitter(Qt.Vertical)
        self._canvas = SimCanvas()
        centre.addWidget(self._canvas)
        self._scope = ScopeWidget()
        centre.addWidget(self._scope)
        centre.setStretchFactor(0, 3)
        centre.setStretchFactor(1, 2)
        splitter.addWidget(centre)

        # The inspector, so parameters can be edited with the diagram still
        # visible. They used to be a modal dialog on double-click: you could
        # not see the block you were editing, or compare two of them.
        self._inspector = BlockInspector()
        self._inspector.setMinimumWidth(0)
        self._inspector.setMaximumWidth(340)
        splitter.addWidget(self._inspector)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter, stretch=1)

        # A standing hint. The wiring gesture was discoverable only by
        # succeeding at it, and the status line said how *after* you clicked.
        self._hint = QLabel(
            "Drag between two ports to wire them, or click one port and then "
            "the other. Drag on empty canvas to select. Double-click a block "
            "for its parameters.")
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: palette(mid);")
        root.addWidget(self._hint)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._palette.block_chosen.connect(self._canvas.add_block)
        self._canvas.status.connect(self._status.setText)
        self._canvas.model_changed.connect(self._on_model_changed)
        self._canvas.path_changed.connect(self._on_path_changed)
        self._canvas.selection_changed.connect(self._on_block_selected)
        self._inspector.apply_requested.connect(self._apply_params)

    def _build_toolbar(self) -> QWidget:
        """
        A real ``QToolBar``, which is the whole point.

        This used to be one ``QHBoxLayout`` holding Run, Stop, stop time,
        solver, step, undo, redo, fit, up, a breadcrumb, Linearise, a progress
        bar and two file buttons — in a row that could not wrap. It demanded
        **1602 px**, and because a tab bar is as wide as its widest tab, that
        one row set the minimum width of the entire application at 2038 px:
        wider than a 1920 monitor, for someone who only wanted a Bode plot.

        A toolbar with ``setMovable(False)`` and overflow puts whatever does
        not fit behind a ``»`` button instead of pushing the window wider.
        Groups are separated the way the plan describes: run, settings,
        history, navigation, bridge, file.
        """
        bar = QToolBar()
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setIconSize(QSize(16, 16))
        bar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        # ── run ──
        self._run_btn = QPushButton("▶ Run")
        self._run_btn.setShortcut("Ctrl+R")
        self._run_btn.setToolTip("Run the simulation (Ctrl+R)")
        self._run_btn.clicked.connect(self.run_simulation)
        bar.addWidget(self._run_btn)

        self._stop_btn = QPushButton("■ Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.setToolTip("Cancel the running simulation")
        self._stop_btn.clicked.connect(self._cancel)
        bar.addWidget(self._stop_btn)
        bar.addSeparator()

        # ── simulation settings ──
        self._t_end = QDoubleSpinBox()
        self._t_end.setRange(1e-3, 1e6)
        self._t_end.setValue(10.0)
        self._t_end.setDecimals(3)
        self._t_end.setAccessibleName("stop time")
        self._t_end.setToolTip("Stop time (s)")
        bar.addWidget(_labelled("Stop", self._t_end))

        self._solver = QComboBox()
        self._solver.addItems(["RK45", "LSODA", "Radau", "BDF", "DOP853",
                               "ode4", "ode1"])
        self._solver.setAccessibleName("solver")
        self._solver.setToolTip(
            "RK45 is a good default. Radau or BDF for stiff models "
            "(widely separated time constants). ode4/ode1 are fixed-step, for "
            "matching what an embedded controller will do.")
        bar.addWidget(_labelled("Solver", self._solver))

        self._step = QDoubleSpinBox()
        self._step.setRange(0.0, 1e3)
        self._step.setDecimals(5)
        self._step.setValue(0.0)
        self._step.setSpecialValueText("auto")
        self._step.setAccessibleName("maximum step")
        self._step.setToolTip(
            "Maximum step; required for the fixed-step solvers.")
        bar.addWidget(_labelled("Step", self._step))
        bar.addSeparator()

        # ── history and canvas navigation ──
        undo = bar.addAction("↶")
        undo.setToolTip("Undo (Ctrl+Z)")
        undo.setShortcut("Ctrl+Z")
        undo.triggered.connect(lambda: self._canvas.undo_stack.undo())
        redo = bar.addAction("↷")
        redo.setToolTip("Redo (Ctrl+Y)")
        redo.setShortcut("Ctrl+Y")
        redo.triggered.connect(lambda: self._canvas.undo_stack.redo())
        fit = bar.addAction("Fit")
        fit.setToolTip("Fit the whole diagram in view")
        fit.triggered.connect(lambda: self._canvas.fit_all())
        bar.addSeparator()

        for label, tip, slot in (
            ("Align ↔", "Align the selected blocks on one row",
             lambda: self._align("y")),
            ("Align ↕", "Align the selected blocks in one column",
             lambda: self._align("x")),
            ("Space ↔", "Space the selected blocks evenly across",
             lambda: self._distribute("x")),
        ):
            action = bar.addAction(label)
            action.setToolTip(tip)
            action.triggered.connect(slot)
        bar.addSeparator()

        # ── subsystem navigation ──
        self._up_action = bar.addAction("↑ Up")
        self._up_action.setToolTip("Leave this subsystem (Esc)")
        self._up_action.triggered.connect(lambda: self._canvas.ascend())
        self._up_action.setVisible(False)

        self._crumb = QLabel("")
        self._crumb.setStyleSheet("color: palette(mid);")
        bar.addWidget(self._crumb)
        bar.addSeparator()

        # ── the bridge to the analysis tabs ──
        lin = bar.addAction("Linearise →")
        lin.setToolTip("Linearise the model and send it to the analysis tabs")
        lin.triggered.connect(self.linearise)
        bar.addSeparator()

        for label, slot, tip in (
            ("Open…", self.open_model, "Open a .fmdl model"),
            ("Save…", self.save_model, "Save this model as .fmdl"),
        ):
            action = bar.addAction(label)
            action.setToolTip(tip)
            action.triggered.connect(slot)

        # The progress bar lives outside the toolbar: it appears and vanishes,
        # and a toolbar that reflows every time a simulation starts is worse
        # than one that does not.
        self._progress = QProgressBar()
        self._progress.setMaximumWidth(160)
        self._progress.setVisible(False)

        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(NORMAL)
        row.addWidget(bar, stretch=1)
        row.addWidget(self._progress)
        self._toolbar = bar
        return wrapper

    # ── inspector ───────────────────────────────────────────────

    def _on_block_selected(self, item) -> None:
        self._inspector.show_block(item.block if item is not None else None)

    def _apply_params(self, block_id: str, changes: dict) -> None:
        """Route the inspector's edit through the canvas's undo stack."""
        from . import commands as cmd

        self._canvas.undo_stack.push(
            cmd.SetParams(self._canvas, block_id, changes))

    # ── arranging ───────────────────────────────────────────────

    def _align(self, axis: str) -> None:
        self._canvas.align_selection(axis)

    def _distribute(self, axis: str) -> None:
        self._canvas.distribute_selection(axis)

    # ── default model ───────────────────────────────────────────

    def _load_default_model(self) -> None:
        """Start on the course architecture rather than a blank sheet."""
        self._canvas.set_model(course_loop())
        self._canvas.fit_all()

    # ── running ─────────────────────────────────────────────────

    @guard("Simulation")
    def run_simulation(self) -> None:
        if self._thread is not None:
            return
        problem = self._canvas.validate()
        if problem and "Algebraic loop" not in problem:
            raise CompileError(problem)

        solver = self._solver.currentText()
        step = self._step.value()
        if solver in FIXED_STEP and step <= 0:
            raise SimulationError(
                f"{solver} is a fixed-step solver, so it needs an explicit "
                f"step size — set 'Step' to something below your fastest time "
                f"constant.")

        options = {
            "t_end": self._t_end.value(),
            "solver": solver,
            "max_step": step if step > 0 else None,
            "n_points": 2000,
        }

        self._worker = _Worker(self._canvas.root_model().copy(), options)
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.progress.connect(self._on_progress)

        self._run_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._status.setText("Running…")
        self._thread.start()

    def _on_progress(self, fraction: float) -> None:
        self._progress.setValue(int(fraction * 100))

    def _on_finished(self, result) -> None:
        self._teardown_thread()
        self._result = result
        self._scope.show_result(result)
        note = f"Done — {len(result.t)} samples, {result.solver}"
        if result.warnings:
            note += "   ⚠ " + result.warnings[0].splitlines()[0]
        self._status.setText(note)

    def _on_failed(self, message: str) -> None:
        self._teardown_thread()
        if message == "cancelled":
            self._status.setText("Cancelled.")
            return
        self.report_error("Simulation", SimulationError(message))
        self._status.setText("")

    def _cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancelled = True

    def _teardown_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
            self._thread = None
        self._worker = None
        self._run_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._progress.setVisible(False)

    # ── linearise ───────────────────────────────────────────────

    @guard("Linearisation")
    def linearise(self) -> None:
        """
        Linearise the model and hand the result to the analysis tabs.

        Input and output are taken from the selected blocks when two are
        selected, and guessed from the model otherwise.
        """
        model = self._canvas.root_model()
        in_port, out_port = self._linearisation_ports(model)

        try:
            point = steady_state(model)
        except LinearizationError:
            point = None                       # fall back to the initial state

        result = linearize(model, in_port, out_port, operating_point=point)
        self.linearised.emit(result.transfer_function(), result.summary())
        self._status.setText(result.summary().replace("\n", "   "))

    def _linearisation_ports(self, model: SimModel) -> tuple[str, str]:
        """
        Decide what to perturb and what to measure.

        If exactly two blocks are selected, the earlier one's input port and
        the later one's output port are used — an explicit choice always wins.
        Otherwise: perturb wherever the first source block drives (so the
        source's own value stays the operating point rather than becoming the
        perturbation), and measure the last block that is neither a source nor
        a sink, which for a control loop is the plant.
        """
        selected = [item.block_id for item in self._canvas.scene().selectedItems()
                    if hasattr(item, "block_id") and hasattr(item, "block")]
        if len(selected) == 2:
            first, second = selected
            in_block, out_block = model.block(first), model.block(second)
            if in_block.inputs and out_block.outputs:
                return (f"{first}.{in_block.inputs[0]}",
                        f"{second}.{out_block.outputs[0]}")

        driven = None
        for block in model:
            if block.category != "Sources" or not block.outputs:
                continue
            wires = model.connections_from(PortRef(block.block_id,
                                                   block.outputs[0]))
            if wires:
                driven = str(wires[0].dst)
                break
        if driven is None:
            raise LinearizationError(
                "could not find an input to perturb. Connect a source block, "
                "or select the input block and the output block (in that "
                "order) and try again.")

        target = None
        for block in model:
            if block.outputs and block.category not in ("Sources", "Sinks"):
                target = f"{block.block_id}.{block.outputs[0]}"
        if target is None:
            raise LinearizationError("could not find an output to measure")
        return driven, target

    # ── files ───────────────────────────────────────────────────

    @guard("Open model")
    def open_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open model", "", "FakeMatlab models (*.fmdl *.json)")
        if not path:
            return
        self._canvas.set_model(SimModel.load(path))
        self._canvas.fit_all()
        self._scope.clear()
        self._status.setText(f"Loaded {path}")

    @guard("Save model")
    def save_model(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save model", f"{self._canvas.root_model().name}.fmdl",
            "FakeMatlab models (*.fmdl)")
        if not path:
            return
        self._canvas.root_model().save(path)
        self._status.setText(f"Saved {path}")

    # ── misc ────────────────────────────────────────────────────

    def _on_path_changed(self, crumbs: list) -> None:
        inside = len(crumbs) > 1
        self._up_action.setVisible(inside)
        self._crumb.setText(" ▸ ".join(crumbs) if inside else "")

    def _on_model_changed(self) -> None:
        problem = self._canvas.validate()
        if problem:
            self._status.setText(problem.splitlines()[0])

    def refresh(self, arch=None) -> None:
        """Called when the tab is shown; nothing to recompute."""


# ──────────────────────────────────────────────────────────────
#  Starter model
# ──────────────────────────────────────────────────────────────

def course_loop() -> SimModel:
    """
    The ch.5 architecture, laid out left to right.

    Opening on a working loop rather than an empty canvas means the first
    thing anyone does is press Run and see a step response.
    """
    m = SimModel("course loop")
    m.add("Step", "r", x=-320, y=0, step_time=0.0)
    m.add("Sum", "e", x=-180, y=0, signs="+-")
    m.add("PID", "K2", x=-40, y=0, Kp=2.0, Ki=1.0)
    m.add("TransferFcn", "G", x=120, y=0, num="1", den="1, 1, 0")
    m.add("Scope", "scope", x=280, y=0, n_inputs=2, title="Loop")

    m.connect("r", "e.in1")
    m.connect("e", "K2")
    m.connect("K2", "G")
    m.connect("G", "e.in2")
    m.connect("G", "scope.in1")
    m.connect("K2", "scope.in2")
    return m
