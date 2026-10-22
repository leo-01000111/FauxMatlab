# clc

Clear the command window: accepted in Evans, and does nothing.

## Syntax

    clc

## Description

In MATLAB, `clc` wipes the text in the command window. Evans accepts `clc` in scripts and at the prompt so that MATLAB scripts run unchanged, but the call itself leaves the console as it is.

To clear the console in Evans, press the **Clear** button beside the prompt. Running a script from the editor already clears the console before the script starts, so each run shows only its own output.

`clc` does not touch variables or figures. Use [clear](clear) for the workspace.

## Example

```matlab
clear
clc
G = tf(1, [1 2 1])
```

## See also

[clear](clear) · [disp](disp) · [figure](figure)
