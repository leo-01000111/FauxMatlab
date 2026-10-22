# lsim

Response of a dynamic system to an arbitrary input signal u(t), sampled on a time vector you supply.

## Syntax

    lsim(sys, u, t)
    lsim(sys, u, t, x0)
    y = lsim(sys, u, t, ...)
    [y, t] = lsim(sys, u, t, ...)

## Description

`lsim(sys, u, t)` simulates `sys` driven by the input samples `u` at the times `t` and plots the output together with the input (dashed). `sys` can be a `tf`, `zpk` or `ss` model. `t` must be an evenly spaced row vector starting at 0, and `u` a row vector of the same length: build both as rows, for example `t = 0:0.01:10; u = sin(t);`. Evans rejects column vectors here, where MATLAB accepts them.

`lsim(sys, u, t, x0)` starts from the initial state `x0` instead of from rest. The state is the one of a state-space model, so give `x0` with an `ss` model, one entry per state. A scalar `0` is accepted as zero initial state.

With output arguments nothing is drawn. `y` is the response as a column vector and `t` the matching time column.

For a discrete-time model the step of `t` must equal the sample time, and `u` is then the input sequence, one value per sample.

For the standard test inputs there are shorter commands: [step](step), [impulse](impulse) and [ramp](ramp). For the free response from an initial state with no input use [initial](initial).

## Example

```matlab
G = tf(1, [1 0.5 1]);
t = 0:0.01:20;
u = sin(0.8*t);
lsim(G, u, t)
y = lsim(G, u, t);
fprintf('Output amplitude near the end: %.3f\n', max(abs(y(end-800:end))))
```

## See also

[step](step) · [impulse](impulse) · [initial](initial) · [ramp](ramp) · [ss](ss)
