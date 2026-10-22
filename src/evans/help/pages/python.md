# MATLAB and Python at the prompt

The console reads what you type as MATLAB, and runs a line as Python when only Python can mean it or only Python can read it.

## How a line is read

Every command goes to the MATLAB translator first, the same one the Script tab uses for `.m` files. A line goes to Python instead in two cases:

- It parses as Python and uses something MATLAB has no use for: it starts with `import`, `from`, `def`, `class`, `elif`, `with`, `lambda`, `async` or `await`; it is a block header such as `for k in range(3):` or `if x > 0:` ending in a colon; it contains `**`; or it calls `print(`.
- MATLAB cannot read it but Python can, as with indexing in square brackets, `y[0]`.

A line neither language reads is reported as an error in the language it looks like. Both languages share one workspace, so a variable made in MATLAB is there for Python on the next line, and the other way round.

    import math
    n = 2**10;
    y[0]
    for k in range(3): print(k)

Python indexes from 0 and MATLAB from 1, so with `y = [10 20 30]` both `y[0]` and `y(1)` give 10.

## np and ctl

numpy is in the workspace as `np` (and `numpy`), and the python-control library as `ctl` (and `control`). Their functions can be called from MATLAB lines too, so `np.logspace(-1, 2, 50)` or `ctl.dcgain(G)` work without switching languages. Use them for anything the MATLAB functions do not cover. A model built with [tf](tf), [ss](ss) or [zpk](zpk) is a python-control object, so `ctl` functions accept it directly.

## Semicolons and comments

In MATLAB lines, a trailing `;` suppresses the echo and `%` starts a comment, as in MATLAB.

Python lines keep two MATLAB habits. A trailing `;` is removed and taken to mean "do not echo the value". A `%` is read as the start of a comment only when the line does not already parse as Python, so `2**5 % 3` is still the modulo operator. The value of a bare expression on a Python line is echoed and stored in `ans`, as in MATLAB; an assignment on a Python line prints nothing.

## Example

```matlab
G = tf(1, [1 2 1]);
w = np.logspace(-1, 1, 3)
ctl.dcgain(G)
y = [10 20 30];
y(1)
```

## See also

[s](s) · [tf](tf) · [logspace](logspace) · [disp](disp)
