# pidtuner

Open the PID Tuner panel on a plant, with one slider for response time, one for transient behaviour, and a readout of what each asks for.

## Syntax

    pidtuner
    pidtuner(G)
    pidtuner(G, type)

## Description

`pidtuner(G)` opens the PID Tuner docked beside the analysis workspace, with `G` as the plant and a PI controller. `pidtuner(G, type)` starts with another controller type: `'P'`, `'PI'`, `'PD'` or `'PID'`, in either case.

The sliders set the targets [pidtune](pidtune) takes as numbers. The response-time slider sets the target crossover frequency and the transient slider sets the target phase margin, from an aggressive, lightly damped loop to a cautious, well-damped one. The panel prints which crossover and margin were asked for and which were achieved, and when a target cannot be met it says why. It plots the closed-loop step response of the tuned design against the controller already in the loop.

The tuner works on the app's shared loop: the sensor H, the feedforward K1 and the current controller K2 come from the analysis workspace, and applying the design writes the new controller into K2.

`pidtuner` with no argument opens the tuner on the plant G of the current analysis workspace. If the tuner is already open, `pidtuner(G)` replaces its plant but keeps the controller type chosen in the panel.

The command returns a short description of the request, such as `<pidtuner: plant>`. In a script run without the app nothing opens; the request is recorded and the line still runs. Evans does not check `type` at the console, so a misspelt type only shows up as an error when the panel opens.

## Example

```matlab
G = tf(1, [1 3 3 1]);
pidtuner(G, 'pid')
```

## See also

[pidtune](pidtune) · [pid](pid) · [sisotool](sisotool) · [ltiview](ltiview)
