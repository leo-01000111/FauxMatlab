# tfdata

Numerator and denominator coefficients of a single-input, single-output model, in descending powers of s (or z).

## Syntax

    [num, den] = tfdata(sys)
    [num, den] = tfdata(sys, 'v')
    num = tfdata(sys, ...)

## Description

`[num, den] = tfdata(sys)` returns the coefficients of `sys` as 1-by-1 cell arrays, as MATLAB does: `num{1}` and `den{1}` are the row vectors. `sys` can be a `tf`, `zpk` or `ss` model; a `zpk` or `ss` model is converted to a transfer function first.

`[num, den] = tfdata(sys, 'v')` returns the two row vectors directly, which is the form you usually want for a SISO model.

The numerator is padded with leading zeros to the length of the denominator, so `num(k)` and `den(k)` multiply the same power of s. For `tf([1 3], [1 2 5])` the numerator comes back as `[0 1 3]`.

With one output, or with no output, `tfdata` gives the numerator only. A model converted from state space can carry round-off such as `8.9e-16` where a coefficient should be zero. Evans returns two outputs at most: MATLAB's third output, the sample time, is not supported, and neither are MIMO models.

## Example

```matlab
G = zpk(-3, [-1 -2], 2);
[num, den] = tfdata(G, 'v')
roots(den)
```

## See also

[tf](tf) · [zpkdata](zpkdata) · [ssdata](ssdata) · [pole](pole) · [zero](zero)
