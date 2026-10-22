# num2str

Convert a number to text.

## Syntax

    str = num2str(x)
    str = num2str(x, precision)
    str = num2str(x, formatSpec)

## Description

`num2str(x)` writes a number as text with up to four digits after the decimal point (five significant digits for values below 1), dropping trailing zeros, so `num2str(pi)` is `'3.1416'` and `num2str(2.5)` is `'2.5'`. Whole numbers print without a decimal point, and large values keep all their integer digits. `NaN`, `Inf` and complex numbers are written the way MATLAB writes them (`'1+2i'`).

`num2str(x, precision)` uses at most `precision` significant digits: `num2str(pi, 8)` is `'3.1415927'`. `num2str(x, formatSpec)` formats with a [sprintf](sprintf) format, such as `'%10.5f'`.

Text passed to `num2str` comes back unchanged. A vector becomes one line of numbers separated by two spaces. A matrix in Evans also becomes a single line, with its rows one after the other, where MATLAB returns one line of text per row.

The usual use is joining a number into a message: `['Kp = ' num2str(Kp)]`.

## Example

```matlab
zeta = 0.42;
label = ['zeta = ' num2str(zeta)]
num2str(pi, 4)
```

## See also

[sprintf](sprintf) · [fprintf](fprintf) · [disp](disp)
