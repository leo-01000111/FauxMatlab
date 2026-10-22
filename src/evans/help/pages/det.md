# det

Determinant of a square matrix.

## Syntax

    d = det(A)

## Description

`det(A)` returns the determinant of the square matrix `A` as a real scalar (a complex rounding residue is dropped). It is computed from an LU factorisation, so a value that should be an integer may show a few decimals of rounding, such as `10.0000`. A non-square argument is an error.

A zero determinant means `A` is singular and [inv](inv) will fail. The size of `det` is a poor measure of how close to singular a matrix is: a matrix with small entries has a small determinant even when it is well conditioned.

In control, `det(ctrb(A, B))` is nonzero exactly when a single-input system is controllable.

## Example

```matlab
A = [0 1; -2 -3];
B = [0; 1];
det(ctrb(A, B))
det([1 2; 2 4])
```

## See also

[inv](inv) · [eig](eig) · [ctrb](ctrb) · [obsv](obsv) · [isctrb](isctrb)
