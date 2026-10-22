# length

Length of the largest dimension of an array.

## Syntax

    L = length(A)

## Description

`length(A)` is the larger of the number of rows and the number of columns, or 0 if `A` is empty. For a vector it is the number of elements, whether it is a row or a column.

For a matrix this is rarely what you want: `length(zeros(3, 7))` is 7. Use [size](size) for the rows and columns, or [numel](numel) for the total number of elements.

A common use in control is the order of a transfer function from its denominator: a polynomial with `n + 1` coefficients has degree `n`. For text, `length` counts characters.

## Example

```matlab
num = [1 3];
den = [1 4 6 4];
order = length(den) - 1
relative_degree = length(den) - length(num)
```

## See also

[size](size) · [numel](numel) · [roots](roots) · [tf](tf)
