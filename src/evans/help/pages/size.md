# size

Number of rows and columns of an array, or of outputs and inputs of a model.

## Syntax

    sz = size(A)
    [m, n] = size(A)
    [m, n, p, ...] = size(A)
    d = size(A, dim)

## Description

`size(A)` with one output is the row vector `[rows columns]`. With two outputs, `[m, n] = size(A)` returns the counts separately. Each output after the second is 1.

`size(A, dim)` returns one dimension: `size(A, 1)` is the number of rows, `size(A, 2)` the number of columns, and any higher `dim` gives 1.

For a [tf](tf), [zpk](zpk) or [ss](ss) model, `size` counts outputs and inputs, so a SISO model is 1-by-1. The number of states of an `ss` model is `size(A, 1)` of its state matrix. Text counts its characters as columns (`size('hello')` is 1-by-5), and a struct is 1-by-1.

Evans arrays are two-dimensional, so `size` never reports a third dimension above 1.

## Example

```matlab
A = [0 1 0; 0 0 1; -6 -11 -6];
B = [0; 0; 1];
[n, m] = size(A)
Co = ctrb(A, B);
rank(Co) == size(A, 1)
```

## See also

[length](length) · [numel](numel) · [reshape](reshape) · [zeros](zeros) · [ss](ss)
