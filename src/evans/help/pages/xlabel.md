# xlabel

Label the x axis of the current axes.

## Syntax

    xlabel(text)

## Description

`xlabel(text)` sets the label under the horizontal axis of the current axes, replacing the one there. A [step](step) plot starts with `Time (s)`, which you can override this way. With a [subplot](subplot) grid it labels the selected cell. Extra arguments after the text are ignored.

Call it after the plot command, on the same command line or in the same script. A plot command without [hold](hold) starts new axes and drops a label set before it.

The y axis has its own function, [ylabel](ylabel).

## Example

```matlab
t = 0:0.01:2;
plot(t, sin(2*pi*t)); xlabel('t (s)'); ylabel('u (V)')
```

## See also

[ylabel](ylabel) · [title](title) · [legend](legend) · [plot](plot)
