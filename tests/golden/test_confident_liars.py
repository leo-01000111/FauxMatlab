"""
Commands that printed a wrong number without any error.

``docs/PLAN.md`` (Part 5) counts this as the worst way for Evans to fail: a
"confident liar". Each test below types the command the way a user would, at
the MATLAB console, and checks it against a value worked out by hand (or by an
independent route), never against what Evans printed before the fix.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from evans.console import Interpreter, set_figure_sink
from evans.console.figures import recording_sink


@pytest.fixture
def it():
    previous = set_figure_sink(recording_sink())
    yield Interpreter()
    set_figure_sink(previous)


def run(it, source: str):
    """Run MATLAB, insist it succeeded."""
    results = it.run_script(source, "matlab")
    failed = [r for r in results if r.error]
    assert not failed, f"{failed[0].source!r} → {failed[0].error}"


def error_of(it, source: str) -> str:
    """Run MATLAB that must fail; return the error text."""
    results = it.run_script(source, "matlab")
    failed = [r for r in results if r.error]
    assert failed, f"{source!r} ran without an error"
    return str(failed[0].error)


def val(it, name):
    return it.namespace[name]


# ──────────────────────────────────────────────────────────────
#  Discrete models: z = e^{sTs}, not z = s
# ──────────────────────────────────────────────────────────────

def test_damp_maps_discrete_poles_to_the_s_plane(it):
    """
    ``c2d`` maps each pole exactly, ``z = e^{sTs}``, so the s-plane pole comes
    back as ``ln(z)/Ts``. ``1/(s+1)`` has ``ωn = 1, ζ = 1``; the
    ``ωn = 2, ζ = 0.5`` pair keeps those values. ζ was −1 for the first.
    """
    run(it, "Gd = c2d(tf(1,[1 1]),0.1); [wn,z] = damp(Gd);")
    assert val(it, "wn").ravel() == pytest.approx([1.0])
    assert val(it, "z").ravel() == pytest.approx([1.0])
    run(it, "Gd = c2d(tf(4,[1 2 4]),0.1); [wn,z] = damp(Gd);")
    assert val(it, "wn").ravel() == pytest.approx([2.0, 2.0])
    assert val(it, "z").ravel() == pytest.approx([0.5, 0.5])


def test_dcgain_of_discrete_model_is_g_at_one(it):
    """The ZOH equivalent keeps the gain: 2, not ``G(0) = −0.21``."""
    run(it, "k = dcgain(c2d(tf(2,[1 1]),0.1));")
    assert val(it, "k") == pytest.approx(2.0, rel=1e-12)


def test_errconst_of_discrete_loop_uses_z_equals_one(it):
    """
    The ZOH equivalent of ``1/(s(s+1))`` with ``a = e^{−T}`` is

        G(z) = ((T−1+a)z + (1−a−Ta)) / ((z−1)(z−a))

    so ``(z−1)G`` at ``z = 1`` is ``T(1−a)/(1−a) = T`` and ``Kv = T/T = 1``:
    type 1, no step error, ramp error 1. It was reported as type 0.
    """
    run(it, "E = errconst(c2d(tf(1,[1 1 0]),0.1));")
    E = val(it, "E")
    assert E["Type"] == 1
    assert math.isinf(E["Kp"])
    assert E["Kv"] == pytest.approx(1.0, rel=1e-9)
    assert E["ess_step"] == pytest.approx(0.0, abs=1e-12)
    assert E["ess_ramp"] == pytest.approx(1.0, rel=1e-9)


def test_errconst_accepts_state_space(it):
    """``ss`` gave NaN; it is the same loop ``2/(s(s+1))``, Kv = 2."""
    run(it, "E = errconst(ss(tf(2,[1 1 0])));")
    assert val(it, "E")["Kv"] == pytest.approx(2.0, rel=1e-9)


def test_freqresp_of_discrete_model_is_on_the_unit_circle(it):
    """``Gd = (1−a)/(z−a)``, ``a = e^{−0.1}``, evaluated at ``z = e^{j·1·0.1}``."""
    run(it, "Gd = c2d(tf(1,[1 1]),0.1); H = freqresp(Gd, 1);")
    a = math.exp(-0.1)
    expected = (1 - a) / (np.exp(0.1j) - a)
    assert complex(np.ravel(val(it, "H"))[0]) == pytest.approx(expected)


def test_bode_of_discrete_model_stops_at_nyquist(it):
    """Above ``π/Ts`` a sampled response only repeats; MATLAB stops there."""
    run(it, "Gd = c2d(tf(1,[1 1]),0.1); [m,p,w] = bode(Gd);")
    w = np.ravel(val(it, "w"))
    assert w.max() == pytest.approx(math.pi / 0.1)
    assert w.min() < 0.1                        # still spans the corner at 1


# ──────────────────────────────────────────────────────────────
#  Building models
# ──────────────────────────────────────────────────────────────

def test_ss_with_sample_time_keeps_the_discrete_matrices(it):
    """
    MATLAB's ``ss(A,B,C,D,Ts)`` *is* ``x[k+1] = A x[k] + B u[k]``; Evans
    sampled it again by ZOH, so ``A = 0.5`` came out as ``e^{0.05} = 1.05``.
    The pole is therefore 0.5 and the gain ``C(1−A)⁻¹B = 1/(1−0.5) = 2``.
    """
    run(it, "S = ss(0.5,1,1,0,0.1); p = pole(S); k = dcgain(S);")
    S = val(it, "S")
    assert np.asarray(S.A).item() == pytest.approx(0.5)
    assert S.dt == pytest.approx(0.1)
    assert np.ravel(val(it, "p")) == pytest.approx([0.5])
    assert val(it, "k") == pytest.approx(2.0)


def test_tf_with_input_delay_refuses_instead_of_going_discrete(it):
    """``'InputDelay', 2`` was read as ``Ts = 2``: a discrete ``1/(z+1)``."""
    message = error_of(it, "G = tf(1,[1 1],'InputDelay',2)")
    assert "delay" in message and "pade(2, 3)" in message
    run(it, "G = tf(1,[1 1],'InputDelay',0);")       # no delay: nothing lost
    assert val(it, "G").dt == 0


def test_tf_reads_ts_given_as_a_property(it):
    run(it, "G = tf(1,[1 -0.5],'Ts',0.1);")
    assert val(it, "G").dt == pytest.approx(0.1)


def test_zpk_with_sample_time_is_discrete(it):
    """``zpk([],0.5,1,0.1)`` is ``1/(z−0.5)`` at 0.1 s; Ts was dropped."""
    run(it, "Z = zpk([],0.5,1,0.1); k = dcgain(Z);")
    Z = val(it, "Z")
    assert Z.dt == pytest.approx(0.1)
    assert val(it, "k") == pytest.approx(1 / (1 - 0.5))


# ──────────────────────────────────────────────────────────────
#  Analysis
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("source,rhp,jw", [
    ("routh(tf(1,[1 0 1]))", 0, 2),        # 1+G = s²+2: roots ±j√2
    ("routh([1 1 1 1])", 0, 2),            # (s+1)(s²+1)
    ("routh([1 1 2 2 1 1])", 0, 4),        # (s+1)(s²+1)²: ±j twice
    ("routh([1 0 -1])", 1, 0),             # (s−1)(s+1)
])
def test_routh_zero_row_is_marginal_not_stable(it, source, rhp, jw):
    """
    A row of zeros means roots mirrored about the origin. With none in the
    RHP the first column shows no sign change, and ``stable`` came out 1 for
    a loop that oscillates forever. The auxiliary polynomial finds them.
    """
    run(it, f"r = {source};")
    r = val(it, "r")
    assert r.stable is False
    assert r.n_rhp_poles == rhp
    assert r.n_jw_poles == jw
    assert all(np.isfinite(float(c)) for c in r.first_col)


def test_routh_without_axis_roots_is_still_stable(it):
    run(it, "r = routh([1 2 1]);")
    assert val(it, "r").stable is True and val(it, "r").n_jw_poles == 0


def test_stepinfo_of_unstable_system_is_nan_with_infinite_peak(it):
    """
    MATLAB's documented rule: NaN for every characteristic of an unstable
    system except Peak and PeakTime, which are Inf. Evans reported the value
    where its simulation stopped, Peak = 1.9e97.
    """
    for G in ("tf(1,[1 -1])", "tf(1,[1 0])", "c2d(tf(1,[1 -1]),0.1)"):
        run(it, f"S = stepinfo({G});")
        S = val(it, "S")
        assert math.isinf(S.Peak) and math.isinf(S.PeakTime), G
        for field in ("RiseTime", "SettlingTime", "Overshoot", "SteadyState",
                      "SettlingMin", "SettlingMax", "Undershoot"):
            assert math.isnan(S[field]), f"{G}: {field}"


def test_allmargin_delay_margin_with_negative_phase_margin(it):
    """
    ``10/(s+1)³`` crosses 0 dB at ``ω = √(100^{1/3} − 1)`` with phase
    ``−3·atan ω`` ≈ −187°, so PM ≈ −7°. A delay adds lag only, so the next
    −180° crossing needs ``PM + 360°`` of it: ``(PM + 360)·π/180 / ω``.
    ``|PM|/ω`` answered 0.064 s, a delay that would have had to lead.
    """
    run(it, "A = allmargin(tf(10,[1 3 3 1]));")
    w = math.sqrt(100 ** (1 / 3) - 1)
    pm = 180 - 3 * math.degrees(math.atan(w))
    A = val(it, "A")
    assert A["PhaseMargin_deg"] == pytest.approx(pm, rel=1e-6)
    assert A["DelayMargin"] == pytest.approx(math.radians(pm + 360) / w,
                                             rel=1e-6)


def test_allmargin_delay_margin_positive_phase_margin_unchanged(it):
    """``2/(s−1)``: ``|G| = 1`` at ``ω = √3``, phase −120°, PM 60°."""
    run(it, "A = allmargin(tf(2,[1 -1]));")
    assert val(it, "A")["DelayMargin"] == pytest.approx(
        math.radians(60) / math.sqrt(3), rel=1e-6)


def test_dcgain_of_mimo_model_is_the_whole_matrix(it):
    """``−C A⁻¹ B`` with ``A = diag(−1, −2)``, ``B = I``: ``[1 1; 3 2]``."""
    run(it, "k = dcgain(ss([-1 0;0 -2],eye(2),[1 2;3 4],zeros(2)));")
    assert np.asarray(val(it, "k")) == pytest.approx(np.array([[1, 1],
                                                               [3, 2]]))


def test_dcgain_of_product_cancels_the_integrator(it):
    """``s · 1/(s(s+1))`` is ``1/(s+1)`` once the pair cancels: gain 1."""
    run(it, "s = tf('s'); H = 1/(s*(s+1)); k = dcgain(s*H);")
    assert val(it, "k") == pytest.approx(1.0)


def test_rlocus_uses_the_gains_it_is_given(it):
    """
    ``s² + 2s + k = 0`` → ``s = −1 ± √(1−k)``: ``k = 0`` gives 0, −2;
    ``k = 1`` gives −1 twice; ``k = 2`` gives ``−1 ± j``. Evans ignored ``k``
    and returned its own 400 gains.
    """
    run(it, "[r,k] = rlocus(tf(1,[1 2 0]), [0 1 2]);")
    r, k = np.asarray(val(it, "r")), np.ravel(val(it, "k"))
    assert r.shape == (2, 3)
    assert k == pytest.approx([0, 1, 2])
    expected = [[0, -2], [-1, -1], [-1 + 1j, -1 - 1j]]
    for column, roots in zip(r.T, expected):
        assert sorted(column, key=lambda z: (z.real, z.imag)) == \
            pytest.approx(sorted(roots, key=lambda z: (z.real, z.imag)),
                          abs=1e-6)


def test_rlocus_with_one_gain(it):
    run(it, "r = rlocus(tf(1,[1 2 0]), 1);")
    assert np.ravel(val(it, "r")) == pytest.approx([-1, -1], abs=1e-6)


def test_sisotool_refuses_a_negative_gain_compensator(it):
    assert "K ≥ 0" in error_of(it, "sisotool(tf(1,[1 1]), tf(-5,1))")


# ──────────────────────────────────────────────────────────────
#  Arrays
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("source,expected", [
    ("sum([1 2;3 4],2)", [[3], [7]]),          # a column, one sum per row
    ("mean([1 2;3 4],2)", [[1.5], [3.5]]),
    ("sum([1 2;3 4],1)", [4, 6]),
    ("sum([1 2 3],1)", [1, 2, 3]),             # each column is one element
    ("sum([1 2 3],2)", 6),
    ("sum([1 2;3 4],3)", [[1, 2], [3, 4]]),    # size 1 along dim 3
    ("prod([1 2;3 4],2)", [[2], [12]]),
    ("cumsum([1 2 3],1)", [1, 2, 3]),
    ("cumsum([1 2;3 4],2)", [[1, 3], [3, 7]]),
    ("max([1 5;7 2],[],2)", [[5], [7]]),
    ("max([1 5 3],[],1)", [1, 5, 3]),
])
def test_reductions_respect_the_dimension(it, source, expected):
    run(it, f"x = {source};")
    got = val(it, "x")
    if np.ndim(expected) == 0:
        assert np.ndim(got) == 0 and got == pytest.approx(expected)
    else:
        assert np.shape(got) == np.shape(expected), source
        assert np.asarray(got) == pytest.approx(np.asarray(expected))


@pytest.mark.parametrize("source,expected", [
    ("sort([3 1;2 4],2)", [[1, 3], [2, 4]]),   # along each row
    ("sort([3 1;2 4],1)", [[2, 1], [3, 4]]),
    ("sort([3 1;2 4])", [[2, 1], [3, 4]]),
    ("sort([3 1;2 4],2,'descend')", [[3, 1], [4, 2]]),
    ("sort([3 1 2],'descend')", [3, 2, 1]),
])
def test_sort_along_a_dimension(it, source, expected):
    run(it, f"x = {source};")
    assert np.asarray(val(it, "x")).tolist() == expected


def test_sort_complex_by_magnitude_then_angle(it):
    """
    ``|1+i| = 1.41 < |2| = 2 < |−3| = 3``; equal magnitudes go by angle,
    ``−1`` (π) after ``1`` (0) and ``i`` (π/2).
    """
    run(it, "x = sort([-3 1+1i 2]); y = sort([-1 1i 1]);")
    assert np.asarray(val(it, "x")) == pytest.approx([1 + 1j, 2, -3])
    assert np.asarray(val(it, "y")) == pytest.approx([1, 1j, -1])


@pytest.mark.parametrize("fn", ["zeros", "ones", "rand", "randn"])
def test_three_sizes_refuse_instead_of_dropping_one(it, fn):
    assert "N-D" in error_of(it, f"x = {fn}(2,3,4)")
    assert "N-D" in error_of(it, f"x = {fn}([2 3 4])")
    run(it, f"x = {fn}(2,3,1);")                # a trailing 1 is still 2-D
    assert np.shape(val(it, "x")) == (2, 3)


def test_logspace_to_pi_ends_at_pi(it):
    """MATLAB: ``logspace(a, pi)`` runs from ``10^a`` to π, not to ``10^π``."""
    run(it, "x = logspace(0,pi,3); y = logspace(0,2,3);")
    assert np.ravel(val(it, "x")) == pytest.approx(
        [1, math.sqrt(math.pi), math.pi])
    assert np.ravel(val(it, "y")) == pytest.approx([1, 10, 100])


def test_repmat_text_refuses_more_than_one_row(it):
    """Evans has no char matrix; ``'ab'`` for two rows was one row."""
    assert "multi-row text" in error_of(it, "x = repmat('ab',2,1)")
    run(it, "x = repmat('ab',1,3);")
    assert val(it, "x") == "ababab"


def test_clear_with_wildcard_and_regexp(it):
    run(it, "K1 = 1; K2 = 2; Kp = 3; x = 4; clear K*")
    assert not {"K1", "K2", "Kp"} & set(it.namespace) and "x" in it.namespace
    run(it, "a1 = 1; a2 = 2; ab = 3; clear -regexp ^a[0-9]")
    assert {"a1", "a2"}.isdisjoint(it.namespace) and "ab" in it.namespace
