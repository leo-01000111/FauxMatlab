# evalfr

Evaluate a model's transfer function at one complex value of s (or z).

## Syntax

    H = evalfr(sys, x)

## Description

`H = evalfr(sys, x)` returns the transfer function of `sys` evaluated at the complex number `x`, as a complex scalar. For a continuous-time model `x` is a value of s: `evalfr(G, 0)` is the DC gain and `evalfr(G, 3i)` is the frequency response at 3 rad/s. For a discrete-time model `x` is a value of z, so the frequency response at `w` rad/s is `evalfr(G, exp(1i*w*Ts))`.

`sys` can be a `tf`, `zpk` or `ss` model. `x` is a single value; for a vector of frequencies use [freqresp](freqresp). The result is always complex, so a real answer displays as `1 + 0i`. `abs(H)` is the gain and `angle(H)` the phase in radians.

## Example

```matlab
G = tf(10, [1 2 10]);
H = evalfr(G, 3i);
fprintf('|G(3j)| = %.3f, phase = %.1f deg\n', abs(H), angle(H)*180/pi)
```

## See also

[freqresp](freqresp) · [dcgain](dcgain) · [bode](bode) · [tf](tf)
