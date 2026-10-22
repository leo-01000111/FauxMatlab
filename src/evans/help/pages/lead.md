# lead

Lead compensator `K*(tau*s + 1)/(alpha*tau*s + 1)` with `alpha < 1`, for adding phase near the crossover frequency.

## Syntax

    C = lead(K, alpha, tau)
    C = lead(K, alpha)
    C = lead(K)
    C = lead()

## Description

`C = lead(K, alpha, tau)` returns `K*(tau*s + 1)/(alpha*tau*s + 1)`. The zero is at `-1/tau` and the pole at `-1/(alpha*tau)`, further left because `alpha` lies between 0 and 1. The compensator adds phase between the two corner frequencies, most of it at `w = 1/(tau*sqrt(alpha))`, where it adds `asin((1 - alpha)/(1 + alpha))`. Its gain is `K` at low frequency and `K/alpha` at high frequency.

To raise the phase margin, put the maximum phase at the new crossover frequency, then adjust `K` so the loop gain there is 1. Check the result with [margin](margin).

Arguments left out take the defaults `K = 1`, `alpha = 0.1`, `tau = 1`. An `alpha` of 1 or more is an error; that shape is a [lag](lag) compensator.

`lead` is part of Evans and has no counterpart in MATLAB's Control System Toolbox, so scripts that use it will not run in MATLAB. There, write the same compensator with [tf](tf).

## Example

```matlab
G = tf(10, [1 1 0]);
C = lead(1, 0.1, 0.3);
[Gm, Pm] = margin(G);
[Gm2, Pm2] = margin(C*G);
fprintf('Phase margin: %.1f deg, with lead %.1f deg\n', Pm, Pm2)
```

## See also

[lag](lag) · [pid](pid) · [margin](margin) · [bode](bode) · [sisotool](sisotool)
