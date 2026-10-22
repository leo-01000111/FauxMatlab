# conv

Convolution of two vectors, which is polynomial multiplication when the vectors are coefficients.

## Syntax

    w = conv(u, v)
    w = conv(u, v, shape)

## Description

`conv(u, v)` returns the full convolution of `u` and `v`, of length `length(u) + length(v) - 1`. With coefficient vectors (highest power first) this is the product of the two polynomials: `conv([1 1], [1 2])` is `[1 3 2]`, that is (s+1)(s+2) = s^2 + 3s + 2. Use it to build a denominator from factors before calling [tf](tf).

`shape` picks part of the result: `'full'` (the default), `'same'` (the central part, as long as `u`), or `'valid'` (only the samples computed without zero padding).

The result is a row vector unless the longer input is a column vector (for `'same'`, unless `u` is). `conv` works on numeric vectors only; to multiply models use `*` or [series](series).

## Example

```matlab
den = conv([1 1], conv([1 2], [1 5]))
G = tf(10, den)
```

## See also

[poly](poly) · [roots](roots) · [tf](tf) · [series](series) · [polyval](polyval)
