# reshape

Rearrange the elements of an array into a new number of rows and columns.

## Syntax

    B = reshape(A, m, n)
    B = reshape(A, [m n])

## Description

`reshape(A, m, n)` returns an m-by-n array holding the elements of `A` in the same column-major order: down the first column, then down the second, and so on. `reshape(A, [m n])` does the same with the sizes in one vector. The total number of elements must stay the same, so `m*n` must equal `numel(A)`.

`reshape(x, [], 1)` is not supported in Evans: give both sizes. To turn any array into a column, `A(:)` works and needs no sizes.

If the counts do not match, the error comes from the numerical library underneath, worded as `cannot reshape array of size 6 into shape (4,2)`.

## Example

```matlab
y = 1:6;
Y = reshape(y, 2, 3)
```

```matlab
K = reshape([2 0.5 1 3], 2, 2)
```

## See also

[size](size) · [numel](numel) · [repmat](repmat) · [zeros](zeros)
