# lqe

Steady-state Kalman filter gain: the observer gain that minimises the variance of the state estimate.

## Syntax

    L = lqe(sys, W, V)
    L = lqe(sys)
    [L, P, e] = lqe(sys, W, V)

## Description

`L = lqe(sys, W, V)` returns the gain of the observer `xhat' = A*xhat + B*u + L*(y - C*xhat)` that is optimal for the model `x' = A*x + B*u + w`, `y = C*x + v`. `W` is the covariance of the process noise `w`, an n by n matrix acting directly on the state derivative, and `V` the covariance of the measurement noise `v`, p by p. `L` comes back n by p.

The ratio of the two sets the speed of the filter. A large `V` (a noisy sensor) makes it trust the model and respond slowly; a large `W` (an uncertain model) makes it trust the measurement and respond fast.

`W` and `V` can each be a full square matrix, a scalar (which multiplies the identity) or a vector of diagonal entries. `V` must be positive definite. With no `W` the default is `B*B'`, noise entering where the input does; with no `V` it is the identity.

`[L, P, e] = lqe(sys, W, V)` also returns `P`, the steady-state covariance of the estimation error (the solution of the filter Riccati equation), and `e`, the eigenvalues of `A - L*C` as a row vector.

The model must be detectable: unstable modes the output cannot see make `lqe` stop with an error. A discrete-time model gets the discrete-time filter.

MATLAB's `lqe(A, G, C, Q, R)` is not supported: build the model with [ss](ss) and pass `W = G*Q*G'`. [kalman](kalman) is the same function under another name. Assign at least `L`, since with no output the three results print together unformatted.

## Example

```matlab
sys = ss([0 1; -2 -3], [0; 1], [1 0], 0);
[L, P, e] = lqe(sys, 1, 0.01)
```

## See also

[kalman](kalman) · [estim](estim) · [lqr](lqr) · [isobsv](isobsv) · [ss](ss)
