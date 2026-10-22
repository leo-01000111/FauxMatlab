# linspace

Row vector of evenly spaced points between two end values, both included.

## Syntax

    y = linspace(a, b)
    y = linspace(a, b, n)

## Description

`linspace(a, b, n)` returns a row vector of `n` points, the first equal to `a` and the last equal to `b`, with spacing `(b - a)/(n - 1)`. Without `n` you get 100 points.

Use it to build a time vector for a simulation, or any grid where you care about the number of points rather than the step. The colon operator `a:h:b` fixes the step instead, and may stop short of `b`.

For points spread evenly on a logarithmic scale, as frequency grids are, use [logspace](logspace).

## Example

```matlab
t = linspace(0, 5, 6)
```

```matlab
G = tf(1, [1 2 1]);
t = linspace(0, 10, 501);
y = step(G, t);
fprintf('%d samples, y(end) = %.4f\n', numel(y), y(end))
```

## See also

[logspace](logspace) · [step](step) · [lsim](lsim) · [plot](plot) · [zeros](zeros)
