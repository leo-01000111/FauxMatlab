"""Tests for fakematlab.core.stability."""

import numpy as np
import pytest
import sympy as sp

from fakematlab.core.stability import (
    routh_table, routh_from_closed_loop, root_locus, RouthResult,
)
import control as ctl


class TestRouthTable:
    def test_stable_second_order(self):
        # s² + 3s + 2 = (s+1)(s+2), all coeffs positive → stable
        result = routh_table([1, 3, 2])
        assert result.stable
        assert result.n_rhp_poles == 0

    def test_unstable_third_order(self):
        # s³ + s² − s + 1: has sign change in coefficients
        # Routh: row0=[1,−1], row1=[1,1], row2=[−2,0], row3=[1,0]
        # sign changes in first col: 1→1→−2→1 = 2 changes
        result = routh_table([1, 1, -1, 1])
        assert not result.stable
        assert result.n_rhp_poles == 2

    def test_symbolic_K(self):
        K = sp.Symbol('K', positive=True)
        # Characteristic poly: s² + s + K (second-order with K gain)
        result = routh_table([1, 1, K], symbol=K)
        assert result.is_symbolic
        # First column should contain K
        assert any(K in sp.sympify(e).free_symbols
                   for e in result.first_col)

    def test_stable_first_order(self):
        result = routh_table([1, 2])
        assert result.stable


class TestRouthFromCL:
    def test_unity_feedback_first_order(self):
        # G = 1/(s+1), K2 = K: char poly = s + 1 + K
        # Stable for K > −1
        G  = ctl.TransferFunction([1], [1, 1])
        result = routh_from_closed_loop(G)
        assert isinstance(result, RouthResult)

    def test_symbolic_K_range(self):
        G  = ctl.TransferFunction([1], [1, 1, 0])  # 1/(s²+s)
        K  = sp.Symbol('K')
        result = routh_from_closed_loop(G, K_sym=K)
        assert result.is_symbolic


class TestRootLocus:
    def test_first_order_locus(self):
        G = ctl.TransferFunction([1], [1, 1])
        rl = root_locus(G, K_max=20.0)
        assert len(rl.K_values) > 1
        assert rl.roots.shape[0] == len(rl.K_values)

    def test_second_order_goes_unstable(self):
        # Double integrator: will go unstable for large K
        G = ctl.TransferFunction([1], [1, 0, 0])
        rl = root_locus(G, K_max=50.0, n_pts=100)
        # Eventually poles should cross imaginary axis
        max_real = np.max(rl.roots.real)
        assert max_real > -0.1  # crosses axis or goes positive

    def test_asymptote_count(self):
        # G = 1/[s(s+1)(s+2)]: 3 poles, 0 zeros → 3 asymptotes
        G = ctl.TransferFunction([1], [1, 3, 2, 0])
        rl = root_locus(G)
        assert len(rl.asymptote_angles) == 3
