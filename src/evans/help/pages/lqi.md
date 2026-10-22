# lqi

Linear-quadratic regulator with integral action, for tracking a constant reference with zero steady-state error.

## Syntax

    K = lqi(sys, Q, R)
    K = lqi(sys)
    [K, S, e] = lqi(sys, Q, R)

## Description

`K = lqi(sys, Q, R)` augments the state of `sys` with the integral of the tracking error, `xi = ∫ (r - y) dt`, and designs an [lqr](lqr) gain for the augmented plant. The control law is `u = -K*[x; xi]`. `K` has one column per state and then one per output: the last columns are the gains on the integrators.

The integrator is what removes steady-state error under a constant disturbance or a model error, which plain state feedback with a precompensator cannot do.

`Q` weights the augmented state, so it is (n+p) by (n+p) for n states and p outputs; a scalar or a vector of n+p diagonal entries also works. A large weight on the last entries makes the integral act faster. `R` weights the inputs as in [lqr](lqr). `lqi(sys)` uses identity matrices for both.

`[K, S, e] = lqi(sys, Q, R)` also returns the Riccati solution `S` of the augmented problem and the closed-loop eigenvalues `e` of the augmented system.

`sys` must be a state-space model with a `C` matrix. Assign at least `K`, since with no output the three results print together unformatted.

## Example

```matlab
sys = ss([0 1; -2 -3], [0; 1], [1 0], 0);
[K, S, e] = lqi(sys, diag([1 1 10]), 1);
K
e
```

## See also

[lqr](lqr) · [place](place) · [pid](pid) · [ss](ss)
