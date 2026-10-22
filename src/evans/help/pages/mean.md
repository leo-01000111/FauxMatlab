# mean

Average of the elements of a vector, or of each column of a matrix.

## Syntax

    m = mean(A)
    m = mean(A, dim)

## Description

`mean(A)` for a row or column vector returns the arithmetic mean of its elements. For a matrix it averages down each column and returns a row vector.

`mean(A, dim)` averages along dimension `dim`: `1` down the columns, `2` along the rows. As with [sum](sum), `mean(A, 2)` is a column vector with one mean per row, and `mean(x, 1)` of a row vector is the row itself.

The mean of an empty array is `NaN`. Evans does not support the `'all'` or `'omitnan'` options; use `mean(A(:))` for the mean of every element.

## Example

```matlab
G = tf(4, [1 2 4]);
[y, t] = step(G, 10);
fprintf('Mean output over 10 s: %.3f\n', mean(y))
mean([1 2; 3 4])
```

## See also

[sum](sum) · [max](max) · [min](min) · [step](step)
