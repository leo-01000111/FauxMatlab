"""
Phase-2 features: symbolic Routh ranges, the delay model, the sensitivity
integral, session round-trips and the text report.
"""

from __future__ import annotations

import json

import control as ctl
import numpy as np
import pytest
import sympy as sp

from fakematlab.core.architecture import CourseArchitecture
from fakematlab.core.performance import waterbed
from fakematlab.core.report import text_report
from fakematlab.core.session import (
    SESSION_VERSION,
    architecture_from_session,
    load_session_dict,
    session_dict,
)
from fakematlab.core.stability import routh_from_closed_loop
from fakematlab.core.tf_utils import factored_str, first_order, pure_delay_pade
from fakematlab.core.tuning import zn_step

# ──────────────────────────────────────────────────────────────
#  Symbolic Routh (ch.6, 6/26)
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("den,expected", [
    ([1, 3, 2, 0], "0 < K < 6"),      # 1/(s(s+1)(s+2))
    ([1, 3, 3, 1], "-1 < K < 8"),     # 1/(s+1)³
    ([1, 1, 0],    "K > 0"),          # 1/(s(s+1))
    ([1, -1],      "K > 1"),          # 1/(s−1): gain must beat the RHP pole
])
@pytest.mark.parametrize("assumptions", [{}, {"real": True}])
def test_symbolic_stability_range(den, expected, assumptions):
    """
    Routh with a free K must produce the interval, not give up.

    v1 solved each first-column inequality separately and joined the strings,
    never intersecting them, so it reported "Cannot determine symbolically"
    for the standard textbook cases.
    """
    K = sp.Symbol("K", **assumptions)
    result = routh_from_closed_loop(ctl.tf([1], den), K_sym=K)
    assert result.K_stable_range == expected


def test_symbolic_range_is_consistent_with_marginal_gain():
    """The upper bound must agree with the exact imaginary-axis crossing."""
    from fakematlab.core.stability import marginal_gain

    G = ctl.tf([1], [1, 3, 2, 0])
    K = sp.Symbol("K", real=True)
    text = routh_from_closed_loop(G, K_sym=K).K_stable_range
    upper = float(text.split("<")[-1])
    assert marginal_gain(G)[0] == pytest.approx(upper, rel=1e-9)


# ──────────────────────────────────────────────────────────────
#  Delay, and the Z-N path it unlocks
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("T,order", [(0.2, 2), (0.5, 3), (1.0, 4)])
def test_pade_is_all_pass_with_the_right_phase(T, order):
    from fakematlab.core.freqresp import response

    delay = pure_delay_pade(T, order)
    omega = np.linspace(0.05, order / T * 0.5, 40)
    mag, phase = response(delay, omega)
    assert np.allclose(mag, 1.0, atol=1e-9), "a delay must not change gain"
    assert np.allclose(np.unwrap(phase), -omega * T, rtol=0.02, atol=0.02)


def test_fopdt_makes_the_reaction_curve_method_work():
    """
    The reaction-curve method needs dead time. With the Padé block exposed in
    the editor, a FOPDT plant can be built and Z-N recovers its parameters.
    v1 had the delay function but never wired it up, so the button could not
    succeed on any plant the UI could produce.
    """
    tau, L = 2.0, 0.5
    plant = first_order(K=1.0, tau=tau) * pure_delay_pade(L, 3)
    result = zn_step(plant)
    assert result.L == pytest.approx(L, rel=0.1)
    assert result.T == pytest.approx(tau, rel=0.2)
    assert result.PID_params.Kp > 0


# ──────────────────────────────────────────────────────────────
#  Bode–Freudenberg (ch.7, 18/20)
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("num,den", [
    ([1], [1, 3, 3, 1]),        # stable, relative degree 3
    ([2], [1, 3, 3, 1]),
    ([1], [1, 2, 1, 0]),        # integrator, relative degree 3
])
def test_sensitivity_integral_is_zero_for_stable_plants(num, den):
    result = waterbed(ctl.tf(num, den))
    assert result.applies
    assert result.theoretical == pytest.approx(0.0, abs=1e-12)
    assert result.integral == pytest.approx(0.0, abs=1e-4)


def test_sensitivity_integral_equals_pi_sum_rhp_poles():
    """An RHP pole at +1 forces ∫ln|S|dω = π."""
    result = waterbed(ctl.tf([8], [1, 2, -3]))     # poles at +1 and −3
    assert result.applies
    assert result.theoretical == pytest.approx(np.pi, rel=1e-9)
    assert result.integral == pytest.approx(np.pi, rel=1e-4)
    assert result.area_above > abs(result.area_below), (
        "an RHP pole forces net amplification"
    )


def test_waterbed_refuses_when_closed_loop_is_unstable():
    """
    The theorem assumes a stable closed loop. Reporting a number for an
    unstable one would look like a violation of the theorem rather than a
    system outside its hypotheses.
    """
    result = waterbed(ctl.tf([1], [1, 1, 0, 0]))   # 1/(s²(s+1)): unstable CL
    assert result.closed_loop_stable is False
    assert result.applies is False
    assert "unstable" in result.note.lower()


# ──────────────────────────────────────────────────────────────
#  Session round-trip
# ──────────────────────────────────────────────────────────────

def _sample_arch() -> CourseArchitecture:
    return CourseArchitecture(
        G=ctl.tf([1.0], [1.0, 0.4, 2.0]),
        K2=ctl.tf([2.0, 0.5], [1.0, 0.0]),
        K1=ctl.tf([3.0], [1.0, 2.0]),
        H=ctl.tf([1.0], [0.5, 1.0]),
    )


def test_session_round_trips_through_json():
    """
    Save → JSON text → load must preserve every block exactly.

    v1 had save and load but no test; a round trip was never verified.
    """
    original = _sample_arch()
    text = json.dumps(session_dict(original))
    restored = architecture_from_session(json.loads(text))

    for bid in ("G", "K2", "K1", "H"):
        before, after = original.block_tf(bid), restored.block_tf(bid)
        assert np.allclose(np.atleast_1d(before.num[0][0]),
                           np.atleast_1d(after.num[0][0]))
        assert np.allclose(np.atleast_1d(before.den[0][0]),
                           np.atleast_1d(after.den[0][0]))

    # ...and so must the analysis derived from them.
    s = 0.3 + 1.1j
    for inp in ("r", "di", "do", "n"):
        for out in ("y", "u", "e"):
            a = original.get_closed_loop_tf(inp, out)
            b = restored.get_closed_loop_tf(inp, out)
            ev = lambda tf: np.polyval(np.atleast_1d(tf.num[0][0]), s) / \
                            np.polyval(np.atleast_1d(tf.den[0][0]), s)
            assert ev(a) == pytest.approx(ev(b), rel=1e-12)


def test_session_reads_the_v1_layout():
    """Older files had the blocks at the top level with no version marker."""
    legacy = {"G": {"num": [1.0], "den": [1.0, 1.0]},
              "K2": {"num": [4.0], "den": [1.0]}}
    arch = CourseArchitecture()
    load_session_dict(arch, legacy)
    assert np.allclose(np.atleast_1d(arch.block_tf("K2").num[0][0]), [4.0])


def test_session_rejects_a_newer_format():
    arch = CourseArchitecture()
    with pytest.raises(ValueError, match="newer version"):
        load_session_dict(arch, {"version": SESSION_VERSION + 1, "blocks": {}})


def test_corrupt_session_leaves_the_architecture_untouched():
    """A bad block must not half-apply the file."""
    arch = _sample_arch()
    before = np.atleast_1d(arch.block_tf("G").den[0][0]).copy()
    bad = session_dict(arch)
    bad["blocks"]["K2"] = {"num": [1.0]}          # no denominator

    with pytest.raises(ValueError, match="malformed"):
        load_session_dict(arch, bad)
    assert np.allclose(np.atleast_1d(arch.block_tf("G").den[0][0]), before)


def test_session_rejects_a_zero_denominator():
    arch = CourseArchitecture()
    with pytest.raises(ValueError, match="denominator"):
        load_session_dict(arch, {"blocks": {"G": {"num": [1.0],
                                                  "den": [0.0, 0.0]}}})


# ──────────────────────────────────────────────────────────────
#  Report
# ──────────────────────────────────────────────────────────────

def test_report_contains_every_section():
    report = text_report(_sample_arch())
    for heading in ("BLOCKS", "DERIVED TRANSFER FUNCTIONS", "CLOSED LOOP",
                    "INTERNAL STABILITY", "STEP RESPONSE",
                    "STABILITY MARGINS", "STEADY-STATE PERFORMANCE"):
        assert heading in report
    # All twelve closed-loop pairs are listed.
    for inp in ("r", "di", "do", "n"):
        for out in ("y", "u", "e"):
            assert f"{inp} → {out}" in report


def test_report_warns_about_a_deceptive_loop():
    arch = CourseArchitecture(G=ctl.tf([1], [1, -1]),
                              K2=ctl.tf([1, -1], [1, 2]))
    report = text_report(arch)
    assert "NOT internally stable" in report


# ──────────────────────────────────────────────────────────────
#  Factored form
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("num,den,expected", [
    ([1], [1],              "1"),
    ([2.5], [1],            "2.5"),
    ([1], [1, 0, 0],        "1 / s²"),
    ([1], [1, 3, 3, 1],     "1 / (s + 1)³"),
    ([1], [1, 4, 4],        "1 / (s + 2)²"),
    ([4], [1, 1.2, 4],      "4 / (s² + 1.2s + 4)"),
])
def test_factored_form_reads_like_algebra(num, den, expected):
    """
    Repeated roots collapse to powers and a unit denominator disappears.

    ``np.roots`` splits a triple real root into a near-conjugate cluster, so
    without cleaning, ``1/(s+1)³`` printed as ``(s² + 2s + 1)(s + 1)``.
    """
    assert factored_str(ctl.tf(num, den)) == expected
