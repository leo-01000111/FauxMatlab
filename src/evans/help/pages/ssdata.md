# ssdata

The A, B, C and D matrices of a model's state-space realisation.

## Syntax

    [A, B, C, D] = ssdata(sys)
    A = ssdata(sys)

## Description

`[A, B, C, D] = ssdata(sys)` returns the matrices of `sys` in the form `dx/dt = A x + B u`, `y = C x + D u`. For an `ss` model they are the model's own matrices. A `tf` or `zpk` model is converted to state space first, and the realisation you get is python-control's (for `tf(1, [1 3 2])` it is `A = [-3 -2; 1 0]`, `C = [0 1]`). MATLAB's `ssdata` can return a different but equivalent realisation of the same transfer function, so compare poles or responses, not individual matrix entries.

Ask for fewer outputs to get only the first ones: `[A, B] = ssdata(sys)`, or `A = ssdata(sys)` for `A` alone. With no output it displays `A`. MATLAB's fifth output, the sample time, is not supported.

## Example

```matlab
G = tf(1, [1 3 2]);
[A, B, C, D] = ssdata(G);
eig(A)
```

## See also

[ss](ss) · [tf2ss](tf2ss) · [tfdata](tfdata) · [canon](canon) · [eig](eig)
