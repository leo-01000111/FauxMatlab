# isctrb

Test whether a state-space model is controllable.

## Syntax

    c = isctrb(sys)

## Description

`c = isctrb(sys)` returns logical 1 when every mode of the state-space model `sys` can be moved by state feedback, and 0 otherwise. The verdict comes from the Popov-Belevitch-Hautus test applied to each eigenvalue, which stays reliable on models where the rank of [ctrb](ctrb) is hard to judge numerically.

Only the one-argument form exists: build the model first, `isctrb(ss(A, B, C, D))`, rather than passing `A` and `B`. A transfer function is not accepted either; convert it with `ss(G)`.

A model that is not controllable can still be stabilisable, when its uncontrollable modes are stable. [place](place) and [acker](acker) need full controllability; [lqr](lqr) needs only stabilisability.

## Example

```matlab
sys = ss([0 1; -2 -3], [0; 1], [1 0], 0);
isctrb(sys)
sys2 = ss([-1 0; 0 -2], [1; 0], [1 1], 0);
isctrb(sys2)
```

## See also

[ctrb](ctrb) · [isobsv](isobsv) · [place](place) · [minreal](minreal)
