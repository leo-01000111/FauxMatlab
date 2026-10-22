# allmargin

Every stability margin of an open loop, returned as named fields.

## Syntax

    S = allmargin(sys)

## Description

`S = allmargin(sys)` computes the margins of the open loop `sys` and returns them as a struct, so you read each one by name (`S.PhaseMargin_deg`) instead of by position as with [margin](margin). The fields are:

- `GainMargin_dB`: the gain margin in dB, `Inf` if the phase never crosses -180 degrees.
- `GMFrequency`: the phase crossover frequency in rad/s, where the gain margin is read.
- `PhaseMargin_deg`: the phase margin in degrees, `Inf` if the gain never crosses 0 dB.
- `PMFrequency`: the gain crossover frequency in rad/s, where the phase margin is read.
- `ModulusMargin`: the smallest distance from the Nyquist curve to the point -1. MATLAB's `allmargin` does not report it.
- `MMFrequency`: the frequency at which that smallest distance occurs.
- `DelayMargin`: the extra time delay in seconds the loop tolerates before it loses stability, the phase margin in radians divided by `PMFrequency`.

A missing crossover gives `NaN` for its frequency.

Evans's `allmargin` differs from MATLAB's. MATLAB returns `GainMargin` as a factor, lists every crossover in vectors and adds a `Stable` field; Evans gives one value for each margin (the smallest), with the units in the field names, and has no `Stable` field. At the prompt the struct prints as one line of `name: value` pairs.

## Example

```matlab
s = tf('s');
L = 4 / (s*(s + 1)*(s + 2));
S = allmargin(L);
fprintf('Pm = %.1f deg, Gm = %.2f dB\n', S.PhaseMargin_deg, S.GainMargin_dB)
fprintf('Delay margin: %.3f s\n', S.DelayMargin)
```

## See also

[margin](margin) · [nyquist](nyquist) · [bode](bode) · [feedback](feedback)
