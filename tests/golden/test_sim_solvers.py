"""
The solver menu: fixed-step Runge–Kutta methods ``ode1``–``ode5`` checked at
their theoretical order, and Simulink's solver names checked against the
analytic answer they must all reach.

A convergence order is the sharpest test a tableau can have: one wrong
coefficient still gives a method that "works" and looks fine on a plot, but it
drops to first or second order, and halving the step shows it at once.
"""

from __future__ import annotations

import time

import control as ctl
import numpy as np
import pytest
from scipy.linalg import expm

from evans.sim.blocks import by_category  # noqa: F401  (registers library)
from evans.sim.model import SimModel
from evans.sim.solver import (
    FIXED_STEP,
    SIMULINK_ALIASES,
    VARIABLE_STEP,
    SimulationError,
    _fixed_step,
    resolve_solver,
    simulate,
)

# ──────────────────────────────────────────────────────────────
#  Fixed-step convergence order
# ──────────────────────────────────────────────────────────────

# A lightly damped oscillator: two coupled states, so a tableau error that
# cancels on a scalar decay cannot hide.
A = np.array([[0.0, 1.0], [-4.0, -0.4]])
X0 = np.array([1.0, 0.0])
T_END = 2.0


def _final_error(method: str, h: float) -> float:
    x_end = _fixed_step(lambda t, x: A @ x, X0, 0.0, T_END, method, h,
                        np.zeros(0), lambda *a: None, None)
    return float(np.max(np.abs(x_end - expm(A * T_END) @ X0)))


# Step sizes chosen so the error is well above rounding (≥ 1e-10) yet in the
# asymptotic regime, where the leading error term dominates.
@pytest.mark.parametrize("method, order, h", [
    ("ode1", 1, 2e-3),
    ("ode2", 2, 1e-2),
    ("ode3", 3, 2e-2),
    ("ode4", 4, 5e-2),
    ("ode5", 5, 1e-1),
])
def test_fixed_step_methods_converge_at_their_order(method, order, h):
    coarse, fine = _final_error(method, h), _final_error(method, h / 2)
    measured = np.log2(coarse / fine)
    assert fine > 1e-12, "rounding, not truncation, would be measured"
    assert abs(measured - order) < 0.2, (method, measured)


def test_on_major_step_is_called_once_per_step_with_increasing_time():
    calls: list[tuple[float, np.ndarray]] = []
    recorded: list[float] = []
    inner = np.array([0.25, 0.5, 0.75])
    x_end = _fixed_step(lambda t, x: -x, np.array([1.0]), 0.0, 1.0, "ode4",
                        0.1, inner, lambda t, x, xd: recorded.append(t), None,
                        on_major_step=lambda t, x: calls.append((t, x.copy())))

    # 0.25 / 0.1 rounds up to 3 steps per interval, four intervals.
    assert len(calls) == 12
    ts = [t for t, _ in calls]
    assert all(b > a for a, b in zip(ts, ts[1:]))
    assert ts[-1] == 1.0                                  # exact, no drift
    assert set(recorded) <= set(ts)                       # outputs are steps
    assert np.array_equal(calls[-1][1], x_end)


def test_on_major_step_is_optional():
    x = _fixed_step(lambda t, x: -x, np.array([1.0]), 0.0, 1.0, "ode5",
                    0.1, np.zeros(0), lambda *a: None, None)
    assert abs(x[0] - np.exp(-1.0)) < 1e-8


# ──────────────────────────────────────────────────────────────
#  Every name reaches the analytic answer
# ──────────────────────────────────────────────────────────────

def _second_order() -> SimModel:
    m = SimModel("so")
    m.add("Step", "r", step_time=0.0)
    m.add("TransferFcn", "G", num="4", den="1, 1.2, 4")
    m.connect("r", "G")
    return m


FIXED_TOL = {"ode1": 1e-2, "ode2": 1e-4, "ode3": 1e-5, "ode4": 1e-6,
             "ode5": 1e-6}


@pytest.mark.parametrize("name", [*SIMULINK_ALIASES, *sorted(VARIABLE_STEP),
                                  *sorted(FIXED_STEP)])
def test_every_solver_name_matches_the_step_response(name):
    fixed = name in FIXED_STEP
    r = simulate(_second_order(), t_end=5.0, n_points=500, solver=name,
                 rtol=1e-8, atol=1e-10,
                 max_step=(2e-3 if name == "ode1" else 1e-2) if fixed else None)
    _, expected = ctl.step_response(ctl.tf([4], [1, 1.2, 4]), T=r.t)
    err = np.max(np.abs(r.trace("G.out") - expected))
    assert err < (FIXED_TOL[name] if fixed else 1e-5), (name, err)


def test_result_records_what_was_asked_and_what_ran():
    assert simulate(_second_order(), t_end=1.0,
                    solver="ode45").solver == "ode45 (RK45)"
    assert simulate(_second_order(), t_end=1.0,
                    solver="ODE113").solver == "ode113 (LSODA)"
    assert simulate(_second_order(), t_end=1.0, solver="rk45").solver == "RK45"
    assert simulate(_second_order(), t_end=1.0, solver="ode3",
                    max_step=0.01).solver == "ode3"


def test_ode15s_handles_a_stiff_system_quickly():
    """Time constants 1 s and 0.1 ms: a ratio of 10⁴."""
    m = SimModel("stiff")
    m.add("Step", "r", step_time=0.0)
    m.add("TransferFcn", "G", num="1", den="1e-4, 1.0001, 1")
    m.connect("r", "G")

    start = time.perf_counter()
    r = simulate(m, t_end=5.0, n_points=500, solver="ode15s",
                 rtol=1e-6, atol=1e-9)
    elapsed = time.perf_counter() - start

    _, expected = ctl.step_response(ctl.tf([1], [1e-4, 1.0001, 1]), T=r.t)
    assert np.max(np.abs(r.trace("G.out") - expected)) < 1e-4
    # An explicit method needs ~10⁵ evaluations to stay stable here.
    assert r.n_steps < 3000, r.n_steps
    assert elapsed < 3.0


# ──────────────────────────────────────────────────────────────
#  Names refused
# ──────────────────────────────────────────────────────────────

def test_resolver_maps_every_family():
    assert resolve_solver("ode45") == ("RK45", False)
    assert resolve_solver("ode23") == ("RK23", False)
    assert resolve_solver("ode15s") == ("BDF", False)
    assert resolve_solver("ode23s") == ("Radau", False)
    assert resolve_solver("ode113") == ("LSODA", False)
    assert resolve_solver("ode4") == ("ode4", True)
    assert resolve_solver("ODE5") == ("ode5", True)
    assert resolve_solver("dop853") == ("DOP853", False)


def test_an_unknown_solver_is_refused_listing_the_choices():
    with pytest.raises(SimulationError) as info:
        simulate(_second_order(), t_end=1.0, solver="ode99")
    message = str(info.value)
    assert "ode99" in message
    for name in ("ode45", "ode15s", "ode4", "RK45", "BDF"):
        assert name in message


def test_an_unknown_solver_is_refused_even_without_continuous_states():
    """Such a model never reaches solve_ivp, so the name used to pass unseen."""
    m = SimModel("static")
    m.add("Step", "r", step_time=0.0)
    m.add("Gain", "k", gain="2")
    m.connect("r", "k")
    with pytest.raises(SimulationError, match="unknown solver"):
        simulate(m, t_end=1.0, solver="nonsense")


def test_ode15i_is_refused_with_the_reason():
    with pytest.raises(SimulationError, match="implicit"):
        simulate(_second_order(), t_end=1.0, solver="ode15i")


# ──────────────────────────────────────────────────────────────
#  The Simulation tab's menu
# ──────────────────────────────────────────────────────────────

def test_the_solver_combo_offers_simulink_names_first():
    pytest.importorskip("PySide6", reason="Qt not available")
    from PySide6.QtWidgets import QApplication

    from evans.ui.sim.sim_tab import SimTab

    QApplication.instance() or QApplication([])
    tab = SimTab()
    combo = tab._solver
    items = [combo.itemText(i) for i in range(combo.count())
             if combo.itemText(i)]                  # separators are blank
    assert items[0] == "ode45"
    assert combo.currentText() == "ode45"
    for name in ("ode23", "ode15s", "ode23s", "ode113",
                 "ode1", "ode2", "ode3", "ode4", "ode5"):
        assert name in items
    # The scipy names remain, after every Simulink name.
    for name in ("RK45", "DOP853", "LSODA", "Radau", "BDF"):
        assert items.index(name) > items.index("ode5")
    # Every entry is something simulate() accepts.
    for name in items:
        resolve_solver(name)
    tab.deleteLater()
