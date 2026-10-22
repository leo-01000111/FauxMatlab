# damp

Natural frequency, damping ratio and time constant of each pole of a system.

## Syntax

    damp(sys)
    wn = damp(sys)
    [wn, zeta] = damp(sys)
    [wn, zeta, p] = damp(sys)

## Description

`damp(sys)` with no output prints a table with one row per pole: the pole itself, its damping ratio, its natural frequency in rad/s and its time constant in seconds. The system can be a `tf`, `zpk` or `ss` model.

For a pole `p`, the natural frequency is `abs(p)`, the damping ratio is `-real(p)/abs(p)` and the time constant is `1/abs(real(p))`. A pole at the origin is given damping 1 and an infinite time constant. A negative damping ratio means the pole is in the right half-plane.

With outputs nothing is printed. `wn` and `zeta` are column vectors, and `p` is the column of poles they belong to, in the same order.

Evans applies these continuous-time formulas to a discrete system's poles as they are, in the z-plane. MATLAB first maps each discrete pole to the s-plane, so for a discrete model the two disagree; convert with [d2c](d2c) before calling `damp` if you need MATLAB's numbers.

## Example

```matlab
G = tf(25, [1 4 25]);
damp(G)
[wn, zeta] = damp(G);
fprintf('wn = %.2f rad/s, zeta = %.2f\n', wn(1), zeta(1))
```

## See also

[pole](pole) · [pzmap](pzmap) · [stepinfo](stepinfo) · [rlocus](rlocus) · [d2c](d2c)
