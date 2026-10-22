# fprintf

Print formatted text to the console.

## Syntax

    fprintf(formatSpec)
    fprintf(formatSpec, A1, A2, ...)
    fprintf(1, formatSpec, A1, ...)

## Description

`fprintf(formatSpec, A1, A2, ...)` fills the conversions in `formatSpec` with the values that follow, in order, and prints the result. Nothing ends the line unless the format does, so finish with `\n`.

The conversions are the C ones:

- `%d` and `%i` for integers. A value that is not a whole number is printed with `%e` instead, as MATLAB does.
- `%f`, `%e` and `%g` for decimals, with an optional width and precision: `%8.3f` is 8 characters wide with 3 decimals.
- `%s` for text (a number given to `%s` is converted as [num2str](num2str) would), `%c` for one character.
- `%%` for a literal percent sign.

Flags `-`, `+`, space, `0` and `#` work as in C. The escapes `\n` (new line), `\t` (tab) and `\\` (backslash) are understood in the format.

Vector and matrix arguments are taken apart element by element, in column order, and the format is reused until every value is printed. So `fprintf('%6.2f\n', [1 2 3])` prints three lines. A complex value prints its real part only.

`fprintf(1, ...)` and `fprintf(2, ...)` print to the console as well. Evans has no `fopen`, so you cannot write to a file with `fprintf`. A width or precision given as `*` is not supported, and `fprintf` returns no byte count.

## Example

```matlab
G = tf(4, [1 2 4]);
S = stepinfo(G);
fprintf('Overshoot: %.1f %%\n', S.Overshoot)
fprintf('Settling time: %.2f s\n', S.SettlingTime)
```

```matlab
for Kp = [1 2 5]
    T = feedback(tf(Kp, [1 3 2]), 1);
    fprintf('Kp = %g, DC gain = %.3f\n', Kp, dcgain(T))
end
```

## See also

[sprintf](sprintf) · [disp](disp) · [num2str](num2str)
