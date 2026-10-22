# eig

Eigenvalues and eigenvectors of a square matrix, or the poles of a model.

## Syntax

    e = eig(A)
    [V, D] = eig(A)
    e = eig(sys)

## Description

`eig(A)` returns the eigenvalues of the square matrix `A` as a column vector. For a state matrix these are the poles of the system: all with negative real part means the system is asymptotically stable.

`[V, D] = eig(A)` returns the eigenvectors as the columns of `V` and the eigenvalues on the diagonal of `D`, so that `A*V = V*D` up to rounding. Each eigenvector has unit length.

`eig(sys)` with a `tf`, `zpk` or `ss` model returns its poles as a column vector, the same as [pole](pole).

Evans does not support the generalised problem `eig(A, B)` or the extra options of MATLAB's `eig`. A non-square matrix is an error.

## Example

```matlab
A = [0 1; -5 -2];
e = eig(A)
[V, D] = eig(A);
real(e) < 0
```

## See also

[pole](pole) · [damp](damp) · [isstable](isstable) · [poly](poly) · [ss](ss) · [det](det)
