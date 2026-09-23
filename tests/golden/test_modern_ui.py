"""
The Modern tab: five views over one shared state-space model.

The point being tested is that the views agree. Each one holding its own copy
of "the model" is the obvious design and the wrong one — an observer designed
for one realisation and a controller for another produce a compensator that
cannot be assembled, and nothing would say so.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", reason="Qt not available")

import control as ctl
from PySide6.QtWidgets import QApplication

from fakematlab.core.architecture import CourseArchitecture
from fakematlab.core.statespace import state_space
from fakematlab.ui.guard import ErrorBanner
from fakematlab.ui.tabs.modern import ModernTab


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def tab(app):
    """
    One tab for the module.

    Building and tearing down Qt widget trees repeatedly inside one
    QApplication is what tripped an access violation in the Simulink tests, so
    the same pattern is used here: build once, reset state per test.
    """
    widget = ModernTab(CourseArchitecture(G=ctl.tf([1], [1, 3, 3, 1])))
    widget.resize(1500, 900)
    widget.show()
    _settle(app)
    yield widget
    widget.hide()


@pytest.fixture(autouse=True)
def reset(request, app):
    if "tab" not in request.fixturenames:
        yield
        return
    widget = request.getfixturevalue("tab")
    widget.ctx.set_system(
        state_space([[0, 1, 0], [0, 0, 1], [-6, -11, -6]],
                    [[0], [0], [1]], [[1, 0, 0]]), "test fixture")
    for banner in widget.findChildren(ErrorBanner):
        banner.clear()
    _settle(app)
    yield


def _settle(app, rounds: int = 25) -> None:
    for _ in range(rounds):
        app.processEvents()


def _errors(widget) -> list[str]:
    return [b.message for b in widget.findChildren(ErrorBanner) if b.has_error]


# ──────────────────────────────────────────────────────────────

def test_every_view_renders_cleanly(app, tab):
    for i in range(tab._tabs.count()):
        tab._tabs.setCurrentIndex(i)
        _settle(app)
        assert not _errors(tab), f"{tab._tabs.tabText(i)}: {_errors(tab)}"


def test_all_views_share_one_model(app, tab):
    """Changing the model anywhere must reach every view."""
    tab.ctx.set_system(state_space([[-2.0]], [[1.0]], [[1.0]]), "test")
    _settle(app)
    assert tab.ctx.n == 1
    assert tab.state_view.ctx is tab.ctx
    assert tab.structure_view.ctx is tab.ctx
    assert tab.feedback_view.ctx is tab.ctx
    assert tab.observer_view.ctx is tab.ctx
    assert tab.discrete_view.ctx is tab.ctx
    assert not _errors(tab)


def test_changing_the_model_clears_stale_designs(app, tab):
    """
    A gain designed for a 3-state plant is meaningless for a 1-state one, and
    keeping it would produce a design that looks valid and is not.
    """
    tab.feedback_view._poles.setText("-4, -5, -6")
    tab.feedback_view._place("place")
    _settle(app)
    assert tab.ctx.K is not None

    tab.ctx.set_system(state_space([[-2.0]], [[1.0]], [[1.0]]), "test")
    _settle(app)
    assert tab.ctx.K is None
    assert tab.ctx.L is None


def test_pole_placement_from_the_ui(app, tab):
    tab.feedback_view._poles.setText("-4, -5, -6")
    tab.feedback_view._place("place")
    _settle(app)

    assert not _errors(tab)
    assert np.allclose(np.sort(tab.feedback_view._design.eigenvalues.real),
                       [-6, -5, -4], atol=1e-7)
    assert tab.ctx.K is not None


def test_a_bad_pole_list_reports_instead_of_blanking(app, tab):
    tab.feedback_view._poles.setText("two, three")
    tab.feedback_view._place("place")
    _settle(app)

    problems = _errors(tab)
    assert problems, "an unparseable pole list should surface an error"
    assert "pole list" in problems[0]


def test_placing_too_few_poles_is_explained(app, tab):
    tab.feedback_view._poles.setText("-1, -2")      # 3 states
    tab.feedback_view._place("place")
    _settle(app)
    assert any("one desired eigenvalue per state" in p for p in _errors(tab))


@pytest.mark.parametrize("integral", [False, True])
def test_lqr_from_the_ui(app, tab, integral):
    tab.feedback_view._integral.setChecked(integral)
    tab.feedback_view._lqr()
    _settle(app)
    try:
        assert not _errors(tab)
        assert tab.feedback_view._design.stable
    finally:
        tab.feedback_view._integral.setChecked(False)


def test_moving_the_r_slider_redesigns(app, tab):
    """
    Cheaper control buys bandwidth and costs gain.

    Measured as ``max |λ|`` and ``‖K‖``, not as the slowest real part: with
    ``Q = I`` the cheap-control limit sends one pole to −∞ while the others
    approach the weighted system's zeros, so the *slowest* pole can drift
    right even as the loop gets far faster overall.
    """
    tab.feedback_view._r_slider.setValue(20)        # R = 100
    tab.feedback_view._lqr()
    _settle(app)
    expensive = tab.feedback_view._design
    slow_bandwidth = max(abs(expensive.eigenvalues))
    small_gain = np.linalg.norm(expensive.K)

    tab.feedback_view._r_slider.setValue(-20)       # R = 0.01
    _settle(app)                                    # the slider redesigns
    cheap = tab.feedback_view._design
    fast_bandwidth = max(abs(cheap.eigenvalues))
    big_gain = np.linalg.norm(cheap.K)

    assert fast_bandwidth > slow_bandwidth
    assert big_gain > small_gain
    assert cheap.stable and expensive.stable
    tab.feedback_view._r_slider.setValue(0)


def test_observer_and_separation_principle_from_the_ui(app, tab):
    tab.feedback_view._poles.setText("-2, -3, -4")
    tab.feedback_view._place("place")
    tab.observer_view._poles.setText("-20, -21, -22")
    tab.observer_view._full()
    _settle(app)

    assert not _errors(tab)
    assert tab.ctx.K is not None and tab.ctx.L is not None
    text = tab.observer_view._separation.text()
    assert "separation principle holds: yes" in text
    # Both pole sets appear in the table.
    assert tab.observer_view._poles_table.rowCount() == 6


def test_reduced_observer_does_not_claim_to_be_a_full_one(app, tab):
    """
    A reduced observer's ``L`` has fewer rows than the plant has states, so it
    cannot go into the separation-principle assembly — the context must not
    accept it as if it could.
    """
    tab.observer_view._poles.setText("-20, -21")
    tab.observer_view._reduced()
    _settle(app)
    assert not _errors(tab)
    assert tab.ctx.L is None


def test_kalman_slider_changes_the_filter(app, tab):
    tab.observer_view._v_slider.setValue(-20)       # quiet sensor
    tab.observer_view._kalman()
    _settle(app)
    fast = max(tab.observer_view._design.eigenvalues.real)

    tab.observer_view._v_slider.setValue(20)        # noisy sensor
    _settle(app)
    slow = max(tab.observer_view._design.eigenvalues.real)

    assert slow > fast, "a noisier sensor should give a slower filter"
    tab.observer_view._v_slider.setValue(0)


def test_discrete_view_samples_and_reports(app, tab):
    tab._tabs.setCurrentIndex(4)
    tab.discrete_view._dt.setValue(0.05)
    _settle(app)

    assert not _errors(tab)
    assert tab.discrete_view._poles.rowCount() == 3
    assert tab.discrete_view._sweep.rowCount() > 0
    assert "stable" in tab.discrete_view._jury.text().lower()


def test_deadbeat_from_the_ui(app, tab):
    tab.discrete_view._dt.setValue(0.1)
    tab.discrete_view._deadbeat()
    _settle(app)
    assert not _errors(tab)
    assert "settles in 3 samples" in tab.discrete_view._dead_result.text()


def test_minimal_realisation_button_reduces_the_model(app, tab):
    tab.ctx.set_system(
        state_space(np.diag([-1.0, -5.0]), [[1.0], [0.0]], [[1.0, 1.0]]),
        "non-minimal")
    _settle(app)
    assert tab.ctx.n == 2

    tab.state_view._minimise()
    _settle(app)
    assert tab.ctx.n == 1
    assert not _errors(tab)


def test_matrix_editor_round_trips(app, tab):
    from fakematlab.ui.tabs.modern.widgets import matrix_text, parse_matrix

    A = np.array([[0.0, 1.0], [-2.0, -3.0]])
    assert np.allclose(parse_matrix(matrix_text(A)), A)
    # Both input styles are accepted.
    assert np.allclose(parse_matrix("0 1; -2 -3"), A)
    assert np.allclose(parse_matrix("0, 1\n-2, -3"), A)


def test_ragged_matrix_is_refused_clearly(app, tab):
    from fakematlab.ui.tabs.modern.widgets import parse_matrix

    with pytest.raises(ValueError, match="different lengths"):
        parse_matrix("1 2 3; 4 5")


def test_bad_matrix_entry_reports_the_row(app, tab):
    tab._tabs.setCurrentIndex(0)
    tab.state_view._editor._boxes["A"].setPlainText("0 1\nx -3")
    tab.state_view._editor._emit()
    _settle(app)
    assert any("row 2" in p for p in _errors(tab))


def test_send_to_analysis_updates_the_plant(app, tab):
    arch = tab._arch
    tab.ctx.set_system(state_space([[-7.0]], [[1.0]], [[1.0]]), "test")
    _settle(app)

    received = []
    tab.model_sent_to_analysis.connect(lambda: received.append(True))
    tab.send_to_analysis()
    _settle(app)

    assert received
    assert np.allclose(np.atleast_1d(ctl.poles(arch.block_tf("G"))), [-7.0])


def test_load_plant_round_trips(app, tab):
    arch = tab._arch
    arch.set_block("G", ctl.tf([2.0], [1.0, 4.0]))
    tab.load_from_plant()
    _settle(app)

    assert tab.ctx.n == 1
    assert np.allclose(np.atleast_1d(ctl.poles(tab.ctx.sys)), [-4.0])
    assert not _errors(tab)
