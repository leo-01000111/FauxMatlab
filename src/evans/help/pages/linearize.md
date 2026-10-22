# linearize

Linearise a block diagram model between an input port and an output signal, and return the result as a transfer function.

## Syntax

    T = linearize(model, input, output)

## Description

`T = linearize(model, input, output)` perturbs the signal arriving at `input`, measures how `output` and the model's states respond, and returns the linear model from one to the other as a transfer function. Ports are named `'block.port'`. The port may be left out when the block has only one of that kind, so `'G'` means the input of `G` when used as `input` and its output when used as `output`.

The input is a block's *input* port. The wire that normally feeds it is cut for the linearisation and replaced by the perturbation, so the choice of port decides which loop you get. In a unity-feedback loop with a sum `e` feeding a plant `G`:

- `linearize(model, 'e.in1', 'G')` perturbs the reference input of the sum and gives the closed-loop transfer function.
- `linearize(model, 'G', 'G')` cuts the wire into `G` and gives the plant alone, open loop.

The derivatives are taken by central differences about the model's initial state. Nonlinear blocks are linearised at that point: a saturation inside its limits becomes a gain of 1, one sitting on a limit a gain of 0. Discrete blocks are held fixed, so the result describes the continuous part of the model only. A model with an algebraic loop is refused with an error naming the loop.

The transfer function is the full state-space result converted with `ss2tf`, without cancellation. States that the chosen path does not see (a controller's integrator when you linearise the plant alone, for example) stay in as pole-zero pairs that cancel, and coefficients that should be zero can come out as round-off of order 1e-14. Pass the result through [minreal](minreal) to remove them.

At the app's console the model on the Simulation canvas is in the workspace as `model`, so `T = linearize(model, 'e.in1', 'G')` is all you type. Evans takes the two ports as strings; MATLAB's `linio` objects, operating-point arguments and a second output are not supported. A fresh console has no `model`, so the example builds one with a Python import, as described on the [sim](sim) page; run as one block it is read entirely as Python, which is why it prints with `print` (see [python](python)).

## Example

```matlab
from evans.sim import SimModel
m = SimModel('loop')
m.add('Sum', 'e', signs='+-')
m.add('TransferFcn', 'G', num='4', den='1, 2, 0')
m.connect('e', 'G'); m.connect('G', 'e.in2')
T = linearize(m, 'e.in1', 'G')
print('closed-loop poles:', pole(T), ' dc gain:', dcgain(T))
```

## See also

[sim](sim) · [minreal](minreal) · [feedback](feedback) · [ss2tf](ss2tf) · [python](python)
