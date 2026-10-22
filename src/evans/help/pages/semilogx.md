# semilogx

Line plot with a logarithmic x axis and a linear y axis.

## Syntax

    semilogx(y)
    semilogx(x, y)
    semilogx(x, y, spec)
    semilogx(x1, y1, spec1, x2, y2, spec2, ...)

## Description

`semilogx` takes the same arguments as [plot](plot) and draws the same curves, with the x axis on a log scale. It is the usual way to draw a frequency response you have computed yourself, for example a magnitude in dB against frequency in rad/s. Space the frequencies evenly on the log scale with [logspace](logspace).

Points with `x` less than or equal to zero cannot be shown on a log axis and are left out of the drawing.

As with `plot`, only the line style of `spec` is used, and name-value pairs are ignored. With [hold](hold) on, several `semilogx` calls share the axes. For a transfer function, [bode](bode) does the whole job, phase included; `semilogx` is for when you have the numbers already, or want only one of the two curves.

## Example

```matlab
G = tf(10, [1 2 10]);
w = logspace(-1, 2, 300);
mag = abs(freqresp(G, w));
semilogx(w, 20*log10(mag)); xlabel('w (rad/s)'); ylabel('|G| (dB)')
```

## See also

[plot](plot) · [bode](bode) · [logspace](logspace) · [freqresp](freqresp) · [xlim](xlim)
