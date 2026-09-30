"""Minimum-phase / all-pass split against analytic values (ch.4, 44/46)."""

import control as ctl
import numpy as np
import pytest

from fakematlab.core.minphase import minimum_phase_split

W = np.logspace(-2, 3, 400)


def _fr(tf, w=W):
    s = 1j * w
    return (np.polyval(tf.num[0][0], s) / np.polyval(tf.den[0][0], s))


def _check_identities(G, split):
    g, ap, mp = _fr(G), _fr(split.allpass), _fr(split.minphase)
    assert np.allclose(ap * mp, g, rtol=1e-6, atol=1e-12)
    assert np.allclose(np.abs(ap), 1.0, atol=1e-9)
    assert np.allclose(np.abs(g), np.abs(mp), rtol=1e-6)
    assert all(z.real <= 1e-9 for z in np.atleast_1d(ctl.zeros(split.minphase)))


def test_first_order_rhp_zero():
    G = ctl.tf([-1, 1], [1, 1])
    sp = minimum_phase_split(G)
    assert not sp.is_minimum_phase
    assert np.allclose(sp.rhp_zeros, [1]) and np.allclose(sp.mirrored_zeros, [-1])
    # The slide's convention: ñ⁺/ñ⁻ with monic factors, so (s−1)/(s+1)…
    assert np.allclose(_fr(sp.allpass), _fr(ctl.tf([1, -1], [1, 1])))
    # …and the sign that leaves over sits in G_mp.
    assert np.allclose(_fr(sp.minphase), -1.0)
    _check_identities(G, sp)


def test_mixed_zeros():
    den = np.polymul(np.polymul([1, 1], [1, 4]), [1, 5])
    G = ctl.tf(np.polymul([1, -2], [1, 3]), den)
    sp = minimum_phase_split(G)
    # One RHP zero: G_ap = (s−2)/(s+2) starts at −1, and G_mp keeps G's gain.
    assert np.allclose(sp.allpass.dcgain(), -1.0)
    assert np.allclose(_fr(sp.allpass), _fr(ctl.tf([1, -2], [1, 2])))
    assert np.allclose(np.real(sp.rhp_zeros), [2])
    expected = _fr(ctl.tf(np.polymul([1, 2], [1, 3]), den))
    assert np.allclose(_fr(sp.minphase), expected)
    _check_identities(G, sp)


def test_complex_rhp_pair():
    G = ctl.tf(np.polymul([1, -2, 5], [1, 1]), [1, 3, 3, 1])   # zeros 1 +/- 2j
    sp = minimum_phase_split(G)
    assert len(sp.rhp_zeros) == 2
    assert np.allclose(sorted(np.imag(sp.rhp_zeros)), [-2, 2])
    assert np.allclose(sp.allpass.dcgain(), 1.0)      # (−1)² = +1
    _check_identities(G, sp)


def test_repeated_rhp_zero():
    G = ctl.tf(np.polymul([1, -1], [1, -1]), [1, 4, 6, 4, 1])
    sp = minimum_phase_split(G)
    assert len(sp.rhp_zeros) == 2
    _check_identities(G, sp)


def test_already_minimum_phase():
    G = ctl.tf([1, 2], [1, 3, 2])
    sp = minimum_phase_split(G)
    assert sp.is_minimum_phase and "Already minimum phase" in sp.explanation
    assert np.allclose(_fr(sp.allpass), 1.0)
    assert np.allclose(_fr(sp.minphase), _fr(G))


def test_axis_zeros_stay_in_mp():
    G = ctl.tf([1, 0, 4], [1, 2, 3, 1])       # zeros +/- 2j
    sp = minimum_phase_split(G)
    assert sp.is_minimum_phase and len(sp.imag_axis_zeros) == 2
    assert "imaginary axis" in sp.explanation
    assert minimum_phase_split(ctl.tf([1, 0], [1, 1])).is_minimum_phase


def test_rhp_poles_mentioned_not_touched():
    G = ctl.tf([-1, 1], [1, -2])
    sp = minimum_phase_split(G)
    assert len(sp.rhp_poles) == 1 and "RHP pole" in sp.explanation
    assert np.allclose(ctl.poles(sp.minphase), [2])
    _check_identities(G, sp)


def test_unpacking_and_errors():
    Gap, Gmp = minimum_phase_split(ctl.tf([-1, 1], [1, 1]))
    assert Gap is not None and Gmp is not None
    mimo = ctl.tf([[[1], [1]]], [[[1, 1], [1, 2]]])
    with pytest.raises(ValueError, match="SISO"):
        minimum_phase_split(mimo)
    with pytest.raises(ValueError, match="continuous"):
        minimum_phase_split(ctl.tf([1], [1, -0.5], dt=1))
