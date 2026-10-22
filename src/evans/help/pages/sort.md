# sort

Sort the elements of a vector, or each column of a matrix, in ascending or descending order.

## Syntax

    B = sort(A)
    B = sort(A, dim)
    B = sort(A, 'descend')
    B = sort(A, dim, 'descend')
    [B, I] = sort(A, ...)

## Description

`sort(A)` returns the elements of a vector in ascending order, with the same orientation as `A`. For a matrix it sorts each column on its own.

`sort(A, 'descend')` sorts from largest to smallest. `'ascend'` is the default and can be given explicitly.

`[B, I] = sort(A)` also returns the index vector, so that `B` equals `A(I)` for a vector. Equal elements keep their original order.

`sort(A, dim)` sorts along dimension `dim`: `1` sorts each column, `2` sorts each row.

Complex values are ordered by magnitude, and values of equal magnitude by their angle from -pi to pi, as in MATLAB: `sort([-3 1+1i 2])` is `[1+1i 2 -3]`.

## Example

```matlab
Ts = [0.8 2.4 1.1 3.0];
[s, k] = sort(Ts, 'descend')
```

## See also

[max](max) · [min](min) · [find](find) · [pole](pole) · [roots](roots)
