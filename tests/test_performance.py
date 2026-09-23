"""Tests for fakematlab.core.performance."""

import numpy as np
import pytest
import control as ctl

from fakematlab.core.performance import analyse_performance
from fakematlab.core.tf_utils import first_order, integrator


class TestPerformance:
    def test_type_0_position_error(self):
        # Type-0 system: e_ss(step) = 1/(1+Kp)
        G  = first_order(K=4.0, tau=1.0)   # L = 4/(s+1), Kp = 4
        rpt = analyse_performance(G)
        assert rpt.system_type == 0
        assert abs(rpt.Kp - 4.0) < 0.1
        # e_ss = 1/(1+4) = 0.2
        assert abs(rpt.ess_step - 0.2) < 0.01

    def test_type_0_ramp_error_inf(self):
        G  = first_order(K=1.0, tau=1.0)
        rpt = analyse_performance(G)
        assert rpt.ess_ramp == float('inf')

    def test_type_1_zero_step_error(self):
        # L = K/s(s+1) → type 1, zero step error
        G = integrator(1.0) * first_order(1.0, 1.0)
        rpt = analyse_performance(G)
        assert rpt.system_type == 1
        assert rpt.ess_step == 0.0

    def test_type_1_finite_ramp_error(self):
        G = integrator(2.0)  # L = 2/s, Kv = 2
        rpt = analyse_performance(G)
        assert rpt.system_type == 1
        assert abs(rpt.Kv - 2.0) < 0.01
        assert abs(rpt.ess_ramp - 0.5) < 0.01

    def test_type_1_infinite_parabola_error(self):
        G = integrator(1.0)
        rpt = analyse_performance(G)
        assert rpt.ess_parabola == float('inf')

    def test_summary_string(self):
        G = first_order(1.0, 1.0)
        rpt = analyse_performance(G)
        assert "System type" in rpt.summary
        assert "Kp" in rpt.summary
