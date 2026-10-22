# ones

Array of ones, of a given number of rows and columns.

## Syntax

    X = ones
    X = ones(n)
    X = ones(m, n)
    X = ones([m n])

## Description

`ones(n)` is an n-by-n matrix of ones. `ones(m, n)` and `ones([m n])` give m rows and n columns. With no argument, `ones` is the scalar 1.

Scale it to get a constant array: `5 * ones(1, 10)` is a row of ten fives. `ones(size(t))` makes a unit step input with the same shape as a time vector `t`.

Evans makes two-dimensional arrays only, so a third size other than 1 is an error, and a class name such as `'int32'` is ignored too: the result is always double.

## Example

```matlab
t = linspace(0, 2, 5);
u = 0.5 * ones(size(t))
```

## See also

[zeros](zeros) · [eye](eye) · [repmat](repmat) · [linspace](linspace) · [size](size)
