# estim

Luenberger observer gain `L` that puts the estimation-error eigenvalues of `A - L*C` at chosen locations.

## Syntax

    L = estim(sys, p)

## Description

`L = estim(sys, p)` returns the gain of the observer `xhat' = A*xhat + B*u + L*(y - C*xhat)` for the state-space model `sys`, chosen so that the estimation error `x - xhat` decays with the eigenvalues in `p`. `L` has one row per state and one column per output.

`p` must be a row vector with one entry per state, complex entries in conjugate pairs. The gain is computed by [place](place) on the dual pair `(A', C')`, so the same limits apply: on a single-output system the poles must be distinct. The model must be observable, otherwise `estim` stops with an error that lists the hidden modes; check with [isobsv](isobsv).

A common rule of thumb puts the observer poles two to five times faster than the closed-loop poles of the state feedback, so the estimate settles before the controller relies on it. Faster still and the observer amplifies measurement noise; [lqe](lqe) makes that trade-off from noise covariances instead.

This is not MATLAB's `estim`. In MATLAB `estim(sys, L)` takes a gain you already have and returns the estimator as a state-space model; Evans's `estim` designs the gain from pole locations, the job MATLAB does with `place(A', C', p)'`.

## Example

```matlab
sys = ss([0 1; -2 -3], [0; 1], [1 0], 0);
L = estim(sys, [-10 -11])
eig(sys.A - L*sys.C)
```

## See also

[place](place) · [lqe](lqe) · [kalman](kalman) · [obsv](obsv) · [isobsv](isobsv)
