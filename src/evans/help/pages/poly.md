# poly

Polynomial coefficients from a vector of roots, or the characteristic polynomial of a square matrix.

## Syntax

    p = poly(r)
    p = poly(A)

## Description

`poly(r)` with a vector of roots, row or column, returns the coefficients of the monic polynomial with those roots, highest power first, as a row vector. Complex roots in conjugate pairs give real coefficients; any imaginary rounding residue is removed.

`poly(A)` with a square matrix returns the characteristic polynomial det(sI - A). For a state matrix these are the denominator coefficients of the transfer function.

[roots](roots) returns its roots as a column, which `poly` reads as a vector, so `poly(roots(p))` gives back `p` divided by its leading coefficient. A matrix is read as a matrix only when it has more than one row and more than one column.

## Example

```matlab
den = poly([-1, -2, -5])
G = tf(10, den);
poly(roots([2 6 4]))
A = [0 1; -2 -3];
poly(A)
```

## See also

[roots](roots) · [conv](conv) · [eig](eig) · [tf](tf) · [polyval](polyval)
