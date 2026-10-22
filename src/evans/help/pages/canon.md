# canon

Canonical state-space realisation of a model: modal, controllable (companion) or observable form.

## Syntax

    csys = canon(sys)
    csys = canon(sys, 'modal')
    csys = canon(sys, 'companion')
    csys = canon(sys, 'observable')

## Description

`csys = canon(sys)` and `canon(sys, 'modal')` return the modal form. `A` becomes block diagonal with one block per mode: a real eigenvalue gives a 1 by 1 block, and a complex pair `sigma ± j*omega` gives the 2 by 2 block `[sigma omega; -omega sigma]`. The states are then the modes, with no coupling between them. A defective `A` (a repeated eigenvalue without a full set of eigenvectors) has no modal form, and `canon` stops with an error.

`canon(sys, 'companion')` returns the controllable canonical form; `'controllable'` and `'reachable'` name the same form. The first row of `A` holds the negated coefficients of the characteristic polynomial, with ones on the subdiagonal. MATLAB's `'companion'` form puts the coefficients in the last column instead, so the matrices differ from MATLAB's by a reordering of the states.

`canon(sys, 'observable')` returns the observable canonical form, the dual of the controllable one: the coefficients sit in the first column of `A`.

`sys` must be a state-space model; convert a transfer function with `ss(G)`. Every form has the same transfer function as `sys`. Evans returns only the new model, without the transformation matrix, and any other form name is an error.

## Example

```matlab
sys = ss(tf(4, [1 2 4]));
m = canon(sys, 'modal');
m.A
c = canon(sys, 'companion');
c.A
```

## See also

[ss](ss) · [tf2ss](tf2ss) · [ctrb](ctrb) · [obsv](obsv) · [eig](eig)
