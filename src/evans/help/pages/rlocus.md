# rlocus

Root locus of a single-input single-output system: the paths the closed-loop poles follow as a feedback gain K rises from 0.

## Syntax

    rlocus(sys)
    rlocus(sys, k)
    r = rlocus(sys, ...)
    [r, k] = rlocus(sys, ...)

## Description

`rlocus(sys)` plots the closed-loop poles of the loop `sys` under negative feedback `u = -K y`, for `K` from 0 upwards, one curve per branch. Each branch starts at an open-loop pole and ends at a zero or heads to infinity. `sys` is the open-loop transfer function, as a `tf`, `zpk` or `ss` model. The gain range is chosen automatically. If the locus crosses the imaginary axis, the title gives the gain and the frequency at which it does, which is the limit of stability for that loop.

`rlocus(sys, k)` evaluates the locus at exactly the gains in `k`, a vector or a single gain. Only the first system is plotted if you pass several.

With output arguments nothing is drawn. `r` is a matrix of closed-loop poles with one row per branch and one column per gain, and `k` the row vector of those gains, so `r(:, j)` are the poles for gain `k(j)`.

## Example

```matlab
L = tf(1, [1 3 2 0]);
rlocus(L)
[r, k] = rlocus(L, 0:0.5:10);
disp(r(:, end))
```

## See also

[pzmap](pzmap) · [feedback](feedback) · [margin](margin) · [routh](routh) · [pole](pole)
