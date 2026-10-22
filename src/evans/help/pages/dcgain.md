# dcgain

Steady-state gain of a system: the final value of its step response, when it has one.

## Syntax

    dcgain(sys)
    k = dcgain(sys)

## Description

`k = dcgain(sys)` returns `G(0)` for a continuous system and `G(1)` for a discrete one, the ratio of the output to a constant input once everything has settled. The system can be a `tf`, `zpk` or `ss` model; for a state-space model the gain is `D - C*inv(A)*B`.

A system with a pole at the origin (an integrator) has an infinite DC gain and returns `Inf` (or `-Inf` for a negative gain). A zero at the origin gives 0. A zero that cancels a pole at the origin is divided out first, so `s*H` with `H = 1/(s*(s+1))` gives 1, the gain of `1/(s+1)`, even though `*` keeps both factors. For a discrete model the same goes for factors at `z = 1`.

The value only predicts the final value of the step response when the system is stable; check that with [isstable](isstable) or [pole](pole) first. For a model with several inputs or outputs, `k` is the whole matrix of gains, one row per output and one column per input, as in MATLAB.

## Example

```matlab
G = tf(4, [1 2 4]);
dcgain(G)
T = feedback(tf(10, [1 1]), 1);
dcgain(T)
```

## See also

[step](step) · [stepinfo](stepinfo) · [errconst](errconst) · [evalfr](evalfr) · [bandwidth](bandwidth)
