# jury

Jury stability test of a discrete-time polynomial: are all its roots inside the unit circle?

## Syntax

    r = jury(den)
    r = jury(sysd)

## Description

`r = jury(den)` applies Jury's criterion to the polynomial with coefficients `den`, highest power first. It is the discrete counterpart of [routh](routh): it decides stability from the coefficients without computing the roots. A negative leading coefficient is handled by flipping every sign, which leaves the roots unchanged.

`r = jury(sysd)` tests the denominator of a discrete `tf` or `zpk` model, so the poles of `sysd` itself. Unlike `routh`, it does not form a closed loop: to test a feedback loop, pass the closed loop made with [feedback](feedback). A continuous model is an error, and a discrete state-space model is not accepted yet; convert it with `tf` first.

The result is a record with these fields:

- `stable`: true (1) when every condition holds.
- `conditions`: the checks made, each with its description, whether it passed and the value tested. The first three are the necessary conditions `a(1) > 0`, `(-1)^n a(-1) > 0` and `|a0| < an`; the rest come from the rows of the table.
- `table`: Jury's array, each row followed by its reverse.
- `n_outside`: how many roots lie on or outside the unit circle, computed from the roots as a cross-check.
- `notes`: a warning when the conditions and the roots disagree, which happens when a root sits very close to the unit circle.

At the prompt the whole record prints on one line. `jury` is not a MATLAB function.

## Example

```matlab
r = jury([1 -0.5 0.2]);
r.stable
Gd = c2d(tf(1, [1 1 0]), 0.5);
r = jury(Gd);
fprintf('stable: %d, roots outside: %d\n', r.stable, r.n_outside)
```

## See also

[routh](routh) · [c2d](c2d) · [pole](pole) · [isstable](isstable) · [roots](roots)
