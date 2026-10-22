# zpk

Transfer function model from its zeros, poles and gain.

## Syntax

    G = zpk(z, p, k)
    G = zpk(sys)

## Description

`G = zpk(z, p, k)` builds the transfer function `k*(s - z1)*(s - z2).../((s - p1)*(s - p2)...)`. `z` and `p` are vectors of zeros and poles, `[]` for none, and `k` is the gain multiplying the polynomials (it is not the DC gain). Complex zeros and poles must come in conjugate pairs, as in `[-1+2i -1-2i]`, so that the coefficients are real.

`G = zpk(sys)` returns `sys` unchanged.

Evans builds an ordinary transfer function and displays it in expanded polynomial form, where MATLAB shows the factors. Use [pole](pole), [zero](zero) or [zpkdata](zpkdata) to read the factors back. Evans does not support a sample time argument: `zpk(z, p, k, Ts)` ignores `Ts` and returns a continuous-time model.

## Example

```matlab
G = zpk(-1, [-2 -3], 5)
p = pole(G)
k = dcgain(G)
```

## See also

[tf](tf) · [zpkdata](zpkdata) · [pole](pole) · [zero](zero) · [pzmap](pzmap)
