"""
The Simulink canvas: editing, undo/redo, validation and the analysis bridge.

These drive the widgets directly rather than synthesising mouse events, so
they test the logic that a click would reach without depending on hit-testing
geometry. Wire *creation* is exercised through the same path the mouse uses
(``_start_wire`` / ``_finish_wire``), because that is where the interesting
rules live.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", reason="Qt not available")

import control as ctl
from PySide6.QtWidgets import QApplication

from fakematlab.sim.model import SimModel
from fakematlab.ui.sim.canvas import SimCanvas
from fakematlab.ui.sim.palette import BlockPalette
from fakematlab.ui.sim.sim_tab import SimTab, course_loop


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def canvas(app):
    view = SimCanvas(course_loop())
    yield view
    view.deleteLater()


# ──────────────────────────────────────────────────────────────
#  Model ↔ scene
# ──────────────────────────────────────────────────────────────

def test_canvas_draws_the_whole_model(canvas):
    assert len(canvas._blocks) == len(canvas.model)
    assert len(canvas._wires) == len(canvas.model.connections)
    for block_id in canvas.model.blocks:
        assert block_id in canvas._blocks


def test_default_model_is_valid(canvas):
    """The starter model must compile cleanly — it is the first impression."""
    assert canvas.validate() == ""


def test_adding_a_block_updates_model_and_scene(canvas):
    before = len(canvas.model)
    canvas.add_block("Gain")
    assert len(canvas.model) == before + 1
    assert len(canvas._blocks) == before + 1


def test_undo_and_redo_restore_the_model(canvas):
    before = len(canvas.model)
    canvas.add_block("Saturation")
    assert len(canvas.model) == before + 1

    canvas.undo_stack.undo()
    assert len(canvas.model) == before
    assert len(canvas._blocks) == before

    canvas.undo_stack.redo()
    assert len(canvas.model) == before + 1
    assert len(canvas._blocks) == before + 1


def test_deleting_a_block_removes_its_wires(canvas):
    wires_before = len(canvas.model.connections)
    canvas._blocks["G"].setSelected(True)
    canvas.delete_selection()

    assert "G" not in canvas.model.blocks
    assert len(canvas.model.connections) < wires_before
    assert all("G" not in (c.src.block, c.dst.block)
               for c in canvas.model.connections)

    canvas.undo_stack.undo()
    assert "G" in canvas.model.blocks
    assert len(canvas.model.connections) == wires_before


def test_moving_a_block_is_undoable(canvas):
    original = canvas.model.placement("G").x
    canvas._on_block_moved("G", original + 100.0, 0.0)
    assert canvas.model.placement("G").x == original + 100.0
    canvas.undo_stack.undo()
    assert canvas.model.placement("G").x == original


# ──────────────────────────────────────────────────────────────
#  Wiring rules
# ──────────────────────────────────────────────────────────────

def test_wiring_two_ports_connects_them(canvas):
    canvas.add_block("Gain")
    gain_id = [b for b in canvas.model.blocks if b.startswith("Gain")][0]
    canvas.model.remove("scope")
    canvas.rebuild()

    before = len(canvas.model.connections)
    canvas._start_wire(canvas._blocks["K2"].ports[("out", False)])
    canvas._finish_wire(canvas._blocks[gain_id].ports[("in", True)])
    canvas._cancel_wire()

    assert len(canvas.model.connections) == before + 1
    assert any(str(c.src) == "K2.out" and str(c.dst) == f"{gain_id}.in"
               for c in canvas.model.connections)


def test_cannot_wire_two_outputs(canvas):
    messages = []
    canvas.status.connect(messages.append)
    before = len(canvas.model.connections)

    canvas._start_wire(canvas._blocks["K2"].ports[("out", False)])
    canvas._finish_wire(canvas._blocks["G"].ports[("out", False)])
    canvas._cancel_wire()

    assert len(canvas.model.connections) == before
    assert any("output" in m for m in messages)


def test_cannot_wire_an_already_driven_input(canvas):
    messages = []
    canvas.status.connect(messages.append)
    before = len(canvas.model.connections)

    # G.in is already driven by K2.
    canvas._start_wire(canvas._blocks["r"].ports[("out", False)])
    canvas._finish_wire(canvas._blocks["G"].ports[("in", True)])
    canvas._cancel_wire()

    assert len(canvas.model.connections) == before
    assert any("already has a wire" in m for m in messages)


def test_escape_cancels_a_pending_wire(canvas):
    canvas._start_wire(canvas._blocks["K2"].ports[("out", False)])
    assert canvas._pending_port is not None
    canvas._cancel_wire()
    assert canvas._pending_port is None
    assert canvas._rubber_wire is None


# ──────────────────────────────────────────────────────────────
#  Validation feedback
# ──────────────────────────────────────────────────────────────

def test_an_algebraic_loop_is_flagged_on_the_offending_blocks(app):
    model = SimModel("loop")
    model.add("Step", "r", step_time=0.0)
    model.add("Sum", "s", signs="+-")
    model.add("Gain", "k", gain=0.5)
    model.connect("r", "s.in1")
    model.connect("s", "k")
    model.connect("k", "s.in2")

    view = SimCanvas(model)
    message = view.validate()
    assert "Algebraic loop" in message
    assert view._blocks["s"]._error
    assert view._blocks["k"]._error
    # The source is not part of the cycle and must not be blamed.
    assert not view._blocks["r"]._error
    view.deleteLater()


def test_a_valid_model_clears_error_marks(canvas):
    for item in canvas._blocks.values():
        item.set_error("boom")
    canvas.validate()
    assert all(not item._error for item in canvas._blocks.values())


# ──────────────────────────────────────────────────────────────
#  Clipboard
# ──────────────────────────────────────────────────────────────

def test_copy_and_paste_duplicates_blocks_and_internal_wires(canvas):
    canvas._blocks["K2"].setSelected(True)
    canvas._blocks["G"].setSelected(True)
    canvas.copy_selection()

    blocks_before = len(canvas.model)
    wires_before = len(canvas.model.connections)
    canvas.paste()

    assert len(canvas.model) == blocks_before + 2
    # K2 → G lay wholly inside the selection, so it is reproduced.
    assert len(canvas.model.connections) == wires_before + 1

    canvas.undo_stack.undo()
    assert len(canvas.model) == blocks_before


def test_paste_ignores_clipboard_junk(canvas):
    QApplication.clipboard().setText("not a model")
    before = len(canvas.model)
    canvas.paste()
    assert len(canvas.model) == before


# ──────────────────────────────────────────────────────────────
#  Palette
# ──────────────────────────────────────────────────────────────

def test_palette_lists_every_block(app):
    from fakematlab.sim.block import block_types

    palette = BlockPalette()
    listed = set()
    for i in range(palette._tree.topLevelItemCount()):
        group = palette._tree.topLevelItem(i)
        for j in range(group.childCount()):
            listed.add(group.child(j).text(0))
    assert listed == set(block_types())
    palette.deleteLater()


def test_palette_filter_narrows_the_list(app):
    palette = BlockPalette()
    palette._filter.setText("delay")
    visible = []
    for i in range(palette._tree.topLevelItemCount()):
        group = palette._tree.topLevelItem(i)
        for j in range(group.childCount()):
            child = group.child(j)
            if not child.isHidden():
                visible.append(child.text(0))
    assert "UnitDelay" in visible
    assert "TransportDelay" in visible
    assert "Gain" not in visible
    palette.deleteLater()


# ──────────────────────────────────────────────────────────────
#  The tab, and the bridge to the analysis half
# ──────────────────────────────────────────────────────────────

def test_sim_tab_opens_on_a_runnable_model(app):
    tab = SimTab()
    assert len(tab._canvas.model) > 0
    assert tab._canvas.validate() == ""
    assert not tab._error_banner.has_error
    tab.deleteLater()


def test_sim_tab_linearises_and_emits(app):
    """
    Pressing "Linearise" must produce the transfer function the exact algebra
    gives for the same loop — this is the bridge between the two halves.
    """
    tab = SimTab()
    model = SimModel("lin")
    model.add("Constant", "r", value=0.0)
    model.add("Sum", "e", signs="+-")
    model.add("TransferFcn", "K2", num="2, 1", den="1, 0")
    model.add("TransferFcn", "G", num="1", den="1, 1")
    model.connect("r", "e.in1")
    model.connect("e", "K2")
    model.connect("K2", "G")
    model.connect("G", "e.in2")
    tab._canvas.set_model(model)

    received = []
    tab.linearised.connect(lambda tf, desc: received.append(tf))
    tab.linearise()

    assert not tab._error_banner.has_error, tab._error_banner.message
    assert len(received) == 1

    exact = ctl.feedback(ctl.tf([2, 1], [1, 0]) * ctl.tf([1], [1, 1]), 1)
    assert np.allclose(np.sort(ctl.poles(received[0])),
                       np.sort(ctl.poles(exact)), atol=1e-5)
    tab.deleteLater()


def test_fixed_step_solver_without_a_step_reports_clearly(app):
    tab = SimTab()
    tab._solver.setCurrentText("ode4")
    tab._step.setValue(0.0)
    tab.run_simulation()
    assert tab._error_banner.has_error
    assert "fixed-step" in tab._error_banner.message
    tab.deleteLater()


def test_scope_shows_the_channels_a_run_logged(app):
    from fakematlab.sim.solver import simulate
    from fakematlab.ui.sim.scope import ScopeWidget

    result = simulate(course_loop(), t_end=5.0, n_points=400)
    scope = ScopeWidget()
    scope.show_result(result)

    assert set(scope._checks) == set(result.signals)
    # A Scope block is wired, so its channels are the ones shown by default.
    shown = {n for n, c in scope._checks.items() if c.isChecked()}
    assert shown == {"G.out", "K2.out"}
    scope.deleteLater()


# ──────────────────────────────────────────────────────────────
#  Subsystem navigation
# ──────────────────────────────────────────────────────────────

def _nested_model() -> SimModel:
    inner = SimModel("PI")
    inner.add("Inport", "e_in", port_name="e", order=1)
    inner.add("TransferFcn", "pi", num="2, 1", den="1, 0")
    inner.add("Outport", "u_out", port_name="u", order=1)
    inner.connect("e_in", "pi")
    inner.connect("pi", "u_out")

    m = SimModel("outer")
    m.add("Step", "r", step_time=0.0)
    m.add("Sum", "e", signs="+-")
    m.add("Subsystem", "C", name="PI").set_inner(inner)
    m.add("TransferFcn", "G", num="1", den="1, 1")
    m.connect("r", "e.in1")
    m.connect("e", "C.e")
    m.connect("C.u", "G")
    m.connect("G", "e.in2")
    return m


def test_double_click_descends_into_a_subsystem(app):
    view = SimCanvas(_nested_model())
    assert view.breadcrumb() == ["outer"]

    view._edit_params("C")               # what a double-click calls
    assert view.inside_subsystem
    assert view.breadcrumb() == ["outer", "PI"]
    assert set(view.model.blocks) == {"e_in", "pi", "u_out"}
    view.deleteLater()


def test_edits_inside_a_subsystem_persist_on_ascend(app):
    view = SimCanvas(_nested_model())
    view.descend("C")
    view.model.block("pi").set_param("num", "5, 1")
    view.ascend()

    assert not view.inside_subsystem
    assert view.model.block("C").inner_model().block("pi").params["num"] == "5, 1"
    view.deleteLater()


def test_descending_and_editing_is_one_undo_step(app):
    """
    Coming back up records a single command.

    Without that, undoing a subsystem edit would mean unwinding every change
    made inside it one at a time, from a level the user is no longer looking
    at.
    """
    view = SimCanvas(_nested_model())
    view.descend("C")
    view.model.block("pi").set_param("num", "9, 1")
    view.ascend()

    view.undo_stack.undo()
    assert view.model.block("C").inner_model().block("pi").params["num"] == "2, 1"
    view.deleteLater()


def test_validation_inside_a_subsystem_uses_the_whole_model(app):
    """
    Compiling only what is on screen would see bare Inport/Outport blocks and
    report a problem that does not exist.
    """
    view = SimCanvas(_nested_model())
    view.descend("C")
    assert view.validate() == ""
    view.deleteLater()


def test_root_model_folds_in_open_subsystem_edits(app):
    """Running while inside a subsystem must use the edited whole model."""
    from fakematlab.sim.solver import simulate

    view = SimCanvas(_nested_model())
    view.descend("C")
    view.model.block("pi").set_param("num", "5, 1")

    root = view.root_model()
    assert "C" in root.blocks
    result = simulate(root, t_end=5.0, n_points=300, rtol=1e-9, atol=1e-12)
    exact = ctl.feedback(ctl.tf([5, 1], [1, 0]) * ctl.tf([1], [1, 1]), 1)
    _, expected = ctl.step_response(exact, T=result.t)
    assert np.max(np.abs(result.trace("G.out") - expected)) < 1e-5
    view.deleteLater()


def test_a_loop_through_a_subsystem_is_flagged_on_screen(app):
    inner = SimModel("gain")
    inner.add("Inport", "i", port_name="in", order=1)
    inner.add("Gain", "k", gain=0.5)
    inner.add("Outport", "o", port_name="out", order=1)
    inner.connect("i", "k")
    inner.connect("k", "o")

    m = SimModel("loop")
    m.add("Step", "r", step_time=0.0)
    m.add("Sum", "s", signs="+-")
    m.add("Subsystem", "S", name="gain").set_inner(inner)
    m.connect("r", "s.in1")
    m.connect("s", "S.in")
    m.connect("S.out", "s.in2")

    view = SimCanvas(m)
    assert "Algebraic loop" in view.validate()
    assert view._blocks["s"]._error

    # And the offending block is marked inside the subsystem too, under the
    # name the flattened model gives it.
    view.descend("S")
    assert "Algebraic loop" in view.validate()
    assert view._blocks["k"]._error
    view.deleteLater()


# ──────────────────────────────────────────────────────────────
#  Wiring through real mouse events
# ──────────────────────────────────────────────────────────────
#
# Everything above drives `_start_wire` / `_finish_wire` directly, which is
# precisely how click-click wiring stayed broken: the *event handlers* were
# never exercised. `mousePressEvent` restarted the wire on the second click
# instead of completing it, so nothing connected and every abandoned attempt
# orphaned a dashed line in the scene. These tests synthesise the real events.

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402

EMPTY_SPOT = QPoint(30, 560)


@pytest.fixture
def wiring(app):
    """Two unconnected blocks, laid far enough apart to click separately."""
    view = SimCanvas(SimModel("wiring"))
    view.resize(900, 600)
    view.show()
    view.add_block("Step", QPointF(-150, 0))
    view.add_block("Gain", QPointF(150, 0))
    for _ in range(10):
        app.processEvents()
    yield view
    view.hide()
    view.deleteLater()


def _press(view, pos):
    view.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, QPointF(pos), Qt.LeftButton, Qt.LeftButton,
        Qt.NoModifier))


def _release(view, pos):
    view.mouseReleaseEvent(QMouseEvent(
        QEvent.MouseButtonRelease, QPointF(pos), Qt.LeftButton, Qt.LeftButton,
        Qt.NoModifier))


def _port(view, block_id, name, is_input):
    """Fresh lookup every time — connecting rebuilds the whole scene."""
    item = view._blocks[block_id].ports[(name, is_input)]
    return view.mapFromScene(item.scene_pos())


def _rubber_bands(view):
    from PySide6.QtWidgets import QGraphicsPathItem

    return sum(1 for i in view._scene.items()
               if isinstance(i, QGraphicsPathItem))


def test_dragging_from_an_output_to_an_input_connects(wiring):
    _press(wiring, _port(wiring, "Step1", "out", False))
    _release(wiring, _port(wiring, "Gain1", "in", True))
    assert len(wiring.model.connections) == 1
    assert _rubber_bands(wiring) == 0


def test_clicking_one_port_then_the_other_connects(wiring):
    """The gesture that did nothing at all before."""
    _press(wiring, _port(wiring, "Step1", "out", False))
    _release(wiring, _port(wiring, "Step1", "out", False))
    assert wiring._pending_port is not None, "the first click must arm a wire"

    _press(wiring, _port(wiring, "Gain1", "in", True))
    _release(wiring, _port(wiring, "Gain1", "in", True))
    assert len(wiring.model.connections) == 1
    assert wiring._pending_port is None
    assert _rubber_bands(wiring) == 0


def test_a_wire_can_be_drawn_backwards(wiring):
    """Input first, then output — the wire still runs the right way."""
    _press(wiring, _port(wiring, "Gain1", "in", True))
    _release(wiring, _port(wiring, "Gain1", "in", True))
    _press(wiring, _port(wiring, "Step1", "out", False))
    _release(wiring, _port(wiring, "Step1", "out", False))

    assert len(wiring.model.connections) == 1
    conn = wiring.model.connections[0]
    assert str(conn.src).startswith("Step1")
    assert str(conn.dst).startswith("Gain1")


def test_releasing_on_empty_space_keeps_the_wire_armed(wiring):
    _press(wiring, _port(wiring, "Step1", "out", False))
    _release(wiring, EMPTY_SPOT)
    assert wiring._pending_port is not None

    _press(wiring, _port(wiring, "Gain1", "in", True))
    _release(wiring, _port(wiring, "Gain1", "in", True))
    assert len(wiring.model.connections) == 1


def test_clicking_empty_space_cancels_an_armed_wire(wiring):
    _press(wiring, _port(wiring, "Step1", "out", False))
    _release(wiring, _port(wiring, "Step1", "out", False))
    _press(wiring, EMPTY_SPOT)
    _release(wiring, EMPTY_SPOT)

    assert wiring._pending_port is None
    assert len(wiring.model.connections) == 0
    assert _rubber_bands(wiring) == 0


def test_abandoned_attempts_do_not_litter_the_canvas(wiring):
    """
    Each abandoned wire used to orphan its rubber band in the scene, so the
    canvas slowly filled with dashed lines that nothing could remove.
    """
    for _ in range(10):
        _press(wiring, _port(wiring, "Step1", "out", False))
        _release(wiring, _port(wiring, "Step1", "out", False))
        _press(wiring, EMPTY_SPOT)
        _release(wiring, EMPTY_SPOT)

    assert _rubber_bands(wiring) == 0
    assert len(wiring.model.connections) == 0
