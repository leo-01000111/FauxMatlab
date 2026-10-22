# max

Largest element of a vector, the largest of each column of a matrix, or the larger of two arrays element by element.

## Syntax

    M = max(A)
    [M, I] = max(A)
    M = max(A, B)
    M = max(A, [], dim)
    [M, I] = max(A, [], dim)

## Description

`max(A)` for a vector returns its largest element. For a matrix it returns a row vector holding the largest element of each column.

`[M, I] = max(A)` also returns the index of the maximum: for a vector the position in the vector, for a matrix the row of each column's maximum. When the maximum appears more than once, `I` points to the first one.

`max(A, B)` compares two arrays element by element and returns the larger of each pair. One of them can be a scalar, so `max(x, 0)` clips negative values to zero.

`max(A, [], dim)` works along dimension `dim`: `1` down the columns, `2` along each row (the result is then a column vector).

`NaN` elements are ignored. Complex elements are compared by magnitude. Evans does not support `max(A, [], 'all')`; use `max(A(:))`.

## Example

```matlab
G = tf(4, [1 2 4]);
[y, t] = step(G);
[peak, k] = max(y);
fprintf('Peak %.3f at t = %.2f s\n', peak, t(k))
```

## See also

[min](min) · [sort](sort) · [find](find) · [stepinfo](stepinfo) · [abs](abs)
