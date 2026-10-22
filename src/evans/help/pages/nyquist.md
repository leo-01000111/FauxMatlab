# nyquist

Nyquist diagram of an open-loop transfer function, with the critical point -1 and the encirclement count that decides closed-loop stability.

## Syntax

    nyquist(sys)
    nyquist(sys, w)
    nyquist(sys, {wmin, wmax})
    nyquist(sys1, sys2, ...)
    [re, im, w] = nyquist(sys, ...)

## Description

`nyquist(sys)` plots `L(jω)` in the complex plane for a `tf`, `zpk` or `ss` model: the solid curve for positive frequencies, its mirror image for negative frequencies dashed. The point -1 is marked, and a dashed unit circle helps read gain crossover.

The title states the Nyquist count for closing the loop with unity negative feedback: `N` clockwise encirclements of -1 by the full contour, `P` open-loop poles in the right half-plane, and `Z = N + P` closed-loop poles in the right half-plane, with the verdict on closed-loop stability. Pass the loop transfer function `L = C*G`, and the count describes closing that loop.

`nyquist(sys, w)` evaluates the response at the frequencies in `w` (rad/s), and `nyquist(sys, {wmin, wmax})` at 500 logarithmically spaced points between the limits. `nyquist(sys1, sys2, ...)` overlays several systems.

With output arguments nothing is drawn. `re` and `im` are the real and imaginary parts of the response for positive frequencies and `w` the frequencies, all row vectors. Plot options from [nyquistoptions](nyquistoptions) are accepted and ignored for now.

## Example

```matlab
L = tf(4, [1 3 3 1]);
nyquist(L)
[re, im, w] = nyquist(L, {0.01, 100});
k = find(im(1:end-1) .* im(2:end) < 0, 1);
fprintf('Crosses the real axis at %.3f (w = %.3f rad/s)\n', re(k), w(k))
```

## See also

[bode](bode) · [margin](margin) · [nichols](nichols) · [feedback](feedback) · [nyquistoptions](nyquistoptions)
