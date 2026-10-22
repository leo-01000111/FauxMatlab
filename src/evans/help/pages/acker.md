# acker

State-feedback gain `K` by Ackermann's formula, for a single-input system.

## Syntax

    K = acker(A, B, p)

## Description

`K = acker(A, B, p)` returns the row vector `K` for the control law `u = -K*x` that puts the eigenvalues of `A - B*K` at the entries of `p`. The formula is `K = [0 ... 0 1] * inv(ctrb(A, B)) * phi(A)`, where `phi` is the desired characteristic polynomial built from `p`.

`B` must have a single column; with more inputs `acker` stops with an error and you use [place](place). `p` needs one entry per state, complex entries in conjugate pairs, and the pair `(A, B)` must be controllable. Repeated poles are allowed, which [place](place) refuses on a single-input system.

Because the formula inverts the controllability matrix, it loses accuracy as the order grows. Compare `eig(A - B*K)` with `p` on anything above third or fourth order, or use [place](place).

## Example

```matlab
A = [0 1; -2 -3];
B = [0; 1];
K = acker(A, B, [-4 -4])
eig(A - B*K)
```

## See also

[place](place) · [ctrb](ctrb) · [lqr](lqr) · [isctrb](isctrb)
