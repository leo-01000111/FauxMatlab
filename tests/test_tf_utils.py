"""Tests for fakematlab.core.tf_utils."""

import numpy as np
import pytest
import control as ctl

from fakematlab.core.tf_utils import (
    from_coefficients, from_expression, from_zpk,
    first_order, second_order, integrator,
    pole_info, analyse, factored_str, coefficients_str,
)


class TestParsing:
    def test_from_coefficients_basic(self):
        tf = from_coefficients([1], [1, 1])
        poles = ctl.poles(tf)
        assert np.allclose(poles, [-1.0], atol=1e-8)

    def test_from_expression_first_order(self):
        tf = from_expression("1 / (s + 1)")
        poles = ctl.poles(tf)
        assert np.allclose(poles, [-1.0], atol=1e-6)

    def test_from_expression_second_order(self):
        tf = from_expression("1 / (s**2 + 2*s + 1)")
        poles = ctl.poles(tf)
        assert len(poles) == 2

    def test_from_expression_caret_exponent(self):
        tf = from_expression("(s+1)/(s^2 + 3*s + 2)")
        zeros = ctl.zeros(tf)
        assert np.allclose(sorted(zeros.real), [-1.0], atol=1e-6)

    def test_from_zpk(self):
        tf = from_zpk(zeros=[], poles=[-1.0, -2.0], gain=2.0)
        poles = sorted(ctl.poles(tf).real)
        assert np.allclose(poles, [-2.0, -1.0], atol=1e-6)

    def test_first_order_preset(self):
        tf = first_order(K=2.0, tau=0.5)
        # DC gain = K = 2
        assert abs(float(np.polyval(tf.num[0][0], 0) /
                         np.polyval(tf.den[0][0], 0)) - 2.0) < 1e-8

    def test_second_order_preset(self):
        tf = second_order(K=1.0, zeta=0.5, wn=2.0)
        poles = ctl.poles(tf)
        # wn = 2, so |pole| = 2
        assert np.allclose(np.abs(poles), [2.0, 2.0], atol=1e-6)


class TestPoleInfo:
    def test_real_stable_pole(self):
        info = pole_info(-2.0 + 0j)
        assert info.stable
        assert not info.oscillatory
        assert info.kind == "real-stable"
        assert abs(info.tau - 0.5) < 1e-8
        assert abs(info.wn - 2.0) < 1e-8
        assert abs(info.zeta - 1.0) < 1e-8

    def test_complex_stable_pole(self):
        # zeta = 0.5, wn = 1 → pole = -0.5 ± j*sqrt(0.75)
        p = -0.5 + 1j * np.sqrt(0.75)
        info = pole_info(p)
        assert info.stable
        assert info.oscillatory
        assert info.kind == "complex-stable"
        assert abs(info.wn - 1.0) < 1e-6
        assert abs(info.zeta - 0.5) < 1e-6

    def test_integrator_pole(self):
        info = pole_info(0.0 + 0j)
        assert info.kind == "integrator"
        assert np.isnan(info.zeta)
        assert info.tau == float('inf')

    def test_unstable_pole(self):
        info = pole_info(1.0 + 0j)
        assert not info.stable
        assert info.kind == "real-unstable"


class TestAnalyse:
    def test_stable_system(self):
        tf = first_order(1.0, 1.0)
        info = analyse(tf)
        assert info.stable
        assert info.system_type == 0
        assert abs(info.dc_gain - 1.0) < 1e-6

    def test_integrator_system_type(self):
        tf = integrator(1.0)
        info = analyse(tf)
        assert info.system_type == 1

    def test_non_minimum_phase(self):
        tf = from_expression("(-s + 1)/(s + 1)")
        info = analyse(tf)
        assert not info.minimum_phase

    def test_minimum_phase(self):
        tf = from_expression("(s + 2)/(s + 1)")
        info = analyse(tf)
        assert info.minimum_phase


class TestFactoredStr:
    def test_simple_real(self):
        tf = from_coefficients([1], [1, 1])
        s = factored_str(tf)
        # Should contain (s) or (s + 1) style
        assert isinstance(s, str) and len(s) > 0

    def test_returns_string(self):
        tf = second_order(1.0, 0.5, 1.0)
        s = factored_str(tf)
        assert isinstance(s, str)
