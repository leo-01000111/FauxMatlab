# poly

Polynomial coefficients from a vector of roots, or the characteristic polynomial of a square matrix.

## Syntax

    p = poly(r)
    p = poly(A)

## Description

`poly(r)` with a row vector of roots returns the coefficients of the monic polynomial with those roots, highest power first, as a row vector. Complex roots in conjugate pairs give real coefficients; any imaginary rounding residue is removed.

`poly(A)` with a square matrix returns the characteristic polynomial det(sI - A). For a state matrix these are the denominator coefficients of the transfer function.

In Evans the roots must be a row vector. [roots](roots) returns a column, which `poly` reads as a non-square matrix and rejects, so transpose it: `poly(roots(p)')`.

## Example

```matlab
den = poly([-1, -2, -5])
G = tf(10, den);
A = [0 1; -2 -3];
poly(A)
```

## See also

[roots](roots) · [conv](conv) · [eig](eig) · [tf](tf) · [polyval](polyval)
