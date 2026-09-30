"""
Plot furniture: meaningful ticks, asymptotes, and the hover readout.

The nearest-point search is Qt-free (:class:`HoverModel`) and is tested with a
synthetic cursor and axis scale; the widget tests then check that the viewer
wired the right data into it.
"""

from __future__ import annotations

import control as ctl
import numpy as np
import pytest

pytest.importorskip("PySide6", reason="Qt not available")

from PySide6.QtWidgets import QApplication

from fakematlab.core.collection import SystemCollection
from fakematlab.core.viewer import Characteristic, ResponseKind
from fakematlab.ui.apps.lti_viewer import LTIViewer
from fakematlab.ui.plots import (
    DbAxis,
    HoverModel,
    PhaseAxis,
    db_tick_step,
    format_curve_point,
    phase_tick_step,
)

SLIDES = ctl.tf([10], [10, 7, 1, 0])          # 10 / (s (1+2s)(1+5s))


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _viewer(app, kind, system=SLIDES, compact=True):
    collection = SystemCollection()
    collection.add("L", system)
    viewer = LTIViewer(collection, compact=compact)
    viewer.resize(700, 600)
    viewer.show()
    viewer.set_response(kind)
    app.processEvents()
    return viewer


def _plots(viewer):
    return [h.plot for h in viewer.hover_readouts()]


def _major_ticks(axis, lo, hi, size=400):
    levels = axis.tickValues(lo, hi, size)
    spacing, values = levels[0]
    return spacing, np.array(values)


# ──────────────────────────────────────────────────────────────
#  Tick rules
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("span, expected", [
    (720, 90), (360, 90), (270, 90), (200, 45), (90, 45), (60, 15),
])
def test_phase_step_by_span(span, expected):
    assert phase_tick_step(span, 600) == expected


def test_phase_step_never_a_default_pyqtgraph_step():
    for span in np.linspace(5, 3000, 300):
        step = phase_tick_step(span, 500)
        assert step not in (50, 100, 150, 25, 250)


@pytest.mark.parametrize("span, expected", [(200, 20), (100, 20), (60, 20),
                                            (40, 10), (20, 5)])
def test_db_step_by_span(span, expected):
    assert db_tick_step(span, 600) == expected


def test_axes_produce_multiples_of_the_step(app):
    axis = PhaseAxis(orientation="left")
    for lo, hi, unit in ((-360, 0, 90), (-200, -20, 45), (-100, -40, 15)):
        spacing, values = _major_ticks(axis, lo, hi)
        assert spacing == unit
        assert len(values) >= 2
        assert np.allclose(values / unit, np.round(values / unit))
    db = DbAxis(orientation="left")
    for lo, hi, unit in ((-80, 40, 20), (-20, 20, 10)):
        spacing, values = _major_ticks(db, lo, hi)
        assert spacing == unit
        assert np.allclose(values / unit, np.round(values / unit))


def test_minor_ticks_are_unlabelled(app):
    axis = PhaseAxis(orientation="left")
    levels = axis.tickValues(-360, 0, 400)
    assert len(levels) == 2
    minor_spacing, minor_values = levels[1]
    assert minor_spacing < levels[0][0]
    assert set(axis.tickStrings(minor_values, 1.0, minor_spacing)) == {""}
    assert axis.tickStrings([-180.0, -90.0], 1.0, levels[0][0]) == ["-180", "-90"]


def test_bode_phase_panel_uses_the_phase_axis(app):
    viewer = _viewer(app, ResponseKind.BODE)
    mag, phase = _plots(viewer)
    assert isinstance(phase.getAxis("left"), PhaseAxis)
    assert isinstance(mag.getAxis("left"), DbAxis)
    lo, hi = phase.getAxis("left").range
    spacing, values = _major_ticks(phase.getAxis("left"), lo, hi,
                                   phase.getAxis("left").height())
    assert spacing in (45, 90, 180)
    assert np.allclose(values % 45, 0)


def test_ticks_follow_zoom(app):
    viewer = _viewer(app, ResponseKind.BODE)
    phase = _plots(viewer)[1]
    phase.getViewBox().setYRange(-100, -40, padding=0)
    app.processEvents()
    axis = phase.getAxis("left")
    spacing, values = _major_ticks(axis, *axis.range, size=400)
    assert spacing <= 15
    assert np.allclose(values % 15, 0)


def test_nichols_axes(app):
    viewer = _viewer(app, ResponseKind.NICHOLS)
    plot = _plots(viewer)[0]
    assert isinstance(plot.getAxis("bottom"), PhaseAxis)
    assert isinstance(plot.getAxis("left"), DbAxis)


# ──────────────────────────────────────────────────────────────
#  Defaults and asymptotes
# ──────────────────────────────────────────────────────────────

def test_compact_viewer_turns_every_characteristic_on(app):
    viewer = _viewer(app, ResponseKind.BODE)
    assert set(Characteristic) <= viewer._characteristics
    full = LTIViewer(SystemCollection())
    assert full._characteristics == set()          # the app is unchanged


def test_step_pane_marks_everything(app):
    stable = ctl.feedback(ctl.tf([4], [1, 1, 0]), 1)     # ζ = 0.25: overshoots
    viewer = _viewer(app, ResponseKind.STEP, stable)
    (hover,) = viewer.hover_readouts()
    texts = " | ".join(m.text for m in hover.model.marks)
    for needle in ("peak", "ts(", "tr(", "y∞"):
        assert needle in texts


def test_bode_pane_draws_asymptotes_on_both_panels(app):
    viewer = _viewer(app, ResponseKind.BODE)
    mag, phase = viewer.hover_readouts()
    assert len(mag.model.segments) == 3            # −20, −40, −60 dB/dec
    assert len(phase.model.segments) == 5
    for readout in (mag, phase):
        dashed = [it for it in readout.plot.items
                  if it.zValue() == -5]
        assert len(dashed) == 1
    assert "dB/dec" in mag.model.segments[0].text
    assert "°/dec" in phase.model.segments[1].text


def test_asymptotes_can_be_toggled_off(app):
    viewer = _viewer(app, ResponseKind.BODE)
    viewer.set_characteristic(Characteristic.ASYMPTOTES, False)
    app.processEvents()
    mag, phase = viewer.hover_readouts()
    assert mag.model.segments == [] and phase.model.segments == []


def test_full_viewer_offers_asymptotes_but_off_by_default(app):
    viewer = _viewer(app, ResponseKind.BODE, compact=False)
    assert Characteristic.ASYMPTOTES not in viewer._characteristics
    assert viewer.hover_readouts()[0].model.segments == []
    viewer.set_characteristic(Characteristic.ASYMPTOTES, True)
    assert viewer.hover_readouts()[0].model.segments


# ──────────────────────────────────────────────────────────────
#  Hover: the lookup
# ──────────────────────────────────────────────────────────────

def test_hover_snaps_to_nearest_curve_point_on_a_log_axis():
    w = np.logspace(-2, 2, 200)
    model = HoverModel(log_x=True)
    model.add_curve(w, 20 * np.log10(1 / w), quantity="bode_mag")
    i = 80
    # 100 px per decade, 5 px per dB; cursor 3 px off the sample.
    hit = model.hit(np.log10(w[i]) + 0.03, -20 * np.log10(w[i]), 100, 5)
    assert hit is not None and hit.kind == "curve"
    assert hit.x == pytest.approx(np.log10(w[i]), abs=0.03)   # view = log10 ω
    assert hit.text.startswith("ω = ")
    assert "rad/s, |L| = " in hit.text and hit.text.endswith("dB")
    shown = float(hit.text.split("ω = ")[1].split(" rad/s")[0])
    assert shown == pytest.approx(w[i], rel=0.05)              # raw ω, not log


def test_hover_far_from_everything_shows_nothing():
    model = HoverModel(log_x=True)
    model.add_curve([1, 10, 100], [0, -20, -40], quantity="bode_mag")
    assert model.hit(0.0, 60.0, 100, 5) is None


def test_hover_distance_is_in_pixels_not_data_units():
    model = HoverModel(log_x=False)
    model.add_curve([0, 1000], [0, 0], quantity="xy")
    # 1 data unit off in y is 1 px here, and 100 px on a stretched axis.
    assert model.hit(500, 1.0, 1, 1) is not None
    assert model.hit(500, 1.0, 1, 100) is None


def test_mark_hover_shows_its_full_label():
    model = HoverModel(log_x=True)
    model.add_curve([1, 10], [0, -20], quantity="bode_mag")
    model.add_mark(2.0, -6.0, "PM = 45.0° at ωc = 2 rad/s")
    hit = model.hit(np.log10(2.0), -6.0, 100, 5)
    assert hit.kind == "mark"
    assert hit.text == "PM = 45.0° at ωc = 2 rad/s"


def test_segment_hover_reports_slope_and_end_points():
    from fakematlab.core.asymptotes import bode_asymptotes

    seg = bode_asymptotes(SLIDES, 0.01, 100).magnitude[1]
    model = HoverModel(log_x=True)
    model.add_segment(seg.omega_start, seg.value_start, seg.omega_end,
                      seg.value_end, seg.describe())
    mid_w = np.sqrt(seg.omega_start * seg.omega_end)
    hit = model.hit(np.log10(mid_w),
                    seg.value_start + seg.slope * np.log10(mid_w / seg.omega_start),
                    100, 5)
    assert hit.kind == "segment"
    assert "−40 dB/dec" in hit.text
    assert "from (0.2 rad/s, 33.98 dB) to (0.5 rad/s, 18.06 dB)" in hit.text


def test_reference_line_only_when_no_curve_is_closer():
    model = HoverModel()
    model.add_curve([0, 1], [0.0, 0.0], quantity="time")
    model.add_mark(1.0, 5.0, "y∞ = 5", kind="hline")
    assert model.hit(0.5, 0.0, 100, 100).kind == "curve"
    assert model.hit(0.5, 5.02, 100, 100).kind == "line"


@pytest.mark.parametrize("quantity, x, y, param, expected", [
    ("bode_phase", 0.5, -135.0, None, "ω = 0.5 rad/s, phase = −135.0°"),
    ("time", 1.5, 0.9, None, "t = 1.5 s, y = 0.9"),
    ("nyquist", -0.5, -0.25, 2.0, "ω = 2 rad/s, Re = −0.5, Im = −0.25"),
    ("nichols", -150.0, -6.0, 3.0, "ω = 3 rad/s, phase = −150.0°, |L| = −6.00 dB"),
    ("rlocus", -0.5, 1.5, 2.0, "K = 2, s = −0.5 ± j1.5"),
    ("rlocus", -2.0, 0.0, 0.1, "K = 0.1, s = −2"),
    ("pole", -1.0, 2.0, None, "pole at −1 ± j2"),
    ("zero", -3.0, 0.0, None, "zero at −3"),
])
def test_readout_wording_per_plot_type(quantity, x, y, param, expected):
    assert format_curve_point(quantity, x, y, param) == expected


# ──────────────────────────────────────────────────────────────
#  Hover: through the widget
# ──────────────────────────────────────────────────────────────

def test_bode_readouts_in_the_viewer(app):
    viewer = _viewer(app, ResponseKind.BODE)
    mag, phase = viewer.hover_readouts()

    # A point of the magnitude curve.
    curve = mag.model.curves[0]
    i = len(curve.x) // 3
    hit = mag.update_at_view(float(curve.vx[i]), float(curve.y[i]))
    assert hit is not None
    assert hit.text.startswith("ω = ") and "|L| =" in hit.text
    assert mag._label.isVisible() and mag._marker.isVisible()

    # A point of the phase curve is worded as phase.
    pc = phase.model.curves[0]
    hit = phase.update_at_view(float(pc.vx[i]), float(pc.y[i]))
    assert "phase =" in hit.text and "°" in hit.text

    # Away from everything: hidden again.
    assert mag.update_at_view(float(curve.vx[i]), 1e6) is None
    assert not mag._label.isVisible()
    mag.update_at_view(float(curve.vx[i]), float(curve.y[i]))
    mag.hide()
    assert not mag._marker.isVisible()


def test_hovering_a_margin_marker_gives_its_full_label(app):
    viewer = _viewer(app, ResponseKind.BODE, ctl.tf([10], [1, 2, 1, 0]))
    mag, phase = viewer.hover_readouts()
    pm = next(m for m in phase.model.marks if m.text.startswith("PM"))
    hit = phase.update_at_view(pm.vx, pm.vy)
    assert hit.kind == "mark" and hit.text == pm.text
    assert "ωc" in hit.text


def test_hovering_an_asymptote_in_the_widget(app):
    viewer = _viewer(app, ResponseKind.BODE)
    mag = viewer.hover_readouts()[0]
    seg = mag.model.segments[-1]                     # −60 dB/dec tail
    vx = float(np.mean(seg.vx))
    vy = float(np.mean(seg.vy))
    hit = mag.update_at_view(vx, vy)
    assert hit is not None
    assert "−60 dB/dec" in hit.text and "from (" in hit.text


def test_hover_installed_on_every_plot_type(app):
    for kind in ResponseKind:
        viewer = _viewer(app, kind, ctl.feedback(ctl.tf([2], [1, 1, 0]), 1)
                         if kind in (ResponseKind.STEP, ResponseKind.IMPULSE,
                                     ResponseKind.RAMP, ResponseKind.PZMAP)
                         else ctl.tf([2], [1, 3, 2, 0]))
        readouts = viewer.hover_readouts()
        assert readouts, kind
        assert all(r.model.curves for r in readouts), kind


def test_nyquist_hover_carries_omega(app):
    viewer = _viewer(app, ResponseKind.NYQUIST)
    (hover,) = viewer.hover_readouts()
    curve = hover.model.curves[0]
    assert curve.param is not None and len(curve.param) == len(curve.x)
    i = 100
    hit = hover.update_at_view(float(curve.vx[i]), float(curve.y[i]))
    assert "ω =" in hit.text and "Re =" in hit.text and "Im =" in hit.text
