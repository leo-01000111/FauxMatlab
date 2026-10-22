# place

State-feedback gain `K` that puts the closed-loop eigenvalues of `A - B*K` at chosen locations.

## Syntax

    K = place(A, B, p)

## Description

`K = place(A, B, p)` returns the gain matrix for the control law `u = -K*x`, so that the eigenvalues of `A - B*K` are the entries of `p`. `A` is n by n, `B` is n by m and `K` comes back m by n.

`p` must be a row vector with exactly n entries, one per state. Complex entries must come in conjugate pairs, because a real gain can only produce conjugate pairs. A value may be repeated at most as many times as `B` has independent columns: on a single-input system every pole must be distinct, and for repeated poles you use [acker](acker).

The pair `(A, B)` must be controllable; otherwise `place` stops with an error that lists the modes it cannot move. Check beforehand with [isctrb](isctrb).

Among the many gains that give the same eigenvalues on a multi-input system, `place` uses the Kautsky-Nichols method, which picks well-conditioned closed-loop eigenvectors. The placement is then less sensitive to model error than Ackermann's formula. Evans has no second output with the placement precision, and the poles cannot be given as a column vector.

## Example

```matlab
A = [0 1; -2 -3];
B = [0; 1];
K = place(A, B, [-4 -5])
eig(A - B*K)
```

## See also

[acker](acker) · [lqr](lqr) · [estim](estim) · [isctrb](isctrb) · [ctrb](ctrb)
