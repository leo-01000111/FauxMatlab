# FakeMatlab — Classical Control workbench (spec)

Native desktop tool replacing MATLAB/Simulink for the CLACO "Classical Control" course
(`COURSE MATERIAL/CORO_CLACO_classical_approach_2026-2027_1slidepp.pdf`, 254 slides, ch1–8).
The old inspiration script is `Inspiration/Transfer Function Cheating 7 - multi K graph.py`.

## Stack (all already installed, Python 3.12)
- `python-control` 0.10.1, `scipy` 1.14, `numpy` 2.0, `sympy` 1.14 (symbolic display + Routh table)
- UI: **PySide6** 6.10 + **pyqtgraph** 0.14 (interactive plots: zoom, hover, crosshair, annotations)
- Tests: `pytest`
- Run: `python app.py`

## Architecture (fixed diagram, not free-form)
The block diagram is the course's "chosen architecture" (ch5 slide 16/24):

```
                                  di            do
                                   |             |
 r --> [K1] --> (+)--> e --> [K2] --> u --(+)--> [G] --(+)--> y
                 ^(-)                                          |
                 |                        n --(+)--------------+
                 +---------------------------------------------+
```
Blocks: K1 (feedforward, default 1), K2 (feedback controller), G (plant). Optional sensor H in
the return path (default 1). Signals: inputs r, di, do, n; outputs y, u, e.
Notation from the course: L = K2·G (loop), S = 1/(1+L), T = L/(1+L).
All 8 closed-loop TFs (r,di,do,n → y,u) are derived from these; user picks any (input, output)
pair as the "signal tap" to analyse. Also analyse open-loop G, L, S, T directly.

## Layout
Left panel: SVG-like block diagram drawn with Qt (QGraphicsScene). Click a block → editor panel
below; click a signal label → sets analysis tap. Right panel: tabs.

Block editor — TF input modes: polynomial coefficients; expression string
`(s+1)/(s^2+0.5s+1)` (sympy parse); ZPK; 1st-order preset (K, tau); 2nd-order preset (K, zeta, wn);
pure delay approximation (Pade). Always show the factored/normalised form.

### Tabs
1. **System** — factored TF, poles/zeros table (Re, Im, zeta, wn, tau), stability verdict,
   minimum-phase check, DC gain, system type.
2. **Time** — step / impulse / ramp for the chosen tap, amplitude & initial value; metrics
   (Mp %, tp, ts at ±2% and ±5%, tr 10–90% and 0–100%, undershoot Mu, y_inf) with markers and
   the ±delta band drawn on the plot. **Parameter sweep overlay**: pick any block parameter
   (e.g. Kp) and a list/range of values → overlaid curves with legend (generalises the old
   "multi-K graph").
3. **Frequency** — Bode (mag dB + phase) with GM, PM, w_c (gain crossover), w_180, -3 dB
   bandwidth, resonant peak Mr marked. Nyquist with -1 point, unit circle, M-circles, modulus
   margin circle. Nichols. Overlay L, S, T. Delay margin printed.
4. **Stability** — Routh table (sympy; with a symbolic K → range of stabilising K), closed-loop
   pole map, Nyquist encirclement count (P, N, Z), root locus vs K.
5. **Performance** — system type, steady-state error for step / ramp / parabola, static error
   constants Kp Kv Ka, disturbance and noise rejection (|S|, |T|), bandwidth, trade-off notes.
6. **Design** — controller structure picker for K2: P / PI / PD / PID (ideal & filtered
   derivative) / lead / lag / lead-lag / custom TF. Live sliders for every parameter → all open
   plots refresh. Ziegler–Nichols buttons (step-response method and ultimate-gain method),
   pinned "snapshots" for before/after comparison.

Extras: save/load session (JSON), export plot PNG, copy MATLAB-style text report, a menu of
presets (1st order, 2nd order under/critically/over-damped, integrator + lag, unstable plant,
non-minimum-phase zero, satellite double integrator from ch2).

## Code structure
```
app.py                 # entry point
fakematlab/
  core/                # pure engine, no Qt — unit tested
    tf.py              # parsing/formatting/factoring, presets
    architecture.py    # blocks + closed-loop TF derivation
    timeresp.py        # step/impulse/ramp + metrics
    freqresp.py        # bode/nyquist/nichols + margins, Mr, bandwidth
    stability.py       # routh (sympy), nyquist count, root locus
    performance.py     # system type, error constants, ess
    tuning.py          # PID/lead/lag builders, Ziegler–Nichols
  ui/
    mainwindow.py, diagram.py, block_editor.py, tabs/*.py, plots.py (pyqtgraph helpers)
tests/                 # pytest for core
```

## Phases
1. Scaffold + `core/` + tests
2. Main window, diagram, block editors
3. System / Time / Frequency tabs
4. Stability / Performance / Design tabs, sweeps
5. Presets, save/load, export, README
