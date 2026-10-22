# step

Step response of a dynamic system: how its output moves after the input jumps from 0 to 1 at t = 0.

## Syntax

    step(sys)
    step(sys, Tfinal)
    step(sys, t)
    step(sys1, sys2, ...)
    step(sys, opts)
    y = step(sys)
    [y, t] = step(sys, ...)

## Description

`step(sys)` plots the unit step response of `sys`, a `tf` or `zpk` model. The time span is picked from the slowest pole, long enough to show the response settle. A state-space model fails here at the moment; convert it first with `step(tf(sys))`.

`step(sys, Tfinal)` simulates from 0 to `Tfinal` seconds. `step(sys, t)` uses the time vector `t` as given, which should start at 0 and be evenly spaced. A discrete model needs this form, with the spacing of `t` equal to its sample time: `step(Gd, 0:Ts:5)`.

`step(sys1, sys2, ...)` draws every system on one set of axes, over a shared time span long enough for the slowest of them. Each curve is labelled with its variable name. A line style string such as `'r--'` is accepted and ignored.

`step(sys, opts)` applies plot options made with [timeoptions](timeoptions). Evans uses the `Title`, `XLim` and `YLim` fields; the label and grid fields are accepted and have no effect.

With output arguments nothing is drawn. `y` is the response as a column vector and `t` the matching time column, so `plot(t, y)` draws the same curve. Ask for outputs one system at a time.

For the numbers that describe the curve (rise time, overshoot, settling time) use [stepinfo](stepinfo).

## Example

```matlab
G = tf(4, [1 2 4]);
step(G)
[y, t] = step(G, 5);
fprintf('Final value: %.3f\n', y(end))
```

## See also

[impulse](impulse) · [stepinfo](stepinfo) · [lsim](lsim) · [initial](initial) · [timeoptions](timeoptions)
