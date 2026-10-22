# disp

Display a value without printing its variable name.

## Syntax

    disp(X)

## Description

`disp(X)` prints `X` the way the console shows it, minus the `X =` line. Text is printed as it is, without quotes. Numbers, vectors and matrices use the console's number format (short or long, see `format`), and models such as a [tf](tf) or [ss](ss) print their usual display. An empty array prints nothing.

To mix text and numbers on one line, join them into one piece of text first, with [num2str](num2str) or [sprintf](sprintf): `disp(['Kp = ' num2str(Kp)])`. For full control over the layout, use [fprintf](fprintf) instead.

`disp` returns nothing. Writing `x = disp(3)` prints 3 and leaves `x` empty, where MATLAB raises an error.

## Example

```matlab
G = tf(1, [1 3 2]);
T = feedback(G, 1);
disp('Closed-loop poles:')
disp(pole(T))
```

```matlab
zeta = 0.42;
disp(['Damping ratio: ' num2str(zeta)])
```

## See also

[fprintf](fprintf) · [sprintf](sprintf) · [num2str](num2str)
