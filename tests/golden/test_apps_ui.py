"""
The apps as windows: do they build, redraw and stay wired to the app?

The arithmetic is tested in ``test_apps.py``. What is left here is what only a
widget can get wrong — a signal connected to the wrong slot, a stale reference
after a rebuild, a panel that fails silently instead of showing its banner.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", reason="Qt not available")

import control as ctl
from PySide6.QtWidgets import QApplication

from fakematlab.console.apps import AppRequest
from fakematlab.core.architecture import CourseArchitecture
from fakematlab.core.collection import SystemCollection
from fakematlab.core.designer import closed_loop_poles
from fakematlab.core.tf_utils import second_order
from fakematlab.core.viewer import CHARACTERISTICS, ResponseKind
from fakematlab.ui.guard import ErrorBanner
from fakematlab.ui.mainwindow import MainWindow

LOCUS_PLANT = ctl.tf([1], [1, 3, 2, 0])


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(app):
    """
    One window for the module.

    Building and tearing down a whole widget tree per test inside a single
    QApplication is what produced access violations on Windows; the state is
    reset between tests instead.
    """
    window = MainWindow(CourseArchitecture(G=second_order(1.0, 0.5, 2.0)))
    window.resize(1500, 900)
    window.show()
    _settle(app)
    yield window
    window.hide()


@pytest.fixture(autouse=True)
def reset(request, app):
    if "win" not in request.fixturenames:
        yield
        return
    window = request.getfixturevalue("win")
    window.snapshots.clear()
    window._snapshot_bar.refresh()
    for widget in window._apps.values():
        widget.hide()
    window._apps.clear()
    for banner in window.findChildren(ErrorBanner):
        banner.clear()
    _settle(app)
    yield


def _settle(app, rounds: int = 20) -> None:
    for _ in range(rounds):
        app.processEvents()


def _banners_clean(widget) -> None:
    failed = [b.message for b in widget.findChildren(ErrorBanner)
              if b.has_error]
    assert not failed, failed[0]


# ──────────────────────────────────────────────────────────────
#  LTI Viewer
# ──────────────────────────────────────────────────────────────

def test_the_viewer_renders_every_response_kind(app, win):
    viewer = win._open_lti_viewer()
    for kind in ResponseKind:
        viewer._kind_combo.setCurrentText(kind.value)
        for characteristic in CHARACTERISTICS[kind]:
            viewer.set_characteristic(characteristic, True)
        _settle(app, 3)
        _banners_clean(viewer)
        assert viewer._plot_lay.count() >= 1, f"{kind.value} drew nothing"


def test_the_response_kind_survives_the_combo_round_trip(app, win):
    """
    Qt hands a ``str``-mixin enum back as a plain ``str``, which compares
    equal everywhere and then fails on ``.value`` three calls later. The kind
    is rebuilt from the text for that reason.
    """
    viewer = win._open_lti_viewer()
    viewer._kind_combo.setCurrentText(ResponseKind.NICHOLS.value)
    assert isinstance(viewer._kind, ResponseKind)
    assert viewer._kind is ResponseKind.NICHOLS


def test_characteristics_that_do_not_apply_are_dropped_on_switching(app, win):
    from fakematlab.core.viewer import Characteristic

    viewer = win._open_lti_viewer()
    viewer._kind_combo.setCurrentText(ResponseKind.STEP.value)
    viewer.set_characteristic(Characteristic.RISE, True)
    assert Characteristic.RISE in viewer._characteristics
    viewer._kind_combo.setCurrentText(ResponseKind.NYQUIST.value)
    assert Characteristic.RISE not in viewer._characteristics
    _banners_clean(viewer)


def test_unchecking_a_system_removes_its_curve(app, win):
    viewer = win._open_lti_viewer()
    viewer.set_collection(SystemCollection())
    viewer.collection.add("a", ctl.tf([1], [1, 1]))
    viewer.collection.add("b", ctl.tf([2], [1, 2]))
    viewer.refresh()
    from PySide6.QtCore import Qt

    viewer._list.item(0).setCheckState(Qt.Unchecked)
    _settle(app, 3)
    assert [e.name for e in viewer.collection.visible] == ["b"]
    _banners_clean(viewer)


def test_the_viewer_opens_with_the_current_loop(app, win):
    viewer = win._open_lti_viewer()
    assert viewer.collection.names == ["G (plant)", "L (open loop)",
                                       "T (closed loop)"]


def test_a_console_request_loads_into_the_same_window(app, win):
    """Typing and clicking must reach one window, not two."""
    first = win._open_lti_viewer()
    second = win.open_app(AppRequest("ltiview",
                                     {"extra": ctl.tf([5], [1, 5])}))
    assert second is first
    assert "extra" in first.collection.names


# ──────────────────────────────────────────────────────────────
#  Plot layout
# ──────────────────────────────────────────────────────────────

def test_a_long_title_cannot_stretch_a_plot_off_its_panel(app):
    """
    A pyqtgraph title is a ``LabelItem`` whose *minimum* width is its text
    width, so a long title lays the whole ``PlotItem`` out wider than the
    scene and pushes every curve off the right-hand edge. The panel then looks
    blank while every value in it is correct and nothing reports an error —
    which is exactly how it was found, in the designer's root locus.
    """
    from fakematlab.ui.plots import make_plot

    widget = make_plot("Root locus", "Re", "Im")
    widget.resize(434, 470)
    widget.show()
    _settle(app, 10)

    plot = widget.getPlotItem()
    plot.setTitle("Root locus — crosses the imaginary axis at "
                  "K = 6.0001, ω = 1.41421356")
    _settle(app, 10)
    assert plot.boundingRect().width() <= widget.sceneRect().width() + 1
    widget.hide()


def test_the_designer_keeps_its_locus_inside_the_panel(app, win):
    designer = win._open_designer()
    _settle(app, 10)
    for panel in (designer._locus_widget, designer._bode_widget,
                  designer._step_widget):
        assert panel.getPlotItem().boundingRect().width() <= \
            panel.sceneRect().width() + 1, "a plot is laid out wider than its panel"


def test_the_marginal_gain_is_reported_in_the_readout(app, win):
    """It used to be the plot title, which is what caused the stretch."""
    designer = win._open_designer()
    designer.set_plant(LOCUS_PLANT)
    _settle(app, 5)
    assert "imaginary axis" in designer._readout.toPlainText()


# ──────────────────────────────────────────────────────────────
#  Control System Designer
# ──────────────────────────────────────────────────────────────

def test_the_designer_builds_all_three_plots(app, win):
    designer = win._open_designer()
    _banners_clean(designer)
    assert designer._summary is not None
    assert designer._target is not None, "nothing to drag"
    assert designer._readout.toPlainText()


def test_picking_a_point_moves_the_gain_and_the_readout(app, win):
    designer = win._open_designer()
    designer.set_plant(LOCUS_PLANT)
    _settle(app, 3)

    target_pole = max(closed_loop_poles(LOCUS_PLANT, 2.0),
                      key=lambda p: p.imag)
    designer.pick_point(target_pole)
    _settle(app, 3)

    _banners_clean(designer)
    assert designer.compensator.gain == pytest.approx(2.0, rel=1e-2)
    assert designer._gain_spin.value() == pytest.approx(2.0, rel=1e-2)
    assert "K = 2" in designer._readout.toPlainText()


def test_the_damping_button_reaches_the_textbook_gain(app, win):
    designer = win._open_designer()
    designer.set_plant(LOCUS_PLANT)
    designer._zeta_spin.setValue(0.5)
    designer._set_gain_for_damping()
    _settle(app, 3)
    _banners_clean(designer)
    assert designer.compensator.gain == pytest.approx(28 / 27, rel=1e-4)


def test_an_unreachable_target_shows_a_banner_rather_than_crashing(app, win):
    designer = win._open_designer()
    designer.set_plant(ctl.tf([1], [1, 1]))     # one real branch, no ζ < 1
    designer._zeta_spin.setValue(0.5)
    designer._set_gain_for_damping()
    _settle(app, 3)
    assert designer._error_banner.has_error
    assert "lead section" in designer._error_banner.message


def test_a_typo_in_the_compensator_lands_in_the_banner(app, win):
    """
    Parsing happens inside the guarded rebuild, not in the line edit's own
    slot — otherwise the exception escapes from a Qt signal and takes the app
    with it.
    """
    designer = win._open_designer()
    designer._zeros_edit.setText("-1, banana")
    designer.rebuild()
    _settle(app, 3)
    assert designer._error_banner.has_error
    assert "is not a number" in designer._error_banner.message


def test_an_unpaired_complex_root_is_refused(app, win):
    designer = win._open_designer()
    designer._poles_edit.setText("-1+2j")
    designer.rebuild()
    _settle(app, 3)
    assert designer._error_banner.has_error
    assert "conjugate" in designer._error_banner.message


def test_adding_a_lead_keeps_the_designer_working(app, win):
    designer = win._open_designer()
    designer._zeros_edit.setText("")
    designer._poles_edit.setText("")
    designer.rebuild()
    designer._add_lead()
    _settle(app, 3)
    _banners_clean(designer)
    assert designer.compensator.zeros == [complex(-1.0, 0.0)]
    assert designer.compensator.poles == [complex(-10.0, 0.0)]


def test_apply_sends_the_compensator_to_every_tab(app, win):
    designer = win._open_designer()
    designer._zeros_edit.setText("")
    designer._poles_edit.setText("")
    designer.rebuild()
    designer.set_gain(3.5)
    designer._apply()
    _settle(app, 5)
    assert float(ctl.dcgain(win._arch.block_tf("K2"))) == \
        pytest.approx(3.5, rel=1e-6)


# ──────────────────────────────────────────────────────────────
#  PID Tuner
# ──────────────────────────────────────────────────────────────

def test_the_tuner_builds_and_tunes(app, win):
    tuner = win._open_pid_tuner()
    _banners_clean(tuner)
    assert tuner.result is not None and tuner.result.feasible
    assert "PM" in tuner._readout.toPlainText()


def test_the_sliders_change_the_design(app, win):
    """
    The plant is pinned rather than inherited from the window: the slider
    range that is *feasible* depends on how much phase the plant has to spare,
    and a test that silently sampled an infeasible target would be asserting
    on a nan.
    """
    tuner = win._open_pid_tuner()
    tuner.set_plant(ctl.tf([1], [1, 3, 3, 1]))
    tuner._kind_combo.setCurrentText("PID")
    tuner._speed.setValue(-20)
    _settle(app, 3)
    slow = tuner.result
    tuner._speed.setValue(20)
    _settle(app, 3)
    fast = tuner.result
    _banners_clean(tuner)
    assert slow.feasible and fast.feasible
    assert fast.achieved_wc > slow.achieved_wc
    assert fast.response_time < slow.response_time


def test_the_slider_labels_state_what_they_do(app, win):
    """The sliders are only honest if they say which target they set."""
    tuner = win._open_pid_tuner()
    assert "rad/s" in tuner._speed_label.text()
    assert "phase margin" in tuner._transient_label.text()


def test_an_impossible_target_explains_itself_without_a_traceback(app, win):
    tuner = win._open_pid_tuner()
    tuner.set_plant(ctl.tf([1], [1, 3, 3, 1]))
    tuner._kind_combo.setCurrentText("PI")
    tuner._speed.setValue(60)                 # far above the plant's phase
    _settle(app, 3)
    assert not tuner.result.feasible
    assert not tuner._error_banner.has_error, \
        "an impossible target is an answer, not an error"
    assert "phase" in tuner._readout.toPlainText()


def test_apply_from_the_tuner_reaches_the_architecture(app, win):
    tuner = win._open_pid_tuner()
    tuner.set_plant(ctl.tf([1], [1, 3, 3, 1]))
    tuner._kind_combo.setCurrentText("PID")
    _settle(app, 3)
    tuner._apply()
    _settle(app, 5)
    expected = np.atleast_1d(tuner.result.C.num[0][0])
    assert np.allclose(np.atleast_1d(win._arch.block_tf("K2").num[0][0]),
                       expected)


# ──────────────────────────────────────────────────────────────
#  Snapshots, across tabs
# ──────────────────────────────────────────────────────────────

def test_a_snapshot_taken_on_one_tab_restores_from_another(app, win):
    bar = win._snapshot_bar
    win._arch.set_block("K2", ctl.tf([2], [1]))
    bar.take("gain 2")

    win._tabs.setCurrentWidget(win._freq_tab)
    win._arch.set_block("K2", ctl.tf([9], [1]))
    _settle(app, 3)

    bar._combo.setCurrentText("gain 2")
    bar.restore()
    _settle(app, 3)
    assert float(ctl.dcgain(win._arch.block_tf("K2"))) == pytest.approx(2.0)


def test_compare_opens_the_viewer_with_every_design_plus_the_current_one(
        app, win):
    bar = win._snapshot_bar
    win._arch.set_block("K2", ctl.tf([1], [1]))
    bar.take("P = 1")
    win._arch.set_block("K2", ctl.tf([4], [1]))
    bar.take("P = 4")
    bar.compare()
    _settle(app, 5)

    viewer = win._apps["ltiview"]
    assert viewer.collection.names == ["P = 1", "P = 4", "current"]
    _banners_clean(viewer)


def test_restoring_refreshes_the_visible_tab(app, win):
    """A restore that leaves a tab showing the old design is worse than none."""
    win._tabs.setCurrentWidget(win._sys_tab)
    win._arch.set_block("G", ctl.tf([1], [1, 1]))
    win._snapshot_bar.take("first order")
    win._arch.set_block("G", ctl.tf([1], [1, 5, 6]))
    _settle(app, 3)

    win._snapshot_bar._combo.setCurrentText("first order")
    win._snapshot_bar.restore()
    _settle(app, 5)
    _banners_clean(win)
    assert len(np.atleast_1d(ctl.poles(win._arch.block_tf("G")))) == 1


def test_a_new_session_rebinds_the_snapshot_bar(app, win):
    """
    ``_new_session`` replaces the architecture object. Anything still holding
    the old one goes on snapshotting a plant that is no longer on screen.
    """
    win._new_session()
    _settle(app, 5)
    assert win._snapshot_bar._arch is win._arch
    win._arch.set_block("K2", ctl.tf([7], [1]))
    snapshot = win._snapshot_bar.take("after new")
    assert float(ctl.dcgain(snapshot.tf("K2"))) == pytest.approx(7.0)
