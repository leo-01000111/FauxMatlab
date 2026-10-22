# lqr

Linear-quadratic regulator: the state-feedback gain that minimises a quadratic cost on the state and the input.

## Syntax

    K = lqr(sys, Q, R)
    K = lqr(sys)
    [K, S, e] = lqr(sys, Q, R)

## Description

`K = lqr(sys, Q, R)` returns the gain for `u = -K*x` that minimises the cost `J = ∫ (x'*Q*x + u'*R*u) dt` for the state-space model `sys`. `Q` weights the states and `R` the inputs: raising `Q` relative to `R` gives a faster, more aggressive loop that uses more control effort.

`Q` must be positive semi-definite and `R` positive definite. Each can be a full square matrix, a scalar (which multiplies the identity) or a vector of diagonal entries, so `lqr(sys, [10 1], 0.1)` is the same as `lqr(sys, diag([10 1]), 0.1)`. `lqr(sys)` uses identity matrices for both.

`[K, S, e] = lqr(sys, Q, R)` also returns `S`, the solution of the algebraic Riccati equation (`x0'*S*x0` is the optimal cost from the initial state `x0`), and `e`, the closed-loop eigenvalues of `A - B*K` as a row vector.

The model must be stabilisable: unstable modes that the input cannot reach make `lqr` stop with an error. For a discrete-time model the discrete Riccati equation is solved, and `K` is the discrete-time gain.

Evans takes a model, not matrices: the MATLAB form `lqr(A, B, Q, R)` is not supported, so write `lqr(ss(A, B, eye(n), 0), Q, R)`. The cross term `N` is not supported either. Assign at least `K`, since with no output the three results print together unformatted.

## Example

```matlab
sys = ss([0 1; 0 0], [0; 1], [1 0], 0);
[K, S, e] = lqr(sys, diag([10 1]), 1)
```

## See also

[lqi](lqi) · [place](place) · [lqe](lqe) · [isctrb](isctrb) · [ss](ss)
