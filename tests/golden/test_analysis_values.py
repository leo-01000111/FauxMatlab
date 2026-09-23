"""
Numerical results against closed-form theory.

Each value here has a textbook answer (ch.3, ch.4, ch.6, ch.8), so these tests
pin behaviour to the mathematics rather than to the current implementation.
"""

from __future__ import annotations

import control as ctl
import numpy as np
import pytest

from fakematlab.core.architecture import CourseArchitecture
from fakematlab.core.freqresp import bode, nichols_m_contour, nyquist, response
from fakematlab.core.stability import marginal_gain, root_locus
from fakematlab.core.tf_utils import dc_gain, pure_delay_pade, second_order
from fakematlab.core.timeresp import compute_step_metrics, step_response
from fakematlab.core.tuning import zn_ultimate

# ──────────────────────────────────────────────────────────────
#  ch.4 — second-order step-response metrics in closed form
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("zeta,wn", [(0.1, 1.0), (0.3, 2.0), (0.5, 1.0),
                                     (0.7, 5.0), (0.9, 0.5)])
def test_second_order_metrics_match_closed_form(zeta, wn):
    """
    For ``G = ωn²/(s² + 2ζωn s + ωn²)`` the course gives

        Mp = exp(−πζ/√(1−ζ²))·100 %        tp = π/(ωn√(1−ζ²))

    The simulated response must reproduce both.
    """
    tf = second_order(K=1.0, zeta=zeta, wn=wn)
    metrics = compute_step_metrics(step_response(tf))

    wd = wn * np.sqrt(1 - zeta ** 2)
    expected_Mp = 100.0 * np.exp(-np.pi * zeta / np.sqrt(1 - zeta ** 2))
    expected_tp = np.pi / wd

    assert metrics.Mp_pct == pytest.approx(expected_Mp, rel=2e-2)
    assert metrics.tp == pytest.approx(expected_tp, rel=2e-2)
    assert metrics.y_inf == pytest.approx(1.0, rel=1e-3)


@pytest.mark.parametrize("tau", [0.1, 1.0, 10.0])
def test_first_order_settling_and_rise(tau):
    """
    For ``1/(τs+1)``: the ±2% settling time is ``≈ 3.91τ`` (``−τ·ln 0.02``)
    and the 10–90% rise time is ``≈ 2.20τ`` (``τ·ln 9``).
    """
    tf = ctl.tf([1.0], [tau, 1.0])
    m = compute_step_metrics(step_response(tf))
    assert m.ts_2pct == pytest.approx(-tau * np.log(0.02), rel=3e-2)
    assert m.tr_1090 == pytest.approx(tau * np.log(9.0), rel=3e-2)


def test_auto_timespan_frames_the_transient():
    """
    The default window must put the transient across the plot, not squash it
    into the left edge.

    v1's ``50/|Re p|`` gave a window twelve times the settling time, so a pole
    at −1 produced a 50 s axis showing a 3.9 s transient.
    """
    for tf in (ctl.tf([1], [1, 1]), ctl.tf([1], [1, 0.1]),
               second_order(1, 0.3, 2)):
        resp = step_response(tf)
        m = compute_step_metrics(resp)
        occupied = m.ts_2pct / resp.t[-1]
        assert 0.3 < occupied < 1.0, (
            f"transient fills {occupied:.0%} of the window for {tf}"
        )


# ──────────────────────────────────────────────────────────────
#  ch.6 — margins
# ──────────────────────────────────────────────────────────────

def test_gain_margin_of_triple_lag():
    """``1/(s+1)³`` has GM = 8 (18.06 dB) at ω₁₈₀ = √3 — a standard exercise."""
    bd = bode(ctl.tf([1], [1, 3, 3, 1]))
    assert bd.gm_dB == pytest.approx(20 * np.log10(8.0), rel=1e-6)
    assert bd.w180 == pytest.approx(np.sqrt(3.0), rel=1e-6)


def test_gain_crossover_of_second_order():
    """
    ``4/(s²+1.2s+4)`` crosses 0 dB where ``ω⁴ − 6.56ω² = 0``, i.e. ω = √6.56.
    """
    bd = bode(ctl.tf([4], [1, 1.2, 4]))
    assert bd.wc == pytest.approx(np.sqrt(6.56), rel=1e-6)
    assert bd.pm_deg == pytest.approx(50.208, abs=1e-2)


def test_margins_match_control_library():
    """Our margins agree with ``control.stability_margins`` on every probe."""
    systems = [ctl.tf([1], [1, 3, 3, 1]), ctl.tf([1], [1, 1, 0]),
               ctl.tf([4], [1, 1.2, 4]), ctl.tf([1], [1, 3, 2, 0])]
    for L in systems:
        bd = bode(L)
        gm, pm, _sm, wpc, wgc, _wms = ctl.stability_margins(L)
        expected_gm = 20 * np.log10(gm) if np.isfinite(gm) and gm > 0 else np.inf
        assert bd.gm_dB == pytest.approx(expected_gm, rel=1e-6, nan_ok=True)
        assert bd.pm_deg == pytest.approx(pm, rel=1e-6, nan_ok=True)
        assert bd.wc == pytest.approx(wgc, rel=1e-6, nan_ok=True)
        assert bd.w180 == pytest.approx(wpc, rel=1e-6, nan_ok=True)


def test_delay_margin_is_pm_over_wc():
    bd = bode(ctl.tf([1], [1, 1, 0]))
    assert bd.dm_s == pytest.approx(np.radians(bd.pm_deg) / bd.wc, rel=1e-9)


def test_positive_margins_do_not_imply_stability_for_unstable_plant():
    """
    ``L = 1/(s−1)`` is not stabilised by unity feedback, and margin signs alone
    cannot say so — the Nyquist count ``Z = N + P`` must. v1 reported
    ``stable=True`` here.
    """
    bd = bode(ctl.tf([1], [1, -1]))
    assert bd.stable is False
    nd = nyquist(ctl.tf([1], [1, -1]))
    assert nd.P == 1
    assert nd.Z == 1


def test_bode_covers_low_frequencies():
    """
    Every sample below ω = 1 must survive into the plotted curve.

    v1 passed ``log10(ω)`` to a plot already in log mode, so pyqtgraph took the
    logarithm twice and every ω < 1 became NaN. The low-frequency half of each
    Bode plot silently vanished.
    """
    from fakematlab.ui.plots import to_freq_coord

    bd = bode(ctl.tf([1], [1, 1, 0]))
    assert bd.omega.min() < 1.0, "test needs samples below 1 rad/s"
    assert np.isfinite(bd.mag_dB).all()
    assert np.isfinite(bd.phase_deg).all()
    assert np.isfinite(to_freq_coord(bd.omega)).all()


@pytest.mark.parametrize("M", [0.25, 0.5, 0.707, 1.0, 2.0, 6.0])
def test_nichols_m_contours_have_the_right_magnitude(M):
    """
    Every point on the ``|T| = M`` Nichols contour must actually give
    ``|L/(1+L)| = M``.

    v1 took the Nyquist M-circle and read off its own phase and magnitude,
    which traces a different curve entirely.
    """
    pts = nichols_m_contour(M)
    pts = pts[np.isfinite(pts[:, 0])]
    assert len(pts) > 10
    L = 10 ** (pts[:, 1] / 20.0) * np.exp(1j * np.radians(pts[:, 0]))
    assert np.allclose(np.abs(L / (1 + L)), M, rtol=1e-6)


# ──────────────────────────────────────────────────────────────
#  ch.6 — internal stability
# ──────────────────────────────────────────────────────────────

def test_unstable_cancellation_is_caught():
    """
    ``G = 1/(s−1)`` with ``K₂ = (s−1)/(s+2)``.

    The controller zero cancels the unstable plant pole, so the mode at
    ``s = +1`` disappears from every response to the reference — the step
    response settles neatly at 1 — while remaining in the loop and showing up
    the moment an input disturbance excites it. v1 reported "✓ Stable".
    """
    arch = CourseArchitecture(G=ctl.tf([1], [1, -1]),
                              K2=ctl.tf([1, -1], [1, 2]))
    report = arch.internal_stability()

    assert report.stable is False
    assert report.deceptive is True
    assert any(m.real == pytest.approx(1.0, abs=1e-6)
               for m in report.unstable_modes)

    # The reference path — everything a step response would show — is clean.
    assert report.reference_path_stable is True
    for out in ("y", "u", "e"):
        assert ctl.poles(arch.get_closed_loop_tf("r", out)).real.max() < 0

    # The disturbance paths are where the mode surfaces.
    assert ("di", "y") in report.unstable_pairs
    assert ctl.poles(arch.get_closed_loop_tf("di", "y")).real.max() \
        == pytest.approx(1.0, abs=1e-6)

    # And the cause is named explicitly.
    assert any(c.unstable and c.zero_of == "K2" and c.pole_of == "G"
               for c in report.cancellations)


def test_deceptive_failure_is_explained_not_just_flagged():
    """The report must say why the step response cannot be trusted."""
    arch = CourseArchitecture(G=ctl.tf([1], [1, -1]),
                              K2=ctl.tf([1, -1], [1, 2]))
    summary = arch.internal_stability().summary()
    assert "NOT internally stable" in summary
    assert "di→y" in summary
    assert "step response" in summary.lower()


def test_genuine_stabilisation_is_accepted():
    """The same unstable plant, stabilised honestly by gain, is internally stable."""
    arch = CourseArchitecture(G=ctl.tf([1], [1, -1]), K2=ctl.tf([5], [1]))
    report = arch.internal_stability()
    assert report.stable is True
    assert report.unstable_hidden == []


def test_stable_cancellation_is_reported_but_not_fatal():
    arch = CourseArchitecture(G=ctl.tf([1], [1, 1]), K2=ctl.tf([1, 1], [1, 5]))
    report = arch.internal_stability()
    assert report.stable is True
    assert report.deceptive is False
    assert any(c.location.real == pytest.approx(-1.0, abs=1e-6)
               and not c.unstable for c in report.cancellations)


def test_characteristic_polynomial_retains_hidden_modes():
    """``det(M')`` must keep the cancelled mode: (s+3)(s−1) = s²+2s−3."""
    arch = CourseArchitecture(G=ctl.tf([1], [1, -1]),
                              K2=ctl.tf([1, -1], [1, 2]))
    chi = arch.characteristic_polynomial()
    assert np.allclose(chi, [1.0, 2.0, -3.0], atol=1e-9)


# ──────────────────────────────────────────────────────────────
#  ch.8 — root locus and Ziegler–Nichols
# ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("den,Ku,wu", [
    ([1, 3, 3, 1], 8.0, np.sqrt(3.0)),      # 1/(s+1)³
    ([1, 3, 2, 0], 6.0, np.sqrt(2.0)),      # 1/(s(s+1)(s+2))
])
def test_marginal_gain_is_exact(den, Ku, wu):
    result = marginal_gain(ctl.tf([1], den))
    assert result is not None
    assert result[0] == pytest.approx(Ku, rel=1e-9)
    assert result[1] == pytest.approx(wu, rel=1e-9)


@pytest.mark.parametrize("den", [[1, 1], [1, 1, 1]])
def test_no_marginal_gain_when_locus_never_crosses(den):
    """Relative degree ≤ 2 with no RHP poles: no ultimate gain exists."""
    assert marginal_gain(ctl.tf([1], den)) is None
    with pytest.raises(ValueError, match="no ultimate gain"):
        zn_ultimate(ctl.tf([1], den))


def test_root_locus_branches_are_continuous():
    """
    Consecutive samples on a branch must stay close.

    v1 sorted the roots at every gain, so branches jumped between physical
    poles and ``K_marginal`` was never found.
    """
    rl = root_locus(ctl.tf([1], [1, 3, 3, 1]), K_max=20.0, n_pts=400)
    steps = np.abs(np.diff(rl.roots, axis=0))
    assert np.nanmax(steps) < 0.5
    assert rl.K_marginal == pytest.approx(8.0, rel=1e-6)
    assert rl.omega_marginal == pytest.approx(np.sqrt(3.0), rel=1e-6)


def test_zn_ultimate_matches_the_course_rules():
    """Ch.8 slide 40/44: PID from Ku, Tu is 0.6Ku, Tu/2, Tu/8."""
    r = zn_ultimate(ctl.tf([1], [1, 3, 3, 1]))
    assert r.Ku == pytest.approx(8.0, rel=1e-9)
    assert r.Tu == pytest.approx(2 * np.pi / np.sqrt(3.0), rel=1e-9)
    assert r.PID_params.Kp == pytest.approx(0.6 * r.Ku, rel=1e-9)
    assert r.PID_params.Kd == pytest.approx(0.6 * r.Ku * r.Tu / 8.0, rel=1e-9)


# ──────────────────────────────────────────────────────────────
#  Utilities that v1 shipped broken
# ──────────────────────────────────────────────────────────────

def test_pade_returns_a_transfer_function_with_the_right_phase():
    """v1 returned the raw ``(num, den)`` tuple from ``control.pade``."""
    delay = pure_delay_pade(0.5, order=3)
    assert isinstance(delay, ctl.TransferFunction)
    mag, phase = response(delay, np.array([1.0]))
    assert mag[0] == pytest.approx(1.0, rel=1e-6)          # all-pass
    assert phase[0] == pytest.approx(-0.5, rel=1e-3)       # −ωT at ω = 1


@pytest.mark.parametrize("num,den,expected", [
    ([1], [1, 1], 1.0),
    ([5], [1, 5], 1.0),
    ([1], [1, 0], np.inf),
    ([-1], [1, 0], -np.inf),
])
def test_dc_gain(num, den, expected):
    got = dc_gain(ctl.tf(num, den))
    if np.isinf(expected):
        assert np.isinf(got) and np.sign(got) == np.sign(expected)
    else:
        assert got == pytest.approx(expected)


def test_dc_gain_of_indeterminate_is_nan():
    assert np.isnan(dc_gain(ctl.tf([1, 0], [1, 0])))
