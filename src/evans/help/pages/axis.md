# axis

Set the limits of both axes of the current plot in one call.

## Syntax

    axis([xmin xmax ymin ymax])
    axis([xmin xmax])

## Description

`axis([xmin xmax ymin ymax])` fixes the x axis to run from `xmin` to `xmax` and the y axis from `ymin` to `ymax`. With only two elements, only the x limits are set and the y axis keeps scaling to the data. It is the same as calling [xlim](xlim) and [ylim](ylim) together.

The limits apply to line plots, time responses such as [step](step), and [pzmap](pzmap). The Bode, Nyquist and root locus windows choose their own ranges and ignore them.

The text forms MATLAB has (`axis equal`, `axis tight`, `axis off`, `axis auto` and so on) are accepted so that scripts run, but they do nothing in Evans.

Call `axis` after the plot command, on the same command line or in the same script.

## Example

```matlab
G = tf(1, [1 0.3 1]);
step(G); axis([0 20 0 2])
```

## See also

[xlim](xlim) · [ylim](ylim) · [plot](plot) · [grid](grid)
