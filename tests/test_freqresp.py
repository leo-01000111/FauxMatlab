"""Tests for fakematlab.core.freqresp."""

import control as ctl
import numpy as np

from fakematlab.core.freqresp import bode, nichols, nyquist
from fakematlab.core.tf_utils import first_order, second_order


class TestBode:
    def test_first_order_dc_magnitude(self):
        tf = first_order(1.0, 1.0)
        bd = bode(tf)
        # At low frequency, |G(jω)| → 1 → 0 dB
        assert abs(bd.mag_dB[0]) < 1.0  # within 1 dB

    def test_first_order_rolloff(self):
        # At ω = 1/tau = 1, mag should be ≈ −3 dB
        tf = first_order(1.0, 1.0)
        bd = bode(tf, omega=np.array([1.0]))
        assert abs(bd.mag_dB[0] - (-3.01)) < 0.1

    def test_phase_margin_positive_stable(self):
        # Stable first-order with K=1: PM should be positive
        tf = first_order(1.0, 1.0)
        bd = bode(tf)
        assert bd.pm_deg > 0 or np.isinf(bd.pm_deg)

    def test_gain_margin_inf_for_first_order(self):
        # First-order system: no phase crossover, so GM = inf
        tf = first_order(1.0, 1.0)
        bd = bode(tf)
        assert np.isinf(bd.gm_dB), f"Expected inf GM, got {bd.gm_dB}"

    def test_shape(self):
        tf = second_order(1.0, 0.5, 1.0)
        bd = bode(tf)
        assert len(bd.omega) == len(bd.mag_dB) == len(bd.phase_deg)

    def test_unstable_open_loop_margins(self):
        # Open-loop unstable but can still compute Bode margins
        tf = ctl.TransferFunction([100], [1, 2, 100])  # underdamped
        bd = bode(tf)
        assert isinstance(bd.pm_deg, float)
        assert isinstance(bd.gm_dB, float)


class TestNyquist:
    def test_stable_encirclements(self):
        # Stable plant with low gain: no encirclements
        tf = first_order(1.0, 1.0)
        nd = nyquist(tf)
        assert nd.Z == 0  # no CL RHP poles

    def test_returns_m_circles(self):
        tf = first_order(1.0, 1.0)
        nd = nyquist(tf)
        assert len(nd.m_circles) > 0

    def test_modulus_margin_positive(self):
        tf = first_order(1.0, 1.0)
        nd = nyquist(tf)
        assert nd.modulus_margin > 0


class TestNichols:
    def test_returns_data(self):
        tf = second_order(1.0, 0.5, 1.0)
        nc = nichols(tf)
        assert len(nc.omega) > 0
        assert len(nc.mag_dB) == len(nc.phase_deg)

    def test_m_circles_present(self):
        tf = first_order(1.0, 1.0)
        nc = nichols(tf)
        assert len(nc.m_circles) > 0
