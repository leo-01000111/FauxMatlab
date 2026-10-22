# ramp

Ramp response of a dynamic system: its output when the input rises as u(t) = t from rest.

## Syntax

    ramp(sys)
    ramp(sys, Tfinal)
    ramp(sys, t)
    ramp(sys, t, slope)
    [t, y] = ramp(sys, ...)

## Description

MATLAB has no `ramp` command; Evans adds one because the ramp input comes up constantly in steady-state error work. Evans computes it as the step response of `sys/s`.

`ramp(sys)` plots the response of `sys` (a `tf`, `zpk` or `ss` model) to the unit ramp, with the ramp itself drawn dashed so the tracking error is visible as the gap between the two. The time span is picked from the slowest pole.

`ramp(sys, Tfinal)` simulates from 0 to `Tfinal` seconds and `ramp(sys, t)` uses the time vector `t`. `ramp(sys, t, slope)` scales the input to `u(t) = slope·t`; `t` can be a final time here too.

The outputs come in the order `[t, y]`, time first, which is the reverse of [step](step) and [impulse](impulse). Both are row vectors. With output arguments the curve is still drawn. Called without a semicolon, `ramp(sys)` also prints a one-line summary of the result.

`ramp` works on continuous-time models only.

For a unity-feedback loop the steady-state ramp error is `1/Kv`; [errconst](errconst) gives `Kv` directly.

## Example

```matlab
L = tf(5, [1 3 0]);
T = feedback(L, 1);
[t, y] = ramp(T, 10);
fprintf('Ramp error at t = 10 s: %.3f\n', t(end) - y(end))
```

## See also

[step](step) · [lsim](lsim) · [errconst](errconst) · [feedback](feedback) · [impulse](impulse)
