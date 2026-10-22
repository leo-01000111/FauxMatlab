# minreal

Minimal realisation: removes cancelling pole-zero pairs from a transfer function, or uncontrollable and unobservable states from a state-space model.

## Syntax

    sysr = minreal(sys)
    sysr = minreal(sys, tol)

## Description

`sysr = minreal(sys)` returns a model with the same input-output behaviour as `sys` and the smallest possible order. For a state-space model it keeps the controllable part, then the observable part of that, so states the input cannot reach or the output cannot see are dropped. For a transfer function it does the same on a state-space realisation and converts back, which cancels every pole-zero pair that coincides.

`sysr = minreal(sys, tol)` sets the tolerance, `1e-9` by default. It is relative to the largest singular value of the controllability matrix: directions with a smaller singular value count as uncontrollable, and the same test is applied for observability. Raise it to cancel a pole and zero that are close but not equal, such as `(s + 1.001)/((s + 1)(s + 2))` with `tol = 0.01`.

MATLAB prints how many states were removed; Evans prints nothing extra. Compare the order before and after with [pole](pole), or for a state-space model with [ssdata](ssdata).

## Example

```matlab
G = (s + 1)/((s + 1)*(s + 2))
Gr = minreal(G)
```

## See also

[feedback](feedback) · [pole](pole) · [zero](zero) · [ctrb](ctrb) · [obsv](obsv) · [balred](balred)
