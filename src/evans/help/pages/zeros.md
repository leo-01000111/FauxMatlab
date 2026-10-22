# zeros

Array of zeros, of a given number of rows and columns.

## Syntax

    X = zeros
    X = zeros(n)
    X = zeros(m, n)
    X = zeros([m n])

## Description

`zeros(n)` is an n-by-n matrix of zeros. `zeros(m, n)` and `zeros([m n])` give m rows and n columns. With no argument, `zeros` is the scalar 0.

The usual uses are a zero initial state (`x0 = zeros(2, 1)`), a zero feedthrough matrix `D` for [ss](ss), and an array allocated before a loop fills it in.

Evans makes two-dimensional arrays only: `zeros(2, 2, 2)` stops with an error saying N-D arrays are not supported yet. A trailing size of 1, as in `zeros(2, 3, 1)`, is still a matrix and works. A class name such as `'int32'` or `'like', x` is accepted and ignored, so the result is always double.

## Example

```matlab
A = [0 1; -2 -3];
B = [0; 1];
x0 = zeros(2, 1)
sys = ss(A, B, eye(2), zeros(2, 1));
```

```matlab
u = [zeros(1, 3), ones(1, 4)]
```

## See also

[ones](ones) · [eye](eye) · [rand](rand) · [size](size) · [repmat](repmat)
