# kalman

Steady-state Kalman filter gain for a state-space model with process and measurement noise.

## Syntax

    L = kalman(sys, W, V)
    L = kalman(sys)
    [L, P, e] = kalman(sys, W, V)

## Description

`kalman` is another name for [lqe](lqe) and takes the same arguments. `L = kalman(sys, W, V)` returns the gain of the observer `xhat' = A*xhat + B*u + L*(y - C*xhat)` that minimises the estimation-error variance, for process noise of covariance `W` (n by n, acting on the state derivative) and measurement noise of covariance `V` (p by p).

`W` and `V` can be full matrices, scalars (which multiply the identity) or vectors of diagonal entries. With no `W` the default is `B*B'`; with no `V` it is the identity. `[L, P, e] = kalman(sys, W, V)` also returns the steady-state error covariance `P` and the eigenvalues `e` of `A - L*C`.

The outputs differ from MATLAB's. In MATLAB `[kest, L, P] = kalman(sys, Qn, Rn)` returns the estimator as a state-space model first; in Evans the first output is the gain `L`, so `[kest, L, P]` would put `L` in `kest`. Build the estimator yourself from `L` when you need it as a model.

## Example

```matlab
sys = ss([0 1; -2 -3], [0; 1], [1 0], 0);
[L, P, e] = kalman(sys, 1, 0.01);
L
e
```

## See also

[lqe](lqe) · [estim](estim) · [lqr](lqr) · [isobsv](isobsv)
