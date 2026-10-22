# subplot

Divide a figure into a grid of axes and select one of them for the next plot.

## Syntax

    subplot(m, n, p)
    subplot(mnp)
    subplot(m, n, [p1 p2])

## Description

`subplot(m, n, p)` splits the figure into `m` rows and `n` columns of axes and makes cell `p` the current one. Cells are numbered along the rows, left to right and then top to bottom, from 1 to `m*n`. The next plot command, and any [title](title), [xlabel](xlabel), [legend](legend) or [xlim](xlim) after it, applies to that cell.

`subplot(mnp)` is the three-digit shorthand: `subplot(212)` is `subplot(2, 1, 2)`. It only works when `m`, `n` and `p` are single digits.

`subplot(m, n, [p1 p2])` makes one set of axes span several cells, for example `subplot(2, 2, [3 4])` for a wide plot across the bottom row. Grids of different sizes can be mixed in one figure.

Selecting a cell that already holds a plot and plotting again replaces what was there, unless [hold](hold) is on for that cell. Each cell remembers its own hold state.

An index outside the grid is an error (`Index exceeds number of subplots`). Call [figure](figure) to start a fresh grid in a new window.

Any plot command can go in a cell, including [step](step), [bode](bode) and [plot](plot).

## Example

```matlab
G = tf(4, [1 2 4]);
subplot(2, 1, 1); step(G); title('Step')
subplot(2, 1, 2); impulse(G); title('Impulse')
```

## See also

[figure](figure) · [plot](plot) · [hold](hold) · [title](title)
