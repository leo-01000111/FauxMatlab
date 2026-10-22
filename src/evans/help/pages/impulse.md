# impulse

Impulse response of a dynamic system: its output after a unit impulse at t = 0, starting from rest.

## Syntax

    impulse(sys)
    impulse(sys, Tfinal)
    impulse(sys, t)
    impulse(sys1, sys2, ...)
    impulse(sys, opts)
    y = impulse(sys)
    [y, t] = impulse(sys, ...)

## Description

`impulse(sys)` plots the unit impulse response of `sys`, which can be a `tf`, `zpk` or `ss` model. The time span is picked from the slowest pole, long enough to show the response decay. For a transfer function the impulse response is the inverse Laplace transform of `G(s)`, so this is also the quickest way to look at it.

`impulse(sys, Tfinal)` simulates from 0 to `Tfinal` seconds. `impulse(sys, t)` uses the time vector `t` as given, which should start at 0 and be evenly spaced.

`impulse(sys1, sys2, ...)` draws every system on one set of axes, over a shared time span long enough for the slowest of them. Each curve is labelled with the name of its variable.

`impulse(sys, opts)` applies plot options made with [timeoptions](timeoptions). Evans uses the title and the axis limits (`XLim`, `YLim`) from them.

With output arguments nothing is drawn. `y` is the response as a column vector and `t` the matching time column. Ask for outputs one system at a time.

For a discrete-time model, pass a time vector whose step is the sample time, for example `impulse(Gd, 0:0.1:5)` when `Gd` has `Ts = 0.1`. Evans does not yet pick the span for a discrete model on its own.

## Example

```matlab
G = tf(4, [1 2 4]);
impulse(G)
[y, t] = impulse(G, 6);
[ypk, k] = max(y);
fprintf('Peak %.3f at t = %.2f s\n', ypk, t(k))
```

## See also

[step](step) · [lsim](lsim) · [initial](initial) · [ramp](ramp) · [timeoptions](timeoptions)
