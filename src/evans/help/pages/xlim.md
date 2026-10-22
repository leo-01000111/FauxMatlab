# xlim

Set the x-axis limits of the current plot.

## Syntax

    xlim([xmin xmax])

## Description

`xlim([xmin xmax])` fixes the horizontal axis to run from `xmin` to `xmax`. The y axis is not affected; use [ylim](ylim) for it, or [axis](axis) for both at once.

The limits apply to line plots, time responses such as [step](step), and [pzmap](pzmap). The Bode, Nyquist and root locus windows choose their own ranges and ignore them. To limit the frequency range of a Bode plot, pass a frequency vector to [bode](bode) instead.

`xlim auto` and other text arguments are accepted and do nothing. Evans does not return the current limits: `xlim` with no argument, or `v = xlim`, is an error.

Call it after the plot command, on the same command line or in the same script.

## Example

```matlab
G = tf(25, [1 4 25]);
step(G); xlim([0 2])
```

## See also

[ylim](ylim) · [axis](axis) · [plot](plot) · [step](step)
