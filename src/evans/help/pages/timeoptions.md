# timeoptions

Create a set of plot options for [step](step) and [impulse](impulse): the title and the axis limits.

## Syntax

    opts = timeoptions
    opts = timeoptions('cstprefs')

## Description

`opts = timeoptions` returns an options object with MATLAB's property names and defaults. Change a property with dot assignment (`opts.XLim = [0 10]`) and pass the object to the plot, as in `step(G, opts)` or `impulse(G, 5, opts)`. Property names are case-insensitive. Any argument, such as `'cstprefs'`, is accepted and ignored: you always get the defaults. `stepDataOptions` returns the same object.

Evans acts on these properties:

- `Title`: the plot title, used when you change it from the default `'Step Response'`.
- `XLim`, `YLim`: two-element vectors that fix the axis limits. Setting `XLim` does not change how long the response is simulated; pass a final time to `step` for that.

The object also lists `XLabel`, `YLabel` and `Grid`, so code written for MATLAB runs, but Evans does not act on them. Use [xlabel](xlabel), [ylabel](ylabel) and [grid](grid) after the plot instead. Reading a property that does not exist is an error; assigning one adds it without complaint, so check the spelling.

With output arguments (`y = step(G, opts)`) nothing is drawn and the options have no effect.

## Example

```matlab
G = tf(4, [1 2 4]);
opts = timeoptions;
opts.Title = 'Closed-loop step';
opts.YLim = [0 1.4];
step(G, opts)
```

## See also

[step](step) · [impulse](impulse) · [bodeoptions](bodeoptions) · [stepinfo](stepinfo)
