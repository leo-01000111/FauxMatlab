# pidtune

Tune a P, PI, PD or PID controller for a plant by loop shaping: pick a crossover frequency and a phase margin, and solve for the gains that put the open loop there.

## Syntax

    C = pidtune(G)
    C = pidtune(G, type)
    C = pidtune(G, type, wc)
    C = pidtune(G, type, wc, pm)
    C = pidtune(G, type, wc, pm, Tf)

## Description

`C = pidtune(G)` tunes a PI controller for the plant `G`, aiming for a 60 degree phase margin. `C` is returned as a transfer function, so it composes with the rest of the toolbox: `feedback(C*G, 1)` is the closed loop.

`pidtune(G, type)` chooses the controller: `'P'`, `'PI'`, `'PD'` or `'PID'`, in either case. Evans has no `'PIDF'` or two-degree-of-freedom types; for a filtered derivative pass `Tf` instead.

`pidtune(G, type, wc)` sets the target crossover frequency `wc` in rad/s. Without it, Evans picks the frequency where the plant's own phase leaves the controller the least work to do for the target margin.

`pidtune(G, type, wc, pm)` sets the target phase margin `pm` in degrees (default 60). This argument belongs to Evans: MATLAB's fourth argument is an options object, which Evans does not support.

`pidtune(G, type, wc, pm, Tf)` adds a first-order filter with time constant `Tf` to the derivative term of a PD or PID. The filter is added after the gains are solved, so the achieved margin moves a little from the target.

The gains come from the plant's gain and phase at `wc`: the controller must supply exactly the gain and phase that put the open loop `C*G` at 0 dB with the requested margin. When a controller of the chosen type cannot supply that phase (a PI only ever subtracts phase, for example), `pidtune` stops with an error that says why and what to change, instead of returning gains that miss the target.

The full report is attached to the result as `C.tuning`. `disp(C.tuning.describe())` prints the gains, the target and achieved crossover and phase margin, the gain margin, and the overshoot, rise time and settling time of the unity-feedback step response. Single values are fields: `C.tuning.params.Kp`, `C.tuning.params.Ki`, `C.tuning.params.Kd`, `C.tuning.achieved_wc`, `C.tuning.achieved_pm_deg`. MATLAB's second output `info` is not supported.

For the same design with sliders and live plots, open the [pidtuner](pidtuner) app.

## Example

```matlab
G = tf(1, [1 3 3 1]);
C = pidtune(G, 'pid', 1, 45);
disp(C.tuning.describe())
T = feedback(C*G, 1);
step(T)
```

## See also

[pidtuner](pidtuner) · [pid](pid) · [zn](zn) · [margin](margin) · [feedback](feedback) · [stepinfo](stepinfo)
