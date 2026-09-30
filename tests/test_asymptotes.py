"""
Classical Bode asymptotes against hand calculation.

Every expected number below was worked out on paper the way the course does
it: Bode form ``K·s^−m·Π(1+s/z)/Π(1+s/p)``, a slope change at each corner, and
a value at each corner read off the previous segment. Nothing here is copied
from the code under test.
"""

from __future__ import annotations

import control as ctl
import numpy as np
import pytest

from fakematlab.core.asymptotes import bode_asymptotes
from fakematlab.core.freqresp import bode

W0, W1 = 0.01, 100.0


def _segments(segs):
    return [(s.omega_start, s.value_start, s.omega_end, s.value_end, s.slope)
            for s in segs]


def _assert_contiguous(segs, lo=W0, hi=W1):
    assert segs[0].omega_start == pytest.approx(lo)
    assert segs[-1].omega_end == pytest.approx(hi)
    for a, b in zip(segs[:-1], segs[1:]):
        assert a.omega_end == pytest.approx(b.omega_start)


# ──────────────────────────────────────────────────────────────
#  10 / (s (1+2s)(1+5s))  — the course-slides example
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def slides():
    # (1+2s)(1+5s) = 10 s² + 7 s + 1
    return ctl.tf([10], [10, 7, 1, 0])


def test_slides_bode_gain_and_low_slope(slides):
    a = bode_asymptotes(slides, W0, W1)
    assert a.gain_dB == pytest.approx(20.0)              # 20 log10 10
    assert a.low_frequency_slope == -20.0                # one integrator


def test_slides_magnitude_segments(slides):
    seg = bode_asymptotes(slides, W0, W1).magnitude
    assert len(seg) == 3
    _assert_contiguous(seg)
    # Low line: 20 − 20 log10 ω. At 0.01 that is 60 dB, at the first corner
    # ω = 1/5 = 0.2 it is 20 + 13.979 = 33.979 dB.
    assert seg[0].slope == -20 and seg[0].unit == "dB"
    assert seg[0].value_start == pytest.approx(60.0)
    assert seg[0].omega_end == pytest.approx(0.2)
    assert seg[0].value_end == pytest.approx(20 - 20 * np.log10(0.2))
    # Second corner ω = 1/2: −40 dB/dec over log10(2.5) = 0.39794 decades.
    assert seg[1].slope == -40
    assert seg[1].omega_end == pytest.approx(0.5)
    assert seg[1].value_end == pytest.approx(33.9794 - 40 * np.log10(2.5),
                                             abs=1e-3)
    assert seg[1].value_end == pytest.approx(18.0618, abs=1e-3)
    # Then −60 dB/dec to the end of the window.
    assert seg[2].slope == -60
    assert seg[2].value_end == pytest.approx(18.0618 - 60 * np.log10(200),
                                             abs=1e-3)


def test_slides_breakpoints(slides):
    breaks = bode_asymptotes(slides, W0, W1).breaks
    assert [b.omega for b in breaks] == pytest.approx([0.2, 0.5])
    assert [b.slope_change for b in breaks] == [-20.0, -20.0]
    assert breaks[0].mag_dB == pytest.approx(33.9794, abs=1e-3)


def test_slides_phase_uses_the_decade_rule(slides):
    seg = bode_asymptotes(slides, W0, W1).phase
    _assert_contiguous(seg)
    # −90° from the integrator; the pole at 0.2 ramps −90° over [0.02, 2],
    # the pole at 0.5 over [0.05, 5]. Kinks at 0.02, 0.05, 2, 5.
    assert [s.omega_start for s in seg] == pytest.approx(
        [0.01, 0.02, 0.05, 2.0, 5.0])
    assert [s.slope for s in seg] == [0, -45, -90, -45, 0]
    assert seg[0].value_start == pytest.approx(-90.0)
    assert seg[-1].value_end == pytest.approx(-270.0)
    assert seg[2].value_start == pytest.approx(-90 - 45 * np.log10(2.5))
    assert all(s.unit == "°" for s in seg)


def test_slides_asymptotes_track_the_exact_response(slides):
    a = bode_asymptotes(slides, W0, W1)
    bd = bode(slides, np.logspace(-2, 2, 400))
    for w in (0.01, 0.02, 30.0, 100.0):
        # A decade or more from every corner the sketch is nearly exact.
        m = _value_at(a.magnitude, w)
        exact = np.interp(w, bd.omega, bd.mag_dB)
        assert abs(m - exact) < 0.5
    # And it never strays absurdly (worst case is around a corner).
    for w, exact in zip(bd.omega, bd.mag_dB):
        assert abs(_value_at(a.magnitude, w) - exact) < 6.0


def _value_at(segs, w):
    for s in segs:
        if s.omega_start <= w <= s.omega_end:
            return s.value_start + s.slope * np.log10(w / s.omega_start)
    raise AssertionError(w)


# ──────────────────────────────────────────────────────────────
#  1 / (s² + 0.4 s + 1)  — a complex pair at ωn = 1
# ──────────────────────────────────────────────────────────────

def test_complex_pair_magnitude_is_flat_then_minus_40():
    a = bode_asymptotes(ctl.tf([1], [1, 0.4, 1]), W0, W1)
    assert a.gain_dB == pytest.approx(0.0)
    assert _segments(a.magnitude) == pytest.approx([
        (0.01, 0.0, 1.0, 0.0, 0.0),
        (1.0, 0.0, 100.0, -80.0, -40.0),
    ])
    assert len(a.breaks) == 1
    assert a.breaks[0].omega == pytest.approx(1.0)
    assert a.breaks[0].slope_change == -40.0
    assert "pair" in a.breaks[0].description


def test_complex_pair_phase_is_a_180_degree_step_at_wn():
    seg = bode_asymptotes(ctl.tf([1], [1, 0.4, 1]), W0, W1).phase
    assert len(seg) == 2
    assert seg[0].value_end == pytest.approx(0.0)
    assert seg[1].value_start == pytest.approx(-180.0)     # the jump
    assert seg[0].omega_end == pytest.approx(1.0)
    assert seg[1].omega_start == pytest.approx(1.0)
    assert [s.slope for s in seg] == [0, 0]


# ──────────────────────────────────────────────────────────────
#  (1 − s) / (1 + s)  — non-minimum phase: same magnitude, more lag
# ──────────────────────────────────────────────────────────────

def test_rhp_zero_has_flat_magnitude_but_extra_phase_lag():
    a = bode_asymptotes(ctl.tf([-1, 1], [1, 1]), W0, W1)
    # |1 − jω| = |1 + jω|: the two corners cancel and the magnitude is flat.
    assert _segments(a.magnitude) == pytest.approx([(0.01, 0.0, 100.0, 0.0, 0.0)])
    assert a.breaks == []
    # Phase: the LHP pole gives −90° over [0.1, 10], and the RHP zero — with
    # the opposite phase sign — a further −90°: −90°/dec, 0° → −180°.
    seg = a.phase
    assert [s.slope for s in seg] == [0, -90, 0]
    assert seg[0].value_start == pytest.approx(0.0)
    assert seg[1].omega_start == pytest.approx(0.1)
    assert seg[1].omega_end == pytest.approx(10.0)
    assert seg[-1].value_end == pytest.approx(-180.0)


def test_rhp_pole_phase_leads_where_lhp_pole_lags():
    lhp = bode_asymptotes(ctl.tf([1], [1, 1]), W0, W1)
    rhp = bode_asymptotes(ctl.tf([1], [1, -1]), W0, W1)
    # Same magnitude sketch (|Kbode| = 1, corner at 1)…
    assert _segments(lhp.magnitude) == pytest.approx(_segments(rhp.magnitude))
    # …but 1/(s+1) lags to −90°, while 1/(s−1) = −1/(1−s) starts at −180°
    # (negative gain) and *rises* to −90°.
    assert lhp.phase[-1].value_end == pytest.approx(-90.0)
    assert rhp.phase[0].value_start == pytest.approx(-180.0)
    assert rhp.phase[-1].value_end == pytest.approx(-90.0)


# ──────────────────────────────────────────────────────────────
#  Integrators, differentiators, gain sign
# ──────────────────────────────────────────────────────────────

def test_pure_integrator():
    a = bode_asymptotes(ctl.tf([1], [1, 0]), W0, W1)
    assert a.low_frequency_slope == -20.0
    assert len(a.magnitude) == 1
    s = a.magnitude[0]
    assert s.slope == -20
    assert s.value_start == pytest.approx(40.0)        # −20 log10(0.01)
    assert s.value_end == pytest.approx(-40.0)
    assert _value_at(a.magnitude, 1.0) == pytest.approx(0.0)   # 0 dB at 1 rad/s
    assert len(a.phase) == 1 and a.phase[0].value_start == pytest.approx(-90.0)
    assert a.breaks == []


def test_double_integrator_and_differentiator():
    a = bode_asymptotes(ctl.tf([1], [1, 0, 0]), W0, W1)
    assert a.magnitude[0].slope == -40
    assert a.phase[0].value_start == pytest.approx(-180.0)
    d = bode_asymptotes(ctl.tf([1, 0], [1, 1]), W0, W1)
    assert d.low_frequency_slope == 20.0
    assert d.magnitude[0].slope == 20 and d.magnitude[-1].slope == 0
    assert d.phase[0].value_start == pytest.approx(90.0)


def test_repeated_pole_is_one_corner_with_two_ramps():
    a = bode_asymptotes(ctl.tf([1], [1, 2, 1]), W0, W1)     # (s+1)²
    assert len(a.breaks) == 1 and a.breaks[0].slope_change == -40.0
    assert a.magnitude[-1].slope == -40
    # Two coincident −90° ramps: −90° per ramp over 2 decades = −90°/dec.
    assert [s.slope for s in a.phase] == [0, -90, 0]
    assert a.phase[-1].value_end == pytest.approx(-180.0)


def test_static_gain_is_the_bode_gain():
    # 100/(s+10) = 10/(1 + s/10): 20 dB flat until 10 rad/s.
    a = bode_asymptotes(ctl.tf([100], [1, 10]), W0, W1)
    assert a.gain_dB == pytest.approx(20.0)
    assert a.magnitude[0].value_start == pytest.approx(20.0)
    assert a.breaks[0].omega == pytest.approx(10.0)


def test_negative_gain_adds_180_and_follows_the_plotted_branch():
    tf = ctl.tf([-2], [1, 2])                    # −1 at DC
    bare = bode_asymptotes(tf, W0, W1)
    assert bare.phase[0].value_start == pytest.approx(-180.0)
    # python-control's unwrapped phase may start at +180; the sketch follows.
    anchored = bode_asymptotes(tf, W0, W1, phase_anchor=180.0)
    assert anchored.phase[0].value_start == pytest.approx(180.0)
    assert anchored.phase[-1].value_end == pytest.approx(90.0)


def test_corners_outside_the_window_still_set_the_slope():
    # Corner at 0.1 rad/s lies below the window: the whole window is on the
    # −20 dB/dec side, and the line is at −20 log10(ω/0.1) dB.
    a = bode_asymptotes(ctl.tf([1], [10, 1]), 1.0, 100.0)
    assert len(a.magnitude) == 1
    assert a.magnitude[0].slope == -20
    assert a.magnitude[0].value_start == pytest.approx(-20.0)
    assert a.breaks[0].omega == pytest.approx(0.1)


def test_segments_are_contiguous_in_frequency():
    tf = ctl.tf([1, 3], [1, 0.6, 4]) * ctl.tf([1], [1, 20]) * ctl.tf([1], [1, 0])
    a = bode_asymptotes(tf, 1e-3, 1e4)
    _assert_contiguous(a.magnitude, 1e-3, 1e4)
    _assert_contiguous(a.phase, 1e-3, 1e4)


def test_describe_reads_like_the_hover_text():
    seg = bode_asymptotes(ctl.tf([10], [10, 7, 1, 0]), W0, W1).magnitude[1]
    text = seg.describe()
    assert text.startswith("−40 dB/dec  from (0.2 rad/s, 33.98 dB)")
    assert "to (0.5 rad/s, 18.06 dB)" in text
    ph = bode_asymptotes(ctl.tf([10], [10, 7, 1, 0]), W0, W1).phase[1]
    assert "°/dec" in ph.describe()


def test_bad_window_raises():
    with pytest.raises(ValueError):
        bode_asymptotes(ctl.tf([1], [1, 1]), 10.0, 1.0)
