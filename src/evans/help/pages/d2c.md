# d2c

Converts a discrete-time model back to a continuous-time one, inverting a zero-order-hold or Tustin discretisation.

## Syntax

    sysc = d2c(sysd)
    sysc = d2c(sysd, method)

## Description

`d2c(sysd)` returns the continuous model that, sampled with a zero-order hold at the sample time of `sysd`, gives `sysd` back. It works through the matrix logarithm of the state matrix, so it is exact when such a model exists. Two cases have none, and `d2c` stops with an error rather than return an approximation:

- a real eigenvalue of the state matrix at or left of `z = 0`, which no continuous system sampled at this rate can produce;
- an eigenvalue at `z = 1`, an integrator, where the zero-order-hold inverse is not defined.

`d2c(sysd, 'tustin')` inverts the bilinear map instead (`'bilinear'` is accepted too). It always gives a result, as long as no eigenvalue sits at `z = -1`, but it only matches a model discretised with the same method. These two are the only methods; any other name is an error.

The model comes back in the form it came in: a `tf` gives a `tf`, an `ss` gives an `ss`. So `d2c(c2d(G, Ts))` can be compared with `G` directly. Calling `d2c` on a continuous model is an error.

## Example

```matlab
G = tf(2, [1 3 2]);
Gd = c2d(G, 0.05);
Gc = d2c(Gd);
pole(Gc)
dcgain(Gc)
```

## See also

[c2d](c2d) · [tf](tf) · [ss](ss) · [pole](pole)
