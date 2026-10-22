# feedback

Closed-loop system of a forward path with a feedback path, negative feedback unless you ask for positive.

## Syntax

    T = feedback(G)
    T = feedback(G, H)
    T = feedback(G, H, sign)

## Description

`T = feedback(G, H)` returns the closed loop `G/(1 + G*H)`. `G` is the forward path from the error to the output, and `H` the path that carries the output back to the summing junction, where it is subtracted. For unity feedback `H` is `1`.

`T = feedback(G)` is unity negative feedback, the same as `feedback(G, 1)`. MATLAB requires the second argument; Evans takes `1` when it is left out.

`T = feedback(G, H, sign)` sets the sign at the summing junction: `-1` (the default) for negative feedback, `+1` for positive feedback, which gives `G/(1 - G*H)`.

With a controller `C` and plant `G` in the forward path, write `feedback(C*G, 1)`. `G` and `H` can be transfer functions or state-space models, and a number acts as a gain. The result is not reduced: a pole and zero that cancel stay in it until you call [minreal](minreal).

## Example

```matlab
G = tf(4, [1 2 0]);
T = feedback(G, 1)
step(T)
damp(T)
```

## See also

[series](series) · [parallel](parallel) · [pid](pid) · [minreal](minreal) · [step](step) · [margin](margin)
