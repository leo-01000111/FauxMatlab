# balred

Model reduction by balanced truncation: a state-space model of lower order that keeps the dominant dynamics.

## Syntax

    rsys = balred(sys, order)

## Description

`rsys = balred(sys, order)` balances `sys`, so that each state is equally controllable and observable, then keeps the `order` states with the largest Hankel singular values. The result is a state-space model with `order` states and the same `D` matrix.

Look at [hsvd](hsvd) first to choose `order`: a clear drop between two consecutive values is a good place to cut. The infinity-norm error of the reduced model is at most twice the sum of the singular values you discard.

`order` must be between 1 and the number of states of `sys`. The model must be a stable state-space model (convert a transfer function with `ss(G)`) and a minimal realisation. If some state is uncontrollable or unobservable, balancing would divide by a zero singular value, so `balred` stops with an error; call [minreal](minreal) first.

Evans returns only the reduced model, with no second output. Balanced truncation does not keep the DC gain exactly, so compare `dcgain(sys)` with `dcgain(rsys)` before you rely on the reduced model at low frequency.

## Example

```matlab
G = ss(tf(1, conv([1 1], conv([1 10], [1 20]))));
hsvd(G)
Gr = balred(G, 1);
dcgain(G)
dcgain(Gr)
```

## See also

[hsvd](hsvd) · [gram](gram) · [minreal](minreal) · [dcgain](dcgain) · [ss](ss)
