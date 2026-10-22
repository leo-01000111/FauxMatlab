# isobsv

Test whether a state-space model is observable.

## Syntax

    o = isobsv(sys)

## Description

`o = isobsv(sys)` returns logical 1 when every mode of the state-space model `sys` shows up in its output, and 0 otherwise. The verdict comes from the Popov-Belevitch-Hautus test applied to each eigenvalue, which stays reliable on models where the rank of [obsv](obsv) is hard to judge numerically.

Only the one-argument form exists: build the model first, `isobsv(ss(A, B, C, D))`, rather than passing `A` and `C`. A transfer function is not accepted; convert it with `ss(G)`.

An unobservable model can still be detectable, when its hidden modes are stable. [estim](estim) needs full observability; [lqe](lqe) needs only detectability.

## Example

```matlab
sys = ss([-1 0; 0 -2], [1; 1], [1 0], 0);
isobsv(sys)
sys2 = ss([-1 0; 0 -2], [1; 1], [1 1], 0);
isobsv(sys2)
```

## See also

[obsv](obsv) · [isctrb](isctrb) · [estim](estim) · [minreal](minreal)
