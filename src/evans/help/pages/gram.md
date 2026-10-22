# gram

Controllability or observability Gramian of a stable state-space model.

## Syntax

    Wc = gram(sys, 'c')
    Wo = gram(sys, 'o')
    Wc = gram(sys)

## Description

`Wc = gram(sys, 'c')` returns the controllability Gramian, the solution of the Lyapunov equation `A*Wc + Wc*A' + B*B' = 0`. It measures how much input energy it takes to reach each direction of the state space: directions along eigenvectors with small eigenvalues of `Wc` are hard to reach.

`Wo = gram(sys, 'o')` returns the observability Gramian, the solution of `A'*Wo + Wo*A + C'*C = 0`. Directions with small eigenvalues of `Wo` produce little output energy and are hard to see from the measurement.

`gram(sys)` with no type returns the controllability Gramian. Any type other than `'c'` or `'o'` is an error.

`sys` must be a state-space model made with [ss](ss); convert a transfer function with `ss(G)`. Every eigenvalue of `A` must have a negative real part, otherwise the integrals that define the Gramians do not converge and `gram` stops with an error. For a discrete-time model the discrete Lyapunov equation is solved instead.

The result is symmetric in theory; off-diagonal entries of order `1e-17` are round-off. The two Gramians together give the Hankel singular values of [hsvd](hsvd) and the reduced models of [balred](balred).

## Example

```matlab
sys = ss([0 1; -2 -3], [0; 1], [1 0], 0);
Wc = gram(sys, 'c')
Wo = gram(sys, 'o')
eig(Wc)
```

## See also

[hsvd](hsvd) · [balred](balred) · [ctrb](ctrb) · [obsv](obsv) · [ss](ss)
