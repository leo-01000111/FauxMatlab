# find

Linear indices of the nonzero (true) elements of an array.

## Syntax

    k = find(X)
    k = find(X, n)

## Description

`find(X)` returns the positions of the nonzero elements of `X`, counting from 1. Most often `X` is a logical condition such as `y > 0.9`. For a row vector the result is a row vector; for a column vector or a matrix it is a column vector. Matrix elements are numbered down the columns (linear indexing), so the indices work directly in `A(k)`.

`find(X, n)` returns only the first `n` indices. `find(X, 1)` is the usual way to get the first sample where a condition holds.

When nothing matches, the result is empty, `[]`. Evans does not support the row and column outputs `[r, c] = find(X)` or the `'last'` direction.

## Example

```matlab
G = tf(4, [1 2 4]);
[y, t] = step(G);
k = find(y >= 0.9 * y(end), 1);
fprintf('Reaches 90%% at t = %.2f s\n', t(k))
```

## See also

[max](max) · [min](min) · [sort](sort) · [stepinfo](stepinfo) · [length](length)
