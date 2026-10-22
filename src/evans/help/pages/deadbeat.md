# deadbeat

State-feedback gain that places every closed-loop pole of a discrete-time model at z = 0, so the state reaches zero in n samples.

## Syntax

    K = deadbeat(sysd)

## Description

MATLAB has no `deadbeat` command; Evans adds it for the deadbeat design taught with discrete control. `deadbeat(sysd)` returns the row vector `K` for the control law `u[k] = -K x[k]` such that every eigenvalue of `A - B*K` is zero. The closed-loop state matrix is then nilpotent: `(A - B*K)^n` is exactly the zero matrix for an `n`-state model, so any initial state is driven exactly to the origin in at most `n` samples.

`sysd` must be a discrete-time state-space model with one input. Sample a continuous plant first with [c2d](c2d) (from an `ss` model, so that the states are the ones you chose), and keep the model controllable, since the gain is computed with Ackermann's formula as in [acker](acker). A continuous model, a transfer function or a model with several inputs is an error.

Deadbeat control asks for large inputs, and it grows with shorter sample times. With every pole at the origin it has no margin to spare, so a small model error shows up at once in the response.

## Example

```matlab
sys = ss([0 1; 0 0], [0; 1], [1 0], 0);
sysd = c2d(sys, 0.5);
K = deadbeat(sysd)
Acl = sysd.A - sysd.B*K;
Acl^2
```

## See also

[c2d](c2d) · [acker](acker) · [place](place) · [ctrb](ctrb) · [ss](ss)
