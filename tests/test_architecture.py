"""Tests for fakematlab.core.architecture."""

import numpy as np
import pytest
import control as ctl

from fakematlab.core.architecture import CourseArchitecture
from fakematlab.core.tf_utils import first_order, second_order, unity


class TestArchitecture:
    def setup_method(self):
        # Simple plant: G = 1/(s+1), K2 = 1 (unity feedback)
        self.G  = first_order(1.0, 1.0)   # 1/(s+1)
        self.K2 = unity()
        self.arch = CourseArchitecture(G=self.G, K2=self.K2)

    def test_loop_tf(self):
        L = self.arch.loop_tf()
        poles = ctl.poles(L)
        assert np.allclose(sorted(poles.real), [-1.0], atol=1e-6)

    def test_sensitivity_dc(self):
        S = self.arch.sensitivity()
        # DC: S(0) = 1/(1 + L(0)) = 1/(1 + 1) = 0.5
        val = float(np.polyval(S.num[0][0], 0) / np.polyval(S.den[0][0], 0))
        assert abs(val - 0.5) < 1e-6

    def test_compl_sensitivity_dc(self):
        T = self.arch.compl_sensitivity()
        val = float(np.polyval(T.num[0][0], 0) / np.polyval(T.den[0][0], 0))
        assert abs(val - 0.5) < 1e-6

    def test_S_plus_T_equals_1(self):
        S = self.arch.sensitivity()
        T = self.arch.compl_sensitivity()
        sum_tf = S + T
        # Should be identically 1
        omega = np.logspace(-2, 2, 100)
        mag, _, _ = ctl.bode(sum_tf, omega=omega, plot=False)
        assert np.allclose(mag, 1.0, atol=1e-6)

    def test_hry_with_unity_k1(self):
        # With K1=1: H_ry = T
        T    = self.arch.compl_sensitivity()
        Hry  = self.arch.get_closed_loop_tf("r", "y")
        omega = np.logspace(-2, 2, 50)
        mag_T,  _, _ = ctl.bode(T,   omega=omega, plot=False)
        mag_Hry, _, _ = ctl.bode(Hry, omega=omega, plot=False)
        assert np.allclose(mag_T, mag_Hry, atol=1e-6)

    def test_set_block_invalidates_cache(self):
        before = self.arch.get_closed_loop_tf("r", "y")
        self.arch.set_block("G", second_order(1.0, 0.5, 1.0))
        after = self.arch.get_closed_loop_tf("r", "y")
        # The memoised solve must not survive an edit to a block: a 1st-order
        # plant gives a 1st-order closed loop, a 2nd-order plant a 2nd-order one.
        assert len(np.atleast_1d(before.den[0][0])) == 2
        assert len(np.atleast_1d(after.den[0][0])) == 3

    def test_all_input_output_pairs(self):
        inputs  = ("r", "di", "do", "n")
        outputs = ("y", "u", "e")
        for inp in inputs:
            for out in outputs:
                tf = self.arch.get_closed_loop_tf(inp, out)
                assert isinstance(tf, ctl.TransferFunction), \
                    f"Failed for ({inp}, {out})"

    def test_unknown_input_raises(self):
        with pytest.raises(ValueError):
            self.arch.get_closed_loop_tf("bad_input", "y")

    def test_model_exposes_blocks_and_ports(self):
        m = self.arch.model
        assert {"K1", "K2", "G", "H"} <= set(m.node_ids)
        assert "r" in m.inputs
        assert "y" in m.outputs

    def test_unstable_plant(self):
        """Unstable G should give unstable loop, but stable CL with high K2."""
        G_unstable = ctl.TransferFunction([1], [1, -1])  # 1/(s-1)
        K2_high    = ctl.TransferFunction([10], [1])      # K=10
        arch = CourseArchitecture(G=G_unstable, K2=K2_high)
        T    = arch.compl_sensitivity()
        poles_T = ctl.poles(T)
        # All closed-loop poles should be in LHP
        assert all(p.real < 0 for p in poles_T), \
            f"Closed-loop poles not stable: {poles_T}"
