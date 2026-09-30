"""
Headless UI smoke test.

Drives every pane kind, sub-tab and selector, then asserts that **no error banner
appeared anywhere**. Because :func:`fakematlab.ui.guard.guard` now routes every
failure to a banner instead of a bare ``except: pass``, this single assertion
catches the whole class of bugs that used to present as a silently blank tab.

It also checks that the plots contain finite data — a curve of NaNs is
indistinguishable from a working plot unless you look, which is exactly how
v1's truncated Bode plots survived 64 green tests.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6", reason="Qt not available")

from PySide6.QtWidgets import QApplication

from fakematlab.core.architecture import CourseArchitecture
from fakematlab.core.tf_utils import second_order, unity
from fakematlab.ui.guard import ErrorBanner
from fakematlab.ui.mainwindow import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def window(app):
    """
    One window shared by the whole module.

    Tearing a ``MainWindow`` down and building another inside a single
    QApplication trips an access violation in Qt/pyqtgraph on Windows, so the
    window is created once and its state is reset between tests by the
    ``clean_state`` fixture below.
    """
    win = MainWindow(CourseArchitecture(G=second_order(K=1.0, zeta=0.5, wn=2.0),
                                        K2=unity(), K1=unity(), H=unity()))
    win.resize(1400, 900)
    win.show()
    _settle(app)
    yield win
    win.hide()


@pytest.fixture(autouse=True)
def clean_state(request, app):
    """Restore the default plant and clear stale banners before each test."""
    if "window" not in request.fixturenames:
        yield
        return
    win = request.getfixturevalue("window")
    win._load_preset_G(second_order(K=1.0, zeta=0.5, wn=2.0))
    time = _pane(win, "time")
    time._sweep_check.setChecked(False)
    time._sweep_vals.setText("0.5, 1, 2, 5")
    for banner in _banners(win):
        banner.clear()
    _settle(app)
    yield


#: Pane kinds that host a whole workflow widget, in the order the old tab bar
#: listed them.
HOSTED = ("system", "time", "frequency", "stability", "performance",
          "design", "modern")


def _pane(window, key: str):
    """
    The widget a pane hosts for ``key``, showing it in the first pane.

    The analysis area used to have a Tabs view holding one long-lived
    instance of each workflow; now they live inside panes, so a test reaches
    one by pointing a pane at it. Asking for the kind the pane already shows
    returns the same instance, so state set by a test survives a second call.
    """
    pane = window._grid.panes[0]
    pane.set_kind(key)
    return pane.content


def _settle(app, rounds: int = 30) -> None:
    for _ in range(rounds):
        app.processEvents()


def _banners(widget) -> list[ErrorBanner]:
    return widget.findChildren(ErrorBanner)


def _assert_no_errors(widget, context: str) -> None:
    shown = [b for b in _banners(widget) if b.has_error]
    assert not shown, (
        f"{context}: {len(shown)} error banner(s) raised — "
        + " | ".join(b.message.splitlines()[0] for b in shown)
    )


# ──────────────────────────────────────────────────────────────

def test_every_hosted_pane_renders_without_error(app, window):
    for key in HOSTED:
        _pane(window, key)
        _settle(app)
        _assert_no_errors(window, f"pane {key!r}")


def test_every_frequency_subtab_and_signal(app, window):
    freq = _pane(window, "frequency")
    for sub in range(freq._sub_tabs.count()):
        freq._sub_tabs.setCurrentIndex(sub)
        for sig in range(freq._sig_combo.count()):
            freq._sig_combo.setCurrentIndex(sig)
            _settle(app)
            _assert_no_errors(
                window,
                f"Frequency/{freq._sub_tabs.tabText(sub)}/"
                f"{freq._sig_combo.itemText(sig)}")


def test_every_system_tab_selection(app, window):
    combo = _pane(window, "system")._sig_combo
    for i in range(combo.count()):
        combo.setCurrentIndex(i)
        _settle(app)
        _assert_no_errors(window, f"System/{combo.itemText(i)}")


def test_every_time_tab_signal_pair(app, window):
    tab = _pane(window, "time")
    for r in range(tab._resp_combo.count()):
        tab._resp_combo.setCurrentIndex(r)
        for i in range(tab._in_combo.count()):
            tab._in_combo.setCurrentIndex(i)
            for o in range(tab._out_combo.count()):
                tab._out_combo.setCurrentIndex(o)
                _settle(app, 10)
        _assert_no_errors(window, f"Time/{tab._resp_combo.itemText(r)}")


def test_time_tab_parameter_sweep(app, window):
    tab = _pane(window, "time")
    tab._sweep_check.setChecked(True)
    for p in range(tab._sweep_param.count()):
        tab._sweep_param.setCurrentIndex(p)
        tab._sweep_vals.setText("0.5, 1, 2, 5")
        tab.refresh()
        _settle(app)
        _assert_no_errors(window, f"Sweep/{tab._sweep_param.itemText(p)}")
    tab._sweep_check.setChecked(False)


def test_bad_sweep_input_reports_instead_of_blanking(app, window):
    """A typo must produce a visible message, not a silently empty plot."""
    tab = _pane(window, "time")
    tab._sweep_check.setChecked(True)
    tab._sweep_vals.setText("one, two, three")
    tab.refresh()
    _settle(app)

    shown = [b for b in _banners(window) if b.has_error]
    assert shown, "an unparseable sweep list should surface an error"
    assert "sweep values" in shown[0].message

    # ...and recovering must clear it again.
    tab._sweep_vals.setText("1, 2")
    tab.refresh()
    _settle(app)
    _assert_no_errors(window, "after fixing the sweep values")
    tab._sweep_check.setChecked(False)


def test_every_design_controller_type(app, window):
    tab = _pane(window, "design")
    for i in range(tab._type_combo.count()):
        tab._type_combo.setCurrentIndex(i)
        _settle(app)
        _assert_no_errors(window, f"Design/{tab._type_combo.itemText(i)}")


def test_every_stability_subtab(app, window):
    tab = _pane(window, "stability")
    for sub in range(tab._sub.count()):
        tab._sub.setCurrentIndex(sub)
        _settle(app)
        _assert_no_errors(window, f"Stability/{tab._sub.tabText(sub)}")


def test_all_presets_render(app, window):
    """Every preset in the menu, across every hosted pane kind."""
    presets = [
        window._preset_first_order, window._preset_so_under,
        window._preset_so_over, window._preset_double_int,
        window._preset_unstable, window._preset_nmp, window._preset_satellite,
    ]
    for preset in presets:
        preset()
        for key in HOSTED:
            _pane(window, key)
            _settle(app, 15)
            if preset == window._preset_nmp and key == "time":
                # G = (1-s)/(1+s) has direct feedthrough, so the unity-
                # feedback r->y loop is (1-s)/2: genuinely non-proper, and
                # the Time pane reports that in its banner rather than
                # plotting it. The shared Tabs instance used to sit on some
                # other signal pair here by accident, which hid it.
                shown = [b for b in _banners(window) if b.has_error]
                assert all("non-proper" in b.message for b in shown)
                continue
            _assert_no_errors(
                window, f"preset {preset.__name__} on pane {key}")


# ──────────────────────────────────────────────────────────────
#  Plot content
# ──────────────────────────────────────────────────────────────

def _curve_data(plot_widget):
    """Finite (x, y) of every real curve in a plot, ignoring annotations."""
    out = []
    for item in plot_widget.getPlotItem().listDataItems():
        x, y = item.getData()
        if x is None or len(x) < 2:
            continue
        out.append((np.asarray(x), np.asarray(y)))
    return out


def test_bode_curve_spans_the_full_frequency_range(app, window):
    """
    The plotted magnitude curve must reach below ω = 1 (view coordinate 0).

    This is the regression test for v1's double-``log10``: it turned every
    sample below 1 rad/s into NaN, so pyqtgraph dropped them and the curve
    started a third of the way across the axis.
    """
    freq = _pane(window, "frequency")
    freq._sub_tabs.setCurrentIndex(0)
    freq._sig_combo.setCurrentIndex(0)
    _settle(app)

    curves = _curve_data(freq._bode_mag)
    assert curves, "no curve drawn on the Bode magnitude plot"
    x, y = curves[0]
    assert np.isfinite(x).all(), "NaN in the Bode frequency axis"
    assert np.isfinite(y).all(), "NaN in the Bode magnitude data"
    assert x.min() < 0.0, (
        f"Bode curve starts at 10^{x.min():.2f} rad/s — the low-frequency "
        f"decades are missing"
    )
    assert x.max() > 0.0


def test_step_response_curve_has_data(app, window):
    tab = _pane(window, "time")
    tab._resp_combo.setCurrentIndex(0)
    tab._in_combo.setCurrentIndex(0)
    tab._out_combo.setCurrentIndex(0)
    tab.refresh()
    _settle(app)

    curves = _curve_data(tab._plot)
    assert curves
    _, y = curves[0]
    assert np.isfinite(y).all()
    assert y.max() > 0.5, "step response never rises"


def test_metrics_table_shows_every_metric(app, window):
    """All ten metrics must be present — v1 sized the table to show two."""
    tab = _pane(window, "time")
    tab._resp_combo.setCurrentIndex(0)
    tab.refresh()
    _settle(app)
    assert tab._metrics_table.rowCount() == 10
    assert tab._metrics_table.minimumHeight() >= 10 * 20


# ──────────────────────────────────────────────────────────────
#  Errors really do surface
# ──────────────────────────────────────────────────────────────

def test_guard_surfaces_a_failure(app, window):
    """
    The safety net itself must work: force a failure and check it appears.

    Without this, "no banner visible" could mean "banners never appear".
    """
    from fakematlab.ui.guard import guard

    class Boom:
        def __init__(self):
            self._error_banner = ErrorBanner()

        @guard("Deliberate failure")
        def go(self):
            raise RuntimeError("expected in test")

    b = Boom()
    b.go()
    assert b._error_banner.has_error
    assert "Deliberate failure" in b._error_banner.message
    assert "expected in test" in b._error_banner.message
