# sim

Simulate a block diagram model (the Simulation tab's canvas) from t = 0 to a final time, and return every logged signal.

## Syntax

    out = sim(model)
    out = sim(model, Tfinal)

## Description

`out = sim(model)` runs the model for 10 seconds. `sim(model, Tfinal)` runs it from 0 to `Tfinal` seconds. The model is a block diagram of the kind you draw on the Simulation tab: sources, sums, gains, transfer functions, PID blocks, saturations, discrete blocks, and the wires between them. Continuous and discrete blocks can sit in the same model, so a sampled controller can drive a continuous plant.

At the app's console the model on the Simulation canvas is already in the workspace as `model`. It is the live model, so `sim(model, 20)` runs exactly what the canvas shows, including edits made a moment ago. Type `out = sim(model, 20);` with the semicolon: the result holds every signal at every time step, and displaying it fills the console.

The result `out` has these fields and methods:

- `out.t`: the time points, a vector from 0 to `Tfinal`.
- `out.trace('G')`: the output of block `G` over time, one value per time point. A block with several outputs is named with its port, as in `out.trace('K2.out')`.
- `out.signals`: every logged signal, keyed by `'block.port'`.
- `out.states`: the continuous states, one row per time point.
- `out.warnings`: anything the solver or compiler reported, for example an algebraic loop.

`plot(out.t, out.trace('G'))` draws the output of `G`.

Evans does not run a model from a file name (`sim('mymodel')`), and it does not accept MATLAB's name-value pairs such as `'StopTime'`. From a Python line you can choose the solver with a keyword, for example `sim(m, 5, solver='ode4')`: the variable-step names `ode45`, `ode23`, `ode15s` and the fixed-step `ode1` to `ode5` are accepted.

A fresh console (or a script) has no `model`, and there is no MATLAB function that makes one. You build it with a Python import, as in the example below: `SimModel` holds the diagram, `add(type, name, ...)` places a block with its parameters, and `connect('from', 'to')` draws a wire, naming a port as `'block.port'` when the block has more than one. Run as one block, the example is read entirely as Python because it starts with an import, so it prints with `print` rather than `fprintf`. Typed line by line, only the import needs Python; the other lines read as MATLAB too. See [python](python) for how the console tells the two languages apart.

To get a transfer function out of the model instead of a time response, use [linearize](linearize).

## Example

```matlab
from evans.sim import SimModel
m = SimModel('demo')
m.add('Step', 'r', step_time=0)
m.add('TransferFcn', 'G', num='4', den='1, 2, 4')
m.connect('r', 'G')
out = sim(m, 8)
print(f"y(8) = {out.trace('G')[-1]:.4f}")
```

## See also

[linearize](linearize) · [step](step) · [lsim](lsim) · [python](python)
