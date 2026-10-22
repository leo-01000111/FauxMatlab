# ylim

Set the y-axis limits of the current plot.

## Syntax

    ylim([ymin ymax])

## Description

`ylim([ymin ymax])` fixes the vertical axis to run from `ymin` to `ymax`. The x axis is not affected; use [xlim](xlim) for it, or [axis](axis) for both at once.

The limits apply to line plots, time responses such as [step](step), and [pzmap](pzmap). The Bode, Nyquist and root locus windows choose their own ranges and ignore them.

`ylim auto` and other text arguments are accepted and do nothing. Evans does not return the current limits: `ylim` with no argument, or `v = ylim`, is an error.

Call it after the plot command, on the same command line or in the same script.

## Example

```matlab
G = tf(1, [1 0.2 1]);
step(G); ylim([0 2])
```

## See also

[xlim](xlim) · [axis](axis) · [plot](plot) · [step](step)
