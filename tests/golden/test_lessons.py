"""
The course lessons, and the claims they make.

This file is the reason the lessons are written as :class:`Claim` objects
rather than as prose. Every sentence a lesson asserts about a number is
checked here against the model it ships, so a note cannot quietly stop being
true after someone changes a default.
"""

from __future__ import annotations

import control as ctl
import numpy as np
import pytest

from fakematlab.core.lessons import Claim, Lesson, all_lessons, lesson


@pytest.fixture(params=all_lessons(), ids=lambda les: les.key)
def any_lesson(request) -> Lesson:
    return request.param


# ──────────────────────────────────────────────────────────────
#  The claims
# ──────────────────────────────────────────────────────────────

def test_every_claim_holds(any_lesson):
    """
    The whole point of the exercise.

    A lesson that stops being true fails the build rather than misleading
    whoever reads it.
    """
    failures = [
        f"{claim.text!r}: predicted {claim.mode} {claim.expected:.6g} "
        f"{claim.units}, measured {measured:.6g}"
        + (f"  ({claim.why})" if claim.why else "")
        for claim, measured, ok in any_lesson.check() if not ok
    ]
    assert not failures, "\n".join(failures)


def test_every_lesson_makes_at_least_three_claims(any_lesson):
    """A lesson with nothing checkable in it is prose, not a worked example."""
    assert len(any_lesson.claims) >= 3


def test_every_claim_says_where_its_number_comes_from(any_lesson):
    for claim in any_lesson.claims:
        assert claim.why, f"{any_lesson.key}: {claim.text!r} has no derivation"


def test_a_claim_that_stops_holding_is_detected():
    """The check must be able to fail, or it is not checking anything."""
    ch4 = lesson("ch4-second-order")
    arch = ch4.architecture()
    # Move the plant well away from the one the lesson is about.
    arch.set_block("G", ctl.tf([1.0], [1.0, 1.0]))
    broken = [c for c in ch4.claims if not c.holds(c.measure(arch))]
    assert broken, "changing the plant should break at least one claim"


def test_bounds_are_checked_as_bounds_not_equalities():
    """
    ch.3's undershoot result is an inequality, and pinning it to a number
    would assert the simulation rather than the theorem.
    """
    claim = Claim("x", "u", lambda a: 5.0, expected=1.0, mode="at_least")
    assert claim.holds(5.0) and claim.holds(1.0)
    assert not claim.holds(0.4)

    at_most = Claim("x", "u", lambda a: 0.5, expected=1.0, mode="at_most")
    assert at_most.holds(0.5) and not at_most.holds(4.0)


def test_a_nan_never_counts_as_holding():
    """
    An undefined phase margin used to read as a pass under a loose tolerance.
    """
    claim = Claim("x", "u", lambda a: float("nan"), expected=0.0, tol=1.0)
    assert not claim.holds(float("nan"))


# ──────────────────────────────────────────────────────────────
#  Loading
# ──────────────────────────────────────────────────────────────

def test_a_lesson_resets_the_blocks_it_does_not_mention(any_lesson):
    """
    Otherwise a lesson shows something different depending on what was on
    screen before it, which makes it useless as a reference.
    """
    from fakematlab.core.architecture import BLOCK_IDS, CourseArchitecture

    arch = CourseArchitecture()
    for bid in BLOCK_IDS:
        arch.set_block(bid, ctl.tf([7.0], [1.0, 9.0]))

    any_lesson.apply_to(arch)
    for bid in BLOCK_IDS:
        if bid not in any_lesson.blocks:
            assert np.allclose(
                np.atleast_1d(arch.block_tf(bid).num[0][0]), [1.0]), \
                f"{bid} kept a stale transfer function"


def test_applying_a_lesson_matches_building_it_fresh(any_lesson):
    from fakematlab.core.architecture import BLOCK_IDS, CourseArchitecture

    applied = CourseArchitecture()
    any_lesson.apply_to(applied)
    fresh = any_lesson.architecture()
    for bid in BLOCK_IDS:
        a = np.atleast_1d(applied.block_tf(bid).num[0][0])
        b = np.atleast_1d(fresh.block_tf(bid).num[0][0])
        if len(a) == len(b):
            assert np.allclose(a, b)


def test_lesson_lookup_names_the_alternatives():
    with pytest.raises(KeyError, match="ch2-satellite"):
        lesson("ch99-nonsense")


def test_every_lesson_targets_a_real_tab():
    from fakematlab.ui.mainwindow import MainWindow

    for item in all_lessons():
        assert item.tab in MainWindow._TAB_BY_NAME, \
            f"{item.key} opens {item.tab!r}, which is not a tab"


def test_the_chapters_are_covered_in_order():
    chapters = [item.chapter for item in all_lessons()]
    assert chapters == sorted(chapters)
    assert set(chapters) == {2, 3, 4, 5, 6, 7, 8}


# ──────────────────────────────────────────────────────────────
#  Specific results, stated independently of the lesson objects
# ──────────────────────────────────────────────────────────────

def test_ch6_crossover_has_the_closed_form_the_note_quotes():
    """``|2/(1+jω)³| = 1`` ⇒ ``ωc = √(2^⅔ − 1)``, and PM = 180° − 3·arctan ωc."""
    from fakematlab.core.freqresp import bode

    arch = lesson("ch6-margins").architecture()
    bd = bode(arch.loop_tf())
    wc = np.sqrt(2.0 ** (2.0 / 3.0) - 1.0)
    assert bd.wc == pytest.approx(wc, rel=1e-4)
    assert bd.pm_deg == pytest.approx(
        180.0 - 3.0 * np.degrees(np.arctan(wc)), rel=1e-4)
    assert bd.gm_dB == pytest.approx(20 * np.log10(4.0), abs=0.02)


def test_ch6_at_unit_gain_there_is_no_crossover_at_all():
    """
    The note's aside, checked: ``|L(0)| = 1`` exactly, so the loop starts on
    the 0 dB line and the phase margin is undefined rather than wrong.
    """
    from fakematlab.core.freqresp import bode

    arch = lesson("ch6-margins").architecture()
    arch.set_block("K2", ctl.tf([1], [1]))
    assert float(abs(ctl.dcgain(arch.loop_tf()))) == pytest.approx(1.0)
    assert not np.isfinite(bode(arch.loop_tf()).pm_deg)


def test_ch8_critical_values_are_exact_not_simulated():
    """``Pc = 8`` and ``Tc = 2π/√3``, solved rather than searched for."""
    from fakematlab.core.stability import marginal_gain

    arch = lesson("ch8-ziegler-nichols").architecture()
    Ku, wu = marginal_gain(arch.loop_tf())
    assert Ku == pytest.approx(8.0, rel=1e-9)
    assert wu == pytest.approx(np.sqrt(3.0), rel=1e-9)


def test_ch2_proportional_control_never_stabilises_a_double_integrator():
    """
    The lesson's argument, checked across gains rather than at one point: a
    pure double integrator under proportional feedback has its poles on the
    imaginary axis for *every* positive gain.
    """
    arch = lesson("ch2-satellite").architecture()
    for gain in (0.1, 1.0, 10.0, 1000.0):
        arch.set_block("K2", ctl.tf([gain], [1]))
        poles = np.atleast_1d(arch.closed_loop_poles())
        assert np.max(poles.real) == pytest.approx(0.0, abs=1e-9), \
            f"gain {gain} moved the poles off the axis"


def test_ch7_an_unstable_pole_makes_the_waterbed_integral_positive():
    """
    The half of Bode–Freudenberg the lesson describes but does not load:
    ``∫ln|S| = π·ΣRe(pᵢ)`` over the unstable poles.
    """
    from fakematlab.core.performance import waterbed

    # 1/((s−1)(s+3)) stabilised by a gain: one unstable loop pole at +1.
    L = ctl.tf([8.0], [1.0, 2.0, -3.0])
    result = waterbed(L)
    assert result.integral == pytest.approx(np.pi * 1.0, rel=0.05)
