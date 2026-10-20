"""
Worked examples from the course, one per chapter.
==================================================

A lesson loads a model, opens the right tab, and says what to look at. The
risk with course content in a tool is that the prose and the code drift: the
note claims a 37% overshoot, someone changes a default, and the note goes on
claiming it.

So a lesson does not contain prose about numbers. It contains
:class:`Claim` objects — a sentence, a **probe** that measures the quantity
from the loaded model, and the value the theory predicts. The lesson panel
shows each claim next to its measured value, and
``tests/golden/test_lessons.py`` checks every claim of every lesson. A note
that stops being true fails the build instead of quietly misleading a student.

Slide references are to ``CORO_CLACO_classical_approach_2026-2027``. The deck
itself is the lecturers' copyright and is not redistributed with this code;
what is reproduced here are the transfer functions and the standard results,
which are textbook.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import control as ctl
import numpy as np

from .architecture import CourseArchitecture
from .freqresp import bode
from .performance import waterbed
from .stability import marginal_gain
from .timeresp import compute_step_metrics, step_response

#: Coefficient lists for one block.
Coeffs = tuple[list[float], list[float]]


# ──────────────────────────────────────────────────────────────
#  Claims
# ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Claim:
    """
    One checkable statement a lesson makes.

    ``mode`` is ``"equals"``, ``"at_least"`` or ``"at_most"`` — because some
    of the course's results are bounds, not values. The ch.3 undershoot
    theorem says *Mu > 1/(e^{c·ts} − 1)*; pinning that to an exact number
    would be asserting the simulation rather than the theorem.
    """

    text: str
    units: str
    probe: Callable[[CourseArchitecture], float]
    expected: float
    tol: float = 0.02                # relative, for "equals"
    mode: str = "equals"
    why: str = ""                    # where the predicted value comes from

    def measure(self, arch: CourseArchitecture) -> float:
        return float(self.probe(arch))

    def holds(self, measured: float) -> bool:
        if not np.isfinite(measured):
            return False
        if self.mode == "at_least":
            return measured >= self.expected * (1.0 - self.tol)
        if self.mode == "at_most":
            return measured <= self.expected * (1.0 + self.tol)
        scale = max(abs(self.expected), 1e-9)
        return abs(measured - self.expected) <= self.tol * scale

    def describe(self, measured: float) -> str:
        symbol = {"equals": "=", "at_least": "≥", "at_most": "≤"}[self.mode]
        return (f"{self.text}\n    predicted {symbol} {self.expected:.4g}"
                f" {self.units}    measured {measured:.4g} {self.units}")


@dataclass(frozen=True)
class Lesson:
    """One chapter's worked example."""

    key: str
    chapter: int
    title: str
    slides: str
    tab: str                          # which tab to bring forward
    summary: str                      # what to look at, and why
    blocks: dict[str, Coeffs]
    claims: tuple[Claim, ...] = ()
    console: tuple[str, ...] = ()     # optional commands to try at the prompt

    def architecture(self) -> CourseArchitecture:
        return CourseArchitecture(
            **{bid: ctl.tf(num, den) for bid, (num, den) in self.blocks.items()})

    def apply_to(self, arch: CourseArchitecture) -> None:
        """Load this lesson's blocks into an existing architecture."""
        for bid, (num, den) in self.blocks.items():
            arch.set_block(bid, ctl.tf(num, den))
        # Blocks the lesson does not mention are reset, so a lesson always
        # shows the same thing regardless of what was on screen before it.
        for bid in ("K1", "K2", "G", "H"):
            if bid not in self.blocks:
                arch.set_block(bid, ctl.tf([1], [1]))

    def check(self) -> list[tuple[Claim, float, bool]]:
        """Measure every claim against a freshly built architecture."""
        arch = self.architecture()
        out = []
        for claim in self.claims:
            try:
                measured = claim.measure(arch)
            except Exception:                                   # noqa: BLE001
                measured = float("nan")
            out.append((claim, measured, claim.holds(measured)))
        return out

    def __repr__(self) -> str:
        return f"<Lesson ch{self.chapter}: {self.title}>"


# ──────────────────────────────────────────────────────────────
#  Probes
# ──────────────────────────────────────────────────────────────

def _closed_loop(arch: CourseArchitecture):
    return arch.get_closed_loop_tf("r", "y")


def _metrics(arch: CourseArchitecture):
    return compute_step_metrics(step_response(_closed_loop(arch)))


def _plant_metrics(arch: CourseArchitecture):
    return compute_step_metrics(step_response(arch.block_tf("G")))


def _worst_closed_loop_pole(arch: CourseArchitecture) -> float:
    poles = np.atleast_1d(arch.closed_loop_poles())
    return float(max(p.real for p in poles)) if len(poles) else float("nan")


def _loop_bode(arch: CourseArchitecture):
    return bode(arch.loop_tf())


# ──────────────────────────────────────────────────────────────
#  The lessons
# ──────────────────────────────────────────────────────────────

def _ch2_satellite() -> Lesson:
    """A satellite axis is a double integrator, and P control cannot hold it."""
    return Lesson(
        key="ch2-satellite",
        chapter=2,
        title="The satellite: why a double integrator resists proportional control",
        slides="ch.2, slides 9–15/28",
        tab="System",
        summary=(
            "Linearising a satellite's attitude about a constant-rate "
            "trajectory leaves one axis as θ̈ = u/Izz — a pure double "
            "integrator, G(s) = 1/s².\n\n"
            "Close the loop with a proportional gain and the closed-loop poles "
            "sit exactly on the imaginary axis: the satellite oscillates "
            "forever and never settles, for *every* positive gain. No amount "
            "of proportional control fixes it, because P control moves the "
            "poles along the imaginary axis rather than off it.\n\n"
            "That is the argument for derivative action, and the reason ch.8's "
            "PD and lead compensators exist. Set K₂ = 1 + s in the block "
            "editor and watch both poles leave the axis."
        ),
        blocks={"G": ([1.0], [1.0, 0.0, 0.0]), "K2": ([1.0], [1.0])},
        claims=(
            Claim("The plant has two poles at the origin.", "poles at s=0",
                  lambda a: float(np.sum(np.abs(
                      np.atleast_1d(ctl.poles(a.block_tf("G")))) < 1e-9)),
                  expected=2.0, tol=1e-9,
                  why="G(s) = 1/s²"),
            Claim("Under unit proportional feedback every closed-loop pole "
                  "sits on the imaginary axis.", "max Re(p)",
                  _worst_closed_loop_pole, expected=0.0, tol=1e-6,
                  why="1 + 1/s² = 0 → s = ±j"),
            Claim("Those poles are at ±j, so the response oscillates at "
                  "1 rad/s and never decays.", "|Im(p)| (rad/s)",
                  lambda a: float(np.max(np.abs(
                      np.atleast_1d(a.closed_loop_poles()).imag))),
                  expected=1.0, tol=1e-6,
                  why="s² + 1 = 0"),
        ),
        console=("G = 1/s**2", "T = feedback(G, 1)", "pole(T)", "step(T)"),
    )


def _ch3_nmp() -> Lesson:
    """
    Slide 26/34: G(s) = (c − s) / (c·(s+1)(0.5s+1)), normalised to G(0) = 1.

    With c = 0.5 the zero sits at +0.5 and the undershoot theorem of slide
    23/34 applies: ``Mu ≥ 1/(e^{c·ts} − 1)``.
    """
    c = 0.5
    den = np.polymul([1.0, 1.0], [0.5, 1.0]) * c
    return Lesson(
        key="ch3-nmp",
        chapter=3,
        title="A right-half-plane zero buys its speed with undershoot",
        slides="ch.3, slides 16–26/34",
        tab="Time",
        summary=(
            "G(s) = (c − s) / (c·(s+1)(0.5s+1)) with c = 0.5, normalised so "
            "G(0) = 1. The zero at s = +c makes this **non-minimum phase**.\n\n"
            "The step response sets off in the *wrong direction* before "
            "recovering. That is not a numerical artefact; slide 23/34 proves "
            "it cannot be avoided. Any stable system with G(0) = 1 and a real "
            "zero at c > 0 undershoots by at least\n\n"
            "        Mu ≥ 1 / (e^{c·ts} − 1)\n\n"
            "so the faster you insist it settles, the deeper the initial dip "
            "has to be. A right-half-plane zero is a hard limit on "
            "performance, not a tuning problem — which is why ch.7 returns to "
            "it when 1/G(s) turns out to be unstable.\n\n"
            "Move the zero towards the imaginary axis (smaller c) and the "
            "bound gets worse."
        ),
        blocks={"G": ([-1.0, c], list(den))},
        claims=(
            Claim("The plant has unit DC gain, as the theorem assumes.",
                  "G(0)",
                  lambda a: float(ctl.dcgain(a.block_tf("G"))),
                  expected=1.0, tol=1e-9,
                  why="the numerator is normalised by c"),
            Claim("Its zero is in the right half plane.", "zero",
                  lambda a: float(np.atleast_1d(
                      ctl.zeros(a.block_tf("G")))[0].real),
                  expected=c, tol=1e-6,
                  why="num = c − s"),
            Claim("The open-loop step response undershoots.", "Mu",
                  lambda a: float(_plant_metrics(a).Mu_abs),
                  expected=0.0, mode="at_least", tol=0.0,
                  why="slide 23/34"),
            Claim("The undershoot respects the theorem's lower bound "
                  "1/(e^{c·ts} − 1).", "Mu / bound",
                  _nmp_bound_ratio, expected=1.0, mode="at_least", tol=0.0,
                  why="slide 23/34, with ts measured from the same response"),
        ),
        console=("G = (0.5 - s)/(0.5*(s+1)*(0.5*s+1))", "step(G)",
                 "stepinfo(G)"),
    )


def _nmp_bound_ratio(arch: CourseArchitecture) -> float:
    """Measured undershoot divided by the ch.3 lower bound."""
    metrics = _plant_metrics(arch)
    zeros = np.atleast_1d(ctl.zeros(arch.block_tf("G")))
    c = float(max(z.real for z in zeros))
    ts = float(metrics.ts_2pct)
    if not np.isfinite(ts) or c <= 0:
        return float("nan")
    bound = 1.0 / (np.exp(c * ts) - 1.0)
    return float(metrics.Mu_abs / bound) if bound > 0 else float("inf")


def _ch4_second_order() -> Lesson:
    """The canonical second-order family, with its closed-form metrics."""
    zeta, wn = 0.3, 2.0
    return Lesson(
        key="ch4-second-order",
        chapter=4,
        title="The second-order family: ζ sets the overshoot, ωn sets the clock",
        slides="ch.4, slides 12–30/46",
        tab="Time",
        summary=(
            "G(s) = ωn² / (s² + 2ζωn·s + ωn²) with ζ = 0.3 and ωn = 2 rad/s.\n\n"
            "This one transfer function is the reason second-order "
            "approximations are worth anything: every step metric has a "
            "closed form, and they separate cleanly.\n\n"
            "    Mp  = exp(−πζ/√(1−ζ²))     — depends on ζ **only**\n"
            "    tp  = π / (ωn√(1−ζ²))      — scales as 1/ωn\n"
            "    ts  ≈ 4 / (ζωn)            — the ±2% envelope\n\n"
            "So ζ fixes the *shape* of the response and ωn fixes its *speed*. "
            "Change ωn in the block editor and the curve stretches "
            "horizontally without changing height; change ζ and the overshoot "
            "moves.\n\n"
            "Every later design specification — a phase margin in ch.6, a "
            "damping target on the root locus in ch.8 — is ultimately a way of "
            "asking for a particular ζ."
        ),
        blocks={"G": ([wn ** 2], [1.0, 2 * zeta * wn, wn ** 2])},
        claims=(
            Claim("Overshoot depends on ζ alone.", "%",
                  lambda a: float(_plant_metrics(a).Mp_pct),
                  expected=100 * np.exp(-np.pi * zeta / np.sqrt(1 - zeta ** 2)),
                  tol=0.02,
                  why="Mp = exp(−πζ/√(1−ζ²))"),
            Claim("Peak time scales as 1/ωn.", "s",
                  lambda a: float(_plant_metrics(a).tp),
                  expected=np.pi / (wn * np.sqrt(1 - zeta ** 2)), tol=0.02,
                  why="tp = π/(ωn√(1−ζ²))"),
            Claim("The ±2% settling time is about 4/(ζωn).", "s",
                  lambda a: float(_plant_metrics(a).ts_2pct),
                  expected=4.0 / (zeta * wn), tol=0.25,
                  why="the envelope e^{−ζωn t} falls to 2% at t = 4/(ζωn); the "
                      "true settling time steps between oscillation peaks, so "
                      "this is an estimate, not an identity"),
            Claim("The DC gain is 1, so there is no steady-state error to a "
                  "step.", "y∞",
                  lambda a: float(ctl.dcgain(a.block_tf("G"))),
                  expected=1.0, tol=1e-9,
                  why="G(0) = ωn²/ωn²"),
        ),
        console=("G = tf([4], [1, 1.2, 4])", "stepinfo(G)", "damp(G)",
                 "step(G)"),
    )


def _ch5_two_dof() -> Lesson:
    """Feedforward changes tracking without touching the loop."""
    return Lesson(
        key="ch5-two-dof",
        chapter=5,
        title="Two degrees of freedom: feedforward is free of the loop",
        slides="ch.5, slides 16–17/24",
        tab="System",
        summary=(
            "The architecture this whole tool is built on: K₁ in the "
            "reference path, K₂ in the loop, G the plant, H the sensor.\n\n"
            "The point of separating them is that **K₁ does not appear in the "
            "loop transfer function**. L = K₂·G·H, with no K₁ in it. So K₁ "
            "cannot change stability, cannot change a margin, and cannot "
            "change how a disturbance is rejected — it only reshapes the path "
            "from r to y.\n\n"
            "That is a genuine separation of concerns: design K₂ for "
            "stability and disturbance rejection (slide 17/24 lists exactly "
            "those jobs), then shape tracking with K₁ afterwards without "
            "undoing any of it.\n\n"
            "Here K₂ = 2 + 1/s and K₁ = 1. Change K₁ to (s+1)/(s+3) and watch "
            "the reference response move while the Frequency tab's margins "
            "stay where they are — the Stability tab will not budge either."
        ),
        blocks={
            "G": ([1.0], [1.0, 1.0]),
            "K2": ([2.0, 1.0], [1.0, 0.0]),
            "K1": ([1.0], [1.0]),
            "H": ([1.0], [1.0]),
        },
        claims=(
            Claim("The loop transfer function does not contain K₁.",
                  "|L − K₂GH| at ω=1",
                  _loop_excludes_k1, expected=0.0, tol=1e-9,
                  why="L is derived by breaking the loop at the error node"),
            Claim("Changing K₁ leaves every *feedback* pole where it was.",
                  "max |Δp|",
                  _pole_shift_under_feedforward, expected=0.0, tol=1e-9,
                  why="the roots of 1 + L do not involve K₁. K₁'s own poles do "
                      "join the r→y response — it is in that path — which is "
                      "why this compares the poles of S, not every mode of "
                      "the interconnection"),
            Claim("Changing K₁ does change the reference response.",
                  "|ΔT(0)|",
                  _tracking_shift_under_feedforward,
                  expected=0.25, mode="at_least", tol=0.0,
                  why="T_ry = K₁·(stuff); K₁(0) = 1/3 here"),
            Claim("The loop has an integrator, so the steady-state error to a "
                  "step is zero.", "e∞",
                  lambda a: abs(1.0 - float(ctl.dcgain(_closed_loop(a)))),
                  expected=0.0, tol=1e-6,
                  why="K₂ contains 1/s → system type 1"),
        ),
        console=("arch.loop_tf()", "arch.get_closed_loop_tf('r', 'y')",
                 "margin(arch.loop_tf())"),
    )


def _loop_excludes_k1(arch: CourseArchitecture) -> float:
    """|L(j1)| compared against K₂GH computed directly."""
    L = arch.loop_tf()
    direct = arch.block_tf("K2") * arch.block_tf("G") * arch.block_tf("H")
    return float(abs(complex(L(1j)) - complex(direct(1j))))


def _feedforward_variant(arch: CourseArchitecture) -> CourseArchitecture:
    other = CourseArchitecture(
        G=arch.block_tf("G"), K2=arch.block_tf("K2"),
        K1=ctl.tf([1.0, 1.0], [1.0, 3.0]), H=arch.block_tf("H"))
    return other


def _pole_shift_under_feedforward(arch: CourseArchitecture) -> float:
    """
    How far the feedback poles move when K₁ changes. They should not move.

    Compared on the *sensitivity* function, whose poles are the roots of
    1 + L. Comparing every mode of the interconnection instead would count
    K₁'s own pole, which genuinely does appear in the reference response —
    K₁ is in that path. The claim is that K₁ cannot move the feedback poles,
    not that it adds no dynamics of its own.
    """
    before = np.sort_complex(np.atleast_1d(ctl.poles(arch.sensitivity())))
    after = np.sort_complex(
        np.atleast_1d(ctl.poles(_feedforward_variant(arch).sensitivity())))
    if before.shape != after.shape:
        return float("inf")
    return float(np.max(np.abs(before - after))) if len(before) else 0.0


def _tracking_shift_under_feedforward(arch: CourseArchitecture) -> float:
    before = float(ctl.dcgain(arch.get_closed_loop_tf("r", "y")))
    after = float(ctl.dcgain(
        _feedforward_variant(arch).get_closed_loop_tf("r", "y")))
    return abs(before - after)


def _ch6_margins() -> Lesson:
    """
    The classical margins on a loop whose answers are all exact.

    ``K₂ = 2`` rather than 1, and for a reason worth showing: with unit gain
    ``|L(0)| = 1`` exactly, so the loop *starts* on the 0 dB line and never
    crosses it. There is then no gain crossover, no phase margin and no delay
    margin — not because anything failed, but because those quantities are
    defined at a crossing that does not happen.
    """
    wc = float(np.sqrt(2.0 ** (2.0 / 3.0) - 1.0))
    pm = 180.0 - 3.0 * float(np.degrees(np.arctan(wc)))
    return Lesson(
        key="ch6-margins",
        chapter=6,
        title="Margins: how far the loop is from −1",
        slides="ch.6, slides 16–21/26",
        tab="Frequency",
        summary=(
            "L(s) = 2/(s+1)³ — every margin has a closed form, so the plot "
            "can be checked rather than believed.\n\n"
            "    gain margin  = 4  (12.04 dB) at ω = √3 rad/s\n"
            "    crossover    ωc = √(2^⅔ − 1) ≈ 0.766 rad/s\n"
            "    phase margin = 180° − 3·arctan(ωc) ≈ 67.6°\n"
            "    delay margin = Mφ / ωφ  (slide 19/26)\n\n"
            "The gain of 2 is not arbitrary. At K₂ = 1 the loop has "
            "|L(0)| = 1 exactly, so it *starts* on the 0 dB line and never "
            "crosses it: there is no gain crossover, and therefore no phase "
            "margin and no delay margin at all. Try it — set K₂ = 1 in the "
            "block editor and watch those three readouts become undefined. "
            "They are not broken; they are quantities defined at a crossing "
            "that is not happening.\n\n"
            "The course's classical targets are a gain margin of ±6 dB and a "
            "phase margin of 35–40° (slides 17–18/26), so this loop is "
            "comfortable on both.\n\n"
            "Being comfortable on both is still not a guarantee. Gain and "
            "phase margins measure the distance to −1 along two particular "
            "directions, and a loop can pass both tests while passing close "
            "to −1 diagonally. The honest single number is the **modulus "
            "margin**: the shortest distance from the Nyquist curve to −1, "
            "equal to 1/‖S‖∞. Slide 21/26 makes the same point with "
            "M-circles — the 2.3 dB contour is the usual limit, and a loop "
            "tangent to it has a closed-loop peak of 2.3 dB, about 23% "
            "overshoot on a second-order approximation.\n\n"
            "Switch between Bode, Nyquist and Nichols in this tab; all three "
            "are showing the same numbers."
        ),
        blocks={"G": ([1.0], [1.0, 3.0, 3.0, 1.0]), "K2": ([2.0], [1.0])},
        claims=(
            Claim("The gain margin is exactly 4 — the factor by which the "
                  "gain could still rise.", "dB",
                  lambda a: float(_loop_bode(a).gm_dB),
                  expected=20 * np.log10(4.0), tol=0.01,
                  why="|L(j√3)| = 2/8 = 1/4"),
            Claim("…measured where the phase passes −180°, at ω = √3.",
                  "rad/s",
                  lambda a: float(_loop_bode(a).w180),
                  expected=np.sqrt(3.0), tol=0.01,
                  why="3·arctan(√3) = 180°"),
            Claim("The gain crosses 0 dB at ωc = √(2^⅔ − 1).", "rad/s",
                  lambda a: float(_loop_bode(a).wc),
                  expected=wc, tol=0.01,
                  why="|2/(1+jω)³| = 1 ⇒ (1+ω²)^{3/2} = 2"),
            Claim("The phase margin there is 180° − 3·arctan(ωc).", "°",
                  lambda a: float(_loop_bode(a).pm_deg),
                  expected=pm, tol=0.01,
                  why="∠L(jω) = −3·arctan(ω)"),
            Claim("The delay margin is that phase margin in radians divided "
                  "by the crossover frequency.", "Md·ωc/Mφ",
                  _delay_margin_identity, expected=1.0, tol=1e-6,
                  why="slide 19/26: Md = Mφ/ωφ"),
            Claim("The modulus margin is smaller than either classical "
                  "margin suggests — it is the distance to −1 in every "
                  "direction at once.", "1/Ms",
                  lambda a: 1.0 / float(_loop_bode(a).Ms),
                  expected=1.0, mode="at_most", tol=0.0,
                  why="‖S‖∞ ≥ 1 whenever the loop has relative degree ≥ 1"),
        ),
        console=("L = 2/(s+1)**3", "margin(L)", "allmargin(L)", "nyquist(L)"),
    )


def _delay_margin_identity(arch: CourseArchitecture) -> float:
    """``dm · wc / PM_rad`` — should be exactly 1."""
    bd = _loop_bode(arch)
    if not (np.isfinite(bd.wc) and np.isfinite(bd.pm_deg) and bd.wc > 0):
        return float("nan")
    return float(bd.dm_s * bd.wc / np.radians(abs(bd.pm_deg)))


def _ch7_waterbed() -> Lesson:
    """Bode–Freudenberg: sensitivity you push down comes back up elsewhere."""
    return Lesson(
        key="ch7-waterbed",
        chapter=7,
        title="The waterbed: ∫ln|S| dω is fixed before you start",
        slides="ch.7, slides 17–19/20",
        tab="Performance",
        summary=(
            "L(s) = 2/((s+1)(s+2)) — stable, relative degree 2.\n\n"
            "Bode's integral theorem (slide 18/20) says that for any loop of "
            "relative degree greater than 1,\n\n"
            "        ∫₀^∞ ln|S(jω)| dω = 0        (L stable)\n"
            "        ∫₀^∞ ln|S(jω)| dω = π·ΣRe(pᵢ)  (L unstable)\n\n"
            "The integral is decided by the *poles* of the loop, not by the "
            "controller. So every decibel of disturbance rejection you win at "
            "low frequency — |S| < 1, ln|S| < 0 — has to be paid back "
            "somewhere else as amplification, |S| > 1.\n\n"
            "You cannot make the loop better everywhere. You can only choose "
            "*where* it is worse. And an unstable plant makes the bill "
            "strictly positive before any design has begun: right-half-plane "
            "poles cost you performance you never had.\n\n"
            "This is the theorem behind every 'trade-off' in ch.7, and the "
            "reason the Performance tab draws S and T together."
        ),
        blocks={"G": ([2.0], [1.0, 3.0, 2.0]), "K2": ([1.0], [1.0])},
        claims=(
            Claim("The loop has relative degree 2, so the theorem applies.",
                  "poles − zeros",
                  lambda a: float(len(np.atleast_1d(ctl.poles(a.loop_tf())))
                                  - len(np.atleast_1d(
                                      ctl.zeros(a.loop_tf())))),
                  expected=2.0, tol=1e-9,
                  why="2/((s+1)(s+2))"),
            Claim("The loop is stable, so the integral should come out at "
                  "zero.", "Σ Re(p) over unstable poles",
                  lambda a: float(sum(
                      p.real for p in np.atleast_1d(ctl.poles(a.loop_tf()))
                      if p.real > 0)),
                  expected=0.0, tol=1e-9,
                  why="poles at −1 and −2"),
            Claim("∫ln|S| dω is zero to within quadrature error.",
                  "integral",
                  lambda a: float(waterbed(a.loop_tf()).integral),
                  expected=0.0, tol=0.06, mode="at_most",
                  why="Bode–Freudenberg, slide 18/20"),
            Claim("…and sensitivity really is amplified somewhere: ‖S‖∞ > 1.",
                  "‖S‖∞",
                  lambda a: float(_loop_bode(a).Ms),
                  expected=1.0, mode="at_least", tol=0.0,
                  why="the integral cannot be zero with |S| ≤ 1 everywhere"),
        ),
        console=("L = 2/((s+1)*(s+2))", "S = feedback(1, L)", "bode(S)"),
    )


def _ch8_ziegler_nichols() -> Lesson:
    """The oscillation method, on the plant whose Ku is exactly 8."""
    Ku, Tu = 8.0, 2 * np.pi / np.sqrt(3.0)
    return Lesson(
        key="ch8-ziegler-nichols",
        chapter=8,
        title="Ziegler–Nichols: tuning from the edge of instability",
        slides="ch.8, slides 37–39/44",
        tab="Design",
        summary=(
            "G(s) = 1/(s+1)³, the standard demonstration plant.\n\n"
            "The oscillation method (slide 37/44): raise a proportional gain "
            "until the loop oscillates steadily, record that critical gain Pc "
            "and the period Tc, then read the gains off a table.\n\n"
            "    P     Kp = 0.5·Pc\n"
            "    PI    Kp = 0.45·Pc,  Ti = 0.83·Tc\n"
            "    PID   Kp = 0.6·Pc,   Ti = 0.5·Tc,  Td = 0.125·Tc\n\n"
            "For this plant the critical values are exact: **Pc = 8** and "
            "**Tc = 2π/√3 ≈ 3.628 s**, because the loop crosses the imaginary "
            "axis at ω = √3 where |L| = 1/8.\n\n"
            "This tool does not hunt for that gain by simulation. It solves "
            "1 + K·L(jω) = 0 for real (K, ω) symbolically, so Pc comes back as "
            "8 rather than 7.98.\n\n"
            "Slide 38/44 is blunt about the method's limits: the tuning is "
            "very sensitive to the plant's delay-to-lag ratio, forcing a real "
            "plant to oscillate can be dangerous, and these gains are a "
            "starting point for tuning rather than an answer. Compare the "
            "result against the PID Tuner app, which asks for a phase margin "
            "instead and gets it exactly."
        ),
        blocks={"G": ([1.0], [1.0, 3.0, 3.0, 1.0]), "K2": ([1.0], [1.0])},
        claims=(
            Claim("The critical gain is exactly 8.", "Pc",
                  lambda a: float(marginal_gain(a.loop_tf())[0]),
                  expected=Ku, tol=1e-6,
                  why="1 + K/(jω+1)³ = 0 has a real solution at K = 8, ω = √3"),
            Claim("The oscillation period is 2π/√3.", "s",
                  lambda a: float(2 * np.pi / marginal_gain(a.loop_tf())[1]),
                  expected=Tu, tol=1e-6,
                  why="ω = √3 rad/s"),
            Claim("The Z-N PID proportional gain is 0.6·Pc.", "Kp",
                  _zn_pid_kp, expected=0.6 * Ku, tol=1e-6,
                  why="slide 38/44"),
            Claim("The Z-N PID derivative gain is 0.6·Pc·0.125·Tc.", "Kd",
                  _zn_pid_kd, expected=0.6 * Ku * 0.125 * Tu, tol=1e-6,
                  why="Td = 0.125·Tc"),
            Claim("The resulting loop is stable, but only just — Z-N aims for "
                  "a quarter-decay response, not a comfortable margin.",
                  "PM (°)",
                  _zn_phase_margin, expected=45.0, mode="at_most", tol=0.0,
                  why="compare with the 60° the PID Tuner defaults to"),
        ),
        console=("G = 1/(s+1)**3", "zn(G, 'ultimate', 'PID')",
                 "C = pidtune(G, 'pid')", "C.tuning.describe()"),
    )


def _zn_pid(arch: CourseArchitecture):
    from .tuning import zn_ultimate

    return zn_ultimate(arch.block_tf("G")).PID_params


def _zn_pid_kp(arch: CourseArchitecture) -> float:
    return float(_zn_pid(arch).Kp)


def _zn_pid_kd(arch: CourseArchitecture) -> float:
    return float(_zn_pid(arch).Kd)


def _zn_phase_margin(arch: CourseArchitecture) -> float:
    from .tuning import pid_tf

    L = pid_tf(_zn_pid(arch)) * arch.block_tf("G")
    return float(bode(L).pm_deg)


# ──────────────────────────────────────────────────────────────
#  Registry
# ──────────────────────────────────────────────────────────────

def all_lessons() -> tuple[Lesson, ...]:
    """Every lesson, in chapter order."""
    return (
        _ch2_satellite(),
        _ch3_nmp(),
        _ch4_second_order(),
        _ch5_two_dof(),
        _ch6_margins(),
        _ch7_waterbed(),
        _ch8_ziegler_nichols(),
    )


def lesson(key: str) -> Lesson:
    for item in all_lessons():
        if item.key == key:
            return item
    raise KeyError(f"no lesson {key!r}. Have: "
                   f"{', '.join(item.key for item in all_lessons())}")
