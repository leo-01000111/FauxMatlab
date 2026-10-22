# numel

Total number of elements in an array.

## Syntax

    N = numel(A)

## Description

`numel(A)` is the number of rows times the number of columns. For a vector it equals [length](length); for a matrix it counts every entry, so `numel(zeros(3, 7))` is 21. An empty array gives 0, and text gives its number of characters.

For a model, `numel` is outputs times inputs, so a SISO [tf](tf) gives 1.

## Example

```matlab
G = tf(1, [1 2 1]);
t = linspace(0, 10, 501);
y = step(G, t);
fprintf('%d samples\n', numel(y))
```

## See also

[size](size) · [length](length) · [reshape](reshape) · [sum](sum)
