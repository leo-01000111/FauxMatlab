# tf

Transfer function model from numerator and denominator polynomials, or the Laplace variable `s` for writing one as an expression.

## Syntax

    G = tf(num, den)
    G = tf(num, den, Ts)
    G = tf(num, den, 'Ts', Ts)
    s = tf('s')
    z = tf('z', Ts)
    G = tf(sys)

## Description

`G = tf(num, den)` builds the continuous-time transfer function `num(s)/den(s)`. `num` and `den` are row vectors of coefficients in descending powers of `s`, so `tf([1 3], [1 2 1])` is `(s + 3)/(s^2 + 2s + 1)`. The model is displayed as a ratio of polynomials.

`G = tf(num, den, Ts)` builds a discrete-time transfer function in `z` with sample time `Ts` seconds; the sample time can also be given as the property `'Ts'`.

`s = tf('s')` returns the Laplace variable, so a transfer function can be written the way it is written on paper: `G = 4/(s^2 + 2*s + 4)`. In Evans `s` is already defined when a console or script starts, so the line is optional; see [s](s). `z = tf('z', Ts)` does the same for a discrete-time model with sample time `Ts`.

`G = tf(sys)` converts a state-space model to a transfer function, as [ss2tf](ss2tf) does. Round-off from the conversion can leave a tiny coefficient such as `8.9e-16 s` in the numerator.

Evans does not support `tf(K)` for a static gain (write `tf(K, 1)`). It has no exact time delays, so `tf(num, den, 'InputDelay', T)` (or `'OutputDelay'`, `'IODelay'`) stops with an error rather than drop the delay; multiply by a Padé approximation instead, `G*pade(T, 3)`, see [pade](pade). Naming properties such as `'Name'` are accepted and change nothing; an unknown property is an error.

To read the coefficients back as vectors, use [tfdata](tfdata).

## Example

```matlab
G = tf([1 3], [1 2 1])
H = 4/(s^2 + 2*s + 4)
step(G, H)
```

## See also

[s](s) · [zpk](zpk) · [ss](ss) · [tfdata](tfdata) · [feedback](feedback) · [minreal](minreal)
