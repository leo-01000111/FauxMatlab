# zn

Ziegler-Nichols tuning of a P, PI or PID controller, from the ultimate gain or from the open-loop step response.

## Syntax

    p = zn(G)
    p = zn(G, 'ultimate')
    p = zn(G, 'step')
    p = zn(G, method, 'P')
    p = zn(G, method, 'PI')
    p = zn(G, method, 'PID')

## Description

`p = zn(G)` applies the ultimate-gain (closed-loop oscillation) method to the plant `G` and returns PID gains. Evans finds the ultimate gain `Ku`, where the loop with proportional control sits on the stability boundary, and the period `Tu` of that oscillation, then applies the classic table: P uses `Kp = 0.5*Ku`; PI uses `Kp = 0.45*Ku` and `Ti = 0.833*Tu`; PID uses `Kp = 0.6*Ku`, `Ti = 0.5*Tu` and `Td = 0.125*Tu`. The loop must reach the boundary: a plant of relative degree 1 or 2 with no right-half-plane poles never does, and `zn` stops with an error.

`p = zn(G, 'step')` uses the reaction-curve method instead. The tangent at the inflection point of the open-loop step response gives the apparent dead time `L` and time constant `T`, and with the DC gain `K` the rules are: P uses `Kp = T/(K*L)`; PI uses `Kp = 0.9*T/(K*L)` and `Ti = 3.33*L`; PID uses `Kp = 1.2*T/(K*L)`, `Ti = 2*L` and `Td = 0.5*L`. The method needs a response with an S shape; a first-order lag has no dead time and gives an error.

The third argument picks the controller: `'P'`, `'PI'` or `'PID'` (the default), in capitals. Any method other than `'ultimate'` is treated as `'step'`.

The result is a structure with the parallel-form gains `p.Kp`, `p.Ki = Kp/Ti` and `p.Kd = Kp*Td`, plus `p.Tf`, which is 0. Pass the gains to [pid](pid) to get the controller as a transfer function. `zn` is Evans's own command; MATLAB has no function of that name.

## Example

```matlab
G = tf(1, [1 3 3 1]);
p = zn(G);
fprintf('Kp = %.2f, Ki = %.2f, Kd = %.2f\n', p.Kp, p.Ki, p.Kd)
C = pid(p.Kp, p.Ki, p.Kd);
step(feedback(C*G, 1))
```

## See also

[pid](pid) · [pidtune](pidtune) · [margin](margin) · [rlocus](rlocus) · [step](step)
