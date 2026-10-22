# ss

State-space model from the matrices A, B, C and D, or a state-space realisation of a transfer function.

## Syntax

    sys = ss(A, B, C, D)
    sys = ss(A, B, C)
    sys = ss(A, B, C, D, Ts)
    sys = ss(G)

## Description

`sys = ss(A, B, C, D)` builds the continuous-time model `dx/dt = A x + B u`, `y = C x + D u`. `A` must be square, with one row per state. `B` needs that many rows and `C` that many columns; a vector given the wrong way round is transposed to fit. `ss(A, B, C)` takes `D` as zeros of the right size.

`sys = ss(A, B, C, D, Ts)` treats `A, B, C, D` as a continuous-time model and discretises it with sample time `Ts` (zero-order hold), as [c2d](c2d) would. MATLAB instead takes the matrices as an already discrete model, so the same line gives different matrices in the two programs.

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
