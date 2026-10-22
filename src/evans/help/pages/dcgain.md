# dcgain

Steady-state gain of a system: the final value of its step response, when it has one.

## Syntax

    dcgain(sys)
    k = dcgain(sys)

## Description

`k = dcgain(sys)` returns `G(0)` for a continuous system, the ratio of the output to a constant input once everything has settled. The system can be a `tf`, `zpk` or `ss` model; for a state-space model the gain is `D - C*inv(A)*B`.

A system with a pole at the origin (an integrator) has an infinite DC gain and returns `Inf` (or `-Inf` for a negative gain). A zero at the origin gives 0, and a zero cancelling a pole at the origin gives `NaN`.

For a discrete state-space model the result is `G(1)`, the correct steady-state gain. For a discrete transfer function Evans currently evaluates at `z = 0` instead, which is not the steady-state gain; use `evalfr(Gd, 1)` or convert with `ss` first.

The value only predicts the final value of the step response when the system is stable; check that with [isstable](isstable) or [pole](pole) first. For a model with several inputs or outputs, Evans returns the gain from the first input to the first output as a scalar, where MATLAB returns the whole matrix.

## Example

```matlab
G = tf(4, [1 2 4]);
dcgain(G)
T = feedback(tf(10, [1 1]), 1);
dcgain(T)
```

## See also

[step](step) · [stepinfo](stepinfo) · [errconst](errconst) · [evalfr](evalfr) · [bandwidth](bandwidth)
