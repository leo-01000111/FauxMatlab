# stepinfo

Rise time, settling time, overshoot and the other numbers that describe a step response.

## Syntax

    S = stepinfo(sys)
    S = stepinfo(y, t)
    S = stepinfo(y)

## Description

`S = stepinfo(sys)` simulates the unit step response of `sys` (a `tf`, `zpk` or `ss` model) and returns a struct with these fields:

- `RiseTime`: time to go from 10 % to 90 % of the final value.
- `SettlingTime`: time after which the response stays within 2 % of the final value. `TransientTime` holds the same number.
- `SettlingMin`, `SettlingMax`: the smallest and largest values after the response has first reached 90 % of the final value.
- `Overshoot`: how far the peak goes past the final value, in percent.
- `Undershoot`: how far the response first goes the wrong way (a right half-plane zero does this), 0 if it never does.
- `Peak`, `PeakTime`: the largest value of the response and when it happens.
- `SteadyState`: the final value.

The simulation runs long enough for the response to settle: if the default time span ends before it has, Evans doubles the span and tries again.

`S = stepinfo(y, t)` computes the same fields from a response you already have, such as the outputs of [step](step) or [lsim](lsim). `y` and `t` are vectors of equal length. `stepinfo(y)` uses the sample index `0, 1, 2, ...` as the time.

Evans uses fixed thresholds (10 to 90 % rise, 2 % settling). After a system, MATLAB's `'SettlingTimeThreshold'` and `'RiseTimeLimits'` options are accepted but ignored; after a data vector they cause an error. A third `yfinal` argument in `stepinfo(y, t, yfinal)` is ignored, and the final value is taken from the data. For an unstable system the fields are not meaningful, where MATLAB returns `NaN`; check [isstable](isstable) first.

## Example

```matlab
G = tf(4, [1 2 4]);
S = stepinfo(G)
fprintf('Overshoot %.1f %%, settles in %.2f s\n', S.Overshoot, S.SettlingTime)
```

## See also

[step](step) · [damp](damp) · [dcgain](dcgain) · [errconst](errconst) · [lsim](lsim)
