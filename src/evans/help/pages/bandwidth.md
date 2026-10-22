# bandwidth

Bandwidth of a system: the first frequency at which its gain falls 3 dB below the DC gain.

## Syntax

    fb = bandwidth(sys)
    fb = bandwidth(sys, dbdrop)

## Description

`fb = bandwidth(sys)` returns, in rad/s, the lowest frequency at which the gain of `sys` has dropped 3 dB below its DC gain, which is about 70.7 % of [dcgain](dcgain). The crossing is found on a dense frequency grid and then refined, so the value is exact to many digits. The system can be a `tf`, `zpk` or `ss` model, continuous or discrete; for a discrete model the search stops at the Nyquist frequency `pi/Ts`.

`fb = bandwidth(sys, dbdrop)` uses a different drop, in dB. `dbdrop` must be negative (`-6` for half the amplitude); a positive value is an error.

The result is `Inf` if the gain never falls that far, and `NaN` if the DC gain is infinite or zero (an integrator or a differentiator), since there is nothing to measure from.

`bandwidth` measures the system you pass. For the bandwidth of a control loop, pass the closed loop: `bandwidth(feedback(L, 1))`, not `L`.

## Example

```matlab
G = tf(4, [1 2 4]);
bandwidth(G)
L = tf(10, [1 1]);
wb = bandwidth(feedback(L, 1))
```

## See also

[bode](bode) · [dcgain](dcgain) · [margin](margin) · [feedback](feedback) · [freqresp](freqresp)
