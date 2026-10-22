# obsv

Observability matrix of a state-space model, `[C; C*A; C*A^2; ...; C*A^(n-1)]`.

## Syntax

    Ob = obsv(A, C)
    Ob = obsv(sys)

## Description

`Ob = obsv(A, C)` builds the observability matrix from the state matrix `A` (n by n) and the output matrix `C` (p by n). The result is n*p by n: the rows of `C`, then those of `C*A`, and so on up to `C*A^(n-1)`.

`Ob = obsv(sys)` takes `A` and `C` from a state-space model made with [ss](ss). A transfer function is not accepted; convert it first with `ss(G)`.

The pair is observable when `Ob` has full rank n, which `rank(Ob)` tells you. [isobsv](isobsv) gives the same verdict as a logical value. Observability of `(A, C)` is controllability of `(A', C')`, so `obsv(A, C)` equals `ctrb(A', C')'`.

## Example

```matlab
A = [0 1; -2 -3];
C = [1 0];
Ob = obsv(A, C)
rank(Ob)
```

## See also

[ctrb](ctrb) · [isobsv](isobsv) · [gram](gram) · [estim](estim) · [lqe](lqe)
