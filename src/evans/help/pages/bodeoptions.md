# bodeoptions

Create a set of plot options for [bode](bode): the title, the axis limits and phase matching.

## Syntax

    opts = bodeoptions
    opts = bodeoptions('cstprefs')

## Description

`opts = bodeoptions` returns an options object with MATLAB's property names and defaults. Change a property with dot assignment (`opts.Title = 'Open loop'`) and pass the object to `bode`, as in `bode(G, opts)` or `bode(G, w, opts)`. Property names are case-insensitive. Any argument, such as `'cstprefs'`, is accepted and ignored: you always get the defaults.

Evans acts on these properties:

- `Title`: the plot title, used when you change it from the default.
- `XLim`, `YLim`: two-element vectors that fix the axis limits.
- `PhaseMatching`: set to `'on'` to shift the phase curve by whole multiples of 360 degrees so that at `PhaseMatchingFreq` (rad/s) it lies closest to `PhaseMatchingValue` (degrees). With `PhaseMatchingFreq` left at 0 the curve is matched at its lowest frequency. This also applies to the phase returned by `[mag, phase] = bode(G, w, opts)`.

The object also lists `XLabel`, `YLabel`, `Grid`, `FreqUnits`, `FreqScale`, `MagUnits`, `MagScale`, `MagVisible`, `PhaseUnits`, `PhaseVisible` and `PhaseWrapping`, so code written for MATLAB runs, but Evans does not act on them: the Bode plot is always in rad/s, dB and degrees on a log frequency axis. Use [grid](grid) after the plot to turn the grid on. Reading a property that does not exist is an error; assigning one adds it without complaint, so check the spelling.

`opts` displays as a list of every property and its value.

## Example

```matlab
G = tf(1, [1 1 0]);
opts = bodeoptions;
opts.Title = 'Open loop L(s)';
opts.PhaseMatching = 'on';
opts.PhaseMatchingFreq = 1;
opts.PhaseMatchingValue = 180;
bode(G, opts)
```

## See also

[bode](bode) · [timeoptions](timeoptions) · [nyquistoptions](nyquistoptions) · [pzoptions](pzoptions) · [margin](margin)
