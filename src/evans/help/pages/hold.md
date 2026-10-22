# hold

Keep the current plot so that the next plot commands add to it instead of replacing it.

## Syntax

    hold on
    hold off
    hold
    hold(state)

## Description

`hold on` makes later plot commands draw onto the current axes. `hold off` returns to the default, where each plot command starts a new figure. `hold` with no argument toggles between the two. `hold all` is the same as `hold on`, and the function form `hold('on')` works as well.

Plots are only combined when they are of the same kind: two [plot](plot) calls, or two [step](step) calls, share axes, but a `step` after a `plot` opens a figure of its own even with hold on. To compare responses of several systems, `step(G1, G2)` and `bode(G1, G2)` already draw them on one set of axes.

The hold state belongs to the current axes. [figure](figure) turns it off, and inside a [subplot](subplot) grid each cell keeps its own.

At the console, hold lasts only as long as the command you entered: `hold on` typed alone at the prompt has no effect on the next line. Write the plots and the `hold on` between them on one line, separated by `;`, or put them in a script.

Curves added with hold are labelled one by one, so the default legend can repeat a name. Call [legend](legend) afterwards to set the labels.

## Example

```matlab
G = tf(1, [1 1 1]);
step(G); hold on; step(feedback(5*G, 1)); hold off
legend('open loop', 'closed loop, K = 5')
```

## See also

[figure](figure) · [subplot](subplot) · [plot](plot) · [legend](legend)
