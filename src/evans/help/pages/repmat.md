# repmat

Tile an array: repeat it a number of times down and across.

## Syntax

    B = repmat(A, n)
    B = repmat(A, m, n)
    B = repmat(A, [m n])

## Description

`repmat(A, m, n)` stacks `m` copies of `A` vertically and `n` copies horizontally, so a p-by-q array becomes (p*m)-by-(q*n). `repmat(A, [m n])` is the same. `repmat(A, n)` repeats `n` times in both directions.

With a scalar `A`, `repmat(7, 3)` is a 3-by-3 matrix of sevens, the same as `7*ones(3)`.

Text is repeated across only: `repmat('ab', 1, 3)` is `'ababab'`. Evans ignores the row count for text, so `repmat('ab', 2, 1)` gives `'ab'`.

## Example

```matlab
row = [1 0 -1];
M = repmat(row, 3, 1)
```

```matlab
pulse = [ones(1, 5), zeros(1, 5)];
u = repmat(pulse, 1, 3);
fprintf('%d samples\n', numel(u))
```

## See also

[ones](ones) · [zeros](zeros) · [reshape](reshape) · [size](size)
