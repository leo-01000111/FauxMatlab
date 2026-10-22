# pzoptions

Create a set of plot options for [pzmap](pzmap), for code written for MATLAB.

## Syntax

    opts = pzoptions
    opts = pzoptions('cstprefs')

## Description

`opts = pzoptions` returns an options object with one property, `Grid` (default `'off'`). Change it with dot assignment and pass the object to the plot, as in `pzmap(G, opts)` or `pzplot(G, opts)`. Property names are case-insensitive, and any argument to `pzoptions` is ignored.

`pzmap` accepts the object so that MATLAB scripts run unchanged, but Evans does not act on it yet: the map is drawn the same with or without it. Use [grid](grid) and [title](title) after the plot instead. Reading a property that does not exist is an error; assigning one adds it without complaint.

## Example

```matlab
G = tf([1 2], [1 2 5]);
opts = pzoptions;
opts.Grid = 'on';
pzmap(G, opts)
grid on
```

## See also

[pzmap](pzmap) · [pole](pole) · [zero](zero) · [bodeoptions](bodeoptions)
