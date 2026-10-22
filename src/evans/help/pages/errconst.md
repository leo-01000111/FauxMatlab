# errconst

Static error constants and steady-state errors of a unity-feedback loop, from its open-loop transfer function.

## Syntax

    e = errconst(L)

## Description

`e = errconst(L)` takes the open loop `L` (a `tf`, `zpk` or `ss` model, continuous or discrete) of a loop closed with unity negative feedback and returns a struct with these fields:

- `Type`: the system type, the number of poles of `L` at the origin.
- `Kp`: the position constant, the limit of `L(s)` as `s` goes to 0.
- `Kv`: the velocity constant, the limit of `s L(s)`.
- `Ka`: the acceleration constant, the limit of `s^2 L(s)`.
- `ess_step`: the steady-state error to a unit step, `1/(1 + Kp)`.
- `ess_ramp`: the steady-state error to a unit ramp, `1/Kv`.
- `ess_parabola`: the error to a unit parabola `t^2/2`, `1/Ka`.

A constant is `Inf` when the loop has more integrators than it needs, and the matching error is then 0. These errors are only reached if the closed loop is stable; check `feedback(L, 1)` with [isstable](isstable) first.

At the prompt the struct prints as one line of `name: value` pairs; read single values with a dot, as in `e.Kv`. For a discrete loop with sample time `Ts`, the type counts poles at `z = 1`, and the constants are the discrete limits as `z` goes to 1: `Kp = L(1)`, `Kv` the limit of `(z-1) L(z)/Ts`, `Ka` the limit of `(z-1)^2 L(z)/Ts^2`. The errors keep the same formulas, for samples of the unit step, ramp and parabola. `errconst` is not a MATLAB function.

## Example

```matlab
L = tf(10, [1 3 2 0]);
e = errconst(L);
fprintf('Type %d, Kv = %g, ramp error = %g\n', e.Type, e.Kv, e.ess_ramp)
```

## See also

[dcgain](dcgain) · [stepinfo](stepinfo) · [feedback](feedback) · [ramp](ramp) · [isstable](isstable)
