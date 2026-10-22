# series

Series (cascade) connection of systems: the output of each one drives the next.

## Syntax

    sys = series(sys1, sys2)
    sys = series(sys1, sys2, sys3, ...)

## Description

`sys = series(sys1, sys2)` returns `sys2*sys1`, the system whose input goes into `sys1` and whose output comes out of `sys2`. For single-input single-output models the order does not matter and the result equals `sys1*sys2`.

`series(sys1, sys2, sys3, ...)` chains any number of systems in the order given.

The systems can be transfer functions or state-space models, and a plain number acts as a gain. A mix of a state-space model and a transfer function gives a transfer function. Evans does not support MATLAB's forms with output and input index vectors for connecting parts of multi-input multi-output models.

Writing the product directly, `C*G`, gives the same result and is more common in scripts.

## Example

```matlab
G1 = tf(1, [1 1]);
G2 = tf(2, [1 3]);
G = series(G1, G2)
step(G)
```

## See also

[parallel](parallel) · [feedback](feedback) · [tf](tf) · [minreal](minreal)
