# pzmap

Pole-zero map of a dynamic system: its poles (x) and zeros (o) in the complex plane.

## Syntax

    pzmap(sys)
    pzmap(sys1, sys2, ...)
    p = pzmap(sys)
    [p, z] = pzmap(sys)

## Description

`pzmap(sys)` plots the poles of `sys` as crosses and its zeros as circles, for a `tf`, `zpk` or `ss` model, with the real and imaginary axes drawn through the origin. For a discrete-time model the unit circle is drawn as well, since stability there means every pole inside it.

`pzmap(sys1, sys2, ...)` puts several systems on one map, each in its own colour. Plot options from [pzoptions](pzoptions) are accepted and ignored for now.

With output arguments nothing is drawn. `p` is a column vector of the poles and `z` a column vector of the zeros, the same values [pole](pole) and [zero](zero) return.

## Example

```matlab
G = tf([1 3], [1 2 10]);
pzmap(G)
[p, z] = pzmap(G)
```

## See also

[pole](pole) · [zero](zero) · [damp](damp) · [rlocus](rlocus) · [pzoptions](pzoptions)
