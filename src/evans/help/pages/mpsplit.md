# mpsplit

Split a transfer function into an all-pass part and a minimum-phase part.

## Syntax

    mpsplit(G)
    [Gap, Gmp] = mpsplit(G)

## Description

`[Gap, Gmp] = mpsplit(G)` factors `G = Gap * Gmp`. Each zero of `G` in the right half-plane is mirrored into the left half-plane: `Gmp` takes the mirrored zero, and `Gap` gets the original zero over a pole at the mirrored position. `Gap` then has a gain of exactly 1 at every frequency, so `G` and `Gmp` have the same magnitude curve, and all the extra phase lag of `G` sits in `Gap`. The input can be a continuous `tf`, `zpk` or `ss` model; both results are transfer functions.

`mpsplit(G)` on its own prints a short explanation of what was mirrored, followed by both factors. With a single output, `x = mpsplit(G)`, you get that same pair, not `Gap` alone; ask for two outputs.

If `G` has no right half-plane zero it is already minimum phase, and `Gap` is 1.

Two details of the result. `Gmp` keeps the new zero and the matching pole uncancelled, so pass it through [minreal](minreal) for the reduced form. With an odd number of right half-plane zeros the sign goes to `Gmp`, which then has a negative gain. `mpsplit` is not a MATLAB function.

## Example

```matlab
s = tf('s');
G = (2 - s) / ((s + 1)*(s + 2));
mpsplit(G)
[Gap, Gmp] = mpsplit(G);
Gmp = minreal(Gmp)
```

## See also

[zero](zero) · [pzmap](pzmap) · [bode](bode) · [minreal](minreal) · [pade](pade)
