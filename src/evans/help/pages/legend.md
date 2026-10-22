# legend

Name the curves on the current axes, in the order they were drawn.

## Syntax

    legend(label1, label2, ...)
    legend({label1, label2, ...})
    legend(..., 'Location', loc)

## Description

`legend('a', 'b')` gives the first curve on the current axes the label `a`, the second `b`, and so on, and the figure shows them in a legend box. The labels can also be passed as one cell array. Extra labels beyond the number of curves are ignored; curves without a label keep the one they had.

A system plot such as [step](step) or [bode](bode) already labels each curve with the system's name, so a legend appears without calling `legend`. Calling it replaces those names. On a Bode plot the labels apply to the magnitude and phase curves together.

Name-value pairs such as `'Location', 'best'` or `'FontSize', 9` are accepted and ignored: Evans places the legend in the upper right corner. `legend off`, `legend hide` and `legend show` are accepted and do nothing.

Call `legend` after all the curves are drawn, on the same command line or in the same script.

## Example

```matlab
G = tf(1, [1 1]);
step(G, feedback(G, 1)); legend('open loop', 'unity feedback')
```

## See also

[plot](plot) · [hold](hold) · [title](title) · [step](step)
