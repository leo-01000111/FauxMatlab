# ss2tf

Transfer function of a state-space model.

## Syntax

    G = ss2tf(sys)

## Description

`G = ss2tf(sys)` returns the transfer function `C (sI - A)^-1 B + D` of the state-space model `sys`. Uncontrollable or unobservable modes cancel in this product, so a pole-zero pair can be left over; use [minreal](minreal) to remove it.

Round-off in the conversion can leave a tiny leading coefficient, such as `8.9e-16 s` in the numerator. It has no visible effect on the response, and [minreal](minreal) removes it.

Evans does not support MATLAB's `[num, den] = ss2tf(A, B, C, D)`. Build the model with [ss](ss), convert it, and take the coefficients out with [tfdata](tfdata), as in the example. `tf(sys)` gives the same transfer function.

## Example

```matlab
sys = ss([-1 0; 0 -2], [1; 1], [1 2], 0);
G = ss2tf(sys)
[num, den] = tfdata(G, 'v')
```

## See also

[tf2ss](tf2ss) · [tf](tf) · [ss](ss) · [tfdata](tfdata) · [minreal](minreal)
