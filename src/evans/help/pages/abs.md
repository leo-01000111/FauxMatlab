# abs

Absolute value of each element, or the magnitude of each complex element.

## Syntax

    y = abs(x)

## Description

`abs(x)` works element by element on a scalar, vector or matrix and returns an array of the same shape. For a real element it drops the sign. For a complex element `a + bi` it returns the magnitude `sqrt(a^2 + b^2)`, which is how you get the gain from a complex frequency response.

`abs` takes one argument only. It does not accept a model: `abs(G)` on a `tf` is an error, so evaluate the model at a frequency first with [evalfr](evalfr) or [freqresp](freqresp).

## Example

```matlab
G = tf(1, [1 1]);
H = evalfr(G, 1i);
abs(H)
abs([-3 4; -1 2])
```

## See also

[sqrt](sqrt) · [freqresp](freqresp) · [evalfr](evalfr) · [bode](bode) · [max](max)
