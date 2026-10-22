# sqrt

Square root of each element, complex for negative inputs.

## Syntax

    y = sqrt(x)

## Description

`sqrt(x)` works element by element on a scalar, vector or matrix and returns an array of the same shape. A negative real input gives an imaginary result, as in MATLAB: `sqrt(-4)` is `0 + 2i`. If any element of a matrix is negative, the whole result is complex, and the other elements show a zero imaginary part.

Complex inputs give the principal square root, the one with a non-negative real part.

`sqrt` is the element-wise root. Evans has no matrix square root (MATLAB's `sqrtm`).

## Example

```matlab
wn = sqrt(4)
zeta = 0.2;
wd = wn * sqrt(1 - zeta^2)
sqrt(-9)
```

## See also

[abs](abs) · [exp](exp) · [damp](damp) · [roots](roots)
