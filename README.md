# FauxMatlab

A control-systems workbench in Python — classical and modern control, a block-diagram
simulator, and a MATLAB-shaped command window, in one PySide6 application.

It is not a MATLAB clone. It is a *slice*: the part of MATLAB, Simulink and the Control
System Toolbox that two courses actually use — **CLACO** (classical, frequency-domain)
and **DYBAC** (modern, state-space) — built so that every number it shows can be traced
back to something exact.

```bash
pip install -e ".[dev]"
python app.py
```

Requires Python 3.12+. The import package is `fakematlab`; the repository is `FauxMatlab`.

---

## What it does

**Eight tabs, one live model.** Change the plant anywhere and every tab, plus the
console, follows.

| Tab | What's in it |
| --- | --- |
| 🔬 **System** | Plant and controller entry, block diagram, pole/zero map, exact closed-loop transfer functions |
| ⏱ **Time** | Step, impulse, ramp and arbitrary inputs; step metrics computed against the *exact* final value |
| 〜 **Frequency** | Bode, Nyquist, Nichols; gain/phase/modulus margins; M-circles; design gabarits |
| 🔒 **Stability** | Root locus with continuous branches, Routh–Hurwitz, symbolic stability ranges in K |
| 📊 **Performance** | Error constants, system type, sensitivity/complementary sensitivity, the waterbed integral |
| 🎛 **Design** | Lead, lag, lead-lag and PID synthesis; Ziegler–Nichols; before/after snapshots |
| ⛓ **Simulink** | A real block-diagram editor and solver — see below |
| ▦ **Modern** | State space, controllability/observability, Gramians, LQR/LQI, observers, Kalman, c2d/d2c, deadbeat |

**A command window.** About sixty MATLAB-shaped commands — `tf`, `feedback`, `step`,
`bode`, `margin`, `stepinfo`, `rlocus`, `lqr`, `place`, `c2d` — with a workspace browser,
history, tab completion and a script editor. `s` is the Laplace variable, so
`G = 1/(s**2 + 2*s + 1)` works. The console shares live references with the GUI: setting a
block at the prompt changes what every tab analyses.

**A working Simulink.** Fifty block types, hierarchical subsystems, a drag-and-drop canvas
with undo, RK4/RK45/Euler solvers, scopes, and `linearize()` to pull a state-space model
out of a nonlinear diagram.

**Three apps**, from the Apps menu or the prompt:

- **LTI Viewer** (`ltiview`) — any set of systems, seven response types, right-click to add
  characteristics. The menu offers only the ones that mean something for the response on
  screen: a rise time has nowhere to go on a Nyquist plot.
- **Control System Designer** (`sisotool`) — drag a closed-loop pole along the root locus
  and watch the Bode plot and step response follow. Or ask directly for the gain that gives
  ζ = 0.5, or 16% overshoot.
- **PID Tuner** (`pidtuner`) — response time and transient behaviour on two sliders, with
  a before/after overlay.

A **snapshot bar** sits above the tabs: freeze the whole architecture under a name, restore
it from any tab, and Compare throws every stored design into the LTI Viewer at once.

---

## Three things it takes seriously

### 1. The block algebra is exact, not hand-derived

Closed-loop transfer functions are not typed in from a textbook. The diagram is a graph
obeying one rule —

$$y_i = H_i \cdot \left( \sum_j A_{ij}\, y_j + b_i\, u \right)$$

— and any transfer function is obtained by clearing denominators into a polynomial matrix
over ℚ(s) and solving it symbolically. Nothing is cancelled, so **hidden modes survive**:
an unstable pole that a pole–zero cancellation removes from the reference response is still
there, still visible from the disturbance input, and the internal-stability report says so.

This replaced twelve hand-derived formulas, of which **six were wrong**.

### 2. Discrete blocks sample and hold

A discrete block reads its inputs at a sample hit and holds its outputs until the next one.
That sounds obvious; getting it wrong is subtle. An earlier version let the proportional
term of a discrete PID pass the *live* continuous error straight through, so a 50 Hz
controller produced a control signal that changed at every solver step — 1498 changes over
three seconds instead of 150. Sampling properly also makes discrete blocks break algebraic
loops, which is exactly what real hardware does.

### 3. Figures are described, not drawn

The console API builds a `FigureSpec` and hands it to an installed *sink*. The GUI installs
one that opens a docked plot; the default just records. That is what makes `step(G)` both
headlessly testable and drawable, from one implementation — and why the API never imports Qt.

The apps follow the same split, which is what lets the PID tuner make a strong claim and
have it checked. It does not search for gains: at the target crossover the controller's
required magnitude and phase are both fixed, so a PI's two parameters are determined
outright and a PID spends its third on the classical `Ti = 4·Td`. The achieved margin is
therefore *exact* — `margin(C·G)` returns the requested ωc and φm to 1e-14, and a test says
so. Where a structure cannot meet a target, it refuses and names the reason: a PI only ever
subtracts phase, so asking one for a crossover above the plant's phase budget is impossible
rather than merely inaccurate.

---

## Tests

```bash
pytest
```

511 tests. They are mostly *golden* tests: analytic values computed by hand or by an
independent route, not snapshots of whatever the code printed first. The numeric signal
solver and the symbolic one check each other; `python-control` acts as a third opinion.

Several are there to pin down a bug that was genuinely hard to see:

- `ctl.stability_margins` returns **six** values, not four — slicing `[:4]` silently
  reports the modulus margin as a frequency.
- pyqtgraph's `setLogMode(x=True)` expects **raw** frequencies for data and **log₁₀**
  coordinates for annotations. Passing `np.log10(ω)` to both produced NaN below ω = 1 and
  quietly truncated every Bode plot.
- `np.roots` splits a repeated real root into a complex pair a few parts in 10⁶ apart, so
  `1/(s+1)³` factors as `(s²+2s+1)(s+1)` unless the roots are cleaned.
- RK4 converging at *first* order because the integrator recorded the state from the end of
  a straddling step rather than stepping onto the output point.
- A pyqtgraph plot **title** long enough to outgrow its panel lays the whole plot out wider
  than the scene it sits in, pushing every curve off the right-hand edge. The panel looks
  blank, every value in it is correct, and nothing reports an error.

Run `python debug_runner.py` for a headless end-to-end sweep (175 checks) that builds every
tab and exercises every core path without a display.

---

## Status

Phases 1–6 of [`PLAN.md`](PLAN.md) are done: correctness, the classical half, modern
control, the simulator, the command window and the apps. Remaining are per-chapter worked
examples and packaging.

`PLAN.md` also records what was deliberately **not** built, and why. The one worth
repeating: there is no Python Function block, because a block that executes arbitrary text
from a shared model file is a code-execution surface, not a feature.

---

## Not included

The CLACO and DYBAC lecture decks the app was built against are the lecturers' copyright
and are not redistributed here. Point the app at your own copy locally; `COURSE MATERIAL/`
is gitignored.

No dependency on **slycot**. Four routines that would normally need it — `minreal`, `gram`,
modal canonical form, and `d2c` — are implemented directly (SVD staircase, Lyapunov solve,
eigendecomposition with real 2×2 blocks, matrix logarithm) so that a clean
`pip install` is all it takes.
