# cumsum

Running (cumulative) sum of a vector, or down each column of a matrix.

## Syntax

    C = cumsum(A)
    C = cumsum(A, dim)

## Description

`cumsum(A)` for a vector returns a vector of the same shape whose `k`-th element is the sum of the first `k` elements of `A`. For a matrix it accumulates down each column.

`cumsum(A, dim)` accumulates along dimension `dim`: `1` down the columns, `2` along the rows. A row vector has one element per column, so `cumsum([1 2 3], 1)` is `[1 2 3]`.

Multiplied by the sample time, `cumsum` is a rectangle-rule integral, the discrete counterpart of an integrator. For a more accurate integral of sampled data use `trapz` or `cumtrapz`. [diff](diff) undoes it, apart from the first element.

## Example

```matlab
Ts = 0.1;
e = [1 0.8 0.5 0.3 0.1];
I = Ts * cumsum(e)
```

## See also

[sum](sum) · [diff](diff) · [lsim](lsim) · [mean](mean)
