# rand

Uniformly distributed random numbers between 0 and 1.

## Syntax

    r = rand
    R = rand(n)
    R = rand(m, n)
    R = rand([m n])

## Description

`rand` with no argument is one random scalar. `rand(n)` is an n-by-n matrix of them, and `rand(m, n)` or `rand([m n])` an m-by-n matrix. Every value is drawn independently and uniformly from the interval [0, 1): 0 can occur, 1 cannot.

For another interval, scale and shift: `a + (b - a) * rand(1, 100)` is uniform between `a` and `b`. For normally distributed numbers, as for measurement noise, use `randn` with the same arguments.

The values differ every time you run. Evans has no `rng` function, so you cannot seed the generator to repeat a sequence, and a class name such as `'single'` is ignored. As with [zeros](zeros), only two-dimensional arrays are made.

## Example

```matlab
noise = 0.05 * rand(1, 200);
size(noise)
fprintf('All samples in [0, 0.05): %d\n', all(noise >= 0 & noise < 0.05))
```

## See also

[zeros](zeros) · [ones](ones) · [size](size) · [mean](mean) · [max](max)
