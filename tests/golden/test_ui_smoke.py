"""
Headless UI smoke test.

Drives every tab, sub-tab and selector, then asserts that **no error banner
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
    win._time_tab._sweep_check.setChecked(False)
    win._time_tab._sweep_vals.setText("0.5, 1, 2, 5")
    for banner in _banners(win):
        banner.clear()
    _settle(app)
    yield


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

def test_every_tab_renders_without_error(app, window):
    for i in range(window._tabs.count()):
        window._tabs.setCurrentIndex(i)
        _settle(app)
        _assert_no_errors(window, f"tab {window._tabs.tabText(i)!r}")


def test_every_frequency_subtab_and_signal(app, window):
    window._tabs.setCurrentIndex(2)
    freq = window._freq_tab
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
    window._tabs.setCurrentIndex(0)
    combo = window._sys_tab._sig_combo
    for i in range(combo.count()):
        combo.setCurrentIndex(i)
        _settle(app)
        _assert_no_errors(window, f"System/{combo.itemText(i)}")


def test_every_time_tab_signal_pair(app, window):
    window._tabs.setCurrentIndex(1)
    tab = window._time_tab
    for r in range(tab._resp_combo.count()):
        tab._resp_combo.setCurrentIndex(r)
        for i in range(tab._in_combo.count()):
            tab._in_combo.setCurrentIndex(i)
            for o in range(tab._out_combo.count()):
                tab._out_combo.setCurrentIndex(o)
                _settle(app, 10)
        _assert_no_errors(window, f"Time/{tab._resp_combo.itemText(r)}")


def test_time_tab_parameter_sweep(app, window):
    window._tabs.setCurrentIndex(1)
    tab = window._time_tab
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
    window._tabs.setCurrentIndex(1)
    tab = window._time_tab
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
    window._tabs.setCurrentIndex(5)
    tab = window._des_tab
    for i in range(tab._type_combo.count()):
        tab._type_combo.setCurrentIndex(i)
        _settle(app)
        _assert_no_errors(window, f"Design/{tab._type_combo.itemText(i)}")


def test_every_stability_subtab(app, window):
    window._tabs.setCurrentIndex(3)
    tab = window._stab_tab
    for sub in range(tab._sub.count()):
        tab._sub.setCurrentIndex(sub)
        _settle(app)
        _assert_no_errors(window, f"Stability/{tab._sub.tabText(sub)}")


def test_all_presets_render(app, window):
    """Every preset in the menu, across every tab."""
    presets = [
        window._preset_first_order, window._preset_so_under,
        window._preset_so_over, window._preset_double_int,
        window._preset_unstable, window._preset_nmp, window._preset_satellite,
    ]
    for preset in presets:
        preset()
        for i in range(window._tabs.count()):
            window._tabs.setCurrentIndex(i)
            _settle(app, 15)
            _assert_no_errors(
                window, f"preset {preset.__name__} on tab {i}")


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
    window._tabs.setCurrentIndex(2)
    freq = window._freq_tab
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
    window._tabs.setCurrentIndex(1)
    tab = window._time_tab
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
    window._tabs.setCurrentIndex(1)
    tab = window._time_tab
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
