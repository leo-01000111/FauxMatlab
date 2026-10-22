# roots

Roots of a polynomial given by its coefficient vector.

## Syntax

    r = roots(p)

## Description

`roots(p)` returns the roots of the polynomial whose coefficients are in `p`, highest power first: `[1 3 2]` is s^2 + 3s + 2. The roots come back as a column vector. Complex roots appear in conjugate pairs.

Leading zeros in `p` are dropped, so `roots([0 1 3 2])` is the same as `roots([1 3 2])`. The coefficients must be real. A matrix is read as one long vector, where MATLAB raises an error.

For a model, [pole](pole) and [zero](zero) give the same numbers directly from the `tf`, `zpk` or `ss` object. [poly](poly) goes the other way, from roots to coefficients.

## Example

```matlab
den = [1 2 5];
r = roots(den)
abs(r)
```

## See also

[poly](poly) · [polyval](polyval) · [pole](pole) · [zero](zero) · [routh](routh)
