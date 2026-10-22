# ctrb

Controllability matrix of a state-space model, `[B, A*B, A^2*B, ..., A^(n-1)*B]`.

## Syntax

    Co = ctrb(A, B)
    Co = ctrb(sys)

## Description

`Co = ctrb(A, B)` builds the controllability matrix from the state matrix `A` (n by n) and the input matrix `B` (n by m). The result is n by n*m: the columns of `B`, then those of `A*B`, and so on up to `A^(n-1)*B`.

`Co = ctrb(sys)` takes `A` and `B` from a state-space model made with [ss](ss). A transfer function is not accepted; convert it first with `ss(G)`.

The pair is controllable when `Co` has full rank n, which you can check with `rank(Co)`. For a yes or no answer that does not depend on a rank tolerance, use [isctrb](isctrb). On models of high order the matrix becomes badly scaled, because its columns grow like the powers of `A`.

## Example

```matlab
A = [0 1; -2 -3];
B = [0; 1];
Co = ctrb(A, B)
rank(Co)
```

## See also

[obsv](obsv) · [isctrb](isctrb) · [gram](gram) · [place](place) · [ss](ss)
