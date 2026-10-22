# tf2ss

State-space realisation of a transfer function.

## Syntax

    sys = tf2ss(G)

## Description

`sys = tf2ss(G)` returns a state-space model with the same input-output behaviour as the transfer function `G`. The realisation is the controller canonical form: for `G = (b1 s + b2)/(s^2 + a1 s + a2)` it has `A = [-a1 -a2; 1 0]`, `B = [1; 0]` and `C = [b1 b2]`, the same matrices MATLAB's `tf2ss` returns.

Evans does not support MATLAB's `[A, B, C, D] = tf2ss(num, den)`. Build the transfer function first with [tf](tf), then take the matrices out with [ssdata](ssdata), as in the example. `ss(G)` gives the same model.

A transfer function has many realisations. This one is controllable by construction; [canon](canon) gives the modal and observable forms.

## Example

```matlab
G = tf([1 3], [1 3 2]);
sys = tf2ss(G);
[A, B, C, D] = ssdata(sys)
```

## See also

[ss2tf](ss2tf) · [ss](ss) · [ssdata](ssdata) · [canon](canon) · [tf](tf)
