# FakeMatlab v2 — from a classical-control workbench to a MATLAB slice

**Goal.** Make this the tool you'd reach for instead of MATLAB for two courses — CLACO
(classical, `COURSE MATERIAL/…classical_approach…pdf`, 254 slides, ch1–8) and DYBAC (modern /
state space) — plus a Simulink that actually simulates.

The v1 spec is archived at [docs/PLAN-v1-classical-spec.md](docs/PLAN-v1-classical-spec.md).
It is ~90% implemented. This document supersedes it.

---

## Part 0 — Where the project actually stands

### 0.1 What exists

| Layer | Files | Lines | State |
|---|---|---|---|
| `core/` engine | 8 modules | ~2 100 | Runs. Numerically wrong in places (§0.3). |
| `ui/` | 12 modules | ~2 700 | Launches, all 6 tabs render without crashing. |
| `tests/` | 6 files, 64 tests | ~500 | All green — but they don't test the things that are broken. |
| `debug_runner.py` | 1 | 341 | 148 pass / 3 fail. Genuinely useful; keep and grow it. |

Verified this session: `python -m pytest -q` → 64 passed. Offscreen GUI smoke test cycles all
six tabs, clicks a block and a signal tap, no exceptions.

### 0.2 What's missing outright

- **No modern control at all.** No state space, no `A,B,C,D`, no controllability/observability,
  no pole placement, no LQR, no observers, no Kalman, no discrete-time. Zero lines.
- **No Simulink.** `ui/diagram/` draws a *picture* of one fixed architecture. There is no model
  object, no block library, no wire editing, no solver, no scope. `FixedDiagramView.update_block`
  only swaps a TF; nothing on the canvas is editable.
- **No command layer.** No console, no workspace, no scripting. A "MATLAB slice" without a
  command window and a variable workspace isn't recognisable as MATLAB.
- **No project hygiene.** Not a git repo. No `pyproject.toml` / `requirements.txt`, no README,
  no CI. `__pycache__/` and `.pytest_cache/` sit in the tree.

### 0.3 What's broken — measured, not guessed

These are the reason Phase 1 exists. Each was reproduced this session.

**(a) 6 of 12 closed-loop transfer functions are wrong.**
Solved the loop by hand and compared against `CourseArchitecture.get_closed_loop_tf` at
`s = 0.7 + 1.3j` for `G = 1/(s+1)`, `K₂ = (2s+1)/s`:

| Case | Wrong pairs |
|---|---|
| `K₁ = 1, H = 1` | `di→u`, `n→e` |
| `K₁ ≠ 1, H = 1` | `r→e`, `di→u`, `n→e` |
| `K₁ ≠ 1, H ≠ 1` | `r→y`, `r→e`, `di→u`, `do→u`, `n→u`, `n→e` |

Root causes, in [architecture.py:160-220](fakematlab/core/architecture.py:160):
- `di→u` returns `−S·K₂`; the course equation (slide 157, ch5 19/24) and the algebra both give
  `−S·K₂·G`. Missing plant factor. — [architecture.py:198](fakematlab/core/architecture.py:198)
- `n→e` returns `+S`; correct is `−S`. Sign flip. — [architecture.py:219](fakematlab/core/architecture.py:219)
- `r→e` returns `S`; correct is `S·K₁`. Feedforward dropped. — [architecture.py:186](fakematlab/core/architecture.py:186)
- **Every formula assumes `H = 1`.** `loop_tf()` correctly includes `H`, so `T = L/(1+L)` is
  right, but `r→y = T·K₁` is off by `1/H`, and the `u` row ignores `H` entirely. The `H` block is
  drawn on the canvas and editable — so it is a trap, not a feature.

**(b) Every Bode plot is silently truncated.** The tabs call `setLogMode(x=True)` *and* pass
`np.log10(omega)` as the x data. pyqtgraph takes `log10` again internally, so all ω < 1 become
`NaN` and are dropped; the rest is on a doubly-compressed axis. Reproduced directly:

```
pi.setLogMode(x=True); c = pi.plot(np.log10(w), ...)   →  xDisp range: nan nan
pi.setLogMode(x=True); c = pi.plot(w, ...)             →  xDisp range: -2.0 2.0   ← correct
```

18 call sites across [frequency_tab.py](fakematlab/ui/tabs/frequency_tab.py),
[performance_tab.py](fakematlab/ui/tabs/performance_tab.py),
[design_tab.py](fakematlab/ui/tabs/design_tab.py). Confirmed visually in a screenshot: the
magnitude curve starts a third of the way across the axis. **The low-frequency half of every Bode
plot in the app does not exist.** Margin annotations (`add_vline(np.log10(wc))`) land in the wrong
place for the same reason.

**(c) Internal stability is never checked.** Ch6 1/26 defines closed-loop stability as *all*
closed-loop TFs being stable. The app verdicts on one TF at a time, so an unstable pole/zero
cancellation between `K₂` and `G` reports "✓ Stable". This is exactly the trap the chapter exists
to teach; the tool currently teaches the wrong thing.

**(d) Ziegler–Nichols is unusable.** 3 of 3 failures in `debug_runner`. `zn_ultimate` uses
`root_locus` whose `_find_marginal_gain` returns `nan` for every test system, because
`np.sort_complex` re-sorts roots at each `K` so branch tracking is meaningless. `zn_step` raises
on any plant without dead time — correct in principle, but the app offers no Padé delay to create
one (see (f)), so the button can never succeed.

**(e) `nichols()` M-circles are wrong.** The code admits it in a comment, then plots the *Nyquist*
M-circle mapped naïvely to (phase, dB) — that's a different locus. Use
`ctl.nichols_grid` data or derive properly.

**(f) Dead code / stubs.**
- `pure_delay_pade` returns a **tuple**, not a TF: the conversion is below an unconditional
  `return`. — [tf_utils.py:116](fakematlab/core/tf_utils.py:116). Nothing calls it.
- `SignalGraph.get_tf(fit=True)` imports `tf_utils.fit_frequency_response`, which doesn't exist.
- `LeadLagParams.alpha` defaults to `10.0` with `is_lead=True`, and `lead_tf` raises on `α ≥ 1`.
  The default construction is an exception.
- `analyse()` catches `ZeroDivisionError` for DC gain, but numpy raises a `RuntimeWarning` and
  returns `inf`/`nan` instead — the guard never fires.

**(g) 15 silent `except: pass` / `except: return` in the UI.** When a computation fails the tab
just goes blank. Debugging is guesswork.

**(h) Usability, from the screenshots.** `_auto_tspan` uses `50/|Re(p)|`, so a pole at −1 gives a
50 s window and the whole transient is squeezed into the left 5% of the plot. The diagram panel is
a 320–520 px column holding a diagram rendered at ~15% of the available area. The metrics table
shows 2 rows of 10.

### 0.4 One genuinely good thing

`SignalGraph.frequency_response` — the `(I − H·A)⁻¹` matrix solver in
[signal_graph.py:161](fakematlab/core/signal_graph.py:161) — is **correct**. I checked all 12
input/output pairs against hand-solved ground truth: 9 exact, and the 3 `n→*` mismatches are a
pure sign-convention difference (the graph subtracts noise at [architecture.py:287](fakematlab/core/architecture.py:287),
the course diagram adds it), not an error in the solver.

So the *numerical* path is right and the *hand-derived analytic* path is wrong. That inverts the
obvious fix and drives decision D1.

---

## Part 1 — What "MATLAB slice" means here

Scope, explicitly bounded. Everything in **Have** or **Build**; **Won't** is stated so it doesn't
creep back in.

| MATLAB thing | Verdict |
|---|---|
| Control System Toolbox — classical (tf, step, bode, nyquist, nichols, margin, rlocus, routh) | Have, needs fixing |
| Control System Toolbox — modern (ss, ctrb, obsv, place, lqr, kalman, c2d, gram, balred) | **Build** (Phase 3) |
| Simulink — canvas, block library, solvers, scopes, subsystems | **Build** (Phase 4) |
| Command Window + Workspace + scripting | **Build** (Phase 5) |
| LTI Viewer / `sisotool` / PID Tuner style apps | **Build** (Phase 6) |
| Symbolic Math (Routh with free `K`, partial fractions, Laplace) | Partly have; extend |
| Simscape, Stateflow, code generation, HDL, MIMO robust control (H∞, μ) | **Won't** |
| General-purpose numerics (matrix language, `.m` file compatibility) | **Won't** — Python is the language; MATLAB-shaped *aliases* only |

The unifying idea: **one model, many views.** A Simulink model can be linearised into a TF/SS and
land in the analysis tabs; a TF designed in the analysis tabs can be dropped into a Simulink
model. That bridge is what makes it a slice of MATLAB rather than two unrelated apps.

---

## Part 2 — Six decisions to make before writing code

**D1 — The block-diagram graph becomes the single source of truth; derive TFs *exactly*, not per-ω.**
Delete the hand-written formulas in `architecture.py`. Build one `Model` graph and derive any
input→output TF by symbolic linear solve over ℝ(s): build `(I − H(s)·A)` with sympy rational
entries, solve, `cancel` to `N(s)/D(s)`, convert to a `control.TransferFunction`. This gives exact
poles/zeros (so Routh, root locus and pole maps stay correct) and handles any topology including
`H ≠ 1`, which is what breaks today. Keep the existing numeric solver as the cross-check oracle in
tests. *Cost:* ~1 day. *Payoff:* class (a) bugs become structurally impossible, and free-form
Simulink topologies get analysis for free.

**D2 — Write our own simulation engine; do not build Simulink on `ctl.interconnect`.**
`interconnect` works well for the pure-continuous nonlinear case (spiked it: PI + saturation +
plant, 1001 points in 0.13 s, correct clipping). But it **cannot mix timebases** — a continuous
plant and a discrete controller raises `ValueError: Systems have incompatible timebases`. A
Simulink without multi-rate isn't Simulink. Build a proper engine (Phase 4.2) and use
`interconnect` only as a validation oracle for continuous-only models.

**D3 — Keep the fixed course architecture as a *preset*, not as the architecture.**
The ch5 2-DOF diagram is the spine of the course and must stay one click away. But it becomes a
saved `Model` file that the generic engine loads — not a hard-coded class. Prevents the
codebase from forking into "fixed" and "free-form" halves.

**D4 — MATLAB compatibility is aliases, not a language.**
No `.m` parser. A Python REPL with a preloaded namespace where `tf`, `step`, `bode`, `margin`,
`lqr`, `place`, `c2d`, `stepinfo` behave MATLAB-shaped. Course snippets mostly transcribe;
nobody maintains a parser. If `.m` support is wanted later it's an additive Phase 8.

**D5 — No slycot; use scipy for the linear-algebra gaps.**
Verified: `lqr`, `place`, `acker`, `lqe`, `care`, `dare`, `ctrb`, `obsv`, `c2d` all work without
it. `ctl.gram` raises `ControlSlycot`. Wrap `scipy.linalg.solve_continuous_lyapunov` /
`solve_discrete_lyapunov` ourselves — 20 lines, avoids a Fortran toolchain on Windows.
Also note `ctl.d2c` does not exist in 0.10.1; implement it.

**D6 — Errors surface, always.**
Replace all 15 silent handlers with a `@guard` decorator that draws the traceback into the panel
and logs it. A blank tab must become impossible.

---

## Part 3 — Target structure

```
app.py
fakematlab/
  core/
    tf_utils.py        (fix: pade, dc_gain; add partial fractions, Laplace pairs)
    model.py       NEW  Model/Block/Port/Connection — the one graph type
    algebra.py     NEW  exact symbolic I/O transfer functions over the graph  [D1]
    internal.py    NEW  internal stability, hidden modes, pole-zero cancellation  [0.3c]
    timeresp.py        (fix: _auto_tspan, settling on non-convergent)
    freqresp.py        (fix: nichols M-circles; migrate off deprecated ctl.bode)
    stability.py       (fix: root-locus branch tracking; add Jury)
    performance.py     (keep)
    tuning.py          (fix: lead/lag defaults; rebuild Z-N on fixed root locus)
    statespace.py  NEW  ss, tf↔ss, canonical forms, similarity, minreal
    structural.py  NEW  ctrb/obsv, PBH, Kalman decomposition, Gramians, balred  [D5]
    statefbk.py    NEW  place, acker, LQR, LQI, servo augmentation, Nbar
    observers.py   NEW  Luenberger, reduced-order, Kalman, separation principle
    discrete.py    NEW  c2d/d2c, Jury, discrete rlocus, deadbeat
    sim/           NEW  the Simulink engine  [D2]
      blocks/          library: sources, continuous, discrete, math, nonlinear, routing, sinks
      compile.py       flatten subsystems, classify, sort, detect algebraic loops
      solver.py        fixed/variable step, multi-rate scheduler, zero-crossing events
      linearize.py     numerical Jacobian about an operating point → ss  (the bridge)
      io.py            .fmdl JSON save/load
  ui/
    plots.py           (fix: log-axis contract; BodeAxisItem with decade ticks)
    diagram/           rewritten as the live canvas: palette, wiring, undo, params
    console/       NEW  REPL dock, workspace browser, figure windows  [D4]
    tabs/              existing 6, fixed + 5 new modern-control tabs
tests/
  golden/          NEW  analytic ground truth (2nd-order metrics, known margins, LQR on a
                        textbook plant) — the tests that would have caught §0.3
docs/
```

---

## Part 4 — Phases

Each phase ends with a stated acceptance test. Estimates are focused working days.

### Phase 1 — Correctness ✅ **DONE**

1. ✅ `core/model.py` + `core/algebra.py`: exact symbolic I/O TFs over a graph. [D1]
2. ✅ `CourseArchitecture` ported onto it; the 12 hand-derived formulas deleted.
3. ✅ Log-axis contract fixed in `plots.py` — `make_freq_plot` / `plot_freq` /
   `freq_vline` / `freq_marker` / `freq_text` all take **raw ω**, with a `LogFreqAxis`
   giving decade majors and 2…9 minors.
4. ✅ `core/internal.py`: internal stability over all 12 TFs, hidden-mode and
   cancellation detection, plus a `deceptive` flag for the case where the reference
   response looks clean and the loop is not.
5. ✅ `_auto_tspan`, root-locus branch tracking (Hungarian assignment), exact
   `marginal_gain` via sympy, `pure_delay_pade`, `LeadLagParams`, Nichols M-contours,
   `dc_gain`.
6. ✅ `@guard` + `ErrorBanner`; all 15 silent handlers gone.
7. ✅ Migrated off deprecated `ctl.bode(plot=False)`.

**Also found and fixed during the work** (not in the original plan):
- `ctl.stability_margins` returns **six** values `(gm, pm, sm, wpc, wgc, wms)`; slicing
  the first four silently reports the stability margin as a crossover frequency.
  Now unpacked in exactly one wrapper.
- `compute_step_metrics` estimated `y∞` from the tail of a finite simulation, biasing
  every settling/rise time by ~6%. Now uses the exact `amplitude·G(0)` when stable.
- `guard` nesting: an inner guard's banner was cleared by the outer guard's success
  path. Fixed with a generation counter.
- Design tab could build an invalid lead/lag (α on the wrong side of 1); α is now
  constrained to the selected structure.

**Acceptance — met.** `tests/golden/` asserts all 12 closed-loop TFs against hand-solved
algebra for `K₁≠1, H≠1` *and* against the independent numerical solver; 2nd-order
`Mp`/`tp`/`ts`/`tr` against the ch.4 closed forms; margins against
`control.stability_margins` and analytic values (`1/(s+1)³` → GM 18.06 dB at √3);
`Ku=8, ωu=√3` exactly; no NaN below ω=1. **210 tests pass** (was 64).
`debug_runner.py`: **153 pass, 0 errors** (was 148/3).

### Phase 2 — Make the classical half genuinely good ✅ **DONE**

- ✅ Layout: left panel widened to 420–760 px and the diagram height capped, so a 3.3:1
  diagram no longer renders at 15% of a tall empty column; `fit_view` resets the
  transform and double-click re-fits. Metrics table sized for all ten rows.
- ✅ Symbolic Routh now **reduces the conjunction** of first-column inequalities to an
  interval: `0 < K < 6`, `-1 < K < 8`, `K > 1`. Cross-checked against `marginal_gain`.
- ✅ Padé delay wired into the block editor as two new modes — *Pure delay (Padé)* and
  *FOPDT (delay + lag)* — which is what makes the Z-N reaction-curve button reachable.
- ✅ Bode templates (gabarits, ch.6 25–26/26 and ch.7 17/20): low-frequency `|S| ≤ s_d`
  and high-frequency `|T| ≤ t_n` drawn as forbidden regions on `|L|`, with an
  infeasibility warning when they overlap.
- ✅ Bode–Freudenberg (ch.7 18/20) computed, not just asserted: `∫ln|S|dω` evaluated on
  a three-segment grid, verified against `π·Σ Re(pₖ)` to 4e-8 for an RHP pole and 4e-5
  for a stable plant. Amplified bands shaded on the trade-off plot. Refuses when the
  closed loop is unstable, since the theorem assumes otherwise.
- ✅ `core/report.py` MATLAB-style text report; `core/session.py` with a versioned
  format, v1 back-compatibility, and all-or-nothing loading. Export menu: copy report,
  save report, export tab as PNG.
- ✅ Corrected `|S| + |T| = 1` → `S + T = 1`; the magnitudes satisfy `|S|+|T| ≥ 1`, and
  the sum is now plotted so the inequality is visible.
- ✅ `factored_str` collapses repeated roots to powers and drops a unit denominator:
  `1/(s+1)³` instead of `(s² + 2s + 1)(s + 1)`.

### Phase 3 — Modern control ✅ **DONE**

Five core modules, each tested before any UI existed:

| Module | Contents |
|---|---|
| `core/statespace.py` | construction, tf↔ss, similarity transforms, controllable/observable/**modal** forms, minimal realisation, per-mode residues, modal response decomposition |
| `core/structural.py` | ctrb/obsv + ranks, **PBH test per mode**, stabilizability/detectability, Gramians, Hankel singular values, balanced realisation and reduction with its error bound, Kalman decomposition |
| `core/statefbk.py` | robust pole placement, Ackermann, LQR (with the Riccati solution), LQI, `Nbar` reference scaling, control-effort extraction |
| `core/observers.py` | Luenberger, reduced-order, Kalman filter, observer-based compensator, separation-principle verification, estimation-error response |
| `core/discrete.py` | c2d (5 methods, with prewarp), **d2c** (absent from python-control), Jury criterion, deadbeat, sample-rate sweep, z→(ζ, ωn) |

**UI** — one **Modern** tab with five sub-views (State Space · Structure · State
Feedback · Observer/Kalman · Discrete) over a single shared `ModernContext`. Grouped
rather than five top-level tabs, which would have made the tab bar unreadable. Editing
or reducing the model anywhere updates every view, and a design made for the previous
model is cleared rather than silently kept at the wrong dimension. Bridges both ways:
**← Load plant G(s)** and **Send to analysis →**.

**Acceptance — met.**
- LQR on the ch.2 satellite reproduces the analytic Riccati solution
  `K = [1/√R, √((2√R+1)/R)]` to **1e-9** at three weightings, and the returned `P`
  satisfies the ARE to 1e-9.
- `place` and `acker` agree to 1e-7 and both hit the requested eigenvalues to 1e-9.
- `c2d` → `d2c` round-trips to **1e-13** across three plants and two rates.
- A non-minimal realisation is correctly flagged, and `minimal()` reduces it while
  preserving the transfer function to 1e-9.
- The separation principle is *verified*, not asserted: 1.2e-12 mismatch.
- Balanced reduction stays inside the Hankel bound `2·Σσ` at every order.

**Four slycot dependencies routed around** (decision D5 turned out to reach further than
expected — `control.gram` was only the first):
- `minreal` → SVD staircase projection onto the controllable subspace, then its dual.
- `gram` → `scipy.linalg.solve_continuous_lyapunov`.
- `canonical_form(..., "modal")` → eigendecomposition with 2×2 real blocks for
  conjugate pairs.
- `d2c` does not exist at all → matrix logarithm for ZOH, with an explicit refusal when
  no real continuous equivalent exists.

**Bugs found while building:**
- Balancing divided by `√σ` without checking minimality, so a redundant state produced a
  singular transform and silent nonsense rather than an error.
- `_psd_sqrt` via Cholesky failed on a semi-definite Gramian — a perfectly reducible
  system raised `LinAlgError`. Now a symmetric eigendecomposition.
- `control_effort` returned `(1, N)` rows for a 2-output system, which no plotting call
  accepts.
- Qt's `valueChanged` passes the new value into slots also connected to argument-less
  signals, so the Discrete view's refresh raised `TypeError` on every spin-box change.
- `MatrixEditor` parsed inside a Qt slot, outside any `@guard`, so a typo in A escaped as
  a crash instead of reaching the error banner. It now emits raw text and the guarded
  view parses it.
- Eigenvalue plots autoscaled their imaginary axis to round-off (±6e-6), so three
  coincident real poles appeared spread across the plot. `frame_poles` floors the
  imaginary range at a fraction of the real one.

### Phase 5 — MATLAB shell ✅ **DONE** · [D4]

**`fakematlab/console/`** — the API, testable with no display:
- `api.py` — **~60 MATLAB-shaped commands** in nine groups. Not just names: the
  *shapes* match, which is what makes transcription work. `stepinfo` returns MATLAB's
  field names, `margin` returns `(Gm, Pm, Wcg, Wcp)` with `Gm` in absolute units and the
  frequencies in MATLAB's confusing order, `damp` displays a table, `allmargin` adds the
  modulus margin MATLAB omits. `s` is the Laplace variable, so `G = 1/(s**2+2*s+1)`
  works. Every command delegates to the same core functions the tabs use — a console
  that disagreed with a tab would be worse than no console.
- `figures.py` — a plot command builds a **`FigureSpec`** and hands it to the installed
  *sink*. The UI installs one that opens a docked figure; the default just records. That
  is what keeps `step(G)` runnable from a headless script and drawable in the window
  from one implementation.
- `interpreter.py` — persistent namespace, captured output, `ans`, statement-by-statement
  script execution so a failure names the line that stopped it.

**`fakematlab/ui/console/`** — command window with transcript, ↑/↓ history, Tab
completion (user names before commands) and Shift+Return continuation; workspace browser
that lists *user* variables only and opens a system in the analysis tabs on double-click;
a capped figure dock; a script editor running against the same workspace (F5).

**Two bridges**, both live rather than copies: the console starts with `G`, `K2`, `arch`
and `model` already bound, so `arch.set_block('G', tf([3],[1,3]))` at the prompt changes
what the tabs analyse. View ▸ *Send current plant to the console* adds `L` and `T`.

**MATLAB habits: accommodated, translated or explained.** A trailing `;` suppresses the
echo. `%` becomes a comment — but only when the line does not already parse, so a real
modulo survives. The rest are **not** silently rewritten, because guessing would change
meaning; each gets a message naming the fix instead:
`[1 2 3]` → "needs commas", `s^2` → "Python uses ** for powers" (caught at *run* time,
since `^` is valid Python), `end` in an index, `~=`, and a case-slipped name.

**The nargout problem.** MATLAB chooses between drawing and returning by counting output
arguments; Python cannot see that. Rather than pick one, the commands return the data
*and* draw, with a one-line `repr` — so `step(T)` at a prompt shows
`<time response: 2000 points over 0…22>` instead of two thousand numbers, and
`t, y = step(T)` still unpacks. `damp` uses the same trick to be a table and a triple at
once.

**Acceptance.** 58 tests: every advertised command exists and is callable, `stepinfo`
reproduces the ch.4 overshoot, `margin` matches the analytic `Gm = 8` at `ω = √3`,
`errconst` and `lqr` agree with the core modules, every figure kind renders, and the
console survives an error and keeps its namespace.

### Phase 6 — The "apps" ✅ **DONE**

1. ✅ **LTI Viewer** — `core/viewer.py` + `ui/apps/lti_viewer.py`. Any set of systems, seven
   response types, right-click to add characteristics (the MATLAB gesture) with the menu
   offering only the ones that mean something for the response on screen.
2. ✅ **Control System Designer** — `core/designer.py` + `ui/apps/designer_app.py`. Drag a
   closed-loop pole on the root locus; Bode and step follow. Compensator poles/zeros editable,
   plus "set K for ζ" and "set K for overshoot".
3. ✅ **PID Tuner** — `core/pidtune.py` + `ui/apps/pid_tuner.py`. Response-time and
   transient-behaviour sliders, before/after overlay, and a readout that says what each slider
   actually sets.
4. ✅ **Snapshot/compare generalised** — `core/collection.py` + `ui/apps/snapshots.py`. The bar
   sits above the tabs, so a snapshot is of the *architecture*, not of whichever panel is open;
   Compare hands the stored designs to the LTI Viewer.
5. ✅ Console commands `pidtune`, `ltiview`, `sisotool`, `pidtuner`, through an **app sink**
   mirroring the figure sink — so the API stays Qt-free and a typed command and a clicked menu
   item reach the same window.

**Three decisions worth recording.**

*The tuner solves, it does not search.* At the target crossover the controller's required
magnitude and phase are both known, so a PI (two free parameters) is determined outright and a
PID spends its third on the classical `Ti = 4·Td`. The achieved margin is therefore **exact**:
`margin(C·G)` returns the requested `ωc` and `φm` to 1e-14. Where a structure cannot meet a
target — a PI asked to *add* phase — it refuses and names the reason instead of returning gains
that do something else.

*The locus is computed at unit gain*, so it does not move when the gain does. Dragging a pole is
then a position on a fixed curve, which is what makes the gesture legible; `evaluate()` takes the
locus back as an argument so a drag costs no root solves.

*A dragged point is projected onto the locus*, not fed to `K = 1/|L(s)|`. Off the locus that
formula answers a different question, and the reported distance says how far off the request was.

**Acceptance.** 79 tests (511 total, up from 432) and 22 more `debug_runner` checks (175, 0
errors). The golden values are analytic: ζ = 0.5 on `1/(s(s+1)(s+2))` gives **K = 28/27** exactly
(hand-derived in the test's docstring), the overshoot and damping entry points agree to 1e-5, a
known gain round-trips through `point_to_gain` to 1e-10, and the locus crossing comes back as
K = 6, ω = √2.

**Bugs found while building it.**

- **A long plot title silently blanks its panel.** A pyqtgraph title is a `LabelItem` whose
  *minimum* width is the text width, so a 63-character title laid a 434-pixel panel out 1080
  wide and pushed every curve off the right-hand edge. Nothing raised; the values were all
  correct; the plot just looked empty. Fixed centrally in `plots.set_title`, which caps the
  label so the view box drives the layout — this also repaired the console figure view's
  root-locus and Nyquist titles, which had the same defect since Phase 5.
- **Qt flattens a `str`-mixin enum.** `QComboBox.itemData` stores the member in a `QVariant` and
  returns a plain `str`, which compares and hashes equal to the member — so every dict lookup
  still worked and the only symptom was `.value` raising three calls later, in a different file.
- **`_new_session` left stale architecture references** in the snapshot bar and the console, so
  a snapshot taken afterwards would have been of a plant no longer on screen.
- **The neutral crossover is wrong for a PI.** Defined as "where the controller needs no phase",
  it is right for a PID but gives a PI `Ki ≈ 1e-6` — a P controller wearing a PI's name. Each
  structure now aims at the phase it can actually supply.

### Phase 7 — Course content ✅ **DONE**

A **Lessons** menu with one worked example per chapter (ch2 satellite, ch3 NMP undershoot, ch4 the
second-order family, ch5 the 2-DOF architecture, ch6 margins and M-circles, ch7 the waterbed, ch8
Ziegler–Nichols). Each loads a model, opens the right tab, and shows a note.

**The decision that makes this worth having.** A lesson contains no prose about numbers. It
contains `Claim` objects — a sentence, a *probe* that measures the quantity from whatever model is
loaded, and the value the theory predicts. The panel shows predicted beside measured, and
`test_lessons.py` checks every claim of every lesson. A note that stops being true fails the build
instead of quietly misleading a student, and changing the plant turns the ticks into crosses in
front of you, which is a better demonstration than a paragraph.

Claims carry a `mode` — `equals`, `at_least`, `at_most` — because some of the course's results are
bounds. Ch.3's undershoot theorem says *Mu > 1/(e^{c·ts} − 1)*; pinning that to a number would be
asserting the simulation rather than the theorem.

**Acceptance.** 60 tests. 29 claims across 7 lessons, several exact: ωc = √(2^⅔ − 1) and
PM = 180° − 3·arctan ωc for ch6, Pc = 8 and Tc = 2π/√3 for ch8, Mp = exp(−πζ/√(1−ζ²)) for ch4.
Plus the arguments the notes make, checked independently — that *no* proportional gain stabilises
a double integrator (not just the one loaded), and that an unstable pole makes ∫ln|S| = π·Σ Re(pᵢ).

**Two claims of mine that were wrong, and the code was right.**

- "Changing K₁ leaves every closed-loop pole where it was" — false. K₁ is in the reference path, so
  its own pole genuinely joins the r→y response. What is true is that K₁ cannot move the roots of
  1 + L, which is what the claim now measures.
- Ch.6 at K₂ = 1 has |L(0)| = 1 exactly, so the loop *starts* on the 0 dB line and never crosses
  it: no gain crossover, and therefore no phase margin and no delay margin. Not a bug — the
  quantities are defined at a crossing that is not happening. The lesson now uses K₂ = 2 and makes
  the degenerate case an exercise.

### Phase 8 — Packaging ✅ **DONE**

`git init`, `.gitignore`, `.gitattributes`, `pyproject.toml`, README, and the repository published
at [github.com/leo-01000111/FauxMatlab](https://github.com/leo-01000111/FauxMatlab). Then:

1. ✅ **`--check`**, a headless self-test (`fakematlab/selftest.py`). Its payload is not smoke
   checks: it runs the course lessons' analytic claims, so a pass means the numbers agree with the
   theory rather than merely that nothing raised. Exit code is the failure count, so
   `app.py --check && deploy` does what it looks like it does.
2. ✅ **CI** — ruff, pytest on Linux *and* Windows, then `app.py --check`. The Linux job installs
   the Qt runtime libraries PySide6 links against even offscreen.
3. ✅ **PyInstaller** one-*folder* build (`packaging/fauxmatlab.spec`). One-file unpacks the whole
   Qt runtime on every launch; one-folder starts immediately. It builds two entry points over one
   bundle — `FauxMatlab.exe` windowed and `FauxMatlab-check.exe` console, because a windowed
   executable on Windows has no stdout and `--check` there would set an exit code and print
   nothing.
4. ✅ **ruff clean**, from 301 violations to zero. 225 were auto-fixed, ~20 were real dead code,
   and the rest are configured off *with a stated reason each* rather than silently.

**Acceptance.** `ruff check .` passes. 589 tests. `app.py --check` reports 41/41 in 5.5 s, and
the *frozen* build passes its own self-test.

**What the linter caught that the tests did not.** A blanket rename of unused loop variables hit
three loops in `solver.py` that *do* use the variable — `F821 undefined-name`, in code paths the
suite does not reach. That is the argument for the linter in one example.

**What the frozen build caught that nothing else did.** Three defects in a row, none visible from
the source tree:

1. `collect_submodules("control")` reaches `control.tests`, which imports pytest, whose plugin
   discovery then reaches whatever else is installed — torch, jax, OpenCV, transformers. **1.5 GB**
   from a 340 MB application. Dropped; the static scan already follows what this code imports.
2. Excluding matplotlib and python-control's plotting modules looked free — this app draws with
   pyqtgraph and never calls them. But `control/__init__.py` imports `ctrlplot`, `freqplot`,
   `timeplot` and five more unconditionally, so `import control` became `ModuleNotFoundError`.
   matplotlib is a hard runtime dependency of python-control 0.10. Same for `PySide6.QtTest`,
   which pyqtgraph imports — caught by a test before it reached a build.
3. A Windows console is cp1252 and the report is full of ζ, ω and −, so printing raised
   `UnicodeEncodeError` *inside* a check's `try` block: a display problem recorded as a
   correctness failure, which is a lie about the build. The development shell is UTF-8, so the
   source tree never hit it.
4. **The windowed build would not launch at all.** A GUI executable on Windows has *no standard
   streams* — `sys.stdout` and `sys.stderr` are `None` — and numpy's `f2py/cfuncs.py` does
   `errmess = sys.stderr.write` at import time, reached through `scipy.linalg`. So the launch died
   with `AttributeError: 'NoneType' object has no attribute 'write'` before the window appeared.
   Fixed with a runtime hook (`packaging/rthook_stdio.py`) that supplies discard streams for every
   package at once rather than patching them one by one.

   **The verification hole matters more than the bug.** The self-test passed, and CI was written to
   run it — against `FauxMatlab-check.exe`, the *console* build, which does have streams. The
   entry point people actually double-click was the one never tested. CI now self-tests both, and
   a test asserts that it does.

**Deliberately deferred, not overlooked.** `B905` (`zip(..., strict=True)`) is switched off with a
note. Fifteen call sites, mostly in the solver, where a length mismatch between ports and widths
would be a genuine bug — but turning it on blind converts working code into raising code, so it
wants a per-site audit rather than a flag.

---

## Part 5 — Sequencing, risk, and what I'd cut

**Order:** ~~1 → 2 → 4 → 3 → 5 → 6 → 7 → 8~~ — **all eight phases complete.** Phase 4 (Simulink) before Phase 3 (modern control),
because Phase 4 depends on the Phase-1 graph while it's fresh, and because Phase 3's tabs are
additive and low-risk. Total ≈ **28–40 focused days**. Phases 1+2 alone (≈ 1 week) turn a tool
that quietly prints wrong numbers into one you can trust.

| Risk | Mitigation |
|---|---|
| Symbolic TF derivation too slow on big graphs (D1) | Cache per (model-hash, port-pair); fall back to the numeric solver above ~20 blocks |
| Algebraic loops in user-drawn models | Detect at compile, name the cycle on the canvas, offer "insert unit delay / memory block" |
| Stiff models hang the UI | Run the solver on a `QThread` with a progress bar and a cancel button |
| Scope with 1e6 points is unusable | Downsample for display, keep full data for export |
| Phase 4 sprawls | Ship the block table above and stop. Lookup tables, buses and Stateflow are not in scope |

**What I'd cut if time runs short:** Phase 6 apps (nice, not load-bearing), the Python Function
block, `balred`/Hankel, PRBS and chirp sources, and the script editor — keep the console.

**What I would not cut:** Phase 1. Every hour spent on features before the 6 wrong transfer
functions and the truncated Bode plots are fixed is an hour spent making a confident liar.
