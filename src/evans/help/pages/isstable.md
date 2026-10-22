# isstable

Whether a model is asymptotically stable: true when every pole is in the stable region.

## Syntax

    isstable(sys)
    B = isstable(sys)

## Description

`isstable(sys)` returns logical 1 when the model is stable and 0 when it is not. For a continuous-time model every pole must have a strictly negative real part. For a discrete-time model every pole must lie strictly inside the unit circle.

A pole on the boundary counts as unstable, so an integrator `tf(1, [1 0])` gives 0. `sys` can be a `tf`, `zpk` or `ss` model. The test uses the poles of the model as given, so a pole cancelled by a zero still counts; run [minreal](minreal) first if that is not what you want.

To test a closed loop, form it first with [feedback](feedback). For how far a loop is from instability, use [margin](margin); for the stability test on the characteristic polynomial, [routh](routh).

## Example

```matlab
G = tf(1, [1 3 3 1]);
isstable(feedback(4*G, 1))
isstable(feedback(10*G, 1))
```

## See also

[pole](pole) · [routh](routh) · [margin](margin) · [feedback](feedback) · [minreal](minreal)
