"""Tests for fakematlab.core.timeresp."""

import numpy as np
import pytest
import control as ctl

from fakematlab.core.timeresp import (
    step_response, impulse_response, ramp_response,
    compute_step_metrics, parameter_sweep,
)
from fakematlab.core.tf_utils import first_order, second_order


class TestStepResponse:
    def test_first_order_dc_gain(self):
        # G = 1/(s+1): step response should settle at 1
        tf = first_order(1.0, 1.0)
        resp = step_response(tf)
        assert abs(resp.y[-1] - 1.0) < 0.05  # within 5% at end

    def test_amplitude_scaling(self):
        tf = first_order(1.0, 1.0)
        resp2 = step_response(tf, amplitude=2.0)
        assert abs(resp2.y[-1] - 2.0) < 0.1

    def test_step_output_shape(self):
        tf = second_order(1.0, 0.5, 1.0)
        resp = step_response(tf)
        assert resp.t.shape == resp.y.ravel().shape
        assert len(resp.t) > 10


class TestImpulseResponse:
    def test_first_order_integral(self):
        # Integral of impulse response = DC gain
        tf = first_order(1.0, 1.0)
        resp = impulse_response(tf)
        integral = np.trapz(resp.y.ravel(), resp.t)
        assert abs(integral - 1.0) < 0.05


class TestStepMetrics:
    def test_underdamped_overshoot(self):
        # zeta=0.1 → lots of overshoot
        tf = second_order(1.0, 0.1, 1.0)
        resp = step_response(tf)
        m = compute_step_metrics(resp)
        assert m.Mp_pct > 50, f"Expected overshoot > 50%, got {m.Mp_pct:.1f}%"
        assert m.tp > 0

    def test_overdamped_no_overshoot(self):
        tf = second_order(1.0, 2.0, 1.0)
        resp = step_response(tf)
        m = compute_step_metrics(resp)
        assert m.Mp_pct < 1.0, f"Expected no overshoot, got {m.Mp_pct:.2f}%"

    def test_settling_time_order(self):
        tf = second_order(1.0, 0.5, 1.0)
        resp = step_response(tf)
        m = compute_step_metrics(resp)
        # ts_2% ≥ ts_5% (tighter band → later settling)
        if not np.isnan(m.ts_2pct) and not np.isnan(m.ts_5pct):
            assert m.ts_2pct >= m.ts_5pct - 1e-6

    def test_dc_gain(self):
        tf = first_order(2.0, 1.0)  # DC gain = 2
        resp = step_response(tf, amplitude=1.0)
        m = compute_step_metrics(resp)
        assert abs(m.dc_gain - 2.0) < 0.1

    def test_y_inf_steady_state(self):
        tf = first_order(3.0, 0.5)
        resp = step_response(tf)
        m = compute_step_metrics(resp)
        assert abs(m.y_inf - 3.0) < 0.1


class TestParameterSweep:
    def test_sweep_length(self):
        import control as ctl
        G = first_order(1.0, 1.0)
        K_vals = [0.5, 1.0, 2.0, 5.0]
        result = parameter_sweep(
            lambda K: ctl.feedback(K * G, ctl.TransferFunction([1], [1])),
            param_values=K_vals,
            param_name="K",
        )
        assert len(result.responses) == len(K_vals)

    def test_sweep_labels(self):
        G = first_order(1.0, 1.0)
        result = parameter_sweep(
            lambda K: ctl.feedback(K * G, ctl.TransferFunction([1], [1])),
            param_values=[1.0, 2.0],
            param_name="K",
        )
        assert "K = 1" in result.responses[0].label
        assert "K = 2" in result.responses[1].label
