# margin

Gain margin, phase margin and the two crossover frequencies of an open loop.

## Syntax

    margin(sys)
    Gm = margin(sys)
    [Gm, Pm, Wcg, Wcp] = margin(sys)

## Description

`margin(sys)` with no output draws the Bode plot of the open loop `sys`, puts the margins in the plot title, and prints the same line in the console: the gain margin in dB with the frequency where it is measured, and the phase margin in degrees with its frequency.

`[Gm, Pm, Wcg, Wcp] = margin(sys)` returns the numbers and draws nothing:

- `Gm`: the gain margin as a plain factor (not in dB). `20*log10(Gm)` gives dB.
- `Pm`: the phase margin in degrees.
- `Wcg`: the phase crossover frequency in rad/s, where the phase is -180 degrees and `Gm` is read.
- `Wcp`: the gain crossover frequency in rad/s, where the gain is 1 (0 dB) and `Pm` is read.

The order follows MATLAB, and it trips people up: the frequency of the gain margin comes before that of the phase margin. If you would rather read margins by name, use [allmargin](allmargin).

Pass the open loop `L = C*G`, not the closed loop. With unity feedback, positive margins mean the closed loop `feedback(L, 1)` is stable, provided `L` itself has no poles in the right half-plane. When a crossover does not exist the margin is `Inf` and its frequency `NaN`.

Evans does not support MATLAB's `margin(mag, phase, w)` form on frequency-response data. With several systems only the first is used.

## Example

```matlab
s = tf('s');
L = 4 / (s*(s + 1)*(s + 2));
[Gm, Pm, Wcg, Wcp] = margin(L);
fprintf('Gm = %.2f dB at %.3f rad/s\n', 20*log10(Gm), Wcg)
fprintf('Pm = %.1f deg at %.3f rad/s\n', Pm, Wcp)
margin(L)
```

## See also

[allmargin](allmargin) · [bode](bode) · [nyquist](nyquist) · [feedback](feedback) · [bandwidth](bandwidth)
