# parallel

Parallel connection of systems: one input feeds every system and their outputs are summed.

## Syntax

    sys = parallel(sys1, sys2)
    sys = parallel(sys1, sys2, sys3, ...)

## Description

`sys = parallel(sys1, sys2)` returns `sys1 + sys2`. The poles of the result are those of both systems. The zeros are new, since the numerators combine over a common denominator.

`parallel(sys1, sys2, sys3, ...)` adds any number of systems.

The systems can be transfer functions or state-space models, and a plain number acts as a direct feedthrough gain, so `parallel(G, 2)` is `G + 2`. To subtract a path, add its negative: `parallel(G1, -G2)`. Evans does not support MATLAB's forms with input and output index vectors for multi-input multi-output models.

## Example

```matlab
G1 = tf(1, [1 1]);
G2 = tf(2, [1 3]);
G = parallel(G1, G2)
z = zero(G)
```

## See also

[series](series) · [feedback](feedback) · [zero](zero) · [tf](tf)
