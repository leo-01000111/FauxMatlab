# c2d

Discretises a continuous-time model with sample time Ts, giving the discrete-time model a digital controller or a sampled plant works with.

## Syntax

    sysd = c2d(sys, Ts)
    sysd = c2d(sys, Ts, method)
    sysd = c2d(sys, Ts, 'tustin', wp)

## Description

`c2d(sys, Ts)` samples the continuous model `sys` every `Ts` seconds with a zero-order hold (`'zoh'`), which models a D/A converter holding each value for one period. It is exact for piecewise-constant inputs. `Ts` must be positive.

`c2d(sys, Ts, method)` picks the discretisation method:

- `'zoh'`: zero-order hold, the default.
- `'tustin'` or `'bilinear'`: the bilinear map from s to z. It maps the left half-plane into the unit disc, so a stable model stays stable, but the frequency axis is warped.
- `'euler'`: forward Euler, `s = (z - 1)/Ts`.
- `'backward_diff'`: backward Euler, `s = (z - 1)/(Ts z)`.
- `'matched'`: matched pole-zero mapping, `z = exp(s Ts)` for every pole and zero.

`c2d(sys, Ts, 'tustin', wp)` prewarps the bilinear map so the discrete response matches the continuous one exactly at the frequency `wp` in rad/s. MATLAB sets this through `c2dOptions`; Evans takes it as the fourth argument. The methods `'foh'`, `'impulse'` and `'least-squares'` are not supported.

A `tf` or `zpk` model comes back as a discrete `tf`, an `ss` model as a discrete `ss`, with the sample time stored in the model. To simulate a discrete model with [step](step) or [impulse](impulse), give a time vector whose step is `Ts`. [d2c](d2c) goes the other way.

## Example

```matlab
G = tf(1, [1 1]);
Gd = c2d(G, 0.1)
step(G, Gd, 0:0.1:5)
pole(Gd)
```

## See also

[d2c](d2c) · [deadbeat](deadbeat) · [jury](jury) · [step](step) · [pzmap](pzmap)
