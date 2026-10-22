# clear

Remove variables from the workspace.

## Syntax

    clear
    clear all
    clear name1 name2 ...
    clear('name1', 'name2', ...)

## Description

`clear` on its own removes every variable from the workspace. `clear all`, `clear variables` and `clearvars` do the same. Functions defined in the running script are kept, so a script that starts with `clear` can still call its own local functions.

`clear G K` removes only the named variables and leaves the rest. The function form `clear('G', 'K')` is the same. A name that is not a variable is skipped without an error.

Scripts often begin with `clear` (and [clc](clc)) so that values left from an earlier run cannot leak into this one. `clear` does not close figures: use `close all` for that.

Evans matches names exactly. Wildcards such as `clear K*` and the `-regexp` option are not supported and remove nothing.

## Example

```matlab
Kp = 2; Ki = 0.5;
clear Ki
exist('Kp')
exist('Ki')
```

## See also

[clc](clc) · [figure](figure) · [tic](tic)
