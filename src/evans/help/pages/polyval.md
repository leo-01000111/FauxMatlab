# polyval

Evaluate a polynomial at each element of an array.

## Syntax

    y = polyval(p, x)

## Description

`polyval(p, x)` evaluates the polynomial with coefficients `p` (highest power first) at every element of `x` and returns an array the same shape as `x`. `x` can be a scalar, a vector, a matrix or complex, so `polyval(den, 1i*w)` evaluates a denominator on the imaginary axis.

The evaluation is element by element. Evans has no matrix polynomial (MATLAB's `polyvalm`) and does not support the error-estimate outputs of MATLAB's `polyval`.

## Example

```matlab
p = [1 4 3];
polyval(p, 2)
polyval(p, roots(p))
w = 2;
abs(polyval([1 2], 1i*w))
```

## See also

[roots](roots) · [poly](poly) · [conv](conv) · [evalfr](evalfr)
