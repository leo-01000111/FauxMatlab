# eye

Identity matrix: ones on the main diagonal, zeros elsewhere.

## Syntax

    I = eye(n)
    I = eye(m, n)
    I = eye([m n])

## Description

`eye(n)` is the n-by-n identity matrix. `eye(m, n)` and `eye([m n])` give an m-by-n matrix with ones on the main diagonal and zeros elsewhere. `eye(1)` and `eye` with no argument are the scalar 1.

In control work it shows up as the output matrix `C = eye(n)` when every state is measured, as the state weight `Q` of [lqr](lqr), and in expressions such as `s*eye(n) - A`.

## Example

```matlab
A = [0 1; -2 -3];
B = [0; 1];
sys = ss(A, B, eye(2), zeros(2, 1));
K = lqr(sys, eye(2), 1)
```

## See also

[zeros](zeros) · [ones](ones) · [ss](ss) · [lqr](lqr) · [inv](inv)
