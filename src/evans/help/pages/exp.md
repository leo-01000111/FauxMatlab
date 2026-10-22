# exp

Exponential e^x of each element, real or complex.

## Syntax

    y = exp(x)

## Description

`exp(x)` works element by element on a scalar, vector or matrix and returns an array of the same shape. For a complex `x = a + bi` it returns `exp(a) * (cos(b) + i*sin(b))`, so `exp(1i*w*t)` gives a point on the unit circle.

It is the element-wise exponential. Evans has no matrix exponential (MATLAB's `expm`); to discretise a state-space model use [c2d](c2d).

The common use in control is a decaying mode: a pole at `s = -a` contributes `exp(-a*t)` to the response.

## Example

```matlab
t = 0:0.5:2;
y = exp(-2*t)
abs(exp(2i))
```

## See also

[sqrt](sqrt) · [abs](abs) · [initial](initial) · [c2d](c2d) · [plot](plot)
