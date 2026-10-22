# min

Smallest element of a vector, the smallest of each column of a matrix, or the smaller of two arrays element by element.

## Syntax

    M = min(A)
    [M, I] = min(A)
    M = min(A, B)
    M = min(A, [], dim)
    [M, I] = min(A, [], dim)

## Description

`min(A)` for a vector returns its smallest element. For a matrix it returns a row vector holding the smallest element of each column.

`[M, I] = min(A)` also returns the index of the minimum: for a vector the position in the vector, for a matrix the row of each column's minimum. When the minimum appears more than once, `I` points to the first one.

`min(A, B)` compares two arrays element by element and returns the smaller of each pair. One of them can be a scalar, so `min(u, 10)` saturates a signal at 10.

`min(A, [], dim)` works along dimension `dim`: `1` down the columns, `2` along each row (the result is then a column vector).

`NaN` elements are ignored. Complex elements are compared by magnitude. Evans does not support `min(A, [], 'all')`; use `min(A(:))`.

## Example

```matlab
G = tf(1, [1 0.4 1]);
[y, t] = step(G, 20);
low = min(y(t > 5));
fprintf('Lowest output after 5 s: %.3f\n', low)
u = min([2 8 15 4], 10)
```

## See also

[max](max) · [sort](sort) · [find](find) · [abs](abs)
