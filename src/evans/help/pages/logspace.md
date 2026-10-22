# logspace

Row vector of points evenly spaced in decades, for frequency grids.

## Syntax

    w = logspace(a, b)
    w = logspace(a, b, n)

## Description

`logspace(a, b, n)` returns `n` points from 10 to the power `a` up to 10 to the power `b`, with the same ratio between neighbours. The arguments are exponents, so `logspace(-1, 2, 200)` runs from 0.1 to 100 rad/s. Without `n` you get 50 points.

Pass the result as the frequency vector to [bode](bode), [nyquist](nyquist) or [freqresp](freqresp) to choose exactly where the response is evaluated.

`logspace(a, pi)` is a special case, as in MATLAB: the points end at pi itself, not at 10 to the power pi, which is the frequency range of a discrete system in rad/sample.

## Example

```matlab
w = logspace(-1, 2, 4)
```

```matlab
G = tf(10, [1 2 10]);
w = logspace(-1, 2, 200);
[mag, phase] = bode(G, w);
fprintf('Peak gain %.2f\n', max(mag))
```

## See also

[linspace](linspace) · [bode](bode) · [nyquist](nyquist) · [freqresp](freqresp) · [semilogx](semilogx)
