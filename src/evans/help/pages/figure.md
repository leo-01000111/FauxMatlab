# figure

Start a new figure window for the plots that follow.

## Syntax

    figure
    figure(n)
    h = figure

## Description

`figure` makes the next plot command open a new figure instead of adding to the current one. It also turns [hold](hold) off and ends any [subplot](subplot) grid, so the next `subplot` call starts a new grid.

`h = figure` returns the number the next figure will get: 1 for the first figure of the command or script, 2 for the second, and so on.

`figure(n)` behaves exactly like `figure`. Evans does not select an existing figure by number, so `figure(1)` after other plots opens a new window rather than going back to figure 1. Name-value pairs such as `'Name', 'Bode'` are accepted and ignored.

You rarely need `figure` between plain plot commands: without `hold on`, each plot already gets a figure of its own. It matters after `hold on` or inside a subplot grid, where the next plot would otherwise land on the existing axes.

## Example

```matlab
G = tf(1, [1 0.4 1]);
step(G); hold on; step(feedback(G, 1))
figure
bode(G)
```

## See also

[plot](plot) · [hold](hold) · [subplot](subplot) · [title](title)
