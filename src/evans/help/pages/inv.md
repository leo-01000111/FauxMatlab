# inv

Inverse of a square matrix.

## Syntax

    B = inv(A)

## Description

`inv(A)` returns the matrix `B` with `A*B = B*A = I`. `A` must be square; a scalar gives its reciprocal.

A singular matrix is an error in Evans (`Singular matrix`), where MATLAB warns and returns `Inf` values. A nearly singular matrix returns a result with large, unreliable entries.

To solve `A*x = b`, the backslash `A\b` is faster and more accurate than `inv(A)*b`. A common control use is the steady-state gain of a state-space model, `-C*inv(A)*B + D`, which [dcgain](dcgain) computes for you.

## Example

```matlab
A = [0 1; -2 -3];
B = [0; 1];
C = [1 0];
Ainv = inv(A)
-C * Ainv * B
```

## See also

[det](det) · [eig](eig) · [dcgain](dcgain) · [ss](ss) · [eye](eye)
