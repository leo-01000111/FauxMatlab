# routh

Routh-Hurwitz table of a polynomial, which tells how many of its roots lie in the right half-plane without computing them.

## Syntax

    r = routh(den)
    r = routh(L)

## Description

`r = routh(den)` builds the Routh array of the characteristic polynomial whose coefficients are in the vector `den`, highest power first. The first two rows hold the coefficients of alternate powers, and each further row is computed from the two above it. The number of sign changes down the first column is the number of roots with a positive real part.

`r = routh(L)` takes an open loop `L` (a `tf` or `zpk` model) and analyses the closed loop with unity negative feedback: the polynomial is the denominator plus the numerator of `L`, that is the numerator of `1 + L`. To test the poles of `L` itself, pass its denominator. A state-space model is not accepted.

The result is a record with these fields, which you read with a dot:

- `table`: the Routh array, one row per power of `s`, padded with zeros.
- `first_col`: the first column of the array.
- `n_sign_changes`, `n_rhp_poles`: the number of sign changes in the first column, which is the number of right half-plane roots.
- `stable`: true (1) when there is no sign change.
- `poly_coeffs`: the polynomial that was analysed.

At the prompt the whole record prints on one line. `routh` is not a MATLAB function.

The special cases are not handled yet. A zero in the first column with the rest of its row non-zero ends in an error. A whole row of zeros (roots on the imaginary axis, such as `s^3 + s^2 + s + 1`) is not detected: the zero is skipped and the polynomial can be reported as stable when it is only marginally stable. Check such cases with [roots](roots) or [pole](pole).

## Example

```matlab
r = routh([1 2 3 4 5]);
r.first_col
fprintf('%d roots in the right half-plane\n', r.n_rhp_poles)
L = zpk([], [0 -1 -2], 4);
r = routh(L);
r.stable
```

## See also

[jury](jury) · [pole](pole) · [roots](roots) · [isstable](isstable) · [rlocus](rlocus)
