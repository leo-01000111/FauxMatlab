# diff

Differences between neighbouring elements of a vector, or down each column of a matrix.

## Syntax

    D = diff(X)
    D = diff(X, n)

## Description

`diff(X)` for a vector returns `[X(2)-X(1), X(3)-X(2), ...]`, one element shorter than `X` and with the same orientation. For a matrix with more than one row it takes the differences down each column, so the result has one row fewer.

`diff(X, n)` applies the difference `n` times; `diff(X, 2)` is the second difference, two elements shorter.

Divided by the sample spacing, `diff` gives a finite-difference estimate of the derivative: `diff(y) ./ diff(t)`. Evans does not support the dimension argument `diff(X, n, dim)`.

## Example

```matlab
G = tf(1, [1 1]);
[y, t] = step(G, 5);
dydt = diff(y) ./ diff(t);
fprintf('Initial slope: %.3f\n', dydt(1))
```

## See also

[cumsum](cumsum) · [sum](sum) · [step](step) · [length](length)
