# zpkdata

Zeros, poles and gain of a single-input, single-output model.

## Syntax

    [z, p, k] = zpkdata(sys)
    [z, p, k] = zpkdata(sys, 'v')
    z = zpkdata(sys, ...)

## Description

`[z, p, k] = zpkdata(sys)` returns the zeros and poles as 1-by-1 cell arrays, as MATLAB does, and the gain `k` as a number. `z{1}` and `p{1}` hold the vectors. `sys` can be a `tf`, `zpk` or `ss` model.

`[z, p, k] = zpkdata(sys, 'v')` returns `z` and `p` directly as column vectors. A model with no finite zeros gives `z = []`.

The gain is the ratio of the leading coefficients of numerator and denominator, so `sys` equals `k*(s - z1)(s - z2).../((s - p1)(s - p2)...)`. For `tf([2 6], [1 3 2])` that is `k = 2`, a zero at -3 and poles at -1 and -2. It is not the DC gain; use [dcgain](dcgain) for that.

Zeros and poles are always returned as complex numbers, so a real pole displays as `-2 + 0i`. With one output, or no output, `zpkdata` gives the zeros only. Evans returns three outputs at most: MATLAB's fourth output, the sample time, is not supported, and neither are MIMO models.

## Example

```matlab
G = tf([2 6], [1 3 2]);
[z, p, k] = zpkdata(G, 'v')
```

## See also

[zpk](zpk) · [tfdata](tfdata) · [pole](pole) · [zero](zero) · [dcgain](dcgain)
