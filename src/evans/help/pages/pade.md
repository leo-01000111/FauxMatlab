# pade

Padé approximation of a time delay `e^(-sT)` as a rational transfer function.

## Syntax

    D = pade(T, n)
    D = pade(T)
    [num, den] = pade(T, n)

## Description

`D = pade(T, n)` returns an order `n` transfer function whose frequency response approximates a pure delay of `T` seconds. Its gain is 1 at every frequency and its phase follows the delay's `-w*T` up to roughly `w*T = n`; above that the phase stops tracking. The approximation has `n` zeros in the right half-plane, so a step response through it starts by moving the wrong way.

`D = pade(T)` uses `n = 1`. `pade(0, n)` returns the unit gain `1`.

`[num, den] = pade(T, n)` returns the numerator and denominator coefficients as row vectors instead of a model.

To add a delay to a plant, multiply by the approximation: `G*pade(T, n)` or `series(pade(T, n), G)`. MATLAB's `pade` called with no output plots the approximation; Evans displays the transfer function instead.

## Example

```matlab
G = tf(1, [1 1]);
D = pade(0.5, 2)
step(series(D, G))
```

## See also

[tf](tf) · [series](series) · [margin](margin) · [allmargin](allmargin) · [bode](bode)
