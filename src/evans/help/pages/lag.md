# lag

Lag compensator `K*(tau*s + 1)/(alpha*tau*s + 1)` with `alpha > 1`, for raising the low-frequency gain.

## Syntax

    C = lag(K, alpha, tau)
    C = lag(K, alpha)
    C = lag(K)
    C = lag()

## Description

`C = lag(K, alpha, tau)` returns `K*(tau*s + 1)/(alpha*tau*s + 1)`. With `alpha > 1` the pole at `-1/(alpha*tau)` lies closer to the origin than the zero at `-1/tau`. The gain is `K` at low frequency and falls to `K/alpha` above the zero, so relative to high frequency the loop gains a factor `alpha` at DC. That reduces steady-state error while changing the response near crossover little, provided the zero sits well below the crossover frequency (a decade is the usual rule).

The compensator takes away some phase between its corner frequencies. Placing `1/tau` far below crossover keeps that loss away from the phase margin.

Arguments left out take the defaults `K = 1`, `alpha = 10`, `tau = 1`. An `alpha` of 1 or less is an error; that shape is a [lead](lead) compensator.

`lag` is part of Evans and has no counterpart in MATLAB's Control System Toolbox, so scripts that use it will not run in MATLAB. There, write the same compensator with [tf](tf).

## Example

```matlab
G = tf(1, [1 3 2]);
C = lag(10, 10, 5);
fprintf('DC gain: %.2f, with lag %.2f\n', dcgain(G), dcgain(C*G))
bode(G, C*G)
```

## See also

[lead](lead) · [pid](pid) · [errconst](errconst) · [dcgain](dcgain) · [bode](bode)
