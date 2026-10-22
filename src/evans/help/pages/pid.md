# pid

PID controller as a transfer function, with an optional first-order filter on the derivative term.

## Syntax

    C = pid(Kp)
    C = pid(Kp, Ki)
    C = pid(Kp, Ki, Kd)
    C = pid(Kp, Ki, Kd, Tf)

## Description

`C = pid(Kp, Ki, Kd, Tf)` returns the parallel-form controller `Kp + Ki/s + Kd*s/(Tf*s + 1)`. Arguments left out are zero, so `pid(Kp)` is a pure gain, `pid(Kp, Ki)` a PI controller and `pid(Kp, Ki, Kd)` an ideal PID `(Kd s^2 + Kp s + Ki)/s`. `Tf` is the time constant of the derivative filter; a small positive value keeps the controller proper and limits its high-frequency gain.

The result is an ordinary transfer function. MATLAB returns a `pid` object with fields such as `C.Kp`; Evans has no such object, so keep the gains in variables of your own.

Close the loop with [feedback](feedback): `T = feedback(C*G, 1)`. To pick the gains, [zn](zn) gives Ziegler-Nichols values and [pidtune](pidtune) opens an interactive tuner.

## Example

```matlab
G = tf(1, [1 3 2]);
C = pid(10, 8, 1, 0.01);
T = feedback(C*G, 1);
step(T)
info = stepinfo(T);
fprintf('Settling time: %.2f s\n', info.SettlingTime)
```

## See also

[feedback](feedback) · [zn](zn) · [pidtune](pidtune) · [lead](lead) · [lag](lag) · [stepinfo](stepinfo)
