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

`python app.py --check` runs a headless self-test and exits with the number of failures.

---

## What it does

**Three workspaces**, on a rail down the left — `Ctrl+1/2/3`. Switching never tears
anything down: a running console session, a half-built diagram and a configured analysis
all survive being navigated away from.

| Workspace | What's in it |
| --- | --- |
| **Analyse** | The current control system — responses, margins, stability, design, lessons |
| **Model** | The block-diagram editor, its palette, inspector, scope and solver |
| **Console** | Command window, workspace variables, figures and scripts |

**A context bar** across the top of Analyse says what is loaded and whether it works:

```
G(s)  = 4 / (s² + 1.2s + 4)
K₂(s) = 2 · (s + 0.5) / s     ● stable    PM 60.0°   GM 11.9 dB   [Edit model ▾]
```

Factored transfer functions, an internal-stability verdict, and the headline margins.
A quantity that is undefined shows an em dash with a tooltip explaining why, not `nan` —
a phase margin that does not exist is not a failed calculation. The architecture diagram
and block editor are a panel behind `Ctrl+\`, not a permanent column.

**An analysis pane grid.** One, two or four panes, fourteen contents each, all reading the
same live architecture — so one edit moves every visible view at once. A fresh 2×2 opens on
step response, Bode, root locus and metrics, which is what tuning a controller actually
needs side by side. The seven classic analysis tabs are still there beside the grid, for the
workflows that are whole panels rather than one plot.

| Pane contents | |
| --- | --- |
| Step · Impulse · Ramp | Bode · Nyquist · Nichols |
| Pole-zero map · Root locus | Step metrics |
| System overview · Stability & Routh | Performance · Design · Modern control |

**A command window.** Fifty-nine MATLAB-shaped commands in ten groups — `tf`, `feedback`,
`step`, `bode`, `margin`, `stepinfo`, `rlocus`, `lqr`, `place`, `c2d`, `pidtune` — with a
workspace browser, history, tab completion and a script editor. `s` is the Laplace
variable, so `G = 1/(s**2 + 2*s + 1)` works. The console shares live references with the
GUI: setting a block at the prompt changes what every pane analyses.

**A working Simulink.** Fifty block types, hierarchical subsystems, a drag-and-drop canvas
with undo, RK4/RK45/Euler solvers, scopes, a properties inspector that leaves the diagram
visible, and `linearize()` to pull a state-space model out of a nonlinear diagram. Wire two
blocks by dragging between ports, or by clicking one and then the other.

**Three design apps**, docked beside the analysis they edit, from the Apps menu or the
prompt:

- **LTI Viewer** (`ltiview`) — any set of systems, eight response types, right-click to add
  characteristics. The menu offers only the ones that mean something for the response on
  screen: a rise time has nowhere to go on a Nyquist plot.
- **Control System Designer** (`sisotool`) — drag a closed-loop pole along the root locus
  and watch the Bode plot and step response follow. Or ask directly for the gain that gives
  ζ = 0.5, or 16% overshoot.
- **PID Tuner** (`pidtuner`) — response time and transient behaviour on two sliders, with
  a before/after overlay.

A **snapshot bar** above the analysis area freezes the whole architecture under a name,
restores it from anywhere, and Compare throws every stored design into the LTI Viewer at
once. Window geometry, workspace, dock layout and pane arrangement are remembered between
runs; View ▸ Reset layout puts them back.

It fits a **1280 × 720** screen, and is tested at 1366 × 768 and 1920 × 1080 too.

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
one that opens a figure tab in the Console workspace; the default just records. That is what makes `step(G)` both
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

684 tests, plus `ruff check .`. They are mostly *golden* tests: analytic values computed by
hand or by an independent route, not snapshots of whatever the code printed first. The
numeric signal solver and the symbolic one check each other; `python-control` acts as a
third opinion.

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
- Qt flattens a `str`-mixin enum through `QVariant`, so `QComboBox.currentData()` hands back
  a plain `str` that compares and hashes equal to the member — every dict lookup keeps
  working and the only symptom is `.value` raising somewhere else entirely.
- A **word-wrapped label is taller the narrower it gets**, so a panel that fits at 1400 px
  can demand more window height at 1280 px. Invisible to any check that measures at one
  width.

Run `python debug_runner.py` for a headless end-to-end sweep (176 checks) that builds every
tab and exercises every core path without a display.

---

## Lessons that check themselves

A **Lessons** menu loads one worked example per chapter: the satellite that proportional
control cannot hold (ch2), the right-half-plane zero that has to undershoot (ch3), the
second-order family (ch4), the two-degrees-of-freedom split (ch5), margins and the 2.3 dB
M-circle (ch6), the waterbed integral (ch7), Ziegler–Nichols (ch8).

The notes contain no prose about numbers. Each lesson carries `Claim` objects — a sentence,
a probe that *measures* the quantity from whatever model is currently loaded, and the value
the theory predicts — and the panel shows predicted beside measured. Change the plant and
the ticks become crosses in front of you.

Every claim of every lesson is checked by the test suite, so a note that stops being true
fails the build rather than quietly misleading whoever reads it. Several are exact:
ωc = √(2^⅔ − 1) with PM = 180° − 3·arctan ωc for the ch6 loop, a critical gain of exactly 8
at ω = √3 for ch8.

That is also what `--check` runs. A packaged build ships without the test suite, so its
self-test is the lessons' analytic claims plus a full offscreen build of the window — a pass
means the numbers agree with the theory, not merely that nothing raised.

---

## Status

Two plans, both complete.

[`PLAN.md`](PLAN.md) — the engine, in eight phases: correctness, the classical half, modern
control, the simulator, the command window, the apps, the course lessons, packaging.

[`UI-PLAN.md`](UI-PLAN.md) — the interface, in eight more. The application had grown to
28 modules and 8 tabs while keeping the layout of a 6-tab viewer, and its minimum window
size had reached **2038 × 643** — wider than a 1920 monitor, because the Simulink toolbar
was one unbreakable row and a tab bar is as wide as its widest tab. That plan's status
table records what is done, what is partial, and the two items left: retrofitting the
classic analysis tabs onto the shared design system, and a bundled icon set.

Both files record what was deliberately **not** built, and why. The one worth repeating:
there is no Python Function block, because a block that executes arbitrary text from a
shared model file is a code-execution surface, not a feature.

### Building a standalone copy

```bash
pyinstaller --clean --noconfirm packaging/fauxmatlab.spec
```

A one-*folder* build: one-file unpacks the whole Qt runtime on every launch, which for
PySide6 plus scipy plus sympy is several seconds before the window appears. It produces two
entry points over one bundle — `FauxMatlab.exe` and `FauxMatlab-check.exe`, because a
windowed executable on Windows has no stdout, so `--check` there would set an exit code and
print nothing.

---

## Not included

The CLACO and DYBAC lecture decks the app was built against are the lecturers' copyright
and are not redistributed here. Point the app at your own copy locally; `COURSE MATERIAL/`
is gitignored.

No dependency on **slycot**. Four routines that would normally need it — `minreal`, `gram`,
modal canonical form, and `d2c` — are implemented directly (SVD staircase, Lyapunov solve,
eigendecomposition with real 2×2 blocks, matrix logarithm) so that a clean
`pip install` is all it takes.
