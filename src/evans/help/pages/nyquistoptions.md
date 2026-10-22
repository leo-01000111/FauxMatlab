# nyquistoptions

Create a set of plot options for [nyquist](nyquist), for code written for MATLAB.

## Syntax

    opts = nyquistoptions
    opts = nyquistoptions('cstprefs')

## Description

`opts = nyquistoptions` returns an options object with the properties `Grid` (default `'off'`) and `ShowFullContour` (default `'on'`). Change a property with dot assignment and pass the object to `nyquist`, as in `nyquist(G, opts)`. Property names are case-insensitive, and any argument to `nyquistoptions` is ignored.

`nyquist` accepts the object so that MATLAB scripts run unchanged, but Evans does not act on any of its properties yet: the plot is drawn the same with or without it. Use [grid](grid) and [title](title) after the plot instead. Reading a property that does not exist is an error; assigning one adds it without complaint.

## Example

```matlab
L = tf(2, [1 2 2 0]);
opts = nyquistoptions;
opts.ShowFullContour = 'on';
nyquist(L, opts)
title('Nyquist plot of L(s)')
```

## See also

[nyquist](nyquist) · [bodeoptions](bodeoptions) · [pzoptions](pzoptions) · [margin](margin)
