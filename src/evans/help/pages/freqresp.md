# freqresp

Frequency response of a continuous-time model at the frequencies you give, as complex numbers.

## Syntax

    H = freqresp(sys, w)

## Description

`H = freqresp(sys, w)` evaluates the transfer function of `sys` at `s = jw` for each frequency in `w`, in rad/s. `H` is a row vector of complex values, one per frequency, so `abs(H)` is the gain and `angle(H)` the phase in radians. `sys` can be a `tf`, `zpk` or `ss` model.

The frequencies must be given. Evans returns one output, a plain row vector: MATLAB returns a 1-by-1-by-N array and can also return the frequency vector as a second output, and neither is supported here. Use it on continuous-time models: for a discrete-time model Evans currently evaluates at `z = jw` instead of on the unit circle, which does not match MATLAB. For one complex point, use [evalfr](evalfr); for magnitude and phase over a sweep, [bode](bode) with output arguments.

## Example

```matlab
G = tf(10, [1 2 10]);
w = logspace(-1, 2, 5);
H = freqresp(G, w);
mag_dB = 20*log10(abs(H))
```

## See also

[evalfr](evalfr) · [bode](bode) · [nyquist](nyquist) · [logspace](logspace)
