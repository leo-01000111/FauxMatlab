"""
All twelve closed-loop transfer functions, against hand-solved algebra.

This is the test v1 did not have. Six of its twelve transfer functions were
wrong — ``di→u`` was missing a plant factor, ``n→e`` had a flipped sign,
``r→e`` dropped the feedforward, and the whole ``u`` row ignored ``H`` — yet
its architecture tests passed, because they only checked that a
``TransferFunction`` came back.
"""

from __future__ import annotations

import control as ctl
import numpy as np
import pytest

from fakematlab.core.architecture import (
    INPUT_SIGNALS,
    OUTPUT_SIGNALS,
    CourseArchitecture,
)
from fakematlab.core.signal_graph import SignalGraph

# Deliberately awkward blocks: a feedforward that is not 1, a sensor that is
# not 1, and an integrating controller.
G_T  = ctl.tf([1.0], [1.0, 1.0])
K2_T = ctl.tf([2.0, 1.0], [1.0, 0.0])
K1_T = ctl.tf([3.0], [1.0, 2.0])
H_T  = ctl.tf([1.0], [0.5, 1.0])

#: Points scattered off the real and imaginary axes, where a sign error or a
#: missing factor cannot hide.
PROBES = [0.7 + 1.3j, -0.4 + 2.1j, 3.0 + 0.5j, 0.05 + 0.05j]


def _ev(tf: ctl.TransferFunction, s: complex) -> complex:
    return complex(np.polyval(np.atleast_1d(tf.num[0][0]), s) /
                   np.polyval(np.atleast_1d(tf.den[0][0]), s))


def _truth(s: complex, G, K2, K1, H) -> dict[tuple[str, str], complex]:
    """
    Solve the ch.5 loop by hand at one point in the s-plane.

        e = K₁·r − H·(y + n)
        u = K₂·e + di              (plant input)
        y = G·u + do

    Eliminating e gives e·(1 + G·K₂·H) = K₁·r − H·(G·di + do + n).
    """
    g, k2, k1, h = _ev(G, s), _ev(K2, s), _ev(K1, s), _ev(H, s)
    out: dict[tuple[str, str], complex] = {}
    for inp in INPUT_SIGNALS:
        r, di, do, n = (1.0 if inp == name else 0.0 for name in INPUT_SIGNALS)
        e = (k1 * r - h * (g * di + do + n)) / (1.0 + g * k2 * h)
        u = k2 * e + di
        y = g * u + do
        out[(inp, "y")], out[(inp, "u")], out[(inp, "e")] = y, u, e
    return out


ARCHITECTURES = {
    "K1=1, H=1":    (G_T, K2_T, ctl.tf([1], [1]), ctl.tf([1], [1])),
    "K1≠1, H=1":    (G_T, K2_T, K1_T,             ctl.tf([1], [1])),
    "K1=1, H≠1":    (G_T, K2_T, ctl.tf([1], [1]), H_T),
    "K1≠1, H≠1":    (G_T, K2_T, K1_T,             H_T),
}


@pytest.mark.parametrize("case", list(ARCHITECTURES))
@pytest.mark.parametrize("inp", INPUT_SIGNALS)
@pytest.mark.parametrize("out", OUTPUT_SIGNALS)
def test_closed_loop_tf_matches_hand_algebra(case, inp, out):
    G, K2, K1, H = ARCHITECTURES[case]
    arch = CourseArchitecture(G=G, K2=K2, K1=K1, H=H)
    tf = arch.get_closed_loop_tf(inp, out)

    for s in PROBES:
        expected = _truth(s, G, K2, K1, H)[(inp, out)]
        got = _ev(tf, s)
        assert got == pytest.approx(expected, rel=1e-9, abs=1e-12), (
            f"{case}: {inp}→{out} at s={s} gave {got}, expected {expected}"
        )


def test_di_to_u_carries_the_plant():
    """
    ``di → u`` is ``1 − S·K₂·G``, which for unity feedback is exactly ``S``.

    ``u`` is the **plant input**: ``u = K₂·e + di``. The disturbance therefore
    reaches ``u`` twice — directly, and again after travelling through the
    plant and back around the loop — so the plant factor must appear. This
    matches the course's own equation (ch.5, slide 19/24), where the
    coefficient of ``di`` in the ``u`` row is ``1/(1 + G·K₂)``.

    v1 returned ``−S·K₂``, which is wrong under either convention: the
    controller-output reading would be ``−S·K₂·G``, and neither has the
    direct feedthrough term.
    """
    arch = CourseArchitecture(G=G_T, K2=K2_T)
    got = arch.get_closed_loop_tf("di", "u")
    S = arch.sensitivity()
    one = ctl.tf([1], [1])

    for s in PROBES:
        assert _ev(got, s) == pytest.approx(_ev(one - S * K2_T * G_T, s),
                                            rel=1e-9)
        # With H = 1 this collapses to S, since S·K₂·G = T = 1 − S.
        assert _ev(got, s) == pytest.approx(_ev(S, s), rel=1e-9)
        # ...and is emphatically not the v1 answer.
        assert _ev(got, s) != pytest.approx(_ev(-S * K2_T, s), rel=1e-6)


def test_n_to_e_is_negative():
    """``n → e`` is ``−S``: noise adds to the measurement, so it subtracts
    from the error. v1 returned ``+S``."""
    arch = CourseArchitecture(G=G_T, K2=K2_T)
    got = arch.get_closed_loop_tf("n", "e")
    expected = -arch.sensitivity()
    for s in PROBES:
        assert _ev(got, s) == pytest.approx(_ev(expected, s), rel=1e-9)


def test_r_to_e_includes_feedforward():
    """``r → e`` is ``S·K₁``. v1 dropped ``K₁`` and returned ``S``."""
    arch = CourseArchitecture(G=G_T, K2=K2_T, K1=K1_T)
    got = arch.get_closed_loop_tf("r", "e")
    expected = arch.sensitivity() * K1_T
    for s in PROBES:
        assert _ev(got, s) == pytest.approx(_ev(expected, s), rel=1e-9)


def test_sensor_h_changes_r_to_y():
    """
    With ``H ≠ 1``, ``r → y`` is **not** ``T·K₁``.

    v1 returned ``T·K₁`` unconditionally, so editing the ``H`` block on the
    canvas changed the loop transfer function but not the response — the two
    silently disagreed.
    """
    arch = CourseArchitecture(G=G_T, K2=K2_T, K1=K1_T, H=H_T)
    got = arch.get_closed_loop_tf("r", "y")
    v1_answer = arch.compl_sensitivity() * K1_T
    s = PROBES[0]
    assert _ev(got, s) != pytest.approx(_ev(v1_answer, s), rel=1e-3)
    assert _ev(got, s) == pytest.approx(
        _truth(s, G_T, K2_T, K1_T, H_T)[("r", "y")], rel=1e-9)


# ──────────────────────────────────────────────────────────────
#  Cross-check against the independent numerical solver
# ──────────────────────────────────────────────────────────────

def _oracle_graph(G, K2, K1, H) -> SignalGraph:
    """The same architecture built for the numerical solver."""
    g = SignalGraph()
    g.add_block("K1", K1); g.add_block("K2", K2)
    g.add_block("G", G);   g.add_block("H", H)
    for nid in ("r", "di", "do", "n", "e", "u", "y", "sum_e", "sum_y", "sum_m"):
        g.add_wire(nid)
    for sig in INPUT_SIGNALS:
        g.add_external_input(sig)
    for sig in OUTPUT_SIGNALS:
        g.add_external_output(sig)
    for src, dst, gain in [
        ("r", "K1", 1), ("K1", "sum_e", 1), ("H", "sum_e", -1),
        ("sum_e", "e", 1), ("e", "K2", 1), ("K2", "u", 1), ("di", "u", 1),
        ("u", "G", 1), ("G", "sum_y", 1), ("do", "sum_y", 1),
        ("sum_y", "y", 1), ("y", "sum_m", 1), ("n", "sum_m", 1),
        ("sum_m", "H", 1),
    ]:
        g.connect(src, dst, gain=gain)
    return g


@pytest.mark.parametrize("inp", INPUT_SIGNALS)
@pytest.mark.parametrize("out", OUTPUT_SIGNALS)
def test_exact_solver_agrees_with_numerical_oracle(inp, out):
    """
    The exact symbolic solver and the numerical matrix solver must agree.

    They share no code: one clears denominators and solves over ℚ(s) with
    sympy, the other inverts a complex matrix at each frequency. A bug would
    have to be made twice, identically, to pass this.
    """
    arch = CourseArchitecture(G=G_T, K2=K2_T, K1=K1_T, H=H_T)
    graph = _oracle_graph(G_T, K2_T, K1_T, H_T)

    omega = np.logspace(-2, 2, 40)
    _, numeric = graph.frequency_response(inp, out, omega)
    exact = np.array([_ev(arch.get_closed_loop_tf(inp, out), 1j * w)
                      for w in omega])

    assert np.allclose(exact, numeric, rtol=1e-8, atol=1e-10)
