# zero

Zeros of a dynamic system: the values of `s` (or `z`) where its transfer function becomes zero.

## Syntax

    zero(sys)
    z = zero(sys)

## Description

`z = zero(sys)` returns the zeros of `sys`, which can be a `tf`, `zpk` or `ss` model, continuous or discrete. For a transfer function they are the roots of the numerator; for a state-space model they are the transmission zeros of the realisation.

The result is a complex vector, so real zeros print with a `+ 0i` part, and it is a row where MATLAB returns a column. A system with no finite zeros returns an empty vector.

Evans does not support the two-output form `[z, k] = zero(sys)`; it stops with "Too many output arguments". Read the gain from [zpkdata](zpkdata) instead.

A zero in the right half-plane makes a continuous system non-minimum phase: the step response starts off in the wrong direction, and the zero limits how fast a feedback loop can be made. [mpsplit](mpsplit) separates that part out.

## Example

```matlab
s = tf('s');
G = (2 - s) / (s^2 + 3*s + 2);
z = zero(G)
```

## See also

[pole](pole) · [pzmap](pzmap) · [zpkdata](zpkdata) · [mpsplit](mpsplit) · [zpk](zpk)
