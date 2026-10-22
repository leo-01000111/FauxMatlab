# plot

Line plot of data: one or more y vectors against x, on linear axes.

## Syntax

    plot(y)
    plot(x, y)
    plot(x, y, spec)
    plot(x1, y1, spec1, x2, y2, spec2, ...)

## Description

`plot(x, y)` draws `y` against `x`. The two must have the same number of elements. If `y` is a matrix, each column is drawn as its own line against `x` (or each row, when the rows match the length of `x`).

`plot(y)` draws `y` against its index, `1:length(y)`. A complex `y` on its own is drawn as its imaginary part against its real part. When `x` and `y` are both given and one of them is complex, the imaginary parts are dropped with a warning.

`spec` is a MATLAB line specification such as `'--'`, `'r:'` or `'o'`. Evans reads only the line style from it: `--`, `:` and `-.` give a dashed line, a marker with no line (`'o'`, `'x'`, `'.'`) gives unconnected points, anything else a solid line. Colours come from the theme's colour cycle, so the colour letter is accepted and ignored. Name-value pairs such as `'LineWidth', 2` are accepted and ignored too.

Several `x, y` pairs in one call draw several lines on the same axes. Without [hold](hold), each `plot` starts a fresh figure.

At the console, a figure is drawn when the command you entered finishes, and the next command starts afresh. Put [hold](hold), [title](title), [legend](legend) and the other annotations on the same line as the plot, separated by `;`, or run them together as a script. In MATLAB you can type them on later lines; in Evans a later line does not reach the earlier figure.

For a logarithmic frequency axis use [semilogx](semilogx). To plot a model's response, call [step](step) or [bode](bode) directly; `[y, t] = step(G)` followed by `plot(t, y)` gives the same curve when you need to combine it with other data.

## Example

```matlab
t = linspace(0, 10, 200);
y1 = 1 - exp(-t);
y2 = 1 - exp(-0.5*t);
plot(t, y1, t, y2, '--'); legend('tau = 1', 'tau = 2'); xlabel('t (s)')
```

## See also

[semilogx](semilogx) · [hold](hold) · [figure](figure) · [subplot](subplot) · [legend](legend) · [step](step)
