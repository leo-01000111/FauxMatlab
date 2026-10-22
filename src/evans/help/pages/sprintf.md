# sprintf

Format values into text and return it, without printing.

## Syntax

    str = sprintf(formatSpec, A1, A2, ...)

## Description

`sprintf` takes the same format and arguments as [fprintf](fprintf) and returns the text instead of printing it. The conversions (`%d`, `%f`, `%e`, `%g`, `%s`, `%c`, `%%`), the widths and precisions, the escapes such as `\n`, and the reuse of the format for vector arguments all work the same way.

Use it to build a plot title or legend entry that includes a number, or a label you print later with [disp](disp). For a single number with default formatting, [num2str](num2str) is shorter.

## Example

```matlab
s = sprintf('Kp = %.2f', 2.5)
```

```matlab
Kp = 4;
T = feedback(tf(Kp, [1 3 2]), 1);
step(T)
title(sprintf('Closed loop, Kp = %g', Kp))
```

## See also

[fprintf](fprintf) · [num2str](num2str) · [disp](disp) · [title](title) · [legend](legend)
