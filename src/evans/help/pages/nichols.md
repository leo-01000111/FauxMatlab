# nichols

Nichols chart of an open-loop transfer function: gain in dB plotted against phase in degrees, one point per frequency.

## Syntax

    nichols(sys)
    nichols(sys, w)
    nichols(sys, {wmin, wmax})
    nichols(sys1, sys2, ...)

## Description

`nichols(sys)` plots the open-loop frequency response of a `tf`, `zpk` or `ss` model with phase in degrees on the horizontal axis and gain in dB on the vertical one. The critical point sits at (-180°, 0 dB): the horizontal distance from it where the curve crosses 0 dB is the phase margin, and the vertical distance where it crosses -180° is the gain margin.

`nichols(sys, w)` evaluates at the frequencies in `w` (rad/s), and `nichols(sys, {wmin, wmax})` at 500 logarithmically spaced points between the limits. `nichols(sys1, sys2, ...)` overlays several systems.

Evans draws the open-loop curve only, without MATLAB's grid of closed-loop gain and phase contours. `nichols` returns no data: with an output argument it draws nothing and returns an empty value. Use [bode](bode) with output arguments for the numbers, since they are the same gain and phase.

## Example

```matlab
L = tf(20, [1 6 5 0]);
nichols(L)
[gm, pm] = margin(L);
fprintf('Gain margin %.2f dB, phase margin %.1f deg\n', 20*log10(gm), pm)
```

## See also

[bode](bode) · [nyquist](nyquist) · [margin](margin) · [allmargin](allmargin)
