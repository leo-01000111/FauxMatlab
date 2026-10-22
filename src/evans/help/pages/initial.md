# initial

Free response of a state-space model: how its output evolves from an initial state x0 with the input held at zero.

## Syntax

    initial(sys, x0)
    initial(sys, x0, Tfinal)
    initial(sys, x0, t)
    y = initial(sys, x0, ...)
    [y, t] = initial(sys, x0, ...)

## Description

`initial(sys, x0)` plots the output of `sys` for `u = 0`, starting from the state `x0`, a vector with one entry per state. Give `sys` as an `ss` model, so that you know which state each entry of `x0` sets. A `tf` model is converted to a state-space realisation first, and its states are then those of that realisation.

Without a time argument the simulation runs from 0 to 10 seconds, whatever the system. This differs from [step](step), which sizes the span from the poles, so pass a span for slow or fast systems. `initial(sys, x0, Tfinal)` simulates from 0 to `Tfinal` seconds and `initial(sys, x0, t)` uses the evenly spaced time vector `t`.

With output arguments nothing is drawn. `y` is the output as a column vector and `t` the matching time column. For a model with several outputs the plot shows one curve per output, but the returned `y` is not split per output, so ask for outputs only from single-output models.

For a discrete-time model, pass a time vector whose step is the sample time.

## Example

```matlab
A = [0 1; -4 -1];
sys = ss(A, [0; 1], [1 0], 0);
initial(sys, [1; 0], 12)
[y, t] = initial(sys, [1; 0], 12);
fprintf('Output after 12 s: %.4f\n', y(end))
```

## See also

[lsim](lsim) · [step](step) · [ss](ss) · [damp](damp) · [timeoptions](timeoptions)
