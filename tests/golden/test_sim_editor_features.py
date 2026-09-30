"""
Simulink editor features: alignment snapping, r/G scope defaults, Tune… on a
PID block, folding the palette away, and the plant a controller block sees.

Same approach as ``test_canvas.py``: real mouse events for the drag, direct
calls for everything a click would reach.
"""

from __future__ import annotations

import control as ctl
import numpy as np
import pytest

pytest.importorskip("PySide6", reason="Qt not available")

from PySide6.QtCore import QEvent, QPointF, QSettings, Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QGraphicsSceneMouseEvent

from fakematlab.sim.linearize import LinearizationError, plant_seen_by
from fakematlab.sim.model import SimModel
from fakematlab.sim.solver import simulate
from fakematlab.ui.sim.canvas import SimCanvas
from fakematlab.ui.sim.items import ALIGN_THRESHOLD, BLOCK_W, align_snap
from fakematlab.ui.sim.palette import STRIP_WIDTH
from fakematlab.ui.sim.scope import ScopeWidget
from fakematlab.ui.sim.sim_tab import SimTab, course_loop


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# ──────────────────────────────────────────────────────────────
#  Alignment snapping: the arithmetic
# ──────────────────────────────────────────────────────────────

HALF_W = BLOCK_W / 2


def test_align_snap_pulls_a_centre_onto_a_nearby_centre_line():
    others = [(0.0, 0.0, HALF_W, 30.0)]
    r = align_snap(200.0, 6.0, HALF_W, 30.0, others)
    assert r.aligned_y and r.y == 0.0
    assert not r.aligned_x and r.x == 200.0      # far in x: left to the grid
    assert [(g.orientation, g.coord) for g in r.guides] == [("h", 0.0)]


def test_align_snap_leaves_distant_blocks_alone():
    others = [(0.0, 0.0, HALF_W, 30.0)]
    r = align_snap(200.0, ALIGN_THRESHOLD + 3, HALF_W, 30.0, others)
    assert (r.x, r.y) == (200.0, ALIGN_THRESHOLD + 3)
    assert not r.guides and not r.aligned_x and not r.aligned_y


def test_align_snap_takes_the_nearest_of_several_levels():
    others = [(0.0, 100.0, HALF_W, 30.0), (0.0, 108.0, HALF_W, 30.0)]
    r = align_snap(300.0, 106.0, HALF_W, 30.0, others)
    assert r.y == 108.0


def test_align_snap_aligns_top_edges_of_blocks_of_different_height():
    # Centres are 20 apart (too far) but the tops are 0 apart once the short
    # block sits at y = -20: dragged top = y - 30, neighbour top = -50.
    others = [(0.0, 0.0, HALF_W, 50.0)]
    r = align_snap(200.0, -14.0, HALF_W, 30.0, others)
    assert r.aligned_y and r.y == pytest.approx(-20.0)
    assert any(g.coord == pytest.approx(-50.0) for g in r.guides)


def test_align_snap_aligns_columns_too():
    others = [(0.0, 0.0, HALF_W, 30.0)]
    r = align_snap(-5.0, 200.0, HALF_W, 30.0, others)
    assert r.aligned_x and r.x == 0.0
    assert [(g.orientation, g.coord) for g in r.guides] == [("v", 0.0)]


def test_align_snap_guides_span_both_blocks():
    others = [(-300.0, 0.0, HALF_W, 30.0)]
    g = align_snap(200.0, 3.0, HALF_W, 30.0, others).guides[0]
    assert g.lo <= -300.0 - HALF_W and g.hi >= 200.0 + HALF_W


def test_align_snap_with_nothing_to_align_to_is_a_no_op():
    r = align_snap(12.0, 34.0, HALF_W, 30.0, [])
    assert (r.x, r.y, r.guides) == (12.0, 34.0, [])


# ──────────────────────────────────────────────────────────────
#  Alignment snapping: a real drag
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def dragging(app):
    """A fixed block at y = 0 and a second one, lower down, to drag."""
    view = SimCanvas(SimModel("drag"))
    view.resize(900, 600)
    view.show()
    view.add_block("Step", QPointF(-150, 0))
    view.add_block("Gain", QPointF(150, 100))
    for _ in range(10):
        app.processEvents()
    yield view
    view.hide()
    view.deleteLater()


def _send(item, kind, scene_pos, last_pos, buttons, modifiers=Qt.NoModifier,
          down=None):
    """Deliver a scene mouse event straight to a block, as the view would."""
    event = QGraphicsSceneMouseEvent(kind)
    event.setScenePos(scene_pos)
    event.setLastScenePos(last_pos)
    event.setPos(item.mapFromScene(scene_pos))
    event.setButton(Qt.LeftButton)
    event.setButtonDownPos(Qt.LeftButton, QPointF(0, 0))   # pressed on the centre
    event.setButtonDownScenePos(Qt.LeftButton, down if down is not None else scene_pos)
    event.setLastPos(item.mapFromScene(last_pos))
    event.setButtons(buttons)
    event.setModifiers(modifiers)
    item.scene().sendEvent(item, event)


def _drag(view, block_id, dy, modifiers=Qt.NoModifier, release=True):
    """Press a block and drag it ``dy`` scene px straight up or down."""
    item = view._blocks[block_id]
    start = QPointF(item.pos())
    _send(item, QEvent.GraphicsSceneMousePress, start, start, Qt.LeftButton,
          modifiers, down=start)
    last = start
    for i in range(1, 7):
        here = QPointF(start.x(), start.y() + dy * i / 6)
        _send(item, QEvent.GraphicsSceneMouseMove, here, last, Qt.LeftButton,
              modifiers, down=start)
        last = here
    if release:
        _finish(item, last, start)
    return last, start


def _finish(item, at, down):
    _send(item, QEvent.GraphicsSceneMouseRelease, at, at, Qt.NoButton, down=down)


def test_dragging_a_block_snaps_to_another_blocks_level(dragging):
    _drag(dragging, "Gain1", -94)        # lands at y = 6; the grid alone says 10
    place = dragging.model.placement("Gain1")
    assert (place.x, place.y) == (150.0, 0.0)


def test_guides_show_during_the_drag_and_vanish_on_release(dragging):
    end, start = _drag(dragging, "Gain1", -94, release=False)
    assert dragging._guides, "a dashed guide should mark the alignment"
    _finish(dragging._blocks["Gain1"], end, start)
    assert dragging._guides == []


def test_a_snapped_drag_is_one_undo_step(dragging):
    before = dragging.undo_stack.count()
    _drag(dragging, "Gain1", -94)
    assert dragging.undo_stack.count() == before + 1
    dragging.undo_stack.undo()
    assert dragging.model.placement("Gain1").y == 100.0


def test_alt_disables_alignment_and_the_grid_takes_over(dragging):
    _drag(dragging, "Gain1", -94, modifiers=Qt.AltModifier)
    assert dragging.model.placement("Gain1").y == 10.0
    assert dragging._guides == []


def test_unaligned_drags_still_snap_to_the_grid(dragging):
    _drag(dragging, "Gain1", -47)        # y = 53, clear of every block's lines
    assert dragging.model.placement("Gain1").y == 50.0


# ──────────────────────────────────────────────────────────────
#  Scope defaults: the reference and the plant output
# ──────────────────────────────────────────────────────────────

def _checked(scope):
    return {n for n, c in scope._checks.items() if c.isChecked()}


def test_scope_defaults_to_r_and_g(app):
    scope = ScopeWidget()
    scope.show_result(simulate(course_loop(), t_end=5.0, n_points=200))
    assert _checked(scope) == {"r.out", "G.out"}
    scope.deleteLater()


def test_scope_falls_back_to_the_wired_channels_without_r_and_g(app):
    m = SimModel("renamed")
    m.add("Step", "ref", step_time=0.0)
    m.add("Gain", "plant", gain=2.0)
    m.add("Scope", "sc", n_inputs=1)
    m.connect("ref", "plant")
    m.connect("plant", "sc.in1")
    scope = ScopeWidget()
    scope.show_result(simulate(m, t_end=1.0, n_points=50))
    assert _checked(scope) == {"plant.out"}
    scope.deleteLater()


def test_scope_shows_a_lone_tracking_signal_when_only_one_exists(app):
    m = SimModel("only G")
    m.add("Step", "src", step_time=0.0)
    m.add("TransferFcn", "G", num="1", den="1, 1")
    m.add("Gain", "aux", gain=3.0)
    m.connect("src", "G")
    m.connect("src", "aux")
    scope = ScopeWidget()
    scope.show_result(simulate(m, t_end=1.0, n_points=50))
    assert _checked(scope) == {"G.out"}
    scope.deleteLater()


def test_an_explicit_choice_still_overrides_the_default(app):
    scope = ScopeWidget()
    scope.show_result(simulate(course_loop(), t_end=2.0, n_points=100),
                      preferred=["K2.out"])
    assert _checked(scope) == {"K2.out"}
    scope.deleteLater()


# ──────────────────────────────────────────────────────────────
#  The plant a controller block sees
# ──────────────────────────────────────────────────────────────

def _unity_loop(num="1", den="1, 1", signs="+-") -> SimModel:
    m = SimModel("unity")
    m.add("Step", "r", step_time=0.0)
    m.add("Sum", "e", signs=signs)
    m.add("PID", "C", Kp=2.0, Ki=1.0)
    m.add("TransferFcn", "G", num=num, den=den)
    m.connect("r", "e.in1")
    m.connect("e", "C")
    m.connect("C", "G")
    m.connect("G", "e.in2")
    return m


def _sorted_poles(tf):
    return np.sort(np.atleast_1d(ctl.poles(tf)).real)


def test_plant_seen_by_a_pid_in_unity_feedback_is_the_plant():
    found = plant_seen_by(_unity_loop(), "C")
    assert found.input_port == "G.in" and found.output_port == "e.out"
    assert np.allclose(_sorted_poles(found.tf), [-1.0], atol=1e-6)
    assert float(ctl.dcgain(found.tf)) == pytest.approx(1.0, abs=1e-6)


def test_plant_seen_by_a_pid_keeps_gain_and_dynamics():
    found = plant_seen_by(_unity_loop("2", "1, 3, 2"), "C")   # 2/((s+1)(s+2))
    assert np.allclose(_sorted_poles(found.tf), [-2.0, -1.0], atol=1e-5)
    assert float(ctl.dcgain(found.tf)) == pytest.approx(1.0, abs=1e-6)


def test_plant_sign_comes_from_the_model_not_an_assumption():
    found = plant_seen_by(_unity_loop("-1", "1, 1"), "C")
    assert float(ctl.dcgain(found.tf)) == pytest.approx(-1.0, abs=1e-6)


def test_the_plant_does_not_depend_on_the_pids_own_gains():
    loud = _unity_loop()
    loud.block("C").set_param("Kp", 50.0)
    loud.block("C").set_param("Kd", 3.0)
    assert np.allclose(_sorted_poles(plant_seen_by(_unity_loop(), "C").tf),
                       _sorted_poles(plant_seen_by(loud, "C").tf), atol=1e-6)


def test_a_pid_without_a_closed_loop_is_reported():
    m = SimModel("open")
    m.add("Step", "r", step_time=0.0)
    m.add("PID", "C")
    m.add("TransferFcn", "G", num="1", den="1, 1")
    m.connect("r", "C")
    m.connect("C", "G")
    with pytest.raises(LinearizationError, match="not closed"):
        plant_seen_by(m, "C")


def test_a_pid_with_nothing_connected_is_reported():
    m = SimModel("loose")
    m.add("PID", "C")
    with pytest.raises(LinearizationError, match="not connected"):
        plant_seen_by(m, "C")


def test_nonlinear_blocks_in_the_loop_are_noted_not_fatal():
    m = _unity_loop()
    m.add("Saturation", "sat", upper=5.0, lower=-5.0)
    conn = next(c for c in m.connections if str(c.dst) == "G.in")
    m.disconnect(conn)
    m.connect("C", "sat")
    m.connect("sat", "G")
    found = plant_seen_by(m, "C")
    assert any("Saturation" in n for n in found.notes)
    assert float(ctl.dcgain(found.tf)) == pytest.approx(1.0, abs=1e-6)


# ──────────────────────────────────────────────────────────────
#  Tune… on a PID block
# ──────────────────────────────────────────────────────────────

def test_the_tune_dialog_reads_the_plant_from_the_diagram(app):
    from fakematlab.core.pidtune import crossover_for, phase_margin_for, tune

    view = SimCanvas(course_loop())
    dialog = view.make_tune_dialog("K2")
    assert dialog._plant is not None and dialog._error.isHidden()
    assert dialog.tuned.feasible and dialog.tuned.stable

    # The course loop's plant is 1/(s(s+1)), and its PID has an integral term,
    # so the dialog opens on PI. Its gains must be what the tuner itself gives.
    G = ctl.tf([1], [1, 1, 0])
    assert dialog.kind.value == "PI"
    pm = phase_margin_for(0.5)
    expected = tune(G, "PI", wc=crossover_for(G, 0.0, pm, "PI"), pm_deg=pm)
    gains = dialog.gains()
    assert gains["Kp"] == pytest.approx(expected.params.Kp, rel=1e-6)
    assert gains["Ki"] == pytest.approx(expected.params.Ki, rel=1e-6)
    dialog.deleteLater()
    view.deleteLater()


def test_accepting_the_dialog_writes_gains_through_undo(app, monkeypatch):
    from fakematlab.ui.sim.tune_dialog import PIDTuneDialog

    monkeypatch.setattr(PIDTuneDialog, "exec",
                        lambda self: (self._accept(), 1)[1])
    view = SimCanvas(course_loop())
    old = {k: view.model.block("K2").params[k] for k in ("Kp", "Ki", "Kd")}
    depth = view.undo_stack.count()

    assert view.tune_pid("K2") is True
    now = view.model.block("K2").params
    assert (now["Kp"], now["Ki"]) != (old["Kp"], old["Ki"])
    assert view.undo_stack.count() == depth + 1

    view.undo_stack.undo()
    restored = view.model.block("K2").params
    assert {k: restored[k] for k in old} == old
    view.deleteLater()


def test_cancelling_the_dialog_leaves_the_block_alone(app, monkeypatch):
    from fakematlab.ui.sim.tune_dialog import PIDTuneDialog

    monkeypatch.setattr(PIDTuneDialog, "exec",
                        lambda self: (self.reject(), 0)[1])
    view = SimCanvas(course_loop())
    before = dict(view.model.block("K2").params)
    depth = view.undo_stack.count()
    assert view.tune_pid("K2") is False
    assert view.model.block("K2").params == before
    assert view.undo_stack.count() == depth
    view.deleteLater()


def test_the_sliders_and_controller_type_change_the_gains(app):
    view = SimCanvas(course_loop())
    dialog = view.make_tune_dialog("K2")
    base = dialog.gains()

    dialog._speed.setValue(-50)              # slower: smaller gains
    assert dialog.gains()["Kp"] < base["Kp"]

    dialog._speed.setValue(0)
    dialog._kind.setCurrentText("PID")
    pid = dialog.gains()
    assert pid["Kd"] > 0 and pid["Ki"] > 0
    dialog._kind.setCurrentText("P")
    p_only = dialog.gains()
    assert p_only["Ki"] == 0.0 and p_only["Kd"] == 0.0
    dialog.deleteLater()
    view.deleteLater()


def test_the_dialog_reports_a_missing_loop_instead_of_tuning(app):
    m = SimModel("no loop")
    m.add("Step", "r", step_time=0.0)
    m.add("PID", "C", Kp=1.0)
    m.add("TransferFcn", "G", num="1", den="1, 1")
    m.connect("r", "C")
    m.connect("C", "G")                      # G's output goes nowhere
    view = SimCanvas(m)
    dialog = view.make_tune_dialog("C")
    assert not dialog._error.isHidden()
    assert "loop" in dialog._error.text().lower()
    assert not dialog._buttons.button(QDialogButtonBox.Ok).isEnabled()
    assert dialog.gains() is None
    dialog.deleteLater()
    view.deleteLater()


def test_the_inspector_offers_tune_only_for_a_pid(app):
    tab = SimTab()
    called = []
    tab._canvas.tune_pid = lambda block_id: called.append(block_id)

    tab._canvas._blocks["K2"].setSelected(True)
    assert not tab._inspector._tune.isHidden()
    tab._inspector._tune.click()
    assert called == ["K2"]

    tab._canvas._scene.clearSelection()
    tab._canvas._blocks["G"].setSelected(True)
    assert tab._inspector._tune.isHidden()
    tab.deleteLater()


# ──────────────────────────────────────────────────────────────
#  Folding the palette away
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def shown_tab(app, monkeypatch):
    monkeypatch.setattr(SimTab, "SETTINGS_ORG", "FauxMatlabTest")
    monkeypatch.setattr(SimTab, "SETTINGS_APP", "PaletteTest")
    QSettings("FauxMatlabTest", "PaletteTest").clear()
    tab = SimTab()
    tab.resize(1200, 700)
    tab.show()
    for _ in range(10):
        app.processEvents()
    yield tab
    tab.hide()
    tab.deleteLater()
    QSettings("FauxMatlabTest", "PaletteTest").clear()


def test_collapsing_the_palette_hides_it_and_widens_the_canvas(app, shown_tab):
    tab = shown_tab
    assert tab.palette_visible and tab._palette.isVisible()
    canvas_before = tab._canvas.width()
    assert tab._palette_dock.width() > STRIP_WIDTH

    tab.set_palette_visible(False)
    for _ in range(5):
        app.processEvents()
    assert not tab._palette.isVisible()
    assert tab._palette_dock.width() <= STRIP_WIDTH + 2
    assert tab._canvas.width() > canvas_before
    assert not tab._palette_action.isChecked()


def test_the_palette_can_be_expanded_again(app, shown_tab):
    tab = shown_tab
    width = tab._palette_dock.width()
    tab.set_palette_visible(False)
    tab.set_palette_visible(True)
    for _ in range(5):
        app.processEvents()
    assert tab._palette.isVisible()
    assert tab._palette_action.isChecked()
    assert tab._palette_dock.width() == pytest.approx(width, abs=4)


def test_toolbar_action_and_strip_button_both_toggle(app, shown_tab):
    tab = shown_tab
    tab._palette_action.trigger()
    assert not tab.palette_visible
    tab._palette_dock._button.click()
    assert tab.palette_visible


def test_the_folded_state_is_remembered(app, shown_tab):
    shown_tab.set_palette_visible(False)
    again = SimTab()
    assert not again.palette_visible
    again.deleteLater()
