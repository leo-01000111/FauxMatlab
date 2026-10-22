# bode

Bode diagram of a dynamic system: gain in dB and phase in degrees against frequency on a logarithmic axis.

## Syntax

    bode(sys)
    bode(sys, w)
    bode(sys, {wmin, wmax})
    bode(sys1, sys2, ...)
    bode(sys, opts)
    mag = bode(sys)
    [mag, phase, w] = bode(sys, ...)

## Description

`bode(sys)` plots the frequency response of `sys`, a `tf`, `zpk` or `ss` model, as two panels: magnitude in dB and phase in degrees, both against angular frequency in rad/s. The frequency range is chosen from the poles and zeros. For a discrete model it ends at the Nyquist frequency `pi/Ts`, as in MATLAB: above it the response of a sampled system only repeats. No margin markers are drawn; use [margin](margin) for those.

`bode(sys, w)` evaluates the response at the frequencies in the vector `w` (rad/s). `bode(sys, {wmin, wmax})` uses 500 logarithmically spaced points between the two limits.

`bode(sys1, sys2, ...)` draws every system on the same axes, over one frequency range covering all of them. Each curve is labelled with the name of its variable.

`bode(sys, opts)` applies options made with [bodeoptions](bodeoptions). Evans uses the title, the axis limits (`XLim`, `YLim`) and phase matching (`PhaseMatching`, `PhaseMatchingFreq`, `PhaseMatchingValue`). The unit options (`FreqUnits`, `MagUnits`) are accepted and have no effect yet.

With output arguments nothing is drawn. `mag` is the gain as an absolute ratio (not in dB), `phase` is in degrees and `w` in rad/s, each a row vector of the same length. MATLAB returns 1-by-1-by-N arrays here; in Evans you can index them directly. Convert the gain with `20*log10(mag)` to compare with the plot. Ask for outputs one system at a time.

## Example

```matlab
G = tf(10, [1 2 10]);
bode(G)
[mag, phase] = bode(G, [1 3.16 10]);
disp(20*log10(mag))
disp(phase)
```

## See also

[margin](margin) · [nyquist](nyquist) · [nichols](nichols) · [bandwidth](bandwidth) · [bodeoptions](bodeoptions) · [freqresp](freqresp)
