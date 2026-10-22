# ylabel

Label the y axis of the current axes.

## Syntax

    ylabel(text)

## Description

`ylabel(text)` sets the label beside the vertical axis of the current axes, replacing the one there (`Amplitude` on a [step](step) plot, for instance). With a [subplot](subplot) grid it labels the selected cell. Extra arguments after the text are ignored.

Call it after the plot command, on the same command line or in the same script. A plot command without [hold](hold) starts new axes and drops a label set before it.

The x axis has its own function, [xlabel](xlabel).

## Example

```matlab
G = tf(1, [0.5 1]);
[y, t] = step(G);
plot(t, 100*y); xlabel('t (s)'); ylabel('Speed (% of final)')
```

## See also

[xlabel](xlabel) · [title](title) · [legend](legend) · [plot](plot)
