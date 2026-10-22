# ltiview

Open the LTI Viewer panel with one or more systems loaded, to compare their responses side by side.

## Syntax

    ltiview
    ltiview(sys)
    ltiview(sys1, sys2, ...)

## Description

`ltiview(sys)` opens the LTI Viewer docked beside the analysis workspace and adds `sys` to it. The viewer plots every loaded system on the same axes. You choose the response in the viewer (step, impulse, Bode and the others it lists) and which characteristics, such as peak response and settling time, are marked on the curves.

`ltiview(sys1, sys2, ...)` adds several systems at once. They are listed as `sys1`, `sys2` and so on, in the order given. Calling `ltiview` again adds to what is already loaded.

`ltiview` with no argument opens the viewer. If it has nothing loaded yet, it starts with the current loop from the analysis workspace: the plant G, the open loop L and the closed loop T.

The command returns a short description of the request, such as `<ltiview: sys1, sys2>`, which the console displays when the line has no semicolon. In a script run without the app nothing opens; the request is recorded and the line still runs. Evans does not take MATLAB's leading plot-type argument (`ltiview('step', G)`): choose the response in the viewer instead.

## Example

```matlab
G = tf(1, [1 3 3 1]);
C = pidtune(G, 'pi');
T = feedback(C*G, 1);
ltiview(G, T)
```

## See also

[step](step) · [bode](bode) · [sisotool](sisotool) · [pidtuner](pidtuner)
