# s, the Laplace variable

At the Evans console `s` is already defined as the transfer function `s/1`, so you can write a model the way it appears on paper.

## Building models from s

When a console session starts, `s` holds the continuous-time transfer function whose numerator is `s` and whose denominator is 1, the same object `tf('s')` makes. Scripts run in the console's workspace, so they see it too. Arithmetic on it gives transfer functions: `+`, `-`, `*` and `/` combine models and numbers, and `^` takes an integer power, negative ones included (`s^-1` is an integrator).

    G = 1/(s^2 + 2*s + 1)
    C = 2*(s + 1)/s
    L = C*G

Products and quotients are multiplied out, so `5*(s + 2)/(s*(s + 1))` prints with expanded polynomials. Use [zpk](zpk) if you want to keep the factored form, and [minreal](minreal) to cancel a common factor between numerator and denominator.

A time delay cannot be written as `exp(-s*T)`: the exponential of a transfer function is not defined in Evans. Approximate the delay with [pade](pade) instead.

## s in MATLAB scripts

MATLAB has no predefined `s`; a MATLAB script starts with `s = tf('s');`. That line works in Evans as well and does no harm, so keep it in scripts you want to run in both. For a discrete-time model the same idea works with `z = tf('z', Ts)`, where `Ts` is the sample time in seconds. Evans does not predefine `z`.

## Overwriting s

`s` is an ordinary variable. `s = 5`, or a loop variable called `s`, replaces it, and from then on `1/(s + 1)` is a number instead of a transfer function. `clear` on its own leaves `s` as it is, and `clear s` removes it altogether. In either case `s = tf('s')` brings it back.

## Example

```matlab
G = 1/(s^2 + 2*s + 1)
C = 4*(s + 2)/s;
T = feedback(C*G, 1);
pole(T)
```

```matlab
s = tf('s');
H = (s + 3)/(s*(s + 1)*(s + 5))
Kv = dcgain(minreal(s*H))
```

## See also

[tf](tf) · [zpk](zpk) · [feedback](feedback) · [pade](pade) · [python](python)
