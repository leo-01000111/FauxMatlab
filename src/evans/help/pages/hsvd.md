# hsvd

Hankel singular values of a stable state-space model, largest first.

## Syntax

    hsv = hsvd(sys)

## Description

`hsv = hsvd(sys)` returns the Hankel singular values, the square roots of the eigenvalues of `Wc*Wo`, where `Wc` and `Wo` are the controllability and observability Gramians from [gram](gram). They come back as a row vector in decreasing order.

Each value measures how much one state of the balanced realisation contributes to the input/output behaviour. A value much smaller than the others marks a state that [balred](balred) can delete at little cost: the infinity-norm error of the truncation is at most twice the sum of the discarded values.

`sys` must be a stable state-space model; convert a transfer function with `ss(G)`. MATLAB returns a column vector and plots the values when called without outputs; Evans returns a row vector and draws nothing.

## Example

```matlab
G = ss(tf(1, conv([1 1], conv([1 10], [1 20]))));
hsv = hsvd(G)
```

## See also

[balred](balred) · [gram](gram) · [minreal](minreal) · [ss](ss)
