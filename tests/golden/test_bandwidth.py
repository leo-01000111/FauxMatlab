"""
``bandwidth`` as MATLAB defines it: the first frequency at which the gain of
the system itself falls ``dbdrop`` dB below its DC gain.

It used to close a unity-feedback loop around its argument first, so a
translated MATLAB script quietly got the bandwidth of a different system.
"""

from __future__ import annotations

import math

import control as ctl
import pytest

from evans.console.api import bandwidth


def test_a_first_order_lag_has_its_corner_as_bandwidth():
    # |1/(jw+1)| = 1/sqrt(2) exactly at w = 1 ... for a 3.0103 dB drop.
    # MATLAB's -3 dB is 3 dB, not 10*log10(2), so the answer is a hair lower.
    expected = math.sqrt(10 ** (3 / 10) - 1)
    assert bandwidth(ctl.tf([1], [1, 1])) == pytest.approx(expected, rel=1e-9)


def test_it_measures_the_system_not_its_closed_loop():
    G = ctl.tf([4], [1, 1])                    # DC gain 4, corner at 1 rad/s
    expected = math.sqrt(10 ** (3 / 10) - 1)
    assert bandwidth(G) == pytest.approx(expected, rel=1e-9)
    # The unity-feedback loop around it is a different system: 4/(s+5).
    closed = bandwidth(ctl.feedback(G, 1))
    assert closed == pytest.approx(5 * expected, rel=1e-9)


def test_dbdrop_sets_how_far_the_gain_must_fall():
    G = ctl.tf([1], [1, 1])
    w6 = math.sqrt(10 ** (6 / 10) - 1)
    assert bandwidth(G, -6) == pytest.approx(w6, rel=1e-9)
    with pytest.raises(ValueError, match="negative"):
        bandwidth(G, 3)


def test_a_second_order_system_with_a_resonant_peak():
    wn, zeta = 2.0, 0.2
    G = ctl.tf([wn ** 2], [1, 2 * zeta * wn, wn ** 2])
    w = bandwidth(G)
    # Analytic: |G(jw)|^2 = 1/2 (for 3.0103 dB); for MATLAB's 3 dB, solve
    # (1 - u^2)^2 + (2 zeta u)^2 = 10^(0.3) with u = w/wn.
    a = 1 - 2 * zeta ** 2
    u2 = a + math.sqrt(a ** 2 - 1 + 10 ** 0.3)
    assert w == pytest.approx(wn * math.sqrt(u2), rel=1e-9)


def test_infinite_or_zero_dc_gain_gives_nan_and_no_drop_gives_inf():
    assert math.isnan(bandwidth(ctl.tf([1], [1, 0])))        # integrator
    assert math.isnan(bandwidth(ctl.tf([1, 0], [1, 1])))     # zero DC gain
    assert bandwidth(ctl.tf([2], [1])) == math.inf           # a plain gain
    assert bandwidth(2.0) == math.inf


def test_a_discrete_system_is_searched_up_to_nyquist():
    G = ctl.c2d(ctl.tf([1], [1, 1]), 0.01)
    expected = math.sqrt(10 ** (3 / 10) - 1)
    assert bandwidth(G) == pytest.approx(expected, rel=1e-3)
    slow = ctl.c2d(ctl.tf([1], [1, 1]), 2.0)   # Nyquist pi/2: may never drop
    w = bandwidth(slow)
    assert math.isinf(w) or w <= math.pi / 2.0
