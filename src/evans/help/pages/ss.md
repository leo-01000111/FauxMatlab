# ss

State-space model from the matrices A, B, C and D, or a state-space realisation of a transfer function.

## Syntax

    sys = ss(A, B, C, D)
    sys = ss(A, B, C)
    sys = ss(A, B, C, D, Ts)
    sys = ss(G)

## Description

`sys = ss(A, B, C, D)` builds the continuous-time model `dx/dt = A x + B u`, `y = C x + D u`. `A` must be square, with one row per state. `B` needs that many rows and `C` that many columns; a vector given the wrong way round is transposed to fit. `ss(A, B, C)` takes `D` as zeros of the right size.

`sys = ss(A, B, C, D, Ts)` builds the discrete-time model `x[k+1] = A x[k] + B u[k]`, `y[k] = C x[k] + D u[k]` with sample time `Ts` seconds, as in MATLAB: the matrices are already the discrete ones and are kept as given. `Ts = -1` leaves the sample time unspecified. To discretise a continuous model, use `c2d(ss(A, B, C, D), Ts)`; see [c2d](c2d).

`sys = ss(G)` returns a state-space realisation of the transfer function `G`, the same one [tf2ss](tf2ss) gives.

The matrices are shown when the model is displayed. To get them back as variables, use [ssdata](ssdata).

## Example

```matlab
A = [0 1; -2 -3]; B = [0; 1]; C = [1 0]; D = 0;
sys = ss(A, B, C, D);
p = pole(sys)
k = dcgain(sys)
step(sys)
```

## See also

[tf](tf) · [ssdata](ssdata) · [tf2ss](tf2ss) · [ss2tf](ss2tf) · [ctrb](ctrb) · [minreal](minreal)
